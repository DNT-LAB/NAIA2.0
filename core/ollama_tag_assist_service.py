"""Ollama 태그 어시스트 파이프라인 — 무상태 2-호출 구조.

설계 원칙 (작은 모델 전제):
  * LLM은 NAIA 자산을 실행하지 않는다 — 실행 주체는 항상 코드. LLM이 하는 일은
    "텍스트 → JSON 변환" 두 번뿐이다.
  * 호출마다 새 컨텍스트(무상태) — 대화 누적으로 인한 소형 모델 열화를 구조적으로 차단.
  * 호출 1: 사용자 요청(한국어 허용) → 영어 시각 개념 JSON (Ollama structured
    output(format=JSON 스키마)으로 강제 — 툴콜링 미학습 모델에서도 동작).
  * 코드: 개념별 후보 태그 검색 (주입된 searcher = NAIA 태그 인덱스, 진실의 원천).
  * 호출 2: 후보 중 선택 — 스키마 enum이 후보 밖 태그를 샘플링 단계에서 차단(환각 0).
  * 코드: 최종 검증(후보 합집합 교차) 후 count/카테고리를 붙여 반환.
"""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Any, Callable


def _has_hangul(text: str) -> bool:
    return any("\uac00" <= ch <= "\ud7a3" for ch in text)


def _expand_e621(query: str, limit: int = 10) -> list[tuple[str, int]]:
    """e621 \uc758\ubbf8 \ud655\uc7a5(lazy). \ubaa8\ub4c8/\ub370\uc774\ud130 \uc5c6\uc73c\uba74 \ube48 \ub9ac\uc2a4\ud2b8(\ud30c\uc774\ud504\ub77c\uc778 \ubb34\ud574)."""
    try:
        from core.e621_semantic import expand_concept
        return expand_concept(query, limit=limit)
    except Exception:
        return []


# \uc5b4\uc2dc\uc2a4\ud2b8 \uc804\uc6a9 NSFW/\uc778\ubb3c \ubcf4\uac15 \uaddc\uce59 \u2014 \uacf5\uc720 canonical \uaddc\uce59(autocomplete/search \uacf5\uc6a9)\uc758
# \ube48\ud2c8\uc744 \uc5b4\uc2dc\uc2a4\ud2b8\uc5d0\ub9cc \ucd94\uac00(\uacf5\uc720 \ud30c\uc77c \ubbf8\uc218\uc815 \u2192 \ubcd1\ud589\uc138\uc158 \ucda9\ub3cc \ud68c\ud53c). \ubc88\uc5ed \uacbd\ub85c\uac00 \ub9dd\uce58\ub294
# NSFW \uc5b4\ud718(\ubb36\uc778\u2192tied hair \ub4f1)\ub97c \uc6d0\ubb38 \ud55c\uad6d\uc5b4\uc5d0 \uacb0\uc815\ub860 \uc575\ucee4. tags\ub294 danbooru \uc778\ub371\uc2a4\ub85c \uc7ac\uac80\uc99d\ub428.
_ASSIST_EXTRA_RULES: tuple[dict[str, Any], ...] = (
    {"id": "a_1girl", "axis": "composition", "patterns": ["\uc18c\ub140", "\uc5ec\uc790\uc544\uc774", "\uc5ec\uc544", "\uacc4\uc9d1"],
     "forbiddenTerms": ["\uc18c\ub144", "\ub0a8\uc790\uc544\uc774"], "tags": ["1girl"], "confidence": 0.9},
    {"id": "a_1boy", "axis": "composition", "patterns": ["\uc18c\ub144", "\ub0a8\uc790\uc544\uc774", "\ub0a8\uc544"],
     "forbiddenTerms": ["\uc18c\ub140", "\uc5ec\uc790\uc544\uc774"], "tags": ["1boy"], "confidence": 0.9},
    {"id": "a_restraint", "axis": "explicit", "patterns": ["\ubb36\uc778", "\ubb36\uc5ec", "\uacb0\ubc15", "\uc18d\ubc15", "\ud3ec\ubc15", "\uc190\uc774 \ubb36"],
     "tags": ["bound", "bondage"], "confidence": 0.85},
    {"id": "a_rope", "axis": "explicit", "patterns": ["\ubc27\uc904", "\ub85c\ud504"], "tags": ["rope"], "confidence": 0.8},
    {"id": "a_bestiality", "axis": "explicit", "patterns": ["\uc218\uac04", "\uc9d0\uc2b9\uacfc", "\ub3d9\ubb3c\uacfc \uc131"],
     "tags": ["bestiality"], "confidence": 0.85},
    {"id": "a_fellatio", "axis": "explicit", "patterns": ["\ud3a0\ub77c", "\ud3a0\ub77c\uce58\uc624", "\uad6c\uac15\uc131\uad50"],
     "tags": ["fellatio"], "confidence": 0.82},
    {"id": "a_nipples", "axis": "explicit", "patterns": ["\uc816\uaf2d\uc9c0", "\uc720\ub450"], "tags": ["nipples"], "confidence": 0.85},
    {"id": "a_breasts", "axis": "sensitive", "patterns": ["\uac00\uc2b4\uc744", "\uac00\uc2b4\uc774", "\uc720\ubc29", "\uac00\uc2b4 \ub4dc\ub7ec"],
     "tags": ["breasts"], "confidence": 0.78},
    {"id": "a_gagged", "axis": "explicit", "patterns": ["\uc7ac\uac08", "\uc785\ub9c9"], "tags": ["gag"], "confidence": 0.8},
    {"id": "a_eyepatch", "axis": "clothing", "patterns": ["\uc548\ub300"], "tags": ["eyepatch"], "confidence": 0.82},
    {"id": "a_open_mouth", "axis": "expression", "patterns": ["\uc785\uc744 \ubc8c", "\uc785 \ubc8c", "\ubc8c\ub9b0 \uc785"],
     "tags": ["open mouth"], "confidence": 0.8},
)


def _suppress_translation_logging():
    """파이프라인 *중간* 번역(KR→EN)이 번역 기록에 남지 않도록 억제(lazy, best-effort).
    최종 결과(태그+자연어)는 _log_assist_final로 1건만 기록한다. 모듈 없으면 nullcontext."""
    try:
        from core.translation_history import suppress_logging
        return suppress_logging()
    except Exception:
        import contextlib
        return contextlib.nullcontext()


def _log_assist_final(
    raw_text: str, prompt_text: str, *, level: str, rating: str, mode: str,
) -> None:
    """어시스트 **최종 결과**(태그 + 자연어 프롬프트)를 번역 기록에 1건 남긴다(best-effort).

    source=사용자 한글 입력, translated=최종 프롬프트. effort/등급/모드 메타를 함께 붙여
    기록 패널이 배지를 그릴 수 있게 한다. force=True로 억제 블록을 무시하고 항상 기록한다.
    """
    try:
        src = str(raw_text or "").strip()
        dst = str(prompt_text or "").strip()
        if not src or not dst:
            return
        from core.translation_history import log_translation
        log_translation(
            src, dst, direction="ko->en", context="ollama_assist",
            meta={
                "level": str(level or "standard"),
                "rating": str(rating or ""),
                "mode": str(mode or ""),
            },
            force=True,
        )
    except Exception:
        pass


def _canonical_anchors(raw_text: str) -> list[tuple[str, float]]:
    """KR \uad6c\ubb38 \u2192 canonical danbooru \ud0dc\uadf8 \uacb0\uc815\ub860 \ub9e4\ud551(lazy, \ud050\ub808\uc774\uc158 182\uaddc\uce59 + \uc5b4\uc2dc\uc2a4\ud2b8
    NSFW \ubcf4\uac15). forbiddenTerms\ub85c disambiguate\ub41c \uace0\uc2e0\ub8b0 \uc575\ucee4. \uc5c6\uc73c\uba74 \ube48 \ub9ac\uc2a4\ud2b8."""
    try:
        from core.kr_phrase_canonicalizer import (
            match_kr_phrase_canonical_tags, load_kr_phrase_canonical_rules,
        )
        rules = list(load_kr_phrase_canonical_rules()) + list(_ASSIST_EXTRA_RULES)
        return [
            (str(m.tag), float(getattr(m, "confidence", 0.0)))
            for m in match_kr_phrase_canonical_tags(raw_text, rules=rules)
        ]
    except Exception:
        return []


def _retriever_stems(text: str) -> set[str]:
    """\uc5b4\uc2dc\uc2a4\ud2b8 \uac80\uc0c9\uae30 \uc2a4\ud15c(lazy)."""
    try:
        from core.tag_candidate_retriever import stems
        return stems(text)
    except Exception:
        return {w for w in str(text).lower().replace("_", " ").split() if len(w) >= 3}


def _retriever_filter(rows, query_stems, kind, tag_allowed, limit):
    """\uc5b4\uc2dc\uc2a4\ud2b8 \uc804\uc6a9 \ud6c4\ubcf4 \uac8c\uc774\ud2b8(lazy): whole-word \uad00\ub828\uc131 + \uce74\ud14c\uace0\ub9ac. \ubaa8\ub4c8 \uc5c6\uc73c\uba74
    \uae30\uc874 \ub3d9\uc791(paren/rating\ub9cc)\uc73c\ub85c \ud3f4\ubc31 \u2014 \ud30c\uc774\ud504\ub77c\uc778 \ubb34\ud574."""
    try:
        from core.tag_candidate_retriever import filter_concept_candidates
        return filter_concept_candidates(
            rows, query_stems, kind=kind, tag_allowed=tag_allowed, limit=limit,
        )
    except Exception:
        kept = []
        for r in rows:
            t = str(r.get("tag") or "").strip()
            if t and not ("(" in t and ")" in t) and (tag_allowed is None or tag_allowed(t.lower().replace("_", " "))):
                kept.append(r)
        return kept[:limit], []


