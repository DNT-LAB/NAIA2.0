"""Conditional Prompt Editor v2.1 — Block 데이터 모델.

블록 UI가 편집하고 DSL 직렬화기가 소비하는 순수 Python dataclass.
Qt/pandas 등 외부 의존성 없음 (SDLC R-01 / R-05 준수).

HANDOFF: docs/HANDOFF_CONDITIONAL_PROMPT_V2_2026_04_21.md
SRS:     docs/CONDITIONAL_PROMPT_EDITOR_PHASE1_SRS.md §5.3
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import List, Literal, Optional


# ============================================================================
# 타입 별칭
# ============================================================================

TagModifier = Literal["contains", "exact", "not_contains", "not_exact"]
RatingSource = Literal["auto", "row", "override", "bayes"]
LogicalOp = Literal["AND", "OR"]
ConditionKind = Literal["leaf", "group"]
LeafKind = Literal["tag", "rating", "char_in", "char_on"]
ActionKind = Literal[
    "append_list", "append", "replace", "char_set", "char_replace"
]
RuleKind = Literal["block", "raw"]
CharState = Literal["enabled", "disabled"]

# 참고: 런타임 타겟 화이트리스트 (DSL 문법과 일치)
# "char:N" / "uc:N" 은 런타임 정규식 검증 (engine.is_char_uc_target 참조)
TARGETS_PROMPT_LIST = ("prefix", "main", "postfix")
TARGETS_CHAR_UC = ("char:*", "uc:*", "global_uc", "neg")


# ============================================================================
# ConditionNode — leaf 또는 group (재귀)
# ============================================================================


@dataclass
class ConditionNode:
    """조건 노드 — leaf(단일 술어) 또는 group(AND/OR 재귀).

    `negated` 는 leaf 한정으로 전체 조건 부정에 사용. group 레벨 부정은 지원 안 함
    (SRS §5.3: NOT은 leaf 수준만, 그룹 부정은 De Morgan 변환으로 대체).
    """

    kind: ConditionKind = "leaf"

    # --- leaf 공통 ---
    leaf_kind: Optional[LeafKind] = None
    negated: bool = False

    # --- leaf: tag ---
    tag_value: str = ""
    tag_modifier: TagModifier = "contains"

    # --- leaf: rating ---
    rating_value: str = ""  # 'e' | 'q' | 's' | 'g'
    rating_source: RatingSource = "auto"

    # --- leaf: char_in / char_on ---
    char_index: Optional[int] = None  # 1-based (DSL과 일치)
    char_tag_value: str = ""  # char_in 전용
    char_tag_modifier: TagModifier = "contains"  # char_in 전용

    # --- group ---
    logical: Optional[LogicalOp] = None
    children: List["ConditionNode"] = field(default_factory=list)


# ============================================================================
# Action — 타겟 조작 또는 함수형 호출
# ============================================================================


@dataclass
class Action:
    """액션 — 타겟 조작 또는 함수형 호출.

    - append_list / append: `target` + `tags` 사용
    - replace: `old_tag` (타겟이름 전체교체 or 특정태그/패턴 부분치환) + `new_tags`
    - char_set: `char_index` + `char_state`
    - char_replace: `char_index` + `char_old_tag` + `char_new_tag`
    """

    kind: ActionKind = "append_list"
    target: str = "main"  # prefix|main|postfix|char:N|uc:N|global_uc|neg|char:*|uc:*
    preserve_weight: bool = True

    # append_list, append
    tags: List[str] = field(default_factory=list)

    # replace
    old_tag: str = ""
    new_tags: List[str] = field(default_factory=list)

    # char_set
    char_state: Optional[CharState] = None

    # char_replace
    char_index: Optional[int] = None  # 1-based
    char_old_tag: str = ""
    char_new_tag: str = ""


# ============================================================================
# Rule / RuleBook
# ============================================================================


@dataclass
class Rule:
    """규칙 — enabled/priority + condition/action 또는 raw_dsl.

    `kind="raw"` 는 블록으로 표현 불가한 legacy DSL 라인 보존용 (Phase 1.3 역파싱
    실패 fallback). `enabled=False` → DSL 직렬화 시 `#` prefix 로 주석화.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    enabled: bool = True
    priority: int = 100  # D7: 낮을수록 먼저 실행 (리스트 정렬 기준)
    kind: RuleKind = "block"

    # kind == "block"
    condition: Optional[ConditionNode] = None
    action: Optional[Action] = None

    # kind == "raw"
    raw_dsl: Optional[str] = None


@dataclass
class RuleBook:
    """규칙 묶음 — 프리셋 저장/로드 단위 (D4: 엔진 옵션은 메타 필드).

    `rules` 의 순서는 priority 기반. `sorted_rules()` 로 정렬된 뷰 반환.
    """

    rules: List[Rule] = field(default_factory=list)
    max_passes: int = 1
    stop_on_match: bool = False

    def sorted_rules(self) -> List[Rule]:
        """priority 오름차순 + 기존 입력 순서 유지 (stable sort)."""
        return sorted(self.rules, key=lambda r: r.priority)


# ============================================================================
# Convenience factories (테스트 및 블록 UI 편의)
# ============================================================================


def make_tag_leaf(
    value: str,
    modifier: TagModifier = "contains",
    negated: bool = False,
) -> ConditionNode:
    return ConditionNode(
        kind="leaf",
        leaf_kind="tag",
        negated=negated,
        tag_value=value,
        tag_modifier=modifier,
    )


def make_rating_leaf(
    value: str,
    source: RatingSource = "auto",
    negated: bool = False,
) -> ConditionNode:
    return ConditionNode(
        kind="leaf",
        leaf_kind="rating",
        negated=negated,
        rating_value=value,
        rating_source=source,
    )


def make_char_in_leaf(
    char_index: int,
    tag_value: str,
    modifier: TagModifier = "contains",
    negated: bool = False,
) -> ConditionNode:
    return ConditionNode(
        kind="leaf",
        leaf_kind="char_in",
        negated=negated,
        char_index=char_index,
        char_tag_value=tag_value,
        char_tag_modifier=modifier,
    )


def make_char_on_leaf(char_index: int, negated: bool = False) -> ConditionNode:
    return ConditionNode(
        kind="leaf",
        leaf_kind="char_on",
        negated=negated,
        char_index=char_index,
    )


def make_and_group(*children: ConditionNode) -> ConditionNode:
    return ConditionNode(kind="group", logical="AND", children=list(children))


def make_or_group(*children: ConditionNode) -> ConditionNode:
    return ConditionNode(kind="group", logical="OR", children=list(children))
