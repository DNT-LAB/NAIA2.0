"""Headless Event Stream module state service."""

from __future__ import annotations

from typing import Any


class HeadlessEventStreamService:
    def __init__(self, context: Any):
        self.context = context

    def state(self) -> dict[str, Any]:
        runtime = getattr(self.context, "event_stream_runtime", None)
        if runtime is None:
            return self.context._module_state_payload("event_stream", {
                "available": False,
                "active": False,
                "message": "Event Stream runtime is not available.",
            })
        state = runtime.get_state() if hasattr(runtime, "get_state") else {}
        return self.context._module_state_payload("event_stream", {
            "available": True,
            "headless": True,
            **state,
        })

    def set_param(self, key: str, value: Any) -> dict[str, Any] | None:
        runtime = getattr(self.context, "event_stream_runtime", None)
        if runtime is None:
            return self.context._toast("Event Stream runtime is not available.", level="error")
        if key == "active":
            enabled = self.context._coerce_bool(value)
            if enabled and not runtime.is_active:
                runtime.start_linear()
            elif not enabled and runtime.is_active:
                runtime.stop()
        elif key == "restart":
            runtime.start_linear()
        else:
            return None
        return self.state()
