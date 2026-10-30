"""Opt-in startup spans, injected via sitecustomize; no production imports needed.

Set NAIA_STARTUP_PROBE_LOG to an absolute JSONL filename and call install().
Only selected functions are wrapped, after their ordinary import completes.
Arguments, prompts, credentials and returned content are never recorded.
Wall spans are inclusive/overlapping, not additive; cpu_ms is calling-thread CPU.
"""
from __future__ import annotations

import asyncio
import contextvars
import functools
import importlib.machinery
import inspect
import itertools
import json
import os
import sys
import threading
import time
from contextlib import contextmanager

TARGETS = {
    "core.web_session_context": ["WebSessionContext.__post_init__"],
    "core.web_session_app": ["create_headless_app"],
    "core.runtime_install_manager": ["RuntimeInstallManager.initialize"],
    "core.headless_session_state_service": ["HeadlessSessionStateService.initial_websocket_messages"],
    "core.headless_random_prompt_service": [
        "HeadlessRandomPromptService.warmup", "HeadlessRandomPromptService._ensure_headless_runtime",
        "HeadlessRandomPromptService._ensure_search_results"],
    "core.headless_search_state_service": ["HeadlessSearchStateService.restore_last_search"],
    "core.parquet_chunk_loader": ["read_parquet_chunked"],
    "core.search_result_model": ["SearchResultModel.__init__", "SearchResultModel.set_dataframe",
                                 "SearchResultModel.prime_random_cache", "SearchResultModel._load_bucket_starts",
                                 "SearchResultModel._add_bucketed_dataframe", "_consolidate_arrow_chunks"],
    "core.headless_prompt_engineering_service": ["HeadlessPromptEngineeringService.state"],
    "core.kr_tag_loader": ["load_kr_tag_records"],
    "core.tag_search_index": ["TagSearchIndex.from_raw_tag_records", "TagSearchIndex.__init__"],
    "core.tag_index_disk_cache": ["fingerprint", "read_cache", "write_cache"],
    "core.named_entity_aliases": ["ensure_named_entity_index"],
    "core.assist_korean": ["build_vocab", "KoreanLayer.warm"],
    "app.backend.server.assist_v2_service": ["korean_layer"],
    "app.backend.server.autocomplete_commands": ["build_tag_index", "ensure_tag_search_index"],
    "app.backend.server.search_runtime": ["reconstruct_active_tag_filter", "tag_filter_search",
        "_build_tags_text", "_match_tags_text", "apply_search_runtime_filters"],
    "app.backend.server.headless_lifespan": ["_after_startup_gate", "_run_random_warmup",
        "_run_tag_index_warmup", "_run_character_index_warmup"],
    "app.backend.server.websocket_session": ["send_startup_messages", "handle_json_command"],
    "uvicorn.server": ["Server.serve"],
}

_parent = contextvars.ContextVar("startup_probe_parent", default=None)
_ids = itertools.count(1)
_lock = threading.Lock()
_start = time.perf_counter()
_installed = False


