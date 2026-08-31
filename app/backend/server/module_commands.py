from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from fastapi import WebSocket

from core.headless_payload_utils import is_loopback_host
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


def _truthy(value: Any) -> bool:
    """일반 dispatch(`_coerce_bool`)와 **같은 잣대**로 읽는다.

    ⚠️ `bool("false")` 는 True 다 - 문자열로 오는 클라이언트의 끄기 요청이
    켜기로 읽히면 안 된다.
    """
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)


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
        # ⚠️ 여기서 가로채면 `return True` 라 **일반 dispatch 가 건너뛰어진다** -
        # 그 경로가 `record.enabled` 를 세우므로, 아무거나 가로채면 플래그가
        # 영영 안 바뀐다. 그래서 `enabled` 는 **켜는 경우만** 가로채고
        # (그때는 import 가 필요하다 - load_all 이 꺼진 것을 안 읽는다),
        # 끄는 경우는 일반 경로로 보내 플래그만 내린다.
        and (
            str(command.get("key") or "").split(":", 1)[0] in {"approve", "retry", "retry_errors"}
            or (str(command.get("key") or "").split(":", 1)[0] == "enabled"
                # ⚠️ `bool("false")` 는 True 다 - 문자열 "false" 를 보내는 클라이언트의
                #    끄기 요청이 켜기로 가로채질 수 있었다(Codex CONCERN).
                #    일반 dispatch 와 같은 잣대로 읽는다.
                and _truthy(command.get("value")))
        )
    ):
        import asyncio

        from core.extension_runtime import load_extensions

        # ⚠️ 플래그는 **여기서 동기적으로** 쓴다. WS 메시지는 순서대로 처리되므로
        #    ON/OFF 가 도착 순서대로 확정된다. 백그라운드 태스크 안에서 쓰면 늦게
        #    깨어나 뒤이어 온 OFF 를 덮는다(Codex BLOCK - 실측 재현했다).
        key = str(command.get("key") or "")
        if key.split(":", 1)[0] == "enabled":
            load_extensions(context).apply_panel_param(key, True)
        asyncio.create_task(_run_extension_load(context, clients, command))
        return True

    # Vibe Storage 관리(파일 삭제 / OS 탐색기 열기)는 서버 머신 로컬 동작이라 루프백 클라이언트
    # 전용으로 게이트한다(기존 result open-location 경계와 일치, Codex 리뷰). 원격 web 클라이언트는
    # vibe 적용/사용은 그대로 가능하며 이 두 관리 동작만 차단된다.
    # ⚠️ 다운스트림 dispatch가 module_id/key를 .strip() 하므로(headless_module_dispatch_service),
    # 여기서도 반드시 strip 후 비교 — 안 하면 "delete_storage "(공백) 등으로 게이트 우회 가능
    # (Codex CRITICAL: 정규화 불일치 우회).
    # 빠른 저장 경로도 서버 머신의 임의 위치를 가리키므로 같은 경계를 쓴다.
    # (set_auto_save_param 에도 방어가 있지만 그쪽은 조용히 무시하므로,
    #  여기서 먼저 잡아 사용자에게 이유를 알린다.)
    if (
        str(command.get("module_id") or "").strip() == "auto_save"
        and str(command.get("key") or "").strip() == "quicksave_dir"
        and not is_loopback_host(client_host)
    ):
        await _send_json(ws, {
            "type": "toast",
            "level": "error",
            "message": "빠른 저장 경로는 로컬(이 PC)에서만 바꿀 수 있습니다.",
            "runtime": "web",
        })
        # 패널은 전송 전에 값을 낙관적으로 반영한다 — 거부했으면 서버 값을 돌려줘
        # 입력란이 적용되지 않은 경로를 계속 보여주지 않게 한다.
        await _send_json(ws, context.auto_save_state_payload())
        return True

    if (
        str(command.get("module_id") or "").strip() == "vibe_transfer"
        and str(command.get("key") or "").strip() in {"open_location", "delete_storage"}
        and not is_loopback_host(client_host)
    ):
        await _send_json(ws, {
            "type": "toast",
            "level": "error",
            "message": "이 동작은 로컬(이 PC)에서만 가능합니다.",
            "runtime": "web",
        })
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
