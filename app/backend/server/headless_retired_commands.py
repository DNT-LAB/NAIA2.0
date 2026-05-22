from __future__ import annotations

import json
from typing import Any

from fastapi import WebSocket

from core.web_session_context import WebSessionContext


HEADLESS_RETIRED_COMMAND_TYPES = {
    "set_desktop_window_visibility",
    "result_upscale",
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
            "message": "Desktop runtime is not available in headless mode.",
            "headless": True,
        })
        await _send_json(ws, context.desktop_window_state_payload(client_host))
        return True

    if command_type == "result_upscale":
        await _send_json(ws, {
            "type": "result_upscale_state",
            "running": False,
            "success": False,
            "message": "NAI 2x upscale is not available in the headless runtime yet.",
            "headless": True,
        })
        await _send_json(ws, {
            "type": "toast",
            "level": "info",
            "message": "Headless command retired: result_upscale",
            "headless": True,
        })
        return True

    return False
