from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from fastapi import WebSocket

from app.backend.server.anlas_poller import build_anlas_payload
from core.web_session_context import WebSessionContext
from core.generation_access_policy import access_policy, GenerationBlocked


AsyncRunner = Callable[..., Awaitable[Any]]

API_CONTROL_COMMAND_TYPES = {
    "enter_no_api",
    "open_api_setup",
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


async def _broadcast_access(context, ws, clients, client_host):
    """Keep every tab on the same process-local policy, preserving setup permissions."""
    for client in set(clients or ()) | {ws}:
        host = getattr(getattr(client, "client", None), "host", None) or client_host
        try:
            await _send_json(client, context.api_status_payload(host))
            await _send_json(client, {"type": "mode", "mode": context.get_api_mode()})
            await _send_json(client, context.generation_param_schema_payload())
            await _send_json(client, {"type": "prompt_sync", "prompt": context.prompt_text,
                                     "negative": context.negative_prompt_text,
                                     "negative_prompt": context.negative_prompt_text, "force": True})
            if context.get_api_mode() == "NAI":
                for module in ("character", "character_reference", "vibe_transfer"):
                    await _send_json(client, context.module_state_payload(module))
        except (RuntimeError, ConnectionError):
            continue


async def handle_api_control_command(
    ws: WebSocket,
    context: WebSessionContext,
    client_host: str,
    command: dict[str, Any],
    *,
    run_in_thread: AsyncRunner,
    clients: set[WebSocket] | None = None,
) -> bool:
    command_type = str(command.get("type") or "").strip()
    if command_type not in API_CONTROL_COMMAND_TYPES:
        return False

    policy = access_policy(context)
    if command_type in {"enter_no_api", "open_api_setup"}:
        allowed, reason = context.setup_gate(client_host)
        if not allowed:
            await _send_setup_blocked(ws, command_type, reason)
            return True
        try:
            if command_type == "enter_no_api":
                policy.enter_reference(context)
            else:
                policy.open_setup()
        except GenerationBlocked as exc:
            await _send_json(ws, {"type": "no_api_result", "success": False, "message": str(exc)})
            return True
        await _broadcast_access(context, ws, clients, client_host)
        await _send_json(ws, {"type": "no_api_result", "success": True, **policy.payload()})
        return True

    if command_type == "probe_api":
        allowed, reason = context.setup_gate(client_host)
        if not allowed:
            await _send_setup_blocked(ws, command_type, reason)
            return True
        revision = policy.revision
        if policy.state == "reference":
            results = {mode: None for mode in ("NAI", "WEBUI", "COMFYUI")}
        else:
            results = await run_in_thread(context.probe_api)
        if (command.get("explicit") is True and policy.state == "setup"
                and revision == policy.revision):
            connected_mode = next((mode for mode, ok in results.items() if ok is True), None)
            if connected_mode and policy.connected(context, connected_mode, revision):
                await _broadcast_access(context, ws, clients, client_host)
                revision = policy.revision
        await _send_json(ws, {
            "type": "probe_result",
            "command": command_type,
            "results": results,
            "api_access_revision": revision,
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
        revision = policy.revision
        result = await run_in_thread(context.verify_api, mode, str(raw_value or ""))
        access_changed = False
        if result.get("success") and policy.blocked:
            if policy.connected(context, mode, revision):
                access_changed = True
                revision = policy.revision
        result["api_access_revision"] = revision
        await _send_json(ws, result)
        if access_changed:
            await _broadcast_access(context, ws, clients, client_host)
        await _send_json(ws, context.api_status_payload(client_host))
        if result.get("success") and mode == "NAI":
            await _send_json(ws, await run_in_thread(build_anlas_payload, context))
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
        enabled = bool(command.get("enabled", False))
        if enabled:
            # Immediate "connecting" feedback before the blocking tunnel start (binary download
            # + handshake can take several seconds). Without this the UI sat unchanged until the
            # final status arrived, so the connect looked like it did nothing.
            context.begin_cloudflared_connect()
            await _send_json(ws, context.api_status_payload(client_host))
        result = await run_in_thread(context.set_cloudflared_enabled, enabled)
        if not result.get("success", False):
            await _send_json(ws, {
                "type": "toast",
                "level": "error",
                "message": result.get("error") or result.get("status_text") or "Cloudflared failed",
            })
        await _send_json(ws, context.api_status_payload(client_host))
        return True

    return False
