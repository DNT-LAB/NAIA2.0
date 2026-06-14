# -*- coding: utf-8 -*-
"""Scene-description to grounded tag candidates.

This module never invents tag strings. It fans out a natural-language scene
query into a small set of search queries, calls the injected tag searcher, then
reranks only returned rows.
"""

from __future__ import annotations

from math import log10
import re
from typing import Any, Callable, Iterable

SearchFn = Callable[[str, int, Any], list[dict[str, Any]]]
TranslatorFn = Callable[[str], str | None]

_HANGUL_RE = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")

_OBJECT_NOISE_TAGS = {
    "hanging breasts",
    "hanging plant",
    "hanging light",
    "hanging scroll",
    "hanging lantern",
    "hanging food",
    "hanging flower",
    "hanging bridge",
    "ceiling light",
    "tile ceiling",
    "wooden ceiling",
    "ceiling fan",
    "chandelier",
    "hand grip",
}
_OBJECT_QUERY_HINTS = {
    "light", "lamp", "plant", "flower", "bridge", "fan", "scroll", "lantern",
    "조명", "등", "식물", "꽃", "다리", "선풍기", "팬", "두루마리", "랜턴",
}
_ADULT_POSITION_NOISE = {
    "suspended congress",
    "reverse suspended congress",
}
_ADULT_NOISE_PARTS = (
    "cum",
    "penis",
    "pussy",
    "vaginal",
    "anal",
    "nipple",
    "breast",
)
_SCENE_NOISE_PARTS = (
    "breasts",
    "wedgie",
    "eyewear",
    "earrings",
    "earring",
    "knot",
    "from branch",
    "branch",
)
_ADULT_QUERY_HINTS = {
    "sex", "sexual", "penetration", "congress", "삽입", "성행위", "체위",
}
_DEATH_QUERY_HINTS = {
    "hanged", "hanging by neck", "hang by neck", "neck", "death", "suicide",
    "목매", "목을 매", "교수", "자살", "사망", "죽음",
}
_PROMPT_SCAFFOLD_RE = re.compile(
    r"(?:프롬프트|태그|추천|소개|검색|찾아|알려|묘사|강조|관련|어울|있을까요|있나요|\bprompts?\b|\btags?\b)",
    re.IGNORECASE,
)
_EXACT_NOISE_TAGS = {
    "yes",
    "no",
    "too many",
    "reference sheet",
    "model sheet",
}
_SOFT_NOISE_TAGS = {
    "punk",
}
_NOISE_PREFIXES = (
    "describing ",
)
_GENITAL_NOISE_PARTS = (
    "penis",
    "pussy",
    "genital",
    "vaginal",
    "anal",
    "testicle",
    "clitoris",
    "vulva",
)
_PROPER_NOISE_PARTS = (
    " the cat",
    " the dog",
)
_LOCAL_KO_QUERY_EXPANSIONS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("가슴골", "클리비지", "슴골"), ("cleavage", "large breasts")),
    (("메이드복", "메이드 옷", "maid"), ("maid outfit", "maid")),
    (("블루 아카이브", "blue archive"), ("blue archive",)),
)
_CATEGORY_AXES = frozenset({
    "clothing",
    "action",
    "expression",
    "background",
    "body",
    "object",
    "general",
})
_CATEGORY_AXIS_ALLOWED_TOPS = {
    # Enumerated from load_kr_tag_records().raw top-level group labels. Keep
    # this mapping code-owned; the model only proposes the compact axis label.
    "clothing": frozenset({
        "패션", "의상", "복장", "의류", "복식", "코스프레", "코스튬", "특정 의상",
        "의상 조합", "복장 조합", "의상/상태", "의상/사물", "의상/디테일",
        "캐릭터/의상", "신발", "신발/디테일", "액세서리", "악세사리", "장신구",
        "모자", "갑옷", "스킨", "clothing", "fashion", "attire",
    }),
    "action": frozenset({
        "행위", "행동", "동작", "자세", "자세/행동", "포즈", "표정/행동",
        "신체 자세", "성행위", "성적 행위", "체위", "활동", "놀이", "움직임",
        "상호작용", "구속", "신체 구속", "BDSM", "Actions", "action", "actions",
        "pose",
    }),
    "expression": frozenset({
        "표정", "표현", "표정/행동", "표정/상태", "Expressions", "감정", "얼굴",
        "눈", "화장", "메이크업", "expression", "expressions",
    }),
    "background": frozenset({
        "배경", "장소", "자연", "풍경", "환경", "지형", "지리", "건축", "건물",
        "배경/사물", "배경/문화", "background", "location", "nature",
    }),
    "body": frozenset({"신체", "body"}),
    "object": frozenset({"사물", "물체", "오브젝트", "사물/음식", "음식", "object", "prop"}),
}
_CATEGORY_AXIS_TOP_MARKERS = {
    # The corpus has many one-off franchise labels such as "블루 아카이브 복식".
    # Marker matching covers those top-levels without blocking valid costume
    # leaves like "패션 > 코스튬".
    "clothing": frozenset({"의상", "복장", "의류", "복식", "코스튬", "신발", "액세서리", "악세사리", "장신구"}),
    "action": frozenset({"행동", "행위", "동작", "자세", "포즈", "성행위", "상호작용", "움직임", "구속"}),
    "expression": frozenset({"표정", "표현", "감정", "얼굴", "메이크업"}),
    "background": frozenset({"배경", "장소", "자연", "풍경", "환경", "지형", "지리", "건축", "건물"}),
    "body": frozenset({"신체", "체형", "외형", "외모", "헤어", "성기"}),
    "object": frozenset({"사물", "물체", "오브젝트", "음식", "아이템", "도구", "소품", "장비", "무기", "가구", "악기", "식기", "탈것"}),
}
_CATEGORY_AXIS_ALLOWED_TOPS_FOLDED = {
    axis: frozenset(item.casefold() for item in tops)
    for axis, tops in _CATEGORY_AXIS_ALLOWED_TOPS.items()
}
_CATEGORY_AXIS_FUNCTION_WORD_TAGS = frozenset({
    "action",
    "can",
    "only",
})


