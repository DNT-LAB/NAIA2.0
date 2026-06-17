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

# 맥락-중립 위치/장소 태그 — explicit 장면과 공기율(co-occurrence)이 높지만 태그
# 자체는 비명시적이다. 전체-아카이브 rating-count 도입 후 이런 위치 태그의 explicit
# 베이스레이트가 es>=0.40 임계를 넘어 'e'로 오분류되는 회귀를 막기 위해 'q' 이하로
# 캡한다(_HARDCORE_KEYWORDS 강제-E의 역방향 대칭). _ACT_DOWNGRADE_TABLE의 q-tier
# 안전 다운그레이드 타깃(on bed/on back 등) 큐레이션을 보존하기 위함.
_POSITIONAL_NEUTRAL_TAGS = frozenset({
    "on bed", "on back", "on side", "on stomach",
    "on couch", "on floor", "on chair", "on table",
})

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
    # 범용 포즈/제스처 — 이벤트 단어 폴백이 전역 인기 포즈를 빈도순으로 끌어오던
    # 실측 누출분("폰 보는 소녀"에 v/hand up/hands up 주입 → 브이 포즈 이미지).
    "v", "double v", "peace sign", "hand up", "hands up", "waving",
    "own hands together", "arms up", "arm up",
})


def is_generic_event_tag(tag: Any) -> bool:
    """이벤트 태그 *자체*가 범용 노이즈(스톱리스트)인지. 이벤트 참조에서 이런 이벤트는
    관측 조합 전체가 '전역 인기 포즈 차트'로 퇴화하므로 통째로 건너뛴다(실측: 'looking'
    단어 폴백이 looking at viewer/back/up/down에 매칭 → v/holding hands 주입)."""
    return str(tag or "").strip().lower().replace("_", " ") in _EVENT_GENERIC_STOPLIST


# 본질적으로 2인 이상을 요구하는 관계 태그 — 확정 인원이 1명인 장면에 boost/event/
# 오염된 선택 enum으로 새면 POV 손잡기·이마 맞대기 같은 의도 외 구도를 만든다(실측:
# "lowering head" 후보 오염 → heads together 선택 → e621 부스트가 foreheads touching
# 연쇄). 요청이 직접 언급한 경우(요청 토큰 겹침)는 호출부에서 면제한다.
_TWO_PERSON_TAGS = frozenset({
    "heads together", "foreheads touching", "holding hands", "interlocked fingers",
    "eye contact", "hug", "kiss", "kissing", "french kiss", "imminent kiss",
    "couple", "yuri", "yaoi", "cheek-to-cheek", "face-to-face", "back-to-back",
    "shoulder-to-shoulder", "arm around shoulder", "arm around waist",
})
# "another"를 포함하는 태그(hugging another, hand on another's head 등)는 정의상 2인+.
_ANOTHER_TOKEN_RE = re.compile(r"\banother'?s?\b")


def _is_two_person_tag(tag_norm: str) -> bool:
    """태그가 본질적으로 2인 이상 관계를 의미하는지(큐레이션 목록 + another 패턴)."""
    t = str(tag_norm).lower().strip()
    return t in _TWO_PERSON_TAGS or bool(_ANOTHER_TOKEN_RE.search(t))


# 공기 쿼리 앵커로 쓸 *행위(이벤트)* 어휘. _is_sexual_tag는 노출/의류 상태·부수
# 해부 명사(nude/underwear/panties/nipples/cleavage 등)까지 잡지만 그것들은 이벤트를
# 명명하지 않아 공기 쿼리 가치가 낮고 주입게이트 fail-open 시 노이즈원이 된다(Codex).
# ⚠️ 경계 인식 매칭 — raw substring은 oral⊂pectoral/floral, rape⊂grape/scrape,
# anal⊂analog, sex⊂sexy/bisexual, cum⊂cucumber를 오매칭한다(Codex R2; LLMSearchIndex
# pen→penis 함정과 동형). 완전단어는 양끝 \b, 활용 어근(penetrat/masturbat 등)은 prefix \b.
_ACT_FULL_WORDS = (
    "sex", "penis", "pussy", "vaginal", "anal", "oral", "fellatio", "cunnilingus",
    "blowjob", "handjob", "footjob", "paizuri", "cum", "fingering", "missionary",
    "doggystyle", "cowgirl", "creampie", "bukkake", "ahegao", "fucked", "fucking",
    "rape", "gangbang", "threesome", "foursome", "fivesome", "orgy", "spitroast",
    "tribadism", "rimming", "rimjob", "facesitting", "irrumatio", "deepthroat",
    "mating press", "bestiality", "zoophilia",
)
# 활용형(-ing/-ion/과거형)까지 prefix 경계로 잡아야 하는 어근.
_ACT_STEMS = ("penetrat", "ejaculat", "masturbat", "grop", "orgasm")
_ACT_ANCHOR_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(w) for w in _ACT_FULL_WORDS) + r")\b"
    + r"|\b(?:" + "|".join(re.escape(s) for s in _ACT_STEMS) + r")"
)


def _is_act_anchor(tag_norm: str) -> bool:
    """태그가 공기 쿼리 가치가 있는 *행위/성기접촉* 앵커인지(노출/의류 상태는 제외).
    경계 인식 — group sex/cum in pussy/double penetration은 ✓, grape/floral/analog/
    sexy/cucumber는 ✗(Codex R2 오매칭 차단)."""
    return bool(_ACT_ANCHOR_RE.search(str(tag_norm).lower()))


def _act_anchor_terms(selected: list[dict[str, Any]], limit: int = 3) -> list[str]:
    """확정된 핵심 sexual-act 태그를 Event Preset 공기 쿼리용으로 추출.

    Event Preset 후반 보강은 추출 *개념*(query_en)으로만 쿼리하는데, forced/canonical
    경로로 들어온 핵심 행위(예: 강간→rape)는 개념이 아니라 그 공기 보강을 통째로 못
    받았다(실측: 1girl_multiple_boys/e 파티션의 sex·penis·group sex·vaginal·cum 누락).
    행위 태그는 이벤트를 *직접* 명명하므로 이벤트 참조가 가장 유의미하다. 선택 순서를
    보존(forced 앵커가 selected 선두라 우선)하고, 노출/의류 상태(_is_act_anchor 밖)·
    인원수 태그는 제외, 중복 제거, limit 캡(캡 도달 시 즉시 중단 — limit≤0이면 빈 목록).
    """
    out: list[str] = []
    lim = max(0, limit)
    for it in selected:
        if len(out) >= lim:
            break
        t = str(it.get("tag") or "").strip()
        nt = t.lower().replace("_", " ")
        if t and _is_act_anchor(nt) and not _is_person_count_tag(nt) and t not in out:
            out.append(t)
    return out


# 성별 전용 해부학/행위 — 확정 인원이 한 성별뿐인 장면에 반대 성별 태그가 새면 모순이다
# (실측: "볼펜 자위 소녀"(1girl solo)에 penis/penile masturbation/holding penis 혼입 —
# 'pen' autocomplete가 penis/penile을 surface + "자위" 검색 1위가 penile masturbation).
# 2인 가드·인원수 가드의 사촌. futanari 등 의도적 케이스는 요청 토큰으로 면제(호출부).
# 부분 문자열 매칭(태그는 공백 정규화·소문자) — penis/penile/testicl 등 어근.
_MALE_ANATOMY_MARKERS = (
    "penis", "penile", "testicl", "scrotum", "foreskin", "ballsack", "phimosis",
    "glans", "male masturbation", "male pubic", "male ejaculation", "huge penis",
    "flaccid", "erection",
)
_FEMALE_ANATOMY_MARKERS = (
    "pussy", "vagina", "vaginal", "clitoris", "clitoral", "vulva", "labia",
    "cameltoe", "female ejaculation", "female masturbation", "female pubic",
)
# 요청이 이걸 명시하면 성별 가드 면제(여성+남성기 등 의도적 조합).
_INTERSEX_REQUEST_MARKERS = (
    "futa", "futanari", "newhalf", "dickgirl", "shemale", "trap", "otokonoko",
    "intersex", "futafem", "후타", "후타나리", "인터섹스", "간성", "양성구유", "남녀추니",
)


