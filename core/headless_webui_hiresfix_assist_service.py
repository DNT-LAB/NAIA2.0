"""Headless WEBUI Hiresfix Assist module state service."""

from __future__ import annotations

from typing import Any


class HeadlessWebuiHiresfixAssistService:
    def __init__(self, context: Any):
        self.context = context

    @staticmethod
    def _coerce_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        return str(value).strip().lower() not in {"", "0", "false", "no", "off", "none"}

    @staticmethod
    def normalized_state(raw: dict[str, Any] | None = None) -> dict[str, Any]:
        source = raw if isinstance(raw, dict) else {}
        target = 768 if str(source.get("target") or source.get("webui_hiresfix_assist_target") or "").strip() == "768" else 512
        enabled = HeadlessWebuiHiresfixAssistService._coerce_bool(
            source.get("enabled", source.get("webui_hiresfix_assist", True))
        )
        return {
            "enabled": enabled,
            "target": target,
            "webui_hiresfix_assist": enabled,
            "webui_hiresfix_assist_target": target,
        }

    def state(self) -> dict[str, Any]:
        state = self.normalized_state(self.context.webui_hiresfix_assist_state)
        return self.context._module_state_payload("webui_hiresfix_assist", state)

    def set_param(self, key: str, value: Any) -> dict[str, Any] | None:
        context = self.context
        state = self.normalized_state(context.webui_hiresfix_assist_state)
        if key == "enabled":
            state["enabled"] = context._coerce_bool(value)
        elif key == "target":
            state["target"] = 768 if str(value).strip() == "768" else 512
        else:
            return None
        state["webui_hiresfix_assist"] = bool(state["enabled"])
        state["webui_hiresfix_assist_target"] = int(state["target"])
        context.webui_hiresfix_assist_state = state
        context.remote_params["webui_hiresfix_assist"] = bool(state["enabled"])
        context.remote_params["webui_hiresfix_assist_target"] = int(state["target"])
        return self.state()
