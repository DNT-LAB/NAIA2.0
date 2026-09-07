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


_neighbor_warm_started = False


def _warm_neighbor_index_once() -> None:
    """첫 이벤트 검색에서 한 번, 이웃 조회용 색인을 뒤에서 데운다(첫 섬이 1.2초 걸리지 않게)."""
    global _neighbor_warm_started
    if _neighbor_warm_started:
        return
    _neighbor_warm_started = True
    from core.event_preset.fast_search_catalog import warm_neighbor_index
    import threading

    def run():
        try:
            warm_neighbor_index()
        except Exception:
            pass        # 데우기 실패는 조용히 - 실제 조회가 다시 시도한다
    threading.Thread(target=run, name='fast-search-neighbor-warm', daemon=True).start()


def _search_event(context, query: str, limit: int, opts) -> tuple[list[dict], str]:
    from core.event_preset.fast_search_catalog import search_catalog

    # 등급·인원은 쉼표로 여럿 올 수 있다(한 줄 토글). 검증은 카탈로그가 한다 - 모르는
    # 값이 하나라도 있으면 빈 결과지, 넓어지는 일은 없다.
    rating = str(opts.get("rating") or "").strip().casefold()
    person = str(opts.get("person") or "").strip()
    detail = str(opts.get('event_detail') or 'basic')
    # 페이징: search_catalog 는 결정적이고 앞에서부터 채우므로 `offset+limit` 로 부른 뒤
    # 앞 offset 개를 잘라내면 **안정된 다음 쪽**이 된다(앞쪽은 limit 이 커져도 같다).
    # 프론트가 '더 보기' 버튼 없이 스크롤로 이어 받는다(사용자 지정 2026-09-07).
    offset = max(0, int(opts.get('event_offset') or 0))
    fetched = search_catalog(query, offset + limit, rating=rating, person=person, detail=detail)
    matches = fetched[offset:]
    # 요청한 만큼 못 채웠으면 이 phase 는 끝이다 - 프론트가 다음 단계(deep)로 넘어간다.
    exhausted = len(fetched) < offset + limit
    items = []
    for event, variant in matches:
        tags = variant.copy_tags
        title = event.tag if event.label == event.tag else f"{event.tag} · {event.label}"
        meta = f"{variant.rating.upper()} · {variant.person.replace('_', ' ')} · {len(tags)}태그 · 관측 {variant.count:,}"
        row = _item(", ".join(tags), title, ", ".join(tags), meta)
        # 앵커(핵심 태그) - 프론트가 이웃 조회(/event-neighbors)에 되돌려 보낸다.
        row["anchor"] = event.tag
        items.append(row)
    # 등급·인원 문구는 뺐다 - 토글 줄이 이미 보여 주는 것을 캡션이 한 번 더 반복했다
    # (사용자 지적 2026-09-07).
    note = f"{'9–16태그' if detail == 'deep' else '3–8태그'} 조합"
    # 결과를 다 만든 뒤에 데운다 - 앞에서 시작하면 데우기가 잡은 락에 이 검색이 기다린다.
    _warm_neighbor_index_once()
    # 세 번째 값은 갈래별 부가 정보 - run_all 이 group 에 얹는다.
    return items, note, {"exhausted": exhausted, "offset": offset}


def _event_neighbor_items(anchor: str, tags: list[str], rating: str, person: str, limit: int) -> dict:
    """고른 조합의 이웃. (1) 전부 포함하는 더 긴 조합 (2) 앵커를 뺀 나머지가 한 태그만 다른 조합.
    (1)에 든 것은 (2)에 다시 나오지 않는다(사용자 지정 2026-09-07). 읽기 전용."""
    from core.event_preset.fast_search_catalog import event_neighbors

    found = event_neighbors(anchor, tags, rating=rating, person=person, limit=limit)

    def rows(matches):
        out = []
        for event, variant, detail in matches:
            copy = variant.copy_tags
            title = event.tag if event.label == event.tag else f"{event.tag} · {event.label}"
            meta = (f"{variant.rating.upper()} · {variant.person.replace('_', ' ')} · {len(copy)}태그"
                    f" · 관측 {variant.count:,}")
            row = _item(", ".join(copy), title, ", ".join(copy), meta)
            row["anchor"] = event.tag
            row["detail"] = detail
            out.append(row)
        return out

    return {"supersets": rows(found["supersets"]), "near": rows(found["near"])}


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
                              event_offset: int = 0):
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
        opts = {"rating": rating, "person": person, "mode": mode, 'event_detail': event_detail,
                'event_offset': event_offset}

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
        if len(chosen) > 32:
            return JSONResponse({"error": "태그가 너무 많습니다."}, status_code=400, headers=_no_store())
        per_group = max(1, min(60, int(limit or 20)))
        payload = await run_in_thread(
            lambda: _event_neighbor_items(anchor_tag, chosen, rating, person, per_group))
        payload["anchor"] = anchor_tag
        payload["tags"] = chosen
        return JSONResponse(payload, headers=_no_store())
