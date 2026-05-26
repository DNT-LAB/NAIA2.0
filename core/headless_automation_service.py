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
                "completed_count": int(runtime.get("completed_count") or 0),
                "remaining_count": runtime.get("remaining_count"),
                "remaining_seconds": self._remaining_seconds(runtime),
            })
        return state

    def set_param(self, key: str, value: Any) -> dict[str, Any] | None:
        from core.automation_settings import save_automation_settings, settings_from_automation_state

        context = self.context
        if key == "start":
            return self.start()
        if key == "stop":
            return self.stop(reason="stopped")

        state = self.state()
        if key == "auto_type":
            state["auto_type"] = value
        elif key in {"delay", "random_delay", "timer_minutes", "count_limit", "notify", "shutdown_on_finish"}:
            state[key] = value
        elif key == "repeat":
            return self.state()
        else:
            return None
        settings = settings_from_automation_state(state)
        context._automation_settings = settings
        save_automation_settings(settings, context._save_path("AutomationModule.json"))
        return self.state()

    def start(self) -> dict[str, Any]:
        settings = self._settings()
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
        }
        self.context.automation_runtime_state = runtime

        build = self._first_generation_command(settings, run_id)
        if build.get("error"):
            self._finish_runtime(run_id, reason="error")
            state = self.state()
            state["_headless_extra_messages"] = [
                self.context._toast(str(build.get("error")), level="error")
            ]
            return state

        state = self.state()
        state["_headless_generation_commands"] = [build["command"]]
        if build.get("messages"):
            state["_headless_extra_messages"] = list(build["messages"])
        return state

    def stop(self, *, reason: str = "stopped") -> dict[str, Any]:
        runtime = self._runtime(create=False)
        if runtime and runtime.get("is_running"):
            runtime["is_running"] = False
            runtime["finish_reason"] = reason
            runtime["delay_until_monotonic"] = None
        return self.state()

    def is_running(self, run_id: str | None = None) -> bool:
        runtime = self._runtime(create=False)
        if not runtime or not runtime.get("is_running"):
            return False
        return not run_id or str(runtime.get("run_id") or "") == str(run_id)

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
        return {"continue": True, "messages": [], "delay_seconds": self.next_delay_seconds()}

    def finish(self, run_id: str, *, reason: str = "complete", error: str = "") -> dict[str, Any]:
        self._finish_runtime(run_id, reason=reason)
        settings = self._settings()
        messages: list[dict[str, Any]] = []
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

    def _base_overrides(self, run_id: str, *, prompt_fixed: bool) -> dict[str, Any]:
        return {
            "auto_generate": True,
            "prompt_fixed": prompt_fixed,
            "automation_run_id": run_id,
            "_remote_queue_source": AUTOMATION_SOURCE,
            "_remote_queue_label": AUTOMATION_SOURCE,
        }

    def _first_generation_command(self, settings: dict[str, Any], run_id: str) -> dict[str, Any]:
        prompt_fixed = self.context._coerce_bool(self.context.get_options().get("prompt_fixed", False))
        overrides = self._base_overrides(run_id, prompt_fixed=prompt_fixed)
        request_id = f"{run_id}:start"
        prompt = str(self.context.prompt_text or "").strip()
        negative = str(self.context.negative_prompt_text or "")
        messages: list[dict[str, Any]] = []
        prompt_run_id = ""

        if not prompt_fixed:
            from core.headless_random_prompt_service import HeadlessRandomPromptService

            service = getattr(self.context, "headless_random_prompt_service", None)
            if service is None:
                service = HeadlessRandomPromptService(self.context)
                self.context.headless_random_prompt_service = service
            result = service.generate(
                active_ratings=self.context.get_active_ratings(),
                overrides=overrides,
                random_request_id=request_id,
            )
            self.context.persist_prompt_engineering_settings()
            payload = result.websocket_payload()
            if not result.success:
                return {"error": payload.get("message") or "Automation start failed: random prompt failed."}
            payload["source"] = "automation"
            messages.append(payload)
            messages.extend(result.extra_messages)
            prompt = result.prompt
            negative = self.context.negative_prompt_text
            prompt_run_id = result.prompt_run_id
            if result.detected_resolution:
                width, height = result.detected_resolution
                overrides["width"] = width
                overrides["height"] = height
                overrides["resolution"] = f"{width} x {height}"

        if not prompt:
            return {"error": "Automation start requires a prompt or a random prompt source."}

        command: dict[str, Any] = {
            "type": "generate",
            "prompt": prompt,
            "negative_prompt": negative,
            "request_id": f"{request_id}:generate",
            "overrides": overrides,
        }
        if prompt_run_id:
            command["prompt_run_id"] = prompt_run_id
        return {"command": command, "messages": messages}

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
