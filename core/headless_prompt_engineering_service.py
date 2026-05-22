"""Headless Prompt Engineering module state service."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


HIRES_OVERLAY_DISALLOWED_NAMES = {"", "*randomized", "(프리셋 없음)"}


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

    def hires_overlay_response(self, preset_name: str) -> dict[str, Any]:
        name = str(preset_name or "").strip()
        response = {
            "type": "hires_preset_overlay",
            "preset_name": name,
            "original": {"prefix_prompt": "", "postfix_prompt": "", "negative_prompt": ""},
            "overlay": None,
            "editable": False,
            "available": False,
            "headless": True,
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
