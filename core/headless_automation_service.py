"""Headless Automation module settings service."""

from __future__ import annotations

from typing import Any


class HeadlessAutomationService:
    def __init__(self, context: Any):
        self.context = context

    def state(self) -> dict[str, Any]:
        from core.automation_settings import automation_state_from_settings, load_automation_settings

        context = self.context
        settings = getattr(context, "_automation_settings", None)
        if not isinstance(settings, dict):
            settings = load_automation_settings(context._existing_save_path("AutomationModule.json"))
            context._automation_settings = settings
        state = automation_state_from_settings(settings)
        state["available"] = True
        state["headless"] = True
        return state

    def set_param(self, key: str, value: Any) -> dict[str, Any] | None:
        from core.automation_settings import save_automation_settings, settings_from_automation_state

        context = self.context
        if key in {"start", "stop"}:
            return context._toast("Automation execution is retired in the supported headless runtime.", level="info")
        state = self.state()
        if key == "auto_type":
            state["auto_type"] = value
        elif key in {"delay", "random_delay", "timer_minutes", "count_limit", "notify"}:
            state[key] = value
        elif key == "repeat":
            return self.state()
        else:
            return None
        settings = settings_from_automation_state(state)
        context._automation_settings = settings
        save_automation_settings(settings, context._save_path("AutomationModule.json"))
        return self.state()
