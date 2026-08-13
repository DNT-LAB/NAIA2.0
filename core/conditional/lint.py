"""조건부 프롬프트 조건식 린트 + 우선순위 마이그레이션.

두 가지를 한다.

1. ``lint_rules_text`` — **거부하지 않고 경고만** 낸다. 잘못된 토큰(`~*tag`, `~(...)`,
   빈 피연산자 등)은 런타임에서 에러가 아니라 "리터럴 문자열 비교"로 흘러가 조건이 조용히
   항상참/항상거짓이 된다. 이미 그런 규칙을 돌리고 있는 사용자의 출력을 바꾸지 않기 위해
   차단 대신 배지로 알린다.

2. ``migrate_rules_text`` — 괄호 없이 `&` 와 `|` 를 섞은 조건에 명시적 괄호를 넣어
   **구(舊) 런타임 의미를 못박는다**. 구 런타임은 `&` 를 먼저 최상위 분할해서 `a|b&c` 를
   `(a|b)&c` 로 계산했다(표준과 반대). 우선순위를 표준으로 고치기 전에 이 마이그레이션을
   태우면 기존 규칙의 결과가 1비트도 바뀌지 않는다. idempotent — 이미 괄호가 있으면 무동작.
"""

from __future__ import annotations

import re
from typing import Any

from core.conditional.expr_utils import (
    CHAR_IN_RE,
    has_operator_shape_defect,
    iter_condition_spans,
    matching_paren,
    split_by_operator,
    strip_redundant_outer_parens,
    top_level_operators,
)

# 부정 뒤에 와도 되는 것들 — `~char_in(...)`, `~rating(...)`, `~char_on(...)` 은 정상 문법이라
# "`~` 바로 뒤 `(`" 검사에 걸리면 안 된다. `~` 직후 문자만 보므로 함수형은 자연히 통과한다.
_ALWAYS_TRUE_PREFIXES = {
    "~*": ("cond.not_star", "`~*` 는 문법이 아닙니다 — 별표까지 태그 이름으로 찾아서 항상 참이 됩니다. `~!` 를 쓰세요."),
    "~(": ("cond.not_group", "괄호 그룹 부정은 지원하지 않습니다 — 항상 참이 됩니다. 각 항목에 `~!` 를 붙여 `&` 로 묶으세요."),
    "~~": ("cond.double_not", "`~~` 는 이중 부정이 아니라 리터럴 비교가 되어 항상 참입니다."),
}
_ALWAYS_FALSE_PREFIXES = {
    "*~": ("cond.star_not", "`*~` 는 문법이 아닙니다 — 물결까지 태그 이름으로 찾아서 항상 거짓이 됩니다."),
}
_EMPTY_OPERANDS = {"~", "~!", "!", "*"}


def _iter_leaves(expression: str):
    """논리식을 잎(단일 조건)으로 분해. 분할 순서와 무관하게 잎 집합은 동일하다."""
    expression = strip_redundant_outer_parens(expression)
    if not expression:
        yield expression
        return
    for operator in ("|", "&"):
        parts = split_by_operator(expression, operator)
        if len(parts) > 1:
            for part in parts:
                yield from _iter_leaves(part)
            return
    yield expression


# 연산자 모양 결함은 **괄호 깊이와 무관하게** 잡아야 한다 — `a|(b&&c)` 나 `char_in(1, a&&b)`
# 처럼 안쪽 층에 숨어 있어도 런타임은 그 층을 재귀 평가하므로 똑같이 조용히 망가진다.
_DOUBLED_OPERATOR_RE = re.compile(r"[&|]\s*[&|]")
_LEADING_OPERATOR_RE = re.compile(r"(?:^|\()\s*[&|]")
_TRAILING_OPERATOR_RE = re.compile(r"[&|]\s*(?:\)|$)")


def _operator_shape_problem(expression: str) -> str | None:
    """연산자가 연달아 오거나 식/괄호 경계에 걸친 경우 (`a&&b`, `&a`, `a&`, `a|(b&&c)`).

    판정은 `expr_utils.has_operator_shape_defect` 에 위임한다 — 런타임이 **같은 판정으로**
    구 우선순위 호환 모드에 들어가므로, 경고와 실행 모드가 갈리면 안 된다.
    """
    if not has_operator_shape_defect(expression):
        return None
    text = str(expression or "")
    if _DOUBLED_OPERATOR_RE.search(text):
        return "연산자가 연달아 있습니다 (`&&` / `||`)"
    if _LEADING_OPERATOR_RE.search(text):
        return "연산자로 시작하는 구간이 있습니다"
    return "연산자로 끝나는 구간이 있습니다"


