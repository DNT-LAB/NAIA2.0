import copy
import random
import re
from typing import Any, Set

from core.prompt_context import PromptContext
from core.prompt_engineering_settings import (
    get_prompt_engineering_store,
    normalize_preset_main_settings,
)
from core.tag_filter_helpers import apply_tag_filters
from core.wildcard_processor import split_tags_smart


_PERSON_TAGS = frozenset({
    "1boy", "2boys", "3boys", "4boys", "5boys", "6+boys",
    "1girl", "2girls", "3girls", "4girls", "5girls", "6+girls",
    "1other", "2others", "3others", "4others", "5others", "6+others",
})
_WEBUI_WEIGHT_EXTRACT = re.compile(r'^\((.*):[\d.]+\)$')
_CLOSED_EYE_STATE_TAGS = frozenset({
    "blind",
    "blindfold",
    "closed eyes",
    "covered eyes",
    "covering eyes",
    "eyes covered",
    "no eyes",
})


def _split_settings(settings: dict[str, Any]) -> dict[str, Any]:
    return {
        "pre_prompt": split_tags_smart(settings.get("pre_prompt", "")),
        "post_prompt": split_tags_smart(settings.get("post_prompt", "")),
        "auto_hide": split_tags_smart(settings.get("auto_hide_prompt", "")),
        "preprocessing_options": dict(settings.get("preprocessing_options") or {}),
    }


def _json_safe_debug_value(value):
    if value is None or value != value:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "item"):
        try:
            return _json_safe_debug_value(value.item())
        except Exception:
            pass
    return str(value)


def _normalize_closed_eyes_tag(tag: Any) -> str:
    text = str(tag or "").strip().lower().replace("_", " ")
    text = re.sub(r'^[\d.]+::\s*', '', text)
    text = re.sub(r'\s*::$', '', text)
    match = _WEBUI_WEIGHT_EXTRACT.match(text)
    if match:
        text = match.group(1).strip()
    text = text.strip("{}[]() ")
    return re.sub(r'\s+', ' ', text)


def _is_closed_eye_state_tag(tag: Any) -> bool:
    return _normalize_closed_eyes_tag(tag) in _CLOSED_EYE_STATE_TAGS


def _is_eye_feature_tag(tag: Any) -> bool:
    normalized = _normalize_closed_eyes_tag(tag)
    if not normalized or normalized in _CLOSED_EYE_STATE_TAGS:
        return False
    return bool(re.search(r'\beyes?\b|\bpupils?\b', normalized))


def _should_apply_closed_eyes_sync(context: PromptContext) -> bool:
    random_prompt_tags = list(getattr(context, "main_tags", []) or [])
    random_prompt_tags.extend(list(getattr(context, "global_append_tags", []) or []))
    if not any(_is_closed_eye_state_tag(tag) for tag in random_prompt_tags):
        return False
    return not any(_is_eye_feature_tag(tag) for tag in random_prompt_tags)


def _leading_open_parens(raw: str) -> str:
    """raw 서브태그 선행부의 여는 괄호('(')만 추출(사이 공백은 무시). 구조 보존용."""
    out = []
    for ch in raw:
        if ch == "(":
            out.append("(")
        elif ch.isspace():
            continue
        else:
            break
    return "".join(out)


