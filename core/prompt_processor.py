import math
import re
import pandas as pd
from typing import Dict, Any
from core.prompt_context import PromptContext
from core.wildcard_processor import WildcardProcessor # 이전 단계에서 생성
from core.context import AppContext
from core.resolution_utils import (
    MAX_1MP_PIXELS,
    nearest_anima_preset_resolution,
    nearest_standard_1mp_resolution,
)

# 가중치 구문 감지 정규식 (C-2: \d+\.?\d* 로 정밀화)
_WEIGHT_WEBUI_RE = re.compile(r'^\(.*:\d+\.?\d*\)$')   # (tag:1.2) — A1111 개별 가중치
_WEIGHT_NAI_RE = re.compile(r'^\d+\.?\d*::.*\s*::$')    # 0.85::tag :: — NAI 개별 가중치
_E621_GROUP_CLOSE_RE = re.compile(r':\d+\.?\d*\)$')     # tag:1.05) — e621 그룹 종료


def _escape_parens_in_content(s: str) -> str:
    """이미 이스케이프된 \\( \\) 보호하면서 리터럴 괄호를 이스케이프."""
    result = s.replace('\\(', '\x00').replace('\\)', '\x01')
    result = result.replace('(', '\\(').replace(')', '\\)')
    result = result.replace('\x00', '\\(').replace('\x01', '\\)')
    return result


def _find_weighted_indices(tags: list, start: int) -> set:
    """main_tags[start:] 중 이미 가중치가 적용된 태그의 인덱스 집합을 반환.
    반환값에는 개별 가중치(individual) 및 e621 그룹(group_start~group_end)이 포함."""
    weighted = set()

    # 1) 개별 가중치 (Danbooru, NAI) 감지
    for i in range(start, len(tags)):
        tag = tags[i].strip()
        if _WEIGHT_WEBUI_RE.match(tag) or _WEIGHT_NAI_RE.match(tag):
            weighted.add(i)

    # 2) e621 그룹 감지: 뒤에서부터 스캔
    group_end = None
    for i in range(len(tags) - 1, start - 1, -1):
        tag = tags[i].strip()
        if i in weighted:
            continue
        if _E621_GROUP_CLOSE_RE.search(tag) and not _WEIGHT_WEBUI_RE.match(tag):
            group_end = i
            break

    if group_end is not None:
        group_start = None
        for i in range(group_end, start - 1, -1):
            tag = tags[i].strip()
            if i in weighted:
                break
            if tag.startswith('(') and not _WEIGHT_WEBUI_RE.match(tag):
                group_start = i
                break

        if group_start is not None:
            for i in range(group_start, group_end + 1):
                weighted.add(i)

    return weighted


def _parse_anima_weight(raw) -> tuple[bool, float]:
    """ANIMA 가중치 입력값 파싱.

    Returns:
        (skip_block, weight):
            - skip_block=True → 괄호 래핑 자체를 생략 (가중치 없음)
            - skip_block=False → weight 를 `:{weight})` 로 적용
    규칙:
        - None / 공란 → 기본값 1 사용 (래핑 생략)
        - 0 또는 1 → skip_block=True (래핑 생략)
        - 잘못된 값 → 기본값 1 로 복원 (입력 무시)
    """
    DEFAULT = 1.0
    if raw is None:
        return (True, DEFAULT)
    try:
        value = float(str(raw).strip())
    except (ValueError, TypeError):
        return (True, DEFAULT)
    if not math.isfinite(value):
        # nan / inf / -inf → 잘못된 값으로 취급, 기본값 복원
        return (True, DEFAULT)
    if value == 0.0 or value == 1.0:
        return (True, value)
    return (False, value)


def _is_comfyui_anima_mode(app_context, settings: Dict[str, Any]) -> bool:
    """Return whether the active prompt formatting target is ComfyUI ANIMA."""
    api_mode = str(
        settings.get('api_mode')
        or getattr(app_context, 'current_api_mode', '')
        or ''
    ).strip().upper()
    if api_mode != 'COMFYUI':
        return False

    sampling_mode = str(
        settings.get('comfyui_sampling_mode')
        or settings.get('sampling_mode')
        or ''
    ).strip().lower()
    workflow_type = str(settings.get('workflow_type') or '').strip().lower()
    if sampling_mode == 'anima' or workflow_type == 'unet':
        return True
    if sampling_mode or workflow_type:
        return False

    main_window = getattr(app_context, 'main_window', None)
    anima_radio = getattr(main_window, 'anima_radio', None)
    return bool(anima_radio is not None and anima_radio.isChecked())


