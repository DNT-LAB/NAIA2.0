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
    CHAR_ON_RE,
    RATING_FUNC_RE,
    has_operator_shape_defect,
    iter_condition_spans,
    matching_paren,
    split_by_operator,
    strip_redundant_outer_parens,
    top_level_operators,
    utf16_offset,
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
_RATING_CHARS = {"e", "q", "s", "g"}


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
    """규칙 텍스트 전체 → 경고가 있는 규칙 목록.

    각 항목: condition(표시용) / raw(원문 그대로) / start,end(조건 본문 구간) / line /
    warnings / fix(De Morgan 치환식, 없으면 None).

    `start`·`end`·`raw` 는 UI가 **원클릭 적용 전에 텍스트가 그새 바뀌지 않았는지**
    검증하는 용도다(offset 만 믿고 갈아끼우면 편집 중인 내용을 훼손한다).

    ⚠️ `start`/`end` 는 **UTF-16 code unit** 기준이다 — 유일한 소비자가 JS 이고
    `String.prototype.slice` 가 UTF-16 단위로 자르기 때문. Python 의 code point 인덱스를
    그대로 보내면 이모지 같은 non-BMP 문자가 하나만 있어도 어긋나 정상 규칙까지
    "그새 바뀌었다"며 적용이 거부된다.

    같은 이유로 줄바꿈을 `\\n` 으로 정규화한 좌표를 쓴다 — 브라우저는 textarea 의 value 를
    항상 `\\n` 으로 정규화하므로, 원본에 `\\r\\n` 이 있으면 둘째 줄부터 구간이 밀린다.
    """
    text = str(rules_text or "").replace("\r\n", "\n").replace("\r", "\n")
    findings: list[dict[str, Any]] = []
    for open_index, close_index in iter_condition_spans(text):
        condition = text[open_index + 1:close_index]
        warnings = lint_condition(condition)
        if warnings:
            findings.append({
                "condition": condition.strip(),
                "raw": condition,
                "start": utf16_offset(text, open_index + 1),
                "end": utf16_offset(text, close_index),
                "line": text.count("\n", 0, open_index) + 1,
                "warnings": warnings,
                "fix": demorgan_rewrite(condition),
            })
    return findings


# ============================================================================
# De Morgan 치환 — `~(...)` 를 지원되는 문법으로 펼친 동등식
# ============================================================================

def _wrap_for(operator: str, expression: str) -> str:
    """`operator` 로 이어붙일 때 이 조각을 괄호로 묶어야 하는가.

    **반대 연산자가 섞일 때만** 묶는다.
    - `&` 로 이을 때 `|` 를 품은 조각: 안 묶으면 `&` 가 먼저 붙어 의미가 깨진다 (필수).
    - `|` 로 이을 때 `&` 를 품은 조각: 의미상 불필요하지만 **명시한다** — 우선순위 혼동이
      이 기능의 발단이었으므로 제안문은 읽는 대로 읽히는 편이 낫다.
    - 같은 연산자끼리는 묶지 않는다 (`~a | (b | c)` 같은 잉여 괄호 방지).
    """
    expression = expression.strip()
    opposite = "&" if operator == "|" else "|"
    if opposite in top_level_operators(strip_redundant_outer_parens(expression)):
        return f"({expression})"
    return expression


def _is_plain_contains_leaf(text: str) -> bool:
    """런타임이 이 문자열을 **접두사 없는 contains 태그**로 분류하는가.

    `~BODY` 에서 `~` 를 떼는 방향이 안전하려면 BODY 가 그대로 contains 잎이어야 한다.
    아니면 needle 이 다른 범주로 재해석된다 — `~ e` 는 리터럴 "e" 를 찾지만 `e` 는
    **rating 조건**이고, `~ !a` 의 `!a` 는 **exact modifier** 가 된다.
    """
    body = text.strip()
    if not body:
        return False
    if body[0] in "*!~\"'(":
        return False
    if body in _RATING_CHARS:
        return False
    if RATING_FUNC_RE.match(body) or CHAR_IN_RE.match(body) or CHAR_ON_RE.match(body):
        return False
    return True


