import math
import re
import pandas as pd
import weakref
from collections import Counter
from typing import Dict, Any
from core.prompt_category_annotation import (
    build_annotated_main_tags,
    build_identity_block,
)
from core.prompt_context import PromptContext
from core.safe_console import safe_print
from core.seam_observer import seam_observer  # 관측 전용(기본 OFF) 파이프라인 seam 계측
from core.wildcard_processor import WildcardProcessor # 이전 단계에서 생성
from core.resolution_utils import (
    MAX_1MP_PIXELS,
    nearest_anima_preset_resolution,
    nearest_standard_1mp_resolution,
)

# 인물 수 태그. 최종 포맷에서 main -> prefix 맨 앞으로 **옮겨진다**(아래 `_step_final_format`).
# ⚠️ 그래서 조립된 프롬프트만 보면 `1girl` 이 프롬프트 엔지니어링이 붙인 것처럼 보인다.
#    실제로는 사용자의 장면 태그다 - 되짚어야 하는 쪽(V5 Scene 저장)이 여기를 함께 봐야
#    해서 모듈 상수로 올렸다. 같은 목록을 두 벌 두면 한쪽만 늘어난다.
PERSON_TAG_SETS = {
    "boys": {"1boy", "2boys", "3boys", "4boys", "5boys", "6+boys"},
    "girls": {"1girl", "2girls", "3girls", "4girls", "5girls", "6+girls"},
    "others": {"1other", "2others", "3others", "4others", "5others", "6+others"},
}
ALL_PERSON_TAGS = PERSON_TAG_SETS["boys"] | PERSON_TAG_SETS["girls"] | PERSON_TAG_SETS["others"]

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


# =====================================================================================
# 파이프라인 트레이스 (읽기 전용 관측)
# -------------------------------------------------------------------------------------
# 제거된 Dev0714 "Hooker"(코드 실행)를 대체한다. 코드를 실행하는 대신, 각 파이프라인 단계가
# 프롬프트 태그에 무엇을 했는지(추가/제거 + 노트)만 단계별로 기록해 context.metadata['pipeline_trace']
# 에 누적한다. add_api_result 단계에서 이미지 항목에 영속되어, 히스토리에서 이미지별로 조회된다.
#
# 설계 불변식(seam_observer와 동일 철학):
#   - 절대 raise 하지 않는다 / context 를 변형하지 않는다 / 제어 흐름을 바꾸지 않는다.
#   - JSON-safe(문자열/리스트/딕트)만 저장한다(매 PNG·메타데이터에 임베드되므로 raw bytes 금지).
#   - 매 단계 출력 목록은 상한으로 캡한다(긴 프롬프트에서도 메모리/페이로드 바운드).
# =====================================================================================

# 트레이스 비교 대상 = 프롬프트 태그 버스(전개/포맷 결과가 보이는 곳).
_TRACE_PROMPT_FIELDS = ("prefix_tags", "main_tags", "postfix_tags")
_TRACE_MAX_ITEMS = 60          # added/removed 각 목록 상한
_TRACE_MAX_TAG_LEN = 200       # 개별 태그 문자열 상한
_TRACE_STAGE_LABELS = {
    "pre_processing": "전처리 (pre)",
    "resolution_fit": "해상도 맞춤",
    "post_processing": "후처리 (post)",
    "wildcard_expand": "와일드카드 전개",
    "after_wildcard": "와일드카드 후",
    "final_hookpoint": "최종 훅",
    "final_format": "최종 포맷",
}


def _trace_norm_tag(tag: Any):
    """트레이스 비교용 태그 정규화. get_all_tags()의 '\\n\\n' 부작용·'#마커'·빈값은 제외."""
    try:
        s = str(tag).strip()
    except Exception:
        return None
    if not s or s.startswith('#') or '\n' in s:
        return None
    return s


def _trace_prompt_snapshot(context: PromptContext) -> list:
    """현재 prefix+main+postfix의 정규화된 태그 목록(순서 보존, 얕은 복사)."""
    out: list = []
    for field_name in _TRACE_PROMPT_FIELDS:
        value = getattr(context, field_name, None)
        if isinstance(value, list):
            for tag in value:
                norm = _trace_norm_tag(tag)
                if norm is not None:
                    out.append(norm)
    return out


