"""Shared, headless inference transport for Chat, Assist and Auto Boost.

Ollama is the first adapter, not the owner of application tools. A process-wide
endpoint queue prevents independent services from competing for one model server.
No GPU library, process, network probe or model download runs during import/init.
"""
from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
import os
import threading
import time
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4
from weakref import WeakValueDictionary


MINIMUM_MODEL = "hf.co/HauhauCS/Gemma-4-E2B-Uncensored-HauhauCS-Aggressive:IQ3_M"
MINIMUM_RUNTIME_MODEL = "naia-gemma4-e2b-iq3_m:think"


@dataclass(frozen=True)
class ExecutionProfile:
    device: str = "auto"

    def __post_init__(self):
        if self.device not in {"auto", "cpu"}:
            raise ValueError("NAIA_AI_DEVICE must be auto or cpu")

    @classmethod
    def from_environment(cls):
        return cls(device=os.environ.get("NAIA_AI_DEVICE", "auto").strip().lower())

    def low_resource(self, model: str) -> bool:
        return self.device == "cpu" or model in {MINIMUM_MODEL, MINIMUM_RUNTIME_MODEL}

    def context_size(self, task: str, model: str) -> int:
        return 8192 if self.low_resource(model) or task != "chat" else 16384

    def call_seconds(self, task: str, model: str) -> float:
        # Boost is on the generation path: retain its best-effort deadline.
        if task == "boost":
            return 45.0
        if self.low_resource(model):
            return 300.0
        return 120.0 if task == "chat" else 180.0

    def session_seconds(self, task: str, model: str) -> float:
        if task == "boost":
            return 45.0
        return 900.0 if self.low_resource(model) else (240.0 if task == "chat" else 900.0)


class InferenceBusyError(RuntimeError):
    pass


class _EndpointQueue:
    MAX_WAITERS = 32

    def __init__(self):
        self.condition = threading.Condition()
        self.owner: int | None = None
        self.waiters: deque = deque()
        self.active: dict | None = None
        self.recent: deque = deque(maxlen=32)

    @contextmanager
    def acquire(self, task: str, timeout: float):
        start = time.monotonic()
        deadline = start + max(0.0, float(timeout))
        thread = threading.get_ident()
        ticket = object()
        nested = False
        with self.condition:
            if self.owner == thread:
                nested = True
                deadline = min(deadline, self.active["deadline"])
            else:
                if len(self.waiters) >= self.MAX_WAITERS:
                    raise InferenceBusyError("AI 대기열이 가득 찼습니다. 진행 중인 요청이 끝난 뒤 다시 시도하세요.")
                self.waiters.append(ticket)
                try:
                    while self.owner is not None or self.waiters[0] is not ticket:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise InferenceBusyError("AI 실행 대기 시간이 초과되었습니다.")
                        self.condition.wait(remaining)
                    if time.monotonic() >= deadline:
                        raise InferenceBusyError("AI 실행 대기 시간이 초과되었습니다.")
                    self.waiters.popleft()
                    self.owner = thread
                    self.active = {"id": uuid4().hex, "task": task, "started": start,
                                   "deadline": deadline, "queue_seconds": time.monotonic() - start}
                except BaseException:
                    if ticket in self.waiters:
                        self.waiters.remove(ticket)
                    self.condition.notify_all()
                    raise
        try:
            yield deadline
        finally:
            if not nested:
                with self.condition:
                    self.owner = None
                    self.active = None
                    self.condition.notify_all()

    def snapshot(self) -> dict:
        with self.condition:
            active = self.active
            return {"active": bool(active), "queued": len(self.waiters), "max_parallel": 1,
                    "task": active["task"] if active else None,
                    "elapsed_seconds": round(time.monotonic() - active["started"], 3) if active else 0,
                    "recent": deepcopy(list(self.recent))}


_QUEUES: WeakValueDictionary = WeakValueDictionary()
_QUEUES_LOCK = threading.Lock()


def _queue_for(endpoint: str) -> _EndpointQueue:
    parsed = urlsplit(endpoint)
    host = (parsed.hostname or "").lower()
    if host in {"localhost", "127.0.0.1", "::1"}:
        host = "loopback"
    key = (parsed.scheme.lower(), host, parsed.port or (443 if parsed.scheme == "https" else 80),
           parsed.path.rstrip("/"))
    with _QUEUES_LOCK:
        queue = _QUEUES.get(key)
        if queue is None:
            queue = _EndpointQueue()
            _QUEUES[key] = queue
        return queue


