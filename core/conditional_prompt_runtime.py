from __future__ import annotations

from typing import Any

from core.conditional_prompt_settings import (
    get_conditional_prompt_store,
    normalize_conditional_engine_options,
)


class ConditionalPromptHeadlessHook:
    """Deferred WebSession hook for the conditional prompt module.

    The full legacy rule engine still lives in PromptListModifierModule. This
    hook keeps that PyQt module out of hidden WebSession startup, then loads it
    only when conditional rules are actually enabled for a generation.
    """

    def __init__(self, app_context):
        self.app_context = app_context
        self._store = get_conditional_prompt_store(app_context)

    def get_title(self) -> str:
        return "Conditional Prompt Headless"

    def get_pipeline_hook_info(self) -> dict[str, Any]:
        return {
            "target_pipeline": "PromptProcessor",
            "hook_point": "after_wildcard",
            "priority": 2,
        }

    def _session_override(self) -> dict[str, Any] | None:
        override = getattr(self.app_context, "session_cond_override", None)
        return override if isinstance(override, dict) else None

    def _active_settings(self) -> dict[str, Any] | None:
        override = self._session_override()
        if override is not None:
            if not override.get("enabled"):
                return None
            rules = str(override.get("rules") or "").strip()
            if not rules:
                return None
            return {
                "enabled": True,
                "rules": rules,
                "rules_v2": rules,
                "editor_mode": "v2",
                "engine_options": normalize_conditional_engine_options(
                    override.get("engine_options") or {}
                ),
                "active_preset": None,
            }

        settings = self._store.collect_settings()
        if not settings.get("enabled"):
            return None
        editor_mode = str(settings.get("editor_mode") or "legacy")
        rules_key = "rules_v2" if editor_mode == "v2" else "rules"
        rules = str(settings.get(rules_key) or "").strip()
        if not rules:
            return None
        settings = dict(settings)
        settings["rules"] = str(settings.get("rules") or "")
        settings["rules_v2"] = str(settings.get("rules_v2") or "")
        settings["engine_options"] = normalize_conditional_engine_options(
            settings.get("engine_options") or {}
        )
        return settings

    def _load_module(self):
        middle_controller = getattr(self.app_context, "middle_section_controller", None)
        if middle_controller is None or not hasattr(middle_controller, "get_module_instance"):
            return None
        return middle_controller.get_module_instance("PromptListModifierModule")

    def execute_pipeline_hook(self, context):
        active_settings = self._active_settings()
        if active_settings is None:
            return context

        module = self._load_module()
        if module is None or not hasattr(module, "execute_pipeline_hook"):
            return context

        if self._session_override() is None and hasattr(module, "apply_settings"):
            module.apply_settings(active_settings)
        return module.execute_pipeline_hook(context)


def register_conditional_prompt_headless_runtime(app_context) -> ConditionalPromptHeadlessHook:
    hook = getattr(app_context, "conditional_prompt_headless_hook", None)
    if isinstance(hook, ConditionalPromptHeadlessHook):
        return hook
    hook = ConditionalPromptHeadlessHook(app_context)
    app_context.register_pipeline_hook(hook.get_pipeline_hook_info(), hook)
    setattr(app_context, "conditional_prompt_headless_hook", hook)
    return hook
