from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from core.kr_phrase_canonicalizer import normalize_kr_phrase


_PARTICLE_SUFFIXES = (
    "으로부터",
    "에서",
    "에게",
    "까지",
    "부터",
    "으로",
    "처럼",
    "보다",
    "에게",
    "한테",
    "로",
    "을",
    "를",
    "이",
    "가",
    "은",
    "는",
    "와",
    "과",
    "만",
    "도",
    "의",
    "에",
)
_WEAK_SENTENCE_TOKENS = {
    "있음",
    "있는",
    "있다",
    "보임",
    "보이는",
    "보여",
    "보임",
    "장면",
    "모습",
    "상태",
    "느낌",
    "차림",
    "강조됨",
    "강조된",
    "강조",
    "착용",
    "착용함",
    "입음",
    "입고",
    "나옴",
    "등장",
    "살짝",
}
_ATTRIBUTE_REWRITES = {
    "큼": "큰",
    "크다": "큰",
    "커짐": "큰",
    "작음": "작은",
    "작다": "작은",
    "길다": "긴",
    "김": "긴",
    "짧다": "짧은",
    "짧음": "짧은",
    "감김": "감은",
    "감음": "감은",
    "감고": "감은",
    "닫힘": "감은",
    "벌림": "벌린",
    "벌어짐": "벌린",
    "열림": "열린",
    "발기함": "발기한",
    "발기됨": "발기한",
}
_ATTRIBUTIVE_ATTRIBUTES = {
    "큰",
    "작은",
    "긴",
    "짧은",
    "감은",
    "벌린",
    "열린",
    "발기한",
}
_FEMALE_SUBJECT_TOKENS = {"여성", "여자", "소녀", "여캐"}
_MALE_SUBJECT_TOKENS = {"남성", "남자", "소년", "남캐"}
_FEMALE_PLURAL_SUBJECT_TOKENS = {"여성들", "여자들", "소녀들"}
_MALE_PLURAL_SUBJECT_TOKENS = {"남성들", "남자들", "소년들"}


@dataclass(frozen=True)
class KrReconstructedQuery:
    query: str
    form: str
    confidence: float


def _strip_particle(token: str) -> str:
    if token in _ATTRIBUTIVE_ATTRIBUTES:
        return token
    for suffix in _PARTICLE_SUFFIXES:
        if token.endswith(suffix) and len(token) > len(suffix):
            return token[: -len(suffix)]
    return token


def _add_variant(
    variants: list[KrReconstructedQuery],
    seen: set[str],
    query: Any,
    *,
    form: str,
    confidence: float,
) -> None:
    normalized = normalize_kr_phrase(query)
    if not normalized or normalized in seen:
        return
    seen.add(normalized)
    variants.append(KrReconstructedQuery(normalized, form, confidence))


def _content_tokens(text: str) -> list[str]:
    tokens = []
    for token in text.split():
        stripped = _strip_particle(token)
        if not stripped or stripped in _WEAK_SENTENCE_TOKENS:
            continue
        tokens.append(stripped)
    return tokens


def reconstruct_kr_tag_queries(
    query: str,
    *,
    limit: int = 8,
) -> list[KrReconstructedQuery]:
    """Return Korean autocomplete search phrases derived from a natural sentence.

    The original query is always kept first. Later variants are shorter or
    attribute-reordered forms that canonical tag rules can match more reliably.
    This does not translate or remove the existing shortening/fallback path.
    """

    original = normalize_kr_phrase(query)
    if not original:
        return []

    variants: list[KrReconstructedQuery] = []
    seen: set[str] = set()
    _add_variant(variants, seen, original, form="original", confidence=1.0)

    compact = re.sub(r"\s+", "", original)
    for pattern, replacement in (
        (r"(.+?)(?:이|가)?큼$", r"큰 \1"),
        (r"(.+?)(?:이|가)?크다$", r"큰 \1"),
        (r"(.+?)(?:이|가)?작음$", r"작은 \1"),
        (r"(.+?)(?:이|가)?작다$", r"작은 \1"),
        (r"(.+?)(?:이|가)?감김$", r"감은 \1"),
        (r"(.+?)(?:이|가)?감음$", r"감은 \1"),
        (r"(.+?)(?:이|가)?발기함$", r"발기한 \1"),
        (r"(.+?)(?:이|가)?발기됨$", r"발기한 \1"),
    ):
        rewritten = re.sub(pattern, replacement, compact)
        if rewritten != compact:
            _add_variant(variants, seen, rewritten, form="attribute_rewrite", confidence=0.94)

    tokens = _content_tokens(original)
    if tokens:
        _add_variant(
            variants,
            seen,
            " ".join(tokens),
            form="content_phrase",
            confidence=0.90,
        )

    for left, right in zip(tokens, tokens[1:]):
        if right in _ATTRIBUTIVE_ATTRIBUTES:
            _add_variant(
                variants,
                seen,
                f"{right} {left}",
                form="attributive_clause",
                confidence=0.94,
            )
        attribute = _ATTRIBUTE_REWRITES.get(right)
        if attribute:
            _add_variant(
                variants,
                seen,
                f"{attribute} {left}",
                form="attribute_rewrite",
                confidence=0.94,
            )
        if right.endswith("한") or right.endswith("은"):
            continue
        if left in {"눈", "입", "성기", "가슴", "머리"}:
            attribute = _ATTRIBUTE_REWRITES.get(right)
            if attribute:
                _add_variant(
                    variants,
                    seen,
                    f"{attribute} {left}",
                    form="body_attribute",
                    confidence=0.94,
                )

    if len(tokens) >= 3:
        _add_variant(
            variants,
            seen,
            " ".join(tokens[:3]),
            form="head_phrase",
            confidence=0.86,
        )

    if tokens:
        subject = tokens[-1]
        if subject in _FEMALE_SUBJECT_TOKENS:
            _add_variant(
                variants,
                seen,
                "여자 한 명",
                form="subject_default",
                confidence=0.86,
            )
        elif subject in _MALE_SUBJECT_TOKENS:
            _add_variant(
                variants,
                seen,
                "남자 한 명",
                form="subject_default",
                confidence=0.86,
            )
        elif subject in _FEMALE_PLURAL_SUBJECT_TOKENS:
            _add_variant(
                variants,
                seen,
                "여러 명의 여자",
                form="subject_default",
                confidence=0.86,
            )
        elif subject in _MALE_PLURAL_SUBJECT_TOKENS:
            _add_variant(
                variants,
                seen,
                "여러 명의 남자",
                form="subject_default",
                confidence=0.86,
            )

    return variants[:limit]
