from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from fastapi import WebSocket

from core.web_session_context import WebSessionContext


PromptEnqueue = Callable[..., Awaitable[None]]
GenerationCommandsEnqueue = Callable[[WebSocket, WebSessionContext, set[WebSocket], list[dict[str, Any]]], Awaitable[None]]

MODULE_COMMAND_TYPES = {
    "set_module_param",
    "get_module_state",
}


async def _send_json(ws: WebSocket, payload: dict[str, Any]) -> None:
    await ws.send_text(json.dumps(payload, ensure_ascii=False))


async def _run_vibe_encode(
    context: WebSessionContext,
    clients: set[WebSocket],
    command: dict[str, Any],
) -> None:
    """Background Vibe encode: broadcast the in-progress module_state, run the
    blocking /ai/encode-vibe call in a thread, then broadcast the result."""
    import asyncio

    from app.backend.server.websocket_broadcast import broadcast_json

    key = str(command.get("key") or "")
    if not key:
        return
    start = context._vibe_transfer_begin_encode(key)
    for message in (start.get("messages", []) if isinstance(start, dict) else []) or []:
        if isinstance(message, dict):
            await broadcast_json(clients, message)
    if not (isinstance(start, dict) and start.get("ok")):
        return  # invalid or already encoding — do NOT start a duplicate /ai/encode-vibe
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None, context._vibe_transfer_perform_encode, key, command.get("value")
        )
    except Exception as exc:  # pragma: no cover - defensive
        result = [{
            "type": "toast",
            "level": "error",
            "message": f"Vibe 인코딩 실패: {exc}",
            "runtime": "web",
        }]
    for message in (result or []):
        if isinstance(message, dict):
            await broadcast_json(clients, message)


async def _run_extension_load(
    context: WebSessionContext,
    clients: set[WebSocket],
    command: dict[str, Any],
) -> None:
    """확장 승인/재시도 — import가 수반되는 무거운 경로. '로딩 중' 상태를 먼저
    브로드캐스트하고 워커 스레드에서 로드한 뒤 결과를 브로드캐스트한다(매니저
    락으로 직렬화, 이벤트 루프 비차단)."""
    import asyncio

    from app.backend.server.websocket_broadcast import broadcast_json
    from core.extension_runtime import load_extensions

    manager = load_extensions(context)
    key = str(command.get("key") or "")
    if not key:
        return
    manager.mark_loading(key)
    await broadcast_json(clients, context._module_state_payload("extensions", manager.panel_state()))
    try:
        await asyncio.to_thread(manager.load_by_key, key)
    except Exception as exc:  # pragma: no cover - load_by_key는 내부 격리가 원칙
        await broadcast_json(clients, {
            "type": "toast",
            "level": "error",
            "message": f"확장 로드 실패: {exc}",
            "runtime": "web",
        })
    await broadcast_json(clients, context._module_state_payload("extensions", manager.panel_state()))


async def handle_module_command(
    ws: WebSocket,
    context: WebSessionContext,
    clients: set[WebSocket],
    client_host: str,
    command: dict[str, Any],
    *,
    enqueue_prompt_from_module: PromptEnqueue,
    enqueue_generation_commands: GenerationCommandsEnqueue,
) -> bool:
    command_type = str(command.get("type") or "").strip()
    if command_type not in MODULE_COMMAND_TYPES:
        return False

    if command_type == "get_module_state":
        module_id = str(command.get("module_id") or "")
        await _send_json(ws, context.module_state_payload(module_id, client_host))
        return True

    # Vibe encoding is a NAI network call (/ai/encode-vibe, ~seconds). Run it off the
    # event loop as a background task so it never blocks the WS handler; broadcast the
    # "encoding…" state, then the result. (set_module_param is called synchronously.)
    if (
        str(command.get("module_id") or "") == "vibe_transfer"
        and str(command.get("key") or "").startswith("encode_")
    ):
        import asyncio

        asyncio.create_task(_run_vibe_encode(context, clients, command))
        return True

    # Extensions 승인/재시도는 Python import를 수반하므로 백그라운드 태스크로 —
    # '로딩 중' 상태를 먼저 브로드캐스트해 패널이 즉시 반응한다.
    if (
        str(command.get("module_id") or "") == "extensions"
        and str(command.get("key") or "").split(":", 1)[0] in {"approve", "retry", "retry_errors"}
    ):
        import asyncio

        asyncio.create_task(_run_extension_load(context, clients, command))
        return True

    module_state = context.set_module_param(
        str(command.get("module_id") or ""),
        str(command.get("key") or ""),
        command.get("value"),
        client_host=client_host,
    )
    if module_state is None:
        await _send_json(ws, {
            "type": "toast",
            "level": "info",
            "message": "Module parameter is not supported in this runtime.",
            "runtime": "web",
        })
        return True

    if isinstance(module_state, list):
        generated_prompt = ""
        generated_source = ""
        for item in module_state:
            if isinstance(item, dict):
                await _send_json(ws, item)
                if item.get("type") == "prompt_generated" and item.get("source") == "e621_event":
                    generated_prompt = str(item.get("prompt") or "")
                    generated_source = "E621"
        if generated_prompt:
            await enqueue_prompt_from_module(
                ws,
                context,
                clients,
                prompt=generated_prompt,
                source=generated_source,
            )
        return True

    generation_commands: list[dict[str, Any]] = []
    extra_messages: list[dict[str, Any]] = []
    if isinstance(module_state, dict):
        raw_commands = module_state.pop("_headless_generation_commands", [])
        if isinstance(raw_commands, list):
            generation_commands = [item for item in raw_commands if isinstance(item, dict)]
        raw_messages = module_state.pop("_headless_extra_messages", [])
        if isinstance(raw_messages, list):
            extra_messages = [item for item in raw_messages if isinstance(item, dict)]
    for message in extra_messages:
        await _send_json(ws, message)
    await _send_json(ws, module_state)
    if str(command.get("module_id") or "") == "automation":
        # A timer automation must finish on wall-clock time even when no
        # generation is running; spawn the independent expiry watcher.
        from app.backend.server.generation_runner import ensure_automation_timer_watcher

        ensure_automation_timer_watcher(context, clients)
    if generation_commands:
        await enqueue_generation_commands(ws, context, clients, generation_commands)
    return True
