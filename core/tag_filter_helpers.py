# core/tag_filter_helpers.py
"""
공유 태그 필터링 헬퍼.

modules/prompt_engineering_module.py 와 ui/virtual_prompt_engineering_tab.py 에서
중복되던 필터링 로직을 통합합니다.
"""
from typing import Dict, List, Any, Optional
from collections import defaultdict

# ===================== 색상 필터링 예외 패턴 =====================
# Critical Issue: 색상 태그 필터링 문제 해결 (2025-01-20)
# 참조: .experimental/Critical_Issue_Colors.md

# 접두사 예외 (이 단어로 시작하면 색상 필터링 예외)
COLOR_EXCEPTION_PREFIXES = [
    'covered',      # covered nipples, covered eyes 등
    'shared',       # shared clothes, shared umbrella 등
    'armored',      # armored boots, armored dress 등
    'layered',      # layered sleeves, layered dress 등
    'feathered',    # feathered wings
    'colored',      # colored shadow, colored skin 등
    'multicolored', # multicolored hair 등
    'checkered',    # checkered (패턴)
    'mirrored',     # mirrored text
    'captured',     # captured (상황)
    'scared',       # scared (표정)
    'striped',      # striped (패턴, 단독 사용)
]

# 포함 예외 (이 문자열이 포함되면 색상 필터링 예외)
COLOR_EXCEPTION_CONTAINS = [
    'palette',      # turn pale이 아닌 palette
    'impaled',      # 관통됨
    'blueberry',    # 블루베리
    'blueprint',    # 청사진
    'goldfish',     # 금붕어
    'marigold',     # 금잔화
    'strawberry',   # 딸기
    'pinky out',    # 새끼손가락 포즈
    'footprints',   # 발자국
    'darkness',     # 어둠
    'dark aura',    # 어두운 기운
    'rainbow',      # 무지개
    ' fire',        # blue fire 등
    ' theme',       # blue theme 등
    ' border',      # black border 등
    ' outline',     # white outline 등
    ' gradient',    # rainbow gradient 등
    'scooping',     # goldfish scooping
]

# 정확히 일치하는 예외
COLOR_EXCEPTION_EXACT = [
    'turn pale',    # 창백해지다
    'checkered',    # 체크무늬 (단독)
    'striped',      # 줄무늬 (단독)
    'rainbow',      # 무지개
    'darkness',     # 어둠
]


def _is_color_exception(tag: str) -> bool:
    """
    색상 필터링 예외 여부를 판단합니다.

    Args:
        tag: 검사할 태그

    Returns:
        True: 예외 (필터링하지 않음)
        False: 필터링 대상
    """
    tag_lower = tag.lower()

    # 1. 정확히 일치하는 예외
    if tag_lower in COLOR_EXCEPTION_EXACT:
        return True

    # 2. 접두사 예외
    for prefix in COLOR_EXCEPTION_PREFIXES:
        if tag_lower.startswith(prefix):
            return True

    # 3. 포함 예외
    for pattern in COLOR_EXCEPTION_CONTAINS:
        if pattern in tag_lower:
            return True

    return False


# 원본 tag_conversion_map (Auto Hide에서 사용)
_ORIGINAL_TAG_CONVERSION_MAP = {
    'v': 'peace sign', 'double v': 'double peace', '|_|': 'bar eyes',
    '\\||/': 'open \\m/', ':|': 'neutral face', ';|': 'neutral face',
    'eyepatch bikini': 'square bikini', 'tachi-e': 'character image'
}
# key와 value를 바꾼 reversed map
_REVERSED_TAG_CONVERSION_MAP = {v: k for k, v in _ORIGINAL_TAG_CONVERSION_MAP.items()}