def discover_semantic_tags(
    query: str,
    *,
    searcher: SearchFn,
    context: Any = None,
    limit: int = 12,
    expansion_queries: Iterable[str] | None = None,
    translator: TranslatorFn | None = None,
    category_axis: str = "general",
) -> list[dict[str, Any]]:
    """Return ranked tag rows for a natural-language scene description."""
    text = _coerce_text(query, limit=1000).strip()
    if not text:
        return []
    queries = semantic_tag_queries(text, expansion_queries=expansion_queries)
    if _HANGUL_RE.search(text) and translator is not None and not any(not _HANGUL_RE.search(q) for q in queries):
        translated = _translate_query(text, translator)
        if translated:
            queries = _dedupe_queries(list(queries) + [_normalize_booru_query(translated)])
    merged = _collect_search_rows(queries, searcher=searcher, context=context, limit=limit)
    ranked = rank_semantic_tag_rows(text, merged.values(), context=context)
    ranked = filter_rows_by_category_axis(ranked, category_axis)
    return ranked[: max(0, int(limit or 12))]


def discover_prompt_tags(
    query: str,
    *,
    searcher: SearchFn,
    context: Any = None,
    limit: int = 12,
    expansion_queries: Iterable[str] | None = None,
    translator: TranslatorFn | None = None,
    category_axis: str = "general",
) -> list[dict[str, Any]]:
    """Return ranked grounded tag rows for prompt-recommendation chat requests."""
    text = _coerce_text(query, limit=1000).strip()
    if not text:
        return []
    queries = prompt_tag_queries(text, expansion_queries=expansion_queries, translator=translator)
    merged = _collect_search_rows(queries, searcher=searcher, context=context, limit=limit)
    ranked = rank_semantic_tag_rows(text, merged.values(), context=context)
    ranked = filter_rows_by_category_axis(ranked, category_axis)
    return ranked[: max(0, int(limit or 12))]