def _remove_eye_feature_tags(tags: list) -> tuple[list, list]:
    """Closed Eyes Sync: eye-feature 태그를 제거하되 **괄호 균형을 깨지 않는다**.

    ⚠️ ``split_tags_smart`` 가 괄호를 추적하지 않아 가중치 그룹 ``(__wc__, tag:0.75)`` 는
    ``(__wc__`` / ``tag:0.75)`` 두 조각으로 쪼개진다. 와일드카드가 'eyes' 포함값으로
    전개되면(예: ``(blue eyes, blonde hair``) 토큰 전체를 지우던 기존 로직이 그룹의 여는
    ``(`` 와 비-eye 태그(blonde hair)까지 통째로 날려 닫는 ``)`` 가 고아가 됐다(사용자 보고,
    ComfyUI/WEBUI 전용 — Codex 적대리뷰 확인). → 콤마/불균형 괄호를 가진 '조각' 토큰은
    콤마로 쪼개 **eye 서브태그만 제거**하고, 제거된 서브태그의 선행 여는 괄호는 다음 생존
    서브태그로 이월해 균형을 유지한다. 모든 서브태그가 eye라 비어도 선행 ``(`` 는 보존한다
    (닫는 ``)`` 고아 방지). 단순 토큰(콤마 없고 괄호 균형, 예: ``blue eyes`` /
    ``(green pupils:0.8)``)은 기존대로 통째 판정한다(회귀 방지·NAI ``::`` 경로 불변)."""
    kept: list = []
    removed: list = []
    for tag in tags or []:
        text = str(tag)
        # 단순 토큰: 콤마 없고 괄호 균형 → 기존 동작(통째 판정).
        if "," not in text and (text.count("(") == text.count(")")):
            if _is_eye_feature_tag(text):
                removed.append(tag)
            else:
                kept.append(tag)
            continue
        # 분절/복합 토큰(쪼개진 가중치 그룹 조각): 콤마로 나눠 eye 서브태그만 제거.
        survivors: list[str] = []
        pending_open = ""
        changed = False
        for raw_part in text.split(","):
            core = raw_part.strip()
            if core and _is_eye_feature_tag(core):
                removed.append(core)
                changed = True
                pending_open += _leading_open_parens(raw_part)  # 구조용 여는 괄호 이월
                continue
            if not core:
                continue
            survivors.append(pending_open + core)
            pending_open = ""
        if not changed:
            kept.append(tag)  # 아무것도 안 지웠으면 원본 그대로(공백/형태 보존)
            continue
        if survivors:
            if pending_open:  # 드문 dangling 여는 괄호 — 괄호 수 보존
                survivors[-1] = survivors[-1] + pending_open
            kept.append(", ".join(survivors))
        elif pending_open:
            kept.append(pending_open)  # 전부 eye → 닫는 ')' 고아 방지 위해 lone '(' 보존
    return kept, removed


def _sync_closed_eyes_character_list(characters: Any) -> list[dict]:
    if not isinstance(characters, list):
        return []
    changes = []
    new_characters = []
    for idx, prompt in enumerate(characters):
        if not isinstance(prompt, str):
            new_characters.append(prompt)
            continue
        prompt_tags = split_tags_smart(prompt)
        kept, removed = _remove_eye_feature_tags(prompt_tags)
        if removed:
            changes.append({"index": idx, "removed": removed})
            new_characters.append(", ".join(kept))
        else:
            new_characters.append(prompt)
    if changes:
        characters[:] = new_characters
    return changes


def _sync_closed_eyes_loaded_character_module(
    app_context,
    already_synced: Any = None,
    *,
    require_same_source: bool = False,
) -> list[dict]:
    controller = getattr(app_context, "middle_section_controller", None)
    if not controller or not hasattr(controller, "get_loaded_module_instance"):
        return []
    try:
        char_mod = controller.get_loaded_module_instance("CharacterModule")
    except Exception:
        return []
    if not char_mod or not getattr(char_mod, "activate_checkbox", None):
        return []
    try:
        if not char_mod.activate_checkbox.isChecked():
            return []
    except Exception:
        return []

    try:
        clone = char_mod.get_character_modifiable_clone()
    except Exception:
        clone = getattr(char_mod, "modifiable_clone", None)
    if not isinstance(clone, dict):
        return []

    characters = clone.get("characters")
    if require_same_source and characters is not already_synced:
        return []
    if already_synced is not None and characters is already_synced:
        changes = []
    else:
        changes = _sync_closed_eyes_character_list(characters)

    if changes or characters is already_synced:
        sync_fn = getattr(char_mod, "sync_external_prompt_edits", None)
        if callable(sync_fn):
            try:
                sync_fn()
            except Exception:
                pass
    return changes


