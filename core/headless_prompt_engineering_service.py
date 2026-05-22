"""Headless Prompt Engineering module state service."""

from __future__ import annotations

import json
from typing import Any


class HeadlessPromptEngineeringService:
    def __init__(self, context: Any):
        self.context = context

    def state(self) -> dict[str, Any]:
        from core.prompt_engineering_settings import get_prompt_engineering_store

        context = self.context
        store = get_prompt_engineering_store(context)
        settings = store.collect_settings()
        state = store.state()
        preset_options = store.preset_options()

        def preset_summary(name: str, mode: str | None = None) -> dict[str, Any]:
            if name == "*randomized":
                return {
                    "name": name,
                    "api_mode": context.get_api_mode(),
                    "description": "Randomized preset pool",
                    "pre_prompt_preview": "",
                    "thumbnail_url": "",
                }
            data = store.read_preset_data(name, mode or context.get_api_mode())
            module_settings = data.get("module_settings") if isinstance(data, dict) else {}
            module_settings = module_settings if isinstance(module_settings, dict) else {}
            return {
                "name": name,
                "api_mode": str(data.get("api_mode") or mode or context.get_api_mode()),
                "description": str(data.get("description") or ""),
                "pre_prompt_preview": str(module_settings.get("pre_prompt") or ""),
                "thumbnail_url": str(data.get("thumbnail_url") or ""),
            }

        webui_presets = store.list_preset_names("WEBUI")
        payload = {
            "preset": state["current_preset"],
            "preset_options": preset_options,
            "preset_summaries": [preset_summary(name) for name in preset_options],
            "webui_preset_options": webui_presets,
            "webui_preset_summaries": [preset_summary(name, "WEBUI") for name in webui_presets],
            "randomized_active": state["current_preset"] == "*randomized",
            "randomized_preset_list": list(state["randomized_preset_list"]),
            "randomized_available_presets": store.randomized_available_presets(),
            "pre_prompt": settings.get("pre_prompt", ""),
            "post_prompt": settings.get("post_prompt", ""),
            "auto_hide": settings.get("auto_hide_prompt", ""),
            "preprocessing": dict(settings.get("preprocessing_options") or {}),
            "e621_settings": dict(settings.get("e621_settings") or {}),
            "danbooru_settings": dict(settings.get("danbooru_weight_settings") or {}),
            "debug_snapshot": {},
            "preset_can_save_current": state["current_preset"] not in ("", "(프리셋 없음)", "*randomized"),
            "preset_can_delete": state["current_preset"] not in ("", "(프리셋 없음)", "*randomized", "default"),
        }
        return context._module_state_payload("prompt_engineering", payload)

    def set_param(self, key: str, value: Any) -> dict[str, Any] | None:
        from core.prompt_engineering_settings import get_prompt_engineering_store

        context = self.context
        store = get_prompt_engineering_store(context)
        text_value = str(value or "")
        if key == "pre_prompt":
            store.apply_settings({"pre_prompt": text_value})
        elif key == "post_prompt":
            store.apply_settings({"post_prompt": text_value})
        elif key == "auto_hide":
            store.apply_settings({"auto_hide_prompt": text_value})
        elif key == "preset":
            if not store.set_preset(text_value):
                return context._toast(f"프리셋을 찾을 수 없습니다: {text_value}", level="error")
        elif key == "preset_save_current":
            ok, message = store.save_current_preset()
            if not ok:
                return context._toast(message, level="error")
        elif key == "preset_create":
            ok, message = store.create_preset(text_value)
            if not ok:
                return context._toast(message, level="error")
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
        elif key == "debug_refresh":
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
