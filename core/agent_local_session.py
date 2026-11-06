"""Command-scoped headless runtime for the generic agent client.

The existing HTTP/WS routes run unchanged behind a loopback-only ephemeral
transport. No Electron, browser, external running server, or extra dependency
is required. Settings use the existing CLI's private workspace.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager
import socket
import threading
import time


@contextmanager
def local_agent_client(args, root, secrets):
    import uvicorn
    from core.agent_cli import isolated_session
    from core.agent_client import AgentCallError, AgentClient
    from core.web_session_app import create_headless_app

    if not 0 < args.timeout <= 3600:
        raise AgentCallError("--timeout must be in (0, 3600]", code="invalid_arguments")
    with isolated_session(args, secrets) as (context, source):
        app = create_headless_app(context)

        @asynccontextmanager
        async def command_lifespan(_app):
            # CLI work is explicit: no GUI startup sweep, automatic downloads,
            # account polling, or background random-prompt warmup on entry.
            context.headless_main_loop = asyncio.get_running_loop()
            yield

        app.router.lifespan_context = command_lifespan
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(
            app, host="127.0.0.1", port=port, log_config=None,
            log_level="critical", access_log=False, lifespan="on",
            timeout_graceful_shutdown=5))
        failures = []

        def serve():
            try:
                server.run(sockets=[listener])
            except BaseException as exc:
                failures.append(type(exc).__name__)

        thread = threading.Thread(target=serve, name="naia-agent-local", daemon=True)
        client = AgentClient(root, f"http://127.0.0.1:{port}", args.timeout)
        client.secrets.extend(secrets)
        try:
            thread.start()
            deadline = time.monotonic() + min(args.timeout, 30)
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(.01)
            if not server.started:
                raise AgentCallError("Local CLI runtime did not start", code="local_runtime_failed",
                                     details={"failure_types": failures})
            yield client, {
                "mode": "standalone_cli", "user_data": str(source.user_root),
                "settings": "Private CLI workspace seeded with existing presets; not the in-memory web session",
                "shared_data": ["data", "wildcards", "cache", "ui_assets"],
                "lifecycle": "Command-scoped; use batch for dependent calls. No GUI startup jobs or user extension autoload.",
                "completion": "Background operations must finish within the command session; dispatch acknowledgment alone is not completion",
            }
        finally:
            try:
                client.close()
            finally:
                secrets.extend(client.secrets)
                server.should_exit = True
                if thread.ident is not None:
                    thread.join(timeout=10)
                listener.close()
                if thread.is_alive():
                    raise AgentCallError("Local runtime is still draining work; process exit may interrupt background tasks",
                                         code="local_shutdown_incomplete")
