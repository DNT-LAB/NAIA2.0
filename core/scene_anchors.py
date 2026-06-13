# -*- coding: utf-8 -*-
"""Scene intent anchors — 입력의 **관계**를 결정론적으로 추출해 tag-assist가 의도를
보존하도록 돕는 순수 모듈.

배경(2026-06-13): "남성이 어린 딸을 들어올리는" 부녀 장면이 번역+`_SUBJECT_SYNONYMS`
압축(woman/young female→1girl, man→1boy)으로 관계가 증발하고, 살아남은 검색 조각
(grabbed/armpits)만 살아남아 가족 의도가 사라졌다. 이 모듈은 원문/번역을 비교해 관계
anchor를 회수하고, tag-assist가 관계 태그(father and daughter 등)를 출력에 보존하게 한다.

설계 원칙:
- **결정론·fail-closed**: 큐레이션 lexicon이 원문/번역에 *literal* 로 존재할 때만 anchor가
  뜬다. lexicon 미적중 → 빈 packet → 파이프라인 무변경(관계 환각 0). LLM 호출 0.
- **양방향 회수**: 원문(한국어) OR 번역(영어) 어느 쪽에 있어도 추출 — 관계가 번역서 증발해도
  원문에서 회수하는 것이 이 버그의 핵심.
- lexicon은 `interactive.json`의 `subgroup: relationships`(KR_tags.parquet `관계>가족`/
  `인물>관계` + `keywords_kr`)를 mirror한다. **트랩 제외**: `모자`(=hat, mother-son 아님),
  `부자`(=rich)는 동음이의라 쓰지 않고 명시 조합(아빠+딸 등)으로만 판정한다.

가족-안전 contract는 **soft steer**(자연어 묘사 톤 안내)일 뿐, 콘텐츠를 강제로 prune하지
않는다 — 강한 제약은 두지 않는다(사용자 방침: 개인이 프롬프트를 직접 수정 가능).

stdlib만 의존(순수). service의 private helper를 import하지 않는다.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

__all__ = ["extract_scene_anchors", "family_safe_contract_line"]


# 표면 어휘 — 영어는 단어경계(\b), 한국어는 부분일치. 동음이의 한국어(모자/부자) 제외.
_DAUGHTER = (r"daughters?", "딸")
_SON = (r"sons?", "아들")
_FATHER = (r"fathers?", r"dad(?:dy|dies)?", r"papas?", "아빠", "아버지")
_MOTHER = (r"mothers?", r"mom(?:my|mies)?", r"mamas?", "엄마", "어머니")
_FAMILY = ("가족", r"famil(?:y|ies)")
_SIBLINGS = ("남매", "형제", "자매", r"siblings?", r"sisters?", r"brothers?")
# 영어 bare "couple"은 "a couple of girls"(=두 명) 오탐이 잦아 제외 — 명시 결혼/연인만.
_COUPLE_EXPLICIT = ("부부", "연인", r"married couple", r"husband and wife", r"wife and husband")
_MALE_GENERIC = (r"man", r"men", r"male", r"boys?", "남성", "남자", "소년", "아저씨")
_FEMALE_GENERIC = (r"woman", r"women", r"female", r"girls?", "여성", "여자", "소녀", "아주머니", "아줌마")
_BUNYEO = ("부녀",)   # father & daughter
_MONYEO = ("모녀",)   # mother & daughter


def _has_hangul(s: str) -> bool:
    return any("가" <= ch <= "힣" for ch in s)


def _matcher(term: str) -> Any:
    if _has_hangul(term):
        return ("ko", term)
    return ("en", re.compile(r"\b(?:" + term + r")\b"))


def _present(matchers: Iterable[Any], hay_lower: str) -> bool:
    for kind, m in matchers:
        if kind == "ko":
            if m in hay_lower:
                return True
        elif m.search(hay_lower):
            return True
    return False


def _compile(group: tuple[str, ...]) -> tuple[Any, ...]:
    return tuple(_matcher(t) for t in group)


_M_DAUGHTER = _compile(_DAUGHTER)
_M_SON = _compile(_SON)
_M_FATHER = _compile(_FATHER)
_M_MOTHER = _compile(_MOTHER)
_M_FAMILY = _compile(_FAMILY)
_M_SIBLINGS = _compile(_SIBLINGS)
_M_COUPLE = _compile(_COUPLE_EXPLICIT)
_M_MALE = _compile(_MALE_GENERIC)
_M_FEMALE = _compile(_FEMALE_GENERIC)
_M_BUNYEO = _compile(_BUNYEO)
_M_MONYEO = _compile(_MONYEO)

# 부정 게이트 — 영어 대표어가 negated_words에 있으면 그 역할을 무효화("not his daughter").
_ROLE_NEG_REPS = {
    "daughter": ("daughter",), "son": ("son",),
    "father": ("father", "dad"), "mother": ("mother", "mom"),
    "family": ("family",), "siblings": ("sibling", "siblings", "sister", "brother"),
    "couple": ("couple", "married", "husband", "wife"),
}


def _negated(role: str, negated_words: frozenset[str]) -> bool:
    return bool(negated_words) and any(rep in negated_words for rep in _ROLE_NEG_REPS.get(role, ()))


def extract_scene_anchors(
    original_text: str,
    request_text: str,
    *,
    negated_words: Iterable[str] = (),
) -> dict[str, Any]:
    """원문+번역에서 관계 anchor를 결정론적으로 추출.

    반환(anchor 있을 때)::

        {"relationships": ["father and daughter", "parent and child"],  # most-specific first
         "kind": "parent_child"|"family"|"siblings"|"couple"}

    anchor 없음 → ``{}`` (호출부 완전 no-op). ``relationships``는 forced 태그 후보로,
    인덱스+등급 검증을 통과하는 첫 1개만 강제된다.
    """
    neg = frozenset(str(w).strip().lower() for w in (negated_words or ()) if str(w).strip())
    hay = f" {str(original_text or '').lower()} {str(request_text or '').lower()} "

    def has(matchers, role):
        return not _negated(role, neg) and _present(matchers, hay)

    has_daughter = has(_M_DAUGHTER, "daughter")
    has_son = has(_M_SON, "son")
    has_father = has(_M_FATHER, "father") or (_present(_M_BUNYEO, hay) and not _negated("daughter", neg))
    has_mother = has(_M_MOTHER, "mother") or (_present(_M_MONYEO, hay) and not _negated("daughter", neg))
    bunyeo = _present(_M_BUNYEO, hay) and not _negated("daughter", neg)
    monyeo = _present(_M_MONYEO, hay) and not _negated("daughter", neg)
    has_family = has(_M_FAMILY, "family")
    has_siblings = has(_M_SIBLINGS, "siblings")
    has_couple = has(_M_COUPLE, "couple")
    male = _present(_M_MALE, hay)
    female = _present(_M_FEMALE, hay)

    relationships: list[str] = []
    kind: str | None = None

    # parent-child (최우선). 핵심: "man + (his) daughter" → 부모는 남성 → father and daughter.
    if has_daughter:
        if bunyeo or has_father or (male and not has_mother):
            relationships.append("father and daughter")
        elif monyeo or has_mother or (female and not male):
            relationships.append("mother and daughter")
        kind = "parent_child"
    if has_son:
        if has_father or (male and not has_mother):
            relationships.append("father and son")
        elif has_mother or (female and not male):
            relationships.append("mother and son")
        kind = "parent_child"
    if (has_daughter or has_son) and "parent and child" not in relationships:
        relationships.append("parent and child")

    if kind is None and has_family:
        relationships.append("family")
        kind = "family"
    elif has_family and "family" not in relationships:
        relationships.append("family")

    if kind is None and has_siblings:
        relationships.append("siblings")
        kind = "siblings"

    if kind is None and has_couple:
        relationships.extend(["married couple", "couple"])
        kind = "couple"

    if kind is None:
        return {}

    seen: set[str] = set()
    relationships = [r for r in relationships if not (r in seen or seen.add(r))]
    return {"relationships": relationships, "kind": kind}


def family_safe_contract_line(anchors: dict[str, Any]) -> str:
    """FINISH 단계용 **soft** 톤 안내 한 줄. 가족/부모자식/형제 anchor일 때만 비-빈 문자열.
    콘텐츠를 강제로 제거하지 않고 모델에게 가족-적절한 framing을 권한다(강한 제약 아님)."""
    if not anchors or anchors.get("kind") not in ("parent_child", "family", "siblings"):
        return ""
    rel = (anchors.get("relationships") or ["family"])[0]
    return (
        f"\nNote: the request describes a {rel} scene — keep the description "
        "wholesome and family-appropriate, framing any physical contact as "
        "caring/protective rather than sensual.\n"
    )