def _compress_implied_main_tags(main_tags: list) -> list:
    entries = []
    for tag in main_tags:
        text = tag.strip()
        if text and not text.startswith("#"):
            entries.append((tag, set(text.split())))
    if len(entries) < 2:
        return []
    to_remove = {}
    for i, (tag_a, words_a) in enumerate(entries):
        for j, (tag_b, words_b) in enumerate(entries):
            if i != j and words_a < words_b:
                to_remove[tag_a] = tag_b
                break
    if not to_remove:
        return []
    main_tags[:] = [tag for tag in main_tags if tag not in to_remove]
    return [{"removed": key, "by": value} for key, value in sorted(to_remove.items())]


class _PromptEngineeringAdvancedModuleBridge:
    def __init__(self, app_context):
        self.app_context = app_context

    def module(self):
        controller = getattr(self.app_context, "middle_section_controller", None)
        if not controller or not hasattr(controller, "get_module_instance"):
            # Headless 런타임에는 데스크톱 MiddleSectionController 가 없다
            # (headless_context_bootstrap: middle_section_controller=None).
            # e621 Auto-Boost / Danbooru Auto-Weight 알고리즘은 Qt-free 서비스로
            # 포팅되어 데스크톱 모듈의 메서드 인터페이스를 그대로 노출하므로,
            # post_processing / after_wildcard 훅 배선이 무수정으로 이 서비스를 구동한다.
            from core.headless_prompt_boost_service import get_headless_prompt_boost_service
            return get_headless_prompt_boost_service(self.app_context)
        try:
            module = controller.get_module_instance("PromptEngineeringModule")
            if module and hasattr(module, "apply_settings"):
                module.apply_settings(get_prompt_engineering_store(self.app_context).collect_settings())
            return module
        except Exception as exc:
            print(f"[WARN] Prompt Engineering advanced module load failed: {exc}")
            return None