def _opposite_sex_anatomy(tag_norm: str, *, girls: int, boys: int) -> bool:
    """확정 인원이 한 성별뿐인데 태그가 반대 성별 해부학/행위면 True(모순).
    양성 공존·인원 모호(둘 다 0)면 가드 비활성(False).
    ⚠️ 단어경계 매칭 — substring이면 'male masturbation'이 'female masturbation'에
    걸린다('male'⊂'female'). prefix \\b로 어근(penile→penile masturbation)은 잡되
    female의 male 오탐은 막는다."""
    t = str(tag_norm).lower().replace("_", " ").strip()
    if girls and not boys:
        markers = _MALE_ANATOMY_MARKERS
    elif boys and not girls:
        markers = _FEMALE_ANATOMY_MARKERS
    else:
        return False
    return any(re.search(r"\b" + re.escape(m), t) for m in markers)

# 크기 형용사 — "huge dog" 검색이 "huge belly/breasts/balls"를 끌어오는 토큰 오염
# 차단용. 후보가 쿼리와 *오직 이 형용사로만* 겹치면(내용 토큰 미공유) 드롭한다.
_SIZE_ADJECTIVES = frozenset({
    "huge", "large", "big", "giant", "gigantic", "massive", "enormous", "oversized",
    "small", "tiny", "little", "long", "short",
})

