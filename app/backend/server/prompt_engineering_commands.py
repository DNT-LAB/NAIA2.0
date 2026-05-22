from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from fastapi import WebSocket

from core.web_session_context import WebSessionContext


AsyncRunner = Callable[..., Awaitable[Any]]

HIRES_OVERLAY_COMMAND_TYPES = {
    "read_hires_preset_overlay",
    "write_hires_preset_overlay",
}


async def _send_json(ws: WebSocket, payload: dict[str, Any]) -> None:
    await ws.send_text(json.dumps(payload, ensure_ascii=False))


async def handle_hires_overlay_command(
    ws: WebSocket,
    context: WebSessionContext,
    command: dict[str, Any],
    *,
    run_in_thread: AsyncRunner,
) -> bool:
    command_type = str(command.get("type") or "").strip()
    if command_type not in HIRES_OVERLAY_COMMAND_TYPES:
        return False

    service = context._prompt_engineering_service()
    preset_name = str(command.get("preset_name") or "")
    if command_type == "read_hires_preset_overlay":
        response = await run_in_thread(service.hires_overlay_response, preset_name)
        await _send_json(ws, response)
        return True

    action = str(command.get("action") or "save")
    if action == "reset":
        ok, message = await run_in_thread(service.reset_hires_overlay, preset_name)
    else:
        body = command.get("body") if isinstance(command.get("body"), dict) else {}
        ok, message = await run_in_thread(service.write_hires_overlay, preset_name, body)
    await _send_json(ws, {
        "type": "toast",
        "level": "success" if ok else "error",
        "message": message,
        "headless": True,
    })
    if ok:
        response = await run_in_thread(service.hires_overlay_response, preset_name)
        await _send_json(ws, response)
    return True