def lint_condition(condition: str) -> list[dict[str, str]]:
    """단일 조건식 → 경고 목록. 정상이면 빈 리스트."""
    warnings: list[dict[str, str]] = []
    condition = str(condition or "")

    shape = _operator_shape_problem(condition)
    if shape:
        warnings.append({
            "code": "cond.operator_shape",
            "level": "warn",
            "message": f"{shape} — 빈 피연산자는 조용히 무시되거나 항상 참이 됩니다.",
        })

    for leaf in _iter_leaves(condition):
        leaf = strip_redundant_outer_parens(leaf)
        stripped = leaf.strip()
        if not stripped:
            # `():main+=tag` — 빈 조건은 "무조건 적용"을 뜻하는 정식 관용구다. 경고하지 않는다.
            continue
        # `char_in(N, <식>)` 의 인자는 런타임이 논리식으로 재귀 평가하므로 안쪽도 검사한다.
        call = CHAR_IN_RE.match(stripped)
        if call:
            inner = call.group(3).strip()
            if not inner:
                warnings.append({
                    "code": "cond.empty_char_in",
                    "level": "warn",
                    "message": f"`{stripped}` — 조건이 비어 항상 참입니다. 캐릭터 활성 여부만 보려면 `char_on({call.group(2)})` 를 쓰세요.",
                })
            else:
                warnings.extend(lint_condition(inner))
            continue
        if stripped in _EMPTY_OPERANDS:
            warnings.append({
                "code": "cond.empty_operand",
                "level": "warn",
                "message": f"`{stripped}` 뒤에 태그가 없습니다 — 항상 참이 됩니다.",
            })
            continue
        for prefix, (code, message) in _ALWAYS_TRUE_PREFIXES.items():
            if stripped.startswith(prefix):
                warnings.append({"code": code, "level": "warn", "message": f"`{stripped}` — {message}"})
                break
        else:
            for prefix, (code, message) in _ALWAYS_FALSE_PREFIXES.items():
                if stripped.startswith(prefix):
                    warnings.append({"code": code, "level": "warn", "message": f"`{stripped}` — {message}"})
                    break

    # 같은 코드가 여러 잎에서 반복되면 한 번만 남긴다(배지 도배 방지).
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for warning in warnings:
        key = f"{warning['code']}::{warning['message']}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(warning)
    return unique


def lint_rules_text(rules_text: str) -> list[dict[str, Any]]:
    """규칙 텍스트 전체 → [{'condition', 'line', 'warnings'}]. 경고가 있는 규칙만 담는다."""
    text = str(rules_text or "")
    findings: list[dict[str, Any]] = []
    for open_index, close_index in iter_condition_spans(text):
        condition = text[open_index + 1:close_index]
        warnings = lint_condition(condition)
        if warnings:
            findings.append({
                "condition": condition.strip(),
                "line": text.count("\n", 0, open_index) + 1,
                "warnings": warnings,
            })
    return findings


def _peel_one_paren(expression: str) -> str | None:
    """식 전체를 감싼 괄호 한 겹만 벗긴다. 전체를 감싸고 있지 않으면 None."""
    if expression.startswith("(") and expression.endswith(")"):
        if matching_paren(expression, 0) == len(expression) - 1:
            return expression[1:-1]
    return None


def _migrate_expression(expression: str) -> str:
    """구 런타임의 그룹핑을 명시적 괄호로 고정한다.

    구 런타임: 겉괄호를 벗기고 → 최상위 `&` 로 먼저 분할(AND) → 없으면 `|` 로 분할(OR) → 잎.
    신 런타임: `|` 를 먼저 분할한다. 그래서 최상위에 `&` 가 있는 층에서는, `|` 를 품은 각
    피연산자를 괄호로 감싸 두면 두 구현의 그룹핑이 같아진다.

    **괄호 안쪽과 중첩 층까지 재귀해야 한다** — 겉괄호로 감싼 `((a&c)|d&b)` 나 중첩된
    `(a|b&c)&d` 는 최상위에 혼용이 안 보여도 안쪽 층에서 그룹핑이 갈린다.
    바뀔 것이 없으면 **입력 문자열을 그대로** 돌려준다(불필요한 재작성·공백 변경 방지).
    """
    original = expression
    stripped = expression.strip()
    if not stripped:
        return original

    inner = _peel_one_paren(stripped)
    if inner is not None:
        migrated_inner = _migrate_expression(inner)
        return original if migrated_inner == inner else f"({migrated_inner})"

    if not top_level_operators(stripped):
        # 잎이지만 `char_in(N, <식>)` 의 인자는 런타임이 **논리식으로 재귀 평가**하므로
        # (conditional_prompt_runtime `_evaluate_single_condition` → `_evaluate_logical_expression`)
        # 그 안쪽도 마이그레이션해야 구 의미가 보존된다. rating/char_on 은 논리식이 아니다.
        call = CHAR_IN_RE.match(stripped)
        if call:
            inner = call.group(3)
            migrated_inner = _migrate_expression(inner)
            if migrated_inner != inner:
                return f"{call.group(1)}char_in({call.group(2)}, {migrated_inner.strip()})"
        return original

    and_parts = split_by_operator(stripped, "&")
    if len(and_parts) > 1:
        rebuilt: list[str] = []
        changed = False
        for part in and_parts:
            migrated = _migrate_expression(part)
            if migrated != part:
                changed = True
            migrated = migrated.strip()
            if len(split_by_operator(migrated, "|")) > 1:
                migrated = f"({migrated})"
                changed = True
            rebuilt.append(migrated)
        return " & ".join(rebuilt) if changed else original

    or_parts = split_by_operator(stripped, "|")
    if len(or_parts) > 1:
        rebuilt = [_migrate_expression(part) for part in or_parts]
        if all(new == old for new, old in zip(rebuilt, or_parts)):
            return original
        return " | ".join(part.strip() for part in rebuilt)

    return original


def migrate_condition(condition: str) -> str:
    """괄호 없이 `&`/`|` 를 섞은 조건에 구 런타임 의미대로 괄호를 넣는다. 그 외엔 원문 그대로."""
    return _migrate_expression(str(condition or ""))


def migrate_rules_text(rules_text: str) -> str:
    """규칙 텍스트의 조건 구간만 골라 마이그레이션. 주석·개행·간격은 그대로 보존한다."""
    text = str(rules_text or "")
    if not text:
        return text
    spans = list(iter_condition_spans(text))
    if not spans:
        return text
    out: list[str] = []
    cursor = 0
    for open_index, close_index in spans:
        condition = text[open_index + 1:close_index]
        migrated = migrate_condition(condition)
        if migrated == condition:
            continue
        out.append(text[cursor:open_index + 1])
        out.append(migrated)
        cursor = close_index
    if not out:
        return text
    out.append(text[cursor:])
    return "".join(out)