def _is_webui_weight_mode(app_context, settings: Dict[str, Any]) -> bool:
    api_mode = str(
        settings.get('api_mode')
        or getattr(app_context, 'current_api_mode', '')
        or ''
    ).strip().upper()
    return api_mode == 'WEBUI'


def _get_random_prompt_weight_raw(app_context, settings: Dict[str, Any], *, allow_window_fallback: bool):
    raw = settings.get('random_prompt_weight')
    if raw is None:
        raw = settings.get('anima_weight')
    if raw is None and allow_window_fallback and hasattr(app_context, 'main_window'):
        mw = app_context.main_window
        if hasattr(mw, 'anima_weight_edit'):
            raw = mw.anima_weight_edit.text().strip() or None
    return raw


def _wrap_unweighted_main_tag_runs(tags: list, first_non_hash: int, weighted_indices: set, weight: float) -> int:
    if not tags or first_non_hash >= len(tags):
        return 0

    runs = []
    run_start = None
    for i in range(first_non_hash, len(tags)):
        if i not in weighted_indices:
            if run_start is None:
                run_start = i
        else:
            if run_start is not None:
                runs.append((run_start, i - 1))
                run_start = None
    if run_start is not None:
        runs.append((run_start, len(tags) - 1))

    for start, end in runs:
        tags[start] = f"({tags[start]}"
        tags[end] = f"{tags[end]}:{weight})"

    return len(runs)


def _escape_main_tags_parens(tags: list, weighted: set):
    """main_tags 리터럴 괄호를 in-place 이스케이프. weighted 인덱스의 가중치 구문은 보존."""
    for i, tag in enumerate(tags):
        if tag.startswith('#'):
            continue

        if i in weighted:
            # 가중치 태그: 가중치 구문 괄호는 보존, 콘텐츠 내 괄호만 이스케이프
            if _WEIGHT_WEBUI_RE.match(tag):
                # (content:weight) → 내부만 이스케이프
                inner = tag[1:]
                colon_idx = inner.rfind(':')
                content = inner[:colon_idx]
                suffix = inner[colon_idx:]
                tags[i] = '(' + _escape_parens_in_content(content) + suffix
            elif tag.startswith('('):
                # e621 그룹 시작: 선행 ( 보존 + 내부 이스케이프
                tags[i] = '(' + _escape_parens_in_content(tag[1:])
            elif _E621_GROUP_CLOSE_RE.search(tag):
                # e621 그룹 종료: :weight) 보존 + 내부 이스케이프
                close_m = _E621_GROUP_CLOSE_RE.search(tag)
                tags[i] = _escape_parens_in_content(tag[:close_m.start()]) + close_m.group()
            else:
                # e621 그룹 중간: 전체 이스케이프
                tags[i] = _escape_parens_in_content(tag)
        else:
            # 비가중치 태그: 전체 이스케이프
            tags[i] = _escape_parens_in_content(tag)