def normalize_category_axis(value: Any) -> str:
    axis = _coerce_text(value, limit=40).strip().lower().replace("-", "_")
    aliases = {
        "clothes": "clothing",
        "clothings": "clothing",
        "costume": "clothing",
        "costumes": "clothing",
        "fashion": "clothing",
        "outfit": "clothing",
        "outfits": "clothing",
        "attire": "clothing",
        "pose": "action",
        "poses": "action",
        "posture": "action",
        "postures": "action",
        "movement": "action",
        "movements": "action",
        "behavior": "action",
        "behaviors": "action",
        # 데이터 top-level이 'Actions'/'Expressions' 복수형이라 소형 모델이 복수/대문자를
        # 낼 가능성이 높다 → 정규화 누락 시 필터가 general로 풀려 노이즈가 부활한다(Codex R1).
        "actions": "action",
        "face": "expression",
        "faces": "expression",
        "expressions": "expression",
        "emotion": "expression",
        "emotions": "expression",
        "location": "background",
        "locations": "background",
        "place": "background",
        "places": "background",
        "scene": "background",
        "scenes": "background",
        "backgrounds": "background",
        "bodies": "body",
        "prop": "object",
        "props": "object",
        "item": "object",
        "items": "object",
        "objects": "object",
        "misc": "general",
        "unknown": "general",
        "none": "general",
    }
    axis = aliases.get(axis, axis)
    return axis if axis in _CATEGORY_AXES else "general"


def infer_category_axis_from_text(value: str) -> str:
    text = _coerce_text(value, limit=1000).lower()
    if _contains_any(text, ("의상", "옷", "복장", "입은", "clothing", "clothes", "outfit", "costume")):
        return "clothing"
    if _contains_any(text, ("행동", "행위", "동작", "포즈", "자세", "action", "pose", "posture", "movement", "behavior")):
        return "action"
    if _contains_any(text, ("표정", "얼굴", "expression", "face")):
        return "expression"
    if _contains_any(text, ("배경", "장소", "background", "location", "place")):
        return "background"
    if _contains_any(text, ("신체", "몸", "body")):
        return "body"
    if _contains_any(text, ("사물", "소품", "물체", "object", "prop", "item")):
        return "object"
    return "general"


def filter_rows_by_category_axis(
    rows: Iterable[dict[str, Any]],
    category_axis: str,
) -> list[dict[str, Any]]:
    """Filter grounded rows by a code-owned category axis.

    Return only rows that match the axis. If no grounded rows match, return an
    empty list and let the route's empty-tool handling produce an honest chat
    fallback; never reintroduce unfiltered noise.
    """
    axis = normalize_category_axis(category_axis)
    original = [dict(row) for row in rows or []]
    if axis == "general":
        return original
    kept = [row for row in original if _row_matches_category_axis(row, axis)]
    return kept


def semantic_tag_queries(query: str, expansion_queries: Iterable[str] | None = None) -> list[str]:
    """Small deterministic scene query expansion."""
    text = _coerce_text(query, limit=1000).strip()
    lowered = text.lower()
    out: list[str] = []

    def add(value: str) -> None:
        value = " ".join(str(value or "").strip().split())
        if value and value not in out:
            out.append(value)

    for value in expansion_queries or ():
        add(_coerce_text(value, limit=80))

    if _contains_any(lowered, ("매달", "걸려", "늘어", "hanging", "suspended")):
        add("hanging")
        add("매달")
    if _contains_any(lowered, ("천장", "ceiling")):
        add("ceiling")
        add("천장")
    if _contains_any(lowered, ("구속", "속박", "묶", "bound", "restraint", "bondage")):
        add("suspension")
        add("bound wrists")
        add("bound")
    elif _contains_any(lowered, ("매달", "suspended")):
        # Hanging from restraints is a common conditional interpretation, but
        # it must rank below the non-restraint core tags when restraint is not explicit.
        add("suspension")
    if _contains_any(lowered, ("거꾸로", "뒤집", "upside", "inverted")):
        add("upside-down")
    if _contains_any(lowered, _DEATH_QUERY_HINTS):
        add("hanged")

    cleaned = clean_tag_discovery_subject(text)
    if cleaned and cleaned != text:
        add(cleaned)
    if _HANGUL_RE.search(text):
        for token in ("천장", "매달", "구속", "속박", "거꾸로"):
            if token in text:
                add(token)
    if not out:
        add(cleaned or text)
    return out[:8]


