from __future__ import annotations

import json
import re
from pathlib import Path
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
    "first",
    "high",
    "in",
    "into",
    "low",
    "of",
    "on",
    "open",
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

_GENERIC_RELATION_TOKENS = {
    "boy",
    "boys",
    "cosplay",
    "everyone",
    "female",
    "focus",
    "girl",
    "girls",
    "human",
    "humans",
    "male",
    "many",
    "multiple",
    "other",
    "others",
    "person",
    "solo",
    "too",
    "view",
    "views",
}

_BROAD_SIBLING_SUBGROUPS = {
    "accessories",
    "activity",
    "attire",
    "clothing_action",
    "effects",
    "etc",
    "gesture",
    "image_composition",
    "instruments",
    "metatags",
    "patterns",
    "pose",
    "posture",
    "sex_acts",
    "sexual_positions",
    "symbols",
    "text",
    "tools",
    "verbs_and_gerunds",
    "weapons",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")


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


# 존재 <-> 부재 쌍. `no shirt` 를 `shirt` 의 "비슷한 것" 으로 내놓으면, 사용자가 그 칩을
# 눌러 정반대 태그를 프롬프트에 넣는다(Codex 전수조사 2026-07-30: 명시적 반대쌍만 564간선).
#
# `_core_tokens` 로는 못 잡는다 — `without` 은 STOP_TOKENS 라 지워지고, 그러면
# `without X` 와 `X` 의 토큰이 **같아져서** 오히려 최고점을 받는다. 그래서 정규화된
# 원문에서 부정 표지를 보고, 표지를 뗀 나머지가 포함 관계인지로 판정한다.
_NEG_RE = re.compile(r"^(?:no|without|missing)\s+|\s+(?:gone|removed)$")


def _is_negation_pair(a: str, b: str) -> bool:
    """한쪽만 부정 표지를 갖고, 표지를 뗀 대상이 겹치면 반대쌍이다."""
    na, nb = bool(_NEG_RE.search(a)), bool(_NEG_RE.search(b))
    if na == nb:                      # 둘 다 부정 / 둘 다 긍정이면 반대쌍이 아니다
        return False
    ta = _relation_tokens(_NEG_RE.sub(" ", a))
    tb = _relation_tokens(_NEG_RE.sub(" ", b))
    if not ta or not tb:
        return False
    return ta <= tb or tb <= ta


def _relation_tokens(tag: str) -> set[str]:
    return {token for token in _TOKEN_RE.findall(normalize_tag(tag)) if token}


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


def _is_broad_sibling_area(group: str, subgroup: str) -> bool:
    subgroup_l = str(subgroup or "").lower()
    if subgroup_l in _BROAD_SIBLING_SUBGROUPS:
        return True
    group_l = str(group or "").lower()
    return "composition_meta" in group_l and subgroup_l in {"", "metatags", "symbols", "text"}


def _is_count_relation_area(group: str, subgroup: str) -> bool:
    return str(group or "").lower() == "composition_meta" and str(subgroup or "").lower() == "count"


@dataclass(frozen=True)
class RankedRelation:
    tag: str
    score: float
    source: str


# 배타 태그쌍 — `tools/build_exclusive_pairs.py` 가 실제 게시물 동반 lift 로 만든다.
# `muscular` 의 "비슷한 것" 에 `loli` 가 나오던 것을 여기서 끊는다(사용자 실측 2026-07-30).
# 사전은 체형 축 태그들을 서로 `siblings` 로 묶어 놓았고 랭커는 "같은 subgroup" 을 유사도
# 근거로 쓰므로, 규칙만으로는 '갈아 끼우는 대안'과 '전혀 안 붙는 쌍'을 구별할 수 없다.
#
# 파일이 없으면 빈 집합이다 — 게이트가 없어도 나머지는 그대로 동작한다(기능 저하만).
_EXCLUSIVE_PATH_CANDIDATES = (
    Path(__file__).resolve().parent.parent / "data" / "tag_exclusive_pairs.json",
)
_exclusive_pairs: frozenset[tuple[str, str]] | None = None


def _load_exclusive_pairs() -> frozenset[tuple[str, str]]:
    global _exclusive_pairs
    if _exclusive_pairs is not None:
        return _exclusive_pairs
    pairs: set[tuple[str, str]] = set()
    for path in _EXCLUSIVE_PATH_CANDIDATES:
        try:
            if not path.exists():
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            for row in payload.get("pairs") or []:
                a, _, b = str(row).partition("	")
                if a and b:
                    pairs.add((a, b) if a < b else (b, a))
            break
        except Exception:
            continue
    _exclusive_pairs = frozenset(pairs)
    return _exclusive_pairs


def is_exclusive_pair(a: str, b: str) -> bool:
    key = (a, b) if a < b else (b, a)
    return key in _load_exclusive_pairs()


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

    # "비슷한 것" 은 `siblings` 와 `word_match` 만이다. `children` 은 **더 구체적인 것**
    # 이라 성격이 다르다(core/interactive_tag_dependency.py 가 그렇게 정의한다).
    # 전에는 셋을 한 통에 넣고 `children` 에 최고점(320 > siblings 190)을 줬다. 그 결과
    # children 이 있는 태그의 99.94%에서 첫 칩이 children 이고, 47%는 상위 8칸을 children
    # 이 채워 siblings 를 밀어냈다(Codex 전수조사 2026-07-30). 목록을 갈라서 낸다.
    SIMILAR_SOURCES = ("siblings", "word_match")
    SPECIFIC_SOURCES = ("children",)

    def rank_related(
        self,
        tag: str,
        info: Mapping[str, Any],
        *,
        limit: int = 8,
    ) -> list[str]:
        return [item.tag for item in self.rank(tag, info, limit=limit)]

    def rank_specific(
        self,
        tag: str,
        info: Mapping[str, Any],
        *,
        limit: int = 8,
    ) -> list[str]:
        """'더 구체적인 것'(children). '비슷한 것' 과 섞지 않는다."""
        return [item.tag for item in
                self.rank(tag, info, limit=limit, sources=self.SPECIFIC_SOURCES)]

    def rank(
        self,
        tag: str,
        info: Mapping[str, Any],
        *,
        limit: int = 8,
        sources: tuple[str, ...] | None = None,
    ) -> list[RankedRelation]:
        normalized = normalize_tag(tag)
        relations = info.get("relations", {}) or {}
        parents = set(self.valid_implications(normalized, info))
        source_group = str(info.get("group", "") or "")
        source_subgroup = str(info.get("subgroup", "") or "")
        source_axis = _axis_from_info(normalized, info, self._registry)
        source_tokens = _core_tokens(normalized)

        wanted = tuple(sources) if sources is not None else self.SIMILAR_SOURCES
        # 두 목록은 겹치지 않아야 한다. `muscular male` 은 siblings 와 children 양쪽에
        # 있어서 '비슷한 것'과 '더 구체적인 것'에 같이 나왔다(실측). 하위 태그는
        # 구체 목록 소관이므로 유사 목록에서 뺀다.
        own_children = {normalize_tag(t) for t in _as_list(relations.get("children"))}
        drop_children = "children" not in wanted
        candidates: list[tuple[str, str]] = []
        for key in ("children", "siblings", "word_match"):
            if key in wanted:
                candidates.extend((key, t) for t in _as_list(relations.get(key)))

        ranked: dict[str, RankedRelation] = {}
        for source, raw_candidate in candidates:
            candidate = normalize_tag(raw_candidate)
            if not candidate or candidate == normalized or candidate in parents:
                continue
            # 존재 <-> 부재는 유사도 방향이 정반대다. 어느 소스로 왔든 막는다.
            if _is_negation_pair(normalized, candidate):
                continue
            # 실제 게시물에서 거의 함께 쓰이지 않는 쌍은 "비슷한 것" 이 아니다.
            # `children`(더 구체적인 것)에는 적용하지 않는다 — 하위 태그는 상위와
            # 동반 확률이 낮은 것이 정상이다(`sweater` 와 `naked sweater`).
            if source != "children" and is_exclusive_pair(normalized, candidate):
                continue
            if drop_children and candidate in own_children:
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

    def valid_implications(
        self,
        tag: str,
        info: Mapping[str, Any],
        *,
        limit: int = 8,
    ) -> list[str]:
        normalized = normalize_tag(tag)
        relations = info.get("relations", {}) or {}
        valid: list[str] = []
        seen: set[str] = set()
        for raw_parent in _as_list(relations.get("parent")):
            parent = normalize_tag(raw_parent)
            if parent in seen:
                continue
            if self._is_valid_parent(normalized, parent):
                seen.add(parent)
                valid.append(parent)
            if len(valid) >= limit:
                break
        return valid

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

        if source == "word_match" and not overlap:
            return 0.0
        if source == "word_match" and self._has_only_generic_overlap(overlap):
            return 0.0
        if (
            source == "word_match"
            and not same_subgroup
            and len(overlap) < 2
            and _is_broad_sibling_area(source_group, source_subgroup)
        ):
            return 0.0
        if source == "children" and not (same_group or same_axis):
            return 0.0
        if source == "children" and not (overlap or same_axis):
            return 0.0
        if source == "siblings" and (
            _is_count_relation_area(source_group, source_subgroup)
            or _is_count_relation_area(candidate_group, candidate_subgroup)
        ):
            return 0.0
        if (
            source == "siblings"
            and not overlap
            and _is_broad_sibling_area(source_group, source_subgroup)
        ):
            return 0.0
        if (
            source == "siblings"
            and _is_broad_sibling_area(source_group, source_subgroup)
            and self._has_only_generic_overlap(overlap)
        ):
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

        if source == "word_match" and score < 100:
            return 0.0

        return score

    def _has_only_generic_overlap(self, overlap: set[str]) -> bool:
        if not overlap:
            return False
        if any(len(token) <= 1 for token in overlap):
            return True
        return overlap <= _GENERIC_RELATION_TOKENS

    def _is_valid_parent(self, child: str, parent: str) -> bool:
        if not parent or parent == child:
            return False
        if parent not in self._records:
            return False
        if len(parent) == 1 and parent.isalpha():
            return False

        parent_tokens = _relation_tokens(parent)
        child_tokens = _relation_tokens(child)
        if not parent_tokens:
            return parent in child

        return parent_tokens.issubset(child_tokens)


def build_ranked_related_tags(
    tag: str,
    info: Mapping[str, Any],
    tag_records: Mapping[str, Mapping[str, Any]],
    *,
    limit: int = 8,
) -> list[str]:
    return TagRelationRanker(tag_records).rank_related(tag, info, limit=limit)
