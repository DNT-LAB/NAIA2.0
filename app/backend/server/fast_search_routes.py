"""Fast Search (Ctrl+F) — 한 칸에서 태그·아티스트·캐릭터·와일드카드·프리셋·이벤트를 찾는다.

**읽기 전용이다.** 이 라우트는 어떤 사용자 데이터도 쓰지 않고, 활성 프리셋·프롬프트·
생성 상태를 건드리지 않는다. 고른 결과는 **클립보드로만** 간다(사용자 지시 2026-09-05)
— 메인 프롬프트에 자동으로 넣지 않는다.

갈래별 검색 소유권:

    tag/artist  autocomplete_commands.search_kr_tags   (`@`/`artist:` 접두어로 갈래)
    character   ollama_chat_tools.search_characters    (도감 - 작품·수록 수를 안다)
    wildcard    autocomplete_commands.search_wildcards
    preset      prompt_engineering_settings            (파일 목록 + 저장된 내용)
    event       event_preset.fast_search_catalog         (기본 제공 정적 관측 조합)

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


def _search_event(context, query: str, limit: int, opts) -> tuple[list[dict], str]:
    from core.event_preset.fast_search_catalog import search_catalog

    rating = str(opts.get("rating") or "").strip().casefold()
    person = str(opts.get("person") or "").strip()
    if rating and rating not in {"g", "s", "q", "e"}:
        return [], "알 수 없는 이벤트 등급입니다."
    matches = search_catalog(query, limit, rating=rating, person=person)
    items = []
    for event, variant in matches:
        tags = variant.copy_tags
        title = event.tag if event.label == event.tag else f"{event.tag} · {event.label}"
        meta = f"{variant.rating.upper()} · {variant.person.replace('_', ' ')} · {len(tags)}태그 · 관측 {variant.count:,}"
        items.append(_item(", ".join(tags), title, ", ".join(tags), meta))
    scope = f"{rating.upper() if rating else '전체 등급'} · {person if person else '전체 인원'}"
    return items, f"{scope} · 기본 제공 조합"


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
                              rating: str = "", person: str = "", mode: str = ""):
        query = str(q or "").strip()
        if len(query) > MAX_QUERY:
            return JSONResponse({"error": "검색어가 너무 깁니다."}, status_code=400,
                                headers=_no_store())
        wanted = [s for s in (sources or "").split(",") if s.strip()] or list(SOURCE_ORDER)
        unknown = [s for s in wanted if s not in SEARCHERS]
        if unknown:
            return JSONResponse({"error": f"알 수 없는 검색 갈래: {', '.join(unknown)}"},
                                status_code=400, headers=_no_store())
        per_source = max(1, min(MAX_LIMIT, int(limit or DEFAULT_LIMIT)))
        opts = {"rating": rating, "person": person, "mode": mode}

        def run_all():
            groups = []
            for source in SOURCE_ORDER:
                if source not in wanted:
                    continue
                items, note = [], ""
                # 와일드카드는 빈 쿼리로 전체 목록을 내는 계약이라 그대로 둔다.
                # 나머지는 빈 쿼리에 온 사전을 쏟지 않는다.
                if query or source == "wildcard":
                    try:
                        items, note = SEARCHERS[source](session_context, query, per_source, opts)
                    except Exception as exc:
                        items, note = [], f"검색 실패: {exc}"
                groups.append({"source": source, "label": SOURCE_LABELS[source],
                               "items": items, "note": note})
            return groups

        groups = await run_in_thread(run_all)
        return JSONResponse({"query": query, "groups": groups,
                             "total": sum(len(g["items"]) for g in groups)},
                            headers=_no_store())
