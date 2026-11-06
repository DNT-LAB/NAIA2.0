"""Focused regression tests for generic agent discovery and reply protocol."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.agent_catalog import audit, describe, runtime_catalog, source_catalog
from core.agent_protocol import AgentReplySocket, CALL_ID_KEY, sanitize


def write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class SourceDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_new_routes_modules_services_and_actions_are_discovered_from_source(self):
        write(self.root, "app/backend/server/new_routes.py", '''
from fastapi import APIRouter
router = APIRouter()
@router.post("/api/new/dispatch")
async def dispatch(request):
    """Accept a new route without editing a registry."""
    payload = request.get("payload")
    mode = payload.get("mode", "safe")
    return {"mode": mode}
''')
        write(self.root, "core/headless_service_registry.py", '''
class HeadlessServiceSpec:
    def __init__(self, module, cls):
        self.module, self.cls = module, cls
SERVICES = {"luna": HeadlessServiceSpec("core.services.luna", "LunaService")}
''')
        write(self.root, "core/web_session_context.py", '''
class WebSessionContext:
    def luna_service(self):
        return self._lazy_service("luna")
    def _lazy_service(self, name):
        return name
''')
        write(self.root, "core/services/luna.py", '''
class LunaService:
    def set_param(self, key, value):
        return self._set_param_locked(key, value)
    def _set_param_locked(self, key, value):
        if key == "wrapped_action":
            return value
''')
        write(self.root, "core/headless_module_dispatch_service.py", '''
class ModuleDispatch:
    def set_module_param(self, context, clean_id, payload):
        if clean_id == "new_module":
            return context.luna_service().set_param(payload)
''')
        write(self.root, "app/backend/server/websocket_session.py", '''
MODULE_COMMAND_TYPES = {"get_module_state", "set_module_param"}
async def _dispatch_json_command(command):
    if command.get("type") in MODULE_COMMAND_TYPES:
        return None
''')

        catalog = source_catalog(self.root)
        route = catalog["entries"]["http:POST:/api/new/dispatch"]
        self.assertEqual(route["availability"], "source_declared; runtime_registration_unverified")
        self.assertTrue(any(hint["object"] == "request" and hint["key"] == "payload"
                            and hint["required"] == "unknown" for hint in route["input_hints"]))
        module = catalog["entries"]["module:new_module:set"]
        self.assertEqual(module["transport"]["command"]["type"], "set_module_param")
        self.assertIn("actions", module, module)
        self.assertEqual(module["actions"]["literal_keys"], ["wrapped_action"])
        self.assertIn("service:luna", module["related"])
        self.assertEqual(module["implementation"]["method"], "set_param")
        self.assertNotIn("python:core.services.luna:LunaService._set_param_locked", catalog["entries"])

    def test_openapi_drift_and_source_only_symbols_do_not_reflect_into_callables(self):
        write(self.root, "app/backend/server/routes.py", '''
@router.get("/api/source-only")
async def source_only():
    return {}

def public_helper(secret=None):
    return secret
''')
        source = source_catalog(self.root)
        runtime = runtime_catalog(source, {"paths": {
            "/api/source-only": {"get": {"operationId": "registered_source_route"}},
            "/api/runtime-only": {"post": {"operationId": "runtime_added_route"}},
        }, "components": {"schemas": {"Request": {"type": "object"}}}})

        self.assertTrue(runtime["entries"]["http:GET:/api/source-only"]["callable"])
        self.assertEqual(runtime["entries"]["http:GET:/api/source-only"]["availability"], "runtime_registered")
        self.assertTrue(runtime["entries"]["http:POST:/api/runtime-only"]["callable"])
        helper = runtime["entries"]["python:app.backend.server.routes:public_helper"]
        self.assertFalse(helper["callable"])
        self.assertEqual(helper["availability"], "source_only")
        self.assertEqual(audit(runtime)["gaps"]["runtime_routes_without_source"], ["http:POST:/api/runtime-only"])

    def test_parse_failures_frontend_only_and_module_gaps_are_reported(self):
        write(self.root, "app/backend/server/broken.py", "def broken(:\n    pass\n")
        write(self.root, "app/web/remote/calls.js", '''
setModuleParam("missing_module", "missing_action", value);
fetch("/api/not-implemented");
''')
        write(self.root, "app/backend/server/websocket_session.py", '''
async def _dispatch_json_command(command):
    if command.get("type") in EMPTY_COMMAND_TYPES:
        return None
EMPTY_COMMAND_TYPES = set()
''')
        catalog = source_catalog(self.root)
        report = audit(catalog)
        self.assertIn("app/backend/server/broken.py", [issue["file"] for issue in report["gaps"]["scan_issues"]])
        self.assertIn("/api/not-implemented", [ref["path"] for ref in catalog["frontend_references"]])
        self.assertTrue(any(item["kind"] == "frontend" for item in catalog["entries"].values()))
        self.assertTrue(report["gaps"]["frontend_routes_unresolved"])
        self.assertTrue(report["gaps"]["module_action_schema_unresolved"] or
                        report["gaps"]["frontend_module_calls_unresolved"])

    def test_input_hints_are_explicitly_not_a_complete_schema(self):
        write(self.root, "app/backend/server/hints.py", '''
@router.post("/api/hints")
async def hints(payload):
    one = payload.get("known", 3)
    two = payload["also_known"]
    return {"one": one, "two": two}
''')
        entry = source_catalog(self.root)["entries"]["http:POST:/api/hints"]
        self.assertEqual(entry["schema_status"], "source_hints_only")
        self.assertTrue(entry["input_hints"])
        self.assertTrue(all(hint["required"] == "unknown" for hint in entry["input_hints"]))
        description = describe(source_catalog(self.root), entry["id"])
        self.assertNotIn("json_schema", description)

    def test_converted_path_route_merges_with_openapi_and_describes_source_path_placeholder(self):
        write(self.root, "app/backend/server/viewer_routes.py", '''
@router.get("/api/viewer/{path:path}")
async def view_path(path):
    return {"path": path}
''')
        source = source_catalog(self.root)
        source_id = "http:GET:/api/viewer/{path:path}"
        source_description = describe(source, source_id)
        self.assertEqual(source_description["call_input_example"]["path"], {"path": "<required>"})

        runtime = runtime_catalog(source, {"paths": {
            "/api/viewer/{path}": {"get": {"operationId": "view_path"}},
        }})
        self.assertIn(source_id, runtime["entries"])
        self.assertEqual(runtime["entries"][source_id]["transport"]["path"],
                         "/api/viewer/{path:path}")
        report = audit(runtime)
        self.assertEqual(report["gaps"]["source_routes_not_registered"], [])
        self.assertEqual(report["gaps"]["runtime_routes_without_source"], [])

    def test_tools_frontend_references_are_development_evidence_not_route_gaps(self):
        write(self.root, "tools/route_probe.js", '''
fetch("/api/tooling-only-route");
''')
        catalog = source_catalog(self.root)
        self.assertIn("/api/tooling-only-route",
                      [ref["path"] for ref in catalog["development_frontend_references"]])
        self.assertNotIn("/api/tooling-only-route",
                         [ref["path"] for ref in audit(catalog)["gaps"]["frontend_routes_unresolved"]])

    def test_hidden_api_route_is_runtime_capability_without_openapi_schema(self):
        from fastapi import FastAPI

        app = FastAPI()

        @app.get("/api/hidden-capability", include_in_schema=False)
        async def hidden_capability():
            return {"ok": True}

        source = source_catalog(self.root)
        runtime = runtime_catalog(source, app.openapi(), routes=app.routes)
        identifier = "http:GET:/api/hidden-capability"
        entry = runtime["entries"][identifier]
        self.assertTrue(entry["callable"])
        self.assertEqual(entry["availability"], "runtime_registered")
        self.assertEqual(entry["schema_status"], "runtime_route_without_openapi")
        self.assertEqual(entry["transport"]["path"], "/api/hidden-capability")


class AgentProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_directed_reply_is_correlated_and_broadcast_is_untagged(self):
        class Socket:
            def __init__(self):
                self.sent = []
                self._search_session_id = "search-session-7"

            async def send_text(self, text):
                self.sent.append(json.loads(text))

        socket = Socket()
        context = SimpleNamespace(secure_token_manager=None)
        command = {"type": "set_module_param", "key": "access_token", "value": "shh-token"}
        reply = AgentReplySocket(socket, "call_42", context, command)
        self.assertEqual(reply._search_session_id, "search-session-7")
        await reply.send_json({"type": "module_state", "value": "shh-token"})
        broadcast = {"type": "generation_progress", "progress": 0.5}
        # The shared broadcast path receives its original object, not the wrapper's tagged reply.
        recorded_broadcast = broadcast
        self.assertNotIn(CALL_ID_KEY, recorded_broadcast)
        self.assertEqual(socket.sent[0][CALL_ID_KEY], "call_42")
        self.assertEqual(socket.sent[0]["value"], "[REDACTED]")
        self.assertEqual(sanitize({"modules": {"private_module_key": "token-value",
                                                "session_token": "abc"}}),
                         {"modules": {"private_module_key": "token-value",
                                       "session_token": "[REDACTED]"}})
        # A generic module's key name can carry a credential even when the key itself is not sensitive.
        self.assertEqual(sanitize({"value": "secret-token"}, ["secret-token"])["value"], "[REDACTED]")

    async def test_websocket_wrapper_dispatches_existing_handler_and_ack_is_not_generation_completion(self):
        from app.backend.server import websocket_session

        class Socket:
            def __init__(self):
                self.sent = []
                self._search_session_id = "search-session-3"

            async def send_text(self, text):
                self.sent.append(json.loads(text))

        socket = Socket()
        command = {"type": "generate", CALL_ID_KEY: "req-9"}
        context = SimpleNamespace(secure_token_manager=None)
        run_in_thread, start_generation_runner = object(), object()
        broadcast_messages = []
        def broadcast_json(payload):
            broadcast_messages.append(payload)

        async def mocked_impl(ws, ctx, clients, host, received, **kwargs):
            self.assertIsInstance(ws, AgentReplySocket)
            self.assertEqual(ws._search_session_id, "search-session-3")
            self.assertNotIn(CALL_ID_KEY, received)
            self.assertEqual(received, dispatched_command)
            self.assertIs(kwargs["run_in_thread"], run_in_thread)
            self.assertIs(kwargs["broadcast_json"], broadcast_json)
            shared = {"type": "generation_progress", "progress": 0.25}
            kwargs["broadcast_json"](shared)
            self.assertNotIn(CALL_ID_KEY, shared)
            await ws.send_json({"type": "accepted", "status": "queued"})

        dispatched_command = {"type": "generate"}
        async def handler(*args, **kwargs):
            return await websocket_session.handle_json_command(*args, **kwargs)

        with patch.object(websocket_session, "_handle_json_command_impl", mocked_impl):
            await handler(socket, context, set(), "host", command,
                          run_in_thread=run_in_thread, broadcast_json=broadcast_json,
                          start_generation_runner=start_generation_runner)

        self.assertEqual([item["type"] for item in socket.sent], ["accepted", "agent_dispatch_complete"])
        self.assertTrue(socket.sent[-1]["dispatch_complete"])
        self.assertFalse(socket.sent[-1]["operation_complete"])
        self.assertNotIn("generation_complete", [item["type"] for item in socket.sent])
        self.assertEqual([item[CALL_ID_KEY] for item in socket.sent], ["req-9", "req-9"])
        self.assertEqual(broadcast_messages, [{"type": "generation_progress", "progress": 0.25}])

    async def test_wrapper_acknowledges_handler_error_and_cancellation(self):
        from app.backend.server import websocket_session

        class Socket:
            def __init__(self):
                self.sent = []

            async def send_text(self, text):
                self.sent.append(json.loads(text))

        async def invoke(impl):
            socket = Socket()
            with patch.object(websocket_session, "_handle_json_command_impl", impl):
                await websocket_session.handle_json_command(
                    socket, SimpleNamespace(secure_token_manager=None), set(), "host",
                    {"type": "module_action", CALL_ID_KEY: "call-1"}, run_in_thread=None,
                    broadcast_json=None, start_generation_runner=None)
            self.assertEqual(socket.sent[-1]["type"], "agent_dispatch_complete")
            self.assertFalse(socket.sent[-1]["operation_complete"])
            self.assertTrue(socket.sent[-1]["error"])
            self.assertNotIn("generation_complete", [item["type"] for item in socket.sent])
            return socket.sent

        async def fail(*args, **kwargs):
            raise RuntimeError("dispatch failed")

        errors = await invoke(fail)
        self.assertIn("dispatch failed", errors[-1]["error"])

        async def cancel(*args, **kwargs):
            raise asyncio.CancelledError()

        socket = Socket()
        with patch.object(websocket_session, "_handle_json_command_impl", cancel):
            with self.assertRaises(asyncio.CancelledError):
                await websocket_session.handle_json_command(
                    socket, SimpleNamespace(secure_token_manager=None), set(), "host",
                    {"type": "module_action", CALL_ID_KEY: "call-2"}, run_in_thread=None,
                    broadcast_json=None, start_generation_runner=None)
        ack = socket.sent[-1]
        self.assertEqual(ack["type"], "agent_dispatch_complete")
        self.assertFalse(ack["operation_complete"])
        self.assertIn("cancelled", ack["error"])
        self.assertEqual(ack[CALL_ID_KEY], "call-2")


if __name__ == "__main__":
    unittest.main()