_PERSON_COUNT_RE = re.compile(r"^\d+\s*(girl|boy)s?$")
_PERSON_COUNT_WORDS = frozenset({"multiple girls", "multiple boys"})


def _is_person_count_tag(tag: str) -> bool:
    """\uc778\uc6d0\uc218 \ud0dc\uadf8(1girl/2boys/multiple girls\u2026)\uc778\uc9c0. solo\ub294 \uc81c\uc678(1\uc778\uacfc \uc591\ub9bd)."""
    t = str(tag).lower().replace("_", " ").strip()
    return bool(_PERSON_COUNT_RE.match(t)) or t in _PERSON_COUNT_WORDS


def _collapse_variants(items: list[dict[str, Any]], protect: set[str]) -> list[dict[str, Any]]:
    """\ubd80\ubd84\uc9d1\ud569 \ubcc0\ud615 \ucd95\uc57d(\uc2e4\uce21 \ub178\uc774\uc988: kimono+kimono dress+kimono only, open mouth+
    slightly open mouth). \ud55c \ud0dc\uadf8\uc758 \ud1a0\ud070\uc774 \ub2e4\ub978 \ud0dc\uadf8 \ud1a0\ud070\uc758 *\uc9c4\ubd80\ubd84\uc9d1\ud569*\uc774\uba74 \uac19\uc740 \uac1c\ub150\uc758
    \ubcc0\ud615\uc73c\ub85c \ubcf4\uace0 \ub354 \ud754\ud55c(\uace0\ube48\ub3c4=canonical) \ucabd\ub9cc \ub0a8\uae34\ub2e4. protect(\uac15\uc81c \uc9c4\uc2e4\ud0dc\uadf8)\ub294 \ubcf4\uc874."""
    toks = [
        {w for w in str(it["tag"]).lower().replace("_", " ").split() if len(w) >= 3}
        for it in items
    ]
    drop: set[int] = set()
    for i in range(len(items)):
        if i in drop or not toks[i]:
            continue
        for j in range(len(items)):
            if i == j or j in drop or not toks[j]:
                continue
            if toks[i] < toks[j]:  # i\uac00 j\uc758 \uc9c4\ubd80\ubd84\uc9d1\ud569(i=base, j=specific)
                ci = int(items[i].get("count") or 0)
                cj = int(items[j].get("count") or 0)
                victim = j if ci >= cj else i
                # \ubcf4\ud638 \ud0dc\uadf8\ub294 \uc808\ub300 \ub4dc\ub86d\ud558\uc9c0 \uc54a\ub294\ub2e4(\ub2e4\ub978 \ucabd\uc744 \ub4dc\ub86d)
                if items[victim]["tag"] in protect:
                    victim = i if victim == j else j
                    if items[victim]["tag"] in protect:
                        continue
                drop.add(victim)
                if victim == i:
                    break
    return [it for k, it in enumerate(items) if k not in drop]


# \uc131\uc801 \uc758\ubbf8 \ud0a4\uc6cc\ub4dc \u2014 e621 safe \uce74\ud14c\uace0\ub9ac(Actions \ud3ec\ud568)\ub97c \ud1b5\uacfc\ud55c \uc131\uc801 \uc561\uc158 \ud0dc\uadf8
# (missionary position, embracing during sex \ub4f1)\uac00 \ube44-explicit \uc694\uccad\uc5d0 \uc0c8\ub294 \uac83\uc744
# \ub9c9\ub294 denylist. \ubd80\ubd84 \ubb38\uc790\uc5f4 \ub9e4\uce6d(\ud0dc\uadf8\ub294 \uacf5\ubc31 \uc815\uaddc\ud654 \ud6c4 \uc18c\ubb38\uc790).
_SEXUAL_KEYWORDS = (
    "sex", "penetrat", "penis", "pussy", "vaginal", "anal", "oral", "fellatio",
    "cunnilingus", "blowjob", "handjob", "footjob", "paizuri", "cum", "ejaculat",
    "orgasm", "masturbat", "fingering", "missionary", "doggystyle", "cowgirl",
    "creampie", "bukkake", "nipple", "areola", "clitoris", "vulva", "testicle",
    "ahegao", "fucked", "fucking", "during sex", "after sex", "imminent",
    "spread legs", "spread pussy", "nude", "naked", "bottomless", "topless",
    "exposed", "bondage", "bdsm", "rape", "pubic", "groin", "crotch", "underwear", "panties", "thong",
)

# \uc0ac\uc6a9\uc790 \uc694\uccad\uc774 \uba85\uc2dc\uc801\uc73c\ub85c \uc131\uc801 \ub9e5\ub77d\uc778\uc9c0 \u2014 explicit\uc774\uba74 \uc704 denylist\ub97c \ud480\uc5b4\uc900\ub2e4.
_EXPLICIT_REQUEST_KEYWORDS = _SEXUAL_KEYWORDS + (
    "nsfw", "lewd", "erotic", "\uc218\uc704", "\uc57c\ud55c", "\uc139\uc2a4", "\ub178\ucd9c", "\uc54c\ubab8",
)


def _is_sexual_tag(tag_norm: str) -> bool:
    t = tag_norm.lower()
    return any(kw in t for kw in _SEXUAL_KEYWORDS)


# 하드코어 키워드 — 분포에 없거나 약하게 잡혀도 무조건 E로 끌어올린다.
_HARDCORE_KEYWORDS = (
    "sex", "penetrat", "penis", "pussy", "vaginal", "anal", "fellatio",
    "cunnilingus", "blowjob", "handjob", "paizuri", "cum", "ejaculat",
    "creampie", "bukkake", "masturbat", "fingering", "missionary",
    "doggystyle", "cowgirl", "clitoris", "vulva", "rape", "ahegao",
    "fucked", "fucking", "during sex", "spread pussy",
)

# NAIA rating 4단계 (danbooru). 어시스트는 "선택 등급 이하 허용"(상한 클램프).
_RATING_ORDER = {"g": 0, "s": 1, "q": 2, "e": 3}
_RATING_INDEX_TO_KEY = ("g", "s", "q", "e")

# Event Preset 후반 보강에서 걸러낼 범용 노이즈 — 파티션 어디서나 고빈도라
# 빈도순 집계가 장면 특이 태그를 누른다(시선/자세/구도/검열/반의어). 실측 누출분
# (looking at viewer, holding phone, untied, bar censor, shaving 등) 포함.
_EVENT_GENERIC_STOPLIST = frozenset({
    "looking at viewer", "looking back", "looking at another", "looking at object",
    "looking away", "looking down", "looking up", "lying", "standing", "sitting",
    "holding", "holding phone", "solo focus", "simple background", "white background",
    "grey background", "bar censor", "censored", "mosaic censoring", "uncensored",
    "untied", "hand on own hip", "shaving", "shaving crotch", "blush", "open mouth",
})

# 크기 형용사 — "huge dog" 검색이 "huge belly/breasts/balls"를 끌어오는 토큰 오염
# 차단용. 후보가 쿼리와 *오직 이 형용사로만* 겹치면(내용 토큰 미공유) 드롭한다.
_SIZE_ADJECTIVES = frozenset({
    "huge", "large", "big", "giant", "gigantic", "massive", "enormous", "oversized",
    "small", "tiny", "little", "long", "short",
})

# 명시적 핵심 행위 — 소형 모델 개념 추출이 "섹스"처럼 명시 단어를 통째로 흘리는 일이
# 잦다(실측). 입력(한/영)에 키워드가 있으면 canonical danbooru 태그를 결정론적으로
# 강제 포함한다(인덱스 실존 + 등급 통과 시). 인원수 강제 포함과 동일 철학 — 진실은 코드.
# (keywords, canonical_tag). 영어 키워드는 단어경계, 한국어는 부분일치.
_FORCED_ACT_TERMS = (
    (("섹스", "성교", "sex", "intercourse"), "sex"),
    (("정상위", "missionary"), "missionary"),
    (("후배위", "doggystyle", "doggy style", "sex from behind"), "sex from behind"),
    (("펠라", "펠라치오", "fellatio", "blowjob", "blow job"), "fellatio"),
    (("커닐", "쿤니", "cunnilingus"), "cunnilingus"),
    (("자위", "masturbat"), "masturbation"),
    (("질내사정", "creampie", "cum inside"), "cum in pussy"),
    (("애무", "fondl", "grop", "caress"), "groping"),
    (("키스", "kiss"), "kiss"),
    (("수간", "bestiality", "zoophilia"), "bestiality"),
    (("강간", "rape"), "rape"),
)

# 태그별 [g,s,q,e] 분포 (data/danbooru_tag_counts_by_rating.json) lazy 캐시.
_RATING_DIST: dict[str, list[int]] | None = None


def _load_rating_dist() -> dict[str, list[int]]:
    global _RATING_DIST
    if _RATING_DIST is not None:
        return _RATING_DIST
    try:
        import json as _json
        from pathlib import Path

        path = Path(__file__).resolve().parents[1] / "data" / "danbooru_tag_counts_by_rating.json"
        data = _json.loads(path.read_text(encoding="utf-8"))
        data.pop("_meta", None)
        _RATING_DIST = data
    except Exception:
        _RATING_DIST = {}
    return _RATING_DIST


