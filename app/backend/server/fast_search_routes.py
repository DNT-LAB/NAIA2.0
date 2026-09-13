"""Fast Search (Ctrl+F) — 한 칸에서 태그·아티스트·캐릭터·와일드카드·프리셋·이벤트를 찾는다.

**읽기 전용이다.** 이 라우트는 어떤 사용자 데이터도 쓰지 않고, 활성 프리셋·프롬프트·
생성 상태를 건드리지 않는다. 고른 결과는 복사하거나 이벤트 맵 검색 조건으로 넘긴다.
메인 프롬프트에 자동으로 넣지 않는다.

갈래별 검색 소유권:

    tag/artist  autocomplete_commands.search_kr_tags   (`@`/`artist:` 접두어로 갈래)
    character   ollama_chat_tools.search_characters    (도감 - 작품·수록 수를 안다)
    wildcard    autocomplete_commands.search_wildcards
    preset      prompt_engineering_settings            (파일 목록 + 저장된 내용)
    event       event_map.quick_search                  (현재 naiamap 관측 조합)

⚠️ **한 갈래가 실패해도 나머지는 낸다.** 실패한 갈래는 빈 목록 + `note` 로
   이유를 말한다. 이벤트 검색에는 별도 Event Preset 다운로드가 필요 없다.
"""
from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from core.web_session_context import WebSessionContext

AsyncRunner = Callable[..., Any]

# 화면에 보이는 순서이자 기본 검색 순서.
SOURCE_ORDER = ("tag", "artist", "character", "wildcard", "preset", "event")
SOURCE_LABELS = {
    "tag": "태그", "artist": "아티스트", "character": "캐릭터",
    "wildcard": "와일드카드", "preset": "프리셋", "event": "이벤트",
}
MAX_QUERY = 160
DEFAULT_LIMIT = 8
MAX_LIMIT = 20


def _no_store() -> dict[str, str]:
    return {"Cache-Control": "no-store, max-age=0"}


def _item(value: str, title: str, subtitle: str = "", meta: str = "") -> dict[str, Any]:
    """`value` 가 클립보드로 가는 것이다. 화면 문구(title/subtitle)와 섞지 않는다."""
    return {"value": str(value or ""), "title": str(title or value or ""),
            "subtitle": str(subtitle or "")[:160], "meta": str(meta or "")}


def _count_meta(count: Any) -> str:
    try:
        n = int(count or 0)
    except (TypeError, ValueError):
        return ""
    return f"{n:,}" if n else ""


# ── 갈래별 검색기 ──────────────────────────────────────────────────────────

def _search_tag(context, query: str, limit: int, _opts) -> tuple[list[dict], str]:
    from app.backend.server.autocomplete_commands import search_kr_tags

    rows = search_kr_tags(context, query, limit=limit)
    items = [_item(r["tag"], r["tag"], r.get("desc") or r.get("group") or "",
                   _count_meta(r.get("count"))) for r in rows]
    return items, ""


def _search_artist(context, query: str, limit: int, _opts) -> tuple[list[dict], str]:
    from app.backend.server.autocomplete_commands import search_kr_tags

    # `@` 접두어가 search_kr_tags 의 autocomplete 레인을 artist 로 좁히지만,
    # ⚠️ 한글 쿼리의 **메타데이터 폴백은 그 갈래를 안 지킨다** — 실측(2026-09-05):
    #    `@가슴` 이 `breasts`·`large breasts`·`cleavage` 를 함께 냈다. 아티스트
    #    칸에 일반 태그가 섞이면 갈래를 나눈 의미가 없으므로 여기서 다시 거른다.
    #    (같은 누수가 프롬프트 입력칸의 `@` 자동완성에도 있다 - 별건.)
    rows = [r for r in search_kr_tags(context, f"@{query}", limit=limit * 3)
            if str(r.get("cat") or "").strip().lower() == "artist"]
    items = [_item(r["tag"], r["tag"], r.get("desc") or "", _count_meta(r.get("count")))
             for r in rows[:limit]]
    return items, ""


def _search_character(context, query: str, limit: int, _opts) -> tuple[list[dict], str]:
    from app.backend.server.ollama_chat_tools import search_characters
    from app.backend.server.autocomplete_commands import _ensure_kr_raw

    _ensure_kr_raw(context)
    payload = search_characters(context, query)
    rows = payload.get("characters") or []
    items = [_item(r["tag"], r["tag"], str(r.get("work") or ""), _count_meta(r.get("count")))
             for r in rows[:limit]]
    return items, "" if items else ""


def _search_wildcard(context, query: str, limit: int, _opts) -> tuple[list[dict], str]:
    from app.backend.server.autocomplete_commands import search_wildcards

    rows = search_wildcards(context, query, limit=limit)
    # 쓸 수 있는 형태로 준다 - 키 이름이 아니라 프롬프트에 그대로 넣는 `__key__` 다.
    items = [_item(f"__{r['tag']}__", f"__{r['tag']}__", r.get("desc") or "",
                   _count_meta(r.get("count"))) for r in rows]
    return items, ""


def _search_preset(context, query: str, limit: int, opts) -> tuple[list[dict], str]:
    from core.prompt_engineering_settings import (
        list_preset_names, normalize_prompt_engineering_mode, read_preset_data,
    )

    save_root = context.runtime_paths.save_dir
    mode = normalize_prompt_engineering_mode(opts.get("mode") or context.get_api_mode())
    needle = query.strip().casefold()
    items: list[dict[str, Any]] = []
    for name in list_preset_names(mode, save_root=save_root):
        if needle and needle not in name.casefold():
            continue
        data = read_preset_data(name, mode, save_root=save_root) or {}
        module = data.get("module_settings") if isinstance(data, dict) else {}
        prefix = str((module or {}).get("pre_prompt") or "")
        # 이름을 복사한다. 본문은 미리보기(Quick Preset 판)가 보여 주는 것이고,
        # 여기서 통째로 복사하면 사용자가 원하지 않은 긴 문자열이 나간다.
        items.append(_item(name, name, prefix, mode))
        if len(items) >= limit:
            break
    return items, f"{mode} 모드에 저장된 프리셋" if items else ""