def _trace_delta(before: list, after: list):
    """multiset 델타. (added, removed) — 중복/순서 노이즈를 줄이되 순서는 대체로 보존."""
    bc = Counter(before)
    ac = Counter(after)
    added = list((ac - bc).elements())
    removed = list((bc - ac).elements())
    return added, removed


def _trace_cap_list(items: list):
    """목록을 상한으로 자르고 각 항목 길이도 캡. (capped_list, overflow_count) 반환."""
    capped = [
        (s[:_TRACE_MAX_TAG_LEN] + '…') if len(s) > _TRACE_MAX_TAG_LEN else s
        for s in items[:_TRACE_MAX_ITEMS]
    ]
    overflow = max(0, len(items) - _TRACE_MAX_ITEMS)
    return capped, overflow


def _trace_resolution_note(context: PromptContext) -> str:
    try:
        res = context.metadata.get('detected_resolution')
        if isinstance(res, (tuple, list)) and len(res) == 2:
            return f"{res[0]}x{res[1]}"
    except Exception:
        pass
    return ""


def _trace_wildcard_rolls(context: PromptContext) -> list:
    """이번 생성에서 전개된 와일드카드 {from: 키, to: 마지막 선택값} 목록(JSON-safe)."""
    rolls: list = []
    try:
        history = getattr(context, 'wildcard_history', None)
        if isinstance(history, dict):
            for key, values in history.items():
                if values:
                    rolls.append({
                        "from": str(key)[:_TRACE_MAX_TAG_LEN],
                        "to": str(values[-1])[:_TRACE_MAX_TAG_LEN],
                    })
                if len(rolls) >= _TRACE_MAX_ITEMS:
                    break
    except Exception:
        pass
    return rolls


def _trace_final_note(context: PromptContext) -> str:
    try:
        fp = context.final_prompt or ""
        parts = [
            p.strip() for p in str(fp).split(',')
            if p.strip() and not p.strip().startswith('#')
        ]
        return f"최종 {len(parts)}개 태그"
    except Exception:
        return ""


