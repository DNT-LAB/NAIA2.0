"""Conditional Prompt Editor v2.1 — DSL → Block 역파싱 (베스트 에포트).

기존 `conditional_prompt_module` 이 런타임에 사용하는 DSL 텍스트를 블록 모델
(`block_model.py`) 로 복원. 파싱 실패한 규칙은 `Rule(kind="raw", raw_dsl=...)` 로
fallback 하여 원문을 보존한다 (D6: 블록→DSL 왕복은 보장, 역방향은 best-effort).

HANDOFF: docs/HANDOFF_CONDITIONAL_PROMPT_V2_2026_04_21.md
SRS:     docs/CONDITIONAL_PROMPT_EDITOR_PHASE1_SRS.md §5.3 / §5.4
"""

from __future__ import annotations

import re
from typing import List, Tuple

from core.conditional.block_model import (
    Action,
    ActionKind,
    CharState,
    ConditionNode,
    RatingSource,
    Rule,
    RuleBook,
    TagModifier,
)


# ============================================================================
# 정규식 — `conditional_prompt_module.py` 와 호환 유지
# ============================================================================

_RATING_FUNC_RE = re.compile(
    r'^(~?)rating\s*\(\s*([eqsg])\s*'
    r'(?:,\s*source\s*=\s*(auto|row|override|bayes)\s*)?\)$'
)
_CHAR_IN_RE = re.compile(r'^(~?)char_in\s*\(\s*(\d+)\s*,\s*(.+?)\s*\)$')
_CHAR_ON_RE = re.compile(r'^(~?)char_on\s*\(\s*(\d+)\s*\)$')
_FUNC_ACTION_RE = re.compile(r'^([a-z_]+)\s*\(\s*(.*)\s*\)$', re.DOTALL)
_CHAR_UC_TARGET_RE = re.compile(r'^(char|uc):(\d+|\*)$')

_FIXED_TARGETS = ("prefix", "main", "postfix", "global_uc", "neg")
_LEGACY_RATING_CHARS = ("e", "q", "s", "g")


# ============================================================================
# Public API
# ============================================================================


def parse_rulebook(dsl_text: str) -> RuleBook:
    """DSL 텍스트 → RuleBook. 라인별 best-effort, 실패 시 raw fallback."""
    book = RuleBook()
    if not dsl_text or not dsl_text.strip():
        return book

    for line in _split_rules(dsl_text):
        rule = parse_rule(line)
        if rule is not None:
            book.rules.append(rule)
    return book


def parse_rule(rule_line: str) -> Rule:
    """단일 DSL 라인 → Rule. 실패 시 kind='raw'."""
    line = rule_line.strip()
    if not line:
        return Rule(kind="raw", raw_dsl="", enabled=True)

    enabled = True
    if line.startswith("#"):
        enabled = False
        line = line[1:].lstrip()

    try:
        cond_text, act_text = _split_rule(line)
        condition = parse_condition(cond_text)
        action = parse_action(act_text)
        return Rule(
            kind="block",
            enabled=enabled,
            condition=condition,
            action=action,
        )
    except Exception:
        return Rule(
            kind="raw",
            enabled=enabled,
            raw_dsl=line,
        )


def parse_condition(text: str) -> ConditionNode:
    """조건 표현식 → ConditionNode. 빈 문자열은 빈 AND 그룹."""
    text = text.strip()
    if not text:
        return ConditionNode(kind="group", logical="AND", children=[])

    # 최외곽 괄호 제거 (매칭되는 경우만 반복)
    while text.startswith("(") and text.endswith(")"):
        close = _matching_paren(text, 0)
        if close == len(text) - 1:
            text = text[1:-1].strip()
            if not text:
                return ConditionNode(
                    kind="group", logical="AND", children=[]
                )
        else:
            break

    # 우선순위: | (낮음) → & (높음) → leaf
    or_parts = _split_at_depth_0(text, "|")
    if len(or_parts) > 1:
        return ConditionNode(
            kind="group",
            logical="OR",
            children=[parse_condition(p) for p in or_parts],
        )

    and_parts = _split_at_depth_0(text, "&")
    if len(and_parts) > 1:
        return ConditionNode(
            kind="group",
            logical="AND",
            children=[parse_condition(p) for p in and_parts],
        )

    return _parse_leaf(text)


