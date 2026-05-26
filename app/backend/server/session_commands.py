from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from fastapi import WebSocket

from core.web_session_context import WebSessionContext


BroadcastJson = Callable[[set[WebSocket], dict[str, Any]], Awaitable[None]]
AsyncRunner = Callable[..., Awaitable[Any]]

SESSION_COMMAND_TYPES = {
    "sync",
    "set_option",
    "set_mode",
    "set_prompt",
    "set_param",
}
API_OPTION_TOKEN_KEYS = {
    "WEBUI": "webui_url",
    "COMFYUI": "comfyui_url",
}


async def refresh_active_api_options_if_configured(
    context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
) -> dict[str, Any] | None:
    mode = str(context.get_api_mode() or "").strip().upper()
    token_key = API_OPTION_TOKEN_KEYS.get(mode)
    if not token_key:
        return None
    if not str(context.secure_token_manager.get_token(token_key) or "").strip():
        return None
    try:
        return await run_in_thread(context.refresh_api_options, mode)
    except Exception:
        return None


async def send_sync_messages(
    ws: WebSocket,
    context: WebSessionContext,
    client_host: str,
    *,
    run_in_thread: AsyncRunner | None = None,
) -> None:
    if run_in_thread is not None:
        await refresh_active_api_options_if_configured(context, run_in_thread=run_in_thread)
    messages = [
        {"type": "mode", "mode": context.get_api_mode()},
        {"type": "options", **context.get_options()},
        context.generation_param_schema_payload(),
        context.queue_state_payload(),
        context.api_status_payload(client_host),
        {"type": "lazy_indices_ready"},
    ]
    for message in messages:
        await ws.send_text(json.dumps(message, ensure_ascii=False))


async def handle_session_command(
    ws: WebSocket,
    context: WebSessionContext,
    clients: set[WebSocket],
    client_host: str,
    command: dict[str, Any],
    *,
    broadcast_json: BroadcastJson,
    run_in_thread: AsyncRunner,
) -> bool:
    command_type = str(command.get("type") or "").strip()
    if command_type == "sync":
        await send_sync_messages(ws, context, client_host, run_in_thread=run_in_thread)
        return True
    if command_type == "set_option":
        context.set_option(str(command.get("key") or ""), command.get("value"))
        await broadcast_json(clients, {"type": "options", **context.get_options()})
        return True
    if command_type == "set_mode":
        await _handle_set_mode(
            ws,
            context,
            clients,
            client_host,
            command,
            broadcast_json=broadcast_json,
            run_in_thread=run_in_thread,
        )
        return True
    if command_type == "set_prompt":
        context.prompt_text = str(command.get("prompt") or "")
        context.negative_prompt_text = str(command.get("negative_prompt", command.get("negative")) or "")
        context.save_remote_ui_state()
        await ws.send_text(json.dumps({
            "type": "prompt_sync",
            "prompt": context.prompt_text,
            "negative": context.negative_prompt_text,
            "negative_prompt": context.negative_prompt_text,
        }, ensure_ascii=False))
        return True
    if command_type == "set_param":
        context.set_param(str(command.get("key") or ""), command.get("value"))
        await broadcast_json(clients, context.generation_param_schema_payload())
        return True
    return False


async def _handle_set_mode(
    ws: WebSocket,
    context: WebSessionContext,
    clients: set[WebSocket],
    client_host: str,
    command: dict[str, Any],
    *,
    broadcast_json: BroadcastJson,
    run_in_thread: AsyncRunner,
) -> None:
    requested_mode = str(command.get("mode") or "").strip().upper()
    if requested_mode not in {"NAI", "WEBUI", "COMFYUI"}:
        await ws.send_text(json.dumps({
            "type": "mode_result",
            "success": False,
            "mode": requested_mode,
            "message": f"Unknown mode: {requested_mode}",
        }, ensure_ascii=False))
        return
    token_key = {
        "NAI": "nai_token",
        "WEBUI": "webui_url",
        "COMFYUI": "comfyui_url",
    }[requested_mode]
    if not str(context.secure_token_manager.get_token(token_key) or ""):
        await ws.send_text(json.dumps({
            "type": "mode_result",
            "success": False,
            "mode": requested_mode,
            "message": f"{requested_mode} API is not connected",
        }, ensure_ascii=False))
        await ws.send_text(json.dumps(context.api_status_payload(client_host), ensure_ascii=False))
        return
    context.set_api_mode(requested_mode)
    if requested_mode in {"WEBUI", "COMFYUI"}:
        await run_in_thread(context.refresh_api_options, requested_mode)
    await broadcast_json(clients, {
        "type": "mode_result",
        "success": True,
        "mode": context.get_api_mode(),
        "message": f"{context.get_api_mode()} mode active",
    })
    await broadcast_json(clients, {"type": "mode", "mode": context.get_api_mode()})
    await broadcast_json(clients, context.generation_param_schema_payload())
    await ws.send_text(json.dumps(context.api_status_payload(client_host), ensure_ascii=False))
