"""Headless Prompt Engineering module state service."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from core.nai_model_contract import NAI_PRESET_FILTER_GROUPS, nai_model_badge

HIRES_OVERLAY_DISALLOWED_NAMES = {"", "*randomized", "(프리셋 없음)"}


# 어느 프리셋을 보고 친 글인지 표식을 함께 받는 키들(위 `_text_and_preset_stamp`).
_STAMPED_TEXT_KEYS = frozenset({"pre_prompt", "post_prompt", "auto_hide"})


class HeadlessPromptEngineeringService:
    def __init__(self, context: Any):
        self.context = context

    @staticmethod
    def _empty_debug_snapshot() -> dict[str, Any]:
        return {
            "source_info": {},
            "filter_log": [],
            "original_count": 0,
            "remaining_count": 0,
            "e621_info": None,
            "implication_info": [],
        }

    @staticmethod
    def _debug_snapshot_from_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(metadata, dict):
            return HeadlessPromptEngineeringService._empty_debug_snapshot()

        def int_value(value: Any) -> int:
            try:
                return int(value or 0)
            except (TypeError, ValueError):
                return 0

        return {
            "source_info": copy.deepcopy(metadata.get("debug_source_info") or {}),
            "filter_log": copy.deepcopy(metadata.get("filter_log") or []),
            "original_count": int_value(metadata.get("original_tag_count")),
            "remaining_count": int_value(metadata.get("remaining_tag_count")),
            "e621_info": copy.deepcopy(metadata.get("e621_debug_info")),
            "implication_info": copy.deepcopy(metadata.get("implication_compressed_tags") or []),
        }

    def debug_snapshot(self) -> dict[str, Any]:
        current_context = getattr(self.context, "current_prompt_context", None)
        current_metadata = getattr(current_context, "metadata", None)
        snapshot = self._debug_snapshot_from_metadata(current_metadata)
        if snapshot != self._empty_debug_snapshot():
            return snapshot

        latest_run = getattr(getattr(self.context, "pipeline_run_registry", None), "latest_prompt_run", None)
        if not callable(latest_run):
            return snapshot
        run = latest_run()
        return self._debug_snapshot_from_metadata(getattr(run, "metadata", None))

    def state(self) -> dict[str, Any]:
        from core.prompt_engineering_settings import (
            get_prompt_engineering_store,
            load_category_filter_overrides,
            load_ollama_boost_settings,
        )

        context = self.context
        store = get_prompt_engineering_store(context)
        self.ensure_first_run_recommended_preset()
        settings = store.collect_settings()
        # Ollama Boost 설정은 *전역*(디스크 SSOT)이라 모드별 캐시(settings)가 아니라
        # 디스크에서 fresh 읽는다 — 모드 전환 시 stale 값 표시 → 재저장 시 데이터 손실
        # (다른 모드에서 바꾼 nl_weight를 덮어씀) 방지. boost-time 읽기와 동일 SSOT.
        _runtime_paths = getattr(context, "runtime_paths", None)
        ollama_boost = load_ollama_boost_settings(save_root=getattr(_runtime_paths, "save_dir", None))
        # 카테고리 필터 오버라이드도 전역 디스크 SSOT — 모드 캐시가 아니라 fresh 읽는다.
        category_filters = load_category_filter_overrides(save_root=getattr(_runtime_paths, "save_dir", None))
        state = store.state()
        preset_options = store.preset_options()

        def preset_summary(
            name: str,
            mode: str | None = None,
            thumbnails: dict[str, str] | None = None,
        ) -> dict[str, Any]:
            if name == "*randomized":
                return {
                    "name": name,
                    "api_mode": context.get_api_mode(),
                    "description": "Randomized preset pool",
                    "pre_prompt_preview": "",
                    "post_prompt_preview": "",
                    "thumbnail_url": "",
                }
            data = store.read_preset_data(name, mode or context.get_api_mode())
            module_settings = data.get("module_settings") if isinstance(data, dict) else {}
            module_settings = module_settings if isinstance(module_settings, dict) else {}
            api_mode = str(data.get("api_mode") or mode or context.get_api_mode())
            # 프리셋이 어느 모델로 저장됐는지. Quick Preset 목록의 `[NAI4.5C]` 배지와
            # 그 위 필터 바(ALL/NAI5/NAI4.5/ETC)가 이 값을 쓴다. NAI 프리셋만 의미가
            # 있고(다른 모드는 모델 개념이 다르다), 모델을 안 적고 저장된 옛 프리셋은
            # 라벨 없이 ETC 로 간다 - 숨기면 다른 갈래에서 사라져 버린다.
            badge = {"key": "", "label": "", "family": "", "group": "etc", "variant": ""}
            if api_mode.upper() == "NAI":
                main_settings = data.get("main_settings") if isinstance(data, dict) else {}
                main_settings = main_settings if isinstance(main_settings, dict) else {}
                badge = nai_model_badge(main_settings.get("model"), context)
            return {
                "name": name,
                "api_mode": api_mode,
                "model_key": badge["key"],
                "model_label": badge["label"],
                "model_family": badge["family"],
                "model_group": badge["group"],
                "model_variant": badge.get("variant", ""),
                "description": str(data.get("description") or ""),
                "pre_prompt_preview": str(module_settings.get("pre_prompt") or ""),
                # 프리셋 검색이 볼 나머지 본문. prefix 만 실으면 postfix 에만 있는
                # 태그로 찾을 수 없어 "포함하는 프리셋 검색"이 반만 맞는다.
                # read_preset_data 는 이미 읽어 둔 것이라 추가 IO 는 없다.
                # auto_hide 는 **싣지 않는다** — 대개 프리셋끼리 공유하는 값이라
                # 검색에 넣으면 전부가 걸려 필터가 무뎌진다(사용자 지적).
                "post_prompt_preview": str(module_settings.get("post_prompt") or ""),
                # 썸네일 SSOT는 previews 디렉터리의 파일 — 프리셋 JSON에는
                # thumbnail_url이 기록된 적이 없어 항상 "No image"가 나오던 버그.
                # 목록 단위 벌크 맵으로 조회(프리셋별 stat 프로브 방지).
                "thumbnail_url": str((thumbnails or {}).get(name) or data.get("thumbnail_url") or ""),
            }

        webui_presets = store.list_preset_names("WEBUI")
        from core.prompt_engineering_settings import preset_thumbnail_url_map

        current_mode_key = str(context.get_api_mode() or "").strip().upper()
        current_thumbs = preset_thumbnail_url_map(context, list(preset_options), current_mode_key)
        webui_thumbs = preset_thumbnail_url_map(context, list(webui_presets), "WEBUI")
        payload = {
            "preset": state["current_preset"],
            "preset_options": preset_options,
            "preset_summaries": [preset_summary(name, thumbnails=current_thumbs) for name in preset_options],
            # Quick Preset 위 필터 바의 갈래. 프론트가 이름을 박지 않도록 계약에서 준다.
            # NAI 모드에서만 의미가 있으므로 다른 모드에서는 빈 목록을 보낸다.
            "preset_filter_groups": (
                [{"key": k, "label": lbl} for k, lbl in NAI_PRESET_FILTER_GROUPS]
                if current_mode_key == "NAI" else []
            ),
            "webui_preset_options": webui_presets,
            "webui_preset_summaries": [
                preset_summary(name, "WEBUI", thumbnails=webui_thumbs) for name in webui_presets
            ],
            "randomized_active": state["current_preset"] == "*randomized",
            "randomized_preset_list": list(state["randomized_preset_list"]),
            "randomized_available_presets": store.randomized_available_presets(),
            "randomized_wildcard_front": str(state.get("randomized_wildcard_front") or ""),
            "randomized_wildcard_back": str(state.get("randomized_wildcard_back") or ""),
            "randomized_wildcard_enabled": bool(state.get("randomized_wildcard_enabled")),
            "pre_prompt": settings.get("pre_prompt", ""),
            "post_prompt": settings.get("post_prompt", ""),
            "auto_hide": settings.get("auto_hide_prompt", ""),
            "preprocessing": dict(settings.get("preprocessing_options") or {}),
            # 세션 전용 토글 — store가 아니라 context 세션 플래그에서 직접 읽는다(비영속).
            "ollama_auto_boost": bool(getattr(context, "ollama_auto_boost", False)),
            "e621_settings": dict(settings.get("e621_settings") or {}),
            "danbooru_settings": dict(settings.get("danbooru_weight_settings") or {}),
            "ollama_boost_settings": ollama_boost,
            "category_filters": category_filters,
            "debug_snapshot": self.debug_snapshot(),
            "preset_can_save_current": state["current_preset"] not in ("", "(프리셋 없음)", "*randomized"),
            "preset_can_delete": state["current_preset"] not in ("", "(프리셋 없음)", "*randomized", "default"),
        }
        return context._module_state_payload("prompt_engineering", payload)

    def ensure_first_run_recommended_preset(self) -> tuple[bool, str]:
        from core.prompt_engineering_settings import get_prompt_engineering_store

        context = self.context
        store = get_prompt_engineering_store(context)
        mode = context.get_api_mode()
        if mode == "COMFYUI" and not self._is_comfyui_anima_mode():
            return False, ""
        if mode not in {"NAI", "WEBUI", "COMFYUI"}:
            return False, ""
        if store.load_last_used_preset(mode):
            return False, ""
        user_presets = [
            name
            for name in store.list_preset_names(mode)
            if name not in {"", "default", "*randomized"}
        ]
        if user_presets:
            return False, ""
        ok, message = self.create_and_apply_recommended_preset(save_current=False)
        if ok:
            print(f"Remote Web: first-run recommended preset applied: {message}", flush=True)
        return ok, message

    def ensure_first_run_recommended_preset_payloads(self) -> list[dict[str, Any]]:
        ok, _message = self.ensure_first_run_recommended_preset()
        if not ok:
            return []
        context = self.context
        return [
            self.state(),
            context.generation_param_schema_payload(),
            {
                "type": "prompt_sync",
                "prompt": context.prompt_text,
                "negative": context.negative_prompt_text,
                "negative_prompt": context.negative_prompt_text,
            },
        ]

    def persist_active_settings(self) -> tuple[bool, str]:
        from core.prompt_engineering_settings import get_prompt_engineering_store

        return get_prompt_engineering_store(self.context).persist_active_settings()

    def set_param(self, key: str, value: Any) -> dict[str, Any] | list[dict[str, Any]] | None:
        from core.prompt_engineering_settings import get_prompt_engineering_store

        context = self.context
        store = get_prompt_engineering_store(context)
        text_value, stamp = self._text_and_preset_stamp(value)
        if key in _STAMPED_TEXT_KEYS and stamp:
            # ⚠️ **어느 프리셋을 보고 친 글인가.** 화면은 프리셋을 바꾼 뒤에도 잠깐
            #    앞 프리셋의 글을 들고 있다(디바운스 500ms · 창이 둘일 때의 에코).
            #    그 글이 스왑 뒤에 도착하면 살아 있는 설정이 오염되고, 이어지는
            #    저장이 그것을 파일에 박는다(사용자 제보 2026-08-25).
            #    보고 친 프리셋과 지금 프리셋이 다르면 **버린다** - 사용자는 그 글을
            #    이 프리셋에 쓰려고 친 적이 없다.
            current = str(store.state(context.get_api_mode()).get("current_preset") or "")
            if current and current != stamp:
                print(
                    f"[info] dropped stale prompt-engineering edit ({key}):"
                    f" typed for {ascii(stamp)}, current is {ascii(current)}",
                    flush=True,
                )
                return self.state()
        if key == "pre_prompt":
            store.apply_settings({"pre_prompt": text_value})
        elif key == "post_prompt":
            store.apply_settings({"post_prompt": text_value})
        elif key == "auto_hide":
            store.apply_settings({"auto_hide_prompt": text_value})
        elif key == "preset":
            if not store.set_preset(text_value):
                return context._toast(f"프리셋을 찾을 수 없습니다: {text_value}", level="error")
            return self._apply_preset_main_settings_response(store, text_value)
        elif key == "preset_save_current":
            ok, message = store.save_current_preset(main_settings=self._capture_main_settings())
            if not ok:
                return context._toast(message, level="error")
        elif key == "preset_create":
            ok, message = store.create_preset(text_value, main_settings=self._capture_main_settings())
            if not ok:
                return context._toast(message, level="error")
        elif key == "preset_apply_recommended":
            # 값은 고른 모델 키(`NAID5F` / `NAID4.5F`). 예전 클라이언트는 `"true"` 를
            # 보내는데, 그건 모델 키가 아니라 아래 판정에서 자연히 V4.5 로 떨어진다.
            ok, message = self.create_and_apply_recommended_preset(model_key=text_value)
            if not ok:
                return context._toast(message, level="error")
            return [
                context._toast(f"추천 프리셋 적용: {message}", level="success"),
                self.state(),
                context.generation_param_schema_payload(),
                {
                    "type": "prompt_sync",
                    "prompt": context.prompt_text,
                    "negative": context.negative_prompt_text,
                    "negative_prompt": context.negative_prompt_text,
                },
            ]
        elif key == "preset_delete":
            ok, message = store.delete_preset(text_value or store.state()["current_preset"])
            if not ok:
                return context._toast(message, level="error")
        elif key == "randomized_add":
            ok, message = store.add_randomized_preset(text_value)
            if not ok:
                return context._toast(message, level="error")
        elif key == "randomized_remove":
            ok, message = store.remove_randomized_preset(text_value)
            if not ok:
                return context._toast(message, level="error")
        elif key == "randomized_clear":
            store.clear_randomized_presets()
        elif key == "randomized_wildcard":
            try:
                payload = json.loads(text_value or "{}")
            except Exception:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            store.set_randomized_wildcard(
                str(payload.get("front") or ""),
                str(payload.get("back") or ""),
                bool(payload.get("enabled")),
            )
        elif key == "e621_settings":
            settings = json.loads(text_value or "{}")
            if not isinstance(settings, dict):
                return context._toast("Invalid e621 settings", level="error")
            store.save_e621_settings(settings)
            store.apply_settings({"e621_settings": settings})
        elif key == "danbooru_settings":
            settings = json.loads(text_value or "{}")
            if not isinstance(settings, dict):
                return context._toast("Invalid Danbooru settings", level="error")
            store.save_danbooru_weight_settings(settings)
            store.apply_settings({"danbooru_weight_settings": settings})
        elif key == "ollama_boost_settings":
            # 영속 설정(세션 전용 ollama_auto_boost 토글과는 별개). merge+clamp+coerce 는
            # store/normalize_ollama_boost_settings 가 담당한다(e621_settings 패턴 동일).
            from core.prompt_engineering_settings import normalize_ollama_boost_settings

            settings = json.loads(text_value or "{}")
            if not isinstance(settings, dict):
                return context._toast("Invalid Ollama Boost settings", level="error")
            normalized = normalize_ollama_boost_settings(settings)
            store.save_ollama_boost_settings(normalized)
            store.apply_settings({"ollama_boost_settings": normalized})
        elif key == "category_filters":
            # 단일 카테고리 부분 업데이트: {"category": <option_key>, "exclude": [...], "include": [...]}.
            # 전체 맵에 머지 후 전역 디스크 SSOT(pp_category_filters.json)에 영속화하고
            # 런타임 캐시를 write-through 갱신한다. 둘 다 비면 해당 카테고리 삭제.
            from core.prompt_engineering_settings import (
                CATEGORY_FILTER_OPTION_KEYS,
                load_category_filter_overrides,
                sanitize_tag_list,
                save_category_filter_overrides,
            )

            try:
                payload = json.loads(text_value or "{}")
            except Exception:
                payload = None
            if not isinstance(payload, dict):
                return context._toast("Invalid category filter settings", level="error")
            category = str(payload.get("category") or "").strip()
            if category not in CATEGORY_FILTER_OPTION_KEYS:
                return context._toast(f"Unknown filter category: {category}", level="error")
            raw_exclude = payload.get("exclude", [])
            raw_include = payload.get("include", [])
            if not isinstance(raw_exclude, list) or not isinstance(raw_include, list):
                return context._toast("Invalid category filter tags", level="error")
            exclude = sanitize_tag_list(raw_exclude)
            include = sanitize_tag_list(raw_include)
            save_root = getattr(getattr(context, "runtime_paths", None), "save_dir", None)
            overrides = load_category_filter_overrides(save_root=save_root)
            if exclude or include:
                overrides[category] = {"exclude": exclude, "include": include}
            else:
                overrides.pop(category, None)
            save_category_filter_overrides(overrides, save_root=save_root)
            # 다음 생성이 디스크 재읽기 없이 반영하도록 런타임 캐시를 갱신(정규화된 SSOT 재적재).
            context._pp_category_filter_cache = load_category_filter_overrides(save_root=save_root)
        elif key == "debug_refresh":
            pass
        elif key == "ollama_auto_boost":
            # ⚠️ 세션 전용 토글(비영속). store/preset/save 어디에도 기록하지 않는다 —
            # 항상 OFF로 시작하고 사용자가 직접 켜야만 ON. (pp_* 영속 경로와 분리)
            enabled = context._coerce_bool(value)
            context.ollama_auto_boost = enabled
            # 모델 상주 관리: ON이면 미리 warm-up(상주), OFF면 언로드. 구독자가 데몬
            # 스레드로 처리(이벤트 루프/응답 비차단). ollama_routes에서 구독.
            try:
                context.publish("ollama_auto_boost_changed", {"enabled": enabled})
            except Exception:
                pass
        elif key.startswith("pp_"):
            option_key = key[3:]
            settings = store.collect_settings()
            preprocessing = dict(settings.get("preprocessing_options") or {})
            preprocessing[option_key] = context._coerce_bool(value)
            store.apply_settings({"preprocessing_options": preprocessing})
        else:
            return None
        return self.state()

    def create_and_apply_recommended_preset(
        self, *, save_current: bool = True, model_key: str = "",
    ) -> tuple[bool, str]:
        """추천 프리셋을 만들어 즉시 적용한다.

        NAI 모드에서는 `model_key` 로 **어느 세대의 추천인지** 고른다(사용자 지시
        2026-08-21). V5 와 V4.5 는 같은 프롬프트에 다르게 반응해서 추천 묶음 자체가
        다르다 - 하나로 뭉뚱그리면 어느 쪽에서도 추천이 아니게 된다.
        빈 값이면 지금까지처럼 V4.5 추천을 쓴다(기존 동작 유지).
        """
        from core.prompt_engineering_settings import get_prompt_engineering_store

        context = self.context
        store = get_prompt_engineering_store(context)
        mode = context.get_api_mode()
        if mode == "COMFYUI":
            if not self._is_comfyui_anima_mode():
                return False, "추천 설정 적용은 COMFYUI ANIMA 모드에서만 지원됩니다."
            preset_name = self._unique_preset_name(store, "recommend_anima", mode)
            module_settings = self._comfyui_anima_recommended_module_settings()
            main_settings = self._comfyui_anima_recommended_main_settings()
        elif mode == "WEBUI":
            preset_name = self._unique_preset_name(store, "recommend", mode)
            module_settings = self._webui_recommended_module_settings()
            main_settings = self._webui_recommended_main_settings()
        elif mode == "NAI":
            from core.nai_model_contract import resolve_nai_model_for_context

            # V5 냐 아니냐로만 가른다 - 키 문자열을 잘라 판정하지 않는다(`NAID4.5`
            # 처럼 접미사 없는 키가 있어 규칙이 한 줄로 안 떨어진다).
            wants_v5 = False
            if str(model_key or "").strip():
                try:
                    wants_v5 = bool(
                        resolve_nai_model_for_context(context, model_key).uses_opus_usage_limit)
                except Exception:
                    wants_v5 = False
            preset_name = self._unique_preset_name(store, "recommend", mode)
            module_settings = store.collect_settings(mode)
            module_settings.update(
                self._nai_v5_recommended_module_settings() if wants_v5
                else self._nai_recommended_module_settings())
            main_settings = (
                self._nai_v5_recommended_main_settings() if wants_v5
                else self._nai_recommended_main_settings())
        else:
            return False, "추천 설정 적용은 현재 NAI, WEBUI 또는 COMFYUI ANIMA 모드에서만 지원됩니다."

        if save_current:
            current = store.state(mode).get("current_preset")
            if current and current not in {"", "(프리셋 없음)", "*randomized"}:
                store.save_current_preset(mode, main_settings=self._capture_main_settings())

        preset_data = {
            "api_mode": mode,
            "module_settings": module_settings,
            "main_settings": main_settings,
        }
        store.write_preset_data(preset_name, mode, preset_data)
        store.refresh(mode)
        if not store.set_preset(preset_name, mode):
            return False, f"프리셋을 적용할 수 없습니다: {preset_name}"
        self._apply_main_settings(main_settings)
        return True, preset_name

    def _is_comfyui_anima_mode(self) -> bool:
        context = self.context
        if context.get_api_mode() != "COMFYUI":
            return False
        sampling_mode = str(context.remote_params.get("sampling_mode") or "").strip().lower()
        comfyui_sampling_mode = str(context.remote_params.get("comfyui_sampling_mode") or "").strip().lower()
        workflow_type = str(
            context.remote_params.get("workflow_type")
            or context.remote_params.get("comfyui_workflow_type")
            or ""
        ).strip().lower()
        if sampling_mode:
            return sampling_mode == "anima"
        if comfyui_sampling_mode:
            return comfyui_sampling_mode == "anima"
        if workflow_type:
            return workflow_type == "unet"
        # Nothing configured yet: ANIMA is the mainstream COMFYUI model, so an
        # unconfigured COMFYUI session defaults to ANIMA — the recommended preset
        # and preprocessing apply on first entry instead of leaving the user
        # empty-handed. A loaded custom workflow sets ``workflow_type`` (handled
        # above) and an explicit eps/v_prediction choice sets ``sampling_mode``
        # (handled above), so both are still respected over this default.
        return True

    @staticmethod
    def _unique_preset_name(store: Any, base_name: str, mode: str) -> str:
        from core.prompt_engineering_settings import sanitize_preset_name

        base = sanitize_preset_name(base_name) or "preset"
        existing = set(store.list_preset_names(mode))
        candidate = base
        suffix = 1
        while candidate in existing:
            candidate = f"{base}_{suffix}"
            suffix += 1
        return candidate

    @staticmethod
    def _text_and_preset_stamp(value: Any) -> tuple[str, str]:
        """텍스트 편집 값에서 `(글, 어느 프리셋을 보고 친 것인가)` 를 뽑는다.

        옛 클라이언트는 문자열만 보낸다 - 그때는 표식이 없으니 그대로 받는다.
        새 클라이언트는 `{"text": ..., "preset": ...}` 로 보낸다.
        """
        if isinstance(value, dict):
            return str(value.get("text") or ""), str(value.get("preset") or "").strip()
        return str(value or ""), ""

    def _capture_main_settings(self) -> dict[str, Any]:
        """Snapshot the active mode's generation params (+ prompt/negative) for
        persisting with a preset. Internal (``_*``) and process-runtime keys are
        excluded; runtime-state keys are stripped later on apply/save."""
        from core.headless_remote_state_service import RUNTIME_REMOTE_PARAM_KEYS

        context = self.context
        captured: dict[str, Any] = {
            "prompt": str(context.prompt_text or ""),
            "negative": str(context.negative_prompt_text or ""),
        }
        for key, value in dict(context.remote_params or {}).items():
            if key.startswith("_") or key in RUNTIME_REMOTE_PARAM_KEYS:
                continue
            captured[key] = value
        return captured

    def sync_param_into_current_preset(self, key: str) -> str:
        """방금 바꾼 생성 파라미터를 **선택된 프리셋에 즉시 반영**한다.

        사용자 지정(2026-08-21): "원래 수정할 때마다 바로 반영되어야 합니다."
        프리셋을 열어 둔 채 모델을 바꾸면 그 프리셋이 곧 새 모델의 프리셋이 된다.

        ⚠️ **스냅샷이 아니라 병합이다.** `_capture_main_settings()` 를 그대로 쓰면
        지금 프롬프트 상자에 있는 글까지 같이 저장된다 - 프리셋을 고르고 Random 을
        몇 번 돌린 뒤 steps 를 만지면, 그 프리셋의 프롬프트가 마지막 랜덤 결과로
        덮어써진다. 바꾼 키 하나만 얹어 나머지(프롬프트 포함)는 건드리지 않는다.
        프롬프트까지 통째로 넣고 싶으면 명시적 저장을 쓴다.

        ⚠️ 디스크 쓰기지 네트워크가 아니다. 예전 프리셋 사고(밀린 쓰기가 앞 프리셋
        값을 덮어씀)는 이 경로에 **구독 조회를 await** 해서 생긴 것이지 저장 자체가
        원인이 아니었다(사용자 확인). 그 조회는 이미 비차단으로 바뀌었다.

        반환: 반영한 프리셋 이름. 반영할 게 없으면 빈 문자열.
        """
        key = str(key or "").strip()
        if not key or key.startswith("_"):
            return ""
        from core.headless_remote_state_service import RUNTIME_REMOTE_PARAM_KEYS
        from core.prompt_engineering_settings import (
            PRESET_RUNTIME_STATE_KEYS,
            get_prompt_engineering_store,
        )

        # 세션 전역으로 두는 값은 프리셋에 싣지 않는다. ⚠️ 목록이 **둘**이다 -
        # 저장 시 `normalize_preset_main_settings` 가 `PRESET_RUNTIME_STATE_KEYS`
        # (랜덤 해상도 등)를 어차피 벗겨 내므로, 그 키로 여기까지 오면 파일은 안
        # 바뀌는데 "반영했다" 고 답하고 쓸데없이 쓰기까지 한다.
        if key in RUNTIME_REMOTE_PARAM_KEYS or key in PRESET_RUNTIME_STATE_KEYS:
            return ""
        try:
            context = self.context
            store = get_prompt_engineering_store(context)
            mode_key = context.get_api_mode()
            state = store.state(mode_key)
            name = str(state.get("current_preset") or "")
            # 고른 프리셋이 없거나 '랜덤' 자리면 반영할 대상이 없다.
            if name in {"", "(프리셋 없음)", "*randomized"}:
                return ""
            if key not in dict(context.remote_params or {}):
                return ""

            data = store.read_preset_data(name, mode_key)
            if not data:
                return ""
            main_settings = data.get("main_settings")
            main_settings = dict(main_settings) if isinstance(main_settings, dict) else {}
            new_value = dict(context.remote_params)[key]
            if main_settings.get(key) == new_value:
                return ""                       # 값이 그대로면 쓰지 않는다
            main_settings[key] = new_value
            # ⚠️ **module_settings 는 건드리지 않는다.** 파라미터 하나를 반영하러 온
            #    길이 프리셋의 Prefix/Postfix 까지 살아 있는 값으로 갈아치우면, 스왑
            #    직후 늦게 도착한 앞 프리셋의 편집이 이 프리셋 파일에 영구히 박힌다.
            ok, _message = store.save_current_preset(
                mode_key, main_settings=main_settings, write_module_settings=False)
            return name if ok else ""
        except Exception as exc:  # noqa: BLE001 - 프리셋 반영 실패가 파라미터 변경을 막으면 안 된다
            print(f"[warn] preset param sync failed for {key}: {exc}", flush=True)
            return ""

    def sync_negative_into_current_preset(self) -> str:
        """네거티브 프롬프트를 **선택된 프리셋에 즉시 반영**한다.

        ⚠️ 사용자 지적(2026-08-21): "네거티브 프롬프트가 프리셋 이동 과정에서 자꾸
        유실되는 것 같습니다". `set_prompt` 커맨드가 컨텍스트에만 쓰고 프리셋은 안
        건드려서, 편집분이 세션에만 남아 있다가 프리셋을 옮기는 순간 사라졌다
        (돌아와도 저장된 옛 값이 다시 실린다). 생성 파라미터는 즉시 반영되는데
        네거티브만 아니었다.

        ⚠️ **메인 프롬프트는 여기서 저장하지 않는다.** Random 이 매번 덮어쓰므로
        아무 `set_prompt` 에서나 반영하면 프리셋의 프롬프트가 마지막 랜덤 결과로 굳어
        버린다(`sync_param_into_current_preset` 주석의 사고와 같은 뿌리). 메인 프롬프트는
        `sync_prompt_into_current_preset` 이 **사용자가 직접 친 경로에서만**(2026-08-27)
        따로 맡는다.

        ⚠️ 호출은 **사용자가 직접 편집한 경로에서만** 한다(`origin="edit"`).
        서버가 밀어 준 값을 클라이언트가 되돌려 보내는 에코 경로가 여럿이라, 아무
        `set_prompt` 에서나 반영하면 파이프라인이 만든 네거티브가 프리셋에 굳는다.

        반환: 반영한 프리셋 이름. 반영할 게 없으면 빈 문자열.
        """
        from core.prompt_engineering_settings import get_prompt_engineering_store

        try:
            context = self.context
            store = get_prompt_engineering_store(context)
            mode_key = context.get_api_mode()
            state = store.state(mode_key)
            name = str(state.get("current_preset") or "")
            if name in {"", "(프리셋 없음)", "*randomized"}:
                return ""

            data = store.read_preset_data(name, mode_key)
            if not data:
                return ""
            main_settings = data.get("main_settings")
            main_settings = dict(main_settings) if isinstance(main_settings, dict) else {}
            new_value = str(context.negative_prompt_text or "")
            # 저장 키는 `negative` 다(`_capture_main_settings` 와 같은 이름). 옛 파일에
            # `negative_prompt` 가 함께 있으면 그쪽도 맞춰 둔다 - 한쪽만 고치면
            # `_apply_main_settings` 가 어느 것을 나중에 읽느냐에 따라 값이 갈린다.
            if main_settings.get("negative") == new_value and (
                "negative_prompt" not in main_settings
                or main_settings.get("negative_prompt") == new_value
            ):
                return ""                       # 값이 그대로면 쓰지 않는다
            main_settings["negative"] = new_value
            if "negative_prompt" in main_settings:
                main_settings["negative_prompt"] = new_value
            # 네거티브만 반영한다 - module_settings 는 위 파라미터 동기화와 같은 이유로 둔다.
            ok, _message = store.save_current_preset(
                mode_key, main_settings=main_settings, write_module_settings=False)
            return name if ok else ""
        except Exception as exc:  # noqa: BLE001 - 반영 실패가 프롬프트 편집을 막으면 안 된다
            print(f"[warn] preset negative sync failed: {ascii(exc)}", flush=True)
            return ""

    def stale_prompt_edit(self, origin: str, stamp: str) -> bool:
        """이 메인 프롬프트 편집이 **앞 프리셋을 보고 친 것**인가.

        표식이 없으면(옛 클라이언트 · 사람이 친 게 아닌 에코) 판정하지 않는다 -
        기존 동작 유지. 참이면 부르는 쪽이 그 프롬프트를 통째로 무시해야 한다.
        """
        if str(origin or "") != "edit":
            return False
        stamp_text = str(stamp or "")
        if not stamp_text:
            return False
        try:
            from core.prompt_engineering_settings import get_prompt_engineering_store

            context = self.context
            store = get_prompt_engineering_store(context)
            name = str(store.state(context.get_api_mode()).get("current_preset") or "")
        except Exception:   # noqa: BLE001 - 판정 실패가 편집을 막으면 안 된다
            return False
        if not name or name == stamp_text:
            return False
        # 콘솔이 cp949 다 - 프리셋 이름은 한글/이모지일 수 있으므로 ascii() 로 이스케이프.
        print(
            "[info] dropped stale prompt edit:"
            f" typed for {ascii(stamp_text)}, current is {ascii(name)}",
            flush=True,
        )
        return True

    def sync_prompt_into_current_preset(self, stamp: str = "") -> str:
        """메인 프롬프트를 **선택된 프리셋에 즉시 반영**한다.

        ⚠️ 사용자 지적(2026-08-27): "프리셋 A -> B -> 다시 A 로 오면 의문의 메인
        프롬프트가 나타난다". 실측 재현: A 에서 `1girl, artist:h.yasai, ...` 로
        작업하다 B 를 거쳐 A 로 돌아오면 A 파일에 옛날에 저장된 전혀 다른 프롬프트가
        실린다. 프리셋 전환은 프롬프트를 **덮어쓰기만** 하고 나가는 프리셋에는
        아무것도 저장하지 않아, 그 사이의 작업이 통째로 사라진 것이다.
        파라미터와 네거티브는 이미 즉시 반영되는데(`sync_param_into_current_preset`
        / `sync_negative_into_current_preset`) 메인 프롬프트만 빠져 있었다.

        ⚠️ 호출은 **사용자가 직접 편집한 경로에서만** 한다(`prompt_origin="edit"`).
        Random 은 `context.prompt_text` 를 서버에서 직접 덮어쓰고(예:
        `headless_random_prompt_service.py`) 그 값은 `prompt_sync` 로 내려갈 뿐
        `set_prompt` 로 되돌아오지 않는다. 이 빗장이 없으면 프리셋의 프롬프트가
        마지막 랜덤 결과로 굳는다 - 위 두 함수가 같은 이유로 같은 빗장을 쓴다.

        빈 문자열도 그대로 저장한다. 사용자가 칸을 비운 것 역시 편집이고,
        네거티브도 같게 다룬다.

        `stamp` = **어느 프리셋을 보고 친 글인가**(클라이언트가 알려 준다).
        화면은 프리셋을 바꾼 뒤에도 잠깐 앞 프리셋의 글을 들고 있고(디바운스 500ms ·
        창이 둘일 때의 에코), 그 글이 스왑 뒤에 도착하면 **새 프리셋에 박힌다**.
        Prefix/Postfix 는 이미 같은 표식으로 막혀 있다(`_text_and_preset_stamp`).
        표식이 없으면(옛 클라이언트) 검사하지 않는다 - 기존 동작 유지.

        반환: 반영한 프리셋 이름. 반영할 게 없으면 빈 문자열.
        """
        from core.prompt_engineering_settings import get_prompt_engineering_store

        try:
            context = self.context
            store = get_prompt_engineering_store(context)
            mode_key = context.get_api_mode()
            state = store.state(mode_key)
            name = str(state.get("current_preset") or "")
            if name in {"", "(프리셋 없음)", "*randomized"}:
                return ""
            if str(stamp or "") and str(stamp) != name:
                return ""      # 판정과 로그는 `stale_prompt_edit` 가 이미 했다

            data = store.read_preset_data(name, mode_key)
            if not data:
                return ""
            main_settings = data.get("main_settings")
            main_settings = dict(main_settings) if isinstance(main_settings, dict) else {}
            new_value = str(context.prompt_text or "")
            if main_settings.get("prompt") == new_value:
                return ""                       # 값이 그대로면 쓰지 않는다
            main_settings["prompt"] = new_value
            # 프롬프트만 반영한다 - module_settings 는 위 두 동기화와 같은 이유로 둔다
            # (스왑 직후 늦게 도착한 앞 프리셋의 Prefix 가 이 파일에 박히는 사고).
            ok, _message = store.save_current_preset(
                mode_key, main_settings=main_settings, write_module_settings=False)
            return name if ok else ""
        except Exception as exc:  # noqa: BLE001 - 반영 실패가 프롬프트 편집을 막으면 안 된다
            print(f"[warn] preset prompt sync failed: {ascii(exc)}", flush=True)
            return ""

    def _apply_preset_main_settings_response(self, store: Any, preset_name: str):
        """On a preset swap, restore the preset's generation params + prompt and
        surface params/prompt_sync so the client UI updates."""
        context = self.context
        try:
            # Read the preset from the ACTIVE mode's directory. Omitting the mode
            # makes read_preset_data default to "NAI", so in COMFYUI/WEBUI this
            # read the wrong (NAI) preset — applying NAI main_settings (sampler/
            # scheduler/steps/cfg + negative) on top of a COMFYUI/WEBUI session
            # (reset to NAI values when a same-named NAI preset existed) or
            # returning {} for COMFYUI/WEBUI-only names (no params/negative applied
            # at all). set_preset() above already reads module_settings with the
            # active mode, so this must match it.
            preset_data = store.read_preset_data(preset_name, context.get_api_mode())
        except Exception:
            preset_data = None
        main_settings = preset_data.get("main_settings") if isinstance(preset_data, dict) else None
        if not isinstance(main_settings, dict) or not main_settings:
            return self.state()
        self._apply_main_settings(main_settings)
        return [
            self.state(),
            context.generation_param_schema_payload(),
            {
                "type": "prompt_sync",
                "prompt": context.prompt_text,
                "negative": context.negative_prompt_text,
                "negative_prompt": context.negative_prompt_text,
            },
        ]

    def _apply_main_settings(self, main_settings: dict[str, Any]) -> None:
        from core.prompt_engineering_settings import normalize_preset_main_settings

        context = self.context
        prompt_dirty = False
        # Strip per-preset runtime-state keys (random_resolution/auto_fit_resolution)
        # so preset application never clobbers those session flags (future01 parity).
        for key, value in normalize_preset_main_settings(dict(main_settings or {})).items():
            if key == "prompt":
                context.prompt_text = str(value or "")
                prompt_dirty = True
            elif key in {"negative", "negative_prompt"}:
                context.negative_prompt_text = str(value or "")
                prompt_dirty = True
            elif key == "webui_hiresfix_assist":
                enabled = context._coerce_bool(value)
                state = context._normalized_webui_hiresfix_assist_state(
                    context.webui_hiresfix_assist_state
                )
                state["enabled"] = enabled
                state["webui_hiresfix_assist"] = enabled
                context.webui_hiresfix_assist_state = state
                context.set_param(str(key), enabled)
            elif key == "webui_hiresfix_assist_target":
                target = 768 if str(value).strip() == "768" else 512
                state = context._normalized_webui_hiresfix_assist_state(
                    context.webui_hiresfix_assist_state
                )
                state["target"] = target
                state["webui_hiresfix_assist_target"] = target
                context.webui_hiresfix_assist_state = state
                context.set_param(str(key), target)
            else:
                context.set_param(str(key), value)
        if main_settings or prompt_dirty:
            context.save_remote_ui_state()
            context.publish("remote_params_changed", context.generation_param_schema_payload())

    def restore_main_prompt_from_preset(self) -> bool:
        """Bug 2b — lazy empty-prompt restore. When the active mode's main prompt
        box is empty, pull the matched (last-used, else resolved current) preset's
        ``main_settings.prompt`` into it and persist that into the mode's prompt
        plane. Returns True iff a non-empty prompt was restored.

        No-op (returns False) when the box already has content, no preset matches,
        or the preset's stored prompt is empty — the caller then falls back to a
        single Random. Only the main prompt is restored; the negative prompt has
        its own plane and is intentionally left untouched (the user's request was
        specifically about the *main* prompt)."""
        from core.prompt_engineering_settings import get_prompt_engineering_store

        context = self.context
        if str(context.prompt_text or "").strip():
            return False
        store = get_prompt_engineering_store(context)
        mode = context.get_api_mode()
        # Resolve to the *validated* current preset, not the raw last-used name:
        # store.state() already resolves a stale/nonexistent last-used preset down
        # to "default", so this also covers the "matched (last-used) preset" the
        # request means without us re-implementing that fallback (Codex finding).
        try:
            preset_name = str(store.state(mode).get("current_preset") or "")
        except Exception:
            preset_name = ""
        if not preset_name or preset_name in {"*randomized", "(프리셋 없음)"}:
            return False
        try:
            preset_data = store.read_preset_data(preset_name, mode)
        except Exception:
            preset_data = None
        main_settings = preset_data.get("main_settings") if isinstance(preset_data, dict) else None
        prompt = (
            str((main_settings or {}).get("prompt") or "").strip()
            if isinstance(main_settings, dict)
            else ""
        )
        if not prompt:
            return False
        context.prompt_text = prompt
        context.save_remote_ui_state()
        return True

    def _webui_remote_options(self, option_key: str) -> list[str]:
        context = self.context
        option_cache = getattr(context, "remote_option_cache", {}) or {}
        cached_options = option_cache.get("WEBUI", {}) if isinstance(option_cache, dict) else {}
        values = cached_options.get(option_key) if isinstance(cached_options, dict) else None
        if isinstance(values, list):
            return [str(value) for value in values if str(value or "").strip()]
        return []

    @staticmethod
    def _option_key(value: str) -> str:
        return "".join(ch for ch in str(value or "").lower() if ch.isalnum())

    def _preferred_webui_option(self, option_key: str, preferred: list[str], fallback: str) -> str:
        options = self._webui_remote_options(option_key)
        if not options:
            return fallback
        option_by_key = {self._option_key(option): option for option in options}
        for candidate in preferred:
            matched = option_by_key.get(self._option_key(candidate))
            if matched:
                return matched
        return options[0]

    @staticmethod
    def _comfyui_anima_recommended_module_settings() -> dict[str, Any]:
        cls = HeadlessPromptEngineeringService
        return {
            "pre_prompt": "(@myowa), newest, year2024, (best quality), highres, absurdres",
            "post_prompt": (
                "(3d background, blurry background:1.5), (musk, oekaki, crosshatching, sketch, "
                "watercolor \\(medium\\), airbrush \\(medium\\), cel rendering:0.4), "
                "(delicate colored lineart, highly aesthetic Pixiv style illustration, clean composition, "
                "high-quality digital art, very thin lineart, low contrast shading, cinematic lighting, "
                "very beautiful and detailed scene:0.8)"
            ),
            # Parity with the NAI/WEBUI recommended presets. COMFYUI ANIMA used to
            # ship an empty auto-hide list and no preprocessing options, so its
            # recommended preset silently skipped closed-eyes sync, auto-hide, and
            # the remove_* normalization the other modes apply on first connect /
            # "추천 설정 적용". Reuse the shared auto-hide list and WEBUI's
            # preprocessing options (which include closed_eyes_sync).
            "auto_hide_prompt": cls._nai_recommended_module_settings()["auto_hide_prompt"],
            "preprocessing_options": dict(
                cls._webui_recommended_module_settings()["preprocessing_options"]
            ),
        }

    @staticmethod
    def _comfyui_anima_recommended_main_settings() -> dict[str, Any]:
        return {
            "negative": (
                "ai-generated, face in shadow, (worst quality), low quality, cropped, (score_1), "
                "score_2, score_3, artist logo, unfinished, work-in-progress, blank, letterboxed, "
                "blurry, jpeg artifacts, sepia, mutated, mutated digits, missing fingers, extra digit, "
                "fewer digits, artistic error, bad anatomy, watermark, patreon username, web address, "
                "patreon logo, weibo username, watermark, mature female, adult female, adolescent, "
                "wide hips, narrow waist, long body, (multiple views:1.3), monochrome, greyscale, "
                "retro artstyle, (outline, thick outlines:1.15), bold lines, thick borders, messy shading, "
                "(western comics \\(style\\):1.5), furry, english text, spot color, doodle on background, "
                "gif artifacts, muted color, high contrast, oversaturated colors, glossy highlights"
            ),
            "sampling_mode": "anima",
            "comfyui_sampling_mode": "anima",
            "workflow_type": "unet",
            "sampler": "er_sde",
            "scheduler": "simple",
            "steps": 30,
            "cfg_scale": 5.1,
            "rescale_cfg": 0.5,
            "anima_weight": "1",
        }

    @staticmethod
    def _webui_recommended_module_settings() -> dict[str, Any]:
        return {
            "pre_prompt": "newest, year 2024, (best quality), score_8, highres, absurdres",
            "post_prompt": (
                "(perspective, foreshortening, dutch angle:0.75), "
                "(dynamic facial expressions), exaggerated and dark environment, "
                "violent composition, (low-contrast, muted color, watercolor \\(medium\\), "
                "highly aesthetic Pixiv style illustration, clean composition, view focus "
                "concentrated on the character with blurry background, high-quality digital art.:0.75)"
            ),
            "auto_hide_prompt": (
                "monochrome, doujin cover, bad source, __censor__, uncensored, female pubic hair, "
                "bad id, _logo, bad twitter id, comic, __background__, ~blurry background, "
                "~sky background, character doll, stuffed animal, stuffed toy, speech bubble, cyclops, "
                "pov, 3d, glasses, mole, text focus, thought bubble, watermark, web address, "
                "body writing, fake screenshot, facing away, |_|, __piercing__, tattoo, _tattoo, "
                "_text, sound effects, greyscale, multiple views, __pubic hair__, peeing, rabbit, "
                "__censor__, pregnant, __chess__, trading card, __(medium)__, __theme__, child on child, "
                "covered clitoris, _gag, sketch, poke_, __pokemon__, recording, viewfinder, multiple boys, "
                "__measuring__, multiple views, big belly, curvy, doll joints, looking at viewer, timestamp, "
                "battery indicator, tan, fake phone screenshot, stomach bulge, __beach__, __shower__, "
                "on table, huge penis, __bug__, giant insect, belly, eye mask, circle cut, dark nipples, "
                "signature, alternate race, alternate species, dark nipples, livestream, slap mark, x-ray, "
                "armpit hair, health bar, snapchat, facial mark, emoji, command spell, dark areolae, "
                "__piercing__, __bed__, __pillow__, __sheet__, body markings, obese, __long tongue__, "
                "toddlercon, __name__, handprint, __pasties__, mini person, __butt plug__, __eyepatch__, "
                "oppai loli, sex toy, loli, chibi, chibi inset, makeup, mascara, large breasts, "
                "runny makeup, third eye, anal hair, __halo__, __(style)__, __(cosplay)__, __freckles__, "
                "braces, gag, __joint__"
            ),
            "preprocessing_options": {
                "remove_author": True,
                "remove_work_title": True,
                "remove_character_name": True,
                "remove_character_features": False,
                "remove_clothes": False,
                "remove_clothing_event": False,
                "remove_color": False,
                "remove_location_and_background_color": False,
                "remove_expression": False,
                "remove_pose_action": False,
                "remove_meta_tags": True,
                "remove_object_tags": True,
                "remove_noise_tags": True,
                "closed_eyes_sync": True,
                "e621_auto_boost": False,
                "danbooru_auto_weight": False,
                "tag_implication_compression": True,
            },
        }

    def _webui_recommended_main_settings(self) -> dict[str, Any]:
        return {
            "sampler": self._preferred_webui_option(
                "options_sampler",
                ["ER SDE", "Euler a", "Euler A", "Euler Ancestral"],
                "Euler a",
            ),
            "scheduler": self._preferred_webui_option(
                "options_scheduler",
                ["Simple", "SGM Uniform"],
                "SGM Uniform",
            ),
            "resolution": "1024 x 1024",
            "steps": 32,
            "cfg_scale": 5.0,
            "negative": (
                "ai-generated, 3d, (worst quality), low quality, (score_1), score_2, score_3, "
                "realistic, furry, furry female, anthro, unfinished, work-in-progress, "
                "absurdly detailed composition, blank, blank background, letterboxed, blurry, "
                "jpeg artifacts, mutated, mutated digits, missing fingers, extra digit, fewer digits, "
                "artistic error, unusual anatomy, watermark, patreon username, web address, patreon logo, "
                "weibo username, (artist logo, twitter username, signature), watermark, (multiple views), "
                "distorted anatomy, english text, anatomically incorrect, doodle on background, "
                "bad perspective, high contrast, cool colored, glitch, distortion, colorful, neon palette, "
                "detailed background, (vignetting, shiny skin, shaded face, face in shadow, underexposed face, "
                "underexposed body, dark body, body in shadow, low-key lighting, cast shadow, diagonal shadow, "
                "shadow across face, shadow across torso, harsh shadow, dramatic lighting, spotlight, rim light, "
                "split lighting, chiaroscuro:0.85)"
            ),
            "seed": "-1",
            "seed_fixed": False,
            "enable_hr": False,
            "hr_scale": 2.0,
            "hr_upscaler": "Latent (nearest-exact)",
            "denoising_strength": 0.5,
            "hires_steps": 0,
            "hr_cfg": 7.0,
            "webui_hiresfix_assist": False,
            "webui_hiresfix_assist_target": 512,
            "anima_weight": "1",
            "random_prompt_weight": "1",
            "resolution_preset_enabled": False,
            "resolution_preset": "standard",
        }

    @staticmethod
    def _nai_recommended_module_settings() -> dict[str, Any]:
        return {
            "pre_prompt": (
                "1.2::artist:kim eb ::, 0.7::artist:torino aqua ::, 0.6::artist:mikozin ::, "
                "0.4::tianliang duohe fangdongye, ixy ::, 0.5::kedama milk ::, "
                "0.7::artist:quasarcake ::, 0.7::artist:channel (caststation) ::, "
                "0.6::artist:tab head ::, 0.5::artist:qiandaiyiyu ::, "
                "0.5::artist:mika pikazo ::, 0.3::artist:wanke ::, 0.4::artist:freng ::, "
                "0.25::artist:cutesexyrobutts ::"
            ),
            "post_prompt": (
                "year 2025, year 2024, 1.2::3d ::, 1.2::blender (medium) ::, detailed eyes, "
                "silky skin, detailed skin texture, masterpiece, best quality, very aesthetic, highres, "
                "best illustration, novel illustration, -1.2::simple illustration ::, "
                "-1::artist collaboration ::, -1::multiple views ::, -1::duplicate ::, -0.8::censored ::"
            ),
            "auto_hide_prompt": (
                "monochrome, doujin cover, bad source, __censor__, uncensored, female pubic hair, "
                "bad id, _logo, bad twitter id, comic, __background__, ~blurry background, "
                "~sky background, character doll, stuffed animal, stuffed toy, speech bubble, cyclops, "
                "pov, 3d, glasses, mole, text focus, thought bubble, watermark, web address, "
                "body writing, fake screenshot, facing away, |_|, __piercing__, tattoo, _tattoo, "
                "_text, sound effects, greyscale, multiple views, __pubic hair__, peeing, rabbit, "
                "__censor__, pregnant, __chess__, trading card, __(medium)__, __theme__, child on child, "
                "covered clitoris, _gag, sketch, poke_, __pokemon__, recording, viewfinder, multiple boys, "
                "__measuring__, multiple views, big belly, curvy, doll joints, looking at viewer, timestamp, "
                "battery indicator, tan, fake phone screenshot, stomach bulge, __beach__, __shower__, "
                "on table, huge penis, __bug__, giant insect, belly, eye mask, circle cut, dark nipples, "
                "signature, alternate race, alternate species, dark nipples, livestream, slap mark, x-ray, "
                "armpit hair, health bar, snapchat, facial mark, emoji, command spell, dark areolae, "
                "__piercing__, __bed__, __pillow__, __sheet__, body markings, obese, __long tongue__, "
                "toddlercon, __name__, handprint, __pasties__, mini person, __butt plug__, __eyepatch__, "
                "oppai loli, sex toy, loli, chibi, chibi inset, makeup, mascara, large breasts, "
                "runny makeup, third eye, anal hair, __halo__, __(style)__, __(cosplay)__, __freckles__, "
                "braces, gag, __joint__"
            ),
            "preprocessing_options": {
                "remove_author": True,
                "remove_work_title": True,
                "remove_character_name": True,
                "remove_character_features": False,
                "remove_clothes": False,
                "remove_clothing_event": False,
                "remove_color": False,
                "remove_location_and_background_color": False,
                "remove_expression": False,
                "remove_pose_action": False,
                "remove_meta_tags": True,
                "remove_object_tags": True,
                "remove_noise_tags": True,
                "e621_auto_boost": False,
                "danbooru_auto_weight": False,
                "tag_implication_compression": True,
            },
        }

    @staticmethod
    def _nai_v5_recommended_module_settings() -> dict[str, Any]:
        """NAI Diffusion V5 용 추천 프롬프트 묶음(`recommend_6` 기준).

        사용자 지시 2026-08-31: NAI5 사양이 바뀌어 `recommend_6` 로 동기화했다.
        V4.5 추천과 **작가 구성부터 다르다** - V5 는 같은 프롬프트에 다르게
        반응해서, 4.5 것을 그대로 쓰면 추천이라 부를 수 없다.

        ⚠️ 이 블록은 프리셋 파일에서 **생성**했다. 다시 동기화할 때도 손으로
        옮기지 말 것 - 프롬프트가 길어 반드시 틀린다.

        ⚠️ 단, `preprocessing_options.category_annotation` 만 **일부러 recommend_6
        과 다르다**(프리셋은 False, 여기는 True - 사용자 지시). 재생성하면 이 한
        줄은 다시 손으로 켜야 한다.
        """
        return {
            "pre_prompt": (
                "0.6::artist:utatanecocoa ::, 0.7::artist:nasuuni ::, 0.65::epi zero, artist:e-note ::, "
                "0.5::artist:sushispin ::, -1::artist collaboration ::"
            ),
            "post_prompt": (
                "0.35::crosshatching, countershading, ::, 0.8::perspective, low-angle view ::, "
                "0.15::light particles ::, 0.33::oekaki, cel shading, hatching (texture), graphite (medium), "
                "thin jaggy lines ::, 0.4::hong (white spider) ::, 0.55::dino (dinoartforame) ::, "
                "0.5::depth of field, foreshortening ::, best quality, very aesthetic, amazing quality, "
                "incredibly absurdres, year 2024, highly aesthetic Pixiv style illustration, "
                "clean composition, very thin lineart, high contrast, beautiful background, "
                "high-quality digital art, high complexity, -0.25::low complexity ::"
            ),
            "auto_hide_prompt": (
                "monochrome, doujin cover, bad source, __censor__, uncensored, female pubic hair, bad id, "
                "_logo, bad twitter id, comic, __background__, ~blurry background, ~sky background, "
                "character doll, stuffed animal, stuffed toy, speech bubble, cyclops, pov, 3d, glasses, mole, "
                "text focus, thought bubble, watermark, web address, body writing, fake screenshot, "
                "facing away, |_|, __piercing__, tattoo, _tattoo, _text, sound effects, greyscale, "
                "multiple views, __pubic hair__, peeing, rabbit, __censor__, pregnant, __chess__, "
                "trading card, __(medium)__, __theme__, child on child, covered clitoris, _gag, sketch, "
                "poke_, __pokemon__, recording, viewfinder, multiple boys, __measuring__, multiple views, "
                "big belly, curvy, doll joints, dark-skinned male, looking at viewer, timestamp, "
                "battery indicator, tan, fake phone screenshot, stomach bulge, __beach__, __shower__, "
                "on table, huge penis, __bug__, giant insect, belly, eye mask, circle cut, dark nipples, "
                "signature, alternate race, alternate species, dark nipples, livestream, slap mark, x-ray, "
                "armpit hair, health bar, snapchat, facial mark, emoji, command spell, dark areolae, "
                "__piercing__, __bed__, __pillow__, __sheet__, body markings, obese, __long tongue__, "
                "toddlercon, __name__, handprint, __pasties__, mini person, __butt plug__, __eyepatch__, "
                "oppai loli, sex toy, loli, chibi, chibi inset, makeup, mascara, large breasts, runny makeup, "
                "third eye, anal hair, __halo__, __(style)__, __(cosplay)__"
            ),
            "preprocessing_options": {
                "remove_author": True,
                "remove_work_title": True,
                "remove_character_name": True,
                "remove_character_features": False,
                "remove_clothes": False,
                "remove_clothing_event": False,
                "remove_color": False,
                "remove_location_and_background_color": False,
                "remove_expression": False,
                "remove_pose_action": False,
                "remove_meta_tags": True,
                "remove_object_tags": True,
                "remove_noise_tags": False,
                "closed_eyes_sync": True,
                "e621_auto_boost": False,
                "danbooru_auto_weight": False,
                "tag_implication_compression": False,
                # ⚠️ **recommend_6 과 일부러 다르다**(그쪽은 False). 사용자 지시
                # 2026-08-31: "category_annotation(True) 좋아보이네요. 그거 켜주세요".
                # 다음에 recommend_6 으로 재동기화할 때 **이 줄이 조용히 False 로
                # 되돌아가지 않게** 할 것 - 생성 스크립트는 프리셋 값을 그대로 쓴다.
                "category_annotation": True,
            },
            # recommend_6 이 함께 담고 있는 보조 설정 - 추천이 재현되려면
            # 이것들도 같이 가야 한다(가중치·부스트가 딴 값이면 결과가 달라진다).
            "e621_settings": {
                "weight": 1.05,
                "hidden_tags": [],
                "mode": "confused",
            },
            "danbooru_weight_settings": {
                "magnitude": 3,
                "rating_blend": 0.3,
                "override_on": False,
                "override_scale": 0.42,
                "override_min": 0.65,
                "override_max": 1.47,
                "rating_override_on": True,
                "rating_override": "s",
                "invert_weight": False,
            },
            "ollama_boost_settings": {
                "nl_weight": 1.5,
                "effort": "rich",
                "include_prefix": False,
                "include_postfix": False,
                "include_e621": False,
                "allow_scent_style": True,
                "allow_material_style": True,
                "allow_light_style": False,
                "emphasize_framing": False,
            },
        }
    @staticmethod
    def _nai_v5_recommended_main_settings() -> dict[str, Any]:
        """V5 추천 생성 파라미터(`recommend_6` 기준).

        사용자 지시 2026-08-31: NAI5 사양이 바뀌어 `recommend_6` 로 동기화.
        이 블록은 그 프리셋 파일에서 **생성**했다 - 긴 프롬프트를 손으로 옮기면
        반드시 틀린다.

        ⚠️ `random_resolution` / `auto_fit_resolution` 은 **프리셋에 저장되지 않는
        세션 전역 키**라(`PRESET_RUNTIME_STATE_KEYS`) recommend_6 에도 없다.
        그래서 동기화 대상이 아니고 예전 값을 그대로 둔다.
        """
        return {
            "model": "NAID5F",
            "sampler": "k_euler_ancestral",
            "scheduler": "karras",
            "resolution": "896 x 1152",
            "width": 896,
            "height": 1152,
            "steps": 23,
            "cfg_scale": 7.0,
            "cfg_rescale": 0.0,
            "negative": (
                "lowres, bad quality, normal quality, very displeasing, abstract, mutated, monochrome, "
                "bleed through, gif artifacts, jpeg artifacts, scan artifacts, bad hands, artistic error, "
                "bad anatomy, extra digits, glitch, chromatic aberration abuse, distortion, haze, anaglyph, "
                "faded, 1.5::moire ::, high contrast, flipnote studio (medium), ink (medium), cubism, "
                "saturated, outline, retro artstyle, partially colored, flat color, blending, ukiyo-e, "
                "sumi-e, minimalism, ai-generated, 1980s (style), bkub (style), yasuhiko yoshikazu (style), "
                "blender (medium), 1.15::multiple views ::"
            ),
            "seed": 7911702124,
            "seed_fixed": False,
            "prompt_fixed": False,
            "wildcard_standalone": False,
            # 프리셋이 담지 못하는 세션 전역 키 - 예전 값 유지.
            "random_resolution": True,
            "auto_fit_resolution": False,
            "SMEA": False,
            "DYN": False,
            "VAR+": False,
            "DECRISP": True,
        }
    @staticmethod
    def _nai_recommended_main_settings() -> dict[str, Any]:
        return {
            "model": "NAID4.5F",
            "sampler": "k_euler_ancestral",
            "scheduler": "karras",
            "resolution": "1024 x 1024",
            "steps": 28,
            "cfg_scale": 5.8,
            "cfg_rescale": 0.28,
            "negative": (
                "text, logo, signature, watermark, too many watermarks, chili inset, "
                "0.4::artist:nameo (judgemasterkou), artist:matsunaga kouyou::, artist collaboration, "
                "chibi, 1990s (style), bad anatomy, distorted anatomy, disfigured, bad hands, "
                "missing finger, extra digits, mutation, extra arms, extra legs, long neck, bad feet, "
                "very displeasing, undetailed eyes, multiple views, negative space, blank page, variant set, "
                "large variant set, 4koma, 2koma, oekaki, halftone, screentone, artistic error, "
                "film grain, scan artifacts, jpeg artifacts, chromatic aberration, dithering, "
                "disorganized colors, lowres, worst quality, bad quality, cheesy, sloppiness, "
                "unfinished, Incomplete, ai-generated"
            ),
            "seed": "8097879955",
            "seed_fixed": False,
            "random_resolution": True,
            "auto_fit_resolution": True,
            "SMEA": False,
            "DYN": False,
            "VAR+": True,
            "DECRISP": False,
        }

    def hires_overlay_response(self, preset_name: str) -> dict[str, Any]:
        name = str(preset_name or "").strip()
        response = {
            "type": "hires_preset_overlay",
            "preset_name": name,
            "original": {"prefix_prompt": "", "postfix_prompt": "", "negative_prompt": ""},
            "overlay": None,
            "editable": False,
            "available": False,
            "runtime": "web",
        }
        path = self.hires_overlay_path(name)
        if path is None:
            return response
        response["editable"] = True
        response["available"] = True
        preset_path = self.context._existing_save_path("presets", "WEBUI", f"{name}.json")
        if preset_path.exists():
            try:
                preset_data = json.loads(preset_path.read_text(encoding="utf-8"))
                module_settings = preset_data.get("module_settings", {}) if isinstance(preset_data, dict) else {}
                main_settings = preset_data.get("main_settings", {}) if isinstance(preset_data, dict) else {}
                module_settings = module_settings if isinstance(module_settings, dict) else {}
                main_settings = main_settings if isinstance(main_settings, dict) else {}
                response["original"] = {
                    "prefix_prompt": str(module_settings.get("pre_prompt", "") or ""),
                    "postfix_prompt": str(module_settings.get("post_prompt", "") or ""),
                    "negative_prompt": str(
                        main_settings.get("negative") or main_settings.get("negative_prompt") or ""
                    ),
                }
            except Exception:
                pass
        overlay_path = self.context._existing_save_path("presets", "WEBUI", f"{name}.hires.json")
        if overlay_path.exists():
            try:
                overlay = json.loads(overlay_path.read_text(encoding="utf-8"))
                if isinstance(overlay, dict):
                    response["overlay"] = {
                        "prefix_prompt": str(overlay.get("prefix_prompt", "") or ""),
                        "postfix_prompt": str(overlay.get("postfix_prompt", "") or ""),
                        "negative_prompt": str(overlay.get("negative_prompt", "") or ""),
                    }
            except Exception:
                pass
        return response

    def write_hires_overlay(self, preset_name: str, body: dict[str, Any] | None) -> tuple[bool, str]:
        path = self.hires_overlay_path(preset_name)
        if path is None:
            return False, "WEBUI 모드의 일반 프리셋만 편집할 수 있습니다."
        source = body if isinstance(body, dict) else {}
        payload = {
            "schema_version": 1,
            "prefix_prompt": str(source.get("prefix_prompt", "") or ""),
            "postfix_prompt": str(source.get("postfix_prompt", "") or ""),
            "negative_prompt": str(source.get("negative_prompt", "") or ""),
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return True, f"Overlay saved: {path.name}"
        except Exception as exc:
            return False, f"저장 실패: {exc}"

    def reset_hires_overlay(self, preset_name: str) -> tuple[bool, str]:
        path = self.hires_overlay_path(preset_name)
        if path is None:
            return False, "WEBUI 모드의 일반 프리셋만 편집할 수 있습니다."
        try:
            if path.exists():
                path.unlink()
                return True, f"Overlay removed: {path.name}"
            return True, "Overlay already absent."
        except Exception as exc:
            return False, f"삭제 실패: {exc}"

    def hires_overlay_path(self, preset_name: str) -> Path | None:
        name = str(preset_name or "").strip()
        if name in HIRES_OVERLAY_DISALLOWED_NAMES:
            return None
        safe_name = Path(name).name
        if safe_name != name:
            return None
        if self.context.get_api_mode() != "WEBUI":
            return None
        return self.context._save_path("presets", "WEBUI", f"{safe_name}.hires.json")
