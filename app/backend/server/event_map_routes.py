# -*- coding: utf-8 -*-
"""이벤트 맵(Ctrl+E) — 태그를 꽂고 **같은 게시물에 실제로 함께 달린** 태그를 따라간다.

**조회 라우트는 읽기 전용이다.** 사용자 데이터를 쓰지 않고, 활성 프리셋·프롬프트·생성 상태를
건드리지 않는다. 프롬프트에 넣는 것은 프론트가 자기 입력칸에 하는 일이고(사용자 지시
2026-09-11: **삽입과 복사 둘 다** 지원), 여기서는 넣을 문자열을 주기만 한다.
명시적인 상태 변경 - 실제 조합의 [적용]·[생성] 및 Random 연결:
  POST /api/event-map/random-link 세션의 Random/Auto Gen 소스를 현재 맵 조건으로 연결·해제한다.
  POST /api/event-map/apply     조합을 **랜덤 프롬프트와 같은 파이프라인**에 태워 메인 프롬프트로 보낸다.
  POST /api/event-map/generate  조합을 가상 메인 프롬프트로 태워 **바이패스 생성**한다 - 이벤트 프리셋의
                                Generate 와 같은 경로라 메인 프롬프트는 그대로다(prompt_generated 를 안 쏜다).
⚠️ Fast Search(Ctrl+F)는 **클립보드 전용**이라 계약이 다르다 - 두 기능을 같은 규칙으로
   묶지 말 것(`app/backend/server/fast_search_routes.py` 머리 주석).

라우트 다섯. 모두 GET, 모두 `no-store`.

    GET /api/event-map/state              색인이 있나 · 어느 판인가 · 칩 목록과 상한
    GET /api/event-map/suggest?q=         꽂을 태그를 찾는다(한글 질의는 태그 사전을 거친다)
    GET /api/event-map/explore?pins=      핀 전부와 함께 달린 다음 후보
    GET /api/event-map/sample?pins=       핀을 포함하는 **실제 게시물**의 태그 조합
    GET /api/event-map/describe?tag=      그 태그가 맵에서 어떻게 다뤄지나

색인은 별도 파일(880MB~1.4GB)이고 기본 배포에 없다. **없는 것은 고장이 아니다** -
`/state` 가 `state: missing` 과 찾아본 경로를 돌려주고, 나머지 라우트는 503 + `code`
`unavailable` 을 준다. 내려받기는 **설치 관리자**가 한다(`POST /api/install-manager/event-map/download`,
루프백 전용) - `/state` 는 그 진행 상황을 `install` 에 실어 주고, 받는 중이면 `state: downloading`
이 된다. 이 라우트는 다운로드를 **시작하지 않는다**(GET 이 부작용을 내면 안 된다).

무거운 질의(교집합 + 집계)는 `run_in_thread` 로 넘긴다 - 이벤트 루프를 막지 않는다.
"""
from __future__ import annotations

import uuid
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.event_map.pe_filter import MAX_TAGS as PE_MAX_TAGS, hidden_by_prompt_engineering
from core.event_map.service import MapQueryError
from core.event_map.random_link import ensure_event_map_service, link_state
from core.web_session_context import WebSessionContext

AsyncRunner = Callable[..., Awaitable[Any]]


# `code` -> HTTP 상태. 나머지는 400.
STATUS_BY_CODE = {"unavailable": 503, "internal_error": 500, "library_error": 500, "duplicate": 409, "not_found": 404}


def _no_store() -> dict[str, str]:
    return {"Cache-Control": "no-store, max-age=0"}

def _install_view(context: WebSessionContext, can_start: bool) -> dict[str, Any]:
    """색인 다운로드 상황. 설치 관리자를 못 잡아도 /state 는 절대 실패하지 않는다.

    ⚠️ 다운로더는 **단일 비행**이다. 태그 아카이브를 받는 중이면 색인은 시작도 못 한다 -
       그 경우를 `busy_other` 로 구분해 준다("다른 다운로드가 끝나야 합니다").
    """
    try:
        from app.backend.server.install_manager_routes import runtime_install_manager

        snapshot = runtime_install_manager(context).snapshot()
    except Exception:
        return {}
    archive = snapshot.get("event_map")
    if not isinstance(archive, dict):
        return {}
    download = dict(archive.get("download") or {})
    running = bool(download.get("active"))
    mine = running and str(download.get("phase") or "") == "event_map"
    return {
        "ready": bool(archive.get("ready")),
        "downloadable": bool(archive.get("downloadable")),
        "approx_mb": archive.get("approx_mb"),
        "label": archive.get("label"),
        "active": mine,
        "busy_other": running and not mine,
        # 루프백에서만 시작할 수 있다 - 폰으로 열었으면 "PC 에서 받으세요" 를 띄워야 한다.
        "can_start": bool(can_start),
        "download": download,
    }


