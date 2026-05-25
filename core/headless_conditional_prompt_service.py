"""Headless Conditional Prompt module state service."""

from __future__ import annotations

import json
from typing import Any


class HeadlessConditionalPromptService:
    def __init__(self, context: Any):
        self.context = context

    def state(self) -> dict[str, Any]:
        from core.conditional_prompt_settings import get_conditional_prompt_store

        store = get_conditional_prompt_store(self.context)
        settings = store.collect_settings()
        editor_mode = str(settings.get("editor_mode") or "legacy")
        editor_mode = editor_mode if editor_mode in {"legacy", "v2"} else "legacy"
        rules_legacy = str(settings.get("rules") or "")
        rules_v2 = str(settings.get("rules_v2") or "")
        active_rules = rules_v2 if editor_mode == "v2" else rules_legacy
        return self.context._module_state_payload("conditional_prompt", {
            "enabled": bool(settings.get("enabled", False)),
            "editor_mode": editor_mode,
            "rules": active_rules,
            "active_rules": active_rules,
            "rules_legacy": rules_legacy,
            "rules_v2": rules_v2,
            "rules_v2_book": None,
            "engine_options": dict(settings.get("engine_options") or {}),
            "active_preset": str(settings.get("active_preset") or ""),
            "presets": [],
            "log": "",
        })

    def set_param(self, key: str, value: Any) -> dict[str, Any] | None:
        from core.conditional_prompt_settings import get_conditional_prompt_store

        context = self.context
        store = get_conditional_prompt_store(context)
        settings = store.collect_settings()
        text_value = str(value or "")
        if key == "enabled":
            settings["enabled"] = context._coerce_bool(value)
        elif key in {"editor_mode", "mode"}:
            if text_value in {"legacy", "v2"}:
                settings["editor_mode"] = text_value
        elif key == "rules_legacy":
            settings["rules"] = text_value
        elif key == "rules_v2":
            settings["rules_v2"] = text_value
        elif key == "rules":
            if settings.get("editor_mode") == "v2":
                settings["rules_v2"] = text_value
            else:
                settings["rules"] = text_value
        elif key == "engine_options":
            parsed = json.loads(text_value or "{}")
            if isinstance(parsed, dict):
                settings["engine_options"] = parsed
        elif key == "max_passes":
            options = dict(settings.get("engine_options") or {})
            options["max_passes"] = context._coerce_int(value, default=1, minimum=1, maximum=20)
            settings["engine_options"] = options
        elif key == "stop_on_match":
            options = dict(settings.get("engine_options") or {})
            options["stop_on_match"] = context._coerce_bool(value)
            settings["engine_options"] = options
        elif key in {"rules_v2_book", "preset_load", "test_rules"}:
            return context._toast(f"Conditional Prompt action is not available in this runtime: {key}", level="info")
        else:
            return None
        store.apply_settings(settings)
        return self.state()
