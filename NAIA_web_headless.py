"""Headless Remote Web entrypoint.

This launcher starts a PyQt-free FastAPI/core-service runtime for the Remote
Web shell. Random prompt generation, request normalization, and headless result
delivery are handled by core services without starting the PyQt desktop app.
"""

from __future__ import annotations

import argparse
import os
import socket
import threading
import time
import webbrowser

import uvicorn

from app.backend.server import WebSessionContext, create_headless_app
from core.web_shell_config import (
    DEFAULT_WEB_SHELL_BIND_HOST,
    DEFAULT_WEB_SHELL_HOST,
    DEFAULT_WEB_SHELL_PORT,
    build_web_shell_url,
    normalize_web_shell_port,
    select_web_shell_port,
)


def _env_flag(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _wait_for_web_server(port: int, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + max(0.1, timeout)
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((DEFAULT_WEB_SHELL_HOST, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _open_browser_when_ready(port: int) -> None:
    url = build_web_shell_url(DEFAULT_WEB_SHELL_HOST, port, embedded=False)

    def worker() -> None:
        ready = _wait_for_web_server(port)
        if ready:
            print(f"Opening NAIA Web UI: {url}", flush=True)
        else:
            print(f"NAIA Web UI readiness timed out; opening anyway: {url}", flush=True)
        try:
            opened = webbrowser.open(url, new=2)
        except Exception as exc:
            print(f"NAIA Web UI browser open failed: {exc}", flush=True)
            return
        if not opened:
            print(f"NAIA Web UI browser open was not accepted by the system: {url}", flush=True)

    threading.Thread(target=worker, daemon=True, name="naia-web-browser-open").start()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start the NAIA headless Remote Web server.")
    parser.add_argument("--host", default=DEFAULT_WEB_SHELL_BIND_HOST)
    parser.add_argument("--port", default=str(DEFAULT_WEB_SHELL_PORT))
    parser.add_argument(
        "--auto-port",
        action="store_true",
        help="If the requested port is busy, bind the next available port.",
    )
    parser.add_argument("--log-level", default="warning")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open the Web UI in the system browser after the server starts.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    requested_port = normalize_web_shell_port(args.port)
    port = select_web_shell_port(args.host, requested_port, auto_port=args.auto_port)
    if port != requested_port:
        print(
            f"NAIA Headless Web: port {requested_port} is busy; using {port}.",
            flush=True,
        )
    context = WebSessionContext(remote_params={"web_session_port": port})
    app = create_headless_app(context)
    print(f"NAIA Headless Web backend: http://127.0.0.1:{port} (bind {args.host})", flush=True)
    if not args.no_browser and _env_flag("NAIA_HEADLESS_OPEN_BROWSER", default=True):
        _open_browser_when_ready(port)
    uvicorn.run(app, host=args.host, port=port, log_level=args.log_level)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