class _PipelineTracer:
    """파이프라인 단계별 태그 델타를 모으는 읽기 전용 관측기. 절대 예외를 밖으로 던지지 않는다."""

    def __init__(self, context: PromptContext) -> None:
        self.records: list = []
        try:
            self.prev = _trace_prompt_snapshot(context)
        except Exception:
            self.prev = []

    def record(self, stage: str, context: PromptContext, note: str = "", rolls=None) -> None:
        try:
            after = _trace_prompt_snapshot(context)
            added, removed = _trace_delta(self.prev, after)
            self.prev = after
            added_c, added_more = _trace_cap_list(added)
            removed_c, removed_more = _trace_cap_list(removed)
            rec = {
                "stage": stage,
                "label": _TRACE_STAGE_LABELS.get(stage, stage),
                "added": added_c,
                "removed": removed_c,
                "changed": bool(added or removed or rolls or note),
            }
            if added_more:
                rec["added_more"] = added_more
            if removed_more:
                rec["removed_more"] = removed_more
            if note:
                rec["note"] = str(note)[:_TRACE_MAX_TAG_LEN]
            if rolls:
                rec["rolls"] = rolls
            self.records.append(rec)
        except Exception:
            pass

    def record_note_only(self, stage: str, context: PromptContext, note: str = "") -> None:
        """포맷 단계처럼 문자열 변형(이스케이프/가중치)이 델타를 오염시키는 단계용 — 노트만 기록."""
        try:
            # prev 스냅샷은 갱신해 두되(이후 단계 없음) added/removed는 노이즈라 생략.
            self.prev = _trace_prompt_snapshot(context)
            self.records.append({
                "stage": stage,
                "label": _TRACE_STAGE_LABELS.get(stage, stage),
                "added": [],
                "removed": [],
                "note": str(note)[:_TRACE_MAX_TAG_LEN],
                "changed": True,
            })
        except Exception:
            pass

    def finalize(self, context: PromptContext) -> None:
        try:
            if isinstance(getattr(context, "metadata", None), dict):
                context.metadata["pipeline_trace"] = self.records
        except Exception:
            pass


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
    if raw is None and allow_window_fallback:
        # Headless: PARAMS 패널 값은 remote_params 에 산다 — 데스크톱 main_window.anima_weight_edit
        # 의 등가물. 이게 없으면 ANIMA 모델 기본 가중치(예: 0.8)가 settings 로 전파되지 않아 랜덤
        # 프롬프트/캐릭터 가중치 래핑이 통째로 생략되던 버그(ComfyUI/ANIMA 사용자 리포트).
        remote_params = getattr(app_context, 'remote_params', None)
        if isinstance(remote_params, dict):
            candidate = remote_params.get('anima_weight') or remote_params.get('random_prompt_weight')
            if candidate not in (None, ''):
                raw = candidate
        if raw is None and hasattr(app_context, 'main_window'):
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

    def __init__(self, app_context: Any):
        self.app_context = app_context
        wildcard_manager = getattr(app_context, 'wildcard_manager', None)
        if wildcard_manager is None:
            main_window = getattr(app_context, 'main_window', None)
            wildcard_manager = getattr(main_window, 'wildcard_manager', None) if main_window else None
        if wildcard_manager is None:
            from core.wildcard_manager import WildcardManager

            wildcard_manager = WildcardManager()
            setattr(app_context, 'wildcard_manager', wildcard_manager)
        if getattr(wildcard_manager, '_app_context_ref', None) is None:
            try:
                wildcard_manager._app_context_ref = weakref.ref(app_context)
            except TypeError:
                pass
        self.wildcard_processor = WildcardProcessor(wildcard_manager)

    def process(self) -> PromptContext:
        """
        [수정] AppContext에 저장된 current_prompt_context를 가져와 파이프라인을 실행합니다.
        이제 이 메소드는 인자를 받지 않습니다.
        """
        context = self.app_context.current_prompt_context
        if not context:
            raise ValueError("PromptProcessor.process: AppContext에 current_prompt_context가 설정되지 않았습니다.")

        # [수정] _step_1_initialize를 여기에서 호출하지 않고, 컨트롤러가 context 생성 시 초기화하도록 변경

        # 읽기 전용 파이프라인 트레이스 — 각 단계가 프롬프트에 무엇을 했는지 관측만 한다(Hooker 대체).
        tracer = _PipelineTracer(context)

        context = self._run_hooks('pre_processing', context)
        tracer.record('pre_processing', context)

        context = self._step_2_fit_resolution(context)
        tracer.record('resolution_fit', context, note=_trace_resolution_note(context))

        context = self._run_hooks('post_processing', context)
        tracer.record('post_processing', context)

        context = self._step_3_expand_wildcards(context)
        _wc_rolls = _trace_wildcard_rolls(context)
        tracer.record(
            'wildcard_expand', context,
            note=(f"{len(_wc_rolls)}개 전개" if _wc_rolls else ""),
            rolls=_wc_rolls,
        )

        context = self._run_hooks('after_wildcard', context)
        tracer.record('after_wildcard', context)

        context = self._run_hooks('final_hookpoint', context)
        tracer.record('final_hookpoint', context)

        context.final_prompt = self._step_final_format(context)
        tracer.record_note_only('final_format', context, note=_trace_final_note(context))

        tracer.finalize(context)

        return context
    
    def _run_hooks(self, hook_point: str, context: PromptContext) -> PromptContext:
        """등록된 훅들을 순서대로 실행합니다."""
        hooks_to_run = self.app_context.get_pipeline_hooks(self.PIPELINE_NAME, hook_point)
        prompt_run_id = str(getattr(context, "metadata", {}).get("prompt_run_id") or "")
        hook_recorder = getattr(self.app_context, "record_prompt_run_hook", None)

        for module_hook in hooks_to_run:
            module_title = self._hook_title(module_hook)
            _seam_before = seam_observer.snapshot(context) if seam_observer.enabled else None
            try:
                # 각 훅은 context를 받아 수정 후 다시 반환
                context = module_hook.execute_pipeline_hook(context)
                if _seam_before is not None:
                    seam_observer.observe(self.PIPELINE_NAME, hook_point, module_title, _seam_before, context)
                if prompt_run_id and callable(hook_recorder):
                    hook_recorder(
                        prompt_run_id,
                        hook_point=hook_point,
                        module=module_title,
                        status="completed",
                    )
            except Exception as e:
                if prompt_run_id and callable(hook_recorder):
                    hook_recorder(
                        prompt_run_id,
                        hook_point=hook_point,
                        module=module_title,
                        status="failed",
                        error=str(e),
                    )
                print(f"파이프라인 훅 실행 중 오류 ({module_title}): {e}")

        return context

    @staticmethod
    def _hook_title(module_hook: Any) -> str:
        getter = getattr(module_hook, "get_title", None)
        if callable(getter):
            try:
                title = str(getter() or "")
                if title:
                    return title
            except Exception:
                pass
        return module_hook.__class__.__name__

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
                    normalized_mode = str(api_mode or '').strip().upper()
                    if (
                        normalized_mode in {'WEBUI', 'COMFYUI'}
                        and settings.get('resolution_preset_enabled')
                    ):
                        width, height = nearest_anima_preset_resolution(
                            width,
                            height,
                            settings.get('resolution_preset'),
                        )
                    elif (
                        normalized_mode == 'NAI'
                        and settings.get('nai_resolution_preset_enabled')
                    ):
                        # 밴드를 켰으면 **그 밴드 안**에서 비율이 가장 가까운 것으로.
                        # 안 그러면 Auto Res 가 항상 1MP 로 끌어내려 밴드가 무의미해진다.
                        from core.resolution_utils import nearest_nai_preset_resolution

                        width, height = nearest_nai_preset_resolution(
                            width, height, settings.get('nai_resolution_preset'))
                    elif normalized_mode == 'NAI':
                        # NAI only accepts dimensions that are multiples of 64.
                        # Always fit to the nearest standard ~1MP resolution so a
                        # low-res source (e.g. 350x600) scales UP instead of
                        # passing a tiny snapped size (320x576) to generation,
                        # and an oversized source scales down. Every standard
                        # combo is a 64-multiple, so requests are never rejected
                        # with a 500.
                        width, height = nearest_standard_1mp_resolution(width, height)
                    elif width * height > MAX_1MP_PIXELS:
                        width, height = nearest_standard_1mp_resolution(width, height)
                    context.metadata['detected_resolution'] = (width, height)
            except (ValueError, TypeError):
                pass

        return context

    def _step_3_expand_wildcards(self, context: PromptContext) -> PromptContext:
        """와일드카드를 실제 태그로 치환하는 단계"""
        # Ollama Boost([기능3])용: prefix/postfix의 *와일드카드 출력만* 캡처한다(고정 아티스트/
        # 퀄리티 태그 제외). 실제 전개와 동일 draw를 써야 하므로 여기서 sink로 수집한다.
        prefix_wc_sink: list[str] = []
        postfix_wc_sink: list[str] = []
        context.prefix_tags = self.wildcard_processor.expand_tags(
            context.prefix_tags, context, wildcard_sink=prefix_wc_sink, location='prefix')
        context.prefix_tags = self._expand_preset_tokens(context.prefix_tags, context)
        context.main_tags = self._expand_preset_tokens(context.main_tags, context)
        context.postfix_tags = self.wildcard_processor.expand_tags(
            context.postfix_tags, context, wildcard_sink=postfix_wc_sink, location='postfix')
        context.postfix_tags = self._expand_preset_tokens(context.postfix_tags, context)
        try:
            if isinstance(getattr(context, "metadata", None), dict):
                context.metadata["prefix_wildcard_tags"] = list(prefix_wc_sink)
                context.metadata["postfix_wildcard_tags"] = list(postfix_wc_sink)
                # Ollama Boost 접지용: 후처리(remove_color/object/features 등) + 와일드카드 전개 후,
                # 최종 포맷(인물수→prefix 이동) 전의 main 스냅샷. raw source_row['general'] 대신 이걸
                # 근거로 써서, 사용자가 전처리로 제거한 색/객체/특징을 부스트가 prose로 재주입해
                # remove_* 설정을 무력화하던 버그를 막는다(사용자 지정: prefix+main+postfix 처리 단계).
                context.metadata["boost_main_tags"] = list(context.main_tags or [])
        except Exception:
            pass
        return context

    def expand_preset_tokens(self, tags: list[str], context: PromptContext) -> list[str]:
        """`preset:...` 토큰을 실제 태그로 푼다. **파이프라인 밖에서 쓰는 공개 입구.**

        ⚠️ 메인 프롬프트 입력창의 Generate 경로는 이 파이프라인을 안 탄다
        (`HeadlessGenerationService._expand_input_wildcards`). 그래서 입력창에 친
        `preset:` 토큰이 전개되지 않은 채 NAI 로 나가 메타데이터에 문자열 그대로
        박혔다(사용자 제보 2026-08-21). 그쪽이 이 메서드를 부른다.

        **로직을 복제하지 마라.** 두 경로가 갈라지면 같은 토큰이 화면에 따라 다르게
        풀린다.
        """
        return self._expand_preset_tokens(tags, context)

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

        # 인물 태그 세트 — 모듈 상수(PERSON_TAG_SETS/ALL_PERSON_TAGS)를 쓴다.
        person_sets = PERSON_TAG_SETS
        all_person_tags = ALL_PERSON_TAGS
        
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

        # Category Annotation: `#랜덤프롬프트` 한 줄 대신 카테고리 주석으로 펼친다.
        # filter_manager 가 없으면(데이터 미적재) 분류가 전부 `#추가:` 로 쏟아지므로
        # 켜져 있어도 **예전 동작으로 되돌린다** - 주석만 있고 분류가 없는 화면이
        # 더 나쁘다.
        annotate = bool(context.metadata.get('category_annotation'))
        annotation_filter_manager = getattr(self.app_context, 'filter_data_manager', None)
        if annotate and not annotation_filter_manager:
            annotate = False
            context.metadata['category_annotation_degraded'] = True

        if annotate:
            converted_main_tags = build_annotated_main_tags(
                converted_main_tags, annotation_filter_manager)
        elif converted_main_tags:
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
        # ⚠️ 주석을 켜면 표식이 **본문 중간에도** 온다. 가중치 래핑은 비가중치 구간을
        #    통째로 `(...:1.2)` 로 감싸는데, 표식이 그 구간에 끼면 `(#의상:` 이 나온다.
        #    예전에는 표식이 맨 앞 하나뿐이라 `first_non_hash` 로 충분했다.
        #    표식 자리를 제외 집합에 넣어 구간이 거기서 끊기게 한다.
        if not is_nai:
            weighted_indices = set(weighted_indices) | {
                index for index, tag in enumerate(context.main_tags)
                if isinstance(tag, str) and tag.startswith('#')
            }

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
                safe_print(f"🎨 ANIMA 모드: 태그 삽입 완료 (인덱스 {at_index}): {', '.join(anima_tags)}")
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
                safe_print(f"🎨 ANIMA 모드: @ 태그 없음, 태그를 맨 뒤에 삽입: {', '.join(anima_tags)}")

        elif annotate:
            # 인원 수 -> #작품: -> #캐릭터: -> #아티스트: -> 선행고정
            #
            # ⚠️ 문단을 가르는 빈 줄은 **직접 넣지 않는다.** `get_all_tags()` 가
            #    prefix 와 main 꼬리에 `\n\n` 을 이미 붙인다(`prompt_context.py`).
            #    여기서 또 넣으면 빈 줄이 두 겹으로 나온다 - 실제로 그렇게 나왔다.
            identity_block = build_identity_block(
                context.metadata.get('annotation_copyright', ''),
                context.metadata.get('annotation_character', ''),
                context.metadata.get('annotation_artist', ''),
            )
            context.prefix_tags = (
                sorted_person_tags + identity_block + context.prefix_tags
            )
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
                safe_print(f"🎨 {label} 모드: main_tags 가중치 {prompt_weight} 적용 — {run_count}개 구간, 가중치 태그 {len(weighted_indices)}개 제외")
            else:
                safe_print(f"🎨 {label} 모드: main_tags 가중치 입력 {raw_prompt_weight} → 래핑 생략")

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
