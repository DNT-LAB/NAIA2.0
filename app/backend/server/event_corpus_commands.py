"""Event Corpus Search WS 커맨드.

``app/backend/server/autocomplete_commands.py`` 의 커맨드 핸들러 형태를 그대로 따른다:
커맨드 타입 집합 + 단일 ``handle_*_command(ws, context, command, *, run_in_thread) -> bool``.

질의는 ``websocket_session.LIVE_DISPATCH_TYPES`` 로 백그라운드 디스패치된다. 무거운 집계가
receive 루프를 막지 않게 하되, 칩 연타로 대형 집계가 동시에 쌓이지 않도록 연결별 seq guard 로
latest-wins 코얼레싱을 건다(tag_filter_search 와 동일한 기법, 별도 카운터).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import WebSocket

from core.event_corpus_search_service import EventCorpusSearchService, QueryError
from core.web_session_context import WebSessionContext


AsyncRunner = Callable[..., Awaitable[Any]]

EVENT_CORPUS_COMMAND_TYPES = {
    "event_corpus_status",
    "event_corpus_query",
}


def _data_roots(context: WebSessionContext) -> list[Path]:
    """autocomplete_commands._tag_data_roots 와 동일한 우선순위.

    runtime user-data 가 먼저다. 마이그레이션/다운로드된 코퍼스가 그쪽에 떨어진다.
    """
    roots: list[Path] = []
    runtime_paths = getattr(context, "runtime_paths", None)
    if runtime_paths is not None:
        roots.append(Path(runtime_paths.data_dir))
    roots.append(Path(context.repo_root) / "data")
    return roots


_SERVICE_LOCK = threading.Lock()


def ensure_event_corpus_service(context: WebSessionContext) -> EventCorpusSearchService:
    service = getattr(context, "event_corpus_service", None)
    if service is not None:
        return service
    # 최초 동시 질의 두 개가 각자 index/service 를 만들어 파티션을 중복 로드하지 않도록.
    with _SERVICE_LOCK:
        service = getattr(context, "event_corpus_service", None)
        if service is not None:
            return service
        from core.event_corpus_index import EventCorpusIndex

        index = EventCorpusIndex(_data_roots(context))
        service = EventCorpusSearchService(index)
        context.event_corpus_service = service
        return service


def invalidate_event_corpus_service(context: WebSessionContext) -> None:
    """마이그레이션/다운로드 이후 캐시를 버린다."""
    service = getattr(context, "event_corpus_service", None)
    if service is not None:
        try:
            service.invalidate()
        except Exception:
            context.event_corpus_service = None


async def _send_json(ws: WebSocket, payload: dict[str, Any]) -> None:
    await ws.send_text(json.dumps(payload, ensure_ascii=False))


def _status(context: WebSessionContext) -> dict[str, Any]:
    try:
        return ensure_event_corpus_service(context).status()
    except Exception as exc:  # pragma: no cover - 상태 조회는 절대 실패시키지 않는다
        print(f"Headless Remote: event corpus status failed - {exc}", flush=True)
        return {"ok": True, "state": "missing", "message": str(exc), "partitions": {}}


def _query(context: WebSessionContext, payload: dict[str, Any], should_abort) -> dict[str, Any]:
    service = ensure_event_corpus_service(context)
    try:
        return service.query(payload, should_abort=should_abort)
    except QueryError as exc:
        return exc.to_payload()
    except Exception as exc:  # pragma: no cover
        print(f"Headless Remote: event corpus query failed - {exc}", flush=True)
        return {"ok": False, "code": "internal_error", "message": str(exc)}


async def handle_event_corpus_command(
    ws: WebSocket,
    context: WebSessionContext,
    command: dict[str, Any],
    *,
    run_in_thread: AsyncRunner,
) -> bool:
    command_type = str(command.get("type") or "").strip()
    if command_type not in EVENT_CORPUS_COMMAND_TYPES:
        return False

    request_id = str(command.get("requestId") or command.get("request_id") or "")

    if command_type == "event_corpus_status":
        result = await run_in_thread(_status, context)
        await _send_json(ws, {
            "type": "event_corpus_status_result",
            "requestId": request_id,
            **result,
        })
        return True

    # event_corpus_query
    seq = command.get("_seq")
    seq_guard = command.get("_seq_guard")

    def _superseded() -> bool:
        if seq is None or not isinstance(seq_guard, dict):
            return False
        return seq_guard.get("seq", seq) != seq

    payload = {
        "rating": command.get("rating"),
        "person": command.get("person"),
        "include": command.get("include"),
        "exclude": command.get("exclude"),
        "search": command.get("search"),
        "offset": command.get("offset"),
        "limit": command.get("limit"),
    }
    result = await run_in_thread(_query, context, payload, _superseded)

    if result.get("code") == "aborted":
        return True

    # 백엔드 stale-send guard. 프론트의 requestId 비교는 2차 방어선이지 1차가 아니다.
    #
    # ws.send 는 연결별 Lock 으로 직렬화된다(websocket_session 의 _locked_send). 그래서
    # 검사와 실제 송신 사이에 lock 대기가 끼어들 수 있고, 그 사이 새 질의가 guard 를 올린다.
    # 따라서 send 를 감싼 게 아니라 **송신 직전에 다시** 확인한다. 완전한 원자성은 아니지만
    # 창이 lock 대기 구간에서 send 호출 직전 한 프레임으로 줄어든다.
    if _superseded():
        return True
    payload_out = {
        "type": "event_corpus_query_result",
        "requestId": request_id,
        **result,
    }
    if _superseded():
        return True
    await _send_json(ws, payload_out)
    return True


# ----------------------------------------------------------------------
# Interactive 생성 게이트
# ----------------------------------------------------------------------

# Interactive 모드는 프롬프트를 블록에서 결정론적으로 조립한다. prompt_fixed(랜덤 생성 잠금)와
# wildcard_standalone(DB 태그 없이 빈 source_row 시작)은 그 전제와 충돌한다 — 무해한 no-op 이
# 아니라 서로 다른 소스를 다투게 된다.
#
# 세션 옵션(set_option)으로 끄면 안 된다: set_option 은 전 클라이언트에 broadcast 되고
# (session_commands.py) remote_options 로 영속된다(headless_remote_ui_state_service.py).
# 한 탭이 Interactive 를 켜면 다른 탭의 설정이 꺼지고 그 값이 저장돼 버린다.
# 따라서 **요청 단위로만** 강제한다.
INTERACTIVE_FORCED_PARAMS = {
    "interactive_mode_request": True,   # core/auto_generation_flags.py 의 기존 마커 재사용
    "prompt_fixed": False,
    "wildcard_standalone": False,
}


def apply_interactive_generation_gate(params: dict[str, Any]) -> dict[str, Any]:
    """Interactive 생성 요청에 플래그를 강제한다. 저장된 사용자 옵션은 건드리지 않는다.

    ``interactive_mode_request`` 는 AUTO_GENERATE_SUPPRESSED_FLAGS 에 이미 등록돼 있어
    Auto Generate 연쇄와 Automation 카운트에서 자동 제외된다.
    """
    if not isinstance(params, dict):
        return dict(INTERACTIVE_FORCED_PARAMS)
    params.update(INTERACTIVE_FORCED_PARAMS)
    return params