class PromptProcessor:
    PIPELINE_NAME = "PromptProcessor"

    def __init__(self, app_context: AppContext):
        self.app_context = app_context
        self.wildcard_processor = WildcardProcessor(app_context.main_window.wildcard_manager)

    def process(self) -> PromptContext:
        """
        [수정] AppContext에 저장된 current_prompt_context를 가져와 파이프라인을 실행합니다.
        이제 이 메소드는 인자를 받지 않습니다.
        """
        context = self.app_context.current_prompt_context
        if not context:
            raise ValueError("PromptProcessor.process: AppContext에 current_prompt_context가 설정되지 않았습니다.")

        # [수정] _step_1_initialize를 여기에서 호출하지 않고, 컨트롤러가 context 생성 시 초기화하도록 변경

        context = self._run_hooks('pre_processing', context)
        context = self._step_2_fit_resolution(context)
        context = self._run_hooks('post_processing', context)
        context = self._step_3_expand_wildcards(context)
        context = self._run_hooks('after_wildcard', context)
        context = self._run_hooks('final_hookpoint', context)
        context.final_prompt = self._step_final_format(context)
        
        return context
    
    def _run_hooks(self, hook_point: str, context: PromptContext) -> PromptContext:
        """등록된 훅들을 순서대로 실행합니다."""
        hooks_to_run = self.app_context.get_pipeline_hooks(self.PIPELINE_NAME, hook_point)
        
        for module_hook in hooks_to_run:
            try:
                # 각 훅은 context를 받아 수정 후 다시 반환
                context = module_hook.execute_pipeline_hook(context)
            except Exception as e:
                print(f"파이프라인 훅 실행 중 오류 ({module_hook.get_title()}): {e}")

        return context

    def _apply_remote_auto_resolution_preset_defaults(self, settings: dict, api_mode: str) -> None:
        """Remote Web Auto Gen also needs the server-owned resolution preset state."""
        normalized_mode = str(api_mode or '').strip().upper()
        if normalized_mode not in {'WEBUI', 'COMFYUI'}:
            return
        if 'resolution_preset_enabled' in settings or 'resolution_preset' in settings:
            return
        if not settings.get('auto_generate', False):
            return
        bridge = getattr(self.app_context, 'remote_bridge', None)
        enabled_getter = getattr(bridge, 'is_remote_auto_generate_enabled', None)
        if not callable(enabled_getter):
            return
        try:
            if not bool(enabled_getter()):
                return
        except Exception:
            return
        preset_getter = getattr(bridge, 'get_resolution_preset_params', None)
        if not callable(preset_getter):
            return
        try:
            defaults = preset_getter(normalized_mode)
        except Exception:
            return
        if not isinstance(defaults, dict) or not defaults.get('resolution_preset_enabled'):
            return
        settings.setdefault('resolution_preset_enabled', True)
        if 'resolution_preset' in defaults:
            settings.setdefault('resolution_preset', defaults['resolution_preset'])

    def _step_2_fit_resolution(self, context: PromptContext) -> PromptContext:
        """[신규] 해상도 자동 맞춤 로직을 파이프라인의 한 단계로 추가합니다."""
        settings = context.settings
        source_row = context.source_row

        if not settings.get('auto_fit_resolution', False) or settings.get('wildcard_standalone', False):
            return context

        if 'image_width' in source_row and 'image_height' in source_row:
            try:
                width = int(source_row['image_width'])
                height = int(source_row['image_height'])
                if width > 0 and height > 0:
                    api_mode = (
                        settings.get('api_mode')
                        or getattr(getattr(self, 'app_context', None), 'current_api_mode', '')
                    )
                    self._apply_remote_auto_resolution_preset_defaults(settings, api_mode)
                    if (
                        str(api_mode or '').strip().upper() in {'WEBUI', 'COMFYUI'}
                        and settings.get('resolution_preset_enabled')
                    ):
                        width, height = nearest_anima_preset_resolution(
                            width,
                            height,
                            settings.get('resolution_preset'),
                        )
                    elif width * height > MAX_1MP_PIXELS:
                        width, height = nearest_standard_1mp_resolution(width, height)
                    context.metadata['detected_resolution'] = (width, height)
            except (ValueError, TypeError):
                pass

        return context

    def _step_3_expand_wildcards(self, context: PromptContext) -> PromptContext:
        """와일드카드를 실제 태그로 치환하는 단계"""
        context.prefix_tags = self.wildcard_processor.expand_tags(context.prefix_tags, context)
        context.prefix_tags = self._expand_preset_tokens(context.prefix_tags, context)
        context.main_tags = self._expand_preset_tokens(context.main_tags, context)
        context.postfix_tags = self.wildcard_processor.expand_tags(context.postfix_tags, context)
        context.postfix_tags = self._expand_preset_tokens(context.postfix_tags, context)
        return context

    def _expand_preset_tokens(self, tags: list[str], context: PromptContext) -> list[str]:
        expanded: list[str] = []
        for tag in tags:
            token = str(tag or "").strip()
            if not token.lower().startswith("preset:"):
                expanded.append(tag)
                continue
            resolver = self._preset_input_bridge(context, tags=tags)
            result = resolver.resolve_prompt_token(token)
            context.metadata.setdefault("preset_prompt_resolutions", []).append(result)
            if result.get("applied"):
                expanded.extend(result.get("tags") or [])
            else:
                expanded.append(tag)
        return expanded

    def _preset_input_bridge(self, context: PromptContext | None = None, tags: list[str] | None = None):
        bridge = getattr(self, "_preset_bridge", None)
        app_context = getattr(self, "app_context", None)
        service_key = None
        service_kwargs = {}
        preset_context = None
        if app_context is not None:
            from core.preset_input_bridge import preset_context_from_prompt, preset_service_kwargs

            service_kwargs = preset_service_kwargs(app_context)
            service_key = tuple(id(service_kwargs.get(key)) for key in ("event_service", "clothes_service", "expression_service"))
            preset_context = preset_context_from_prompt(app_context, context, tags=tags)
        if bridge is None or (
            service_key is not None
            and getattr(self, "_preset_bridge_service_key", service_key) != service_key
        ):
            from pathlib import Path
            from core.preset_input_bridge import PresetInputBridge

            bridge = PresetInputBridge(
                Path(__file__).resolve().parent.parent,
                **service_kwargs,
                context=preset_context,
            )
            self._preset_bridge = bridge
            self._preset_bridge_service_key = service_key
        elif preset_context is not None and hasattr(bridge, "set_context"):
            bridge.set_context(preset_context)
        return bridge

    def _step_final_format(self, context: PromptContext) -> str:
        """모든 태그를 조합하여 최종 문자열로 포맷팅하는 단계"""
        
        # [추가] Step 3에서 처리된 global_append_tags를 main_tags의 끝에 추가합니다.
        # 이 작업은 다른 모든 처리보다 먼저 수행되어야 합니다.
        if context.global_append_tags:
            context.main_tags.extend(context.global_append_tags)

        # 인물 태그 세트 정의
        person_sets = {
            "boys": {"1boy", "2boys", "3boys", "4boys", "5boys", "6+boys"},
            "girls": {"1girl", "2girls", "3girls", "4girls", "5girls", "6+girls"},
            "others": {"1other", "2others", "3others", "4others", "5others", "6+others"}
        }
        all_person_tags = person_sets["boys"] | person_sets["girls"] | person_sets["others"]
        
        person_tags_found = []
        new_main_tags = []

        # 1. main_tags에서 인물 관련 태그와 나머지 태그 분리
        for tag in context.main_tags:
            if tag in all_person_tags:
                person_tags_found.append(tag)
            else:
                new_main_tags.append(tag)

        # 2. 찾은 인물 태그들을 boys -> girls -> others 순서로 정렬
        sorted_person_tags = sorted(person_tags_found, key=lambda tag: 
                                    0 if tag in person_sets["boys"] else 
                                    1 if tag in person_sets["girls"] else 2)

        # 3. 태그 자동 변환 적용
        tag_conversion_map = {
            'v': 'peace sign', 'double v': 'double peace', '|_|': 'bar eyes',
            '\\||/': 'open \\m/', ':|': 'neutral face', ';|': 'neutral face',
            'eyepatch bikini': 'square bikini', 'tachi-e': 'character image'
        }

        converted_main_tags = [tag_conversion_map.get(tag, tag) for tag in new_main_tags]
        if converted_main_tags:
            converted_main_tags.insert(0, '#랜덤프롬프트')  # Ensure 'main tags' is always the first tag

        # 4. context 최종 업데이트
        context.main_tags = converted_main_tags

        # 4-0. 가중치 인덱스 계산 (이스케이프 + ANIMA 래핑에서 공유)
        is_nai = self.app_context.current_api_mode == 'NAI'
        first_non_hash = next(
            (i for i, t in enumerate(context.main_tags) if not t.startswith('#')),
            len(context.main_tags)
        )
        weighted_indices = (
            _find_weighted_indices(context.main_tags, first_non_hash)
            if not is_nai and first_non_hash < len(context.main_tags)
            else set()
        )

        # 4-0b. non-NAI 모드: main_tags 리터럴 괄호 이스케이프 (인덱스 기반)
        if not is_nai:
            _escape_main_tags_parens(context.main_tags, weighted_indices)

        # 4-1. 인원수 태그 배치 (ANIMA 모드 고려)
        is_anima_mode = _is_comfyui_anima_mode(self.app_context, context.settings)
        is_comfyui = self.app_context.current_api_mode == 'COMFYUI'
        is_webui_weight_mode = _is_webui_weight_mode(self.app_context, context.settings)
        apply_prompt_weight = is_webui_weight_mode or is_comfyui
        raw_prompt_weight = _get_random_prompt_weight_raw(
            self.app_context,
            context.settings,
            allow_window_fallback=(is_webui_weight_mode or is_comfyui),
        )
        prompt_weight_skip, prompt_weight = _parse_anima_weight(raw_prompt_weight)

        if is_comfyui and is_anima_mode:
            # ANIMA 모드: @ 태그 앞에 삽입
            at_index = None
            for i, tag in enumerate(context.prefix_tags):
                if '@' in tag:
                    at_index = i
                    break

            if at_index is not None:
                # ANIMA 모드: 순서대로 삽입 (인원수 → 캐릭터 → copyright → @artist)
                anima_tags = []

                # 1. 인원수 태그
                anima_tags.extend(sorted_person_tags)

                # 2. 캐릭터 태그 (metadata에서, 괄호 이스케이프 + 가중치 적용)
                if 'anima_character' in context.metadata:
                    character_str = context.metadata['anima_character']
                    # 쉼표로 분리하여 리스트로 만들기
                    char_list = [c.strip() for c in character_str.split(',')]

                    if char_list:
                        # 괄호 이스케이프 처리
                        char_list = [c.replace("(", r"\(").replace(")", r"\)") for c in char_list]

                        # 가중치 래핑 (anima_weight — 0/1 또는 잘못된 입력은 _parse_anima_weight 에서 처리)
                        if not prompt_weight_skip:
                            char_list[0] = f"({char_list[0]}"
                            char_list[-1] = f"{char_list[-1]}:{prompt_weight})"

                        # 다시 쉼표로 조인
                        character = ', '.join(char_list)
                        anima_tags.append(character)

                # 3. copyright 태그 (metadata에서, 괄호 이스케이프)
                if 'anima_copyright' in context.metadata:
                    copyright_tag = context.metadata['anima_copyright'].replace("(", r"\(").replace(")", r"\)")
                    anima_tags.append(copyright_tag)

                # 4. @artist 태그 (metadata에서, @ 붙이고 괄호 이스케이프)
                if 'anima_artist' in context.metadata:
                    artist = context.metadata['anima_artist'].replace("(", r"\(").replace(")", r"\)")
                    anima_tags.append(f"@{artist}")

                # @ 태그 앞에 삽입
                context.prefix_tags = (
                    context.prefix_tags[:at_index] +
                    anima_tags +
                    context.prefix_tags[at_index:]
                )
                print(f"🎨 ANIMA 모드: 태그 삽입 완료 (인덱스 {at_index}): {', '.join(anima_tags)}")
            else:
                # @ 태그가 없으면 맨 뒤에 삽입
                anima_tags = []

                # 1. 인원수 태그
                anima_tags.extend(sorted_person_tags)

                # 2. 캐릭터 태그 (괄호 이스케이프 + 가중치 적용)
                if 'anima_character' in context.metadata:
                    character_str = context.metadata['anima_character']
                    # 쉼표로 분리하여 리스트로 만들기
                    char_list = [c.strip() for c in character_str.split(',')]

                    if char_list:
                        # 괄호 이스케이프 처리
                        char_list = [c.replace("(", r"\(").replace(")", r"\)") for c in char_list]

                        # 가중치 래핑 (anima_weight — 0/1 또는 잘못된 입력은 _parse_anima_weight 에서 처리)
                        if not prompt_weight_skip:
                            char_list[0] = f"({char_list[0]}"
                            char_list[-1] = f"{char_list[-1]}:{prompt_weight})"

                        # 다시 쉼표로 조인
                        character = ', '.join(char_list)
                        anima_tags.append(character)

                # 3. copyright 태그 (괄호 이스케이프)
                if 'anima_copyright' in context.metadata:
                    copyright_tag = context.metadata['anima_copyright'].replace("(", r"\(").replace(")", r"\)")
                    anima_tags.append(copyright_tag)

                # 4. @artist 태그 (@ 붙이고 괄호 이스케이프)
                if 'anima_artist' in context.metadata:
                    artist = context.metadata['anima_artist'].replace("(", r"\(").replace(")", r"\)")
                    anima_tags.append(f"@{artist}")

                context.prefix_tags = context.prefix_tags + anima_tags
                print(f"🎨 ANIMA 모드: @ 태그 없음, 태그를 맨 뒤에 삽입: {', '.join(anima_tags)}")

        else:
            # 기존 방식: 맨 앞에 삽입
            context.prefix_tags = sorted_person_tags + context.prefix_tags

        # ANIMA/WEBUI 랜덤 프롬프트 가중치: 이미 가중치가 적용된 태그는 제외하고
        # 비가중치 연속 구간만 A1111 형식으로 래핑한다.
        if apply_prompt_weight and context.main_tags and first_non_hash < len(context.main_tags):
            label = "WEBUI" if is_webui_weight_mode else "COMFYUI"
            if not prompt_weight_skip:
                run_count = _wrap_unweighted_main_tag_runs(
                    context.main_tags,
                    first_non_hash,
                    weighted_indices,
                    prompt_weight,
                )
                print(f"🎨 {label} 모드: main_tags 가중치 {prompt_weight} 적용 — {run_count}개 구간, 가중치 태그 {len(weighted_indices)}개 제외")
            else:
                print(f"🎨 {label} 모드: main_tags 가중치 입력 {raw_prompt_weight} → 래핑 생략")

        # --- 이하 기존 로직 ---
        all_tags = context.get_all_tags()
        seen_person = set()
        final_tags = []

        for tag in all_tags:
            if not isinstance(tag, str):
                continue
            if '\n\n' in tag:
                final_tags.append(tag)
            elif tag in all_person_tags and tag in seen_person:
                pass  # 인물 태그 중복만 제거
            else:
                final_tags.append(tag)
                if tag in all_person_tags:
                    seen_person.add(tag)
        
        formatted_prompt = []
        for tag in final_tags:
            if tag.startswith('#'):
                formatted_prompt.append(f"\n{tag.strip()}\n")
            elif tag == "\n\n":
                formatted_prompt.append("\n\n")
            else:
                formatted_tag = tag
                formatted_prompt.append(formatted_tag)

        # 와일드카드 단독 모드 + NAI + 사용자 활성화: 프롬프트 squeeze 적용
        if (context.settings.get('wildcard_standalone', False) and
                self.app_context.current_api_mode == 'NAI' and
                getattr(self.app_context, 'prompt_squeeze_enabled', False)):
            formatted_prompt = self._apply_prompt_squeeze(formatted_prompt)

        final_string = ', '.join(formatted_prompt)

        return final_string

    def _apply_prompt_squeeze(self, formatted_prompt: list) -> list:
        """와일드카드 단독 모드에서 동일 프롬프트 해시 검출을 회피하기 위한 미세 변형.
        기존 태그에서 조각을 추출하여 극저 가중치로 무작위 삽입."""
        import re
        import random

        # 1. 태그에서 pure text 조각 수집
        fragments = []
        for tag in formatted_prompt:
            stripped = tag.strip()
            if not stripped or stripped.startswith('#') or stripped.startswith('\n'):
                continue

            # 가중치/구문 제거 → pure text
            pure = stripped
            pure = re.sub(r'^\d+\.?\d*::', '', pure)   # 선행 "0.85::"
            pure = re.sub(r'\s*::$', '', pure)          # 후행 " ::"
            pure = re.sub(r'[{}\[\]()]', '', pure)      # 괄호류
            pure = re.sub(r':\d+\.?\d*', '', pure)      # ":1.2" 등
            pure = pure.strip()

            if not pure:
                continue
            if 'artist' in pure.lower():
                continue
            if re.search(r'\d', pure):
                continue

            # 공백/_로 분해, 2글자 이상만
            parts = re.split(r'[\s_]+', pure)
            fragments.extend(p for p in parts if len(p) >= 2)

        if not fragments:
            return formatted_prompt

        # 2. 무작위 조각을 극저 가중치로 삽입
        result = formatted_prompt.copy()
        num_insert = random.randint(1, min(3, len(fragments)))
        selected = random.sample(fragments, k=min(num_insert, len(fragments)))

        for frag in selected:
            weight = random.randint(1, 9) / 100
            dummy = f"{weight}::{frag} ::"
            start = max(1, len(result) // 2)
            pos = random.randint(start, max(start, len(result) - 1))
            result.insert(pos, dummy)

        return result