class PromptEngineeringHeadlessPostHook:
    def __init__(self, app_context):
        self.app_context = app_context
        self._advanced = _PromptEngineeringAdvancedModuleBridge(app_context)

    def get_title(self):
        return "Prompt Engineering"

    def get_pipeline_hook_info(self):
        return {
            "target_pipeline": "PromptProcessor",
            "hook_point": "post_processing",
            "priority": 10,
        }

    def _current_options(self) -> dict[str, Any]:
        event_stream = getattr(self.app_context, "event_stream_runtime", None)
        frozen = (
            event_stream.get_frozen_prompt_engineering_options()
            if event_stream and event_stream.should_freeze_prompt_engineering()
            else None
        )
        if frozen is not None:
            return frozen

        session_override = getattr(self.app_context, "session_p_eng_override", None)
        if session_override is not None:
            return {
                "pre_prompt": split_tags_smart(session_override.get("pre_prompt", "")),
                "post_prompt": split_tags_smart(session_override.get("post_prompt", "")),
                "auto_hide": split_tags_smart(session_override.get("auto_hide", "")),
                "preprocessing_options": dict(session_override.get("preprocessing_options") or {}),
            }

        controller = getattr(self.app_context, "middle_section_controller", None)
        loaded_module = None
        if controller and hasattr(controller, "get_loaded_module_instance"):
            loaded_module = controller.get_loaded_module_instance("PromptEngineeringModule")
        if loaded_module and hasattr(loaded_module, "get_parameters"):
            try:
                return copy.deepcopy(loaded_module.get_parameters())
            except Exception as exc:
                print(f"⚠️ PromptEngineering loaded module parameters unavailable: {exc}")

        settings = get_prompt_engineering_store(self.app_context).collect_settings()
        return _split_settings(settings)

    def _category_filter_overrides(self) -> dict:
        """카테고리별 전처리 필터 오버라이드를 context 캐시에서 lazy load.

        매 생성마다 디스크를 읽지 않도록 context._pp_category_filter_cache 에 1회
        적재하고, 저장 커맨드(set_param category_filters)가 write-through 로 갱신한다."""
        ctx = self.app_context
        cache = getattr(ctx, "_pp_category_filter_cache", None)
        if cache is None:
            from core.prompt_engineering_settings import load_category_filter_overrides

            runtime_paths = getattr(ctx, "runtime_paths", None)
            try:
                cache = load_category_filter_overrides(save_root=getattr(runtime_paths, "save_dir", None))
            except Exception:
                cache = {}
            setattr(ctx, "_pp_category_filter_cache", cache)
        return cache if isinstance(cache, dict) else {}

    def execute_pipeline_hook(self, context: PromptContext) -> PromptContext:
        if getattr(self.app_context, "skip_prompt_engineering_hook", False):
            return context

        options = self._current_options()
        skip_preprocessing = bool(getattr(self.app_context, "skip_prompt_engineering_auto_hide", False))
        filter_manager = getattr(self.app_context, "filter_data_manager", None)

        prefix_tags = list(options.get("pre_prompt") or []) + list(context.prefix_tags)
        postfix_tags = list(context.postfix_tags) + list(options.get("post_prompt") or [])
        main_tags = context.main_tags
        removed_tags = context.removed_tags
        source_row = context.source_row
        checkbox_options = {} if skip_preprocessing else dict(options.get("preprocessing_options") or {})

        # 이벤트 스트림(Storyteller) 중에는 Tag Implication 압축을 소비 지점에서 강제
        # OFF — 'bikini pull' 같은 새 행 태그가 carry로 유지해야 할 'bikini' 등 의상
        # 태그를 소거해 의상 전이를 깨뜨린다(사용자 결정). frozen 캡처의 fallback
        # 분기만 믿으면 모듈/세션 override 등 다른 options 경로가 빠져나간다 —
        # 캐릭터 freeze와 같은 교훈: 강제는 실제 적용되는 단일 소비 지점에서.
        event_stream = getattr(self.app_context, "event_stream_runtime", None)
        if checkbox_options and event_stream is not None and getattr(event_stream, "is_active", False):
            checkbox_options["tag_implication_compression"] = False

        if not skip_preprocessing:
            api_mode = context.settings.get("api_mode")
            sampling_mode = context.settings.get("comfyui_sampling_mode")
            is_anima_mode = api_mode == "COMFYUI" and sampling_mode == "anima"

            if not checkbox_options.get("remove_work_title"):
                copyright = source_row.get("copyright")
                if isinstance(copyright, str) and copyright:
                    if is_anima_mode:
                        context.metadata["anima_copyright"] = copyright
                    else:
                        prefix_tags.insert(0, copyright)

            if not checkbox_options.get("remove_author"):
                artist = source_row.get("artist")
                if isinstance(artist, str) and artist:
                    if is_anima_mode:
                        context.metadata["anima_artist"] = artist
                    else:
                        prefix_tags.insert(0, artist)

            if not checkbox_options.get("remove_character_name"):
                character = source_row.get("character")
                if isinstance(character, str) and character:
                    if is_anima_mode:
                        context.metadata["anima_character"] = character
                    else:
                        prefix_tags.insert(0, character)

            # ⚠️ 주석은 **본문(랜덤 프롬프트)에만** 단다. 작품·캐릭터·아티스트에는
            #    안 단다(사용자 회수 2026-08-31: "칸만 차지하네요"). 값이 짧은데
            #    주석이 두 줄을 먹었고, 특히 `#아티스트:` 는 바로 뒤 선행고정
            #    와일드카드와 붙어 그것들이 아티스트인 것처럼 읽혔다.
            #    이 셋은 예전 그대로 prefix 머리에 꽂는다.
            if checkbox_options.get("category_annotation") and not is_anima_mode:
                context.metadata["category_annotation"] = True

        auto_hide = [] if skip_preprocessing else list(options.get("auto_hide") or [])
        context.metadata["_closed_eyes_sync_enabled"] = (
            not skip_preprocessing and checkbox_options.get("closed_eyes_sync", False)
        )

        source_tags = list(main_tags)
        original_count = len(main_tags)
        filter_result = apply_tag_filters(
            main_tags,
            removed_tags,
            checkbox_options,
            auto_hide,
            filter_manager,
            track_clothing_regions=True,
            # ⚠️ 전처리를 건너뛰는 경로에서는 오버라이드도 넘기지 않는다. 예전에는
            #    라운드 본문이 전부 `if enabled:` 안이라 빈 checkbox_options 만으로
            #    막혔지만, 개별 숨김(hide)은 스위치를 안 보므로 여기서 막아야 한다.
            #    '전처리 건너뛰기' 인데 태그가 사라지면 사용자는 원인을 못 찾는다.
            category_overrides=None if skip_preprocessing else self._category_filter_overrides(),
        )
        if filter_result.get("removed_clothes_by_region"):
            context.metadata["removed_clothes_by_region"] = filter_result["removed_clothes_by_region"]
        if filter_result.get("filter_log"):
            context.metadata["filter_log"] = filter_result["filter_log"]
            context.metadata["original_tag_count"] = original_count
            context.metadata["remaining_tag_count"] = len(main_tags)
        context.metadata["debug_source_info"] = {
            "character": _json_safe_debug_value(source_row.get("character", "")),
            "copyright": _json_safe_debug_value(source_row.get("copyright", "")),
            "artist": _json_safe_debug_value(source_row.get("artist", "")),
            "id": _json_safe_debug_value(source_row.get("id", "")),
        }

        if not skip_preprocessing and checkbox_options.get("tag_implication_compression"):
            compressed = _compress_implied_main_tags(main_tags)
            if compressed:
                context.metadata["implication_compressed_tags"] = compressed

        if not skip_preprocessing and checkbox_options.get("danbooru_auto_weight"):
            module = self._advanced.module()
            if module and hasattr(module, "_apply_danbooru_auto_weight"):
                pre_weight_tags = {tag.strip() for tag in main_tags}
                module._apply_danbooru_auto_weight(main_tags, context)
                context.metadata["_danbooru_weight_applied_tags"] = pre_weight_tags
                if context.settings.get("wildcard_standalone", False):
                    context.metadata["_danbooru_weight_deferred"] = True

        if not skip_preprocessing and checkbox_options.get("e621_auto_boost"):
            if context.settings.get("wildcard_standalone", False):
                context.metadata["_e621_source_tags"] = list(source_tags)
            else:
                module = self._advanced.module()
                if module and hasattr(module, "_run_e621_boost"):
                    module._run_e621_boost(context, list(prefix_tags) + source_tags, main_tags)

        context.prefix_tags = prefix_tags
        context.postfix_tags = postfix_tags
        context.main_tags = main_tags
        return context