def prompt_tag_queries(
    query: str,
    *,
    expansion_queries: Iterable[str] | None = None,
    translator: TranslatorFn | None = None,
) -> list[str]:
    """Build a clean English-first query plan for chat prompt recommendations."""
    text = _coerce_text(query, limit=1000).strip()
    out: list[str] = []

    def add(value: str) -> None:
        value = _normalize_booru_query(value)
        if value and value not in out:
            out.append(value)

    for value in expansion_queries or ():
        add(_coerce_text(value, limit=80))

    lowered = text.lower()
    has_kokona_blue_archive = "kokona" in lowered and "blue archive" in lowered
    if has_kokona_blue_archive:
        add("kokona (blue archive)")
        add("kokona")
    for needles, values in _LOCAL_KO_QUERY_EXPANSIONS:
        if any(needle.lower() in lowered for needle in needles):
            if has_kokona_blue_archive and values == ("blue archive",):
                continue
            for value in values:
                add(value)

    cleaned = clean_prompt_search_subject(text)
    if cleaned and not _HANGUL_RE.search(cleaned):
        add(cleaned)
    elif cleaned and translator is not None and not any(not _HANGUL_RE.search(q) for q in out):
        translated = _translate_query(cleaned, translator)
        if translated:
            add(translated)

    # Raw Korean/mixed text is retained only as a fallback phase. When English
    # queries return rows, _collect_search_rows never calls this noisy lane.
    if text and _HANGUL_RE.search(text):
        raw = clean_prompt_search_subject(text) or text
        raw = " ".join(raw.strip().split())
        if raw and raw not in out:
            out.append(raw)
    if not out:
        add(cleaned or text)
    return out[:8]


def rank_semantic_tag_rows(
    query: str,
    rows: Iterable[dict[str, Any]],
    *,
    context: Any = None,
) -> list[dict[str, Any]]:
    """Rank only supplied candidate rows."""
    lowered = _coerce_text(query, limit=1000).lower()
    signals = _scene_signals(lowered)
    existing_tags = _context_tags(context)
    ranked: list[tuple[float, int, str, dict[str, Any]]] = []
    for row in rows or []:
        tag = _norm_tag(row.get("tag"))
        if not tag:
            continue
        score, reason, role = _score_row(tag, row, lowered, signals, existing_tags)
        out = {
            "tag": tag,
            "count": _safe_int(row.get("count")),
            "desc": _coerce_text(row.get("desc") or row.get("description"), limit=500),
            "group": _coerce_text(row.get("group"), limit=200),
            "cat": _coerce_text(row.get("cat") or row.get("_cat"), limit=80),
            "score": round(score, 4),
            "reason": reason,
            "role": role,
        }
        query_count = len(set(row.get("_queries") or ()))
        best_index = _safe_int(row.get("_best_index"))
        query_order = _safe_int(row.get("_query_order"))
        ranked.append((score, query_count, tag, out | {"_best_index": best_index, "_query_order": query_order}))
    ranked.sort(key=lambda item: (-item[0], -item[1], item[3].get("_query_order", 9999), item[3].get("_best_index", 9999), item[2]))
    rows_out = [_strip_internal(item[3]) for item in ranked if item[0] > -0.25]
    strong = [
        row for row in rows_out
        if float(row.get("score") or 0.0) >= 0.25 or row.get("role") in {"core", "conditional"}
    ]
    return strong if len(strong) >= 3 else rows_out


def clean_tag_discovery_subject(value: str) -> str:
    text = _coerce_text(value, limit=500).strip()
    text = re.sub(r"(?:을|를)?\s*묘사(?:하는|할|한)?\s*태그.*$", "", text).strip()
    text = re.sub(r"(?:와|과|에)?\s*관련(?:된|한)?\s*태그.*$", "", text).strip()
    text = re.sub(r"태그(?:가|를|는)?\s*(?:있을까요|있나요|찾아.*|추천.*|알려.*)?\??$", "", text).strip()
    text = re.sub(r"^(?:혹시|혹은|그럼|음)\s*", "", text).strip()
    return text.strip(" .,:;!?\"'“”‘’<>")