def _tag_rating(tag_norm: str) -> str:
    """태그의 danbooru 등급(g/s/q/e). 분포가 주 분류기 — Codex 권고대로 단순
    다수결 대신 보수적 임계(흔한 중립 태그의 S/E 베이스레이트 오염 방지) +
    키워드 하드 오버라이드."""
    t = tag_norm.lower().strip()
    dist = _load_rating_dist()
    # 분포 키는 공백 정규화 태그. 언더스코어/공백 양쪽 시도.
    v = dist.get(t) or dist.get(t.replace(" ", "_"))
    rating = "g"
    if v and isinstance(v, (list, tuple)) and len(v) >= 4:
        g, s, q, e = (float(x) for x in v[:4])
        total = g + s + q + e
        if total > 0:
            gs, ss, qs, es = g / total, s / total, q / total, e / total
            if es >= 0.40:
                rating = "e"
            elif (qs + es) >= 0.45:
                rating = "q"
            elif gs <= 0.06 and (qs + es) >= 0.15:
                rating = "s"
            elif ss >= 0.60 and gs <= 0.10:
                rating = "s"
            else:
                rating = "g"
    # 키워드 하드 오버라이드 — 분포가 약해도 명백한 성적 태그는 끌어올린다.
    if any(kw in t for kw in _HARDCORE_KEYWORDS):
        return "e"
    if _RATING_ORDER[rating] < _RATING_ORDER["q"] and _is_sexual_tag(t):
        rating = "q"
    return rating


def _tag_allowed(tag_norm: str, max_rating: str) -> bool:
    """태그 등급이 상한(max_rating) 이하면 허용. max_rating='s' → g·s 허용."""
    ceil = _RATING_ORDER.get(str(max_rating or "s").lower(), 1)
    return _RATING_ORDER[_tag_rating(tag_norm)] <= ceil


def _resolve_max_rating(options: dict[str, Any], request_text: str) -> str:
    """옵션의 rating/max_rating 우선. 없으면 legacy nsfw bool, 그것도 없으면
    요청 키워드로 추론(Codex: 명시 키워드는 등급 미지정 시에만 상향)."""
    raw = str(options.get("max_rating") or options.get("rating") or "").lower()
    if raw in _RATING_ORDER:
        return raw
    if "nsfw" in options:
        return "e" if bool(options.get("nsfw")) else "s"
    if any(kw in request_text.lower() for kw in _EXPLICIT_REQUEST_KEYWORDS):
        return "e"
    return "s"


# 호출당 상한 — 소형 모델 컨텍스트 예산(호출당 ~2k 토큰)을 지키는 캡.
MAX_CONCEPTS = 10
CANDIDATES_PER_CONCEPT = 12
MAX_ENUM_TAGS = 150

_STOPWORDS = {"the", "and", "with", "near", "from", "into", "onto", "over", "under"}

# subject 계열 정규화 — "two girls" 같은 자연어는 리터럴 검색으로 "2girls"를 못
# 찾는다. 진실(인덱스 존재 여부)은 그대로 검색으로 확인하되, 질의만 정규 태그로.
_SUBJECT_SYNONYMS: dict[str, tuple[str, ...]] = {
    "girl": ("1girl",), "a girl": ("1girl",), "one girl": ("1girl",), "woman": ("1girl",),
    "female": ("1girl",), "young female": ("1girl",), "young woman": ("1girl",),
    "young girl": ("1girl",), "a woman": ("1girl",), "lady": ("1girl",),
    "two girls": ("2girls",), "three girls": ("3girls",), "girls": ("2girls",),
    "two women": ("2girls",), "two females": ("2girls",),
    "boy": ("1boy",), "a boy": ("1boy",), "one boy": ("1boy",), "man": ("1boy",),
    "male": ("1boy",), "young man": ("1boy",), "a man": ("1boy",), "guy": ("1boy",),
    "two boys": ("2boys",), "three boys": ("3boys",), "boys": ("2boys",),
    "two men": ("2boys",), "two males": ("2boys",), "two guys": ("2boys",),
    "alone": ("solo",), "single person": ("solo",),
    # 복합 주어 — 두 정규 태그로 분해 검색.
    "schoolgirl": ("1girl", "school uniform"), "school girl": ("1girl", "school uniform"),
    "schoolboy": ("1boy", "school uniform"), "school boy": ("1boy", "school uniform"),
}

# 창의성 레벨 — 보완 태그/부스트 강도, 자연어 양·길이, Event Preset 참조 개수를
# 한 손잡이로 조절. 4단계, 단계 간 차이를 크게 벌린다(사용자 피드백).
#   event_top  = Event Preset에서 참조할 상위 이벤트 수
#   nat_words  = 자연어 문장당 단어 범위 (min, max)
_LEVELS: dict[str, dict[str, Any]] = {
    "concise":  {"enhance_max": 0,  "boost_top": 0,  "boost_floor": 0.32, "natural_max": 0, "event_top": 0, "nat_words": (6, 12)},
    "standard": {"enhance_max": 3,  "boost_top": 4,  "boost_floor": 0.18, "natural_max": 2, "event_top": 2, "nat_words": (8, 16)},
    "rich":     {"enhance_max": 7,  "boost_top": 8,  "boost_floor": 0.10, "natural_max": 4, "event_top": 4, "nat_words": (12, 24)},
    "max":      {"enhance_max": 12, "boost_top": 12, "boost_floor": 0.05, "natural_max": 6, "event_top": 6, "nat_words": (18, 36)},
}


def _level_cfg(level: Any) -> dict[str, Any]:
    return _LEVELS.get(str(level or "standard").lower(), _LEVELS["standard"])


# Event Preset 파티션 person_id (등급×인원). 선택된 subject 태그에서 추론한다.
_EVENT_PERSON_IDS = (
    "1girl_solo", "1girl", "1girl_1boy", "1girl_multiple_boys",
    "2girls", "multiple_girls", "1boy_solo", "1boy", "1boy_multiple_girls",
    "2boys", "multiple_boys", "multiple_girls_multiple_boys",
)


def _resolve_person_id(selected: list[dict[str, Any]], *, solo: bool = False) -> str:
    """선택된 subject 태그(1girl/2boys/...)에서 Event Preset 파티션 person_id 추론.
    solo는 명시적으로 'solo' 태그가 있거나 solo=True일 때만 _solo 파티션을 쓴다 —
    그 외 단독 인물은 1girl/1boy 파티션(개·다른 객체가 등장하는 장면 포함)."""
    tags = {str(i.get("tag") or "").lower().replace("_", " ") for i in selected}
    explicit_solo = solo or "solo" in tags
    girls = 0
    boys = 0
    for t in tags:
        if t in ("1girl", "1 girl"):
            girls = max(girls, 1)
        elif t in ("2girls", "2 girls"):
            girls = max(girls, 2)
        elif t in ("3girls", "multiple girls", "6+girls"):
            girls = max(girls, 3)
        if t in ("1boy", "1 boy"):
            boys = max(boys, 1)
        elif t in ("2boys", "2 boys"):
            boys = max(boys, 2)
        elif t in ("3boys", "multiple boys", "6+boys"):
            boys = max(boys, 3)
    if girls and boys:
        gp = "1girl" if girls == 1 else ("2girls" if girls == 2 else "multiple_girls")
        bp = "1boy" if boys == 1 else "multiple_boys"
        if gp == "1girl":
            return "1girl_1boy" if boys == 1 else "1girl_multiple_boys"
        if bp == "1boy":
            return "1boy_multiple_girls"
        return "multiple_girls_multiple_boys"
    if girls:
        if girls == 1:
            return "1girl_solo" if explicit_solo else "1girl"
        return "2girls" if girls == 2 else "multiple_girls"
    if boys:
        if boys == 1:
            return "1boy_solo" if explicit_solo else "1boy"
        return "2boys" if boys == 2 else "multiple_boys"
    return "1girl_solo" if explicit_solo else "1girl"

# 일반 개념 검색에서 제외할 카테고리 접두 — 캐릭터/저작권/작품 후보는 사용자가
# 고유명을 직접 말했을 때만 의미가 있다 ("two girls"에 girls und panzer 방지).
_PROPER_NOUN_CATEGORY_PREFIXES = (
    "캐릭터", "저작권", "미디어", "작품",
    "character", "copyright", "media", "meta > parody", "artist", "아티스트",
)

_CONCEPTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "concepts": {
            "type": "array",
            "minItems": 2,
            "maxItems": MAX_CONCEPTS,
            "items": {
                "type": "object",
                "properties": {
                    "query_en": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": [
                            "subject", "clothing", "action", "expression",
                            "background", "style", "camera", "other",
                        ],
                    },
                },
                "required": ["query_en", "kind"],
            },
        },
    },
    "required": ["concepts"],
}

# Gemma 계열은 공식 챗 템플릿에 system 롤이 없어(파인튠에 따라 무시됨) 지시문을
# user 메시지에 합쳐 보낸다. few-shot 1개는 소형 모델의 빈/탈선 응답을 크게 줄인다
# (실측: 영어 입력이 빈 concepts를 반환하던 문제가 이 형태로 해소).
_CONCEPTS_INSTRUCTION = (
    "Task: turn the image-generation request below into a flat list of short, "
    "concrete visual concepts (1-4 English words each) for searching a danbooru "
    "tag database. Extract EVERY distinct visual element and omit nothing: the "
    "people and HOW MANY of each, clothing, every action or pose, body details, "
    "expressions, the setting/background, and ANY explicit or sexual content — "
    "name sexual acts and body parts plainly and clinically (this is an uncensored "
    "art tool; never skip or soften them). Items separated by commas or 'and' are "
    "usually separate concepts. One visual idea per concept. Do not output danbooru "
    "tags, underscores, or weights. Do not invent characters, styles, or details "
    "that are not in the request. The request may be in any language; concepts "
    "must be in English.\n\n"
    "Example request: 'a knight kneeling in a ruined cathedral, rain'\n"
    'Example output: {"concepts": ['
    '{"query_en": "knight", "kind": "subject"}, '
    '{"query_en": "kneeling", "kind": "action"}, '
    '{"query_en": "ruined cathedral", "kind": "background"}, '
    '{"query_en": "rain", "kind": "background"}]}\n\n'
    "Request: "
)