def invalidate_event_map_service(context: WebSessionContext) -> None:
    """내려받기·마이그레이션 뒤에 다시 찾게 한다."""
    service = getattr(context, "event_map_service", None)
    if service is not None:
        try:
            service.invalidate()
        except Exception:
            context.event_map_service = None


def _kr_lookup(context: WebSessionContext) -> Callable[[str, int], list[str]]:
    """한글 질의 -> 태그 이름 후보. 태그 사전이 없으면 빈 목록(영문 검색은 계속 된다).

    Fast Search 의 태그 갈래와 **같은 검색기**를 쓴다 - 한 칸에서 `가슴` 을 쳤을 때
    두 기능이 다른 태그를 내놓으면 사용자가 같은 사전을 두 번 배워야 한다.
    """
    def lookup(query: str, limit: int) -> list[str]:
        try:
            from app.backend.server.autocomplete_commands import search_kr_tags

            rows = search_kr_tags(context, query, limit=limit)
        except Exception:
            return []
        return [str(row.get("tag") or "") for row in rows if row.get("tag")]

    return lookup


def _error(exc: MapQueryError) -> JSONResponse:
    return JSONResponse(exc.to_payload(),
                        status_code=STATUS_BY_CODE.get(exc.code, 400),
                        headers=_no_store())


def _combo_source_row(payload: dict[str, Any]) -> dict[str, Any]:
    """실제 조합 하나를 검색 행 모양으로. 이벤트 프리셋의 source_row 와 같은 열을 둔다."""
    tags = payload.get("tags")
    if isinstance(tags, str):
        tags = [p.strip() for p in tags.split(",")]
    if not isinstance(tags, (list, tuple)):
        tags = []
    clean = [str(t or "").strip() for t in tags]
    clean = [t for t in clean if t]
    if not clean:
        raise ValueError("조합이 비어 있다.")
    if len(clean) > 200:
        raise ValueError("조합은 200개까지다.")
    rating = str(payload.get("rating") or "").strip()[:1]
    if rating not in {"g", "s", "q", "e"}:
        rating = "s"
    return {
        "general": ", ".join(clean),
        "rating": rating,
        "character": None, "copyright": None, "artist": None, "meta": None,
        "event_map_combo": True,
    }


async def _read_json(req: Request) -> dict[str, Any]:
    try:
        payload = await req.json()
    except Exception:
        payload = {}
    return payload if isinstance(payload, dict) else {}