def clean_prompt_search_subject(value: str) -> str:
    text = _coerce_text(value, limit=500).strip()
    text = re.sub(r"^(?:사용자가|유저가|나는|제가)\s*", "", text)
    text = re.sub(r"(?:을|를)?\s*(?:묘사|강조)(?:하는|할|한)?", " ", text)
    text = re.sub(r"(?:와|과|에)?\s*관련(?:된|한)?", " ", text)
    text = re.sub(r"(?:프롬프트|태그)(?:가|를|는)?|\bprompts?\b|\btags?\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"(?:추천|소개|검색|찾아|알려)(?:줘|주세요|주세요\??|.*)?$", " ", text)
    text = re.sub(r"\bof\b", " ", text, flags=re.IGNORECASE)
    text = text.replace("의", " ")
    return " ".join(text.strip(" .,:;!?\"'“”‘’<>").split())


def _score_row(
    tag: str,
    row: dict[str, Any],
    query: str,
    signals: set[str],
    existing_tags: set[str],
) -> tuple[float, str, str]:
    score = min(0.28, log10(max(1, _safe_int(row.get("count")))) / 20.0)
    score += min(0.16, 0.04 * len(set(row.get("_queries") or ())))
    score += max(0.0, 0.12 - 0.04 * _safe_int(row.get("_query_order")))
    reason = "관련 후보"
    role = "related"
    explicit = _tag_explicitly_requested(tag, query, row)
    overlap = _english_tag_stems(tag) & _english_query_stems(query, row)
    if explicit:
        score += 0.92
        reason = "검색어와 직접 일치"
        role = "core"
    elif overlap:
        score += min(0.42, 0.16 * len(overlap))
        reason = "검색어 핵심 단어와 일치"
    elif _english_query_stems(query, row):
        score -= 0.42
        reason = "검색어와 직접 겹치는 단어가 약함"
        role = "demoted"

    if tag == "hanging" and "hanging" in signals:
        score += 1.1
        reason = "캐릭터가 매달린 상태를 직접 묘사"
        role = "core"
    elif tag == "ceiling" and "ceiling" in signals:
        score += 1.0
        reason = "매달린 위치/앵커가 천장임"
        role = "core"
    elif tag == "hanging legs" and "hanging" in signals:
        score += 0.55
        reason = "발이 땅에서 떨어져 다리가 늘어진 경우"
        role = "conditional"
    elif tag == "hanging upside down" and "hanging" in signals:
        score += 0.48
        reason = "거꾸로 매달린 경우에 적합"
        role = "conditional"
    elif tag == "hanging on" and "hanging" in signals:
        score += 0.36
        reason = "무언가에 매달리거나 붙잡은 경우"
        role = "conditional"
    elif tag == "suspension":
        if "restraint" in signals:
            score += 0.9
            reason = "구속구에 매달린 속박 자세"
        else:
            score += 0.42
            reason = "구속구에 매달린 경우에만 적합"
        role = "conditional"
    elif tag in {"bound", "bound wrists", "bound arms", "bound legs", "bound ankles"}:
        if "restraint" in signals:
            score += 0.75
            reason = "묶이거나 구속된 상태"
        else:
            score += 0.18
            reason = "묶인 상황이 명시될 때 보조로 사용"
        role = "conditional"
    elif tag == "upside-down" and "upside_down" in signals:
        score += 0.85
        reason = "거꾸로 매달린 방향을 묘사"
        role = "conditional"
    elif tag == "hanged":
        if "death" in signals:
            score += 0.82
            reason = "목매달림/교수형 맥락"
            role = "conditional"
        else:
            score -= 0.42
            reason = "목매달림/사망 의미가 강해 일반 매달림에는 부적합"
            role = "caution"

    if not explicit:
        floor_delta, floor_reason = _generic_noise_floor(tag, row)
        if floor_delta:
            score += floor_delta
            reason = floor_reason
            role = "demoted"

    scene_noise_context = _has_scene_noise_context(signals) and not explicit
    if scene_noise_context and tag in _OBJECT_NOISE_TAGS and not _contains_any(query, _OBJECT_QUERY_HINTS):
        score -= 0.85
        reason = "캐릭터 상태가 아니라 물체 태그에 가까움"
        role = "demoted"
    if scene_noise_context and any(part in tag for part in _SCENE_NOISE_PARTS) and not _contains_any(query, _OBJECT_QUERY_HINTS):
        score -= 0.65
        reason = "요청한 캐릭터 매달림 장면과 다른 세부 태그"
        role = "demoted"
    if scene_noise_context and "bondage" in tag and "restraint" not in signals:
        score -= 0.55
        reason = "속박이 명시되지 않아 일반 매달림보다 후순위"
        role = "demoted"
    if scene_noise_context and tag in _ADULT_POSITION_NOISE and not _contains_any(query, _ADULT_QUERY_HINTS):
        score -= 0.9
        reason = "성행위 체위 태그라 현재 장면 설명과 다름"
        role = "demoted"
    if scene_noise_context and any(part in tag for part in _ADULT_NOISE_PARTS) and not _contains_any(query, _ADULT_QUERY_HINTS):
        score -= 0.85
        reason = "성적 세부 의미가 명시되지 않아 제외 대상"
        role = "demoted"
    if tag in existing_tags:
        score -= 0.55
        reason = "현재 프롬프트에 이미 포함된 태그"
        role = "existing"
    return score, reason, role


def _collect_search_rows(
    queries: Iterable[str],
    *,
    searcher: SearchFn,
    context: Any,
    limit: int,
) -> dict[str, dict[str, Any]]:
    deduped = _dedupe_queries(queries)
    primary = [query for query in deduped if not _HANGUL_RE.search(query)]
    fallback = [query for query in deduped if _HANGUL_RE.search(query)]
    if not primary:
        primary, fallback = fallback, []
    merged = _search_query_phase(primary, searcher=searcher, context=context, limit=limit)
    if not merged and fallback:
        merged = _search_query_phase(fallback, searcher=searcher, context=context, limit=limit)
    return merged


def _search_query_phase(
    queries: Iterable[str],
    *,
    searcher: SearchFn,
    context: Any,
    limit: int,
) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    per_query_limit = max(8, min(24, int(limit or 12) * 2))
    for query_order, search_query in enumerate(queries):
        if not search_query:
            continue
        rows = searcher(search_query, per_query_limit, context)
        for index, row in enumerate(rows or []):
            tag = _norm_tag(row.get("tag"))
            if not tag:
                continue
            existing = merged.get(tag)
            if existing is None:
                existing = {
                    "tag": tag,
                    "count": _safe_int(row.get("count")),
                    "desc": _coerce_text(row.get("desc") or row.get("description"), limit=500),
                    "group": _coerce_text(row.get("group"), limit=200),
                    "cat": _coerce_text(row.get("cat") or row.get("_cat"), limit=80),
                    "_queries": [],
                    "_best_index": index,
                    "_query_order": query_order,
                }
                merged[tag] = existing
            existing["_queries"].append(search_query)
            existing["_best_index"] = min(int(existing.get("_best_index") or 0), index)
            existing["_query_order"] = min(int(existing.get("_query_order") or 0), query_order)
            if _safe_int(row.get("count")) > _safe_int(existing.get("count")):
                existing["count"] = _safe_int(row.get("count"))
    return merged


def _generic_noise_floor(tag: str, row: dict[str, Any]) -> tuple[float, str]:
    tag_norm = _norm_tag(tag)
    if tag_norm in _EXACT_NOISE_TAGS or any(tag_norm.startswith(prefix) for prefix in _NOISE_PREFIXES):
        return -1.25, "메타/동사 매칭 노이즈"
    if tag_norm in _CATEGORY_AXIS_FUNCTION_WORD_TAGS:
        return -1.25, "기능어 매칭 노이즈"
    if any(part in tag_norm for part in _GENITAL_NOISE_PARTS):
        return -0.95, "요청과 직접 관련 없는 신체/성적 세부 노이즈"
    if tag_norm in _SOFT_NOISE_TAGS:
        return -0.75, "요청과 직접 관련 없는 스타일 노이즈"
    if any(part in tag_norm for part in _PROPER_NOISE_PARTS):
        return -0.95, "사용자가 요청하지 않은 고유명 후보"
    cat = _norm_tag(row.get("cat") or row.get("_cat") or row.get("group"))
    if any(marker in cat for marker in ("character", "copyright", "artist", "작가", "캐릭터", "저작권", "작품")):
        return -0.85, "사용자가 요청하지 않은 고유명 후보"
    try:
        from core.ollama_tag_assist_service import is_generic_event_tag

        if is_generic_event_tag(tag_norm):
            return -0.85, "전역 고빈도 이벤트/메타 노이즈"
    except Exception:
        pass
    return 0.0, ""


def _row_matches_category_axis(row: dict[str, Any], axis: str) -> bool:
    tag = _norm_tag(row.get("tag"))
    if tag in _CATEGORY_AXIS_FUNCTION_WORD_TAGS:
        return False
    allowed = _CATEGORY_AXIS_ALLOWED_TOPS.get(axis)
    allowed_folded = _CATEGORY_AXIS_ALLOWED_TOPS_FOLDED.get(axis, frozenset())
    markers = _CATEGORY_AXIS_TOP_MARKERS.get(axis, frozenset())
    if not allowed and not markers:
        return True
    category = _coerce_text(row.get("group") or row.get("_kr_category") or row.get("cat") or row.get("_cat"), limit=200)
    top, _leaves = _category_parts(category)
    top_fold = top.casefold()
    if top in allowed or top_fold in allowed_folded:
        return True
    return any(marker.casefold() in top_fold for marker in markers)


def _category_parts(value: str) -> tuple[str, set[str]]:
    parts = [part.strip() for part in _coerce_text(value, limit=200).split(">") if part.strip()]
    if not parts:
        return "", set()
    return parts[0], set(parts[1:])


def _scene_signals(lowered: str) -> set[str]:
    signals: set[str] = set()
    if _contains_any(lowered, ("매달", "걸려", "늘어", "hanging", "suspended")):
        signals.add("hanging")
    if _contains_any(lowered, ("천장", "ceiling")):
        signals.add("ceiling")
    if _contains_any(lowered, ("구속", "속박", "묶", "bound", "restraint", "bondage")):
        signals.add("restraint")
    if _contains_any(lowered, ("거꾸로", "뒤집", "upside", "inverted")):
        signals.add("upside_down")
    if _contains_any(lowered, _DEATH_QUERY_HINTS):
        signals.add("death")
    return signals


def _has_scene_noise_context(signals: set[str]) -> bool:
    return bool(signals & {"hanging", "ceiling", "upside_down", "restraint", "death"})


def _tag_explicitly_requested(tag: str, query: str, row: dict[str, Any]) -> bool:
    tag_norm = _norm_tag(tag)
    query_norm = _norm_tag(query)
    checks = [query_norm]
    checks.extend(_norm_tag(item) for item in (row.get("_queries") or ()))
    variants = {tag_norm}
    if tag_norm.endswith("s") and len(tag_norm) > 3:
        variants.add(tag_norm[:-1])
    for text in checks:
        if not text:
            continue
        for variant in variants:
            if variant and variant in text:
                return True
    return False


def _context_tags(context: Any) -> set[str]:
    tags = getattr(context, "tags", ())
    if isinstance(context, dict):
        tags = context.get("tags") or context.get("current_tags") or ()
    if not isinstance(tags, (list, tuple, set)):
        return set()
    return {_norm_tag(tag) for tag in tags if _norm_tag(tag)}


def _dedupe_queries(queries: Iterable[str]) -> list[str]:
    out: list[str] = []
    for query in queries or ():
        text = " ".join(_coerce_text(query, limit=120).strip().split())
        if text and text not in out:
            out.append(text)
    return out[:8]


def _normalize_booru_query(value: str) -> str:
    text = _coerce_text(value, limit=120).strip().replace("_", " ")
    if not text:
        return ""
    text = text.replace("`", "")
    text = re.sub(r"\s+", " ", text)
    text = _PROMPT_SCAFFOLD_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip(" .,:;!?\"'“”‘’<>")
    return text.lower()


def _translate_query(value: str, translator: TranslatorFn) -> str:
    try:
        translated = translator(value)
    except Exception:
        translated = None
    return _coerce_text(translated, limit=200).strip()


def _english_query_stems(query: str, row: dict[str, Any]) -> set[str]:
    texts = [query]
    texts.extend(str(item or "") for item in (row.get("_queries") or ()))
    return _english_stems(" ".join(texts))


def _english_tag_stems(tag: str) -> set[str]:
    return _english_stems(tag)


def _english_stems(text: str) -> set[str]:
    try:
        from core.tag_candidate_retriever import stems

        return stems(" ".join(re.findall(r"[a-z0-9]+", str(text).lower())))
    except Exception:
        return {word for word in re.findall(r"[a-z0-9]+", str(text).lower()) if len(word) >= 3}


def _contains_any(text: str, needles: Iterable[str]) -> bool:
    return any(str(needle).lower() in text for needle in needles)


def _norm_tag(value: Any) -> str:
    return " ".join(_coerce_text(value, limit=200).replace("_", " ").lower().split())


def _strip_internal(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if not k.startswith("_")}


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _coerce_text(value: Any, limit: int = 8000) -> str:
    try:
        text = "" if value is None else str(value)
    except Exception:
        return ""
    return text[:limit]


__all__ = [
    "clean_tag_discovery_subject",
    "clean_prompt_search_subject",
    "discover_prompt_tags",
    "discover_semantic_tags",
    "filter_rows_by_category_axis",
    "infer_category_axis_from_text",
    "normalize_category_axis",
    "prompt_tag_queries",
    "rank_semantic_tag_rows",
    "semantic_tag_queries",
]
