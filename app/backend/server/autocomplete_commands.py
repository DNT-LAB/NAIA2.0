from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import WebSocket

from app.backend.server.preset_services import (
    clothes_preset_service,
    event_preset_service,
    expression_preset_service,
)
from app.backend.server.prompt_tools_routes import tag_lookup_info
from core.web_session_context import WebSessionContext
from utils.translator import english_to_korean, korean_to_english


AsyncRunner = Callable[..., Awaitable[Any]]

AUTOCOMPLETE_COMMAND_TYPES = {
    "tag_search",
    "tag_filter_ac",
    "autocomplete",
    "autocomplete_translate",
    "autocomplete_wildcard",
    "autocomplete_chunk",
    "autocomplete_vibe_cluster",
    "autocomplete_preset",
    "tag_lookup",
    "translate_text",
    "interactive_autocomplete",
    "interactive_related",
}

# Interactive 슬롯 <-> group 매핑.
#
# 축(tag_axis_overrides)이 아니라 group 으로 거른다. 이유: 축 오버라이드는 세부 태그
# 대부분이 uncategorized 라, 축으로 거르면 "smile"·"seductive smile" 같은 표정 태그가
# 통째로 빠진다. 반대로 uncategorized 를 통과시키면 "unicorn"(Creatures)·"microphone
# stand"(Food_Object) 같은 노이즈가 clothing 슬롯에 새어든다.
#
# interactive_tags.json 의 group 은 16,698 태그 전부 채워져 있고(9대분류), 실측상
# 노이즈/신호를 정확히 가른다. group 문자열이 파티션 그대로라 완전일치로 비교한다.
# (KR_tags 병합분은 "패션 > 디테일"처럼 다른 스킴이라 여기 없을 수 있다 → uncategorized 취급.)
INTERACTIVE_SLOT_GROUPS: dict[str, set[str]] = {
    "characteristic": {"Person_Body", "Creatures"},
    "clothing": {"Clothing_Wear"},
    "pose_action": {"Expression_Action"},
    "expression": {"Expression_Action"},
    "meta": {"Composition_Meta"},
    "location": {"Location_Background"},
    "object": {"Food_Object"},
}


async def _send_json(ws: WebSocket, payload: dict[str, Any]) -> None:
    await ws.send_text(json.dumps(payload, ensure_ascii=False))


def _tag_data_roots(context: WebSessionContext) -> list[Path]:
    roots: list[Path] = []
    runtime_paths = getattr(context, "runtime_paths", None)
    if runtime_paths is not None:
        roots.append(runtime_paths.data_dir)
    roots.append(Path(context.repo_root) / "data")
    return roots


def _ensure_kr_raw(context: WebSessionContext) -> dict[str, Any]:
    """KR 병합 raw 레코드를 세션당 1회만 로드한다.

    tag_search_index / relation_ranker / browse_index 가 전부 이 raw 위에 빌드된다. 각자
    로드하면 168k corpus 를 여러 번 읽어(측정상 첫 질의 7초+) 서로 다른 스냅샷을 들게 된다
    (Codex H3). 여기 한 곳으로 모아 재로드를 막고, 재프로비저닝 시 이 하나만 비우면 된다.
    """
    raw = getattr(context, "kr_tags_raw", None)
    if isinstance(raw, dict) and raw:
        return raw
    from core.kr_tag_loader import load_kr_tag_records

    result = load_kr_tag_records(context.repo_root, data_roots=_tag_data_roots(context))
    context.kr_tags_raw = result.raw
    context.autocomplete_state.kr_tags_loaded = bool(result.raw)
    return result.raw if isinstance(result.raw, dict) else {}


def ensure_tag_search_index(context: WebSessionContext):
    index = getattr(context, "tag_search_index", None)
    if index is not None:
        return index
    from core.tag_search_index import TagSearchIndex

    raw = _ensure_kr_raw(context)
    index = TagSearchIndex.from_raw_tag_records(raw)
    context.tag_search_index = index
    return index


def _autocomplete_row(result: Any) -> dict[str, Any]:
    entry = result.entry
    return {
        "tag": result.tag,
        "count": int(getattr(entry, "freq", 0) or 0),
        "desc": getattr(entry, "desc", "") or "",
        "group": getattr(entry, "category", "") or "",
        "cat": getattr(entry, "cat", "") or "",
        # 축은 Interactive 슬롯 자동완성이 클라이언트에서 스코프 표시/필터하는 데 쓴다.
        # 기존 소비자(일반 autocomplete/tag_search)는 이 키를 무시하므로 계약 파괴가 아니다.
        "axis": getattr(entry, "axis", "") or "",
    }


