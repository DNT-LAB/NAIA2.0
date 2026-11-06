"""Focused transport and CLI discovery regression tests (no live backend)."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import queue
import threading
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.agent_client import AgentCallError, AgentClient, run_discovery_command
from core.agent_protocol import ACK_TYPE, CALL_ID_KEY
from core import agent_cli


class Response:
    def __init__(self, status=200, body=None, content=b"", content_type="application/json"):
        self.status_code = status
        self._body = body
        self.content = content
        self.headers = {"Content-Type": content_type}
        self.ok = 200 <= status < 300

    def json(self):
        if self._body is None:
            raise ValueError("not JSON")
        return self._body


class AgentClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agent-client-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.session = Mock()
        self.session.trust_env = True
        self.session.request.return_value = Response(body={"ok": True})
        self.session.close = Mock()
        self.session.request = Mock(return_value=Response(body={"ok": True}))
        self.session_patch = patch("requests.Session", return_value=self.session)
        self.session_patch.start()
        self.addCleanup(self.session_patch.stop)
        self.client = AgentClient(self.root, "http://localhost:7243", timeout=3)
        self.addCleanup(self.client.close)

    @staticmethod
    def http_entry(path="/api/items/{item_id}", method="POST"):
        return {"id": f"http:{method}:{path}", "callable": True,
                "transport": {"type": "http", "method": method, "path": path}}

    def describe_as(self, entry):
        self.client.describe = Mock(return_value=entry)

    def test_http_call_encodes_path_and_forwards_query_json_and_headers(self):
        self.describe_as(self.http_entry())
        self.session.request.return_value = Response(body={"saved": True})

        result = self.client.call("http:POST:/api/items/{item_id}", {
            "path": {"item_id": "a/b ?"}, "query": {"limit": 4, "tag": ["one", "two"]},
            "json": {"nested": [1, {"ok": True}]}, "headers": {"X-Trace": "trace-1"},
        })

        self.assertEqual(result["response"], {"saved": True})
        self.session.request.assert_called_once_with(
            "POST", "http://localhost:7243/api/items/a%2Fb%20%3F", timeout=3,
            allow_redirects=False,
            params={"limit": 4, "tag": ["one", "two"]},
            headers={"X-Trace": "trace-1"}, json={"nested": [1, {"ok": True}]})
        self.assertFalse(self.session.trust_env)

    def test_body_file_sends_raw_bytes_and_declared_content_type(self):
        body = self.root / "payload.bin"
        body.write_bytes(b"\x00\xffraw-body")
        self.describe_as(self.http_entry("/api/upload", "PUT"))
        self.session.request.return_value = Response(body={"accepted": True})

        self.client.call("http:PUT:/api/upload", {
            "body_file": str(body), "content_type": "application/x-fixture",
        })

        kwargs = self.session.request.call_args.kwargs
        self.assertEqual(kwargs["data"], b"\x00\xffraw-body")
        self.assertEqual(kwargs["headers"], {"Content-Type": "application/x-fixture"})
        self.assertNotIn("json", kwargs)

    def test_rejects_unknown_sections_bad_shapes_missing_and_extra_path_values(self):
        self.describe_as(self.http_entry())
        invalid = [
            ({"raw": "not allowed"}, "Unknown HTTP input sections"),
            ({"query": []}, "must be objects"),
            ({"path": {}}, "Missing path parameter"),
            ({"path": {"item_id": "x", "other": "y"}}, "Unknown path parameters"),
            ({"path": {"item_id": "x"}, "json": {}, "body_file": "missing.bin"}, "mutually exclusive"),
        ]
        for payload, expected in invalid:
            with self.subTest(payload=payload):
                with self.assertRaises(AgentCallError) as caught:
                    self.client.call("id", payload)
                self.assertEqual(caught.exception.code, "invalid_request")
                self.assertIn(expected, str(caught.exception))
        self.session.request.assert_not_called()

    def test_unknown_and_non_callable_capabilities_are_rejected_before_transport(self):
        self.client.describe = Mock(side_effect=ValueError("Unknown capability: missing"))
        with self.assertRaisesRegex(ValueError, "Unknown capability"):
            self.client.call("missing")

        self.describe_as({"id": "source:only", "callable": False,
                          "availability": "source_only", "related": ["http:GET:/api/x"]})
        with self.assertRaises(AgentCallError) as caught:
            self.client.call("source:only")
        self.assertEqual(caught.exception.code, "not_callable")
        self.assertEqual(caught.exception.details["related"], ["http:GET:/api/x"])
        self.session.request.assert_not_called()

    def test_binary_output_is_written_once_and_existing_file_is_preserved(self):
        self.describe_as(self.http_entry("/api/image", "GET"))
        binary = b"\x89PNG\r\nfixture"
        self.session.request.return_value = Response(content=binary, content_type="image/png")
        target = self.root / "result.png"
        result = self.client.call("image", output=str(target))
        self.assertEqual(target.read_bytes(), binary)
        self.assertEqual(result["response"], {"bytes": len(binary), "binary": True})
        self.assertEqual(result["output"], str(target.resolve()))

        target.write_bytes(b"keep-me")
        self.session.request.reset_mock()
        with self.assertRaises(AgentCallError) as caught:
            self.client.call("image", output=str(target))
        self.assertEqual(caught.exception.code, "output_exists")
        self.assertEqual(target.read_bytes(), b"keep-me")
        self.session.request.assert_not_called()

    def test_http_error_includes_operation_context(self):
        self.describe_as(self.http_entry("/api/update", "PATCH"))
        self.session.request.return_value = Response(503, {"reason": "busy"})
        with self.assertRaises(AgentCallError) as caught:
            self.client.call("update", {"json": {"x": 1}})
        self.assertIn("HTTP 503", str(caught.exception))
        self.assertEqual(caught.exception.details["http_status"], 503)
        self.assertEqual(caught.exception.details["id"], "http:PATCH:/api/update")

    def test_remote_overview_uses_catalog_overview_view(self):
        overview = {"counts": {"callable": 2}, "entries": []}
        self.session.request.return_value = Response(body=overview)

        self.assertEqual(self.client.overview(), overview)
        self.session.request.assert_called_once_with(
            "GET", "http://localhost:7243/api/agent/catalog", timeout=3,
            allow_redirects=False, params={"view": "overview"})

    def test_response_secrets_are_sanitized(self):
        secret = "credential-fixture-731"
        self.describe_as(self.http_entry("/api/echo", "POST"))
        self.session.request.return_value = Response(body={"echo": secret})
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            result = self.client.call("echo", {"json": {"token": secret}})
        self.assertEqual(result["response"]["echo"], "[REDACTED]")
        self.assertNotIn(secret, json.dumps(result))


class WebSocketClientTests(unittest.TestCase):
    setUp = AgentClientTests.setUp
    describe_as = AgentClientTests.describe_as
    http_entry = AgentClientTests.http_entry

    def setUp(self):
        AgentClientTests.setUp(self)
        self.client.protocol_available = True
        self.entry = {"id": "ws:generate", "kind": "service", "callable": True,
                      "transport": {"type": "websocket", "command": {"type": "generate"}}}
        self.client.describe = Mock(return_value=self.entry)
        self.socket = Mock()
        self.client.socket = self.socket

    def test_correlated_events_are_separate_from_broadcasts(self):
        frames = []
        initialized = False
        def recv():
            nonlocal initialized
            if not initialized:
                initialized = True
                sent = json.loads(self.socket.send.call_args.args[0])
                call_id = sent[CALL_ID_KEY]
                frames.extend([
                    {"type": "other", CALL_ID_KEY: "another-call", "value": "broadcast-before-ack"},
                    {"type": ACK_TYPE, CALL_ID_KEY: call_id},
                    {"type": "progress", CALL_ID_KEY: call_id, "value": 1},
                    {"type": "progress", CALL_ID_KEY: "another-call", "value": 2},
                ])
            return json.dumps(frames.pop(0)) if frames else ""
        self.socket.recv.side_effect = recv

        result = self.client.call("ws:generate", {"prompt": "fixture"}, observe=0.01)

        self.assertTrue(result["dispatch_complete"])
        self.assertEqual(result["messages"], [{"type": "progress", CALL_ID_KEY: result["call_id"], "value": 1}])
        self.assertEqual(result["observed_broadcasts"], [
            {"type": "progress", CALL_ID_KEY: "another-call", "value": 2}])
        sent = json.loads(self.socket.send.call_args.args[0])
        self.assertEqual(sent["type"], "generate")
        self.assertEqual(sent["prompt"], "fixture")
        self.assertEqual(sent[CALL_ID_KEY], result["call_id"])

    def test_selector_and_internal_fields_cannot_be_overridden(self):
        for payload in ({"type": "other"}, {"_agent_call_id": "fake"}, {"_seq": 7}):
            with self.subTest(payload=payload):
                with self.assertRaises(AgentCallError) as caught:
                    self.client.call("ws:generate", payload)
                self.assertEqual(caught.exception.code, "invalid_request")
        self.socket.send.assert_not_called()

    def test_timeout_reports_uncertain_execution_and_does_not_retry(self):
        import websocket
        self.socket.recv.side_effect = websocket.WebSocketTimeoutException("timeout")
        with patch("core.agent_client.time.monotonic", side_effect=[0, 0, 4]):
            with self.assertRaises(AgentCallError) as caught:
                self.client.call("ws:generate", {"prompt": "possibly-submitted"})
        self.assertEqual(caught.exception.code, "dispatch_timeout")
        self.assertIn("may have executed", str(caught.exception))
        self.assertEqual(self.socket.send.call_count, 1)

    def test_module_batch_reuses_socket_and_stops_at_first_failed_call(self):
        from types import SimpleNamespace
        entries = {
            "ws:first": {"id": "ws:first", "kind": "service", "callable": True,
                         "transport": {"type": "websocket", "command": {"type": "first"}}},
            "ws:bad": {"id": "ws:bad", "kind": "service", "callable": False,
                       "transport": {"type": "websocket", "command": {"type": "bad"}}},
            "ws:last": {"id": "ws:last", "kind": "service", "callable": True,
                         "transport": {"type": "websocket", "command": {"type": "last"}}},
        }
        socket = Mock()
        last_sent = {}
        responses = queue.Queue()
        def send(raw):
            last_sent.clear()
            last_sent.update(json.loads(raw))
            responses.put(json.dumps({"type": ACK_TYPE, CALL_ID_KEY: last_sent[CALL_ID_KEY]}))
        socket.send.side_effect = send
        def recv():
            try:
                return responses.get(timeout=.05)
            except queue.Empty:
                import websocket
                raise websocket.WebSocketTimeoutException()
        socket.recv.side_effect = recv
        socket.settimeout = Mock()
        socket.close = Mock()
        http = Mock()
        http.close = Mock()
        def initialize(client, root, server="http://127.0.0.1:7243", timeout=60):
            client.root, client.server, client.timeout = Path(root), server.rstrip("/"), timeout
            client.http, client.socket = http, None
            client.secrets, client.protocol_available = [], True
            client.fallback, client._descriptions = None, {}
            client._reader, client._reader_stop = None, threading.Event()
            client._frames, client._dropped_frames = queue.Queue(maxsize=512), 0
        args = SimpleNamespace(command="batch", server="http://localhost:7243", timeout=1,
                               input=json.dumps([{"id": "ws:first"}, {"id": "ws:last"}, {"id": "ws:bad"}]), observe=0)
        with patch.object(AgentClient, "__init__", initialize), \
                patch.object(AgentClient, "describe", side_effect=lambda identifier: entries[identifier]), \
                patch("websocket.create_connection", return_value=socket) as connect:
            with self.assertRaises(AgentCallError) as caught:
                run_discovery_command(args, self.root, [])
        self.assertEqual(caught.exception.code, "not_callable")
        self.assertEqual(len(caught.exception.details["completed"]), 2)
        self.assertEqual(socket.send.call_count, 2)
        connect.assert_called_once_with("ws://localhost:7243/ws", timeout=1, http_no_proxy=["localhost"])
        socket.close.assert_called_once()
        http.close.assert_called_once()


class AgentCliDiscoveryTests(unittest.TestCase):
    def test_capabilities_defaults_to_overview(self):
        args = agent_cli.parse_args(["capabilities"])
        self.assertEqual(args.command, "capabilities")
        self.assertEqual(args.action, "overview")

    def test_json_run_preserves_nested_call_and_batch_input(self):
        call_payload = {"path": {"id": "x"}, "json": {"nested": [1, {"value": True}]}}
        batch_payload = [{"id": "ws:one", "input": {"nested": {"list": ["a", "b"]}}}]
        with tempfile.TemporaryDirectory(prefix="agent-cli-run-") as temporary:
            call_file, batch_file = Path(temporary) / "call.json", Path(temporary) / "batch.json"
            call_file.write_text(json.dumps({"command": "call", "capability": "http:POST:/api/x",
                                             "input": call_payload}), encoding="utf-8")
            batch_file.write_text(json.dumps({"command": "batch", "input": batch_payload}), encoding="utf-8")
            parsed_call = agent_cli.parse_args(["run", str(call_file)])
            parsed_batch = agent_cli.parse_args(["run", str(batch_file)])
        from core.agent_client import read_input
        self.assertEqual(read_input(parsed_call.input), call_payload)
        self.assertEqual(read_input(parsed_batch.input), batch_payload)

    def test_json_run_discovery_dispatch_uses_batch_one_client_and_redacts_errors(self):
        secret = "cli-discovery-secret-994"
        with tempfile.TemporaryDirectory(prefix="agent-cli-discovery-") as temporary:
            request_file = Path(temporary) / "request.json"
            request_file.write_text(json.dumps({
                "command": "batch", "input": [{"id": "http:POST:/api/x",
                                                  "input": {"json": {"token": secret}}}],
                "server": "http://localhost:7243",
            }), encoding="utf-8")
            fake = Mock()
            fake.secrets = [secret]
            fake.call.return_value = {"transport": "http", "response": "[REDACTED]"}
            fake.close = Mock()
            with patch("core.agent_client.AgentClient", return_value=fake) as factory:
                stdout, stderr = io.StringIO(), io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = agent_cli.main(["run", str(request_file)])
        self.assertEqual(code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertNotIn(secret, stdout.getvalue())
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"])
        fake.call.assert_called_once_with("http:POST:/api/x", {"json": {"token": secret}}, output=None, observe=0.0)
        fake.close.assert_called_once()
        factory.assert_called_once()


if __name__ == "__main__":
    unittest.main()
