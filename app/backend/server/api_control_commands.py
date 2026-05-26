from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from fastapi import WebSocket

from core.web_session_context import WebSessionContext


AsyncRunner = Callable[..., Awaitable[Any]]

API_CONTROL_COMMAND_TYPES = {
    "probe_api",
    "verify_nai",
    "verify_webui",
    "verify_comfyui",
    "clear_api",
    "set_cloudflared_enabled",
}


async def _send_json(ws: WebSocket, payload: dict[str, Any]) -> None:
    await ws.send_text(json.dumps(payload, ensure_ascii=False))


async def _send_setup_blocked(ws: WebSocket, command_type: str, reason: str) -> None:
    await _send_json(ws, {
        "type": "setup_blocked",
        "command": command_type,
        "reason": reason,
    })


async def handle_api_control_command(
    ws: WebSocket,
    context: WebSessionContext,
    client_host: str,
    command: dict[str, Any],
    *,
    run_in_thread: AsyncRunner,
) -> bool:
    command_type = str(command.get("type") or "").strip()
    if command_type not in API_CONTROL_COMMAND_TYPES:
        return False

    if command_type == "probe_api":
        allowed, reason = context.setup_gate(client_host)
        if not allowed:
            await _send_setup_blocked(ws, command_type, reason)
            return True
        results = await run_in_thread(context.probe_api)
        await _send_json(ws, {
            "type": "probe_result",
            "command": command_type,
            "results": results,
        })
        return True

    if command_type in {"verify_nai", "verify_webui", "verify_comfyui"}:
        allowed, reason = context.setup_gate(client_host)
        if not allowed:
            await _send_setup_blocked(ws, command_type, reason)
            return True
        mode = {
            "verify_nai": "NAI",
            "verify_webui": "WEBUI",
            "verify_comfyui": "COMFYUI",
        }[command_type]
        raw_value = command.get("token") if mode == "NAI" else command.get("url")
        result = await run_in_thread(context.verify_api, mode, str(raw_value or ""))
        await _send_json(ws, result)
        await _send_json(ws, context.api_status_payload(client_host))
        if result.get("success") and mode in {"WEBUI", "COMFYUI"}:
            await run_in_thread(context.refresh_api_options, mode)
            if context.get_api_mode() == mode:
                await _send_json(ws, context.generation_param_schema_payload())
        return True

    if command_type == "clear_api":
        allowed, reason = context.setup_gate(client_host)
        if not allowed:
            await _send_setup_blocked(ws, command_type, reason)
            return True
        result = await run_in_thread(context.clear_api, str(command.get("mode") or ""))
        if result.get("success"):
            context.clear_api_options(str(command.get("mode") or ""))
        await _send_json(ws, result)
        await _send_json(ws, context.api_status_payload(client_host))
        return True

    if command_type == "set_cloudflared_enabled":
        allowed, reason = context.cloudflared_gate(client_host)
        if not allowed:
            await _send_json(ws, {
                "type": "toast",
                "level": "error",
                "message": reason,
                "reason": reason,
            })
            return True
        result = await run_in_thread(context.set_cloudflared_enabled, bool(command.get("enabled", False)))
        if not result.get("success", False):
            await _send_json(ws, {
                "type": "toast",
                "level": "error",
                "message": result.get("error") or result.get("status_text") or "Cloudflared failed",
            })
        await _send_json(ws, context.api_status_payload(client_host))
        return True

    return False