def _process_auto_hide(main_tags: List[str], removed_tags: List[str],
                        auto_hide: List[str]):
    """
    Auto Hide 처리: 직접 매칭 + 패턴 매칭으로 main_tags에서 태그 제거.
    main_tags, removed_tags를 in-place 수정.
    """
    # ~ 로 시작하는 아이템을 분리 (보호할 키워드들)
    protected_keywords = []
    for item in auto_hide:
        if item.startswith('~'):
            protected_keywords.append(item[1:].strip())

    # ~ 로 시작하는 아이템 제거
    auto_hide = [item for item in auto_hide if not item.startswith('~')]

    # auto_hide에 있는 항목이 reversed map의 key와 매칭되면, 해당 value도 추가
    additional_auto_hide = []
    for item in auto_hide:
        if item in _REVERSED_TAG_CONVERSION_MAP:
            additional_auto_hide.append(_REVERSED_TAG_CONVERSION_MAP[item])
    auto_hide = list(set(auto_hide + additional_auto_hide))

    # 직접 매칭되는 키워드 제거 (보호된 키워드는 제외)
    temp_hide_prompt = []
    for keyword in main_tags:
        if keyword in auto_hide:
            is_protected = any(protected in keyword or keyword == protected
                               for protected in protected_keywords)
            if not is_protected:
                temp_hide_prompt.append(keyword)

    for keyword in temp_hide_prompt:
        main_tags.remove(keyword)
        removed_tags.append(keyword)

    # 패턴 매칭 처리
    to_remove = []
    for item in auto_hide:
        modified_item = item
        if item.startswith("__") and item.endswith("__"):
            modified_item = modified_item.replace("_", "")
            to_remove += [keyword for keyword in main_tags if modified_item in keyword]
        elif item.startswith("_") and item.endswith("_"):
            modified_item = modified_item.replace("_", " ")
            to_remove += [keyword for keyword in main_tags if modified_item in keyword]
        elif item.startswith("_"):
            modified_item = modified_item.replace("_", " ", 1)
            to_remove += [keyword for keyword in main_tags if modified_item in keyword]
        elif item.endswith("_"):
            modified_item = " " + modified_item.rstrip("_") + " "
            to_remove += [keyword for keyword in main_tags if modified_item.strip() in keyword]

    # 보호된 키워드를 to_remove에서 제외
    to_remove = list(set(to_remove))
    if protected_keywords:
        protected_to_keep = []
        for protected in protected_keywords:
            for keyword in to_remove[:]:
                if protected in keyword or keyword == protected:
                    protected_to_keep.append(keyword)
        for protected_item in protected_to_keep:
            if protected_item in to_remove:
                to_remove.remove(protected_item)

        print(f"보호된 키워드: {', '.join(protected_to_keep) if protected_to_keep else '없음'}")

    # 조건에 맞는 키워드를 main_tags에서 제거
    for keyword in to_remove:
        if keyword in main_tags:
            main_tags.remove(keyword)
            removed_tags.append(keyword)

    print(f"Auto Hide로 제거된 태그: {', '.join(removed_tags) if removed_tags else '없음'}")


