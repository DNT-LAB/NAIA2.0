# -*- coding: utf-8 -*-
"""인원 그룹 판정 - 13그룹.

목록의 SSOT 는 `core/event_preset/engines.py` 의 `PERSON_PARTITION_ORDER` 이고,
판정 규칙의 SSOT 는 `core/preset_input_bridge.py:_infer_person_id_from_prompt` 다.
여기서 규칙을 다시 적는 이유는 두 가지다:

1. 빌더는 700만 게시물을 훑으므로 프롬프트 파싱 계층(정규식 split, 속성 접근)을
   태우면 안 된다. 입력이 이미 정규화된 태그 집합이다.
2. 그 함수는 아무 인원 서명도 못 찾으면 **`""` 를 반환한다**(`:322`). 그런데
   그룹 목록에는 `other` 가 따로 있다. 그대로 쓰면 14번째 유령 버킷이 생기거나
   그 게시물이 사라진다 - 실측으로 `other` 는 283,386건(3.8%)이라 무시 못 한다.
   여기서는 `other` 로 명시해 접는다.

**규칙을 바꿀 때는 위 두 SSOT 와 같이 바꿔야 한다.** 갈라지면 같은 인원 설정에서
프리셋과 조합 추천이 다른 모델을 본다.
"""

from __future__ import annotations

from typing import Iterable

# `core/event_preset/engines.py:44-49` 와 같은 순서.
PERSON_GROUPS: tuple[str, ...] = (
    "1girl_solo", "1girl", "1girl_1boy", "1girl_multiple_boys",
    "2girls", "multiple_girls", "1boy_solo", "1boy",
    "1boy_multiple_girls", "2boys", "multiple_boys",
    "multiple_girls_multiple_boys", "other",
)


def person_group_of(tags: Iterable[str]) -> str:
    """태그 집합 -> 인원 그룹. 우선순위 사슬은 preset_input_bridge 와 동일하다.

    혼성이 동성보다 먼저 걸리고, `1girl`/`1boy` 는 잔여 버킷이다. 아무것도 안
    걸리면 `other` 다(원본은 `""` 를 반환한다 - 모듈 독스트링 참조).
    """
    s = tags if isinstance(tags, (set, frozenset)) else set(tags)
    if "multiple girls multiple boys" in s or {"multiple girls", "multiple boys"} <= s:
        return "multiple_girls_multiple_boys"
    if {"1girl", "multiple boys"} <= s:
        return "1girl_multiple_boys"
    if {"1boy", "multiple girls"} <= s:
        return "1boy_multiple_girls"
    if {"1girl", "1boy"} <= s:
        return "1girl_1boy"
    if "2girls" in s:
        return "2girls"
    if "2boys" in s:
        return "2boys"
    if "multiple girls" in s:
        return "multiple_girls"
    if "multiple boys" in s:
        return "multiple_boys"
    if {"1girl", "solo"} <= s:
        return "1girl_solo"
    if {"1boy", "solo"} <= s:
        return "1boy_solo"
    if "1girl" in s:
        return "1girl"
    if "1boy" in s:
        return "1boy"
    return "other"