def _ensure_relation_ranker(context: WebSessionContext):
    """TagRelationRanker + raw 레코드. prompt_tools_routes 와 같은 세션 캐시를 공유한다."""
    raw = _ensure_kr_raw(context)   # 이미 로드됐으면 재로드하지 않는다(H3)
    ranker = getattr(context, "tag_relation_ranker", None)
    if ranker is not None:
        return ranker, raw
    from core.tag_relation_ranker import TagRelationRanker

    ranker = TagRelationRanker(raw) if raw else None
    context.tag_relation_ranker = ranker
    return ranker, raw


def _ensure_browse_index(context: WebSessionContext):
    """InteractiveBrowseIndex. 세션당 1회 빌드(~120ms). 관계 랭커와 같은 raw 를 공유한다."""
    idx = getattr(context, "interactive_browse_index", None)
    if idx is not None:
        return idx
    from core.interactive_browse_index import InteractiveBrowseIndex

    _, raw = _ensure_relation_ranker(context)
    idx = InteractiveBrowseIndex(raw if isinstance(raw, dict) else {})
    context.interactive_browse_index = idx
    return idx


def browse_interactive(
    context: WebSessionContext,
    slot: str,
    subgroup: str = "",
    parent: str = "",
    offset: int = 0,
    limit: int = 60,
    include: Any = None,
    exclude: Any = None,
) -> dict[str, Any]:
    """계층 브라우징. depth 는 어떤 인자가 채워졌는지로 결정된다.

    - parent 지정  -> Depth3: 그 태그의 children
    - subgroup 지정 -> Depth2: 그 subgroup 의 태그
    - 둘 다 없음    -> Depth1: 슬롯의 subgroup 목록
    """
    idx = _ensure_browse_index(context)
    if parent:
        payload = idx.children_of(parent, slot=slot, limit=limit)
        payload["depth"] = 3
    elif subgroup:
        payload = idx.tags_in(slot, subgroup, offset=offset, limit=limit)
        payload["depth"] = 2
    else:
        # Depth1 만 섹션 스코프(구도 vs 효과)를 건다. Depth2/3 은 선택한 subgroup 으로 자연 스코프.
        payload = {
            "items": idx.subgroups(slot, include=include, exclude=exclude),
            "depth": 1, "total": 0, "hasMore": False,
        }
        payload["total"] = len(payload["items"])
    return payload


def search_interactive_tags(
    context: WebSessionContext,
    query: str,
    axis: str = "",
    limit: int = 20,
) -> list[dict[str, Any]]:
    """축 스코프 자동완성. 슬롯(axis)의 group 집합에 속하는 태그만 반환한다.

    Interactive WS 명령은 7개 슬롯 전용이다. axis 가 슬롯 매핑에 없으면(오타/미지) 스코프가
    없어 전역 결과가 새어나가므로 **fail-closed**(빈 결과)로 처리한다(Codex M6).
    """
    from core.tag_search_index import normalize_search_query

    q = normalize_search_query(str(query or ""))
    if not q:
        return []
    groups = INTERACTIVE_SLOT_GROUPS.get(str(axis or "").strip().lower())
    if groups is None:
        return []   # unknown/empty axis — 슬롯 전용이므로 fail-closed
    index = ensure_tag_search_index(context)
    _, raw = _ensure_relation_ranker(context)

    def _group_of(tag: str) -> str:
        rec = raw.get(tag) if isinstance(raw, dict) else None
        return str(rec.get("group", "") or "") if isinstance(rec, dict) else ""

    def _group_ok(tag: str) -> bool:
        # 슬롯 group 에 속하면 통과. 빈 group(데이터상 1건)은 어느 슬롯에도 못 붙이므로 버린다.
        return _group_of(tag) in groups

    # filter-before-limit: 상위 limit*5 만 잘라서 필터하면, 슬롯 group 이 희소한 경우
    # (예: location 슬롯의 "h") 유효 결과가 상위권 밖에 있어 통째로 누락된다(Codex H4).
    # 검색 자체를 넉넉히 받아 필터한 뒤 limit 을 적용한다. group 조회는 O(1) 라 순회는 싸다.
    fetch = max(limit * 20, 300)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for result in index.search_autocomplete(q, limit=fetch, axes=None):
        if not _group_ok(result.tag):
            continue
        row = _autocomplete_row(result)
        if row["tag"] in seen:
            continue
        seen.add(row["tag"])
        rows.append(row)
        if len(rows) >= limit:
            break
    # 한글 입력은 KR 메타데이터 폴백까지 뒤진다(일반 autocomplete 와 동일 정책).
    if len(rows) < limit and re.search(r"[가-힣ㄱ-ㅎㅏ-ㅣ]", str(query or "")):
        for result in index.search_metadata_fallback(q, limit=fetch, exclude_noisy_categories=True):
            if not _group_ok(result.tag):
                continue
            row = _autocomplete_row(result)
            if row["tag"] in seen:
                continue
            seen.add(row["tag"])
            rows.append(row)
            if len(rows) >= limit:
                break
    return rows[:limit]