# 특수화 prefix가 동작/상태(holding/sitting 등)면 base의 *잡음 변형*이 아니라 의미적으로
# 다른 태그다 — "holding pen"(누가 듦)은 "pen"(사물 존재)과 다른 정보. 특수화 필터가
# 이걸 base 잡음으로 제거하면, solo 장면에서 'pen'만 남아 NAI가 외부 손이 펜을 들게
# 그린다(실측 S 케이스). 동작/상태 prefix 태그는 특수화 제거에서 면제한다. 작품/색상/
# 고유명 prefix(ooarai/red/competition)는 여기 없으므로 정상 제거된다.
_MEANINGFUL_SPEC_PREFIXES = frozenset({
    "holding", "sitting", "lying", "standing", "kneeling", "leaning", "squatting",
    "wielding", "carrying", "grabbing", "gripping", "covering", "hugging", "riding",
    "wearing", "removing", "spreading", "touching", "licking", "sucking", "straddling",
    "spread", "open", "closed", "crossed", "raised", "bent", "arched",
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


# 활용형(-ing/-ion)·복수형까지 잡아야 하는 *어근* 키워드 — prefix 단어경계만 적용한다.
# 그 외 영어 키워드는 완전 단어(양끝 경계)로 매칭해 일상어 오탐을 막는다.
#   - 동사 어근: masturbat→masturbating, grop→groping, fondl→fondly, caress→caressing
#   - 복수 흔한 명사: nipple→nipples, areola→areolae, testicle→testicles
#   - 완전단어로 두는 것(오탐 위험): sex(≠sexy/sexual/unisex/sexes), kiss(≠kissimmee),
#     rape(≠drape/grape/scrape/rapeseed). 복수형(kisses 등)은 놓치나 대부분 무해.
_STEM_KEYWORDS = frozenset({
    "masturbat", "grop", "fondl", "caress", "penetrat", "ejaculat", "orgasm",
    "nipple", "areola", "testicle",
})


def _kw_in_text(kw: str, haystack: str) -> bool:
    """경계 인식 키워드 매칭. 한국어=부분일치, 영어 어근(_STEM_KEYWORDS)=prefix 경계,
    그 외 영어=완전 단어(양끝 경계). haystack은 소문자. unisex/bisexual의 'sex',
    drape/grape/scrape의 'rape', kissimmee의 'kiss' 같은 오탐을 차단한다."""
    k = kw.lower()
    if any("가" <= ch <= "힣" for ch in k):
        return k in haystack                 # 한국어: 부분일치
    if k in _STEM_KEYWORDS:
        return re.search(r"\b" + re.escape(k), haystack) is not None      # 어근: prefix만
    return re.search(r"\b" + re.escape(k) + r"\b", haystack) is not None  # 완전단어: 양끝


def _forced_act_kw_hit(keywords: tuple[str, ...], haystack: str) -> bool:
    """forced act 키워드 매칭. forced act 루프와 _resolve_max_rating(auto 추론)이 공유
    — 한국어 행위어 단일 출처. 매칭 규칙은 _kw_in_text(어근/완전단어 구분)."""
    return any(_kw_in_text(kw, haystack) for kw in keywords)


def _intersex_marker_in_text(marker: str, haystack: str) -> bool:
    """성별 해부학 가드 면제 마커 매칭.

    영어/라틴 마커는 단어 경계를 지켜 strapless/trapped/trapeze 같은 일상어 오탐을
    막고, 한국어 마커는 띄어쓰기 없는 입력을 고려해 제한된 명시어만 부분일치한다.
    """
    return _kw_in_text(marker, haystack)


# 등급 수위 다이얼 — forced act가 등급 상한을 넘을 때 "생략"이 아니라 그 등급에서
# *자연 통과하는* 수위 태그로 변환한다(사용자: "차단 메커니즘을 손봄"). 설계 원칙:
#   ⚠️ 클램프 면제 없음. 타겟은 전부 해당 등급에서 _tag_allowed를 통과하는 dist-검증
#      태그만(검열 프레이밍 q·자세·근접·분위기). implied sex(e48)/imminent penetration
#      (e96)/hetero(e)/spread legs(e) 류는 "암시 단어"여도 danbooru 분포가 노골과 강상관
#      → NAI가 노골적으로 그려서 **배제**(Opus 패널 B 발견). 약한 쪽에서 시작 — 라이브
#      A/B(사용자 게이트)로 강도 조정.
#   검열 프레이밍(convenient censoring q75·hair censor q87 등)이 Q의 핵심 무기.
#   kiss(g)는 모든 등급 통과 → 테이블 미등재(폴백=원본 그대로).
_ACT_DOWNGRADE_TABLE: dict[str, dict[str, list[str]]] = {
    # 각 칸의 태그는 그 등급에서 _tag_allowed를 자연 통과하는 것만(q칸=q이하, s칸=s이하).
    # 런타임에 한 번 더 필터하므로 안전하지만, 테이블 자체도 등급 정합으로 유지한다.
    "sex":             {"q": ["on bed", "convenient censoring", "covered nipples"],
                        "s": ["lying on bed", "blush", "embarrassed"]},
    "missionary":      {"q": ["on back", "on bed", "convenient censoring"],
                        "s": ["lying on bed", "blush", "embarrassed"]},
    "sex from behind": {"q": ["bent over", "ass focus", "from behind"],
                        "s": ["from behind", "blush"]},
    "fellatio":        {"q": ["tongue out", "face in crotch", "oral invitation"],
                        "s": ["open mouth", "kneeling", "blush"]},
    "cunnilingus":     {"q": ["face in crotch", "oral invitation"],
                        "s": ["between legs", "lying on bed", "blush"]},
    "masturbation":    {"q": ["hand between legs", "covering breasts", "sweat"],
                        "s": ["hand between legs", "blush", "embarrassed"]},
    "groping":         {"q": ["hand on breast", "breast hold", "covering breasts"],
                        "s": ["underboob", "bare shoulders", "blush"]},
    "cum in pussy":    {"q": ["suggestive fluid", "sweat", "steam"],
                        "s": ["blush", "embarrassed"]},
    "rape":            {"q": ["torn clothes", "struggling"],
                        "s": ["struggling", "tears"]},
    "bestiality":      {"q": ["animal"], "s": ["animal"]},
}


def _downgrade_act(
    canonical: str, max_rating: str, *,
    validate_tag: Callable[[str], "dict[str, Any] | None"],
    tag_allowed: Callable[[str, str], bool],
) -> list[dict[str, Any]]:
    """forced act가 상한을 넘으면 그 등급에서 통과하는 수위 태그로 변환. 반환=[태그 dict].
    타겟은 등급 클램프를 *자연 통과*하는 것만(면제 없음) → e등급 노골 타겟 자동 배제.
    각 타겟은 인덱스 실존(validate_tag) 재확인. 테이블 미등재/전부 불가면 빈 리스트(=생략).
    """
    table = _ACT_DOWNGRADE_TABLE.get(canonical)
    if not table:
        return []
    ceil = _RATING_ORDER.get(str(max_rating or "s").lower(), 1)
    if ceil < _RATING_ORDER["s"]:
        return []                        # G = 완전 차단(변환 없이 생략, 사용자 정의)
    variants: list[str] | None = None
    for key in (_RATING_INDEX_TO_KEY[ceil], "q", "s"):   # 요청 등급 칸부터 아래로 폴백
        if key in table:
            variants = table[key]
            break
    if not variants:
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in variants:
        norm = str(raw).lower().replace("_", " ")
        if norm in seen or not tag_allowed(norm, max_rating):
            continue                         # 등급 통과 못 하면 스킵(이중 안전)
        v = validate_tag(norm)
        if not v:
            continue                         # 인덱스 미실존 → 스킵
        seen.add(norm)
        out.append({**v, "category": v.get("category") or "downgrade"})
    return out


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
    # 맥락-중립 위치 태그는 explicit 공기율(베이스레이트)이 높아도 'q' 이하로 캡한다.
    # (명시적 성적 키워드가 있으면 위 _HARDCORE_KEYWORDS override가 이미 'e'를 반환했다.)
    if t in _POSITIONAL_NEUTRAL_TAGS and _RATING_ORDER[rating] > _RATING_ORDER["q"]:
        rating = "q"
    return rating


def _tag_allowed(tag_norm: str, max_rating: str) -> bool:
    """태그 등급이 상한(max_rating) 이하면 허용. max_rating='s' → g·s 허용."""
    ceil = _RATING_ORDER.get(str(max_rating or "s").lower(), 1)
    return _RATING_ORDER[_tag_rating(tag_norm)] <= ceil


def _resolve_max_rating(options: dict[str, Any], request_text: str) -> str:
    """옵션의 rating/max_rating 우선(=사용자 명시 다이얼, 그대로 존중). 없으면 legacy
    nsfw bool, 그것도 없으면(=UI 'auto' 모드) 요청으로 추론.

    auto 추론(P1): 명시 explicit 키워드 + **forced act 키워드의 canonical 등급**으로
    상향한다. 한국어 행위어(자위/펠라/정상위…)는 _EXPLICIT_REQUEST_KEYWORDS에 없어
    s로 떨어지던 결함(QA #1) → _FORCED_ACT_TERMS(한국어 단일 출처)를 재사용해 canonical
    등급(masturbation=e 등)을 반영. 기본 s 하한은 보존."""
    raw = str(options.get("max_rating") or options.get("rating") or "").lower()
    if raw in _RATING_ORDER:
        return raw
    if "nsfw" in options:
        return "e" if bool(options.get("nsfw")) else "s"
    text_l = str(request_text or "").lower()
    hay = f" {text_l} "
    # 경계 인식 매칭(_kw_in_text) — 무경계 부분일치가 unisex→sex, drape→rape를 오탐하던
    # 것 차단(Codex Finding 2).
    rating = "e" if any(_kw_in_text(kw, hay) for kw in _EXPLICIT_REQUEST_KEYWORDS) else "s"
    if _RATING_ORDER[rating] < _RATING_ORDER["e"]:
        for keywords, canonical in _FORCED_ACT_TERMS:
            if _forced_act_kw_hit(keywords, hay):
                cr = _tag_rating(str(canonical).lower())
                if _RATING_ORDER[cr] > _RATING_ORDER[rating]:
                    rating = cr
                    if rating == "e":
                        break
    return rating


# 호출당 상한 — 소형 모델 컨텍스트 예산(호출당 ~2k 토큰)을 지키는 캡.
MAX_CONCEPTS = 10
CANDIDATES_PER_CONCEPT = 12
MAX_ENUM_TAGS = 150
# P1 autocomplete 보정(실측 근거): autocomplete 랭킹은 UI용이라 빈도순이 아니어서
# 정답이 얕은 컷에 탈락한다 — looking at phone 21위·holding phone 16위·school uniform
# 10위(단어 limit 6은 전부 미달). 24면 위 셋을 덮고, head down(31위)은 비용(call2
# 프롬프트 비대) 대비 효용이 낮아 의도적으로 미포함(오선택은 2인 가드가 차단).
WORD_SPLIT_LIMIT = 24        # 단어 분해 검색 깊이(기존 6)
DEEP_INTERSECT_LIMIT = 64    # 교집합 직조회 깊이(leaning out of window 28위)
DEEP_INTERSECT_KEEP = 8      # 교집합 직조회로 합류시킬 최대 행 수
PER_CONCEPT_CANDIDATES = 32  # 개념당 후보 캡(기존 48이나 실효 ≤30이었음 — 상한 보존)
BASE_SUFFIX_LOOKUPS = 6      # 개념당 base 접미 보장 재검색 상한

_STOPWORDS = {"the", "and", "with", "near", "from", "into", "onto", "over", "under"}


def _with_singular_variants(queries: list[str]) -> list[str]:
    """단수형 폴백: 리터럴 substring 검색은 "clouds"로 "cloud"(고빈도 canonical)를 못
    본다(복수형 문자열만 매칭) — count-0 알리아스("clouds")만 후보가 되는 실측 결함.
    s로 끝나는 한 단어 쿼리에 단수형을 덧붙인다(스템이 같아 retriever 점수는 자연 정렬)."""
    out = list(queries)
    for q in queries:
        qs = str(q).strip()
        if " " not in qs and len(qs) >= 4 and qs.endswith("s") and not qs.endswith("ss"):
            singular = qs[:-1]
            if singular not in out:
                out.append(singular)
    return out

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


def _count_girls_boys(tags: set[str]) -> tuple[int, int]:
    """정규화된 태그 집합에서 확정 인원수(여, 남)를 센다 — person_id 추론과
    2인 관계 태그 가드가 공유하는 단일 해석."""
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
    return girls, boys


def _resolve_person_id(selected: list[dict[str, Any]], *, solo: bool = False) -> str:
    """선택된 subject 태그(1girl/2boys/...)에서 Event Preset 파티션 person_id 추론.
    solo는 명시적으로 'solo' 태그가 있거나 solo=True일 때만 _solo 파티션을 쓴다 —
    그 외 단독 인물은 1girl/1boy 파티션(개·다른 객체가 등장하는 장면 포함)."""
    tags = {str(i.get("tag") or "").lower().replace("_", " ") for i in selected}
    explicit_solo = solo or "solo" in tags
    girls, boys = _count_girls_boys(tags)
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

from core.named_entity_groups import is_denylisted_franchise_tag, is_generic_char_attribute

# 일반 개념 검색에서 제외할 카테고리 접두 — 캐릭터/저작권/작품 후보는 사용자가
# 고유명을 직접 말했을 때만 의미가 있다 ("two girls"에 girls und panzer 방지).
# ⚠️ "캐릭터 > 직업/종족/유형/..." generic 인물·생물·속성은 면제(is_generic_char_attribute)
# — cheerleader/nurse/futanari 등 generic 태그 오배제 차단(감사 2026-06-12).
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


# 주입 게이트 — 코드가 만든 보강 제안(e621 부스트·이벤트 참조)을 무조건 주입하지
# 않고, 모델이 "이 장면에 맞는가"를 보고 승인한 것만 넣는다. verify 패스(기본 OFF,
# recall 0.645→0.578 회귀)와 달리 enum이 *제안 목록뿐*이라 — 과제거의 최악에도 잃는 건
# 보강분뿐, 핵심 장면 태그는 구조적으로 못 건드린다. 불확실하면 거부(보강은 옵션).
_GATE_INSTRUCTION = (
    "Task: you are gating EXTRA tags proposed for an anime image prompt. You get the "
    "user's request, the core tags already chosen, and PROPOSED extra tags that came "
    "from co-occurrence statistics — they are often generic or off-scene. Approve a "
    "proposal ONLY if it clearly belongs in THIS exact scene: concretely visible, "
    "consistent with the stated number of people, the location and the mood, and "
    "adding a real detail. Reject generic filler poses, anything tied to a specific "
    "franchise or character not in the request, two-person interactions in a "
    "single-person scene, and anything off-mood. When unsure, reject — extras are "
    "optional. List approved tags exactly as given.\n\n"
    "Input: "
)


def _gate_schema(tags: list[str]) -> dict[str, Any]:
    """주입 게이트: 승인할 태그를 *제안 목록 안에서만*(enum) 고르게 강제 — 환각 0."""
    return {
        "type": "object",
        "properties": {
            "approved": {
                "type": "array",
                "minItems": 0,
                "maxItems": len(tags),
                "items": {"type": "string", "enum": list(tags)},
            },
        },
        "required": ["approved"],
    }


# keep_alive 값(Ollama): -1=무기한 상주, 0=즉시 언로드, None=서버 기본(~5분).
# Auto Boost ON이면 2B 모델을 -1로 살려 둬 매 boost의 콜드 로드를 없앤다.
_KEEP_ALIVE_RESIDENT = -1
_KEEP_ALIVE_UNLOAD = 0
# Scene Boost 전용 chat 타임아웃(connect, read). 일반 assist(5,180)보다 짧게 — 동기 Random
# 경로가 Ollama 지연에 길게 묶이지 않도록 worst-case를 묶는다(정상 boost는 1~5s).
_BOOST_CHAT_TIMEOUT = (5, 45)


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
        # Auto Boost 모델 상주 관리. 토글이 데몬 스레드에서 warm/unload를 비동기로
        # 일으키므로 '마지막 토글 승리'를 보장해야 한다(느린 warm-up이 빠른 unload보다
        # 늦게 끝나도 OFF가 이긴다). _keep_resident=desired intent(scene_boost·assist가
        # 읽음), _resident_model=상주 대상(모델별 언로드 스킵 판정), _resident_loaded=
        # 실제 적재 여부(중복 warm 스킵). meta_lock=빠른 플래그 가드, apply_lock=warm/
        # unload HTTP 직렬화(최대 120s; meta_lock과 분리해 동기 토글이 안 막히게).
        self._keep_resident = False
        self._resident_model: "str | None" = None
        self._resident_loaded = False
        self._resident_meta_lock = threading.Lock()
        self._resident_apply_lock = threading.Lock()
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

    def set_endpoint(
        self, *, base_url: str | None = None, default_model: str | None = None
    ) -> None:
        """라이브 엔드포인트/모델 변경(고급 연결 설정). 호스트가 바뀌면 이전 호스트의
        상주 적재에는 닿을 수 없으므로 ``_resident_loaded`` 추적만 리셋해 새 호스트에
        대해 다시 warm 하도록 한다(이전 호스트 언로드는 불가/불요). 상주 추적이 기존
        기본 모델을 가리키고 있었다면 새 기본 모델을 따라가게 한다. 실제 재-warm은
        호출부(라우트)가 직후 ``set_resident``를 부르면 일어난다 — 여기서 부르면
        비재진입 ``_resident_meta_lock``에 데드락이 나므로 부르지 않는다."""
        with self._resident_meta_lock:
            if base_url is not None:
                new_url = str(base_url).rstrip("/")
                if new_url != self.base_url:
                    self.base_url = new_url
                    self._resident_loaded = False
            if default_model is not None and str(default_model).strip():
                new_model = str(default_model).strip()
                if new_model != self.default_model:
                    old_default = self.default_model
                    self.default_model = new_model
                    if self._resident_model == old_default:
                        self._resident_model = new_model
                    self._resident_loaded = False

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

    def translate_to_english(self, text: str) -> tuple[str, str]:
        """Public wrapper for Chat pipelines that need Assist's translator lane."""
        return self._to_english(text)

    def validate_tag(self, normalized: str) -> dict[str, Any] | None:
        """Public wrapper around the grounded exact tag validator."""
        return self._validate_tag(normalized)

    def recover_tag(
        self, normalized: str, seen: set[str], *, max_rating: str = "e",
    ) -> dict[str, Any] | None:
        """Public wrapper around the no-LLM tag recovery path."""
        return self._recover_tag(normalized, seen, max_rating=max_rating)

    def collapse_variants(self, items: list[dict[str, Any]], protect: set[str]) -> list[dict[str, Any]]:
        """Public wrapper for Assist's subset-variant collapse."""
        return _collapse_variants(items, protect)

    def tag_allowed(self, tag_norm: str, max_rating: str) -> bool:
        """Public wrapper for rating policy checks."""
        return _tag_allowed(tag_norm, max_rating)

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
        keep_alive: Any = None,
        num_predict: Any = None,
        timeout: Any = None,
        think: Any = False,
    ) -> dict[str, Any]:
        import requests

        options: dict[str, Any] = {"temperature": float(temperature)}
        # num_predict: 출력 토큰 상한(속도 backstop). 스키마 강제라 정상 출력은 안 잘리고,
        # 폭주만 막는다. None이면 무제한(기존 동작).
        if num_predict is not None:
            options["num_predict"] = int(num_predict)
        payload: dict[str, Any] = {
            "model": model,
            # 지시문+입력을 user 단일 메시지로 — Gemma 챗 템플릿엔 system 롤이 없다.
            "messages": [
                {"role": "user", "content": user},
            ],
            "stream": False,
            "format": schema,
            # 단계별 분리: 개념/선택은 결정적(낮게), 자연어/보완은 창의적(높게).
            "options": options,
        }
        # think: 추론(<think>) 모델은 답 앞에 긴 사고 블록을 낸다. **기본 False** — 모든
        # assist/oneshot/boost 호출에서 사고를 끄고 곧장 답(JSON)을 받는다. 스키마로 구조가
        # 강제되므로 사고 없이도 정확하고 ~8배 빠르다(Scene Boost는 사고가 num_predict를 다
        # 먹어 빈 출력이 되던 회귀를 think=False로 차단). 사고를 다시 켜려면 think=None 전달.
        if think is not None:
            payload["think"] = bool(think)
        # keep_alive: -1=무기한 유지(Auto Boost 모드 — 모델 상주로 매 boost 재로드 없음),
        # 0=언로드, None=Ollama 기본(~5분). Auto Boost scene_boost는 -1로 모델을 살려 둔다.
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive
        response = requests.post(
            f"{self.base_url}/api/chat",
            json=payload,
            timeout=timeout or (5, 180),
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
            _cat_l = category.lower()
            if _cat_l.startswith(_PROPER_NOUN_CATEGORY_PREFIXES) and not is_generic_char_attribute(_cat_l, normalized):
                return None
            if "(" in tag and ")" in tag:
                return None
            if int(row.get("count") or 0) <= 0:
                # count-0 = 알리아스/사어 행(실측: "clouds"/"black clouds") — 실태그로
                # 안 본다. "cloud"+"clouds" 중복 주입의 원인.
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
            self._finalize_residency(target_model)

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

    def _get_axis_classifier(self):
        """Scene 축 분류기(서비스 1회 캐시). 실패해도 None 반환(boost는 degrade-safe)."""
        if not hasattr(self, "_axis_classifier"):
            try:
                import os
                from core.scene_axis import build_axis_classifier
                repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                self._axis_classifier = build_axis_classifier(repo)
            except Exception:
                self._axis_classifier = None
        return self._axis_classifier

    def scene_boost(
        self, prompt: str, *, model: str | None = None, options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Scene Boost — 기존 프롬프트(주로 danbooru 태그)를 **원샷**으로 배경/구도/분위기
        보강한다. 전 로직은 core/scene_boost(순수·테스트가능)가 보유하고, 여기선 실제
        callable만 주입한다. 주체/의상/행위/인원/저작권 불변 — 검증된 구도 태그 +
        드리프트·에코·한글 필터를 통과한 자연어만 덧붙인다.

        best-effort: 어떤 실패에서도 raise하지 않고 원문 그대로(additions 빈)로 반환.
        Auto Boost(상주) 모드 + 대상 모델이 상주 모델일 때만 chat에 keep_alive=-1을
        주입해 2B 모델을 살려 둔다(다른 모델이면 서버 기본 → self-clean).
        """
        from core.scene_boost import run_scene_boost

        target_model = str(model or self.default_model).strip()
        # 상주 의도 + 대상이 상주 모델일 때만 keep_alive=-1. 진입 시점 스냅샷.
        with self._resident_meta_lock:
            resident_at_start = self._keep_resident
            resident_model = self._resident_model or self.default_model
        keep_alive = _KEEP_ALIVE_RESIDENT if (resident_at_start and target_model == resident_model) else None

        def _boost_chat(*args: Any, **kwargs: Any) -> dict[str, Any]:
            if keep_alive is not None:
                kwargs.setdefault("keep_alive", keep_alive)
            # 동기 Random 경로 worst-case를 묶는다(일반 assist보다 짧게).
            kwargs.setdefault("timeout", _BOOST_CHAT_TIMEOUT)
            # 추론 모델의 <think> 블록이 num_predict를 다 먹어 빈 출력이 되는 걸 차단 +
            # 8배가량 빠르게. Scene Boost는 결정론적 구조(코드)라 모델 사고가 불필요.
            kwargs.setdefault("think", False)
            return self._chat(*args, **kwargs)

        result = run_scene_boost(
            prompt, options or {},
            chat=_boost_chat,
            default_model=target_model,
            tag_rating=_tag_rating,
            validate_tag=self._validate_tag,
            tag_allowed=_tag_allowed,
            is_sexual=_is_sexual_tag,
            is_hardcore=lambda t: any(kw in str(t).lower() for kw in _HARDCORE_KEYWORDS),
            has_hangul=_has_hangul,
            classify_axes=self._get_axis_classifier(),
        )
        # 레이스 backstop: 이 boost가 keep_alive=-1을 보낸 사이 토글이 OFF로 뒤집혔거나
        # 상주 모델이 교체됐다면 모델이 재적재됐을 수 있다 → best-effort 언로드
        # (전체 조건 재확인 — _finalize_residency와 동일 패턴, Codex R1 HIGH 미러).
        if keep_alive is not None:
            with self._resident_meta_lock:
                still_resident = self._keep_resident and target_model == (
                    self._resident_model or self.default_model)
            if not still_resident:
                self._unload_model(target_model)
        return result

    # ------------------------------------------------------------------
    # Auto Boost 모델 상주 관리 — 토글 ON 시 warm-up(적재+상주), OFF 시 언로드.
    # 토글 이벤트가 데몬 스레드를 띄우므로 '마지막 토글 승리'를 apply_lock으로 보장한다.
    # ------------------------------------------------------------------

    def _http_keep_alive_load(self, model: str) -> bool:
        """/api/generate에 빈 프롬프트 + keep_alive=-1 → 모델 적재 후 무기한 상주.
        성공하면 True. best-effort(예외/비200 = False, 결과에 영향 없음)."""
        target = str(model or "").strip()
        if not target:
            return False
        try:
            import requests

            resp = requests.post(
                f"{self.base_url}/api/generate",
                json={"model": target, "prompt": "", "stream": False,
                      "keep_alive": _KEEP_ALIVE_RESIDENT},
                timeout=(5, 120),
            )
            return getattr(resp, "status_code", 0) == 200
        except Exception:
            return False

    def set_resident(self, enabled: bool, model: str | None = None) -> None:
        """Auto Boost 토글 진입점(동기·빠름). 상주 의도만 갱신하고 실제 적재/언로드는
        데몬 스레드에 위임 — warm-up이 최대 120s 블로킹이라 토글 응답을 막으면 안 된다.
        여러 토글이 겹쳐도 _apply_resident_state가 매번 최신 의도를 읽어 마지막이 이긴다."""
        with self._resident_meta_lock:
            self._keep_resident = bool(enabled)
            if enabled:
                self._resident_model = str(model or self.default_model).strip() or self.default_model
        threading.Thread(
            target=self._apply_resident_state, name="ollama-resident-apply", daemon=True,
        ).start()

    def _apply_resident_state(self) -> None:
        """최신 상주 의도에 맞춰 Ollama를 적재/언로드. apply_lock으로 직렬화하고, 락을
        잡은 뒤 '현재' 의도를 다시 읽으므로 마지막 토글 상태로 수렴한다(느린 warm-up이
        빠른 unload보다 늦게 끝나도 OFF가 이긴다)."""
        with self._resident_apply_lock:
            with self._resident_meta_lock:
                enabled = self._keep_resident
                model = self._resident_model or self.default_model
                already = self._resident_loaded
            if enabled:
                if not already:
                    ok = self._http_keep_alive_load(model)
                    with self._resident_meta_lock:
                        # 적재 도중 OFF로 안 바뀐 경우에만 loaded 마킹(바뀌었으면 다음
                        # applier가 언로드).
                        if self._keep_resident:
                            self._resident_loaded = bool(ok)
            else:
                self._unload_model(model)
                with self._resident_meta_lock:
                    self._resident_loaded = False

    def warm_up(self, model: str | None = None) -> None:
        """동기 warm-up(테스트/직접용). 상주 의도 ON + 즉시 적재. 프로덕션 토글 경로는
        set_resident(비동기)를 쓴다."""
        with self._resident_meta_lock:
            self._keep_resident = True
            self._resident_model = str(model or self.default_model).strip() or self.default_model
            target = self._resident_model
        ok = self._http_keep_alive_load(target)
        with self._resident_meta_lock:
            self._resident_loaded = bool(ok) and self._keep_resident

    def unload(self, model: str | None = None) -> None:
        """동기 언로드(테스트/직접용). 상주 의도 OFF + 즉시 언로드(keep_alive=0)."""
        with self._resident_meta_lock:
            self._keep_resident = False
            self._resident_loaded = False
            target = str(model or self._resident_model or self.default_model).strip()
            self._resident_model = None
        self._unload_model(target)

    def _finalize_residency(self, target_model: str) -> None:
        """assist/oneshot 종료 시 모델 상주/언로드 정리(공용 finally 경로).

        Auto Boost로 '이 모델'이 상주 중이면 언로드 대신 keep_alive=-1 재확인(assist의
        기본 keep_alive가 상주 타이머를 ~5분으로 덮었을 수 있다). 상주 모델이 아니면
        (다른 모델 override 포함) 기존대로 언로드 — 무거운 모델이 VRAM에 남지 않게.
        P4(Codex CP7): 재적재 도중/직후 토글이 OFF로 뒤집혔으면 best-effort 언로드
        백스톱 — scene_boost와 동일 패턴('마지막 토글 승리'를 이 경로에도 보장)."""
        with self._resident_meta_lock:
            is_resident_model = self._keep_resident and target_model == (
                self._resident_model or self.default_model)
        if is_resident_model:
            self._http_keep_alive_load(target_model)
            # 재확인은 플래그만이 아니라 *전체 조건* — 적재 중 상주 모델이 A→B로
            # 교체되면(_keep_resident는 여전히 True) A를 언로드해야 한다(Codex R1 HIGH).
            with self._resident_meta_lock:
                still_resident = self._keep_resident and target_model == (
                    self._resident_model or self.default_model)
            if not still_resident:
                self._unload_model(target_model)
        else:
            self._unload_model(target_model)

    def _recover_tag(
        self, normalized: str, seen: set[str], *, max_rating: str = "e",
    ) -> dict[str, Any] | None:
        """정확 일치 실패 시: 그 용어로 검색해 가장 흔한 실제 태그로 회수.
        고유명/괄호형은 제외. subject 시노님("two girls"→2girls)도 먼저 적용.
        등급 상한(max_rating)을 넘는 태그로의 드리프트도 차단."""
        # 디나이된 franchise 오염(super saiyan/au ra 등)은 *회수하지 않는다* — 검색 치환이
        # super saiyan→super crown 류 다른 franchise/무관 태그로 새기 때문(Codex R2). 드롭.
        if is_denylisted_franchise_tag(normalized):
            return None
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
            if int(row.get("count") or 0) <= 0:
                continue  # count-0 알리아스/사어 행으로는 복구하지 않는다(Codex CP4)
            category = str(row.get("group") or "")
            _cat_l = category.lower()
            if _cat_l.startswith(_PROPER_NOUN_CATEGORY_PREFIXES) and not is_generic_char_attribute(_cat_l, tag):
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
            self._finalize_residency(target_model)

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
        # 진행 단계 총개수(레벨에 따라 가변): 개념·검색·선택은 항상, 이벤트·부스트·
        # 주입 게이트·자연어는 조건부.
        total_stages = 3 + (1 if int(cfg["event_top"]) > 0 else 0) \
            + (1 if int(cfg["boost_top"]) > 0 else 0) \
            + (1 if (int(cfg["boost_top"]) > 0 or int(cfg["event_top"]) > 0) else 0) \
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
        # 디나이된 franchise 오염 개념(super saiyan/au ra/os-tan 등)은 검색 전 드롭 — 검색/
        # 회수가 다른 태그로 치환(super saiyan→super saiyan 4, os-tan→tan)해 새는 것 차단
        # (Codex R3). generic leaf 디나이(_excluded·리트리버·_recover_tag)와 일관 — 6종은
        # 인덱스·후보 enum·회수·개념 어디서도 surface 되지 않는다.
        concepts = [c for c in concepts if not is_denylisted_franchise_tag(c["query_en"])]
        if not concepts:
            return {"ok": False, "stage": "concepts", "error": "요청에서 시각 개념을 찾지 못했습니다."}

        # 요청 근거 스템(요청문 + 개념 쿼리만, 태그 유래 토큰은 제외 — 섞으면 자기 면제가
        # 된다). "요청이 직접 말했는가" 판정용: 2인 관계 태그 가드의 면제 기준.
        # P2(Codex CP2b): 부정 윈도 — 앞 2토큰 안에 no/without/not류가 있으면 그 토큰은
        # "부정 언급"이라 면제 근거가 못 된다("no holding hands"). 같은 토큰이 다른 곳에서
        # 긍정 언급되면 긍정이 이긴다(보수적). 한국어 부정("없이/말고")은 사전 번역이
        # without/no로 정규화하므로 영어 윈도로 충분하다.
        _NEG_WORDS = frozenset({
            "no", "not", "without", "never", "don't", "dont", "avoid", "none",
            "neither", "nor",
        })
        _affirmed: set[str] = set()
        _negated: set[str] = set()
        for _src in (request_text, original_text):
            _toks = re.findall(r"[a-z']+", str(_src).lower())
            for _i, _w in enumerate(_toks):
                if len(_w) < 3 or _w in _STOPWORDS or _w in _NEG_WORDS:
                    continue
                if any(p in _NEG_WORDS for p in _toks[max(0, _i - 2):_i]):
                    _negated.add(_w)
                else:
                    _affirmed.add(_w)
        _negated_only = _negated - _affirmed
        _concept_words = {
            _w
            for c in concepts
            for _w in re.findall(r"[a-z']+", str(c["query_en"]).lower())
            if len(_w) >= 3 and _w not in _STOPWORDS and _w not in _negated_only
        }
        # 면제 비교는 스템으로(단·복수 hand/hands 흡수). 부정-전용 토큰의 스템은 제외하되
        # 긍정 출처가 같은 스템을 내면 긍정이 이긴다.
        request_stems: set[str] = _retriever_stems(" ".join(_affirmed | _concept_words))
        request_stems -= (_retriever_stems(" ".join(_negated_only)) - _retriever_stems(" ".join(_affirmed)))
        # 성별 해부학 가드 면제 — 요청이 futanari/trap 등 의도적 양성 조합을 명시하면
        # 반대 성별 해부학을 허용한다(원문 한국어 + 번역문 양쪽 검사).
        _intersex_haystack = f" {original_text.lower()} {request_text.lower()} "
        _intersex_request = any(
            _intersex_marker_in_text(m, _intersex_haystack)
            for m in _INTERSEX_REQUEST_MARKERS
        )

        # 의도보존 관계 anchor(결정론·fail-closed) — 원문/번역에서 관계(부녀/모자/가족…)를
        # 회수해 관계 태그(father and daughter 등)를 출력에 보존한다. 번역+1girl/1boy 압축으로
        # 관계가 증발하던 문제 수정. anchor 없으면 빈 packet → 무변경(관계 환각 0). LLM 호출 0.
        # 강한 제약(자연어 prune)은 두지 않고 soft contract로만 안내(개인 편집 가능).
        from core.scene_anchors import extract_scene_anchors, family_safe_contract_line

        scene_anchors = extract_scene_anchors(
            original_text, request_text, negated_words=_negated_only
        )
        # 관계 태그 1개만 강제 — most-specific 우선, 인덱스+등급 검증 통과하는 첫 1개.
        forced_relations: list[dict[str, Any]] = []
        for _rel in scene_anchors.get("relationships", ()):
            _rel_norm = str(_rel).strip().lower().replace("_", " ")
            if not _rel_norm or not _tag_allowed(_rel_norm, max_rating):
                continue
            _rel_valid = self._validate_tag(_rel_norm)
            if _rel_valid:
                forced_relations.append(_rel_valid)
                break

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
            for q in _with_singular_variants(list(queries)):
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
                    for wq in _with_singular_variants(list(word_queries)):
                        try:
                            rows.extend(self._searcher(wq, WORD_SPLIT_LIMIT) or [])
                        except Exception:
                            continue
                # 교집합 직조회(P1): 단어별로 더 깊이 훑되, 개념 스템을 2개 이상 공유하는
                # 후보만 합류 — "looking at cell phone"의 looking at phone(21위),
                # "leaning against window"의 leaning out of window(28위) 같은 다단어
                # 직접 표현이 얕은 컷에 묻히는 것을 구제한다. 단일 겹침의 대량 잡음
                # (head tilt/headphones류)은 합류시키지 않아 enum이 비대해지지 않는다.
                q_stems_deep = _retriever_stems(query)
                if len(q_stems_deep) >= 2:
                    have = {
                        str(r.get("tag") or "").lower().replace("_", " ") for r in rows
                    }
                    harvest: list[dict[str, Any]] = []
                    h_seen: set[str] = set()
                    for word in words[:3]:
                        try:
                            deep = self._searcher(word, DEEP_INTERSECT_LIMIT) or []
                        except Exception:
                            continue
                        for r in deep:
                            tl = str(r.get("tag") or "").lower().replace("_", " ")
                            if not tl or tl in have or tl in h_seen:
                                continue
                            if len(_retriever_stems(tl) & q_stems_deep) >= 2:
                                h_seen.add(tl)
                                harvest.append(r)
                    harvest.sort(key=lambda r: int(r.get("count") or 0), reverse=True)
                    rows.extend(harvest[:DEEP_INTERSECT_KEEP])
            # base 접미 보장(P1): 후보에 "… school uniform"류 특수화가 있는데 그 base가
            # row set에 없으면 _is_noisier_specialization이 비교 기준을 잃어 작품 교복이
            # 살아남는다(실측: search("school") top-6에 school uniform 859k 부재).
            # 3단어+ 태그의 끝 2단어 base를 정확 일치 재조회로 합류시킨다.
            if rows:
                have_tags = {
                    str(r.get("tag") or "").lower().replace("_", " ") for r in rows
                }
                base_lookups = 0
                for r in list(rows):
                    if base_lookups >= BASE_SUFFIX_LOOKUPS:
                        break
                    tl = str(r.get("tag") or "").lower().replace("_", " ")
                    parts = tl.split()
                    if len(parts) < 3 or any(len(p) < 3 for p in parts[-2:]):
                        continue
                    base = " ".join(parts[-2:])
                    if base in have_tags:
                        continue
                    have_tags.add(base)  # 실패해도 같은 base를 재조회하지 않는다
                    base_lookups += 1
                    try:
                        hit = next(
                            (b for b in (self._searcher(base, 4) or [])
                             if str(b.get("tag") or "").strip().lower().replace("_", " ") == base
                             and int(b.get("count") or 0) > 0),
                            None,
                        )
                    except Exception:
                        hit = None
                    if hit:
                        rows.append(hit)
            rows.sort(key=lambda r: int(r.get("count") or 0), reverse=True)
            # 특수화형 제거: 같은 후보군에 generic("school uniform")이 있으면 그
            # 접미사 특수화("ooarai school uniform" 등 작품 종속 변형)는 떨어뜨린다 —
            # 요청에 해당 고유명이 없는 한 잡음이다.
            base_counts = {
                str(r.get("tag") or "").strip().lower(): int(r.get("count") or 0)
                for r in rows
            }
            # 쿼리 스템(전 검색어 합집합) — 특수화 면제 판정과 retriever 게이트가 공유.
            _query_stems: set[str] = set()
            for _t in search_terms:
                _query_stems |= _retriever_stems(_t)

            def _is_noisier_specialization(row):
                tag_l = str(row.get("tag") or "").strip().lower()
                count = int(row.get("count") or 0)
                # 면제: 동작/상태 prefix(holding/sitting 등)는 base 잡음이 아니라 의미적
                # 변형 — "holding pen"이 "pen" 특수화로 제거→solo인데 외부 손이 펜 듦(실측).
                first = tag_l.split(" ", 1)[0] if tag_l else ""
                if first in _MEANINGFUL_SPEC_PREFIXES:
                    return False
                # 면제(P1): 태그 스템이 *전부* 쿼리 스템에서 온 다단어 태그는 개념의
                # 직접 합성 표현이다 — "looking at phone"({look,phon}⊆{look,cell,phon})을
                # base "phone"(111k)의 특수화로 오판해 떨어뜨리던 실측 결함 수정.
                # 프랜차이즈 특수화(ooarai/hasu …)는 쿼리 밖 스템이 있어 면제 불가.
                tl_stems = _retriever_stems(tag_l)
                if len(tl_stems) >= 2 and tl_stems <= _query_stems:
                    return False
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
            # (_query_stems는 특수화 면제 판정과 공유 — 위에서 계산)
            # 한도는 넉넉히 — 좁게 캡하면 선택 enum이 줄어 recall이 회귀한다(실측).
            # P1로 단어 분해가 깊어져(6→24) rows가 커졌으므로 개념당 32로 캡하되,
            # 컷은 retriever 점수순(교집합 승격 포함)이라 정답이 컷에 밀리지 않는다.
            # (기존 캡 48은 rows가 실효 ≤30이라 사실상 무캡이었다 — 상한은 보존됨.)
            kept_rows, _rejected = _retriever_filter(
                rows, _query_stems, concept["kind"],
                lambda tl: _tag_allowed(tl, max_rating), PER_CONCEPT_CANDIDATES,
            )
            tags = []
            for row in kept_rows:
                tag = str(row.get("tag") or "").strip()
                if not tag or int(row.get("count") or 0) <= 0:
                    continue  # count-0 알리아스/사어 행은 후보 가치 없음(cloud/clouds 중복원)
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
            # 강제 행위는 *보장*이다 — 이미 후보(candidate_info)여도 강제 포함한다
            # (canonical 앵커와 동일 결정). 후보 잔류에 맡기면 enum 캡 탈락이나 모델
            # 선택 누락으로 잃을 수 있다(Codex R1). 중복 주입은 선택 단계 seen이 막는다.
            if cl in forced_seen:
                continue
            if not _forced_act_kw_hit(keywords, _act_haystack):
                continue
            if not _tag_allowed(cl, max_rating):
                # 등급 초과 → "생략"이 아니라 등급 내 수위 태그로 변환(P2 다이얼).
                # 변환 타겟은 등급 클램프를 자연 통과하므로 후속 조립서 안 잘린다.
                forced_seen.add(cl)          # 원본 canonical 재주입 방지(변환으로 대체)
                for v in _downgrade_act(
                    cl, max_rating, validate_tag=self._validate_tag, tag_allowed=_tag_allowed,
                ):
                    vt = str(v.get("tag") or "").lower().replace("_", " ")
                    if not vt or vt in forced_seen:
                        continue
                    forced_seen.add(vt)
                    forced_subjects.append(v)
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

        # 선택 enum(스키마) — 전역 캡(150)을 개념 간 round-robin으로 공정 분배한다.
        # 삽입순이면 단어 분해 상향(P1) 후 앞 개념이 캡을 독식해 뒤 개념(주로 배경)
        # 후보가 통째로 잘린다. 각 개념의 후보는 점수순이므로 round-robin은 곧
        # "개념별 상위 N개씩"이 된다.
        candidate_tags: list[str] = []
        _rr_seen: set[str] = set()
        _rr_idx = 0
        while len(candidate_tags) < MAX_ENUM_TAGS:
            _advanced = False
            for c in concept_results:
                cands = c["candidates"]
                if _rr_idx >= len(cands):
                    continue
                _advanced = True
                t = cands[_rr_idx]
                if t not in _rr_seen and t in candidate_info:
                    _rr_seen.add(t)
                    candidate_tags.append(t)
                    if len(candidate_tags) >= MAX_ENUM_TAGS:
                        break
            if not _advanced:
                break
            _rr_idx += 1
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
        # 모델에 보여주는 후보는 스키마 enum 멤버로 한정 — round-robin 캡(150) 밖
        # 후보가 보이기만 하고 선택 불가능한(grammar 거부) 불일치를 막는다.
        _enum_set = set(candidate_tags)
        selection_user = json.dumps(
            {
                "request": request_text,
                "concepts": [
                    {
                        "concept": c["query_en"],
                        "kind": c["kind"],
                        "candidates": [t for t in c["candidates"] if t in _enum_set],
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
        # 관계 anchor 태그(부녀 등)를 강제 포함 — 인원수 태그처럼 핵심 의도라 LLM 선택에
        # 맡기지 않는다. _protected에도 들어가 injection gate/2인 가드가 제거하지 못한다.
        for item in forced_relations:
            tag = item["tag"]
            if tag in seen:
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
        # 후보를 강제 포함한다. action/expression은 후보 자체가 어긋날 수
        # 있어(예: "tied hands"→"tied sleeves") 복원 대상에서 제외 — 오염 방지.
        # 선정 기준은 count 최대가 아니라 *개념 쿼리 스템 겹침* 우선(겹침 0이면 복원 포기) —
        # count 최대는 'school hallway'(배경)에 hasu no sora school uniform(작품 교복,
        # 10k>hallway 5k)을 주입하는 실측 사고를 냈다. 겹침 기준이면 school/hallway가 이긴다.
        for c in concept_results:
            if c["kind"] not in ("subject", "clothing", "background"):
                continue
            cands = [t for t in c["candidates"] if t in candidate_info]
            if not cands or any(t in seen for t in cands):
                continue
            q_stems = _retriever_stems(c["query_en"])

            def _recovery_key(t: str) -> tuple[int, float, int]:
                t_stems = _retriever_stems(t)
                overlap = len(q_stems & t_stems)
                ratio = (overlap / len(t_stems)) if t_stems else 0.0
                return (overlap, ratio, int(candidate_info[t].get("count") or 0))

            top = max(cands, key=_recovery_key)
            if _recovery_key(top)[0] <= 0:
                continue  # 쿼리와 스템 한 개도 안 겹치는 후보뿐 → 강제 주입하지 않는다
            if not _tag_allowed(top.lower().replace("_", " "), max_rating):
                continue
            seen.add(top)
            selected.append(candidate_info[top])

        _protected = {it["tag"] for it in forced_subjects} | {it["tag"] for it in forced_relations}

        # 2인 관계 태그 가드(결정론·전단): 확정 인원이 정확히 1명인데 본질적 2인 태그
        # (heads together/holding hands류)가 선택에 끼면 — 오염된 후보 enum에서의
        # 오선택(실측) — 모순이므로 제거한다. 요청이 직접 언급한 경우(request_tokens
        # 겹침, 예: "pov holding hands")는 면제. boost 시드가 되기 *전에* 잘라 연쇄
        # (heads together → e621이 foreheads touching)를 차단하고, seen에는 남겨
        # 후속 단계(boost/event/enhance) 재유입도 막는다. 강제 진실태그는 보호.
        _girls_n, _boys_n = _count_girls_boys(
            {str(i.get("tag") or "").lower().replace("_", " ") for i in selected})
        _single_person_scene = (_girls_n + _boys_n) == 1

        def _two_person_ok(tag: str) -> bool:
            if not _single_person_scene or tag in _protected:
                return True
            norm = str(tag).lower().replace("_", " ").strip()
            if not _is_two_person_tag(norm):
                return True
            # 요청이 직접 언급해야 면제 — 태그의 *모든* 스템이 긍정 언급에 있어야 한다
            # (P2: any-겹침이면 "holding cup, no holding hands"의 holding이 면제를 뚫는다).
            t_stems = _retriever_stems(norm)
            return bool(t_stems) and t_stems <= request_stems

        def _sex_anatomy_ok(tag: str) -> bool:
            # 확정 인원이 한 성별뿐인데 반대 성별 해부학이면 제거(실측: 1girl 자위에
            # penis/penile masturbation). futanari 등 요청 명시 시 면제. 강제 태그 보호.
            if _intersex_request or tag in _protected:
                return True
            return not _opposite_sex_anatomy(tag, girls=_girls_n, boys=_boys_n)

        selected = [it for it in selected if _two_person_ok(it["tag"]) and _sex_anatomy_ok(it["tag"])]

        # 변형 축약: 같은 개념의 부분집합 변형(kimono/kimono dress/kimono only)을 한
        # canonical로 합친다. 강제 인원/행위 태그는 보존. ⚠️ 기본 OFF: 격리측정서
        # recall -0.05(0.645→0.598, 원본의 구체변형까지 합침). 검색기 정밀화가 변형
        # 범람을 더 근본적으로 줄이므로 보류, 코드 보존.
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
            # 쿼리는 개념 구문 *그대로*만 쓴다 — 단어 분해 폴백("looking at cell phone"
            # →"looking")은 범용 동사가 시선/포즈 이벤트 패밀리에 substring 매칭돼 전역
            # 인기 포즈를 주입하는 퇴화를 실측으로 일으켰다(v/holding hands 사고; 상위
            # 4개를 스톱리스트로 스킵해도 다음 티어 looking ahead/at animal이 샘).
            # 이벤트 참조는 개념이 이벤트를 직접 명명할 때(fellatio/hug/kiss류 정형
            # 행위)만 의미가 있다 — 매칭 0건이면 보강 없이 넘어가는 게 옳다.
            # 결정론 핵심 행위 앵커를 공기 쿼리 *선두*에 합류(개념 추출을 우회한 forced
            # 행위가 인원수 파티션 공기를 못 받던 갭 — _act_anchor_terms docstring 참조).
            act_terms = _act_anchor_terms(selected, limit=3)
            query_terms: list[str] = list(act_terms)
            for c in queryable:
                term = c["query_en"].strip()
                if term and term not in query_terms:
                    query_terms.append(term)
            agg: dict[str, int] = {}
            # 행위 앵커는 개념 예산과 별도 전용 슬롯을 받는다(개념이 행위를 밀어내지 않게).
            n_terms = min(len(query_terms), len(act_terms) + max(2, event_top // 2))
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

        # 주입 게이트(LLM 1콜) — 코드가 만든 보강 제안(e621 부스트·이벤트 참조)을
        # 무조건 주입하지 않고, 모델이 장면 적합성을 승인한 것만 넣는다. enum이 제안
        # 목록뿐이라 최악(전부 거부)에도 잃는 건 보강분뿐 — recovery로 복원한 핵심
        # subject/clothing/background 앵커는 이미 selected의 core tag이며 게이트가
        # 제거하지 않는다. 거부된 태그는 seen에 남겨 enhance 재유입도 차단. 게이트
        # 자체가 실패하면(LLM 다운 등) 결정론 가드를 통과한 제안을 그대로 쓴다(best-effort).
        # finish(호출 3)보다 앞에 둬서 자연어/보완 생성이 오염된 tags_so_far를 보지 않게 한다.
        injection_rejected: list[str] = []
        if boost_top > 0 or event_top > 0:
            proposals: list[str] = []
            _p_seen: set[str] = set()
            for t in (
                [it["tag"] for it in boosted]
                + [it["tag"] for it in event_enrich]
            ):
                if t not in _p_seen:
                    _p_seen.add(t)
                    proposals.append(t)
            if proposals:
                step_no += 1
                self._stage(step_no, "주입 게이트")
                gate_user = json.dumps(
                    {
                        "request": request_text,
                        "core_tags": [
                            it["tag"].replace("_", " ") for it in selected
                        ],
                        "proposed_extras": proposals,
                    },
                    ensure_ascii=False,
                )
                try:
                    verdict = self._chat(
                        _GATE_INSTRUCTION + gate_user, _gate_schema(proposals),
                        model=target_model, temperature=0.0,
                    )
                    approved = {
                        str(t).strip() for t in (verdict.get("approved") or []) if str(t).strip()
                    }
                    rej = {t for t in proposals if t not in approved}
                    if rej:
                        injection_rejected = [t for t in proposals if t in rej]
                        boosted = [it for it in boosted if it["tag"] not in rej]
                        event_enrich = [it for it in event_enrich if it["tag"] not in rej]
                        event_added = [t for t in event_added if t not in rej]
                except Exception:
                    pass  # 게이트 실패 — 가드 통과 제안을 그대로 사용(파이프라인 불파괴)

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
                    ) + family_safe_contract_line(scene_anchors) + finish_user,
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
                # 의미 토큰이 아예 없는 태그("v" 같은 단문자/이모티콘)도 근거 불능 → 탈락
                # (기존엔 빈 토큰셋이 prune을 *우회*해 "v"가 통과하는 구멍이었다).
                _v_tokens = {w for w in norm.split() if len(w) >= 3 and w not in _STOPWORDS}
                if not _v_tokens or not (_v_tokens & _ground_tokens):
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

        # 2인 관계 태그 가드를 보강 단계 산출물에도 적용(벨트&서스펜더 — 게이트가
        # 실패하거나 통과시켜도 단일 인물 장면의 관계 태그는 결정론으로 막는다).
        boosted = [it for it in boosted if _ok_count(it) and _two_person_ok(it["tag"]) and _sex_anatomy_ok(it["tag"])]
        enhanced = [it for it in enhanced if _ok_count(it) and _two_person_ok(it["tag"]) and _sex_anatomy_ok(it["tag"])]
        event_enrich = [it for it in event_enrich if _ok_count(it) and _two_person_ok(it["tag"]) and _sex_anatomy_ok(it["tag"])]

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
            "injection_rejected": injection_rejected,
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
