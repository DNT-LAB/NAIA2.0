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


def _norm_tag(tag: Any) -> str:
    """카테고리 오버라이드 비교용 정규화 (strip + lower). 사전 태그가 소문자
    관례이므로 대소문자·주변 공백만 무시하고 저장값 원형은 보존한다."""
    return str(tag or "").strip().lower()


def _pattern_norm(value: Any) -> str:
    """패턴 매칭용 정규화 — lower만(strip 금지). ``_x_``/``_x``/``x_`` 의 경계
    공백은 needle 안에 유지돼야 __x__(단순 포함)과 구분되므로 strip 하지 않는다."""
    return str(value or "").lower()


def compile_hide_pattern(item, *, normalize=None):
    """Auto-Hide 스타일 묶음 문법을 substring 매처(predicate)로 컴파일.

    반환 None = plain(정확일치 대상), 아니면 keyword -> bool predicate.

    관대한 일반화 규칙 (2026-07-24, 사용자 결정 — 밑줄 개수를 외울 필요 없게):
      - 감싸면(앞뒤 모두, 개수 무관: ``__x__``/``_x_``/``__x_``/``_x__``) : 포함 매치
      - 앞에만(개수 무관: ``_x``/``__x``) : " x" — 앞에 공백이 오는 단어 경계 매치
      - 뒤에만(개수 무관: ``x_``/``x__``) : 포함 매치
      - 밑줄 없음 : None (plain, 정확일치)
      - 중간 밑줄은 공백으로 취급 (``__blue_eyes__`` = "blue eyes" 포함 —
        Danbooru 표기 복붙 호환. 앞뒤 밑줄이 전혀 없으면 plain 그대로)
      - 심(core)이 비면 None (``____`` 가 전체 매치로 폭주하던 기존 결함 차단)

    normalize 가 주어지면 needle 과 대상 keyword 양쪽에 적용해 비교한다(카테고리
    오버라이드는 lower 기준). 미지정(None) 시 원형 그대로 비교(auto-hide, 대소문자
    구분)."""
    if not isinstance(item, str):
        return None
    stripped_lead = item.lstrip("_")
    lead = len(item) - len(stripped_lead)
    core = stripped_lead.rstrip("_")
    trail = len(stripped_lead) - len(core)
    if lead == 0 and trail == 0:
        return None
    # 심이 비면(밑줄만) 빈 needle -> 전체 매치가 되므로 차단.
    if not core.strip():
        return None
    needle = core.replace("_", " ")
    if lead > 0 and trail == 0:
        needle = " " + needle
    if normalize is None:
        return lambda keyword: needle in keyword
    needle_n = normalize(needle)
    if not needle_n.strip():
        return None
    return lambda keyword: needle_n in normalize(keyword)


def _parse_override_terms(items):
    """오버라이드 항목 리스트를 (exact_set, pattern_predicates)로 분리.

    Auto-Hide 묶음 문법이면 패턴 predicate, 아니면 정규화 정확일치 set.
    ``~text`` 는 카테고리에서 특수 의미가 없어 plain(정확일치)로 취급된다
    (밑줄 패턴이 아니므로 compile_hide_pattern 이 None -> exact)."""
    exact = set()
    preds = []
    for raw in (items or []):
        text = str(raw or "")
        if not text.strip():
            continue
        pred = compile_hide_pattern(text, normalize=_pattern_norm)
        if pred is not None:
            preds.append(pred)
        else:
            exact.add(_norm_tag(text))
    return exact, preds


def _override_sets(category_overrides, option_key):
    """해당 라운드(option_key)의 (exclude, include) 를 반환.

    각각 (exact_set, pattern_predicates) 튜플. 오버라이드 없으면 빈 형태.
    (하위 라운드는 이 튜플을 그대로 _apply_round_overrides 에 전달만 한다.)"""
    entry = (category_overrides or {}).get(option_key) if isinstance(category_overrides, dict) else None
    if not isinstance(entry, dict):
        return (set(), []), (set(), [])
    exclude = _parse_override_terms(entry.get("exclude"))
    include = _parse_override_terms(entry.get("include"))
    return exclude, include


def _matches_terms(keyword, terms):
    """keyword 가 (exact_set, predicates) 에 정확일치 또는 패턴 매치하면 True."""
    exact, preds = terms
    if _norm_tag(keyword) in exact:
        return True
    return any(pred(keyword) for pred in preds)