def related_interactive_tags(
    context: WebSessionContext,
    tag: str,
    axis: str = "",
    limit: int = 12,
) -> list[dict[str, Any]]:
    """이미 놓인 태그에서 뻗어나가는 관계 추천(children/siblings/word_match).

    interactive_tags.json 의 relations 를 TagRelationRanker 가 스코어링한다.
    axis 가 주어지면 후보를 그 슬롯 축으로 한 번 더 거른다.
    """
    from core.tag_axis_registry import normalize_tag as _norm

    ranker, raw = _ensure_relation_ranker(context)
    if ranker is None or not raw:
        return []
    key = _norm(str(tag or ""))
    info = raw.get(key)
    if not isinstance(info, dict):
        return []
    groups = INTERACTIVE_SLOT_GROUPS.get(str(axis or "").strip().lower())
    if groups is None:
        return []   # unknown/empty axis — fail-closed (M6)
    # filter-before-limit: 관계 후보를 넉넉히 랭크한 뒤 group 필터하고 자른다(H4).
    ranked = ranker.rank(key, info, limit=max(limit * 8, 60))
    rows: list[dict[str, Any]] = []
    for item in ranked:
        cand = raw.get(item.tag, {}) or {}
        g = str(cand.get("group", "") or "")
        # group 을 못 찾으면 통과(부모가 이 슬롯이라 관계로 뽑힌 것). 다른 group 이면 버림.
        if g and g not in groups:
            continue
        rows.append({
            "tag": item.tag,
            "count": int(cand.get("freq", 0) or 0),
            "desc": str(cand.get("description", "") or ""),
            "group": str(cand.get("group", "") or ""),
            "source": item.source,   # children / siblings / word_match
        })
        if len(rows) >= limit:
            break
    return rows


def search_kr_tags(context: WebSessionContext, query: str, limit: int = 20) -> list[dict[str, Any]]:
    from core.tag_search_index import normalize_search_query

    raw_query = str(query or "")
    q = normalize_search_query(raw_query)
    if not q:
        return []
    cats = None
    if q.startswith("@"):
        cats = {"artist"}
        q = normalize_search_query(q[1:])
    else:
        for prefix in ("artist:", "character:"):
            if q.startswith(prefix):
                cats = {prefix[:-1]}
                q = normalize_search_query(q[len(prefix):])
                break
    if not q:
        return []
    index = ensure_tag_search_index(context)
    rows = [_autocomplete_row(result) for result in index.search_autocomplete(q, limit=limit, cats=cats)]
    if len(rows) < limit and re.search(r"[가-힣ㄱ-ㅎㅏ-ㅣ]", raw_query):
        seen = {row["tag"] for row in rows}
        for result in index.search_metadata_fallback(q, limit=limit, exclude_noisy_categories=True):
            row = _autocomplete_row(result)
            if row["tag"] in seen:
                continue
            seen.add(row["tag"])
            rows.append(row)
            if len(rows) >= limit:
                break
    return rows[:limit]


