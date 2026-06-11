"""어시스트 전용 후보 관련성 스코어링/게이팅.

문제(Codex 진단): 어시스트가 쓰는 검색은 자동완성(autocomplete) 인덱스라 UI 타이핑
보조용 prefix/substring 매칭이다. NLP 개념→태그엔 부적합해 cross-category 노이즈를
낸다 — "short hair"→shortcake(음식), "mint"(색)→mint chocolate(음식),
"back view"→backpack, "connected"→connected beard.

이 모듈은 raw 검색 결과 위에 **whole-word(경량 스테밍) 관련성 + 카테고리 게이트**를
얹는다. count 우선이 아니라 *증거 우선*(exact ≫ whole-word ≫ prefix-only). 결정론적·
테스트 가능(Ollama 무의존). 자동완성 인덱스는 그대로 두고(UI 계약 보존), 어시스트만
이 레이어를 통과시킨다.

설계 결정(Codex 자문 반영):
- 카테고리는 **denylist**(음식/고유명만 거름) — 인덱스 ~80%가 빈 카테고리라
  allowlist는 과도 필터(recall 회귀)를 부른다. 빈 카테고리는 통과시킨다.
- whole-word는 prefix-only 노이즈(shortcake)만 거르고 스테밍으로 smile↔smiling 보존.
- e621 의미확장 태그는 이 게이트 면제(의도적으로 다른 단어 — 별도 검증됨).
"""
from __future__ import annotations

import math
import re
from typing import Any, Callable

# danbooru 한국어 카테고리(KR_tags). 음식 마커 하나로 shortcake(사물/음식)·
# mint chocolate(음식>맛) 둘 다 잡힌다. 무기/도구/가방 등 일반 사물은 정상 유지.
_FOOD_MARKER = "음식"
# 음식 게이트를 적용할 개념 종류 — 음식이 명백히 무관한 시각 개념.
# action/background/other는 제외(드물게 음식 장면이 있을 수 있어 과필터 방지).
_FOOD_GATED_KINDS = frozenset({"subject", "clothing", "expression"})

# 고유명 카테고리(캐릭터/저작권/작가/작품/시리즈) — 사용자가 고유명을 직접 말하지
# 않는 한 잡음. 기존 _PROPER_NOUN_CATEGORY_PREFIXES와 동일 의도(여기선 한국어 카테고리).
_PROPER_NOUN_MARKERS = ("작가", "캐릭터", "저작권", "작품", "시리즈", "창작자", "아티스트", "미디어")

_SPLIT_RE = re.compile(r"[\s_]+")


def _stem(w: str) -> str:
    """경량 스테밍: ing/ed/es/s/e 접미 제거. smile↔smiling, walk↔walking 보존하되
    shortcake↛short, backpack↛back(복합어는 어간이 안 맞아 안 합쳐짐)."""
    w = w.lower()
    for suf in ("ing", "ed", "es"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)]
    if len(w) > 3 and w.endswith("s"):
        return w[:-1]
    if len(w) > 3 and w.endswith("e"):
        return w[:-1]
    return w


def stems(text: str) -> set[str]:
    """텍스트의 의미 토큰(len≥3) 스템 집합."""
    return {_stem(w) for w in _SPLIT_RE.split(str(text).lower()) if len(w) >= 3}


def score_candidate(
    tag: str, count: int, category: str, query_stems: set[str], *, kind: str,
) -> tuple[float, str]:
    """후보의 (score, reject_reason). reject_reason='' 이면 채택.
    query_stems = 개념의 모든 검색어(원문+시노님+분해어) 스템 합집합."""
    tag_norm = str(tag).lower().replace("_", " ")
    cand_stems = stems(tag_norm)
    if not cand_stems:
        return (0.0, "empty")
    cat = str(category or "")
    # 카테고리 게이트(denylist, hard reject — recall 위험 없음):
    # ① 음식: 시각 개념엔 무관(shortcake=사물/음식, mint chocolate=음식>맛). mint
    #    chocolate은 "mint"를 공유해 whole-word론 못 잡지만 음식이라 여기서 탈락.
    if kind in _FOOD_GATED_KINDS and _FOOD_MARKER in cat:
        return (0.0, "food-category")
    # ② 고유명 카테고리(캐릭터/저작권/작가): 사용자가 고유명 직접 안 말한 일반 검색의 잡음.
    if any(m in cat for m in _PROPER_NOUN_MARKERS):
        return (0.0, "proper-noun-category")
    # ⚠️ 스코어는 count 지배(기존 동작 보존) + exact/overlap 작은 타이브레이크만.
    #    whole-word 데모션은 폐기 — 측정상 정당한 복합어(windowsill↛window)를 하단으로
    #    밀어 recall이 회귀했다(collapse·verify와 동일 패턴: 정밀도 필터가 recall을 깎음).
    #    카테고리 hard-reject(음식/고유명)만 남긴다 — 이건 원본 general에 거의 안 나와
    #    recall 중립이면서 shortcake/mint chocolate를 원천 제거한다.
    exact = cand_stems == query_stems
    overlap_n = len(cand_stems & query_stems)
    rank = math.log10(int(count or 0) + 1) * 10.0
    if exact:
        rank += 50.0
    elif overlap_n >= 2:
        # 다단어 교집합 승격(P1): 쿼리 스템 2개 이상 공유 = 개념의 직접 표현일 공산
        # ("looking at cell phone"→looking at phone). count 지배 랭킹이 고빈도
        # 단일겹침(looking at viewer 3.7M)에 묻어버리던 정답을 enum 상단으로 끌어올린다.
        rank += 40.0
    elif overlap_n:
        rank += 10.0
    return (rank, "")


def filter_concept_candidates(
    rows: list[dict[str, Any]],
    query_stems: set[str],
    *,
    kind: str,
    tag_allowed: Callable[[str], bool] | None = None,
    limit: int = 12,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """한 개념의 raw 검색 rows를 스코어/게이트. (kept_sorted, rejected) 반환.
    kept는 score 내림차순. rejected는 reason 포함(감사/디버그용)."""
    scored: list[tuple[float, dict[str, Any]]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        tag = str(row.get("tag") or "").strip()
        if not tag:
            continue
        tl = tag.lower().replace("_", " ")
        if tl in seen:
            continue
        seen.add(tl)
        if "(" in tag and ")" in tag:
            rejected.append({**row, "reject_reason": "parenthetical"})
            continue
        if tag_allowed is not None and not tag_allowed(tl):
            rejected.append({**row, "reject_reason": "rating"})
            continue
        score, reason = score_candidate(
            tag, int(row.get("count") or 0),
            str(row.get("group") or row.get("category") or row.get("cat") or ""),
            query_stems, kind=kind,
        )
        if reason:
            rejected.append({**row, "reject_reason": reason})
            continue
        scored.append((score, row))
    scored.sort(key=lambda sr: sr[0], reverse=True)
    return [r for _, r in scored[:limit]], rejected


__all__ = ["stems", "score_candidate", "filter_concept_candidates"]