class AIBackend:
    """Synchronous adapter: callers run it in the existing backend worker thread.

    Leases are reentrant on the calling thread. Hold one across a tool loop or
    Assist's final unload so another operation cannot unload its active model.
    The queue deadline includes waiting. No retries or automatic model fallback.
    """
    def __init__(self, base_url: str, *, profile: ExecutionProfile | None = None,
                 http_post=None, http_get=None):
        self.base_url = str(base_url).rstrip("/")
        self.profile = profile or ExecutionProfile.from_environment()
        self._queue = _queue_for(self.base_url)
        self._http_post = http_post
        self._http_get = http_get

    @contextmanager
    def operation(self, task: str, *, model: str = "", timeout: float | None = None):
        limit = self.profile.session_seconds(task, model) if timeout is None else timeout
        with self._queue.acquire(task, limit) as deadline:
            yield deadline

    @property
    def busy(self) -> bool:
        state = self._queue.snapshot()
        return state["active"] or state["queued"] > 0

    def get(self, path: str, *, timeout: Any = 1.5):
        import requests
        return (self._http_get or requests.get)(f"{self.base_url}{path}", timeout=timeout)

    def post(self, path: str, payload: dict, *, timeout: Any = (5, 180), task: str = "assist"):
        import requests
        sender = self._http_post or requests.post
        body = deepcopy(payload)  # Never modify caller messages, tool results or options.
        if path not in {"/api/chat", "/api/generate"}:
            return sender(f"{self.base_url}{path}", json=body, timeout=timeout)
        with self._queue.condition:
            if self._queue.owner == threading.get_ident():
                task = self._queue.active["task"]
        if body.get("stream") is True:
            raise ValueError("Streaming inference requires an adapter that owns response lifetime")
        body["stream"] = False
        # The low-memory profile must fail explicitly instead of discarding
        # earlier actors, negations or tool evidence when its context is full.
        body.setdefault("truncate", False)
        body.setdefault("shift", False)
        try:
            keep_alive = int(os.environ.get("NAIA_OLLAMA_KEEP_ALIVE_SECONDS", "180"))
        except ValueError:
            keep_alive = 180
        body.setdefault("keep_alive", keep_alive)
        options = dict(body.get("options") or {})
        if self.profile.device == "cpu":
            options["num_gpu"] = 0
        # Loading and inference use the same context size to avoid reload churn.
        if body.get("keep_alive") != 0:
            options.setdefault("num_ctx", self.profile.context_size(task, str(body.get("model") or "")))
        if options:
            body["options"] = options
        connect, read = timeout if isinstance(timeout, (tuple, list)) else (timeout, timeout)
        started = time.monotonic()
        record = {"task": task, "model": str(body.get("model") or ""), "device": self.profile.device,
                  "options": {k: options[k] for k in ("num_gpu", "num_ctx", "num_predict") if k in options},
                  "status": "error"}
        with self.operation(task, timeout=float(connect) + float(read)) as deadline:
            sent_at = time.monotonic()
            remaining = deadline - sent_at
            if remaining <= 0:
                raise InferenceBusyError("AI 실행 시간이 초과되었습니다.")
            record["queue_seconds"] = round(sent_at - started, 4)
            with self._queue.condition:
                record["operation_id"] = self._queue.active["id"]
                record["operation_queue_seconds"] = round(self._queue.active["queue_seconds"], 4)
            try:
                response = sender(f"{self.base_url}{path}", json=body,
                                  timeout=(min(float(connect), remaining), min(float(read), remaining)))
                record["status"] = "ok" if getattr(response, "status_code", 0) == 200 else "http_error"
                record["http_status"] = getattr(response, "status_code", 0)
                try:
                    data = response.json()
                    if isinstance(data, dict):
                        if data.get("error"):
                            record["status"] = "model_error"
                        # Only numeric counters; never persist prompt, output, thinking or raw error.
                        for key in ("load_duration", "prompt_eval_duration", "eval_duration",
                                    "prompt_eval_count", "eval_count", "total_duration"):
                            if isinstance(data.get(key), (int, float)):
                                record[key] = data[key]
                except (ValueError, AttributeError):
                    pass
                return response
            finally:
                record["http_seconds"] = round(time.monotonic() - sent_at, 4)
                with self._queue.condition:
                    self._queue.recent.append(record)

    def status(self, *, include_details: bool = False) -> dict:
        state = self._queue.snapshot()
        result = {"ok": True, "adapter": "ollama", "device": self.profile.device,
                  "gpu_required": False, "minimum_model": MINIMUM_MODEL,
                  "active": state["active"], "queued": state["queued"], "max_parallel": 1,
                  "task": state["task"], "elapsed_seconds": state["elapsed_seconds"],
                  "runtime_management": "external", "running_cancel_supported": False}
        if include_details:
            result.update(endpoint=self.base_url, recent=state["recent"])
        return result
