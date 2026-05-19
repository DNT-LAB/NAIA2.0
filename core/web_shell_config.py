"""Configuration helpers for local Remote Web launch modes."""

from __future__ import annotations

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
