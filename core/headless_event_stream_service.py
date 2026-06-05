"""Headless Event Stream module state service."""

from __future__ import annotations

from typing import Any


class HeadlessEventStreamService:
    def __init__(self, context: Any):
        self.context = context

    def runtime(self, *, create: bool = True):
        runtime = getattr(self.context, "event_stream_runtime", None)
        if runtime is None and create:
            try:
                from core.event_tree import EventStreamRuntime

                runtime = EventStreamRuntime(self.context)
                self.context.event_stream_runtime = runtime
            except Exception:
                runtime = None
        return runtime

    def state(self) -> dict[str, Any]:
        runtime = self.runtime(create=True)
        if runtime is None:
            return self.context._module_state_payload("event_stream", {
                "available": False,
                "active": False,
                "message": "Event Stream runtime is not available.",
            })
        state = runtime.get_state() if hasattr(runtime, "get_state") else {}
        return self.context._module_state_payload("event_stream", {
            "available": True,
            "runtime": "web",
            **state,
        })

    def set_param(self, key: str, value: Any) -> dict[str, Any] | None:
        runtime = self.runtime(create=True)
        if runtime is None:
            return self.context._toast("Event Stream runtime is not available.", level="error")
        # A Storyteller cycle owns the Event Stream freeze/allocator while running. Block
        # manual active/restart toggles so the node sequence / freeze snapshot can't be
        # reset mid-cycle; the user stops it from the Storyteller controls instead.
        if key in {"active", "restart"}:
            storyteller = getattr(self.context, "_storyteller_service", None)
            if callable(storyteller) and self.context._storyteller_service().is_running():
                state = self.state()
                state["_headless_extra_messages"] = [self.context._toast(
                    "A Storyteller cycle is running. Use the Storyteller controls to stop it.",
                    level="error",
                )]
                return state
        if key == "active":
            enabled = self.context._coerce_bool(value)
            if enabled and not runtime.is_active:
                runtime.start_linear(self._storyteller_nodes())
            elif not enabled and runtime.is_active:
                runtime.stop()
        elif key == "restart":
            runtime.start_linear(self._storyteller_nodes())
        else:
            return None
        return self.state()

    def _storyteller_nodes(self):
        """활성화 경로 통일(1.5 모델): 어디서 켜든(런처 토글·수동 시작 버튼) 저장된
        Storyteller 스텝 시퀀스를 무장한다. 스텝이 없으면 None → 기본 1노드."""
        try:
            storyteller = self.context._storyteller_service()
            steps = storyteller.load_steps()
            if steps:
                return storyteller._build_step_nodes(steps, len(steps))
        except Exception:
            pass
        return None