# Tag Search 탭 -> 카테고리 필터.
#
# ⚠️ 네 탭이 **전체를 덮어야** 한다. `cat` 실측 분포는
#     artist 95,619 · character 48,932 · (빈값) 34,208 · copyright 8,845 · e621 5,382
# 이라, General 을 `cat == ""` 로 잡으면 copyright(touhou 등)와 e621 이 어느 탭에도
# 안 속해 ALL 에서만 보인다. 그래서 General 은 **캐릭터도 아티스트도 아닌 것**이다.
TAG_SEARCH_TABS: dict[str, dict[str, set[str] | None]] = {
    "all": {"cats": None, "exclude_cats": None},
    "character": {"cats": {"character"}, "exclude_cats": None},
    "artist": {"cats": {"artist"}, "exclude_cats": None},
    "general": {"cats": None, "exclude_cats": {"artist", "character"}},
}


def search_tags_substring(
    context: WebSessionContext,
    query: str,
    tab: str = "all",
    limit: int = 200,
    translate: bool = False,
) -> tuple[list[dict[str, Any]], str]:
    """Tag Search 팝업 — **부분 매칭 + 빈도순**. `(행, 번역어)` 를 준다.

    자동완성은 속도 때문에 접두사만 본다. 그래서 `utsusumi kio` 의 뒷부분(`kio`)만
    기억나면 찾을 길이 없었다 - 이 기능이 채우는 구멍이다(사용자 지정).

    실측: `kio` 129개 중 `utsusumi kio` 가 점수순으로는 29위, **빈도순 5위**.
    비용은 질의당 30~50ms 라 지연 검색(lazy)으로 감당한다.

    두 번째 값은 **번역으로 다시 찾았을 때의 영어 질의**다. 빈 문자열이면 번역을
    안 썼다는 뜻이다 - 화면이 "'밀크티' -> 'milk tea' 로 찾았습니다" 를 알려야
    사용자가 왜 다른 말의 결과가 나오는지 안다.
    """
    from core.tag_search_index import normalize_search_query

    raw_query = str(query or "")
    q = normalize_search_query(raw_query)
    if not q:
        return [], ""
    spec = TAG_SEARCH_TABS.get(str(tab or "all").strip().lower()) or TAG_SEARCH_TABS["all"]
    index = ensure_tag_search_index(context)
    cap = max(1, min(500, int(limit or 200)))
    results = index.search_substring(
        q, limit=cap, cats=spec["cats"], exclude_cats=spec["exclude_cats"],
    )
    translated = ""
    if not results and translate:
        # 한글이 안 걸리면 번역해서 한 번 더 친다(사용자 제안).
        #
        # ⚠️ **자동으로 하지 않는다.** `translate` 를 켜야 돈다. 이유는 실측이다:
        #   · 번역기는 **네트워크**다(googletrans / Google Translate API). 이
        #     환경에서는 전부 빈 문자열을 돌려주면서 질의당 **700~870ms** 를 쓴다.
        #     자동으로 걸면 결과 없는 질의마다 0.8초 멈추고 얻는 것이 없다.
        #   · 한글 색인이 이미 거의 다 덮는다 - `자동차`->motor vehicle ·
        #     `권투 장갑`->boxing gloves · `칫솔`->toothbrush · `선글라스`->sunglasses ·
        #     `헬리콥터`->helicopter 가 **번역 없이** 나온다.
        #
        # 그래서 0건일 때 화면이 [번역해서 다시 찾기] 를 내밀고, 누르면 여기로 온다.
        # 오프라인이면 멈춤이 아니라 "번역하지 못했습니다" 가 된다.
        translated = _translate_autocomplete_query(context, raw_query)
        if translated and translated != q:
            results = index.search_substring(
                translated, limit=cap, cats=spec["cats"], exclude_cats=spec["exclude_cats"],
            )
        if not results:
            # 번역해도 빈손이면 번역어를 알릴 이유가 없다 - 오히려 헷갈린다.
            translated = ""
    rows: list[dict[str, Any]] = []
    for result in results:
        row = _autocomplete_row(result)
        entry = result.entry
        # 우측 설명 패널이 쓰는 값들. `_autocomplete_row` 는 자동완성 목록용이라
        # 한글 동의어(keywords)를 안 싣는다 - 여기서만 더한다.
        keywords = getattr(entry, "keywords", None) or ()
        row["keywords"] = [str(k) for k in keywords if str(k or "").strip()]
        row["source"] = str(getattr(entry, "source", "") or "")
        profile = _character_profile(context, row)
        if profile:
            row["profile"] = profile
        rows.append(row)
    return rows, translated


