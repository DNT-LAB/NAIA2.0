"""조건식 스캔 프리미티브 — 런타임/린터/마이그레이션이 공유하는 단일 구현.

이 모듈이 생기기 전에는 괄호 인식 스캐너가 `conditional_prompt_runtime` 안에만 있었고,
린터·마이그레이션이 같은 로직을 다시 구현하면 또 다른 파서 분기가 생긴다(이 파일이 고치려는
결함의 원인 자체가 "조건 파서가 둘"이었다). 의존성 0 — 순환 임포트를 만들지 않는다.
"""

from __future__ import annotations

import re

# 조건 함수 정규식의 단일 정의 — 런타임(conditional_prompt_runtime)과 New Editor 파서
# (conditional/dsl_parser)가 각자 들고 있다가 공백 허용/대소문자/source 허용범위가 갈렸다.
# 여기 하나만 고치면 양쪽이 함께 움직인다.
RATING_FUNC_RE = re.compile(
    r"^(~?)rating\s*\(\s*([eqsg])\s*(?:,\s*source\s*=\s*([^)]+?)\s*)?\)$",
    re.IGNORECASE,
)
CHAR_IN_RE = re.compile(r"^(~?)char_in\s*\(\s*(\d+)\s*,\s*(.*?)\s*\)$", re.IGNORECASE)
CHAR_ON_RE = re.compile(r"^(~?)char_on\s*\(\s*(\d+)\s*\)$", re.IGNORECASE)
KNOWN_RATING_SOURCES = ("auto", "row", "override", "bayes")

# 연산자 모양이 깨진 식: 연산자가 연달아 있거나(`a&&b`, `a|&b`) 식/괄호 경계에 걸린 경우
# (`&a`, `a&`, `a|(&b)`). 깊이와 무관하게 본다 — 런타임이 안쪽 층도 재귀 평가하기 때문.
_OPERATOR_SHAPE_DEFECT_RE = re.compile(r"[&|]\s*[&|]|(?:^|\()\s*[&|]|[&|]\s*(?:\)|$)")


def has_operator_shape_defect(expression: str) -> bool:
    """`a|&b` 처럼 분할기가 빈 피연산자를 버려 의미가 불명확해지는 식인가."""
    text = str(expression or "")
    if not text.strip():
        return False
    return bool(_OPERATOR_SHAPE_DEFECT_RE.search(text))


def utf16_offset(text: str, index: int) -> int:
    """Python code point 인덱스 → **UTF-16 code unit** 인덱스.

    브라우저의 `String.prototype.slice` 는 UTF-16 단위로 자른다. Python 인덱스를 그대로
    넘기면 이모지 같은 non-BMP 문자가 하나만 앞에 있어도 구간이 밀린다.
    """
    return len(str(text or "")[:index].encode("utf-16-le")) // 2


def matching_paren(text: str, start: int) -> int:
    """`text[start]` 가 '(' 일 때 짝이 되는 ')' 의 인덱스. 없으면 -1."""
    depth = 1
    for index in range(start + 1, len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return index
    return -1


def split_by_operator(expression: str, operator: str) -> list[str]:
    """괄호 depth 0 에서만 `operator` 로 분할.

    분할 결과가 1개 이하면 **원본 문자열 그대로** 담은 리스트를 돌려준다(호출부가
    `len(parts) > 1` 로 "이 연산자가 최상위에 있는가"를 판정하는 계약).
    """
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for char in expression:
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        if char == operator and depth == 0:
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
        else:
            current.append(char)
    part = "".join(current).strip()
    if part:
        parts.append(part)
    return parts if len(parts) > 1 else [expression]


def top_level_operators(expression: str) -> set[str]:
    """괄호 depth 0 에 실제로 등장하는 논리 연산자 집합 ({'&'}, {'|'}, 둘 다, 또는 공집합)."""
    depth = 0
    found: set[str] = set()
    for char in str(expression or ""):
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif depth == 0 and char in "&|":
            found.add(char)
    return found


def strip_redundant_outer_parens(expression: str) -> str:
    """전체를 감싼 괄호만 반복 제거. `(a)&(b)` 처럼 짝이 끝까지 안 가면 그대로 둔다."""
    expression = str(expression or "").strip()
    while expression.startswith("(") and expression.endswith(")"):
        end = matching_paren(expression, 0)
        if end != len(expression) - 1:
            break
        expression = expression[1:-1].strip()
    return expression


def iter_condition_spans(text: str):
    """규칙 텍스트에서 조건식이 차지하는 구간만 훑는다.

    **규칙이 시작하는 자리의 `(` 만** 조건으로 인정한다. "짝이 되는 `)` 뒤가 `:`" 라는 모양만
    보면 액션 안의 문자열도 걸린다 — `():main+=(a|b&c):literal` 의 `(a|b&c):` 가 조건으로
    오인되어 액션 태그가 통째로 변조된다(Codex 리뷰에서 재현). 그래서 rule 경계 판정을
    `HeadlessConditionalRuleEngine._split_rules_with_quotes` 와 동일하게 맞춘다:
    따옴표 밖 depth 0 의 `,`/개행 다음에 새 규칙(`#` 또는 조건형 `(`)이 오면 규칙 경계.

    `#` 로 시작하는 주석 규칙은 **건너뛴다** — 실행되지 않는 텍스트라 재작성 이득이 없고,
    산문 주석 안의 DSL 예시를 망가뜨릴 수 있다.

    Yields:
        (open_index, close_index) — condition 본문은 text[open_index+1:close_index]
    """
    text = str(text or "")
    length = len(text)

    def starts_new_rule(pos: int) -> bool:
        cursor = pos
        while cursor < length and text[cursor] in " \t\r\n":
            cursor += 1
        if cursor >= length:
            return False
        if text[cursor] == "#":
            return True
        if text[cursor] != "(":
            return False
        close = matching_paren(text, cursor)
        return close >= 0 and close + 1 < length and text[close + 1] == ":"

    index = 0
    depth = 0
    in_quotes = False
    at_rule_start = True
    while index < length:
        char = text[index]
        if char == '"' and (index == 0 or text[index - 1] != "\\"):
            in_quotes = not in_quotes
            index += 1
            continue
        if in_quotes:
            index += 1
            continue
        if at_rule_start:
            if char in " \t\r\n":
                index += 1
                continue
            if char == "#":
                at_rule_start = False  # 주석 규칙 — 조건을 내주지 않고 액션처럼 훑어 넘긴다
                index += 1
                continue
            if char == "(":
                close = matching_paren(text, index)
                if close >= 0 and close + 1 < length and text[close + 1] == ":":
                    yield (index, close)
                    at_rule_start = False
                    index = close + 2
                    continue
            at_rule_start = False
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif depth == 0 and char in ",\n\r" and starts_new_rule(index + 1):
            at_rule_start = True
        index += 1
