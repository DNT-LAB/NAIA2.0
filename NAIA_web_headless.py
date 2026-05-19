"""Headless Remote Web entrypoint.

This launcher starts a PyQt-free FastAPI/core-service runtime for the Remote
Web shell. Random prompt generation, request normalization, and headless result
delivery are handled by core services without starting the PyQt desktop app.
"""

from __future__ import annotations

import argparse

import uvicorn

from core.web_session_app import create_headless_app
from core.web_session_context import WebSessionContext
from core.web_shell_config import (
    DEFAULT_WEB_SHELL_BIND_HOST,
    DEFAULT_WEB_SHELL_PORT,
    normalize_web_shell_port,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start the NAIA headless Remote Web server.")
    parser.add_argument("--host", default=DEFAULT_WEB_SHELL_BIND_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_WEB_SHELL_PORT)
    parser.add_argument("--log-level", default="warning")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    port = normalize_web_shell_port(args.port)
    context = WebSessionContext()
    app = create_headless_app(context)
    print(f"NAIA Headless Web backend: http://127.0.0.1:{port} (bind {args.host})", flush=True)
    uvicorn.run(app, host=args.host, port=port, log_level=args.log_level)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