def apply_tag_filters(
    main_tags: List[str],
    removed_tags: List[str],
    checkbox_options: Dict[str, bool],
    auto_hide: List[str],
    filter_manager,
    track_clothing_regions: bool = False,
) -> Dict[str, Any]:
    """
    공통 태그 필터링 로직. main_tags, removed_tags를 in-place 수정.

    처리 순서:
    1. Auto Hide (보호 키워드 + 패턴 매칭)
    2. remove_character_features → filter_manager.characteristic_list
    3. remove_clothes → filter_manager.clothes_list (+ region 추적)
    3.5 remove_clothing_event → filter_manager._clothing_event_set (+ category 추적)
    4. remove_color → filter_manager.color_list + _is_color_exception()
    5. remove_location_and_background_color → filter_manager._location_set
    6. remove_expression (NEW) → filter_manager._expression_set
    7. remove_pose_action (NEW) → filter_manager._pose_action_set

    Args:
        main_tags: 메인 태그 리스트 (in-place 수정)
        removed_tags: 제거된 태그 리스트 (in-place 수정)
        checkbox_options: 체크박스 옵션 dict
        auto_hide: 자동 숨김 태그 리스트
        filter_manager: FilterDataManager 인스턴스 (None이면 필터 건너뜀)
        track_clothing_regions: 의류 Region 추적 여부

    Returns:
        dict: {'removed_clothes_by_region': dict} (추적 시) or {}
    """
    result = {}
    filter_log = []

    # 1. Auto Hide
    before_len = len(removed_tags)
    _process_auto_hide(main_tags, removed_tags, auto_hide)
    filter_log.append({
        'name': 'Auto Hide',
        'enabled': True,
        'removed': removed_tags[before_len:],
    })

    if not filter_manager:
        result['filter_log'] = filter_log
        return result

    # 2. remove_character_features
    enabled = checkbox_options.get("remove_character_features", False)
    before_len = len(removed_tags)
    if enabled:
        characteristics = filter_manager.characteristic_list
        temp = [keyword for keyword in main_tags if keyword in characteristics]
        for keyword in temp:
            main_tags.remove(keyword)
            removed_tags.append(keyword)
    filter_log.append({
        'name': '캐릭터 특징',
        'enabled': enabled,
        'removed': removed_tags[before_len:],
    })

    # 3. remove_clothes (+ optional region 추적)
    enabled = checkbox_options.get("remove_clothes", False)
    before_len = len(removed_tags)
    if enabled:
        clothes = filter_manager.clothes_list
        temp = [keyword for keyword in main_tags if keyword in clothes]

        if track_clothing_regions and temp:
            removed_by_region = defaultdict(list)
            for keyword in temp:
                region = filter_manager.get_clothing_region(keyword)
                removed_by_region[region].append(keyword)
            result['removed_clothes_by_region'] = dict(removed_by_region)

        for keyword in temp:
            main_tags.remove(keyword)
            removed_tags.append(keyword)
    filter_log.append({
        'name': '의류',
        'enabled': enabled,
        'removed': removed_tags[before_len:],
    })

    # 3.5 remove_clothing_event (의상 이벤트: 상태/동작)
    enabled = checkbox_options.get("remove_clothing_event", False)
    before_len = len(removed_tags)
    if enabled:
        event_set = filter_manager._clothing_event_set
        temp = [keyword for keyword in main_tags if keyword in event_set]

        if track_clothing_regions and temp:
            removed_by_category = defaultdict(list)
            for keyword in temp:
                cat = filter_manager.get_clothing_event_category(keyword) or 'unknown'
                removed_by_category[cat].append(keyword)
            result['removed_clothing_events_by_category'] = dict(removed_by_category)

        for keyword in temp:
            main_tags.remove(keyword)
            removed_tags.append(keyword)
    filter_log.append({
        'name': '의상 이벤트',
        'enabled': enabled,
        'removed': removed_tags[before_len:],
    })

    # 4. remove_color
    enabled = checkbox_options.get("remove_color", False)
    before_len = len(removed_tags)
    if enabled:
        colors = filter_manager.color_list
        temp = [keyword for keyword in main_tags
                if not _is_color_exception(keyword) and any(color in keyword for color in colors)]
        for keyword in temp:
            main_tags.remove(keyword)
            removed_tags.append(keyword)
    filter_log.append({
        'name': '색상',
        'enabled': enabled,
        'removed': removed_tags[before_len:],
    })

    # 5. remove_location_and_background_color
    enabled = checkbox_options.get("remove_location_and_background_color", False)
    before_len = len(removed_tags)
    if enabled:
        location_set = filter_manager._location_set
        temp = [keyword for keyword in main_tags if keyword in location_set]
        for keyword in temp:
            main_tags.remove(keyword)
            removed_tags.append(keyword)
    filter_log.append({
        'name': '위치/배경',
        'enabled': enabled,
        'removed': removed_tags[before_len:],
    })

    # 6. remove_expression (NEW)
    enabled = checkbox_options.get("remove_expression", False)
    before_len = len(removed_tags)
    if enabled:
        expression_set = filter_manager._expression_set
        temp = [keyword for keyword in main_tags if keyword in expression_set]
        for keyword in temp:
            main_tags.remove(keyword)
            removed_tags.append(keyword)
    filter_log.append({
        'name': '표정',
        'enabled': enabled,
        'removed': removed_tags[before_len:],
    })

    # 7. remove_pose_action (NEW)
    enabled = checkbox_options.get("remove_pose_action", False)
    before_len = len(removed_tags)
    if enabled:
        pose_action_set = filter_manager._pose_action_set
        temp = [keyword for keyword in main_tags if keyword in pose_action_set]
        for keyword in temp:
            main_tags.remove(keyword)
            removed_tags.append(keyword)
    filter_log.append({
        'name': '포즈/동작',
        'enabled': enabled,
        'removed': removed_tags[before_len:],
    })

    # 8. remove_meta_tags (메타 태그 제거)
    enabled = checkbox_options.get("remove_meta_tags", False)
    before_len = len(removed_tags)
    if enabled:
        meta_set = filter_manager._meta_set
        temp = [keyword for keyword in main_tags if keyword in meta_set]
        for keyword in temp:
            main_tags.remove(keyword)
            removed_tags.append(keyword)
    filter_log.append({
        'name': '메타',
        'enabled': enabled,
        'removed': removed_tags[before_len:],
    })

    # 9. remove_object_tags (사물 태그 제거)
    enabled = checkbox_options.get("remove_object_tags", False)
    before_len = len(removed_tags)
    if enabled:
        object_set = filter_manager._object_set
        temp = [keyword for keyword in main_tags if keyword in object_set]
        for keyword in temp:
            main_tags.remove(keyword)
            removed_tags.append(keyword)
    filter_log.append({
        'name': '사물',
        'enabled': enabled,
        'removed': removed_tags[before_len:],
    })

    # 10. remove_noise_tags (저빈도 태그 제거)
    enabled = checkbox_options.get("remove_noise_tags", False)
    before_len = len(removed_tags)
    if enabled:
        filtered = filter_manager.filter_noise_tags(main_tags)
        removed = [t for t in main_tags if t not in set(filtered)]
        main_tags[:] = filtered
        removed_tags.extend(removed)
    filter_log.append({
        'name': '노이즈 태그',
        'enabled': enabled,
        'removed': removed_tags[before_len:],
    })

    result['filter_log'] = filter_log
    return result
