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


# V5 인페인트 캔버스의 **합성을 바꾸는** 파라미터. 이 응답은 모두에게 보낸다
# (Codex 리뷰 2026-10-03 HIGH): 두 탭이 같은 세션을 보는데 A 가 레이어를 숨기거나
# 베이스를 옮기면, B 화면은 옛 합성을 보이면서 B 의 [인페인트 생성] 은 서버의 새
# 합성으로 나간다 - 화면과 다른 그림에 돈이 나간다. 레이어 추가(HTTP)는 이미 방송한다.
_INPAINT_CANVAS_KEYS = frozenset({
    "base_offset", "base_scale", "base_rotation", "base_reset",
    "canvas_size", "mask_png", "clear_mask", "auto_mask",
    # 1MP 토글은 베이스를 다시 만들어 합성을 바꾼다(크기가 달라지면 캔버스 · 마스크까지).
    "resize_1mp",
})


def _is_inpaint_canvas_edit(command: dict[str, Any]) -> bool:
    if str(command.get("module_id") or "") != "img2img":
        return False
    key = str(command.get("key") or "")
    return key.startswith("layer_") or key in _INPAINT_CANVAS_KEYS


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


# 끝나기 전에 쓰레기 수집되지 않게 붙잡아 둔다(asyncio 는 태스크를 약하게만 쥔다).
_E621_TRANSLATION_TASKS: set[Any] = set()


def translate_e621_search_query(context: WebSessionContext, query: str) -> str:
    """한국어 검색어를 영어로. 네트워크를 타므로 스레드에서 부른다. 실패 · 쓸 수 없는 결과는 ''."""
    from app.backend.server.autocomplete_commands import _translate_autocomplete_query

    return _translate_autocomplete_query(context, query, label="e621_search")


async def _run_e621_search_translation(
    ws: WebSocket,
    context: WebSessionContext,
    client_host: str,
    query: str,
) -> None:
    """E621 연구모듈: 한국어 검색어를 영어로 번역한 결과로 한 번 더 찾는다(사용자 지정 2026-10-03).

    화면이 검색 뒤에 `search_translate` 로 따로 청한다(자동완성의 autocomplete_translate 와 같은 모양) - 검색 명령에
    걸어 두면 한국어로 검색하는 모든 호출이 번역기를 부른다. 검색 응답은 이미 나갔고, 여기서는 번역이 끝나면
    보탠 결과를 **한 번 더** 보낸다. 그사이 검색어가 바뀌었으면 서비스가 버린다(search_translation 이 비어서 온다).
    """
    import asyncio

    try:
        translated = await asyncio.to_thread(translate_e621_search_query, context, query)
        if not translated:
            return
        state = context.set_module_param(
            "e621_event", "search_translation", {"query": query, "translated": translated}, client_host=client_host)
        if isinstance(state, dict) and state.get("search_translation"):
            await _send_json(ws, state)
    except Exception as exc:  # noqa: BLE001 - 덤으로 얹는 검색이다. 실패해도 원래 결과는 이미 화면에 있다
        print(f"[warn] e621 search translation skipped: {type(exc).__name__}", flush=True)


def _e621_translate_request(command: dict[str, Any]) -> str | None:
    """`search_translate` 명령이면 번역할 검색어(한글이 없으면 ''), 다른 명령이면 None."""
    if str(command.get("module_id") or "") != "e621_event" or str(command.get("key") or "") != "search_translate":
        return None
    from core.e621_research_index import HANGUL

    # 서비스가 검색어를 다듬는 방식(strip · lower)과 같아야 search_translation 이 지금 검색어와 맞는다.
    query = str(command.get("value") or "").strip().lower()
    return query if HANGUL.search(query) else ""


def _snapshot_moves_a_dataset(command: dict[str, Any]) -> bool:
    """이 명령이 스냅샷의 **데이터셋 사본**을 쓰거나 읽는가(= 오래 걸릴 수 있는가).

    담기는 `include_search` 를 켰을 때(항목을 골라 담는 저장 창은 `sections` 에 `search` 가 있을 때),
    되돌리기는 `search` 를 골랐을 때(또는 항목을 안 골라 전부일 때)다.
    그 밖의 스냅샷 명령은 작아서 예전처럼 제자리에서 돈다 - 스레드로 넘기면 다른 창의 명령과 섞일 틈만 는다.
    """
    if str(command.get("module_id") or "").strip() != "snapshot":
        return False
    key = str(command.get("key") or "").strip()
    value = command.get("value")
    if not isinstance(value, dict):
        try:
            import json

            value = json.loads(str(value or "{}"))
        except (TypeError, ValueError):
            return False
        if not isinstance(value, dict):
            return False
    if key == "save":
        sections = value.get("sections")
        if isinstance(sections, list):
            # 항목을 골라 담을 때는 그 목록이 정한다 - 서비스가 `include_search` 를 보지 않는다.
            return "search" in sections
        flag = value.get("include_search")
        return flag is True or (isinstance(flag, str) and flag.strip().lower() == "true")
    if key == "apply":
        sections = value.get("sections")
        return sections is None or (isinstance(sections, list) and "search" in sections)
    return False