def register_event_map_routes(
    app: FastAPI,
    session_context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
    clients: set[Any] | None = None,
    broadcast_json: Callable[..., Awaitable[None]] | None = None,
    start_generation_runner: Callable[..., Any] | None = None,
) -> None:
    async def _broadcast(message: dict[str, Any]) -> None:
        if clients is not None and broadcast_json is not None:
            await broadcast_json(clients, message)


    def _call(fn, *args, **kwargs):
        """서비스 호출을 스레드에서 돌리고 예외를 payload 로 바꾼다."""
        try:
            return fn(*args, **kwargs)
        except MapQueryError:
            raise
        except Exception as exc:                                  # pragma: no cover
            print(f"Headless Remote: event map query failed - {exc}", flush=True)
            raise MapQueryError("internal_error", str(exc)) from exc

    @app.get("/api/event-map/state")
    async def api_event_map_state(req: Request):
        """절대 실패하지 않는다. 색인이 없으면 `state: missing` + 찾아본 경로.

        색인이 준비되지 않았을 때만 `install`(다운로드 진행/가능 여부)을 얹는다. 받는 중이면
        `state` 를 `downloading` 으로 바꿔 화면이 검색 대신 진행 막대를 그리게 한다.
        """
        from app.backend.server.install_manager_routes import _is_local_request

        service = ensure_event_map_service(session_context)
        payload = await run_in_thread(service.status)
        payload["random_link"] = link_state(session_context)
        if payload.get("state") != "ready":
            install = await run_in_thread(_install_view, session_context, _is_local_request(req))
            if install:
                payload["install"] = install
                if install.get("active"):
                    payload["state"] = "downloading"
        return JSONResponse(payload, headers=_no_store())

    @app.get("/api/event-map/library")
    async def api_event_map_library():
        from core.event_map.library import EventMapLibrary
        try:
            payload = await run_in_thread(EventMapLibrary(session_context._save_path("event_map", "combinations.json")).list)
        except MapQueryError as exc:
            return _error(exc)
        return JSONResponse(payload, headers=_no_store())

    @app.post("/api/event-map/library")
    async def api_event_map_library_save(req: Request):
        from core.event_map.library import EventMapLibrary
        try:
            body = await _read_json(req)
            library = EventMapLibrary(session_context._save_path("event_map", "combinations.json"))
            payload = await run_in_thread(library.mutate if body.get("action") else library.save, body)
        except MapQueryError as exc:
            return _error(exc)
        return JSONResponse(payload, headers=_no_store())

    @app.get("/api/event-map/random-link")
    async def api_event_map_random_link_state():
        return JSONResponse(link_state(session_context), headers=_no_store())

    @app.post("/api/event-map/random-link")
    async def api_event_map_random_link(req: Request):
        payload = await _read_json(req)
        if not isinstance(payload.get("enabled"), bool):
            return JSONResponse({"message": "enabled must be boolean"}, status_code=400)
        state = {"enabled": payload["enabled"]}
        if state["enabled"]:
            for key in ("pins", "exclude", "ratings", "persons"):
                value = payload.get(key, "")
                if not isinstance(value, str) or len(value) > 8192:
                    return JSONResponse({"message": f"Invalid {key}"}, status_code=400)
                state[key] = value
            revision = link_state(session_context)["revision"] + 1
            session_context.event_map_random_link = {**state, "revision": revision, "pending": True}
            try:
                # Validate the same query used by Random. Empty matches are valid;
                # generation must fail closed rather than broaden the conditions.
                await run_in_thread(ensure_event_map_service(session_context).sample,
                                    **{k: state[k] for k in ("pins", "exclude", "ratings", "persons")}, n=1)
            except MapQueryError as exc:
                if link_state(session_context)["revision"] == revision:
                    session_context.event_map_random_link = {"enabled": False, "revision": revision}
                    await _broadcast({"type": "event_map_random_link", **link_state(session_context)})
                return _error(exc)
            if link_state(session_context)["revision"] != revision:
                return JSONResponse({"message": "다른 연결 설정이 적용되었습니다."}, status_code=409)
        state["revision"] = link_state(session_context)["revision"] + 1
        session_context.event_map_random_link = state
        from app.backend.server.generation_commands import invalidate_auto_gen_prefetch
        invalidate_auto_gen_prefetch(session_context)
        if state["enabled"] and session_context._coerce_bool(
                session_context.get_options().get("wildcard_standalone", False)):
            session_context.set_option("wildcard_standalone", False)
            await _broadcast({"type": "options", **session_context.get_options()})
            await _broadcast({"type": "toast", "level": "info",
                              "message": "이벤트 맵의 랜덤 버튼 연결을 위해 WC Solo를 자동 해제했습니다."})
        await _broadcast({"type": "event_map_random_link", **state})
        return JSONResponse(state, headers=_no_store())

    @app.get("/api/event-map/suggest")
    async def api_event_map_suggest(q: str = "", limit: int = 20):
        service = ensure_event_map_service(session_context)
        lookup = _kr_lookup(session_context)
        try:
            payload = await run_in_thread(
                _call, service.suggest, q, limit, kr_lookup=lookup)
        except MapQueryError as exc:
            return _error(exc)
        return JSONResponse(payload, headers=_no_store())

    @app.get("/api/event-map/explore")
    async def api_event_map_explore(pins: str = "", exclude: str = "", ratings: str = "",
                                    persons: str = "", roles: str = "", groups: str = "",
                                    limit: int = 24, sort: str = "lift", offset: int = 0, subcategory: str = ""):
        """색상 태그는 **항상** 후보에서 빠진다(켜는 파라미터를 두지 않는다 - 사용자 지정 2026-09-12).
        `groups` 는 접기 표의 갈래 id(쉼표) - 후보를 그 대분류로 가둔다."""
        service = ensure_event_map_service(session_context)
        try:
            payload = await run_in_thread(
                _call, service.explore, pins=pins, exclude=exclude, ratings=ratings,
                persons=persons, roles=roles, groups=groups, limit=limit, sort=sort, offset=offset, subcategory=subcategory)
        except MapQueryError as exc:
            return _error(exc)
        return JSONResponse(payload, headers=_no_store())

    @app.get("/api/event-map/browse")
    async def api_event_map_browse(group: str = "", ratings: str = "", persons: str = "",
                                   limit: int = 40, offset: int = 0, subcategory: str = ""):
        """첫 화면: 핀 없이 대분류 하나 → 그 인원·등급에서 특징적인 태그(코퍼스 대비 lift)."""
        service = ensure_event_map_service(session_context)
        try:
            payload = await run_in_thread(
                _call, service.browse, group=group, ratings=ratings, persons=persons, limit=limit, offset=offset, subcategory=subcategory)
        except MapQueryError as exc:
            return _error(exc)
        return JSONResponse(payload, headers=_no_store())

    @app.get("/api/event-map/sample")
    async def api_event_map_sample(pins: str = "", exclude: str = "", ratings: str = "",
                                   persons: str = "", n: int = 5, seed: str = ""):
        """뽑힌 조합의 `prompt` 가 프롬프트에 넣거나 복사할 문자열이다."""
        service = ensure_event_map_service(session_context)
        try:
            payload = await run_in_thread(
                _call, service.sample, pins=pins, exclude=exclude, ratings=ratings,
                persons=persons, n=n, seed=seed)
        except MapQueryError as exc:
            return _error(exc)
        return JSONResponse(payload, headers=_no_store())

    @app.get("/api/event-map/describe")
    async def api_event_map_describe(tag: str = ""):
        service = ensure_event_map_service(session_context)
        try:
            payload = await run_in_thread(_call, service.describe, tag)
        except MapQueryError as exc:
            return _error(exc)
        return JSONResponse(payload, headers=_no_store())

    @app.get("/api/event-map/pe-filter")
    async def api_event_map_pe_filter(tags: str = ""):
        """이 태그들 중 **지금 프롬프트 엔지니어링 설정**이 지우는 것(사용자 지정 2026-09-12 밤).

        후보 목록·실제 조합을 진한 회색으로 칠하는 데 쓴다. 색인이 없어도 답한다 - 설정은
        색인과 무관하다. 규칙은 생성이 쓰는 `apply_tag_filters` 그대로다.
        """
        items = [p.strip() for p in str(tags or "").split(",") if p.strip()]
        if len(items) > PE_MAX_TAGS:
            return JSONResponse(
                MapQueryError("too_many_tags", "태그는 %d개까지다." % PE_MAX_TAGS, limit=PE_MAX_TAGS).to_payload(),
                status_code=400, headers=_no_store())
        try:
            payload = await run_in_thread(hidden_by_prompt_engineering, session_context, items)
        except Exception as exc:                                  # pragma: no cover
            print(f"Headless Remote: event map pe-filter failed - {exc}", flush=True)
            return JSONResponse({"ok": False, "code": "internal_error", "message": str(exc)},
                                status_code=500, headers=_no_store())
        return JSONResponse(payload, headers=_no_store())

    @app.post("/api/event-map/apply")
    async def api_event_map_apply(req: Request):
        """[적용] 조합 → 랜덤 프롬프트와 **같은** 파이프라인(PE 앞뒤·auto hide·remove_*·와일드카드·
        인물 정렬) → 메인 프롬프트. Random 버튼이 하는 일과 같이 prompt_generated 를 **브로드캐스트**한다."""
        payload = await _read_json(req)
        try:
            source_row = _combo_source_row(payload)
        except ValueError as exc:
            return JSONResponse({"ok": False, "code": "bad_request", "message": str(exc)},
                                status_code=400, headers=_no_store())
        from app.backend.server.generation_commands import (
            _broadcast_wildcard_state, random_service)

        request_id = str(payload.get("requestId") or uuid.uuid4().hex)
        try:
            result = await run_in_thread(
                random_service(session_context).generate_from_source_row,
                source_row, random_request_id=request_id, source="event_map", update_context=True)
        except Exception as exc:                                  # pragma: no cover
            print(f"Headless Remote: event map apply failed - {exc}", flush=True)
            return JSONResponse({"ok": False, "code": "internal_error", "message": str(exc)},
                                status_code=500, headers=_no_store())
        if not result.success:
            return JSONResponse({"ok": False, "code": "pipeline_failed", "message": result.error},
                                status_code=400, headers=_no_store())
        await _broadcast(result.websocket_payload())
        for message in result.extra_messages:
            await _broadcast(message)
        if clients is not None:
            try:
                await _broadcast_wildcard_state(session_context, clients)
            except Exception:
                pass
        return JSONResponse({"ok": True, "prompt": result.prompt, "requestId": request_id,
                             "promptRunId": result.prompt_run_id}, headers=_no_store())

    @app.post("/api/event-map/generate")
    async def api_event_map_generate(req: Request):
        """[생성] 조합을 가상 메인 프롬프트로 파이프라인에 태우고 바이패스로 생성한다.

        이벤트 프리셋의 Generate 와 **같은 함수**를 쓴다(`_generate_event_preset_prompt` 는 파이프라인을
        돌린 뒤 메인 프롬프트·컨텍스트를 되돌린다). 다른 점 하나: prompt_generated 를 쏘지 않는다 -
        메인 프롬프트를 오염시키지 않는 것이 이 단추의 뜻이다. 모드별 도구(캐릭터 등)는 파이프라인과
        생성 서비스가 세션 상태에서 그대로 참조한다.
        """
        payload = await _read_json(req)
        try:
            source_row = _combo_source_row(payload)
        except ValueError as exc:
            return JSONResponse({"ok": False, "code": "bad_request", "message": str(exc)},
                                status_code=400, headers=_no_store())
        from app.backend.server.event_preset_routes import (
            _generate_event_preset_prompt, _generation_service, _preset_source_to_generation_command)

        request_id = str(payload.get("requestId") or uuid.uuid4().hex)
        try:
            processed = await run_in_thread(
                _generate_event_preset_prompt, session_context, source_row,
                overrides={}, request_id=request_id, source="event_map")
            if not processed.success:
                return JSONResponse({"ok": False, "code": "pipeline_failed",
                                     "message": processed.error or "prompt processing failed"},
                                    status_code=400, headers=_no_store())
            result = {"requestId": request_id, "sourceRow": source_row, "sourceName": f"event_map:{request_id}"}
            command = _preset_source_to_generation_command(
                session_context, result, source="preset", overrides={},
                prompt_override=processed.prompt, prompt_run_id_override=processed.prompt_run_id)
            command["overrides"]["_remote_queue_label"] = "event_map"
            dispatch = await run_in_thread(_generation_service(session_context).enqueue_remote_request, command)
        except RuntimeError as exc:
            return JSONResponse({"ok": False, "code": "blocked", "message": str(exc)},
                                status_code=409, headers=_no_store())
        except ValueError as exc:
            return JSONResponse({"ok": False, "code": "bad_request", "message": str(exc)},
                                status_code=400, headers=_no_store())
        except Exception as exc:                                  # pragma: no cover
            print(f"Headless Remote: event map generate failed - {exc}", flush=True)
            return JSONResponse({"ok": False, "code": "internal_error", "message": str(exc)},
                                status_code=500, headers=_no_store())
        if not dispatch.ok:
            return JSONResponse({"ok": False, "code": "blocked", **dispatch.websocket_payload()},
                                status_code=409, headers=_no_store())
        if start_generation_runner is not None and clients is not None \
                and getattr(session_context, "headless_generation_execute_enabled", False):
            start_generation_runner(session_context, clients)
        return JSONResponse({"ok": True, "status": "generation_requested", "requestId": request_id,
                             "prompt": processed.prompt, "promptRunId": processed.prompt_run_id},
                            headers=_no_store())

    @app.get("/api/event-map/resolve")
    async def api_event_map_resolve(tags: str = ""):
        """프롬프트의 태그들을 한 번에 맵 어휘로 푼다(패널이 열릴 때 씨앗 칩을 만든다).

        인원 태그는 `person_group` 으로 따로 돌려준다 - 핀이 아니라 분면 필터로 써야 한다.
        """
        service = ensure_event_map_service(session_context)
        try:
            payload = await run_in_thread(_call, service.resolve_many, tags)
        except MapQueryError as exc:
            return _error(exc)
        return JSONResponse(payload, headers=_no_store())
