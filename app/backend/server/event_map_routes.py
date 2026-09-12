# -*- coding: utf-8 -*-
"""이벤트 맵(Ctrl+E) — 태그를 꽂고 **같은 게시물에 실제로 함께 달린** 태그를 따라간다.

**읽기 전용이다.** 이 라우트는 사용자 데이터를 쓰지 않고, 활성 프리셋·프롬프트·생성 상태를
건드리지 않는다. 프롬프트에 넣는 것은 프론트가 자기 입력칸에 하는 일이고(사용자 지시
2026-09-11: **삽입과 복사 둘 다** 지원), 여기서는 넣을 문자열을 주기만 한다.
⚠️ Fast Search(Ctrl+F)는 **클립보드 전용**이라 계약이 다르다 - 두 기능을 같은 규칙으로
   묶지 말 것(`app/backend/server/fast_search_routes.py` 머리 주석).

라우트 다섯. 모두 GET, 모두 `no-store`.

    GET /api/event-map/state              색인이 있나 · 어느 판인가 · 칩 목록과 상한
    GET /api/event-map/suggest?q=         꽂을 태그를 찾는다(한글 질의는 태그 사전을 거친다)
    GET /api/event-map/explore?pins=      핀 전부와 함께 달린 다음 후보
    GET /api/event-map/sample?pins=       핀을 포함하는 **실제 게시물**의 태그 조합
    GET /api/event-map/describe?tag=      그 태그가 맵에서 어떻게 다뤄지나

색인은 별도 파일(744MB~1.4GB)이고 기본 배포에 없다. **없는 것은 고장이 아니다** -
`/state` 가 `state: missing` 과 찾아본 경로를 돌려주고, 나머지 라우트는 503 + `code`
`unavailable` 을 준다. 화면은 그때 내려받기를 안내해야 한다.

무거운 질의(교집합 + 집계)는 `run_in_thread` 로 넘긴다 - 이벤트 루프를 막지 않는다.
"""
from __future__ import annotations

import threading
from typing import Any, Awaitable, Callable

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from core.event_map.service import EventMapService, MapQueryError, default_roots
from core.web_session_context import WebSessionContext

AsyncRunner = Callable[..., Awaitable[Any]]

_SERVICE_LOCK = threading.Lock()

# `code` -> HTTP 상태. 나머지는 400.
STATUS_BY_CODE = {"unavailable": 503, "internal_error": 500}


def _no_store() -> dict[str, str]:
    return {"Cache-Control": "no-store, max-age=0"}


def ensure_event_map_service(context: WebSessionContext) -> EventMapService:
    """세션에 하나만 둔다. 색인은 1GB 대라 두 번 열면 mmap 도 두 배가 된다."""
    service = getattr(context, "event_map_service", None)
    if service is not None:
        return service
    with _SERVICE_LOCK:
        service = getattr(context, "event_map_service", None)
        if service is not None:
            return service
        service = EventMapService(default_roots(context))
        context.event_map_service = service
        return service


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


def register_event_map_routes(
    app: FastAPI,
    session_context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
) -> None:

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
    async def api_event_map_state():
        """절대 실패하지 않는다. 색인이 없으면 `state: missing` + 찾아본 경로."""
        service = ensure_event_map_service(session_context)
        payload = await run_in_thread(service.status)
        return JSONResponse(payload, headers=_no_store())

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
                                    limit: int = 24):
        """색상 태그는 **항상** 후보에서 빠진다(켜는 파라미터를 두지 않는다 - 사용자 지정 2026-09-12).
        `groups` 는 접기 표의 갈래 id(쉼표) - 후보를 그 대분류로 가둔다."""
        service = ensure_event_map_service(session_context)
        try:
            payload = await run_in_thread(
                _call, service.explore, pins=pins, exclude=exclude, ratings=ratings,
                persons=persons, roles=roles, groups=groups, limit=limit)
        except MapQueryError as exc:
            return _error(exc)
        return JSONResponse(payload, headers=_no_store())

    @app.get("/api/event-map/browse")
    async def api_event_map_browse(group: str = "", ratings: str = "", persons: str = "",
                                   limit: int = 40):
        """첫 화면: 핀 없이 대분류 하나 → 그 인원·등급에서 특징적인 태그(코퍼스 대비 lift)."""
        service = ensure_event_map_service(session_context)
        try:
            payload = await run_in_thread(
                _call, service.browse, group=group, ratings=ratings, persons=persons, limit=limit)
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