async def _run_snapshot_dataset_command(context: WebSessionContext, command: dict[str, Any]) -> Any:
    """데이터셋 사본을 쓰거나 읽는 스냅샷 명령. **긴 파일 일만** 이벤트 루프 밖으로 내보낸다.

    ⚠️ 통째로 스레드에 넘기지 않는다(Codex 리뷰 2026-10-05 HIGH). 스냅샷의 잠금은 프리셋 · 모드 변경과 공유되지
       않아서, 스레드가 세션을 읽거나 고치는 동안 다른 창의 명령이 이벤트 루프에서 끼어든다 - `*snapshot` 으로
       넘어가던 중에 프리셋이 바뀌면 스냅샷의 값이 그 프리셋에 섞인다. 그래서:
       · 담기 - 설정을 모으는 것까지 여기(이벤트 루프)서 하고, 파일 쓰기만 스레드로.
       · 되돌리기 - 세션에 넣는 것(프리셋 · 캐릭터 · 조건부 · 참조)은 여기서, 데이터셋만 스레드로.
         풀 교체는 제 잠금(`search_pool_state_guard`) 아래에서 한다 - 커스텀 Parquet 불러오기와 같은 길이다.
    이 연결의 다음 명령은 이 await 가 끝난 뒤에 처리되므로 같은 창 안의 순서는 그대로다.
    """
    import asyncio

    service = context._snapshot_service()
    key = str(command.get("key") or "").strip()
    payload = service._payload(command.get("value"))
    if key == "save":
        pending = service.begin_save(payload)
        return await asyncio.to_thread(pending) if callable(pending) else pending
    name = str(payload.get("name") or "")
    sections = payload.get("sections")
    first = service.apply(name, sections, part="session")
    if not isinstance(first.get("apply_report"), dict):
        return first                      # 시작도 못 했다(모드 · 모델 · 떠나는 프리셋 저장 실패) - 데이터셋도 안 건드린다
    second = await asyncio.to_thread(lambda: service.apply(name, sections, part="dataset"))
    return service.merge_apply(first, second)


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

    e621_query = _e621_translate_request(command)
    if e621_query is not None:
        if e621_query:
            import asyncio

            task = asyncio.create_task(_run_e621_search_translation(ws, context, client_host, e621_query))
            _E621_TRANSLATION_TASKS.add(task)
            task.add_done_callback(_E621_TRANSLATION_TASKS.discard)
        return True

    if _snapshot_moves_a_dataset(command):
        # ⚠️ 데이터셋 사본을 쓰거나 읽는 스냅샷 명령은 **이벤트 루프 밖에서** 돌린다. 풀이 수백 MB 일 수
        #    있어(실측: 사용자 custom_tags 가 150 ~ 330MB) 여기서 동기로 돌리면 그동안 모든 창의 소켓이
        #    멈춘다. 커스텀 Parquet 불러오기가 같은 이유로 스레드에서 돈다(`search_commands`).
        #    이 연결의 다음 명령은 이 await 가 끝난 뒤에 처리되므로 같은 창 안의 순서는 그대로다.
        #    설정을 읽고 넣는 일은 여기(이벤트 루프)에 남긴다 - `_run_snapshot_dataset_command`.
        module_state = await _run_snapshot_dataset_command(context, command)
    elif str(command.get("module_id") or "") == "character" and str(command.get("slot_uuid") or "").strip():
        # ⚠️ 캐릭터 명령은 배열 **인덱스**로 주소를 매긴다. 화면이 그 칸의 uuid 를 함께 보냈으면 서비스가
        #    그 칸이 지금 있는 자리로 고쳐 쓴다(밀린 글 편집이 낡은 번호로 남의 칸을 덮지 않게).
        #    `set_module_param` 의 캐릭터 갈래는 `set_param` 으로 넘기기만 하므로 여기서 바로 부른다.
        module_state = context._character_service().set_param(
            str(command.get("key") or "").strip(),
            command.get("value"),
            slot_uuid=str(command.get("slot_uuid") or "").strip(),
        )
    else:
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
        e621_use_main_pipeline = True
        for item in module_state:
            if isinstance(item, dict):
                await _send_json(ws, item)
                if item.get("type") == "prompt_generated" and item.get("source") == "e621_event":
                    generated_prompt = str(item.get("prompt") or "")
                    generated_source = "E621"
                    e621_use_main_pipeline = item.get("use_main_pipeline", True) is not False
        if generated_prompt:
            await enqueue_prompt_from_module(
                ws,
                context,
                clients,
                prompt=generated_prompt,
                source=generated_source,
                e621_use_main_pipeline=e621_use_main_pipeline,
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
    # ⚠️ 캐릭터 모듈만은 **모두에게** 보낸다(Codex BLOCK 3).
    #
    #    이 모듈의 편집 명령은 전부 배열 **인덱스**로 주소를 매긴다(`char_prompt_3`).
    #    탭이 둘 열려 있는데 A 가 순서를 바꾸면 B 의 화면은 옛 배열 그대로다 - B 가
    #    화면상 C2 를 고치면 서버에서는 새 인덱스 1 의 **다른 캐릭터**를 덮는다.
    #    프롬프트에는 되돌리기가 없어 그대로 유실이다.
    #
    #    ⚠️ 다른 모듈까지 넓히지 않는다 - 각자 에코를 받고 무엇을 하는지 안 봤다.
    #       캐릭터는 이미 에셋 REST 경로가 같은 페이로드를 방송하고 있어
    #       (`character_asset_routes`), 화면이 받을 준비가 되어 있는 것이 확인된다.
    if _is_inpaint_canvas_edit(command):
        from app.backend.server.websocket_broadcast import broadcast_json

        await broadcast_json(clients, module_state)
    elif str(command.get("module_id") or "") == "character":
        from app.backend.server.websocket_broadcast import broadcast_json

        await broadcast_json(clients, module_state)
    else:
        await _send_json(ws, module_state)
    if str(command.get("module_id") or "") == "automation":
        # A timer automation must finish on wall-clock time even when no
        # generation is running; spawn the independent expiry watcher.
        from app.backend.server.generation_runner import ensure_automation_timer_watcher

        ensure_automation_timer_watcher(context, clients)
    if generation_commands:
        await enqueue_generation_commands(ws, context, clients, generation_commands)
    return True
