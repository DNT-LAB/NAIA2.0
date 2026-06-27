"""Pure (Qt-free, AppContext-free) image classification rule engine.

이 모듈은 ``core/image_crud_controller.py`` (데스크톱 전용, 헤드리스 경로에서는 호출되지
않는 죽은 컨트롤러)에 들어 있던 프롬프트-인식 분류 규칙 엔진을 **의미를 한 글자도 바꾸지
않고** 추출한 것이다. 헤드리스/포터블 자동 저장 경로(``core/headless_save_service.py``)가
이 엔진을 직접 호출해, 사용자가 UI에서 고른 "분류 방식 + 규칙"을 실제 디스크 하위 폴더로
반영한다.

DSL 의미(데스크톱과 동일):
  * ``*tag``      : 퍼펙트 매칭 — ``tag`` 가 태그 리스트에 **정확히** 존재해야 True
  * ``tag``       : 포함 검사 — 어떤 태그 요소든 ``tag`` 를 부분 문자열로 포함하면 True
  * ``&``         : AND (괄호 밖에서만 분할)
  * ``|``         : OR  (괄호 밖에서만 분할)
  * ``()``        : 그룹핑(중첩 가능)
  * 쉼표(``,``)   : 규칙 구분 — **순서가 곧 우선순위**, 처음 만족하는 규칙이 채택됨
  * 미매칭        : ``"misc"`` 폴더로 분류(폴백)

폴더명 변환(``condition_to_folder_name``):
  * ``()`` 제거, ``&`` → ``_and_``, ``|`` → ``_or_``, ``*`` 제거, 공백 → ``_``,
    그 외 파일시스템 비안전 문자 제거(``[^\\w_-]``), 빈 문자열이면 ``"misc"``.

2차(secondary) 분류:
  * 1차 규칙이 채택되면, 해당 1차 폴더명에 대응하는 2차 규칙 문자열을 같은 엔진으로 평가해
    ``primary/secondary`` 경로를 만든다. 2차가 미매칭(None)이면 1차 폴더만 사용한다.

반환:
  * ``classify(...)`` 는 분류 하위 폴더 경로 문자열(예: ``"1girl"``, ``"solo_and_1girl"``,
    ``"1girl/solo"``, 또는 폴백 ``"misc"``)을 돌려준다. 분류를 끄거나(method가 "none"/빈값)
    알 수 없는 method면 ``None`` 을 돌려준다(= 하위 폴더 없음).

원본 코드와의 차이는 **로깅 부재**(print 호출 제거)뿐이며 분기/판정 로직은 동일하다.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Mapping, Optional


__all__ = [
    "classify",
    "classify_by_prompt",
    "condition_to_folder_name",
    "evaluate_condition",
    "split_rules",
]


def split_rules(rules_text: str) -> List[str]:
    """쉼표로 구분된 분류 규칙을 리스트로 분리합니다.

    "*1girl, (*solo&*1girl), (landscape|scenery)"
        -> ["*1girl", "(*solo&*1girl)", "(landscape|scenery)"]
    """
    if not rules_text:
        return []
    # 쉼표로 분리하고 공백 제거
    return [rule.strip() for rule in rules_text.split(',') if rule.strip()]


def condition_to_folder_name(condition_text: str) -> str:
    """조건 텍스트를 폴더명으로 변환합니다.

    규칙:
    - 괄호 () 제거
    - & -> _and_
    - | -> _or_
    - * 제거 (퍼펙트 매칭 표시)
    - 공백 -> _ (언더스코어)
    - 파일시스템에 안전하지 않은 문자 제거
    """
    folder_name = condition_text.strip()

    # 괄호 제거
    folder_name = folder_name.replace('(', '').replace(')', '')

    # 논리 연산자 치환
    folder_name = folder_name.replace('&', '_and_')
    folder_name = folder_name.replace('|', '_or_')

    # * 제거 (퍼펙트 매칭 표시)
    folder_name = folder_name.replace('*', '')

    # 공백 -> 언더스코어
    folder_name = folder_name.replace(' ', '_')

    # 파일시스템에 안전한 문자만 유지 (알파벳, 숫자, _, -)
    folder_name = re.sub(r'[^\w_-]', '', folder_name)

    # 빈 문자열 방지
    if not folder_name:
        folder_name = "misc"

    return folder_name


def _matching_paren(s: str, start: int) -> int:
    """시작 괄호의 짝을 찾습니다. 못 찾으면 -1."""
    depth = 1
    for i in range(start + 1, len(s)):
        if s[i] == '(':
            depth += 1
        elif s[i] == ')':
            depth -= 1
            if depth == 0:
                return i
    return -1


def _split_by_operator(expression: str, operator: str) -> List[str]:
    """괄호 밖의 연산자로만 분할합니다. 분할이 없으면 [expression]."""
    parts: List[str] = []
    current = ""
    depth = 0

    for char in expression:
        if char == '(':
            depth += 1
            current += char
        elif char == ')':
            depth -= 1
            current += char
        elif char == operator and depth == 0:
            # 괄호 밖의 연산자
            parts.append(current.strip())
            current = ""
        else:
            current += char

    if current.strip():
        parts.append(current.strip())

    return parts if len(parts) > 1 else [expression]


def _evaluate_single_condition(condition: str, tags: List[str]) -> bool:
    """단일 조건을 평가합니다.

    - *tag: 정확 일치 (퍼펙트 매칭)
    - tag : 포함 검사 (부분 일치)
    """
    condition = condition.strip()

    if condition.startswith('*'):
        # 퍼펙트 매칭: 정확 일치
        tag = condition[1:].strip()
        return tag in tags
    # 포함 검사: 부분 일치
    return any(condition in element for element in tags)


def _evaluate_logical_expression(expression: str, tags: List[str]) -> bool:
    """논리 표현식을 평가합니다 (AND, OR, 중첩 괄호 지원)."""
    expression = expression.strip()

    if not expression:
        return True

    # 최외곽 괄호 제거 (매칭되는 경우만)
    while expression.startswith('(') and expression.endswith(')'):
        matching_index = _matching_paren(expression, 0)
        if matching_index == len(expression) - 1:
            expression = expression[1:-1].strip()
        else:
            break

    # AND 연산자 분할 (괄호 밖에서만)
    and_parts = _split_by_operator(expression, '&')
    if len(and_parts) > 1:
        # 모든 부분이 True여야 함
        return all(_evaluate_logical_expression(part, tags) for part in and_parts)

    # OR 연산자 분할 (괄호 밖에서만)
    or_parts = _split_by_operator(expression, '|')
    if len(or_parts) > 1:
        # 하나라도 True이면 됨
        return any(_evaluate_logical_expression(part, tags) for part in or_parts)

    # 단일 조건 평가
    return _evaluate_single_condition(expression, tags)


def evaluate_condition(condition: str, tags: List[str]) -> bool:
    """분류 조건 하나를 평가합니다 (단일 조건 또는 논리 표현식)."""
    condition = condition.strip()

    # 논리 연산자 포함 여부 확인
    if '&' in condition or '|' in condition:
        return _evaluate_logical_expression(condition, tags)

    # 단일 조건 평가
    return _evaluate_single_condition(condition, tags)


def _apply_secondary_classification(
    secondary_rules_text: str,
    tags: List[str],
) -> Optional[str]:
    """2차 분류 규칙을 적용하여 서브폴더명을 반환합니다(미매칭 시 None)."""
    if not secondary_rules_text or not tags:
        return None

    secondary_rules = split_rules(secondary_rules_text)

    # 순차적으로 조건 평가
    for rule in secondary_rules:
        try:
            if evaluate_condition(rule, tags):
                return condition_to_folder_name(rule)
        except Exception:
            continue

    # 2차 규칙 모두 불만족 시 None 반환 (1차 폴더만 사용)
    return None


# 가중치/강조 구문 제거용(분류 매칭 정규화). prompt_processor.py:664-667 과 동일 순서/패턴.
_CLS_WEIGHT_LEAD_RE = re.compile(r'^\d+\.?\d*::')   # 선행 "0.7::"
_CLS_WEIGHT_TRAIL_RE = re.compile(r'\s*::$')         # 후행 " ::"
_CLS_BRACKET_RE = re.compile(r'[{}\[\]()]')          # 괄호류 (){}[]
_CLS_LOCAL_WEIGHT_RE = re.compile(r':\d+\.?\d*')     # ":1.2" 등


def _strip_weight_syntax(token: str) -> str:
    """NAI/로컬 가중치·강조 구문을 떼어 순수 태그명만 남긴다(분류 매칭용).

    예) '0.7::1girl ::' → '1girl', '1.2::artist:ciloranko ::' → 'artist:ciloranko',
        '(masterpiece:1.2)' → 'masterpiece', '[tag]' → 'tag'.
    이 정규화가 없으면 실행 프롬프트의 가중치 토큰에 '*tag'(exact)가 매칭되지 않아 조용히
    misc 로 오분류된다(사용성 분석 결과).
    """
    text = _CLS_WEIGHT_LEAD_RE.sub('', token)
    text = _CLS_WEIGHT_TRAIL_RE.sub('', text)
    text = _CLS_BRACKET_RE.sub('', text)
    text = _CLS_LOCAL_WEIGHT_RE.sub('', text)
    return text.strip()


def _coerce_tags(tags: "Iterable[str] | str | None") -> List[str]:
    """태그를 리스트 형태로 정규화합니다(+가중치/강조 구문 제거).

    - 문자열이면 쉼표로 분리(``<...>`` 블록 내부 콤마는 보존)한다.
    - 이미 리스트/이터러블이면 각 원소를 문자열화한다.
    - 모든 토큰에서 가중치/강조 구문을 떼어 순수 태그명으로 만든다(_strip_weight_syntax) —
      실행 프롬프트(예: ``0.7::1girl ::``)에서도 exact(``*tag``)/contains 매칭이 동작하게 한다.

    엔진의 비교(``tag in tags`` / ``cond in element``)는 정규화된 태그 리스트를 전제로 한다.
    """
    if tags is None:
        return []
    if isinstance(tags, str):
        # 와일드카드/프롬프트 문자열과 동일한 분리 규칙 사용(<...> 내부 콤마 보존).
        from core.wildcard_processor import split_tags_smart

        raw = [tag.strip() for tag in split_tags_smart(tags) if tag.strip()]
    else:
        raw = [str(tag).strip() for tag in tags if str(tag).strip()]
    result: List[str] = []
    for token in raw:
        normalized = _strip_weight_syntax(token)
        if normalized:
            result.append(normalized)
    return result


def classify_by_prompt(
    tags: "Iterable[str] | str | None",
    rules: str,
    *,
    secondary_enabled: bool = False,
    secondary_method: str = "none",
    secondary_rules: "Optional[Mapping[str, str]]" = None,
) -> str:
    """프롬프트 규칙에 따라 분류 폴더명을 반환합니다(미매칭/빈입력 시 "misc").

    작동 방식(데스크톱 ``_classify_by_prompt`` 동일):
    1. rules를 쉼표로 분리
    2. 각 규칙을 순서대로 평가
    3. 첫 번째 만족하는 규칙의 폴더명 반환(+필요 시 2차 분류 ``primary/secondary``)
    4. 모두 만족하지 않으면 "misc" 반환
    """
    # 규칙이 없으면 misc
    if not rules:
        return "misc"

    tag_list = _coerce_tags(tags)
    if not tag_list:
        return "misc"

    parsed_rules = split_rules(rules)
    secondary_rules = secondary_rules or {}

    # 순차적으로 조건 평가
    for rule in parsed_rules:
        try:
            if evaluate_condition(rule, tag_list):
                primary_folder_name = condition_to_folder_name(rule)

                # 2차 분류 적용 (데스크톱과 동일 게이트)
                if (
                    secondary_enabled
                    and secondary_method == "prompt_recognition"
                    and primary_folder_name in secondary_rules
                ):
                    secondary_rules_text = secondary_rules[primary_folder_name]
                    if secondary_rules_text.strip():
                        secondary_folder = _apply_secondary_classification(
                            secondary_rules_text, tag_list
                        )
                        if secondary_folder and secondary_folder != "misc":
                            return f"{primary_folder_name}/{secondary_folder}"

                return primary_folder_name
        except Exception:
            continue

    # 모든 규칙 불만족 시 misc
    return "misc"


def classify(
    tags: "Iterable[str] | str | None",
    method: str,
    rules: str,
    *,
    secondary_enabled: bool = False,
    secondary_method: str = "none",
    secondary_rules: "Optional[Mapping[str, str]]" = None,
) -> Optional[str]:
    """분류 방식/규칙으로부터 저장 하위 폴더 경로를 결정합니다.

    데스크톱 ``_get_classified_directory`` + ``_classify_by_prompt`` 의 합성:

    Parameters:
        tags: 태그 리스트 또는 콤마 구분 프롬프트 문자열(None 허용).
        method: "none" | "prompt_recognition" (그 외 값은 분류 안 함 = None).
        rules: 쉼표 구분 규칙 문자열.
        secondary_*: 2차 분류 옵션(헤드리스 기본 저장 경로에서는 미사용).

    Returns:
        str: 하위 폴더 경로(예: "1girl", "1girl/solo", 폴백 "misc").
        None: 분류 비활성("none"/빈값) 또는 알 수 없는 method.
    """
    method = str(method or "none")

    if method == "none":
        return None

    if method == "prompt_recognition":
        return classify_by_prompt(
            tags,
            rules,
            secondary_enabled=secondary_enabled,
            secondary_method=secondary_method,
            secondary_rules=secondary_rules,
        )

    return None
