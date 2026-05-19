"""Conditional Prompt Editor v2.1 — Block → DSL 직렬화 (단방향).

블록 모델(`block_model.py`)을 기존 `conditional_prompt_module` 엔진이 소비하는
DSL 텍스트로 변환. 왕복 역파싱은 Sub-phase 1.3의 `dsl_parser` 소관.

HANDOFF: docs/HANDOFF_CONDITIONAL_PROMPT_V2_2026_04_21.md
SRS:     docs/CONDITIONAL_PROMPT_EDITOR_PHASE1_SRS.md §5.3
"""

from __future__ import annotations

from typing import List

from legacy_desktop.modules.conditional.block_model import (
    Action,
    ConditionNode,
    Rule,
    RuleBook,
    TagModifier,
)


# ============================================================================
# 태그 modifier → DSL 접두사
# ============================================================================

_TAG_MODIFIER_PREFIX = {
    "contains": "",
    "exact": "*",
    "not_contains": "~",
    "not_exact": "~!",
}


def _tag_prefix(modifier: TagModifier) -> str:
    return _TAG_MODIFIER_PREFIX[modifier]


# ============================================================================
# Condition 직렬화
# ============================================================================


def serialize_condition(cond: ConditionNode, *, is_root: bool = True) -> str:
    """ConditionNode → DSL 조건 표현식 (외부 () 는 rule 레벨에서 붙임).

    - is_root=False: AND/OR 그룹을 `(...)` 로 감쌈 (중첩 우선순위).
    - is_root=True: 최상위 그룹은 `()` 없이 내부만 반환 (규칙이 직접 감쌈).
    """
    if cond.kind == "leaf":
        return _serialize_leaf(cond)

    # group
    if not cond.children:
        return ""  # 빈 그룹 → 무조건 매칭

    if len(cond.children) == 1:
        return serialize_condition(cond.children[0], is_root=is_root)

    sep = "&" if cond.logical == "AND" else "|"
    inner = sep.join(
        serialize_condition(c, is_root=False) for c in cond.children
    )
    return inner if is_root else f"({inner})"


def _serialize_leaf(leaf: ConditionNode) -> str:
    kind = leaf.leaf_kind

    if kind == "tag":
        prefix = _tag_prefix(leaf.tag_modifier)
        body = f"{prefix}{leaf.tag_value}"
        # 외부 부정(~)은 modifier prefix 와 충돌 방지 — 이미 `~`/`~!` 이면 negated 무시
        if leaf.negated and not body.startswith("~"):
            return f"~{body}"
        return body

    if kind == "rating":
        neg = "~" if leaf.negated else ""
        # source=auto 는 레거시 단순 문법(e/q/s/g)으로 축약
        if leaf.rating_source == "auto":
            return f"{neg}{leaf.rating_value}"
        return f"{neg}rating({leaf.rating_value}, source={leaf.rating_source})"

    if kind == "char_in":
        inner_prefix = _tag_prefix(leaf.char_tag_modifier)
        inner = f"{inner_prefix}{leaf.char_tag_value}"
        neg = "~" if leaf.negated else ""
        return f"{neg}char_in({leaf.char_index}, {inner})"

    if kind == "char_on":
        neg = "~" if leaf.negated else ""
        return f"{neg}char_on({leaf.char_index})"

    raise ValueError(f"Unknown leaf_kind: {kind}")


# ============================================================================
# Action 직렬화
# ============================================================================


def serialize_action(action: Action) -> str:
    k = action.kind

    if k == "append_list":
        return f"{action.target}+={_join_tags(action.tags)}"

    if k == "append":
        return f"{action.target}+:{_join_tags(action.tags)}"

    if k == "replace":
        # old_tag 는 '타겟 이름'(전체 교체) 또는 특정 태그/패턴(부분 치환)
        rhs = _join_tags(action.new_tags)
        return f"{action.old_tag}={rhs}"

    if k == "char_set":
        return f"char_set({action.char_index}, {action.char_state})"

    if k == "char_replace":
        return (
            f"char_replace({action.char_index}, "
            f"{action.char_old_tag}, {action.char_new_tag})"
        )

    if k == "char_append":
        # 레거시 호환 DSL 로 직렬화 (char:N+=tags). 런타임은 이미 이 문법을
        # 처리하고 있으므로 신규 kind 추가로 인한 엔진 변경 불필요.
        idx = action.char_index if action.char_index is not None else 1
        return f"char:{idx}+={_join_tags(action.tags)}"

    raise ValueError(f"Unknown action kind: {k}")


def _join_tags(tags: List[str]) -> str:
    """태그 리스트를 '^' 구분자로 결합 (DSL 복수 태그 규약).

    단일 태그는 그대로. 빈 리스트는 빈 문자열 (예: 삭제용 `__tag=,`).
    """
    cleaned = [t.strip() for t in tags if t and t.strip()]
    return "^".join(cleaned)


# ============================================================================
# Rule / RuleBook 직렬화
# ============================================================================


def serialize_rule(rule: Rule) -> str:
    """단일 규칙 → DSL 라인.

    - enabled=False → `#` prefix 주석화
    - kind="raw" → raw_dsl 원문 그대로 (enabled=False 면 앞에 `#`)
    """
    if rule.kind == "raw":
        line = (rule.raw_dsl or "").strip()
        if not line:
            return ""
        if not rule.enabled and not line.startswith("#"):
            return f"#{line}"
        return line

    # kind == "block"
    cond_expr = ""
    if rule.condition is not None:
        cond_expr = serialize_condition(rule.condition, is_root=True)
    act_expr = serialize_action(rule.action) if rule.action else ""
    line = f"({cond_expr}):{act_expr}"

    if not rule.enabled:
        return f"#{line}"
    return line


def serialize_rulebook(book: RuleBook) -> str:
    """RuleBook → DSL 텍스트.

    - priority 오름차순으로 규칙 정렬
    - `,\\n` 으로 구분 (기존 엔진 `_split_rules_with_quotes` 호환)
    - 엔진 옵션(max_passes/stop_on_match)은 DSL에 직렬화하지 않음 — 프리셋 메타 JSON
      에만 존재 (D4).
    """
    lines = [serialize_rule(r) for r in book.sorted_rules()]
    lines = [l for l in lines if l.strip()]
    return ",\n".join(lines)