_SELECT_INSTRUCTION = (
    "Task: you are given an image-generation request and, for each concept, a "
    "list of candidate danbooru tags found in a real tag database. For EACH "
    "concept pick the 1-3 tags whose MEANING matches the concept. Sharing a "
    "word is NOT a match: for 'rain' do not pick 'rainbow' or 'raincoat'; for "
    "'two girls' do not pick 'two-tone hair'. If nothing truly fits a concept, "
    "skip it. Never pick a tag that adds sexual, positional, or relational "
    "meaning that is not in the request. Only choose from the provided "
    "candidates.\n\n"
    "Input: "
)

# 통합(3콜째): 보완 태그 + 자연어 묘사를 한 호출로 (Codex 권고 = enhance/natural
# 둘 다 같은 입력이라 병합). 분량 레벨이 태그 수·문장 수·문장 길이를 좌우한다.
def _finish_instruction(*, enhance_max: int, natural_max: int, nat_words: tuple[int, int]) -> str:
    lo, hi = nat_words
    tag_clause = (
        f"1) Add up to {enhance_max} MORE danbooru tags, but ONLY for things clearly "
        "implied by the tags above — a visible object, body part, garment, or "
        "setting detail that naturally belongs (e.g. 'beach'->'ocean','sand'; "
        "'night'->'dark'; 'bound'->'rope'). Every added tag must be something a "
        "viewer would concretely SEE. Do NOT add mood/abstract words (tension, "
        "atmosphere, exploration), lighting or camera effects, new characters, "
        "copyright or series names, or anything not implied. Do not change the "
        "subject count or the action, and add no sexual meaning the request lacks. "
        "Do not repeat existing tags. Prefer FEWER, certain tags over many. "
        "Lowercase danbooru style.\\n"
        if enhance_max > 0 else "1) Output an empty tags array.\\n"
    )
    nat_clause = (
        f"2) Write {max(1, natural_max - 1)}-{natural_max} English scene-description "
        f"phrases ({lo}-{hi} words each) that add atmosphere and vivid detail — "
        "complementary, not a repeat of the tags. English only. Only describe "
        "what the request implies; invent no new location, character, or story.\\n\\n"
        if natural_max > 0 else "2) Output an empty descriptions array.\\n\\n"
    )
    return (
        "Task: you are finishing an anime image prompt. You get the user's "
        "request and the tags chosen so far. Do TWO things:\\n"
        + tag_clause + nat_clause +
        "Example request: 'a girl shivering wrapped in newspaper, snowy night'\\n"
        "Example tags so far: 1girl, shivering, snowing, newspaper, sitting\\n"
        'Example output: {"tags": ["against wall", "huddling", "barefoot", "dark"], '
        '"descriptions": ['
        '"a fragile figure huddled against the biting winter chill, paper rustling softly", '
        '"dim moonlight spilling over the quiet, snow-blanketed street"]}\\n\\n'
        "Input: "
    )

_FINISH_SCHEMA = {
    "type": "object",
    "properties": {
        "tags": {"type": "array", "minItems": 0, "maxItems": 10, "items": {"type": "string"}},
        "descriptions": {"type": "array", "minItems": 1, "maxItems": 4, "items": {"type": "string"}},
    },
    "required": ["tags", "descriptions"],
}

_ONESHOT_INSTRUCTION = (
    "Task: convert the image-generation request below into danbooru tags for an "
    "anime image. The request may be in any language; translate it internally. "
    "Output lowercase danbooru-style tags (real danbooru tags only — do not "
    "invent tag names) plus 2-3 short English scene-description phrases (6-14 "
    "words) that add atmosphere. Be sensible and a little creative, but stay "
    "faithful to the request.\n\n"
    "Example request: 'a girl shivering wrapped in newspaper, snowy night'\n"
    'Example output: {"tags": ["1girl", "shivering", "newspaper", "snowing", '
    '"night", "sitting", "against wall"], "descriptions": ['
    '"a fragile figure huddled against the winter cold", '
    '"dim moonlight over falling snow"]}\n\n'
    "Request: "
)

_ONESHOT_SCHEMA = {
    "type": "object",
    "properties": {
        "tags": {"type": "array", "minItems": 1, "maxItems": 30, "items": {"type": "string"}},
        "descriptions": {"type": "array", "minItems": 0, "maxItems": 4, "items": {"type": "string"}},
    },
    "required": ["tags", "descriptions"],
}


def _selection_schema(candidate_tags: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "selected": {
                "type": "array",
                "maxItems": len(candidate_tags),
                "items": {"type": "string", "enum": candidate_tags},
            },
        },
        "required": ["selected"],
    }


def _verify_schema(tags: list[str]) -> dict[str, Any]:
    """최종 검증: 제거할 태그를 *제공된 태그 안에서만* 고르게(enum) 강제 — 환각 0."""
    return {
        "type": "object",
        "properties": {
            "remove": {
                "type": "array",
                "maxItems": len(tags),
                "items": {"type": "string", "enum": tags},
            },
        },
        "required": ["remove"],
    }


# 최종 검증 패스 — 소형 모델은 생성보다 *판단*을 잘한다. 조립된 태그 전체에서 장면에
# 안 맞는 것(엉뚱한 사물·모순·무의미)을 골라 제거시킨다. enum 제약 + 강제 진실태그 보호.
_VERIFY_INSTRUCTION = (
    "Task: you are quality-checking the danbooru tags for ONE anime image. You get "
    "the user's request and the current tag list. Find tags that clearly do NOT "
    "belong and should be removed:\n"
    "- a tag about an unrelated object (e.g. 'shortcake' food when the scene means "
    "'short hair'; 'backpack' when it means a back view; 'mint chocolate' when "
    "'mint' is a hair color),\n"
    "- a tag that CONTRADICTS the scene (a beard, penis, or '1boy' on a girl-only "
    "scene; a different number of people than stated),\n"
    "- a nonsensical or out-of-place tag,\n"
    "- REDUNDANT near-duplicates: when several tags describe the SAME single detail "
    "in near-identical words (e.g. 'one eye covered', 'covering one eye', 'bandage "
    "over one eye' all for one eyepatch; or 'kimono dress' next to 'kimono'), keep "
    "the single clearest one and list the others for removal.\n"
    "Keep every tag that adds a DISTINCT detail, including atmosphere and sensible "
    "detail. Remove ONLY clear mistakes and redundant duplicates. If all tags fit, "
    "return an empty list. List tags to remove exactly as given.\n\n"
    "Input: "
)


