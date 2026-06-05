"""Headless Automation module runtime service."""

from __future__ import annotations

import random
import time
import uuid
from typing import Any


AUTOMATION_SOURCE = "Automation"
AUTOMATION_UNSUPPORTED_SHUTDOWN_MESSAGE = (
    "Shutdown on finish is not supported in the headless/portable runtime; no shutdown was attempted."
)


class HeadlessAutomationService:
    def __init__(self, context: Any):
        self.context = context

    def state(self) -> dict[str, Any]:
        from core.automation_settings import automation_state_from_settings

        settings = self._settings()
        state = automation_state_from_settings(settings)
        runtime = self._runtime(create=False)
        running = bool(runtime and runtime.get("is_running"))

        state.update({
            "available": True,
            "runtime": "web",
            "is_running": running,
            "status": self._status_text(settings, runtime),
            "repeat_info": self._repeat_info(settings, runtime),
            "delay_info": self._delay_info(runtime),
            "shutdown_on_finish": bool(settings.get("shutdown_on_finish", False)),
            "shutdown_supported": False,
            "shutdown_message": (
                AUTOMATION_UNSUPPORTED_SHUTDOWN_MESSAGE
                if settings.get("shutdown_on_finish")
                else ""
            ),
        })
        if runtime:
            state.update({
                "automation_run_id": str(runtime.get("run_id") or ""),
                "automation_type": str(runtime.get("automation_type") or ""),
                "completed_count": int(runtime.get("completed_count") or 0),
                "remaining_count": runtime.get("remaining_count"),
                "remaining_seconds": self._remaining_seconds(runtime),
            })
        state["repeat"] = str(self._repeat_count())
        return state

    def set_param(self, key: str, value: Any) -> dict[str, Any] | None:
        from core.automation_settings import save_automation_settings, settings_from_automation_state

        context = self.context
        if key == "start":
            return self.start()
        if key == "stop":
            return self.stop(reason="stopped")

        if key == "repeat":
            # Session-only (desktop parity): store pending so state() echoes the
            # typed value, but never persist it to AutomationModule.json.
            try:
                self.context._automation_repeat_pending = max(1, int(value))
            except (TypeError, ValueError):
                self.context._automation_repeat_pending = 1
            return self.state()

        state = self.state()
        if key == "auto_type":
            state["auto_type"] = value
        elif key in {"delay", "random_delay", "timer_minutes", "count_limit", "notify", "shutdown_on_finish", "persist_automation"}:
            state[key] = value
        else:
            return None
        settings = settings_from_automation_state(state)
        context._automation_settings = settings
        save_automation_settings(settings, context._save_path("AutomationModule.json"))
        # 지속 자동화를 방금 켰고 Auto Gen이 이미 켜져 있으면 자동 시작(Auto Gen이 트리거).
        if key == "persist_automation" and context._coerce_bool(value):
            started = self.maybe_autostart()
            if isinstance(started, dict):
                return started
        return self.state()

    def start(self) -> dict[str, Any]:
        settings = self._settings()
        # Mutual exclusion with the Storyteller cycle — both own the single Auto Generate
        # loop, so only one controller may drive it at a time (reciprocal of the guard in
        # HeadlessStorytellerService.start_cycle).
        if self.context._storyteller_service().is_running():
            state = self.state()
            state["_headless_extra_messages"] = [self.context._toast(
                "A Storyteller cycle is running. Stop it before starting Automation.",
                level="error",
            )]
            return state
        credential_error = self._credential_error()
        if credential_error:
            state = self.state()
            state["_headless_extra_messages"] = [self.context._toast(credential_error, level="error")]
            return state

        run_id = f"automation-{uuid.uuid4().hex}"
        now = time.monotonic()
        automation_type = str(settings.get("automation_type") or "unlimited")
        runtime = {
            "run_id": run_id,
            "is_running": True,
            "automation_type": automation_type,
            "started_at_monotonic": now,
            "completed_count": 0,
            "remaining_count": int(settings.get("count_limit") or 0) if automation_type == "count" else None,
            "ends_at_monotonic": (
                now + max(1, int(settings.get("timer_minutes") or 1)) * 60
                if automation_type == "timer"
                else None
            ),
            "delay_until_monotonic": None,
            "finish_reason": "",
            "repeat_count": self._repeat_count(),
            "repeat_progress": 0,
        }
        self.context.automation_runtime_state = runtime

        # Automation is a controller over the shared Auto Generate loop
        # (future01 parity): Start only sets the run conditions and engages
        # Auto Gen. It never issues a generation itself. The unified generation
        # runner drives each iteration once a generation runs, and this
        # controller enforces the timer/count limit and disables Auto Gen when
        # the limit is reached.
        messages: list[dict[str, Any]] = []
        options_message = self._engage_auto_generate(True)
        if options_message:
            messages.append(options_message)
        messages.append(self.context._toast(
            "Automation armed. Generation runs through Auto Generate.",
            level="info",
        ))

        state = self.state()
        state["_headless_extra_messages"] = messages
        return state

    def stop(self, *, reason: str = "stopped") -> dict[str, Any]:
        runtime = self._runtime(create=False)
        was_running = bool(runtime and runtime.get("is_running"))
        if was_running:
            runtime["is_running"] = False
            runtime["finish_reason"] = reason
            runtime["delay_until_monotonic"] = None
        state = self.state()
        if was_running:
            # Disable Auto Gen when the controller stops (future01
            # _disable_auto_generate_immediately parity).
            options_message = self._engage_auto_generate(False)
            if options_message:
                state["_headless_extra_messages"] = [options_message]
        return state

    def maybe_autostart(self) -> dict[str, Any] | None:
        """지속 자동화: Auto Gen이 켜져 있고 persist_automation이 켜져 있으며 아직
        실행 중이 아니면 자동화를 자동 시작한다(Auto Gen이 핵심 트리거). 완료 시
        finish가 Auto Gen을 끄므로, 다시 켜기 전까지 재시작되지 않는다(무한 루프 없음)."""
        if self.is_running():
            return None
        if self.context._storyteller_service().is_running():
            return None
        settings = self._settings()
        if not settings.get("persist_automation"):
            return None
        if not bool(self.context.get_options().get("auto_generate", False)):
            return None
        return self.start()

    def is_running(self, run_id: str | None = None) -> bool:
        runtime = self._runtime(create=False)
        if not runtime or not runtime.get("is_running"):
            return False
        return not run_id or str(runtime.get("run_id") or "") == str(run_id)

    def active_run_id(self) -> str:
        """Return the running controller's run id, or "" when idle.

        Lets the generation runner bind a plain Auto Generate completion to the
        live Automation controller so its timer/count limit is enforced even
        though Start never tags requests itself.
        """
        runtime = self._runtime(create=False)
        if not runtime or not runtime.get("is_running"):
            return ""
        return str(runtime.get("run_id") or "")

    def timer_remaining_seconds(self, run_id: str) -> float | None:
        """Remaining seconds for a running *timer* automation, else ``None``.

        Drives the independent server-side timer watcher: count automations
        finish per-generation, but a timer must expire on wall-clock time even
        when no generation is running (future01 QTimer parity).
        """
        runtime = self._runtime_for_run(run_id)
        if runtime is None:
            return None
        if str(runtime.get("automation_type") or "") != "timer":
            return None
        remaining = self._remaining_seconds(runtime)
        return None if remaining is None else float(remaining)

    def begin_delay(self, run_id: str, delay_seconds: float) -> bool:
        runtime = self._runtime_for_run(run_id)
        if runtime is None:
            return False
        runtime["delay_until_monotonic"] = time.monotonic() + max(0.0, float(delay_seconds or 0.0))
        return True

    def end_delay(self, run_id: str) -> bool:
        runtime = self._runtime_for_run(run_id)
        if runtime is None:
            return False
        runtime["delay_until_monotonic"] = None
        return True

    def record_generation_completed(self, run_id: str) -> dict[str, Any]:
        runtime = self._runtime_for_run(run_id)
        if runtime is None:
            return {"continue": False, "messages": []}

        runtime["completed_count"] = int(runtime.get("completed_count") or 0) + 1
        automation_type = str(runtime.get("automation_type") or "unlimited")
        if automation_type == "count":
            remaining = max(0, int(runtime.get("remaining_count") or 0) - 1)
            runtime["remaining_count"] = remaining
            if remaining <= 0:
                return self.finish(run_id, reason="count_complete")
        elif automation_type == "timer":
            if self._remaining_seconds(runtime) <= 0:
                return self.finish(run_id, reason="timer_complete")
        # Repeat Count: 같은 프롬프트를 N회 생성한 뒤 다음 프롬프트로 진행(desktop parity).
        # hold_prompt=True면 러너가 새 프롬프트를 뽑지 않고 직전 프롬프트를 재사용한다.
        hold_prompt = False
        repeat_count = int(runtime.get("repeat_count") or 1)
        if repeat_count > 1:
            progress = int(runtime.get("repeat_progress") or 0) + 1
            if progress < repeat_count:
                runtime["repeat_progress"] = progress
                hold_prompt = True
            else:
                runtime["repeat_progress"] = 0
        return {
            "continue": True,
            "messages": [],
            "delay_seconds": self.next_delay_seconds(),
            "hold_prompt": hold_prompt,
        }

    def finish(self, run_id: str, *, reason: str = "complete", error: str = "") -> dict[str, Any]:
        # 완료(횟수/타이머)·정지·오류는 항상 자동화를 멈추고 Auto Gen을 해제한다.
        # 지속 자동화는 '완료 후 재무장'이 아니라 'Auto Gen을 다시 켜면 재시작'이므로
        # 여기서 재무장하지 않는다(무한 루프 방지). → maybe_autostart 참조.
        self._finish_runtime(run_id, reason=reason)
        settings = self._settings()
        messages: list[dict[str, Any]] = []
        # Disable Auto Gen when the controller finishes so a later manual
        # generate does not silently keep looping (future01 parity).
        options_message = self._engage_auto_generate(False)
        if options_message:
            messages.append(options_message)
        if error:
            messages.append(self.context._toast(f"Automation stopped: {error}", level="error"))
        elif settings.get("notify_on_finish", True):
            messages.append(self.context._toast("Automation complete.", level="success"))
        if settings.get("shutdown_on_finish"):
            messages.append(self.context._toast(AUTOMATION_UNSUPPORTED_SHUTDOWN_MESSAGE, level="info"))
        return {"continue": False, "messages": messages}

    def fail(self, run_id: str, message: str) -> dict[str, Any]:
        return self.finish(run_id, reason="error", error=message)

    def next_delay_seconds(self) -> float:
        settings = self._settings()
        delay = max(0.0, float(settings.get("delay_seconds") or 0.0))
        if delay <= 0:
            return 0.0
        if settings.get("random_delay"):
            return random.uniform(delay * 0.5, delay * 1.5)
        return delay

    def _engage_auto_generate(self, enabled: bool) -> dict[str, Any] | None:
        """Toggle the shared Auto Generate option and return a broadcastable
        ``options`` message when the value actually changed.

        Automation is an Auto Gen controller: starting it engages Auto Gen and
        stopping/finishing disengages it. Returning the message lets the caller
        push the option change to connected clients so the Auto Gen checkbox
        stays in sync.
        """
        try:
            current = bool(self.context.get_options().get("auto_generate", False))
            if current == bool(enabled):
                return None
            self.context.set_option("auto_generate", bool(enabled))
            return {"type": "options", **self.context.get_options()}
        except Exception:
            return None

    def _repeat_count(self) -> int:
        """Session-only Repeat Count (desktop parity: never persisted, default 1).

        Prefers the live runtime value while running, else the pending value the
        UI set via ``set_param('repeat', N)`` so the panel echoes the typed value.
        """
        runtime = self._runtime(create=False)
        if runtime and runtime.get("is_running") and runtime.get("repeat_count"):
            try:
                return max(1, int(runtime.get("repeat_count")))
            except (TypeError, ValueError):
                return 1
        pending = getattr(self.context, "_automation_repeat_pending", None)
        try:
            return max(1, int(pending)) if pending is not None else 1
        except (TypeError, ValueError):
            return 1

    def _settings(self) -> dict[str, Any]:
        from core.automation_settings import load_automation_settings

        context = self.context
        settings = getattr(context, "_automation_settings", None)
        if not isinstance(settings, dict):
            settings = load_automation_settings(context._existing_save_path("AutomationModule.json"))
            context._automation_settings = settings
        return settings

    def _runtime(self, *, create: bool) -> dict[str, Any] | None:
        runtime = getattr(self.context, "automation_runtime_state", None)
        if isinstance(runtime, dict):
            return runtime
        if create:
            runtime = {}
            self.context.automation_runtime_state = runtime
            return runtime
        return None

    def _runtime_for_run(self, run_id: str) -> dict[str, Any] | None:
        runtime = self._runtime(create=False)
        if not runtime or not runtime.get("is_running"):
            return None
        if str(runtime.get("run_id") or "") != str(run_id or ""):
            return None
        return runtime

    def _finish_runtime(self, run_id: str, *, reason: str) -> None:
        runtime = self._runtime(create=False)
        if not runtime or str(runtime.get("run_id") or "") != str(run_id or ""):
            return
        runtime["is_running"] = False
        runtime["finish_reason"] = reason
        runtime["delay_until_monotonic"] = None

    def _credential_error(self) -> str:
        from core.headless_generation_service import TOKEN_KEYS

        api_mode = str(self.context.get_api_mode() or "NAI").upper()
        token_key = TOKEN_KEYS.get(api_mode, "nai_token")
        credential = str(self.context.secure_token_manager.get_token(token_key) or "")
        if credential:
            return ""
        return f"{api_mode} credential is not configured."

    @staticmethod
    def _remaining_seconds(runtime: dict[str, Any] | None) -> int | None:
        if not runtime:
            return None
        ends_at = runtime.get("ends_at_monotonic")
        if ends_at is None:
            return None
        return max(0, int(round(float(ends_at) - time.monotonic())))

    def _delay_info(self, runtime: dict[str, Any] | None) -> str:
        if not runtime or not runtime.get("is_running"):
            return ""
        delay_until = runtime.get("delay_until_monotonic")
        if delay_until is None:
            return ""
        remaining = max(0, int(round(float(delay_until) - time.monotonic())))
        return f"Waiting {remaining}s"

    def _repeat_info(self, settings: dict[str, Any], runtime: dict[str, Any] | None) -> str:
        if not runtime or not runtime.get("is_running"):
            return ""
        automation_type = str(settings.get("automation_type") or runtime.get("automation_type") or "unlimited")
        if automation_type == "count":
            return f"{int(runtime.get('remaining_count') or 0)} generation(s) remaining"
        if automation_type == "timer":
            remaining = self._remaining_seconds(runtime)
            return f"{remaining or 0}s remaining"
        completed = int(runtime.get("completed_count") or 0)
        return f"{completed} generation(s) completed"

    def _status_text(self, settings: dict[str, Any], runtime: dict[str, Any] | None) -> str:
        if runtime and runtime.get("is_running"):
            delay = self._delay_info(runtime)
            if delay:
                return delay
            return "Running"
        reason = str(runtime.get("finish_reason") or "") if runtime else ""
        if reason == "stopped":
            return "Stopped"
        if reason in {"count_complete", "timer_complete", "complete"}:
            return "Complete"
        if reason == "error":
            return "Stopped after error"
        if settings.get("shutdown_on_finish"):
            return "Idle (shutdown-on-finish is unsupported in headless runtime)"
        return ""