def _character_profile(context: WebSessionContext, row: dict[str, Any]) -> dict[str, Any]:
    """캐릭터 태그면 **구성요소**(퍼스널 컬러 · 특징)를 함께 싣는다.

    설명 칸이 캐릭터에서 유난히 비어 보이던 이유는 사전에 설명글이 없어서다
    (사용자 제보 2026-08-25). 캐릭터의 답은 설명글이 아니라 **어떤 특징으로
    이루어져 있는가**이고, 그 값은 캐릭터 뷰어가 이미 쓰는
    `data/character_analysis.json` 에 있다 - 같은 SSOT 를 그대로 본다.

    조회 실패는 삼킨다 - 부가 정보 하나 때문에 검색이 통째로 죽으면 안 된다.
    """
    if str(row.get("cat") or "").strip().lower() != "character":
        return {}
    try:
        from app.backend.server.character_viewer_routes import character_viewer_service

        service = character_viewer_service(context)
        return service.profile_summary(str(row.get("tag") or ""))
    except Exception as exc:  # noqa: BLE001 - 부가 정보다. 검색을 막으면 안 된다
        print(f"[warn] character profile lookup failed: {exc}", flush=True)
        return {}


def _has_hangul_text(text: str) -> bool:
    return bool(re.search(r"[가-힣ㄱ-ㅎㅏ-ㅣ]", str(text or "")))