class PromptEngineeringClosedEyesHeadlessHook:
    def __init__(self, app_context):
        self.app_context = app_context

    def get_title(self):
        return "Closed Eyes Sync"

    def execute_pipeline_hook(self, context: PromptContext) -> PromptContext:
        if not context.metadata.get("_closed_eyes_sync_enabled"):
            return context
        if not _should_apply_closed_eyes_sync(context):
            return context

        api_mode = str(context.settings.get("api_mode") or "").upper()
        sync_info = {"mode": api_mode, "prefix_removed": [], "postfix_removed": [], "character_removed": []}
        if api_mode == "NAI":
            characters = context.settings.get("characters")
            sync_info["character_removed"].extend(_sync_closed_eyes_character_list(characters))
            generation_request = context.settings.get("_generation_request")
            nai_characters = getattr(generation_request, "nai_characters", None) if generation_request else None
            request_characters = getattr(nai_characters, "characters", None)
            if request_characters is not None and request_characters is not characters:
                sync_info["character_removed"].extend(_sync_closed_eyes_character_list(request_characters))
            sync_info["character_removed"].extend(
                _sync_closed_eyes_loaded_character_module(
                    self.app_context,
                    already_synced=characters,
                    require_same_source=isinstance(characters, list),
                )
            )
        elif api_mode in {"WEBUI", "COMFYUI"}:
            context.prefix_tags, sync_info["prefix_removed"] = _remove_eye_feature_tags(context.prefix_tags)
            context.postfix_tags, sync_info["postfix_removed"] = _remove_eye_feature_tags(context.postfix_tags)

        if any(sync_info[key] for key in ("prefix_removed", "postfix_removed", "character_removed")):
            context.metadata["closed_eyes_sync"] = sync_info
        return context


