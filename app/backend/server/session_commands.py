from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from fastapi import WebSocket

from app.backend.server.anlas_poller import broadcast_anlas
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
RECOMMENDED_PRESET_PARAM_TRIGGERS = {
    "sampling_mode",
    "comfyui_sampling_mode",
    "workflow_type",
    "comfyui_workflow_type",
}


async def broadcast_first_run_recommended_preset_payloads(
    context: WebSessionContext,
    clients: set[WebSocket],
    *,
    broadcast_json: BroadcastJson,
) -> bool:
    payloads = context._prompt_engineering_service().ensure_first_run_recommended_preset_payloads()
    for payload in payloads:
        await broadcast_json(clients, payload)
    return bool(payloads)


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


async def _maybe_autostart_automation(
    context: WebSessionContext,
    clients: set[WebSocket],
    *,
    broadcast_json: BroadcastJson,
) -> None:
    """Auto Gen을 켤 때 지속 자동화(persist)가 켜져 있으면 자동화를 자동 시작한다.

    Auto Gen이 핵심 트리거다. start는 종료 조건을 무장하고 Auto Gen을 엔게이지만 하므로
    (생성은 사용자 생성으로 점화) 여기서는 무장된 module_state와 타이머 watcher만 동기화한다.
    완료되면 finish가 Auto Gen을 끄므로 다시 켜기 전까지 재시작되지 않는다(무한 루프 없음).
    """
    state = context._automation_service().maybe_autostart()
    if not isinstance(state, dict):
        return
    extra = state.pop("_headless_extra_messages", [])
    if isinstance(extra, list):
        for message in extra:
            if isinstance(message, dict):
                await broadcast_json(clients, message)
    await broadcast_json(clients, state)
    from app.backend.server.generation_runner import ensure_automation_timer_watcher

    ensure_automation_timer_watcher(context, clients)


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
        option_key = str(command.get("key") or "")
        context.set_option(option_key, command.get("value"))
        await broadcast_json(clients, {"type": "options", **context.get_options()})
        # 지속 자동화: Auto Gen을 켜면(+persist) 자동화를 자동 시작(Auto Gen이 트리거).
        if option_key == "auto_generate" and context._coerce_bool(command.get("value")):
            await _maybe_autostart_automation(context, clients, broadcast_json=broadcast_json)
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
        key = str(command.get("key") or "")
        context.set_param(key, command.get("value"))
        recommended_applied = False
        if key.strip() in RECOMMENDED_PRESET_PARAM_TRIGGERS:
            recommended_applied = await broadcast_first_run_recommended_preset_payloads(
                context,
                clients,
                broadcast_json=broadcast_json,
            )
        if not recommended_applied:
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
    # Bug 2b — lazy empty-prompt restore for the mode we just entered. set_api_mode
    # activated this mode's prompt plane (blank if it was never used this session).
    # When the box is blank AND Prompt Fixed is off: (a) restore the matched
    # (last-used) preset's main_settings.prompt; (b) if that is empty too, run a
    # single Random so the box is never left empty on mode entry. Skipped entirely
    # when Prompt Fixed is on (the user pinned whatever prompt was there).
    #
    # Runs BEFORE the first-run recommended preset below — that's intentional and
    # safe: the recommended preset only seeds params/negative/module-settings, never
    # the main prompt, so it can't overwrite (or be overwritten by) this. Whatever
    # this lands in the box is persisted to the mode's plane, so later switches back
    # find it remembered and skip this entirely.
    pe_service = context._prompt_engineering_service()
    if not context.get_options().get("prompt_fixed") and not str(context.prompt_text or "").strip():
        try:
            restored = pe_service.restore_main_prompt_from_preset()
        except Exception as exc:  # noqa: BLE001 — never let restore break mode switch
            print(f"Remote Web: empty-prompt preset restore failed: {exc}", flush=True)
            restored = False
        if not restored:
            from app.backend.server.generation_commands import (
                run_random_fallback_for_empty_prompt,
            )

            await run_random_fallback_for_empty_prompt(
                context, clients, broadcast_json=broadcast_json
            )
    # Per-mode prompt memory: set_api_mode swapped in the target mode's stored
    # prompt (possibly just restored above). Push it so the main prompt box reflects
    # THIS mode's prompt (force: the previous mode's prompt is no longer valid here).
    await broadcast_json(clients, {
        "type": "prompt_sync",
        "prompt": context.prompt_text,
        "negative": context.negative_prompt_text,
        "negative_prompt": context.negative_prompt_text,
        "force": True,
    })
    if requested_mode in {"WEBUI", "COMFYUI"}:
        await run_in_thread(context.refresh_api_options, requested_mode)
    recommended_payloads = pe_service.ensure_first_run_recommended_preset_payloads()
    await broadcast_json(clients, {
        "type": "mode_result",
        "success": True,
        "mode": context.get_api_mode(),
        "message": f"{context.get_api_mode()} mode active",
    })
    await broadcast_json(clients, {"type": "mode", "mode": context.get_api_mode()})
    if recommended_payloads:
        for payload in recommended_payloads:
            await broadcast_json(clients, payload)
    else:
        await broadcast_json(clients, context.generation_param_schema_payload())
    await ws.send_text(json.dumps(context.api_status_payload(client_host), ensure_ascii=False))
    # 모드 전환 시 Anlas pill 갱신: NAI 진입 시 다시 표시, 비-NAI 진입 시 숨김.
    # (없으면 한 번 숨겨진 pill이 5분 폴링/재연결 전까지 NAI 복귀해도 안 나타남)
    await broadcast_anlas(context, clients)