def parse_action(text: str) -> Action:
    """액션 표현식 → Action. 지원 불가(insert 류)는 ValueError."""
    text = text.strip()
    text = _strip_outer_quotes(text)

    # 함수형 먼저 매칭 (char_set / char_replace)
    func = _try_parse_func_action(text)
    if func is not None:
        return func

    if "+=" in text:
        left, _, right = text.partition("+=")
        left = left.strip()
        if _is_valid_target(left):
            return Action(
                kind="append_list",
                target=left,
                tags=_parse_tag_list(right),
            )
        # existing_tag+= (legacy insert) — 블록 모델 미지원
        raise ValueError(
            f"insert 액션(existing_tag+=) 은 블록 모델 미지원: {text}"
        )

    if "+:" in text:
        left, _, right = text.partition("+:")
        left = left.strip()
        if _is_valid_target(left):
            target = left
            tag_part = right
        else:
            target = "main"
            tag_part = text.replace("+:", "", 1)
        return Action(
            kind="append",
            target=target,
            tags=_parse_tag_list(tag_part.strip()),
        )

    if "=" in text:
        left, _, right = text.partition("=")
        return Action(
            kind="replace",
            old_tag=left.strip(),
            new_tags=_parse_tag_list(right.strip()),
        )

    raise ValueError(f"알 수 없는 액션 형식: {text}")


# ============================================================================
# 내부 헬퍼 — 조건
# ============================================================================


def _parse_leaf(text: str) -> ConditionNode:
    text = text.strip()

    m = _RATING_FUNC_RE.match(text)
    if m:
        negated = m.group(1) == "~"
        source: RatingSource = m.group(3) or "auto"  # type: ignore[assignment]
        return ConditionNode(
            kind="leaf",
            leaf_kind="rating",
            negated=negated,
            rating_value=m.group(2),
            rating_source=source,
        )

    m = _CHAR_IN_RE.match(text)
    if m:
        negated = m.group(1) == "~"
        idx = int(m.group(2))
        inner = m.group(3).strip()
        mod, val = _parse_tag_modifier(inner)
        return ConditionNode(
            kind="leaf",
            leaf_kind="char_in",
            negated=negated,
            char_index=idx,
            char_tag_value=val,
            char_tag_modifier=mod,
        )

    m = _CHAR_ON_RE.match(text)
    if m:
        negated = m.group(1) == "~"
        return ConditionNode(
            kind="leaf",
            leaf_kind="char_on",
            negated=negated,
            char_index=int(m.group(2)),
        )

    # 레거시 rating: e/q/s/g 단독
    if text in _LEGACY_RATING_CHARS:
        return ConditionNode(
            kind="leaf",
            leaf_kind="rating",
            rating_value=text,
            rating_source="auto",
        )
    if text.startswith("~") and len(text) == 2 and text[1] in _LEGACY_RATING_CHARS:
        return ConditionNode(
            kind="leaf",
            leaf_kind="rating",
            negated=True,
            rating_value=text[1],
            rating_source="auto",
        )

    # 태그 leaf — modifier 기반 (negated 는 사용하지 않음, 충돌 방지)
    mod, val = _parse_tag_modifier(text)
    return ConditionNode(
        kind="leaf",
        leaf_kind="tag",
        tag_value=val,
        tag_modifier=mod,
    )


def _parse_tag_modifier(text: str) -> Tuple[TagModifier, str]:
    """'~!foo' / '~foo' / '*foo' / 'foo' 접두사 해석 → (modifier, tag)."""
    t = text.strip()
    if t.startswith("~!"):
        return "not_exact", t[2:].strip()
    if t.startswith("~"):
        return "not_contains", t[1:].strip()
    if t.startswith("*"):
        return "exact", t[1:].strip()
    return "contains", t


# ============================================================================
# 내부 헬퍼 — 액션
# ============================================================================


