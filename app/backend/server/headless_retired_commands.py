from __future__ import annotations

import json
from typing import Any

from fastapi import WebSocket

from core.web_session_context import WebSessionContext


HEADLESS_RETIRED_COMMAND_TYPES = {
    "set_desktop_window_visibility",
}


async def _send_json(ws: WebSocket, payload: dict[str, Any]) -> None:
    await ws.send_text(json.dumps(payload, ensure_ascii=False))


async def handle_headless_retired_command(
    ws: WebSocket,
    context: WebSessionContext,
    client_host: str,
    command: dict[str, Any],
) -> bool:
    command_type = str(command.get("type") or "").strip()
    if command_type not in HEADLESS_RETIRED_COMMAND_TYPES:
        return False

    if command_type == "set_desktop_window_visibility":
        await _send_json(ws, {
            "type": "toast",
            "level": "info",
            "message": "Native window controls are not available in this runtime.",
            "runtime": "web",
        })
        await _send_json(ws, context.desktop_window_state_payload(client_host))
        return True

    return False
