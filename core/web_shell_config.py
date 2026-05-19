"""Configuration helpers for local Remote Web launch modes."""

from __future__ import annotations

import socket
from urllib.parse import urlencode


DEFAULT_WEB_SHELL_HOST = "127.0.0.1"
DEFAULT_WEB_SHELL_BIND_HOST = "0.0.0.0"
DEFAULT_WEB_SHELL_PORT = 7243
MIN_WEB_SHELL_PORT = 1024
MAX_WEB_SHELL_PORT = 65535


def normalize_web_shell_port(port: int | str | None) -> int:
    """Return a valid TCP port for the local Remote Web server."""
    try:
        value = int(port) if port is not None else DEFAULT_WEB_SHELL_PORT
    except (TypeError, ValueError):
        return DEFAULT_WEB_SHELL_PORT

    if MIN_WEB_SHELL_PORT <= value <= MAX_WEB_SHELL_PORT:
        return value
    return DEFAULT_WEB_SHELL_PORT


def can_bind_web_shell_port(host: str, port: int | str | None) -> bool:
    """Return whether the Remote Web server can bind the requested port."""
    clean_host = (host or DEFAULT_WEB_SHELL_BIND_HOST).strip() or DEFAULT_WEB_SHELL_BIND_HOST
    clean_port = normalize_web_shell_port(port)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((clean_host, clean_port))
        return True
    except OSError:
        return False


def select_web_shell_port(
    host: str,
    preferred_port: int | str | None = DEFAULT_WEB_SHELL_PORT,
    *,
    auto_port: bool = False,
    max_attempts: int = 20,
) -> int:
    """Select the port for Remote Web, optionally falling forward when busy."""
    clean_port = normalize_web_shell_port(preferred_port)
    if not auto_port:
        return clean_port

    attempts = max(1, int(max_attempts))
    for offset in range(attempts):
        candidate = clean_port + offset
        if candidate > MAX_WEB_SHELL_PORT:
            break
        if can_bind_web_shell_port(host, candidate):
            return candidate

    raise RuntimeError(
        f"No available Remote Web port found from {clean_port} to "
        f"{min(MAX_WEB_SHELL_PORT, clean_port + attempts - 1)}"
    )


def build_web_shell_url(
    host: str = DEFAULT_WEB_SHELL_HOST,
    port: int | str | None = DEFAULT_WEB_SHELL_PORT,
    *,
    embedded: bool = True,
) -> str:
    """Build the localhost URL for the legacy embedded Desktop Web Shell."""
    clean_host = (host or DEFAULT_WEB_SHELL_HOST).strip() or DEFAULT_WEB_SHELL_HOST
    clean_port = normalize_web_shell_port(port)
    query = urlencode({"desktop_shell": "1"}) if embedded else ""
    suffix = f"?{query}" if query else ""
    return f"http://{clean_host}:{clean_port}/{suffix}"


def should_launch_web_shell_by_default(
    *,
    desktop_requested: bool = False,
    web_session_requested: bool = False,
) -> bool:
    """Return whether the legacy desktop entrypoint should open QWebEngine by default."""
    return False