class OllamaTagAssistService:
    def __init__(
        self,
        *,
        base_url: str,
        default_model: str,
        searcher: Callable[[str, int], list[dict[str, Any]]],
        chat: Callable[..., dict[str, Any]] | None = None,
        e621_recommend: Callable[..., list] | None = None,
        event_combo_provider: Callable[..., list[tuple[str, int]]] | None = None,
        translator: Callable[[str], "str | None"] | None = None,
        unloader: Callable[[str], None] | None = None,
    ):
        self.base_url = str(base_url).rstrip("/")
        self.default_model = default_model
        # searcher(query, limit) -> [{tag, count, desc, group, cat}] — NAIA 태그 인덱스.
        self._searcher = searcher
        self._chat = chat or self._default_chat
        # 한국어 사전 번역(Dev0714 STAGE 0): 4B에게 번역을 맡기지 않고 NAIA 내장
        # Google Translate로 깨끗한 영어를 만들어 보낸다(소형 모델 신뢰도↑).
        self._translator = translator
        # 파이프라인 종료 후 VRAM 언로드 콜백(테스트 주입용). None이면 기본 구현.
        self._unloader = unloader
        # Event Preset 참조: (rating, person_id, query) -> [(tag, weight)]. 실제 관측
        # 조합에서 공기 태그를 끌어와 후보를 보강한다(app 레이어에서 주입).
        self._event_combo_provider = event_combo_provider
        # e621 부스트: Dev0714가 tool calling으로 풀려다 실패한 부분을 NAIA가
        # 이미 결정론적 co-occurrence 추천기로 이식해 둠(data/e621_boost_static.py).
        # LLM 무관 — 선택 태그를 입력하면 실데이터 기반 보완 태그를 돌려준다.
        self._e621_recommend = e621_recommend  # None이면 lazy 로드
        # 진행 단계 보고 — FE가 폴링해 "현재 N번째 단계 + 경과초"를 보여준다.
        # (백엔드는 단일 블로킹 호출이라 실제 단계는 여기서만 알 수 있다.)
        self._progress_lock = threading.Lock()
        self._progress: dict[str, Any] = {
            "active": False, "step": 0, "total": 0, "stage": "", "started_at": 0.0, "done": True,
        }

    def _begin_progress(self, total: int, label: str) -> None:
        with self._progress_lock:
            self._progress = {
                "active": True, "step": 1, "total": int(total), "stage": label,
                "started_at": time.time(), "done": False,
            }

    def _stage(self, step: int, label: str) -> None:
        with self._progress_lock:
            if not self._progress.get("active"):
                return
            self._progress["step"] = int(step)
            self._progress["stage"] = label

    def _end_progress(self) -> None:
        with self._progress_lock:
            self._progress["active"] = False
            self._progress["done"] = True

    def progress(self) -> dict[str, Any]:
        """현재 파이프라인 단계 스냅샷(경과초 포함). FE 폴링용."""
        with self._progress_lock:
            snap = dict(self._progress)
        started = float(snap.get("started_at") or 0.0)
        snap["elapsed"] = round(max(0.0, time.time() - started), 1) if started else 0.0
        return snap

    def _to_english(self, text: str) -> tuple[str, str]:
        """한국어가 섞이면 영어로 사전 번역. (영어로 보낼 텍스트, 원문)을 반환.
        번역기 없음/실패면 원문 그대로(LLM 내부 번역 폴백)."""
        original = text
        if self._translator and _has_hangul(text):
            try:
                tr = self._translator(text)
                if tr and tr.strip():
                    return tr.strip(), original
            except Exception:
                pass
        return text, original

    def _unload_model(self, model: str) -> None:
        """파이프라인 종료 후 모델을 VRAM에서 즉시 내린다(keep_alive=0).
        ComfyUI 등과 VRAM을 공유하는 사용자 보호 — 한 번 변환 후 점유 해제.
        베스트에포트(실패해도 결과에 영향 없음)."""
        if self._unloader is not None:
            try:
                self._unloader(model)
            except Exception:
                pass
            return
        try:
            import requests

            # /api/generate에 빈 프롬프트 + keep_alive=0 → 해당 모델 언로드.
            requests.post(
                f"{self.base_url}/api/generate",
                json={"model": model, "keep_alive": 0},
                timeout=10,
            )
        except Exception:
            pass

    def _get_e621_recommend(self):
        if self._e621_recommend is not None:
            return self._e621_recommend
        try:
            import importlib.util
            from pathlib import Path

            path = Path(__file__).resolve().parents[1] / "data" / "e621_boost_static.py"
            spec = importlib.util.spec_from_file_location("e621_boost_static", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            self._e621_recommend = mod.recommend_detailed
        except Exception:
            self._e621_recommend = False  # 로드 실패 — 이후 스킵
        return self._e621_recommend

    # ------------------------------------------------------------------
    # LLM IO — 매 호출 새 컨텍스트(messages 2개뿐), JSON 스키마 강제.
    # ------------------------------------------------------------------

    def _default_chat(
        self,
        user: str,
        schema: dict[str, Any],
        *,
        model: str,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        import requests

        response = requests.post(
            f"{self.base_url}/api/chat",
            json={
                "model": model,
                # 지시문+입력을 user 단일 메시지로 — Gemma 챗 템플릿엔 system 롤이 없다.
                "messages": [
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "format": schema,
                # 단계별 분리: 개념/선택은 결정적(낮게), 자연어/보완은 창의적(높게).
                "options": {"temperature": float(temperature)},
            },
            timeout=(5, 180),
        )
        if response.status_code != 200:
            detail = ""
            try:
                detail = str((response.json() or {}).get("error") or "")
            except Exception:
                pass
            raise RuntimeError(detail or f"Ollama HTTP {response.status_code}")
        content = (response.json().get("message") or {}).get("content") or "{}"
        return json.loads(content)

    # ------------------------------------------------------------------
    # 파이프라인
    # ------------------------------------------------------------------

    def _validate_tag(self, normalized: str) -> dict[str, Any] | None:
        """제안된 태그가 실제 인덱스 태그인지 확인. 정규화 일치만 채택(드리프트 방지)."""
        try:
            rows = list(self._searcher(normalized, 6) or [])
        except Exception:
            return None
        for row in rows:
            tag = str(row.get("tag") or "").strip()
            if not tag:
                continue
            if tag.lower().replace("_", " ") != normalized:
                continue
            category = str(row.get("group") or "")
            if category.lower().startswith(_PROPER_NOUN_CATEGORY_PREFIXES):
                return None
            if "(" in tag and ")" in tag:
                return None
            return {
                "tag": tag,
                "count": int(row.get("count") or 0),
                "category": str(row.get("group") or row.get("cat") or ""),
            }
        return None

    # ------------------------------------------------------------------
    # A안 — 원샷: 번역+태그+자연어를 단일 LLM 호출로. 빠르지만 태그 진실
    # 보장이 없어(모델 기억에 의존) 환각 가능 — B(파이프라인)와 비교용.
    # ------------------------------------------------------------------

    def assist_oneshot(
        self, text: str, *, model: str | None = None, options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # 종료 후 VRAM 언로드 — ComfyUI 등과 공유하는 사용자 보호(사용자 요청).
        if not str(text or "").strip():
            return {"ok": False, "error": "요청 텍스트가 비어 있습니다."}
        target_model = str(model or self.default_model).strip()
        try:
            return self._assist_oneshot(text, model=model, options=options)
        finally:
            self._end_progress()
            self._unload_model(target_model)

    def _assist_oneshot(
        self, text: str, *, model: str | None = None, options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raw_text = str(text or "").strip()
        if not raw_text:
            return {"ok": False, "error": "요청 텍스트가 비어 있습니다."}
        target_model = str(model or self.default_model).strip()
        self._begin_progress(2, "생성")
        _os_rating = _resolve_max_rating(options or {}, raw_text)
        # 중간 번역은 기록하지 않는다 — 최종 결과만 아래에서 1건 남긴다.
        with _suppress_translation_logging():
            request_text, _original_text = self._to_english(raw_text)
        user = _ONESHOT_INSTRUCTION + request_text
        try:
            out = self._chat(user, _ONESHOT_SCHEMA, model=target_model)
        except Exception as exc:
            return {"ok": False, "stage": "oneshot", "error": str(exc) or "원샷 생성 실패"}

        raw_tags = [str(t or "").strip() for t in (out.get("tags") or []) if str(t or "").strip()]
        natural = [
            str(n or "").strip().rstrip(".")
            for n in (out.get("descriptions") or [])
            if str(n or "").strip() and not _has_hangul(str(n))
        ]
        # 코드 검증 + 복구 — 원샷 태그를 인덱스로 거르되, 정확 일치가 없으면
        # 그 용어로 재검색해 가장 흔한 실제 태그로 회수한다(LLM 호출 없음).
        # 드롭되던 핵심 동작("hugging"→"hugging another")을 살리는 게 목적.
        self._stage(2, "태그 검증")
        valid: list[dict[str, Any]] = []
        invalid: list[str] = []
        seen: set[str] = set()
        max_rating = _resolve_max_rating(options or {}, raw_text)
        # Solo 토글 — 원샷에는 인원수 파티션이 없으므로 'solo' 태그를 선두에 보강
        # (인덱스에 존재할 때만, 등급 상한 통과 시).
        if bool((options or {}).get("solo")) and "solo" not in seen:
            solo_v = self._validate_tag("solo")
            if solo_v and _tag_allowed("solo", max_rating):
                valid.append(solo_v)
                seen.add("solo")
        for tag in raw_tags:
            norm = tag.lower().replace("_", " ")
            if norm in seen:
                continue
            seen.add(norm)
            # 등급 상한 초과 태그 차단(원샷 모델이 "female pubic hair" 류를
            # 직접 만드는 것까지) — B의 후보 게이트와 동일 정책.
            if not _tag_allowed(norm, max_rating):
                invalid.append(tag)
                continue
            v = self._validate_tag(norm)
            if not v:
                v = self._recover_tag(norm, seen, max_rating=max_rating)
            if v and v["tag"].lower().replace("_", " ") not in {
                x["tag"].lower().replace("_", " ") for x in valid
            }:
                valid.append(v)
                seen.add(v["tag"].lower().replace("_", " "))
            elif not v:
                invalid.append(tag)

        parts = [", ".join(item["tag"] for item in valid)] + natural
        result = {
            "ok": True,
            "mode": "oneshot",
            "model": target_model,
            "selected": valid,
            "hallucinated": invalid,
            "natural": natural,
            "prompt": ", ".join(p for p in parts if p),
        }
        # 최종 결과(태그+자연어)를 번역 기록에 1건 — 사용자 한글 입력을 키로.
        _log_assist_final(
            raw_text, result["prompt"],
            level=str((options or {}).get("level") or "standard"), rating=_os_rating, mode="fast",
        )
        return result

    def _recover_tag(
        self, normalized: str, seen: set[str], *, max_rating: str = "e",
    ) -> dict[str, Any] | None:
        """정확 일치 실패 시: 그 용어로 검색해 가장 흔한 실제 태그로 회수.
        고유명/괄호형은 제외. subject 시노님("two girls"→2girls)도 먼저 적용.
        등급 상한(max_rating)을 넘는 태그로의 드리프트도 차단."""
        queries = _SUBJECT_SYNONYMS.get(normalized) or (normalized,)
        rows: list[dict[str, Any]] = []
        for q in queries:
            try:
                rows.extend(self._searcher(q, 8) or [])
            except Exception:
                continue
        rows.sort(key=lambda r: int(r.get("count") or 0), reverse=True)
        for row in rows:
            tag = str(row.get("tag") or "").strip()
            if not tag or tag.lower().replace("_", " ") in seen:
                continue
            category = str(row.get("group") or "")
            if category.lower().startswith(_PROPER_NOUN_CATEGORY_PREFIXES):
                continue
            if "(" in tag and ")" in tag:
                continue
            # 복구가 등급 상한을 넘는 고빈도 태그로 드리프트하는 것 차단
            # ("embracing"→"embracing during sex" 류).
            if not _tag_allowed(tag.lower().replace("_", " "), max_rating):
                continue
            return {
                "tag": tag,
                "count": int(row.get("count") or 0),
                "category": str(row.get("group") or row.get("cat") or ""),
            }
        return None

    def assist(
        self, text: str, *, model: str | None = None, options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # 종료 후 VRAM 언로드 — ComfyUI 등과 공유하는 사용자 보호(사용자 요청).
        if not str(text or "").strip():
            return {"ok": False, "error": "요청 텍스트가 비어 있습니다."}
        target_model = str(model or self.default_model).strip()
        try:
            return self._assist(text, model=model, options=options)
        finally:
            self._end_progress()
            self._unload_model(target_model)

    def _assist(
        self, text: str, *, model: str | None = None, options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raw_text = str(text or "").strip()
        if not raw_text:
            return {"ok": False, "error": "요청 텍스트가 비어 있습니다."}
        target_model = str(model or self.default_model).strip()
        opts = options or {}
        solo = bool(opts.get("solo"))
        cfg = _level_cfg(opts.get("level"))
        # 등급 키워드는 원문(한국어 "야한/노출" 등)에서 감지. 그 외 단계는 영어로.
        max_rating = _resolve_max_rating(opts, raw_text)
        # 진행 단계 총개수(레벨에 따라 가변): 개념·검색·선택은 항상, 이벤트·부스트·자연어는 조건부.
        total_stages = 3 + (1 if int(cfg["event_top"]) > 0 else 0) \
            + (1 if int(cfg["boost_top"]) > 0 else 0) \
            + (1 if (int(cfg["enhance_max"]) > 0 or int(cfg["natural_max"]) > 0) else 0)
        self._begin_progress(total_stages, "개념 추출")
        step_no = 1
        # 중간 번역은 기록하지 않는다 — 최종 결과만 함수 끝에서 1건 남긴다.
        with _suppress_translation_logging():
            request_text, original_text = self._to_english(raw_text)

        # 호출 1 — 개념 추출 (새 컨텍스트). 결정적으로 낮게.
        try:
            extracted = self._chat(
                _CONCEPTS_INSTRUCTION + request_text, _CONCEPTS_SCHEMA,
                model=target_model, temperature=0.1,
            )
        except Exception as exc:
            return {"ok": False, "stage": "concepts", "error": str(exc) or "개념 추출 실패"}
        concepts: list[dict[str, Any]] = []
        for item in (extracted.get("concepts") or [])[:MAX_CONCEPTS]:
            if isinstance(item, dict) and str(item.get("query_en") or "").strip():
                concepts.append({
                    "query_en": str(item["query_en"]).strip(),
                    "kind": str(item.get("kind") or "other"),
                })
        if not concepts:
            return {"ok": False, "stage": "concepts", "error": "요청에서 시각 개념을 찾지 못했습니다."}

        # 코드 — 후보 검색 (진실은 NAIA 태그 인덱스)
        step_no += 1
        self._stage(step_no, "후보 검색")
        candidate_info: dict[str, dict[str, Any]] = {}
        concept_results: list[dict[str, Any]] = []
        # 인원수 태그(1girl/2boys/...)는 가장 중요하고 모호하지 않다 — LLM 선택에
        # 맡기면 소형 모델이 드롭하는 일이 잦아(실측: "2boys" 누락) 결정론적으로
        # 강제 포함한다. subject 개념의 시노님 매핑에서 count 태그를 모은다.
        forced_subjects: list[dict[str, Any]] = []
        forced_seen: set[str] = set()
        for concept in concepts:
            queries = _SUBJECT_SYNONYMS.get(concept["query_en"].lower()) or (concept["query_en"],)
            query = queries[0]
            if concept["kind"] == "subject":
                for cand in queries:
                    cl = cand.lower()
                    if cl in forced_seen:
                        continue
                    # 정규 인원/구성 태그만 강제(1girl, 2boys, solo, school uniform 등 시노님 결과).
                    try:
                        hit = next(
                            (r for r in (self._searcher(cand, 4) or [])
                             if str(r.get("tag") or "").strip().lower() == cl),
                            None,
                        )
                    except Exception:
                        hit = None
                    if hit:
                        forced_seen.add(cl)
                        forced_subjects.append({
                            "tag": str(hit.get("tag")),
                            "count": int(hit.get("count") or 0),
                            "category": str(hit.get("group") or ""),
                        })
            rows = []
            search_terms = list(queries)  # 어시스트 검색기 whole-word 게이트의 기준 토큰원
            for q in queries:
                try:
                    rows.extend(self._searcher(q, CANDIDATES_PER_CONCEPT) or [])
                except Exception:
                    continue
            if not rows and " " in query:
                # 다단어 구("sitting by window")는 리터럴 검색이 자주 비므로
                # 의미 단어별로 분해해 후보를 보충한다 (진실은 여전히 인덱스).
                words = [
                    w for w in query.split()
                    if len(w) >= 3 and w.lower() not in _STOPWORDS
                ]
                for word in words[:3]:
                    word_queries = _SUBJECT_SYNONYMS.get(word.lower()) or (word,)
                    search_terms.extend(word_queries)
                    for wq in word_queries:
                        try:
                            rows.extend(self._searcher(wq, max(4, CANDIDATES_PER_CONCEPT // 2)) or [])
                        except Exception:
                            continue
            rows.sort(key=lambda r: int(r.get("count") or 0), reverse=True)
            # 특수화형 제거: 같은 후보군에 generic("school uniform")이 있으면 그
            # 접미사 특수화("ooarai school uniform" 등 작품 종속 변형)는 떨어뜨린다 —
            # 요청에 해당 고유명이 없는 한 잡음이다.
            base_counts = {
                str(r.get("tag") or "").strip().lower(): int(r.get("count") or 0)
                for r in rows
            }

            def _is_noisier_specialization(row):
                tag_l = str(row.get("tag") or "").strip().lower()
                count = int(row.get("count") or 0)
                # 베이스가 특수화보다 흔할 때만 잡음으로 본다 —
                # "school uniform"(859k) vs "uniform"(소수)은 유지,
                # "ooarai school uniform"(9k) vs "school uniform"(859k)은 제거.
                return any(
                    tag_l.endswith(" " + base) and base_counts[base] >= count
                    for base in base_counts
                    if base and tag_l != base
                )

            rows = [r for r in rows if not _is_noisier_specialization(r)]
            # 크기 형용사 토큰 오염 차단(D1, row 사전필터): "huge dog" 후보가 크기
            # 형용사로만 겹치면("huge belly") 드롭. 검색기 whole-word는 "huge"를 공유로
            # 봐서 못 잡으므로(여전히 D1 필요) 여기서 먼저 거른다.
            _q_tokens = set(query.lower().split())
            _q_size = _q_tokens & _SIZE_ADJECTIVES
            _q_content = {
                t for t in _q_tokens
                if t not in _SIZE_ADJECTIVES and t not in _STOPWORDS and len(t) >= 3
            }
            if _q_size and _q_content:
                rows = [
                    r for r in rows
                    if not (
                        (set(str(r.get("tag") or "").lower().replace("_", " ").split()) & _q_size)
                        and not (set(str(r.get("tag") or "").lower().replace("_", " ").split()) & _q_content)
                    )
                ]
            # ▶ 어시스트 전용 검색기 게이트(Codex 설계): 자동완성 인덱스의 prefix/substring
            # 노이즈를 whole-word(스테밍) 관련성 + 카테고리(음식/고유명) denylist로 거른다.
            # shortcake/backpack(no-wholeword)·mint chocolate(음식)이 검색 단계서 원천 차단.
            _query_stems: set[str] = set()
            for _t in search_terms:
                _query_stems |= _retriever_stems(_t)
            # 한도는 넉넉히(기존 per-row 루프는 per-concept 캡이 없었다 — 전역
            # MAX_ENUM_TAGS만). 좁게 캡하면 선택 enum이 줄어 recall이 회귀한다(실측).
            kept_rows, _rejected = _retriever_filter(
                rows, _query_stems, concept["kind"],
                lambda tl: _tag_allowed(tl, max_rating), 48,
            )
            tags = []
            for row in kept_rows:
                tag = str(row.get("tag") or "").strip()
                if not tag:
                    continue
                tags.append(tag)
                if tag not in candidate_info:
                    candidate_info[tag] = {
                        "tag": tag,
                        "count": int(row.get("count") or 0),
                        "category": str(row.get("group") or row.get("cat") or ""),
                    }

            # e621 의미 확장(P1): danbooru substring이 놓치는 의미 클러스터를 e621 wiki
            # 그래프로 보강한다("hands tied"→bound/bondage/rope/arms tied). e621는 시소러스,
            # 출력 태그는 danbooru 인덱스(_validate_tag 정확 일치)로 검증 — 하드코딩 0.
            # ⚠️ action/expression(행위·관계 구)만 — subject/other(1girl 등 일반 인물)는
            # 일반 단어가 "monster girl" 류로 과확장돼 노이즈(Codex P0). 인물은 danbooru
            # 검색 + 강제 인원 태그로 충분.
            if concept["kind"] in ("action", "expression"):
                try:
                    expansions = _expand_e621(concept["query_en"], limit=10)
                except Exception:
                    expansions = []
                for e621_name, _e_cnt in expansions:
                    norm_e = e621_name.lower().replace("_", " ")
                    if norm_e in candidate_info or not _tag_allowed(norm_e, max_rating):
                        continue
                    # 범용 자세/시선 노이즈(standing/lying/sitting 등 wiki "see also")는
                    # 확장 후보에서도 제외 — event 스톱리스트 재사용.
                    if norm_e in _EVENT_GENERIC_STOPLIST:
                        continue
                    v = self._validate_tag(norm_e)   # danbooru 인덱스 정확 일치만 채택
                    if v and v["tag"] not in candidate_info:
                        v = {**v, "category": v.get("category") or "e621-semantic"}
                        candidate_info[v["tag"]] = v
                        tags.append(v["tag"])

            concept_results.append({**concept, "candidates": tags})

        # 명시적 핵심 행위 강제 포함(D2): 입력에 "섹스/sex" 등 명시 act가 있는데
        # 개념 추출이 흘린 경우(실측) 결정론적으로 회수한다. 한국어 원문 + 영어 번역문
        # 양쪽에서 키워드 탐지(영어는 단어경계). canonical 태그가 인덱스 실존 + 등급
        # 통과일 때만 forced에 합류(인원수 강제 포함과 동일 경로 → 선택 앞에 보장).
        _act_haystack = f" {original_text.lower()} \n {request_text.lower()} "
        for keywords, canonical in _FORCED_ACT_TERMS:
            cl = canonical.lower()
            if cl in forced_seen or cl in candidate_info:
                continue
            hit_kw = False
            for kw in keywords:
                k = kw.lower()
                if any("가" <= ch <= "힣" for ch in k):
                    hit_kw = k in _act_haystack            # 한국어: 부분일치
                else:
                    hit_kw = re.search(r"\b" + re.escape(k) + r"\b", _act_haystack) is not None
                if hit_kw:
                    break
            if not hit_kw or not _tag_allowed(cl, max_rating):
                continue
            try:
                act_hit = next(
                    (r for r in (self._searcher(canonical, 4) or [])
                     if str(r.get("tag") or "").strip().lower() == cl),
                    None,
                )
            except Exception:
                act_hit = None
            if act_hit:
                forced_seen.add(cl)
                forced_subjects.append({
                    "tag": str(act_hit.get("tag")),
                    "count": int(act_hit.get("count") or 0),
                    "category": str(act_hit.get("group") or ""),
                })

        # 결정론 canonical 앵커(Codex 권고·기존 자산 활용): 큐레이션된 KR 구문→태그 규칙
        # (data/tag_index/kr_phrase_canonical_rules.json, forbiddenTerms로 disambiguate)을
        # 강제 앵커로 합류. 손으로 만든 _FORCED_ACT_TERMS/시노님의 유지되는 상위집합 —
        # E2B 의존 0(원문 한국어에 직접 결정론 매핑). 인덱스 실존+등급 통과만.
        for c_tag, _conf in _canonical_anchors(raw_text):
            cl = str(c_tag).strip().lower()
            # ⚠️ candidate_info 스킵 제거: 앵커는 *보장*이다. "bound"가 이미 후보(e621
            # 확장)여도 강제 포함해야 한다(이전엔 스킵→LLM이 tied shirt 선택→bound 누락).
            if not cl or cl in forced_seen or not _tag_allowed(cl, max_rating):
                continue
            # 큐레이션 규칙 = 검증된 danbooru 태그. _validate_tag(autocomplete 검색기)이
            # "bound" 류 정확매치를 못 surface해도 신뢰(count/category만 best-effort).
            v = self._validate_tag(cl)
            tag = v["tag"] if v else cl
            if tag in forced_seen:
                continue
            forced_seen.add(tag)
            forced_seen.add(cl)
            forced_subjects.append({
                "tag": tag,
                "count": int((v or {}).get("count") or 0),
                "category": str((v or {}).get("category") or ""),
            })

        # Solo 토글이 켜져 있으면 'solo' 태그를 강제 포함 — 1girl_solo 파티션을 쓰게
        # 하고 최종 프롬프트에도 solo가 들어간다(인덱스에 존재할 때만).
        if solo and "solo" not in forced_seen:
            try:
                solo_hit = next(
                    (r for r in (self._searcher("solo", 4) or [])
                     if str(r.get("tag") or "").strip().lower() == "solo"),
                    None,
                )
            except Exception:
                solo_hit = None
            if solo_hit:
                forced_seen.add("solo")
                forced_subjects.append({
                    "tag": str(solo_hit.get("tag")),
                    "count": int(solo_hit.get("count") or 0),
                    "category": str(solo_hit.get("group") or ""),
                })

        unmatched = [c["query_en"] for c in concept_results if not c["candidates"]]

        # ⚠️ Event Preset 참조는 더 이상 선택 *앞에서* 후보 풀에 주입하지 않는다.
        # (이전엔 여기서 candidate_info에 event 태그를 넣어 selection enum을 오염시켜,
        #  소형 모델이 generic 노이즈에 휘둘리고 핵심 명사를 드롭하는 회귀가 있었음 —
        #  사용자 진단. Dev0714도 선택 enum은 항상 깨끗했고 event 주입이 없었다.)
        # 이제 event 참조는 선택 *이후* 보강 단계로 이동한다(아래 _event_enrich).
        event_added: list[str] = []
        event_top = int(cfg["event_top"])

        candidate_tags = list(candidate_info.keys())[:MAX_ENUM_TAGS]
        if not candidate_tags:
            return {
                "ok": False,
                "stage": "search",
                "error": "태그 데이터베이스에서 후보를 찾지 못했습니다.",
                "concepts": concept_results,
                "unmatched": unmatched,
            }

        # 호출 2 — 후보 중 선택 (새 컨텍스트, enum 강제 = 환각 차단)
        step_no += 1
        self._stage(step_no, "태그 선택")
        selection_user = json.dumps(
            {
                "request": request_text,
                "concepts": [
                    {
                        "concept": c["query_en"],
                        "kind": c["kind"],
                        "candidates": c["candidates"],
                    }
                    for c in concept_results
                    if c["candidates"]
                ],
            },
            ensure_ascii=False,
        )
        try:
            picked = self._chat(
                _SELECT_INSTRUCTION + selection_user,
                _selection_schema(candidate_tags), model=target_model, temperature=0.1,
            )
        except Exception as exc:
            return {"ok": False, "stage": "select", "error": str(exc) or "태그 선택 실패"}

        # 코드 — 최종 검증 (스키마가 보장하지만 후보 합집합과 교차로 한 번 더)
        seen: set[str] = set()
        selected: list[dict[str, Any]] = []
        # 인원수 태그를 맨 앞에 강제 포함 (LLM이 드롭해도 보장). 등급 클램프는 적용.
        for item in forced_subjects:
            tag = item["tag"]
            if tag in seen or not _tag_allowed(tag.lower().replace("_", " "), max_rating):
                continue
            seen.add(tag)
            selected.append(item)
        for tag in picked.get("selected") or []:
            tag = str(tag or "").strip()
            if tag and tag in candidate_info and tag not in seen:
                seen.add(tag)
                selected.append(candidate_info[tag])

        # 코드 단계 — 복원(recovery): 소형 모델이 가끔 핵심 명사를 통째로 드롭한다
        # (실측: bikini/beach가 후보에 있는데도 selected=[shy,1girl]). 구체 명사
        # 개념(subject/clothing/background)이 선택에 한 태그도 못 들어갔으면 그 개념의
        # 최고빈도 후보를 강제 포함한다. action/expression은 후보 자체가 어긋날 수
        # 있어(예: "tied hands"→"tied sleeves") 복원 대상에서 제외 — 오염 방지.
        for c in concept_results:
            if c["kind"] not in ("subject", "clothing", "background"):
                continue
            cands = [t for t in c["candidates"] if t in candidate_info]
            if not cands or any(t in seen for t in cands):
                continue
            top = max(cands, key=lambda t: int(candidate_info[t].get("count") or 0))
            if not _tag_allowed(top.lower().replace("_", " "), max_rating):
                continue
            seen.add(top)
            selected.append(candidate_info[top])

        # 변형 축약: 같은 개념의 부분집합 변형(kimono/kimono dress/kimono only)을 한
        # canonical로 합친다. 강제 인원/행위 태그는 보존. ⚠️ 기본 OFF: 격리측정서
        # recall -0.05(0.645→0.598, 원본의 구체변형까지 합침). 검색기 정밀화가 변형
        # 범람을 더 근본적으로 줄이므로 보류, 코드 보존.
        _protected = {it["tag"] for it in forced_subjects}
        if cfg.get("collapse_variants", False):
            selected = _collapse_variants(selected, _protected)
            seen = {it["tag"] for it in selected}

        # 코드 단계 — e621 co-occurrence 부스트 (LLM 무관). 선택 태그를 입력해
        # 실데이터 기반 보완 태그를 얻는다(explicit/성별 게이트 + action-sexual
        # denylist 내장). Codex 권고: 부스트를 자연어 생성 전에 둬 맥락 반영.
        boosted: list[dict[str, Any]] = []
        boost_top = int(cfg["boost_top"])
        if boost_top > 0:
            step_no += 1
            self._stage(step_no, "e621 보완")
        recommend = self._get_e621_recommend()
        if recommend and selected and boost_top > 0:
            boost_input = ", ".join(item["tag"] for item in selected)
            boost_floor = float(cfg["boost_floor"])
            try:
                results = recommend(boost_input, top_n=boost_top, diversity_cap=2, score_floor=boost_floor) or []
            except TypeError:
                results = recommend(boost_input, top_n=boost_top, diversity_cap=2) or []
            except Exception:
                results = []
            for entry in results[:boost_top]:
                try:
                    tag = str(entry[0]).replace("_", " ").strip()
                    score = float(entry[1])
                except (IndexError, TypeError, ValueError):
                    continue
                if not tag or tag in seen:
                    continue
                # action-sexual denylist: e621 safe 카테고리에 Actions가 포함돼
                # missionary position 류 성적 액션이 비-explicit 요청에 새는 것 차단.
                if not _tag_allowed(tag, max_rating):
                    continue
                seen.add(tag)
                boosted.append({"tag": tag, "count": 0, "category": "e621", "score": round(score, 3)})

        # 코드 단계 — Event Preset 후반 보강(선택 enum을 오염시키지 않도록 선택 이후로
        # 이동). 인원수+등급 파티션에서 실제 관측 조합의 공기 태그를 끌어오되, 선택은
        # 끝났으므로 풀에 넣지 않고 *결과 보강*으로만 추가한다. generic 노이즈 스톱리스트
        # (looking at viewer/untied/bar censor 등)로 거른 뒤 소량만 — 정형 행위(fellatio
        # →penis/oral/hetero/cum)는 통과, 비정형 장면의 빈도 노이즈는 탈락.
        event_enrich: list[dict[str, Any]] = []
        if self._event_combo_provider and event_top > 0 and selected:
            step_no += 1
            self._stage(step_no, "이벤트 참조")
            person_id = _resolve_person_id(selected, solo=solo)
            queryable = [
                c for c in concept_results
                if c["kind"] in ("action", "expression", "clothing", "background")
            ]

            def _top_count(c: dict[str, Any]) -> int:
                return max((candidate_info[t]["count"] for t in c["candidates"] if t in candidate_info), default=0)

            queryable.sort(key=lambda c: (c["kind"] != "action", -_top_count(c)))
            query_terms: list[str] = []
            for c in queryable:
                term = c["query_en"].strip()
                if term and term not in query_terms:
                    query_terms.append(term)
                for w in term.split():
                    wl = w.lower()
                    if len(wl) >= 4 and wl not in _STOPWORDS and wl not in query_terms:
                        query_terms.append(wl)
            agg: dict[str, int] = {}
            n_terms = min(len(query_terms), max(2, event_top // 2))
            for term in query_terms[:n_terms]:
                try:
                    combo = self._event_combo_provider(max_rating, person_id, term, event_top) or []
                except Exception:
                    combo = []
                for entry in combo:
                    try:
                        tag = str(entry[0]).strip()
                        weight = int(entry[1])
                    except (IndexError, TypeError, ValueError):
                        continue
                    norm = tag.lower().replace("_", " ")
                    # 이미 선택/부스트된 것·괄호 고유명·등급초과·generic 노이즈 제외.
                    if not tag or not norm or tag in seen or norm in seen:
                        continue
                    if norm in _EVENT_GENERIC_STOPLIST:
                        continue
                    if "(" in tag and ")" in tag:
                        continue
                    if not _tag_allowed(norm, max_rating):
                        continue
                    agg[tag] = agg.get(tag, 0) + weight
            event_cap = max(2, event_top)
            for tag, weight in sorted(agg.items(), key=lambda kv: kv[1], reverse=True)[:event_cap]:
                seen.add(tag)
                event_enrich.append({"tag": tag, "count": weight, "category": "event"})
                event_added.append(tag)

        # 호출 3 (통합) — 보완 태그 + 자연어 묘사를 한 호출로. 선택+부스트 태그를
        # 보고 작성. 태그는 코드가 인덱스 검증(환각 탈락), 자연어는 창의적(temp↑).
        enhanced: list[dict[str, Any]] = []
        natural: list[str] = []
        enhance_max = int(cfg["enhance_max"])
        natural_max = int(cfg["natural_max"])
        finish_input_items = selected + boosted + event_enrich
        # concise 레벨(enhance_max=0, natural_max≤1)이면 최소 자연어만, 보완 태그 없음.
        if finish_input_items and (enhance_max > 0 or natural_max > 0):
            step_no += 1
            self._stage(step_no, "자연어 생성")
            finish_user = json.dumps(
                {
                    "request": request_text,
                    "tags_so_far": [item["tag"].replace("_", " ") for item in finish_input_items],
                },
                ensure_ascii=False,
            )
            try:
                finished = self._chat(
                    _finish_instruction(
                        enhance_max=enhance_max, natural_max=natural_max,
                        nat_words=cfg["nat_words"],
                    ) + finish_user,
                    _FINISH_SCHEMA, model=target_model, temperature=0.4,
                )
            except Exception:
                finished = {}
            # 관련성 prune(사용자 제안 Stage1→2 정제): enhance 단계가 요구와 무관한
            # 태그를 환각하는 게 측정된 주 노이즈원(실측: "pokemon bw2"·male 장면 "pussy"·
            # "3girls"에 "2girls"·"soft lighting"). 장면 근거 토큰셋(개념 query + 선택/부스트/
            # event 태그)과 토큰을 공유하는 enhance만 채택 — 환각/모순/무관 atmosphere 제거.
            _ground_tokens: set[str] = set()
            for c in concept_results:
                for w in str(c.get("query_en") or "").lower().split():
                    if len(w) >= 3 and w not in _STOPWORDS:
                        _ground_tokens.add(w)
            for it in selected + boosted + event_enrich:
                for w in str(it["tag"]).lower().replace("_", " ").split():
                    if len(w) >= 3 and w not in _STOPWORDS:
                        _ground_tokens.add(w)
            for raw in (finished.get("tags") or [])[:max(0, enhance_max)]:
                norm = str(raw or "").strip().lower().replace("_", " ")
                if not norm or norm in seen:
                    continue
                if not _tag_allowed(norm, max_rating):
                    continue
                # 장면 근거 prune: enhance 태그가 요구/선택 토큰과 하나도 안 겹치면 환각으로 보고 탈락.
                _v_tokens = {w for w in norm.split() if len(w) >= 3 and w not in _STOPWORDS}
                if _v_tokens and not (_v_tokens & _ground_tokens):
                    continue
                validated = self._validate_tag(norm)
                if validated and validated["tag"] not in seen:
                    seen.add(validated["tag"])
                    seen.add(norm)
                    enhanced.append(validated)
            # 자연어 길이 상한은 레벨에 맞춰(max는 최대 40단어까지 허용).
            word_cap = int(cfg["nat_words"][1]) + 6
            for line in finished.get("descriptions") or []:
                if len(natural) >= natural_max:
                    break
                text = str(line or "").strip().rstrip(".")
                if 3 <= len(text.split()) <= word_cap and text and not _has_hangul(text):
                    natural.append(text)

        # 인원수 모순 가드: 인원수는 파이프라인 초반에 결정된 진실(강제 인원 태그).
        # 후속 단계(boost/enhance/event)가 다른 인원수 태그를 끌어오면(실측: 2boys
        # 장면에 "1boy", 3girls 장면에 "2girls") 모순이므로 제거한다. solo는 제외.
        _established_counts = {
            item["tag"].lower().replace("_", " ")
            for item in selected if _is_person_count_tag(item["tag"])
        }

        def _ok_count(item: dict[str, Any]) -> bool:
            if not _is_person_count_tag(item["tag"]):
                return True
            return item["tag"].lower().replace("_", " ") in _established_counts

        boosted = [it for it in boosted if _ok_count(it)]
        enhanced = [it for it in enhanced if _ok_count(it)]
        event_enrich = [it for it in event_enrich if _ok_count(it)]

        # 최종 검증 패스(LLM 판단) — 토큰 매칭이 못 잡는 의미 오류(shortcake/backpack/
        # connected beard 등)를 제거한다. 소형 모델은 생성보다 판단을 잘한다. enum 제약
        # = 환각 0. 강제 진실태그(인원수·명시행위)는 보호. best-effort(절대 파이프라인을
        # 깨지 않음). concise(enhance0&natural0)는 생략.
        # ⚠️ 기본 OFF: round-trip eval에서 Gemma 4B의 *제거* 판단이 과도해 정타 태그까지
        # 지워 aggregate recall 0.645→0.578 회귀(타깃 케이스는 깨끗했지만 12 varied서
        # over-prune). LLM-judge 제거는 이 모델엔 비신뢰 — 코드/검색단계 수정이 정도.
        # 코드는 보존(향후 보수적 설계로 재시도용), 기본 비활성.
        if cfg.get("verify", False) and (enhance_max > 0 or natural_max > 0):
            try:
                # enum은 작게(거대 grammar 회피). 검증 대상은 보강/선택 태그.
                _seen_v: set[str] = set()
                verify_tags = []
                for it in (boosted + event_enrich + enhanced + selected):
                    t = it["tag"]
                    if t not in _protected and t not in _seen_v:
                        _seen_v.add(t)
                        verify_tags.append(t)
                verify_tags = verify_tags[:24]
                if verify_tags:
                    step_no += 1
                    self._stage(step_no, "검증")
                    verify_user = json.dumps(
                        {
                            "request": request_text,
                            "tags": [it["tag"].replace("_", " ") for it in (selected + boosted + event_enrich + enhanced)],
                        },
                        ensure_ascii=False,
                    )
                    verdict = self._chat(
                        _VERIFY_INSTRUCTION + verify_user,
                        _verify_schema(verify_tags), model=target_model, temperature=0.0,
                    )
                    remove = {str(t).strip() for t in (verdict.get("remove") or []) if str(t).strip()}
                    remove -= _protected  # 강제 진실태그는 절대 제거 안 함(이중 안전장치)
                    if remove:
                        selected = [it for it in selected if it["tag"] not in remove]
                        boosted = [it for it in boosted if it["tag"] not in remove]
                        event_enrich = [it for it in event_enrich if it["tag"] not in remove]
                        enhanced = [it for it in enhanced if it["tag"] not in remove]
            except Exception:
                pass  # 검증 실패는 무시 — 검증 없는 결과를 그대로 반환

        all_items = selected + boosted + event_enrich + enhanced
        tag_text = ", ".join(item["tag"] for item in all_items)
        parts = [tag_text] + natural
        full_prompt = ", ".join(p for p in parts if p)
        result = {
            "ok": True,
            "model": target_model,
            "concepts": concept_results,
            "selected": selected,
            "enhanced": enhanced,
            "boosted": boosted,
            "natural": natural,
            "event_referenced": event_added,
            "person_id": _resolve_person_id(selected, solo=solo),
            "max_rating": max_rating,
            "level": str(opts.get("level") or "standard"),
            "translated": request_text if request_text != original_text else "",
            "prompt": full_prompt,
            "tags_only": tag_text,
            "unmatched": unmatched,
        }
        # 최종 결과(태그+자연어)를 번역 기록에 1건 — 사용자 한글 입력을 키로.
        _log_assist_final(
            raw_text, full_prompt,
            level=str(opts.get("level") or "standard"), rating=max_rating, mode="manual",
        )
        return result