def _translate_autocomplete_query(context: WebSessionContext, query: str) -> str:
    from core.tag_search_index import normalize_search_query

    normalized = normalize_search_query(query)
    if not normalized or not _has_hangul_text(normalized):
        return ""
    cache = getattr(context, "autocomplete_translation_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        context.autocomplete_translation_cache = cache
    cached = cache.get(normalized)
    if cached is not None:
        return str(cached)
    from core.translation_history import translation_context

    with translation_context("autocomplete"):
        translated = normalize_search_query(korean_to_english(normalized) or "")
    failed = not translated
    if not translated or _has_hangul_text(translated) or translated == normalized:
        translated = ""
    # ⚠️ **실패는 캐시하지 않는다.** 429 하나가 그 질의를 세션 내내 실패로 굳혔다 -
    #    제한이 풀린 뒤 같은 말을 쳐도 다시 시도조차 안 했다(Codex 리뷰 MED 4).
    #    "번역했는데 쓸 값이 아니다"(한글 그대로 · 원문과 같음)는 캐시해도 된다 -
    #    그건 네트워크와 무관한 확정된 결과다.
    if failed:
        return ""
    if len(cache) > 256:
        cache.clear()
    cache[normalized] = translated
    return translated


def _translation_hint_row(translated: str) -> dict[str, Any]:
    return {
        "tag": translated,
        "count": 0,
        "desc": "translation hint",
        "group": "[translation hint]",
        "cat": "",
        "_wc_type": "fallback_recommended",
        "_fallback_recommended": True,
        "candidate": {
            "type": "translation_hint",
            "source": "translation_fallback",
            "confidence": 0.2,
            "insertPolicy": "manual",
        },
        "candidateType": "translation_hint",
        "source": "translation_fallback",
        "confidence": 0.2,
        "insertPolicy": "manual",
    }


def search_kr_tags_with_translation(
    context: WebSessionContext,
    query: str,
    limit: int = 20,
) -> tuple[list[dict[str, Any]], str]:
    from core.tag_search_index import normalize_search_query

    translated = _translate_autocomplete_query(context, query)
    base_rows = search_kr_tags(context, query, limit)
    if not translated:
        return base_rows, ""

    merged: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []

    def add_row(row: dict[str, Any], *, translated_match: bool = False) -> None:
        tag = str(row.get("tag") or "")
        key = normalize_search_query(tag)
        if not key or key in merged:
            return
        item = dict(row)
        if translated_match:
            item["_translated"] = True
            item.setdefault("candidateType", "tag_translated")
            item.setdefault("source", "translation_search")
            item.setdefault("confidence", 0.75)
            item.setdefault("insertPolicy", "default")
            candidate = dict(item.get("candidate") or {})
            candidate.setdefault("type", item["candidateType"])
            candidate.setdefault("source", item["source"])
            candidate.setdefault("confidence", item["confidence"])
            candidate.setdefault("insertPolicy", item["insertPolicy"])
            item["candidate"] = candidate
        merged[key] = item
        rows.append(item)

    for row in search_kr_tags(context, translated, limit):
        add_row(row, translated_match=True)
    for row in base_rows:
        add_row(row)

    translated_key = normalize_search_query(translated)
    if translated_key and translated_key not in merged:
        hint_row = _translation_hint_row(translated)
        if len(rows) >= limit:
            rows = rows[:max(0, limit - 1)] + [hint_row]
        else:
            add_row(hint_row)
    return rows[:limit], translated


def search_wildcards(context: WebSessionContext, query: str, limit: int = 12) -> list[dict[str, Any]]:
    # 빈 쿼리(`__` 만 입력)도 허용 → 전체 와일드카드 상위 N개를 나열한다.
    q = str(query or "").strip().lower()
    base = context._wildcard_base_dir()
    if not base.exists():
        return []
    # 1) 경로만 먼저 수집/필터 (entries 파일 읽기는 상위 N개로 지연 — 빈 쿼리 성능)
    matched: list[tuple[str, Any]] = []
    for path in base.rglob("*.txt"):
        try:
            rel = path.relative_to(base).with_suffix("").as_posix()
        except Exception:
            continue
        if q and q not in rel.lower():
            continue
        matched.append((rel, path))
    if q:
        matched.sort(key=lambda rp: (rp[0].lower() != q, not rp[0].lower().startswith(q), rp[0].lower()))
    else:
        matched.sort(key=lambda rp: rp[0].lower())
    # 2) 상위 N개만 entries 카운트
    results: list[dict[str, Any]] = []
    for rel, path in matched[:limit]:
        try:
            entries = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except Exception:
            entries = []
        results.append({
            "tag": rel,
            "count": len(entries),
            "desc": f"{len(entries)} entries",
            "group": "wildcard",
            "cat": "",
            "_wc_type": "wildcard",
        })
    return results


def search_chunks(context: WebSessionContext, query: str, limit: int = 12) -> list[dict[str, Any]]:
    store = context._instant_wildcard_store()
    tree = dict(store.get("instant_wildcard_tree") or {})
    raw = str(query or "").strip()
    if raw.startswith("$"):
        raw = raw[1:].strip()
    q = raw.lower()

    def preview(value: Any, max_len: int = 96) -> str:
        text = str(value or "").replace("\n", " ").strip()
        return text[:max_len] + "..." if len(text) > max_len else text

    def rank(text: str) -> int | None:
        haystack = str(text or "").lower()
        if not q:
            return 4
        if haystack == q:
            return 0
        if haystack.startswith(q):
            return 1
        if q in haystack:
            return 2
        return None

    rows: list[tuple[int, int, dict[str, Any]]] = []
    if ":" in raw:
        group_name, item_query = raw.split(":", 1)
        q = item_query.strip().lower()
        groups = [(name, items) for name, items in tree.items() if str(name).lower() == group_name.strip().lower()]
    else:
        groups = list(tree.items())
    index = 0
    for group_name, items in groups:
        group_rank = rank(group_name)
        if group_rank is not None and ":" not in raw:
            rows.append((group_rank, index, {
                "tag": str(group_name),
                "value": f"${group_name}:",
                "count": len(items or {}),
                "desc": f"{len(items or {})} entries",
                "group": "chunk group",
                "cat": "",
                "_wc_type": "chunk_group",
            }))
            index += 1
        if isinstance(items, dict):
            for key, value in items.items():
                item_rank = min([r for r in (rank(key), rank(value)) if r is not None], default=None)
                if item_rank is None:
                    continue
                rows.append((item_rank, index, {
                    "tag": str(key),
                    "value": str(value or ""),
                    "count": 0,
                    "desc": preview(value),
                    "group": str(group_name),
                    "cat": "",
                    "preview": str(value or ""),
                    "_wc_type": "chunk",
                }))
                index += 1
    rows.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in rows[:limit]]