def _try_parse_func_action(text: str):
    m = _FUNC_ACTION_RE.match(text)
    if not m:
        return None
    func = m.group(1)
    args_str = m.group(2).strip()
    args = [a.strip() for a in args_str.split(",")] if args_str else []

    if func == "char_set":
        if len(args) != 2:
            raise ValueError(
                f"char_set 은 2 인자 필요 (N, enabled|disabled): {text}"
            )
        idx = int(args[0])
        state = args[1].lower()
        if state not in ("enabled", "disabled"):
            raise ValueError(f"char_set 상태 오류: {state}")
        return Action(
            kind="char_set",
            char_index=idx,
            char_state=state,  # type: ignore[arg-type]
        )

    if func == "char_replace":
        if len(args) != 3:
            raise ValueError(
                f"char_replace 는 3 인자 필요 (N, old, new): {text}"
            )
        idx = int(args[0])
        return Action(
            kind="char_replace",
            char_index=idx,
            char_old_tag=args[1],
            char_new_tag=args[2],
        )

    # 인식 못 한 함수 → fallback 하도록 None (상위에서 += 등 재시도)
    return None


def _parse_tag_list(text: str) -> List[str]:
    """태그 리스트 파싱 — '^' 구분자 우선, 없으면 ',', 없으면 단일."""
    t = _strip_outer_quotes(text.strip())
    if not t:
        return []
    if "^" in t:
        parts = [p.strip() for p in t.split("^")]
    elif "," in t:
        parts = [p.strip() for p in t.split(",")]
    else:
        parts = [t]
    cleaned = []
    for p in parts:
        p = _strip_outer_quotes(p.strip())
        if p:
            cleaned.append(p)
    return cleaned


def _is_valid_target(name: str) -> bool:
    """고정 타겟 또는 char:N/uc:N/char:*/uc:* 형식인지 검증."""
    if name in _FIXED_TARGETS:
        return True
    return bool(_CHAR_UC_TARGET_RE.match(name))


# ============================================================================
# 내부 헬퍼 — 구조 파싱
# ============================================================================


def _split_rule(line: str) -> Tuple[str, str]:
    """'(cond):action' → (cond, action). 괄호 중첩 인식."""
    line = line.strip()
    if not line.startswith("("):
        raise ValueError(f"규칙은 '(' 로 시작해야 함: {line}")
    depth = 0
    for i, ch in enumerate(line):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                if i + 1 >= len(line) or line[i + 1] != ":":
                    raise ValueError(f"')' 뒤에 ':' 없음: {line}")
                return line[1:i], line[i + 2:]
    raise ValueError(f"매칭되는 ')' 없음: {line}")


def _split_rules(text: str) -> List[str]:
    """쉼표 분할. 괄호/따옴표 내부는 무시. # 주석 라인 보존.

    엔진의 `_split_rules_with_quotes` 와 동일 로직이지만 `#` 라인을 drop 하지
    않고 유지한다 (블록 에디터에서 enabled 토글로 복원 가능).
    """
    rules: List[str] = []
    current = ""
    in_quotes = False
    paren_depth = 0

    for i, ch in enumerate(text):
        if ch == "(":
            paren_depth += 1
        elif ch == ")":
            paren_depth -= 1

        if ch == '"' and (i == 0 or text[i - 1] != "\\"):
            in_quotes = not in_quotes

        if ch == "," and not in_quotes and paren_depth == 0:
            if current.strip():
                rules.append(current.strip())
            current = ""
        else:
            current += ch

    if current.strip():
        rules.append(current.strip())
    return rules


def _matching_paren(s: str, start: int) -> int:
    """`s[start]` 가 '(' 일 때 짝 ')' 위치. 없으면 -1."""
    depth = 1
    for i in range(start + 1, len(s)):
        if s[i] == "(":
            depth += 1
        elif s[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _split_at_depth_0(text: str, op: str) -> List[str]:
    """괄호 depth 0 에서만 `op` 로 분할."""
    parts: List[str] = []
    current = ""
    depth = 0
    for ch in text:
        if ch == "(":
            depth += 1
            current += ch
        elif ch == ")":
            depth -= 1
            current += ch
        elif ch == op and depth == 0:
            parts.append(current.strip())
            current = ""
        else:
            current += ch
    if current.strip():
        parts.append(current.strip())
    return parts


def _strip_outer_quotes(text: str) -> str:
    t = text.strip()
    if len(t) >= 2 and (
        (t.startswith('"') and t.endswith('"'))
        or (t.startswith("'") and t.endswith("'"))
    ):
        return t[1:-1]
    return t


__all__ = [
    "parse_rulebook",
    "parse_rule",
    "parse_condition",
    "parse_action",
]
