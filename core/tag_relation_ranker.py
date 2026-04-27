from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from core.tag_axis_registry import TagAxisRegistry, normalize_tag


_STOP_TOKENS = {
    "a",
    "an",
    "and",
    "at",
    "by",
    "for",
    "from",
    "in",
    "into",
    "of",
    "on",
    "or",
    "over",
    "the",
    "to",
    "under",
    "with",
    "without",
}

_COLOR_TOKENS = {
    "aqua",
    "black",
    "blonde",
    "blue",
    "brown",
    "dark",
    "gold",
    "green",
    "grey",
    "gray",
    "light",
    "orange",
    "pink",
    "purple",
    "red",
    "silver",
    "white",
    "yellow",
}


def _as_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return []


def _core_tokens(tag: str) -> set[str]:
    return {
        token
        for token in normalize_tag(tag).split()
        if token and token not in _STOP_TOKENS and token not in _COLOR_TOKENS
    }


def _axis_from_info(tag: str, info: Mapping[str, Any] | None, registry: TagAxisRegistry) -> str:
    axis = registry.axis_for(tag)
    if axis != "uncategorized":
        return axis
    if not info:
        return axis

    group = str(info.get("group", "") or "").lower()
    subgroup = str(info.get("subgroup", "") or "").lower()
    text = f"{group} {subgroup}"
    if "clothing" in text or "의상" in text:
        return "clothing"
    if "expression" in text or "face" in text or "eyes" in text or "표정" in text:
        return "expression"
    if "action" in text or "pose" in text or "자세" in text or "행동" in text:
        return "pose_action"
    if "location" in text or "background" in text or "장소" in text:
        return "location"
    if "object" in text or "물체" in text:
        return "object"
    if "meta" in text or "composition" in text:
        return "meta"
    if "nsfw" in text or "sexual" in text:
        return "sexual_or_nsfw"
    if "body" in text or "characteristic" in text or "특징" in text:
        return "characteristic"
    return axis


@dataclass(frozen=True)
class RankedRelation:
    tag: str
    score: float
    source: str


class TagRelationRanker:
    """Rank tag relations for prompt tooltip insertion.

    The input relation graph contains useful structural links (`children`,
    `siblings`) and noisy lexical links (`word_match`). This ranker keeps lexical
    matches only when they share the same semantic area or a meaningful noun
    token with the source tag.
    """

    def __init__(self, tag_records: Mapping[str, Mapping[str, Any]]):
        self._records = tag_records
        self._registry = TagAxisRegistry()

    def rank_related(
        self,
        tag: str,
        info: Mapping[str, Any],
        *,
        limit: int = 8,
    ) -> list[str]:
        return [item.tag for item in self.rank(tag, info, limit=limit)]

    def rank(
        self,
        tag: str,
        info: Mapping[str, Any],
        *,
        limit: int = 8,
    ) -> list[RankedRelation]:
        normalized = normalize_tag(tag)
        relations = info.get("relations", {}) or {}
        parents = set(normalize_tag(t) for t in _as_list(relations.get("parent")))
        source_group = str(info.get("group", "") or "")
        source_subgroup = str(info.get("subgroup", "") or "")
        source_axis = _axis_from_info(normalized, info, self._registry)
        source_tokens = _core_tokens(normalized)

        candidates: list[tuple[str, str]] = []
        candidates.extend(("children", t) for t in _as_list(relations.get("children")))
        candidates.extend(("siblings", t) for t in _as_list(relations.get("siblings")))
        candidates.extend(("word_match", t) for t in _as_list(relations.get("word_match")))

        ranked: dict[str, RankedRelation] = {}
        for source, raw_candidate in candidates:
            candidate = normalize_tag(raw_candidate)
            if not candidate or candidate == normalized or candidate in parents:
                continue

            candidate_info = self._records.get(candidate, {})
            score = self._score_candidate(
                candidate,
                candidate_info,
                source=source,
                source_group=source_group,
                source_subgroup=source_subgroup,
                source_axis=source_axis,
                source_tokens=source_tokens,
            )
            if score <= 0:
                continue

            previous = ranked.get(candidate)
            if previous is None or score > previous.score:
                ranked[candidate] = RankedRelation(candidate, score, source)

        results = list(ranked.values())
        results.sort(
            key=lambda item: (
                -item.score,
                -int((self._records.get(item.tag, {}) or {}).get("freq", 0) or 0),
                item.tag,
            )
        )
        return results[:limit]

    def _score_candidate(
        self,
        candidate: str,
        candidate_info: Mapping[str, Any],
        *,
        source: str,
        source_group: str,
        source_subgroup: str,
        source_axis: str,
        source_tokens: set[str],
    ) -> float:
        candidate_group = str(candidate_info.get("group", "") or "")
        candidate_subgroup = str(candidate_info.get("subgroup", "") or "")
        candidate_axis = _axis_from_info(candidate, candidate_info, self._registry)
        candidate_tokens = _core_tokens(candidate)
        overlap = source_tokens & candidate_tokens
        same_group = bool(source_group and candidate_group and source_group == candidate_group)
        same_subgroup = bool(
            same_group and source_subgroup and candidate_subgroup and source_subgroup == candidate_subgroup
        )
        same_axis = bool(source_axis != "uncategorized" and source_axis == candidate_axis)

        if source == "word_match" and not (overlap or same_subgroup):
            return 0.0

        score = {
            "children": 320.0,
            "siblings": 190.0,
            "word_match": 40.0,
        }.get(source, 0.0)

        if same_subgroup:
            score += 150
        elif same_group:
            score += 75
        if same_axis:
            score += 35
        if overlap:
            score += 70 * len(overlap)
            if len(overlap) >= 2:
                score += 30

        # Lexical-only cross-axis candidates are the common tooltip noise source.
        if source == "word_match" and not same_axis and len(overlap) < 2:
            score -= 80

        return score


def build_ranked_related_tags(
    tag: str,
    info: Mapping[str, Any],
    tag_records: Mapping[str, Mapping[str, Any]],
    *,
    limit: int = 8,
) -> list[str]:
    return TagRelationRanker(tag_records).rank_related(tag, info, limit=limit)