class PromptEngineeringAdvancedAfterWildcardHook:
    def __init__(self, app_context, method_name: str, title: str, predicate):
        self.app_context = app_context
        self.method_name = method_name
        self.title = title
        self.predicate = predicate
        self._advanced = _PromptEngineeringAdvancedModuleBridge(app_context)

    def get_title(self):
        return self.title

    def execute_pipeline_hook(self, context: PromptContext) -> PromptContext:
        if not self.predicate(context):
            return context
        module = self._advanced.module()
        method = getattr(module, self.method_name, None) if module else None
        if callable(method):
            return method(context)
        return context


class PromptEngineeringOutfitContextHeadlessHook:
    def __init__(self, app_context):
        self.app_context = app_context

    def get_title(self):
        return "Outfit Context Resolver"

    def execute_pipeline_hook(self, context: PromptContext) -> PromptContext:
        filter_manager = getattr(self.app_context, "filter_data_manager", None)
        if filter_manager is None or not getattr(filter_manager, "_clothing_event_meta", None):
            return context
        get_meta = getattr(filter_manager, "get_clothing_event_meta", None)
        get_region = getattr(filter_manager, "get_garment_region", None)
        if get_meta is None or get_region is None:
            return context

        all_tags = list(getattr(context, "prefix_tags", []) or []) \
            + list(getattr(context, "main_tags", []) or []) \
            + list(getattr(context, "postfix_tags", []) or [])
        if not all_tags:
            return context

        bound_events = []
        for tag in all_tags:
            meta = get_meta(tag)
            if meta and meta.get("garment_bound"):
                bound_events.append((tag, meta))
        if not bound_events:
            return context

        clothes_set = set(getattr(filter_manager, "clothes_list", set()) or set())
        region_lookup = getattr(filter_manager, "_clothing_tag_to_region", {}) or {}
        final_tag_set = set(all_tags)
        final_clothing: Set[str] = final_tag_set & clothes_set

        source_alive_clothing: Set[str] = set()
        source_row = getattr(context, "source_row", None)
        if source_row is not None:
            try:
                general_raw = source_row.get("general", "") if hasattr(source_row, "get") else ""
                general_raw = str(general_raw) if general_raw else ""
            except Exception:
                general_raw = ""
            if general_raw:
                for raw in general_raw.split(","):
                    token = raw.strip()
                    if token and token in clothes_set and token in final_tag_set:
                        source_alive_clothing.add(token)

        user_garments = list(final_clothing - source_alive_clothing)
        if not user_garments:
            return context

        user_regions: Set[str] = set()
        user_garment_nouns: Set[str] = set()
        for garment in user_garments:
            region = get_region(garment)
            if region:
                user_regions.add(region)
                if region == "FULL_BODY":
                    user_regions.update({"UPPER_BODY", "WAIST_HIP"})
            padded = f" {garment.lower()} "
            for known in region_lookup:
                if known and f" {known} " in padded:
                    user_garment_nouns.add(known)

        to_remove: Set[str] = set()
        for tag, meta in bound_events:
            event_noun = meta.get("garment_noun")
            event_region = meta.get("region")
            if event_noun and event_noun in user_garment_nouns:
                continue
            if event_region == "FULL_BODY":
                if user_regions:
                    to_remove.add(tag)
                continue
            if event_region and event_region in user_regions:
                to_remove.add(tag)

        if not to_remove:
            return context

        for list_name in ("prefix_tags", "main_tags", "postfix_tags"):
            tags = getattr(context, list_name, None)
            if tags:
                setattr(context, list_name, [tag for tag in tags if tag not in to_remove])
        context.metadata.setdefault("outfit_context_removed", []).extend(sorted(to_remove))
        return context


