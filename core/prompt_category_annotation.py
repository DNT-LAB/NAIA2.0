# -*- coding: utf-8 -*-
"""Category Annotation — 랜덤 프롬프트를 카테고리 주석과 함께 줄 단위로 펼친다.

사용자 요청 2026-08-31:
  "랜덤이 작동할 때, 메인 프롬프트에 전달하는 프롬프트를 기존 `#랜덤프롬프트,` 대신
   라인 단위로 다음 주석을 삽입합니다. 공란인 경우 주석도 출력하지 않습니다."

끄면 예전 그대로 `#랜덤프롬프트` 한 줄이다.

⚠️ 작품·캐릭터·아티스트에는 **주석을 안 단다**(사용자 회수 2026-08-31:
   "칸만 차지하네요"). 값이 한 줄인데 주석이 두 줄을 먹었고, 특히 `#아티스트:` 는
   바로 뒤에 오는 선행고정 와일드카드와 붙어 그것들이 아티스트인 것처럼 읽혔다.
   그 셋은 예전 그대로 선행고정 프롬프트 머리에 꽂힌다 - 배치도 순서도 안 바뀐다.

## 왜 이렇게 되는가

`_step_final_format` 은 `#` 로 시작하는 태그를 `\\n{tag}\\n` 으로 감싸 **자기 줄**로
내보내고, 생성 직전에는 여러 소비 지점이 `startswith('#')` 로 일괄 제거한다
(`api_service` · `comfyui_workflow_manager` · `headless_generation_service` ·
`headless_v5_scene_service` · `v5_scene_store`). 그래서 주석을 몇 줄로 늘려도
API 로는 한 줄도 나가지 않는다 - 기존 `#랜덤프롬프트` 가 쓰던 바로 그 통로다.

## 색상은 왜 카테고리가 아닌가

`color.txt` 는 **37개짜리 낱말 사전**(`black` · `blue` · `striped` …)이고,
`remove_color` 만 유일하게 **부분일치**(`any(color in keyword ...)`)로 쓴다. 나머지
여덟 라운드는 전부 정확일치다. 색이 든 태그는 이미 제 집이 있다(실측 2026-08-31):

    특징 3,376개 중 462개 · 의상 11,091개 중 2,709개 · 사물 4,541개 중 281개 …
    (`aqua eyes` -> 특징, `american flag bikini` -> 의상)

그래서 `#색상:` 버킷을 두지 않는다.

## 겹치면 앞선 카테고리가 이긴다

한 태그가 여러 세트에 드는 경우가 있다(실측: 의상∩의상이벤트 120 · 의상∩포즈 72 ·
특징∩의상 52). 우선순위는 아래 나열 순서, 즉 **사용자가 적어 준 순서**다.
결과가 맞는 것을 표본으로 확인했다: `halo`->특징 · `apron`->의상 · `arm armor`->의상.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

# 본문. **나열 순서가 곧 분류 우선순위**다.
EXTRA_KEY = "extra"
MAIN_CATEGORY_ORDER: tuple[tuple[str, str, str], ...] = (
    # (키, 주석, filter_manager 속성)
    ("features", "#특징:", "characteristic_list"),
    ("clothes", "#의상:", "clothes_list"),
    ("clothing_event", "#의상 이벤트:", "_clothing_event_set"),
    ("expression", "#표정:", "_expression_set"),
    ("pose_action", "#포즈/동작:", "_pose_action_set"),
    ("object", "#사물:", "_object_set"),
    ("location", "#위치/배경:", "_location_set"),
    ("meta", "#메타:", "_meta_set"),
    # 어디에도 안 걸린 것 - e621 Auto-Boost 가 붙인 태그도 여기로 온다(세트에 없다).
    (EXTRA_KEY, "#추가:", ""),
)

LEGACY_MAIN_MARKER = "#랜덤프롬프트"

# 프롬프트 문자열에서 **본문이 시작하는 자리**를 찾는 표식들.
MAIN_BLOCK_MARKERS: tuple[str, ...] = tuple(
    marker for _, marker, _ in MAIN_CATEGORY_ORDER
) + (LEGACY_MAIN_MARKER,)

PARAGRAPH_BREAK = "\n\n"

_WEBUI_WEIGHT_RE = re.compile(r"^\((.*):\s*-?\d+(?:\.\d+)?\)$")
# 여러 태그를 감싸는 NAI 가중치 그룹의 **여는 쪽**: `0.8::tag`
_NAI_WEIGHT_OPEN_RE = re.compile(r"^-?\d+(?:\.\d+)?::")


def find_main_block_start(prompt: str) -> int:
    """최종 문자열에서 **본문(랜덤 프롬프트)이 시작하는 자리**. 없으면 -1.

    ⚠️ 예전에는 `#랜덤프롬프트` 하나만 찾으면 됐다. 주석을 켜면 그 표식이 사라지고
       카테고리 표식들로 갈리므로, **가장 먼저 나오는 본문 표식**을 찾아야 한다.
       한 곳만 고치면 나머지가 조용히 옛 답을 낸다.
    """
    if not prompt:
        return -1
    found = [at for at in (prompt.find(m) for m in MAIN_BLOCK_MARKERS) if at >= 0]
    return min(found) if found else -1


def match_key(tag: Any) -> str:
    """세트 조회용으로 태그를 벗긴다.

    ⚠️ 이 단계는 Danbooru Auto-Weight(post_processing) **뒤**라 태그에 가중치가
       이미 붙어 있다. 안 벗기면 `0.8::solo ::` 가 어느 세트에도 안 걸려 전부
       `#추가:` 로 쏟아진다.
    """
    if not isinstance(tag, str):
        return ""
    value = tag.strip()
    if not value:
        return ""

    # NAI: `0.8::tag ::`
    while value.endswith("::"):
        value = value[:-2].rstrip()
    separator = value.find("::")
    if separator > 0:
        head = value[:separator].strip()
        try:
            float(head)
            value = value[separator + 2:].lstrip()
        except ValueError:
            pass

    # WEBUI/ComfyUI: `(tag:1.2)` · e621 그룹: `(tag`
    matched = _WEBUI_WEIGHT_RE.match(value)
    if matched:
        value = matched.group(1).strip()

    # e621 Auto-Boost 는 구간을 `(` `)` 로 묶는다 - 그 **그룹 괄호만** 벗긴다.
    # ⚠️ 이스케이프된 괄호는 태그의 일부다(`hakurei reimu \(cosplay\)`).
    #    `strip("()")` 로 한꺼번에 벗기면 닫는 `\)` 의 `)` 만 뜯겨 백슬래시가 남고,
    #    그 태그는 어느 세트에도 안 걸려 통째로 `#추가:` 로 떨어진다.
    # ⚠️ **짝이 맞지 않을 때만** 벗긴다. 그냥 벗기면 `1930s (style)` ·
    #    `female byleth (fire emblem)` 처럼 괄호가 이름의 일부인 태그의 닫는 괄호를
    #    뜯어 세트 조회가 통째로 실패한다(실측 2026-08-31: 그래서 `1930s (style)` 이
    #    메타에 있는데도 `#추가:` 로 떨어졌다).
    while value.startswith("(") and value.count("(") > value.count(")"):
        value = value[1:].lstrip()
    while (value.endswith(")") and not value.endswith(r"\)")
           and value.count(")") > value.count("(")):
        value = value[:-1].rstrip()

    # non-NAI 는 리터럴 괄호를 이스케이프해 둔다 - 되돌려야 세트와 맞는다.
    value = value.replace(r"\(", "(").replace(r"\)", ")")
    return value.strip().lower()


def _opens_group(token: str) -> bool:
    """이 토큰이 **여러 태그를 감싸는** 가중치 그룹을 여는가.

    e621 Auto-Boost 는 추천 묶음을 하나의 그룹으로 감싼다
    (`headless_prompt_boost_service`): 첫 태그에 여는 쪽, **마지막 태그**에 닫는 쪽.

        non-NAI : `(satisfied` ... `panting:0.8)`
        NAI     : `0.8::satisfied` ... `panting ::`

    ⚠️ `0.83::open clothes ::` 처럼 **한 토큰 안에서 닫히는** 것은 그룹이 아니다
       (Danbooru Auto-Weight 가 태그마다 붙인다).
    """
    value = token.strip()
    if not value:
        return False
    if value.count("(") > value.count(")"):
        return True
    match = _NAI_WEIGHT_OPEN_RE.match(value)
    return bool(match) and not value.endswith("::")


def _closes_group(token: str) -> bool:
    value = token.strip()
    if not value:
        return False
    if value.count(")") > value.count("("):
        return True
    return value.endswith("::") and not _NAI_WEIGHT_OPEN_RE.match(value)


def _group_units(tags: list) -> list:
    """토큰을 **원자 단위**로 묶는다. 보통은 한 개짜리, 그룹이면 그 전체.

    ⚠️ 안 묶으면 카테고리로 재배치하면서 그룹의 여는 쪽과 닫는 쪽이 갈라지고,
       **사이에 낀 남의 태그가 그 가중치를 뒤집어쓴다.** 실측 2026-08-31:
       `(satisfied, panting:0.8)` + 그룹 밖 `sitting` ->
       `(satisfied, sitting, panting:0.8)` (부스트한 적 없는 sitting 이 0.8 을 먹는다).
    """
    units: list[list] = []
    index = 0
    total = len(tags)
    while index < total:
        token = tags[index]
        if _opens_group(token) and not _closes_group(token):
            run = [token]
            index += 1
            while index < total:
                run.append(tags[index])
                closed = _closes_group(tags[index])
                index += 1
                if closed:
                    break
            units.append(run)
            continue
        units.append([token])
        index += 1
    return units


def _category_sets(filter_manager: Any) -> dict[str, frozenset]:
    """카테고리별 조회 세트. filter_manager 인스턴스에 한 번만 만들어 붙인다.

    ⚠️ `characteristic_list`/`clothes_list` 는 **list** 라 `in` 이 선형 탐색이다
       (의상만 11,091개). 매 생성마다 훑으면 느리다 - frozenset 으로 굳힌다.
    """
    cached = getattr(filter_manager, "_category_annotation_sets", None)
    if isinstance(cached, dict):
        return cached

    built: dict[str, frozenset] = {}
    for key, _marker, attribute in MAIN_CATEGORY_ORDER:
        if not attribute:
            continue
        raw = getattr(filter_manager, attribute, None)
        if not raw:
            continue
        built[key] = frozenset(
            str(tag).strip().lower() for tag in raw if isinstance(tag, str) and tag.strip()
        )
    try:
        setattr(filter_manager, "_category_annotation_sets", built)
    except Exception:
        pass
    return built


def classify(tag: Any, category_sets: dict[str, frozenset]) -> str:
    """태그 하나의 카테고리 키. 어디에도 없으면 `extra`."""
    key = match_key(tag)
    if not key:
        return EXTRA_KEY
    for category, _marker, attribute in MAIN_CATEGORY_ORDER:
        if not attribute:
            continue
        if key in category_sets.get(category, frozenset()):
            return category
    return EXTRA_KEY


def build_annotated_main_tags(tags: Iterable[Any], filter_manager: Any) -> list[str]:
    """본문 태그를 카테고리로 묶고 그 앞에 주석을 꽂는다.

    카테고리 안에서는 **원래 순서를 지킨다**. 빈 카테고리는 주석도 안 낸다.
    """
    ordered = [tag for tag in tags if isinstance(tag, str) and tag.strip()]
    if not ordered:
        return []

    category_sets = _category_sets(filter_manager) if filter_manager else {}
    buckets: dict[str, list[str]] = {key: [] for key, _m, _a in MAIN_CATEGORY_ORDER}
    for unit in _group_units(ordered):
        if len(unit) > 1:
            # 여러 태그를 감싼 가중치 그룹은 **쪼개지 않는다.** 어느 카테고리에도
            # 온전히 속하지 않으므로 `#추가:` 에 통째로 둔다 - 사용자 사양에서도
            # e621 은 추가 뒤에 붙는다.
            buckets[EXTRA_KEY].extend(unit)
            continue
        buckets[classify(unit[0], category_sets)].append(unit[0])

    result: list[str] = []
    for key, marker, _attribute in MAIN_CATEGORY_ORDER:
        if buckets[key]:
            result.append(marker)
            result.extend(buckets[key])
    return result