def _search_event(context, query: str, limit: int, opts):
    from core.event_map.quick_search import search
    from app.backend.server.event_map_routes import _kr_lookup, _install_view
    from core.event_map.service import MapQueryError
    try:
        return search(context, query, limit, opts, _kr_lookup(context))
    except MapQueryError as exc:
        if exc.code != "unavailable":
            raise
        downloading = bool(_install_view(context, can_start=False).get("active"))
        note = "다운로드 중" if downloading else "이벤트 맵 파일이 없습니다. 이벤트 맵에서 다운로드해주세요."
        return [], note, {"state": "downloading" if downloading else "unavailable",
                          "exhausted": True, "events": []}



def _event_neighbor_items(context, anchor, tags, rating, person, limit):
    from core.event_map.quick_search import neighbors
    return neighbors(context, anchor, tags, rating, person, limit)


SEARCHERS = {
    "tag": _search_tag, "artist": _search_artist, "character": _search_character,
    "wildcard": _search_wildcard, "preset": _search_preset, "event": _search_event,
}


def register_fast_search_routes(
    app: FastAPI,
    session_context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
) -> None:

    @app.get("/api/fast-search")
    async def api_fast_search(q: str = "", sources: str = "", limit: int = DEFAULT_LIMIT,
                              rating: str = "", person: str = "", mode: str = "", event_detail: str = "basic",
                              event_offset: int = 0, event_exclude: str = ""):
        query = str(q or "").strip()
        if len(query) > MAX_QUERY:
            return JSONResponse({"error": "검색어가 너무 깁니다."}, status_code=400,
                                headers=_no_store())
        wanted = [s for s in (sources or "").split(",") if s.strip()] or list(SOURCE_ORDER)
        unknown = [s for s in wanted if s not in SEARCHERS]
        if unknown:
            return JSONResponse({"error": f"알 수 없는 검색 갈래: {', '.join(unknown)}"},
                                status_code=400, headers=_no_store())
        if 'event' in wanted and event_detail not in {'basic', 'deep'}:
            return JSONResponse({'error': '알 수 없는 이벤트 상세 범위입니다.'}, status_code=400, headers=_no_store())
        per_source = max(1, min(MAX_LIMIT, int(limit or DEFAULT_LIMIT)))
        if event_offset < 0 or event_offset > 10000:
            return JSONResponse({"error": "이벤트 offset 이 범위를 벗어났습니다."}, status_code=400,
                                headers=_no_store())
        if len(event_exclude) > 4000:
            return JSONResponse({"error": "제외 이벤트 목록이 너무 깁니다."}, status_code=400,
                                headers=_no_store())
        opts = {"rating": rating, "person": person, "mode": mode, 'event_detail': event_detail,
                'event_offset': event_offset, 'event_exclude': event_exclude}

        def run_all():
            groups = []
            for source in SOURCE_ORDER:
                if source not in wanted:
                    continue
                items, note = [], ""
                # 와일드카드는 빈 쿼리로 전체 목록을 내는 계약이라 그대로 둔다.
                # 나머지는 빈 쿼리에 온 사전을 쏟지 않는다.
                extra = {}
                if query or source == "wildcard":
                    try:
                        result = SEARCHERS[source](session_context, query, per_source, opts)
                        items, note = result[0], result[1]
                        extra = result[2] if len(result) > 2 and isinstance(result[2], dict) else {}
                    except Exception as exc:
                        items, note = [], f"검색 실패: {exc}"
                groups.append({"source": source, "label": SOURCE_LABELS[source],
                               "items": items, "note": note, **extra})
            return groups

        groups = await run_in_thread(run_all)
        return JSONResponse({"query": query, "groups": groups,
                             "total": sum(len(g["items"]) for g in groups)},
                            headers=_no_store())

    @app.get("/api/fast-search/event-neighbors")
    async def api_fast_search_event_neighbors(tags: str = "", anchor: str = "", rating: str = "",
                                              person: str = "", limit: int = 20):
        """고른 이벤트 조합의 이웃(아래 섬). 클립보드 후보일 뿐 - 아무것도 쓰지 않는다."""
        chosen = [t.strip() for t in str(tags or "").split(",") if t.strip()]
        anchor_tag = str(anchor or "").strip()
        if not chosen or not anchor_tag or len(tags) > 1200:
            return JSONResponse({"error": "tags 와 anchor 가 필요합니다."}, status_code=400,
                                headers=_no_store())
        if not 3 <= len(chosen) <= 8:
            return JSONResponse({"error": "조합은 3~8개 태그여야 합니다."}, status_code=400, headers=_no_store())
        per_group = max(1, min(60, int(limit or 20)))
        from core.event_map.service import MapQueryError
        try:
            payload = await run_in_thread(
                lambda: _event_neighbor_items(session_context, anchor_tag, chosen, rating, person, per_group))
        except MapQueryError as exc:
            return JSONResponse(exc.to_payload(), status_code=503 if exc.code == "unavailable" else 400,
                                headers=_no_store())
        payload["anchor"] = anchor_tag
        payload["tags"] = chosen
        return JSONResponse(payload, headers=_no_store())