def emit(event, **fields):
    path = os.environ.get("NAIA_STARTUP_PROBE_LOG")
    if not path:
        return
    row = dict(event=event, t_ms=round((time.perf_counter() - _start) * 1000, 3),
               epoch_ms=time.time() * 1000, pid=os.getpid(), thread=threading.current_thread().name,
               **fields)
    try:
        with _lock, open(path, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass  # Diagnostics must not break startup.


@contextmanager
def span(name, **fields):
    identity = next(_ids)
    parent = _parent.get()
    started, cpu = time.perf_counter(), time.thread_time()
    emit("begin", name=name, span=identity, parent=parent, **fields)
    token = _parent.set(identity)
    status = "ok"
    try:
        yield
    except BaseException:
        status = "error"
        raise
    finally:
        _parent.reset(token)
        emit("end", name=name, span=identity, parent=parent, status=status,
             wall_ms=round((time.perf_counter() - started) * 1000, 3),
             cpu_ms=round((time.thread_time() - cpu) * 1000, 3))


async def _heartbeat():
    loop = asyncio.get_running_loop()
    while True:
        before = loop.time()
        await asyncio.sleep(0.1)
        emit("loop_lag", lag_ms=round(max(0, loop.time() - before - 0.1) * 1000, 3))


def wrap(function, name):
    if getattr(function, "_startup_probe", False):
        return function
    if inspect.iscoroutinefunction(function):
        @functools.wraps(function)
        async def call(*args, **kwargs):
            heartbeat = asyncio.create_task(_heartbeat()) if name == "uvicorn.server.Server.serve" else None
            try:
                fields = {}
                if name.endswith(".handle_json_command") and len(args) > 4 and isinstance(args[4], dict):
                    fields["command_type"] = str(args[4].get("type", ""))[:80]
                with span(name, **fields):
                    return await function(*args, **kwargs)
            finally:
                if heartbeat is not None:
                    heartbeat.cancel()
                    try:
                        await heartbeat
                    except asyncio.CancelledError:
                        pass
    else:
        @functools.wraps(function)
        def call(*args, **kwargs):
            fields = {}
            if name.startswith("core.search_result_model."):
                frame = next((arg for arg in args[:2] if hasattr(arg, "shape") and hasattr(arg, "columns")), None)
                if frame is not None:
                    fields["rows"] = len(frame)
            with span(name, **fields):
                if name.endswith(".read_parquet_chunked"):
                    original = kwargs.get("progress")
                    def progress(loaded, total):
                        emit("parquet_batch", loaded=int(loaded), total=int(total), parent=_parent.get())
                        if original is not None:
                            original(loaded, total)
                    kwargs["progress"] = progress
                return function(*args, **kwargs)
    call._startup_probe = True
    return call


def instrument(module):
    for dotted in TARGETS.get(module.__name__, []):
        owner = module
        parts = dotted.split(".")
        try:
            for part in parts[:-1]:
                owner = getattr(owner, part)
            attr = parts[-1]
            raw = inspect.getattr_static(owner, attr)
            descriptor = type(raw) if isinstance(raw, (classmethod, staticmethod)) else None
            function = raw.__func__ if descriptor else raw
            wrapped = wrap(function, module.__name__ + "." + dotted)
            setattr(owner, attr, descriptor(wrapped) if descriptor else wrapped)
        except AttributeError:
            emit("missing_target", name=module.__name__ + "." + dotted)
    # Record executor queue delay separately from worker execution; preserve to_thread semantics.
    if module.__name__ == "core.web_session_app":
        async def measured_to_thread(func, /, *args, **kwargs):
            queued = time.perf_counter()
            name = getattr(func, "__qualname__", type(func).__name__)
            def worker():
                emit("worker_start", name=name, queue_ms=(time.perf_counter() - queued) * 1000)
                with span("worker:" + name):
                    return func(*args, **kwargs)
            return await asyncio.to_thread(worker)
        module._to_thread = measured_to_thread
    # Explicit measurement-only isolation: never download the optional character pack.
    if module.__name__ == "core.runtime_install_manager" and os.environ.get("NAIA_STARTUP_PROBE_OFFLINE") == "1":
        def skip_pack(self):
            emit("isolation", name="skip_character_pack_autostart")
            return dict(self._download_state)
        module.RuntimeInstallManager.auto_start_character_pack = skip_pack


class _Loader:
    def __init__(self, inner):
        self.inner = inner

    def create_module(self, spec):
        return self.inner.create_module(spec)

    def exec_module(self, module):
        with span("import:" + module.__name__):
            self.inner.exec_module(module)
        instrument(module)

    def __getattr__(self, name):
        return getattr(self.inner, name)


class _Finder:
    def find_spec(self, fullname, path=None, target=None):
        if fullname not in TARGETS:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
        if spec is not None and spec.loader is not None:
            spec.loader = _Loader(spec.loader)
        return spec


def install():
    global _installed
    if _installed or not os.environ.get("NAIA_STARTUP_PROBE_LOG"):
        return
    _installed = True
    sys.meta_path.insert(0, _Finder())
    emit("probe_installed", executable=sys.executable, cwd=os.getcwd())