class PromptEngineeringRandomizedSubscriber:
    def __init__(self, app_context):
        self.app_context = app_context

    def handle(self, _data=None):
        event_stream = getattr(self.app_context, "event_stream_runtime", None)
        if event_stream and event_stream.should_freeze_random_prompt_side_effects():
            return
        store = get_prompt_engineering_store(self.app_context)
        state = store.state()
        if state.get("current_preset") != "*randomized":
            return
        pool = list(state.get("randomized_preset_list") or [])
        if not pool:
            print("⚠️ 랜덤 프리셋 목록이 비어있습니다")
            return
        selected = random.choice(pool)
        preset_data = store.read_preset_data(selected, store.mode())
        module_settings = dict(preset_data.get("module_settings") or {})
        updates = {}
        base_pre = str(module_settings.get("pre_prompt", ""))
        wc_front = str(state.get("randomized_wildcard_front") or "").strip()
        wc_back = str(state.get("randomized_wildcard_back") or "").strip()
        wc_on = bool(state.get("randomized_wildcard_enabled"))
        if wc_on and (wc_front or wc_back):
            # Rebuild the leading prompt as: <front wildcard>, <rolled preset Prefix>, <back wildcard>.
            # 1.5 컨벤션: artist 류는 앞(front), character 류는 뒤(back). 토큰(__character__ 등)은
            # 미전개 상태로 둬서 파이프라인 와일드카드 단계가 매 생성 새로 reroll한다. 매 롤마다
            # 완전히 재구성하므로 키 없는/비활성 프리셋에서도 stale 토큰이 남지 않는다.
            trimmed = base_pre.strip()
            if trimmed.endswith(","):
                trimmed = trimmed[:-1].rstrip()
            updates["pre_prompt"] = ", ".join(part for part in (wc_front, trimmed, wc_back) if part)
        elif "pre_prompt" in module_settings:
            updates["pre_prompt"] = base_pre
        if "post_prompt" in module_settings:
            updates["post_prompt"] = module_settings.get("post_prompt", "")
        if updates:
            store.apply_settings(updates)

        main_settings = normalize_preset_main_settings(preset_data.get("main_settings") or {})
        main_settings.pop("prompt", None)
        if main_settings and getattr(self.app_context, "main_window", None):
            module = _PromptEngineeringAdvancedModuleBridge(self.app_context).module()
            if module and hasattr(module, "apply_main_ui_settings"):
                module.apply_main_ui_settings(main_settings)
        print(f"Random preset applied: {selected}")


def register_prompt_engineering_headless_runtime(app_context) -> None:
    if getattr(app_context, "prompt_engineering_headless_runtime_registered", False):
        return
    app_context.prompt_engineering_headless_runtime_registered = True
    post_hook = PromptEngineeringHeadlessPostHook(app_context)
    app_context.register_pipeline_hook(post_hook.get_pipeline_hook_info(), post_hook)
    for priority, hook in (
        (5, PromptEngineeringClosedEyesHeadlessHook(app_context)),
        (
            10,
            PromptEngineeringAdvancedAfterWildcardHook(
                app_context,
                "_execute_e621_after_wildcard",
                "e621 Auto-Boost",
                lambda context: "_e621_source_tags" in context.metadata,
            ),
        ),
        (
            15,
            PromptEngineeringAdvancedAfterWildcardHook(
                app_context,
                "_execute_danbooru_weight_after_wildcard",
                "Danbooru Auto-Weight",
                lambda context: (
                    "_danbooru_weight_deferred" in context.metadata
                    or "_danbooru_weight_applied_tags" in context.metadata
                ),
            ),
        ),
        (20, PromptEngineeringOutfitContextHeadlessHook(app_context)),
    ):
        app_context.register_pipeline_hook(
            {"target_pipeline": "PromptProcessor", "hook_point": "after_wildcard", "priority": priority},
            hook,
        )
    subscriber = PromptEngineeringRandomizedSubscriber(app_context)
    app_context.subscribe("random_prompt_triggered", subscriber.handle)
