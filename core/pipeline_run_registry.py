"""Small server-owned run registry for headless prompt/generation pipelines."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
import math
from threading import RLock
from typing import Any
import uuid


SENSITIVE_SETTING_KEYS = {
    "credential",
    "token",
    "api_key",
    "nai_token",
    "webui_url",
    "comfyui_url",
}


def _utc_now() -> datetime:
    return datetime.now()


def _safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _safe_value(item())
        except Exception:
            pass
    if isinstance(value, dict):
        return {str(key): _safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value]
    if isinstance(value, set):
        items = [_safe_value(item) for item in value]
        return sorted(items, key=lambda item: str(item))
    return str(value)


def _source_row_name(source_row: Any) -> str:
    return str(getattr(source_row, "name", "") or "")


def _source_row_payload(source_row: Any) -> dict[str, Any]:
    if source_row is None:
        return {}
    to_dict = getattr(source_row, "to_dict", None)
    if callable(to_dict):
        try:
            return _safe_value(to_dict())
        except Exception:
            return {}
    if isinstance(source_row, dict):
        return _safe_value(source_row)
    return {}


def _settings_payload(settings: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(settings, dict):
        return {}
    return {
        str(key): _safe_value(value)
        for key, value in settings.items()
        if str(key).lower() not in SENSITIVE_SETTING_KEYS
    }


@dataclass
class PipelineHookTrace:
    hook_point: str
    module: str
    status: str
    error: str = ""
    timestamp: datetime = field(default_factory=_utc_now)

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "hook_point": self.hook_point,
            "module": self.module,
            "status": self.status,
            "timestamp": self.timestamp.isoformat(),
        }
        if self.error:
            payload["error"] = self.error
        return payload


@dataclass
class PromptPipelineRun:
    prompt_run_id: str
    source: str
    external_request_id: str = ""
    source_row_name: str = ""
    source_row: dict[str, Any] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)
    status: str = "processing"
    final_prompt: str = ""
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    hook_trace: list[PipelineHookTrace] = field(default_factory=list)
    generation_request_ids: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    completed_at: datetime | None = None

    def mark_completed(self, *, final_prompt: str = "", metadata: dict[str, Any] | None = None) -> None:
        self.status = "completed"
        if final_prompt:
            self.final_prompt = final_prompt
        if metadata:
            self.metadata.update(_safe_value(metadata))
        self.updated_at = _utc_now()
        self.completed_at = self.updated_at

    def mark_failed(self, error: str, *, metadata: dict[str, Any] | None = None) -> None:
        self.status = "failed"
        self.error = str(error or "Unknown prompt pipeline error")
        if metadata:
            self.metadata.update(_safe_value(metadata))
        self.updated_at = _utc_now()
        self.completed_at = self.updated_at

    def add_hook_trace(self, hook_point: str, module: str, status: str, error: str = "") -> None:
        self.hook_trace.append(PipelineHookTrace(
            hook_point=str(hook_point or ""),
            module=str(module or ""),
            status=str(status or ""),
            error=str(error or ""),
        ))
        self.updated_at = _utc_now()

    def link_generation_request(self, generation_request_id: str) -> None:
        clean_id = str(generation_request_id or "")
        if clean_id and clean_id not in self.generation_request_ids:
            self.generation_request_ids.append(clean_id)
            self.updated_at = _utc_now()

    def to_payload(self, *, include_source_row: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "prompt_run_id": self.prompt_run_id,
            "source": self.source,
            "external_request_id": self.external_request_id,
            "source_row_name": self.source_row_name,
            "status": self.status,
            "final_prompt": self.final_prompt,
            "error": self.error,
            "metadata": _safe_value(self.metadata),
            "settings": _safe_value(self.settings),
            "hook_trace": [trace.to_payload() for trace in self.hook_trace],
            "generation_request_ids": list(self.generation_request_ids),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
        if include_source_row:
            payload["source_row"] = _safe_value(self.source_row)
        return payload


class PipelineRunRegistry:
    """Bounded in-memory prompt run registry for the server-owned web session."""

    def __init__(self, max_prompt_runs: int = 200):
        self.max_prompt_runs = max(1, int(max_prompt_runs or 200))
        self._prompt_runs: OrderedDict[str, PromptPipelineRun] = OrderedDict()
        self._lock = RLock()

    def start_prompt_run(
        self,
        *,
        source: str,
        source_row: Any = None,
        settings: dict[str, Any] | None = None,
        external_request_id: str = "",
        metadata: dict[str, Any] | None = None,
        prompt_run_id: str = "",
    ) -> PromptPipelineRun:
        run_id = str(prompt_run_id or uuid.uuid4())
        run = PromptPipelineRun(
            prompt_run_id=run_id,
            source=str(source or "prompt"),
            external_request_id=str(external_request_id or ""),
            source_row_name=_source_row_name(source_row),
            source_row=_source_row_payload(source_row),
            settings=_settings_payload(settings),
            metadata=_safe_value(metadata or {}),
        )
        with self._lock:
            self._prompt_runs[run_id] = run
            self._prompt_runs.move_to_end(run_id)
            self._trim_locked()
        return run

    def get_prompt_run(self, prompt_run_id: str) -> PromptPipelineRun | None:
        run_id = str(prompt_run_id or "")
        if not run_id:
            return None
        with self._lock:
            run = self._prompt_runs.get(run_id)
            if run is not None:
                self._prompt_runs.move_to_end(run_id)
            return run

    def latest_prompt_run(self) -> PromptPipelineRun | None:
        with self._lock:
            if not self._prompt_runs:
                return None
            return next(reversed(self._prompt_runs.values()))

    def complete_prompt_run(
        self,
        prompt_run_id: str,
        *,
        final_prompt: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> PromptPipelineRun | None:
        with self._lock:
            run = self._prompt_runs.get(str(prompt_run_id or ""))
            if run is None:
                return None
            run.mark_completed(final_prompt=final_prompt, metadata=metadata)
            self._prompt_runs.move_to_end(run.prompt_run_id)
            return run

    def fail_prompt_run(
        self,
        prompt_run_id: str,
        error: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> PromptPipelineRun | None:
        with self._lock:
            run = self._prompt_runs.get(str(prompt_run_id or ""))
            if run is None:
                return None
            run.mark_failed(error, metadata=metadata)
            self._prompt_runs.move_to_end(run.prompt_run_id)
            return run

    def record_hook(
        self,
        prompt_run_id: str,
        *,
        hook_point: str,
        module: str,
        status: str,
        error: str = "",
    ) -> PromptPipelineRun | None:
        with self._lock:
            run = self._prompt_runs.get(str(prompt_run_id or ""))
            if run is None:
                return None
            run.add_hook_trace(hook_point, module, status, error)
            self._prompt_runs.move_to_end(run.prompt_run_id)
            return run

    def link_generation_request(
        self,
        prompt_run_id: str,
        generation_request_id: str,
    ) -> PromptPipelineRun | None:
        with self._lock:
            run = self._prompt_runs.get(str(prompt_run_id or ""))
            if run is None:
                return None
            run.link_generation_request(generation_request_id)
            self._prompt_runs.move_to_end(run.prompt_run_id)
            return run

    def list_prompt_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            runs = list(self._prompt_runs.values())[-max(1, int(limit or 50)):]
            return [run.to_payload() for run in reversed(runs)]

    def _trim_locked(self) -> None:
        while len(self._prompt_runs) > self.max_prompt_runs:
            self._prompt_runs.popitem(last=False)


__all__ = [
    "PipelineRunRegistry",
    "PromptPipelineRun",
    "PipelineHookTrace",
]