def preset_autocomplete_payload(
    context: WebSessionContext,
    query: str,
    limit: int = 12,
    preset_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        from core.preset_input_bridge import PresetInputBridge, update_app_preset_context

        token = str(query or "").strip()
        if not token.lower().startswith("preset:"):
            token = "preset:" + token
        preset_context = update_app_preset_context(
            context,
            preset_context if isinstance(preset_context, dict) else {},
            source="autocomplete",
        )
        bridge = getattr(context, "preset_autocomplete_bridge", None)
        if bridge is None:
            bridge = PresetInputBridge(
                Path(context.repo_root),
                event_service=event_preset_service(context),
                clothes_service=clothes_preset_service(context),
                expression_service=expression_preset_service(context),
                context=preset_context,
            )
            context.preset_autocomplete_bridge = bridge
        elif hasattr(bridge, "set_context"):
            bridge.set_context(preset_context)
        payload = bridge.suggest(token, limit=limit)
        rows = payload.get("suggestions") or []
        secondary = payload.get("secondaryResults") or payload.get("secondarySuggestions") or []
        if payload.get("stage") in {"loading", "unavailable"}:
            state = payload.get("loadState") or {}
            rows = [{
                "tag": str(state.get("main") or payload.get("stage") or "preset"),
                "value": token,
                "count": 0,
                "desc": str(state.get("message") or "Preset data is not ready."),
                "group": "preset",
                "cat": "preset",
                "_wc_type": "preset_status",
                "disabled": True,
            }]
            secondary = []
        return {
            "query": token,
            "results": rows,
            "secondaryResults": secondary,
            "preset": {
                "axis": payload.get("axis") or "",
                "stage": payload.get("stage") or "",
                "context": payload.get("presetContext") or preset_context,
                "loadState": payload.get("loadState") or {},
                "dataReady": bool(payload.get("dataReady")),
                "secondaryResults": secondary,
            },
        }
    except Exception as exc:
        print(f"Headless Remote: preset autocomplete failed - {exc}", flush=True)
        return {"query": str(query or ""), "results": [], "secondaryResults": [], "preset": {}}


async def handle_autocomplete_command(
    ws: WebSocket,
    context: WebSessionContext,
    command: dict[str, Any],
    *,
    run_in_thread: AsyncRunner,
) -> bool:
    command_type = str(command.get("type") or "").strip()
    if command_type not in AUTOCOMPLETE_COMMAND_TYPES:
        return False

    query = str(command.get("query") or "")
    if command_type == "tag_search":
        # ⚠️ 이 커맨드는 **소비자가 없는 채로 남아 있었다** — `#tagSearchBar` 가
        #    `display:none` 하드 숨김이고(주석: reserved for future) JS 참조도 0이었다.
        #    Tag Search 팝업이 그 자리를 이어받는다. 새 메시지 타입을 만들지 않는
        #    이유는 **웹 스모크 계약이 타입을 순서대로 세기 때문**이다 - 하나만 더해도
        #    이후 전부가 밀린다.
        tab = str(command.get("tab") or "all")
        limit = int(command.get("limit") or 200)
        # `translate` 는 화면의 [번역해서 다시 찾기] 가 켠다 - 자동이 아니다
        # (번역기가 네트워크라 질의당 0.8초를 문다, search_tags_substring 주석 참조).
        translate = bool(command.get("translate"))
        results, translated = await run_in_thread(
            search_tags_substring, context, query, tab, limit, translate)
        await _send_json(ws, {
            "type": "tag_search_result",
            "query": query,
            "tab": tab,
            # 번역으로 다시 찾았으면 그 영어 질의. 화면이 왜 다른 말의 결과가
            # 나오는지 알려야 한다.
            "translated": translated,
            "results": results,
        })
        return True

    if command_type == "tag_filter_ac":
        results = await run_in_thread(search_kr_tags, context, query, 12)
        await _send_json(ws, {"type": "tag_filter_ac_result", "query": query, "results": results})
        return True

    if command_type == "autocomplete":
        results = await run_in_thread(search_kr_tags, context, query, 12)
        await _send_json(ws, {"type": "autocomplete_result", "query": query, "results": results})
        return True

    if command_type == "interactive_autocomplete":
        axis = str(command.get("axis") or "")
        request_id = str(command.get("requestId") or command.get("request_id") or "")
        results = await run_in_thread(search_interactive_tags, context, query, axis, 16)
        await _send_json(ws, {
            "type": "interactive_autocomplete_result",
            "query": query,
            "axis": axis,
            "requestId": request_id,
            "results": results,
        })
        return True

    if command_type == "interactive_related":
        axis = str(command.get("axis") or "")
        tag = str(command.get("tag") or query or "")
        request_id = str(command.get("requestId") or command.get("request_id") or "")
        results = await run_in_thread(related_interactive_tags, context, tag, axis, 12)
        await _send_json(ws, {
            "type": "interactive_related_result",
            "tag": tag,
            "axis": axis,
            "requestId": request_id,
            "results": results,
        })
        return True

    if command_type == "autocomplete_translate":
        request_id = str(command.get("requestId") or command.get("request_id") or "")
        results, translated = await run_in_thread(search_kr_tags_with_translation, context, query, 12)
        payload = {
            "type": "autocomplete_result",
            "query": query,
            "results": results,
            "translated_query": translated,
        }
        if request_id:
            payload["requestId"] = request_id
        await _send_json(ws, payload)
        return True

    if command_type == "autocomplete_wildcard":
        results = await run_in_thread(search_wildcards, context, query, 12)
        await _send_json(ws, {"type": "autocomplete_result", "query": query, "results": results})
        return True

    if command_type == "autocomplete_chunk":
        results = await run_in_thread(search_chunks, context, query, 12)
        await _send_json(ws, {"type": "autocomplete_result", "query": query, "results": results})
        return True

    if command_type == "autocomplete_vibe_cluster":
        from core.vibe_cluster_resolver import search_vibe_clusters

        results = await run_in_thread(
            search_vibe_clusters,
            query,
            12,
            context._existing_save_path("vibe_transfer_clusters"),
        )
        await _send_json(ws, {"type": "autocomplete_result", "query": query, "results": results})
        return True

    if command_type == "autocomplete_preset":
        payload = await run_in_thread(
            preset_autocomplete_payload,
            context,
            query,
            12,
            command.get("presetContext") if isinstance(command.get("presetContext"), dict) else command.get("context"),
        )
        await _send_json(ws, {
            "type": "autocomplete_result",
            "query": payload.get("query", query),
            "results": payload.get("results", []),
            "secondaryResults": payload.get("secondaryResults", []),
            "preset": payload.get("preset") or {},
        })
        return True

    if command_type == "translate_text":
        request_id = str(command.get("requestId") or command.get("request_id") or "")
        direction = str(command.get("direction") or "ko_en").strip().lower()
        text = str(command.get("text") or command.get("query") or "")
        translator = english_to_korean if direction in {"en_ko", "en-ko", "en2ko"} else korean_to_english
        from core.translation_history import translation_context

        try:
            # asyncio.to_thread는 contextvar를 워커 스레드로 복사하므로 라벨이 전파된다.
            # ⚠️ **사유를 예외로 받지 않는다.** `utils/translator` 의 계약은 "실패하면
            #    None, 절대 raise 안 함" 이고, 자동완성 경로(`_translate_autocomplete_query`)
            #    는 예외를 안 잡는다 - 던지게 바꾸면 WS 수신 루프가 통째로 끝난다
            #    (Codex 리뷰 2026-08-29 MED 2). 그래서 사유를 **함께 돌려주는** 함수를 쓴다.
            from utils.translator import rate_limit_seconds_remaining, translate_with_reason

            direction_key = "en_ko" if translator is english_to_korean else "ko_en"
            with translation_context("manual_translate"):
                translated, reason = await run_in_thread(
                    translate_with_reason, text, direction_key)
            payload = {
                "type": "translation_result",
                "text": text,
                "translated": translated or "",
                "direction": direction_key,
                "ok": bool(translated),
            }
            if not translated:
                # 화면이 "Translation failed" 밖에 못 말하던 것을 고친다(사용자 제보).
                wait = rate_limit_seconds_remaining()
                payload["reason"] = reason
                payload["retry_after"] = wait
                payload["error"] = {
                    "rate_limited": (
                        f"번역 서버가 요청을 제한하고 있습니다 (약 {wait}초 후 다시 시도)"
                        if wait > 0 else "번역 서버가 요청을 제한하고 있습니다"),
                    "timeout": "번역 서버 응답이 없습니다 (시간 초과)",
                    "network": "번역 서버에 연결하지 못했습니다 (네트워크 확인)",
                }.get(reason, "번역하지 못했습니다")
        except Exception as exc:
            payload = {
                "type": "translation_result",
                "text": text,
                "translated": "",
                "direction": "en_ko" if translator is english_to_korean else "ko_en",
                "ok": False,
                "error": str(exc),
            }
        if request_id:
            payload["requestId"] = request_id
        await _send_json(ws, payload)
        return True

    info = await run_in_thread(tag_lookup_info, context, str(command.get("tag") or ""))
    await _send_json(ws, {"type": "tag_lookup_result", **info})
    return True