def _terms_empty(terms):
    exact, preds = terms
    return not exact and not preds


def _apply_round_overrides(temp, main_tags, exclude, include):
    """정확일치/부분일치 라운드의 제거 후보(temp)에 exclude/include 오버라이드를 적용.

    exclude/include 는 각각 (exact_set, pattern_predicates).
    - exclude: temp 에서 정확일치 ∪ 패턴 매치하는 태그를 보호(제거하지 않음).
    - include: main_tags 중 정확일치·패턴 매치하는 태그를 추가 제거 대상으로 편입.
    우선순위: exclude(모든 형태) > include(모든 형태).
    반환 순서는 원래 temp 순서 뒤에 include 추가분을 잇는다."""
    if _terms_empty(exclude) and _terms_empty(include):
        return temp
    result = [k for k in temp if not _matches_terms(k, exclude)]
    if not _terms_empty(include):
        scheduled = {_norm_tag(k) for k in result}
        for keyword in main_tags:
            nk = _norm_tag(keyword)
            if nk in scheduled:
                continue
            if _matches_terms(keyword, exclude):
                continue  # exclude 우선
            if _matches_terms(keyword, include):
                result.append(keyword)
                scheduled.add(nk)
    return result


def _apply_category_hide(main_tags, removed_tags, category_overrides):
    """개별 숨김 - 카테고리별 `hide` 목록을 **라운드 스위치와 무관하게** 적용한다.

    ⚠️ 왜 include 로 안 하는가: include 는 `if enabled:` 안에서만 돈다. 그런데
       사전에 있는 태그는 그 라운드가 켜지면 **어차피** 지워지므로, 사전 태그에
       대한 include 는 언제나 no-op 다(실측 2026-08-31: remove_clothes OFF ->
       swimsuit 남음 / ON -> 의상 전체 사라짐. 두 경우 다 include 가 한 일이 없다).
       우클릭 '자동 숨김 (랜덤 프롬프트 - 의상)' 은 **그 태그 하나만** 지워야 하고,
       사용자는 라운드를 켜지 않는다(실측: 사용자 설정의 remove_* 는 전부 OFF).
       그래서 스위치를 안 보는 목록이 따로 필요하다.

    exclude(보호)가 hide 를 이긴다 - 기존 우선순위(exclude > include)와 같은 방향이라,
    미리보기에서 지워진 칩을 눌러 exclude 에 넣는 동작이 그대로 '되돌리기'가 된다.
    """
    if not isinstance(category_overrides, dict) or not category_overrides:
        return
    # 화이트리스트를 다시 들지 않고 맵 자신을 돈다 - 로더가 이미 정규화한 SSOT 라,
    # 여기서 키 목록을 한 벌 더 들면 카테고리가 늘 때 두 곳이 어긋난다.
    for _option_key, entry in category_overrides.items():
        if not isinstance(entry, dict):
            continue
        hide = _parse_override_terms(entry.get('hide'))
        if _terms_empty(hide):
            continue
        exclude = _parse_override_terms(entry.get('exclude'))
        # 리스트를 돌면서 지우면 인덱스가 밀린다 - 지울 것을 먼저 모은다.
        doomed = [k for k in main_tags
                  if _matches_terms(k, hide) and not _matches_terms(k, exclude)]
        for keyword in doomed:
            main_tags.remove(keyword)
            removed_tags.append(keyword)

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

    # 패턴 매칭 처리 — compile_hide_pattern 헬퍼로 통일(카테고리 오버라이드와 동일 문법).
    # normalize 미지정 = 원형 substring 비교라 기존 동작이 그대로 보존된다.
    to_remove = []
    for item in auto_hide:
        pred = compile_hide_pattern(item)
        if pred is None:
            continue
        to_remove += [keyword for keyword in main_tags if pred(keyword)]

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
    category_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    공통 태그 필터링 로직. main_tags, removed_tags를 in-place 수정.

    처리 순서:
    1. Auto Hide (보호 키워드 + 패턴 매칭)
    1.5 개별 숨김 (category_overrides 의 hide - 라운드 스위치와 무관)
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
        category_overrides: 카테고리별 사용자 오버라이드
            {option_key: {"exclude": [...], "include": [...], "hide": [...]}}.
            exclude=해당 라운드가 어떤 방식으로 매칭했든 제거하지 않음(보호).
            include=라운드 enabled 일 때만 정확일치 태그를 함께 제거.
            hide=**라운드 스위치와 무관하게 항상** 제거(개별 숨김). exclude 가 이긴다.
            Auto Hide(라운드 1)는 자체 문법을 가지므로 오버라이드 대상 아님.

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
        'key': 'auto_hide',
        'enabled': True,
        'removed': removed_tags[before_len:],
    })

    # 1.5 개별 숨김 - filter_manager 가 없어도 돈다(사전이 필요 없는 정확일치 목록).
    before_len = len(removed_tags)
    _apply_category_hide(main_tags, removed_tags, category_overrides)
    if len(removed_tags) > before_len:
        filter_log.append({
            'name': '개별 숨김',
            'key': 'category_hide',
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
        exclude_set, include_set = _override_sets(category_overrides, "remove_character_features")
        characteristics = filter_manager.characteristic_list
        temp = [keyword for keyword in main_tags if keyword in characteristics]
        temp = _apply_round_overrides(temp, main_tags, exclude_set, include_set)
        for keyword in temp:
            main_tags.remove(keyword)
            removed_tags.append(keyword)
    filter_log.append({
        'name': '캐릭터 특징',
        'key': 'remove_character_features',
        'enabled': enabled,
        'removed': removed_tags[before_len:],
    })

    # 3. remove_clothes (+ optional region 추적)
    enabled = checkbox_options.get("remove_clothes", False)
    before_len = len(removed_tags)
    if enabled:
        exclude_set, include_set = _override_sets(category_overrides, "remove_clothes")
        clothes = filter_manager.clothes_list
        temp = [keyword for keyword in main_tags if keyword in clothes]
        temp = _apply_round_overrides(temp, main_tags, exclude_set, include_set)

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
        'key': 'remove_clothes',
        'enabled': enabled,
        'removed': removed_tags[before_len:],
    })

    # 3.5 remove_clothing_event (의상 이벤트: 상태/동작)
    enabled = checkbox_options.get("remove_clothing_event", False)
    before_len = len(removed_tags)
    if enabled:
        exclude_set, include_set = _override_sets(category_overrides, "remove_clothing_event")
        event_set = filter_manager._clothing_event_set
        temp = [keyword for keyword in main_tags if keyword in event_set]
        temp = _apply_round_overrides(temp, main_tags, exclude_set, include_set)

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
        'key': 'remove_clothing_event',
        'enabled': enabled,
        'removed': removed_tags[before_len:],
    })

    # 4. remove_color
    enabled = checkbox_options.get("remove_color", False)
    before_len = len(removed_tags)
    if enabled:
        exclude, include = _override_sets(category_overrides, "remove_color")
        colors = filter_manager.color_list
        # 색상 라운드는 '단어' 부분일치라 exclude 가 이중 의미를 갖는다:
        # - exclude 항목이 색상 단어와 (정확일치·패턴) 매치하면 그 단어를 통째로 보호
        #   (예: exclude 'blue' -> 'blue hair', 'blue dress' 전부 제거 안 함)
        # - 그 외 항목은 아래 _apply_round_overrides 의 완성-태그 보호
        #   (예: exclude 'blue hair' -> 'blue hair' 만 보호)
        if not _terms_empty(exclude):
            colors = [color for color in colors if not _matches_terms(color, exclude)]
        temp = [keyword for keyword in main_tags
                if not _is_color_exception(keyword) and any(color in keyword for color in colors)]
        temp = _apply_round_overrides(temp, main_tags, exclude, include)
        for keyword in temp:
            main_tags.remove(keyword)
            removed_tags.append(keyword)
    filter_log.append({
        'name': '색상',
        'key': 'remove_color',
        'enabled': enabled,
        'removed': removed_tags[before_len:],
    })

    # 5. remove_location_and_background_color
    enabled = checkbox_options.get("remove_location_and_background_color", False)
    before_len = len(removed_tags)
    if enabled:
        exclude_set, include_set = _override_sets(category_overrides, "remove_location_and_background_color")
        location_set = filter_manager._location_set
        temp = [keyword for keyword in main_tags if keyword in location_set]
        temp = _apply_round_overrides(temp, main_tags, exclude_set, include_set)
        for keyword in temp:
            main_tags.remove(keyword)
            removed_tags.append(keyword)
    filter_log.append({
        'name': '위치/배경',
        'key': 'remove_location_and_background_color',
        'enabled': enabled,
        'removed': removed_tags[before_len:],
    })

    # 6. remove_expression (NEW)
    enabled = checkbox_options.get("remove_expression", False)
    before_len = len(removed_tags)
    if enabled:
        exclude_set, include_set = _override_sets(category_overrides, "remove_expression")
        expression_set = filter_manager._expression_set
        temp = [keyword for keyword in main_tags if keyword in expression_set]
        temp = _apply_round_overrides(temp, main_tags, exclude_set, include_set)
        for keyword in temp:
            main_tags.remove(keyword)
            removed_tags.append(keyword)
    filter_log.append({
        'name': '표정',
        'key': 'remove_expression',
        'enabled': enabled,
        'removed': removed_tags[before_len:],
    })

    # 7. remove_pose_action (NEW)
    enabled = checkbox_options.get("remove_pose_action", False)
    before_len = len(removed_tags)
    if enabled:
        exclude_set, include_set = _override_sets(category_overrides, "remove_pose_action")
        pose_action_set = filter_manager._pose_action_set
        temp = [keyword for keyword in main_tags if keyword in pose_action_set]
        temp = _apply_round_overrides(temp, main_tags, exclude_set, include_set)
        for keyword in temp:
            main_tags.remove(keyword)
            removed_tags.append(keyword)
    filter_log.append({
        'name': '포즈/동작',
        'key': 'remove_pose_action',
        'enabled': enabled,
        'removed': removed_tags[before_len:],
    })

    # 8. remove_meta_tags (메타 태그 제거)
    enabled = checkbox_options.get("remove_meta_tags", True)
    before_len = len(removed_tags)
    if enabled:
        exclude_set, include_set = _override_sets(category_overrides, "remove_meta_tags")
        meta_set = filter_manager._meta_set
        temp = [keyword for keyword in main_tags if keyword in meta_set]
        temp = _apply_round_overrides(temp, main_tags, exclude_set, include_set)
        for keyword in temp:
            main_tags.remove(keyword)
            removed_tags.append(keyword)
    filter_log.append({
        'name': '메타',
        'key': 'remove_meta_tags',
        'enabled': enabled,
        'removed': removed_tags[before_len:],
    })

    # 9. remove_object_tags (사물 태그 제거)
    enabled = checkbox_options.get("remove_object_tags", False)
    before_len = len(removed_tags)
    if enabled:
        exclude_set, include_set = _override_sets(category_overrides, "remove_object_tags")
        object_set = filter_manager._object_set
        temp = [keyword for keyword in main_tags if keyword in object_set]
        temp = _apply_round_overrides(temp, main_tags, exclude_set, include_set)
        for keyword in temp:
            main_tags.remove(keyword)
            removed_tags.append(keyword)
    filter_log.append({
        'name': '사물',
        'key': 'remove_object_tags',
        'enabled': enabled,
        'removed': removed_tags[before_len:],
    })

    # 10. remove_noise_tags (저빈도 태그 제거)
    enabled = checkbox_options.get("remove_noise_tags", False)
    before_len = len(removed_tags)
    if enabled:
        exclude, include = _override_sets(category_overrides, "remove_noise_tags")
        filtered_set = set(filter_manager.filter_noise_tags(main_tags))
        # 빈도 기반이라 temp 후처리 대신 filtered 결과에 exclude 태그를 되살리는 방식.
        # exclude=보호(정확일치·패턴), include=강제 제거(정확일치·패턴). exclude 우선.
        new_main = []
        removed_here = []
        for keyword in main_tags:
            protected = _matches_terms(keyword, exclude)
            forced = _matches_terms(keyword, include)
            should_remove = (keyword not in filtered_set or forced) and not protected
            if should_remove:
                removed_here.append(keyword)
            else:
                new_main.append(keyword)
        main_tags[:] = new_main
        removed_tags.extend(removed_here)
    filter_log.append({
        'name': '노이즈 태그',
        'key': 'remove_noise_tags',
        'enabled': enabled,
        'removed': removed_tags[before_len:],
    })

    result['filter_log'] = filter_log
    return result