def _negate_leaf(leaf: str) -> str:
    """단일 조건의 부정형.

    **런타임 `_evaluate_single_condition` 의 분류 순서를 그대로 따라간다.** 접두사만 기계적으로
    뒤집으면 결과가 다른 범주로 재분류되어 의미가 조용히 바뀐다(rating / 함수 / modifier).
    안전하게 뒤집을 수 없는 입력은 ValueError → 제안 자체를 하지 않는다.
    """
    text = leaf.strip()
    if not text:
        raise ValueError("빈 잎은 부정형을 만들 수 없습니다")

    # 이미 잘못된 토큰(`~*a` 등)은 De Morgan 동치가 성립하지 않는다.
    if lint_condition(text):
        raise ValueError(f"잘못된 토큰은 부정형을 만들 수 없습니다: {text!r}")

    # 0) 따옴표 — 런타임이 잎 평가 전에 `_remove_outer_quotes` 를 돌리므로 **안쪽**을 부정한다.
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'"):
        quote = text[0]
        return f"{quote}{_negate_leaf(text[1:-1])}{quote}"

    # 1~3) 함수형 — 선두 `~` 토글이 곧 부정이다(정규식이 양쪽 모두 매칭).
    for regex in (RATING_FUNC_RE, CHAR_IN_RE, CHAR_ON_RE):
        match = regex.match(text)
        if match:
            return text[1:].strip() if match.group(1) == "~" else f"~{text}"

    # 4~5) 레거시 rating — 런타임은 `e`/`~e` **정확히 그 문자열**만 rating 으로 본다.
    if text in _RATING_CHARS:
        return f"~{text}"
    if text.startswith("~") and text[1:] in _RATING_CHARS:
        return text[1:]

    # 6) `~!X` -> `*X` — 양쪽 다 needle 이 X 인 원소 멤버십. 재분류 위험 없음.
    if text.startswith("~!"):
        body = text[2:].strip()
        if not body:
            raise ValueError("피연산자가 없는 조건은 부정형을 만들 수 없습니다")
        return f"*{body}"

    # 7) `~X` -> `X` — **유일하게 위험한 방향**. X 가 contains 잎으로 남아야 한다.
    if text.startswith("~"):
        body = text[1:].strip()
        if not _is_plain_contains_leaf(body):
            raise ValueError(f"다른 범주로 재해석되는 부정은 만들 수 없습니다: {text!r}")
        return body

    # 8~9) `!X` / `*X` -> `~!X` — needle 이 X 로 보존된다.
    if text[0] in "!*":
        body = text[1:].strip()
        if not body:
            raise ValueError("피연산자가 없는 조건은 부정형을 만들 수 없습니다")
        return f"~!{body}"

    # 10) 접두사 없는 contains -> `~X`
    return f"~{text}"


def _negate_expression(expression: str) -> str:
    """식 전체의 부정형을 De Morgan 으로 밀어 내린다."""
    expression = strip_redundant_outer_parens(expression)
    if not expression:
        # 빈 조건은 "항상 참" 이라 부정은 "항상 거짓" — 표현할 문법이 없다.
        raise ValueError("빈 조건은 부정형을 만들 수 없습니다")

    # `~(...)` 의 부정은 괄호 안 그대로 (이중 부정)
    if expression.startswith("~("):
        close = matching_paren(expression, 1)
        if close == len(expression) - 1:
            return strip_redundant_outer_parens(expression[2:-1])

    or_parts = split_by_operator(expression, "|")
    if len(or_parts) > 1:
        return " & ".join(_wrap_for("&", _negate_expression(part)) for part in or_parts)

    and_parts = split_by_operator(expression, "&")
    if len(and_parts) > 1:
        return " | ".join(_wrap_for("|", _negate_expression(part)) for part in and_parts)

    return _negate_leaf(expression)


def _rewrite_groups(expression: str) -> str:
    """식 안의 `~(...)` 를 전부 펼친다. 바뀔 게 없으면 입력 그대로."""
    original = expression
    stripped = expression.strip()
    if not stripped:
        return original

    if stripped.startswith("~("):
        close = matching_paren(stripped, 1)
        if close == len(stripped) - 1:
            # 안쪽에 또 `~(...)` 가 있을 수 있으니 먼저 펼친 뒤 부정한다.
            return _negate_expression(_rewrite_groups(stripped[2:-1]))

    inner = _peel_one_paren(stripped)
    if inner is not None:
        rewritten = _rewrite_groups(inner)
        return original if rewritten == inner else f"({rewritten})"

    if not top_level_operators(stripped):
        call = CHAR_IN_RE.match(stripped)
        if call:
            rewritten = _rewrite_groups(call.group(3))
            if rewritten != call.group(3):
                return f"{call.group(1)}char_in({call.group(2)}, {rewritten.strip()})"
        return original

    for operator, joiner in (("|", " | "), ("&", " & ")):
        parts = split_by_operator(stripped, operator)
        if len(parts) > 1:
            rebuilt = [_rewrite_groups(part) for part in parts]
            if all(new == old for new, old in zip(rebuilt, parts)):
                return original
            # 펼친 조각이 최상위 연산자를 갖게 되면 반드시 괄호로 묶는다. `&` 가 `|` 보다
            # 강하게 묶이므로, 안 씌우면 `x & ~(a & b)` 가 `(x & ~a) | ~b` 로 읽힌다.
            return joiner.join(_wrap_for(operator, part) for part in rebuilt)
    return original


def demorgan_rewrite(condition: str) -> str | None:
    """`~(...)` 를 지원 문법으로 펼친 **동등한** 조건식. 대상이 없거나 만들 수 없으면 None.

    그룹 부정은 런타임이 지원하지 않아 조용히 항상 참이 된다. 문법을 늘리는 대신
    사용자가 그대로 쓸 수 있는 치환식을 돌려주는 쪽을 택했다(De Morgan).
    모양이 깨진 식(`a|&b`)이 섞여 있으면 치환 결과의 의미를 보장할 수 없어 포기한다.
    """
    text = str(condition or "")
    if "~(" not in text or has_operator_shape_defect(text):
        return None
    try:
        rewritten = _rewrite_groups(text).strip()
    except ValueError:
        return None
    if not rewritten or rewritten == text.strip() or "~(" in rewritten:
        return None
    # 최종 안전망 — 제안식이 또 경고를 부르면(= 잘못된 토큰이 섞여 나왔으면) 내놓지 않는다.
    if lint_condition(rewritten):
        return None
    return rewritten


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
