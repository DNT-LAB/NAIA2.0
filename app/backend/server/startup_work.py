"""Process switch policy and a per-context background CPU slot."""
from __future__ import annotations

import asyncio
import math
import os
import sys
import threading
from contextlib import contextmanager


_switch_interval_applied = False
_switch_interval_original: float | None = None
_switch_interval_startup: float | None = None
_switch_interval_restored = False
_CPU_SLOT_CREATION = threading.Lock()
KOREAN_WARM_WAIT_SECONDS = 120.0


def apply_switch_interval_policy() -> None:
    global _switch_interval_applied, _switch_interval_original, _switch_interval_startup
    if _switch_interval_applied:
        return
    old = sys.getswitchinterval()
    interval = 0.0009 if sys.platform == "win32" and sys.implementation.name == "cpython" else old
    try:
        override = float(os.environ.get("NAIA_GIL_SWITCH_INTERVAL_SECONDS", ""))
    except ValueError:
        pass
    else:
        if math.isfinite(override) and 0 < override <= 0.1:
            interval = override
    if interval != old:
        sys.setswitchinterval(interval)
        _switch_interval_original = old
        _switch_interval_startup = sys.getswitchinterval()
    _switch_interval_applied = True
    print(f"Headless Remote: GIL switch interval {old:g} -> {sys.getswitchinterval():g} seconds", flush=True)


def restore_switch_interval() -> None:
    """시작 예열 창을 닫는다 - 0.9ms 는 세션 중 Python CPU 작업 둘이 겹치면 합계 처리량이 35% 로 떨어진다(2026-10-30 실측)."""
    global _switch_interval_restored
    if _switch_interval_restored or _switch_interval_original is None:
        return
    _switch_interval_restored = True
    current = sys.getswitchinterval()
    # 그사이 누가 바꿨으면 그 값을 존중한다.
    if current != _switch_interval_startup:
        return
    sys.setswitchinterval(_switch_interval_original)
    print(f"Headless Remote: GIL switch interval {current:g} -> {sys.getswitchinterval():g} seconds (startup done)",
          flush=True)


async def restore_switch_interval_after_startup(context) -> None:
    """태그 · 캐릭터 예열과 그 뒤 한국어 층 예열이 끝나면 원래 간격으로 돌아간다."""
    try:
        tasks = [task for task in (getattr(context, "headless_tag_index_warmup_task", None),
                                   getattr(context, "headless_character_index_warmup_task", None))
                 if task is not None]
        if tasks:
            await asyncio.wait(tasks)
        # 한국어 층은 태그 예열 끝에서 깃발을 세우고 스레드로 돈다 - 상한까지만 기다린다.
        loop = asyncio.get_running_loop()
        until = loop.time() + KOREAN_WARM_WAIT_SECONDS
        while getattr(context, "assist_korean_warming", False) and loop.time() < until:
            await asyncio.sleep(0.5)
    finally:
        restore_switch_interval()


def cpu_slot(context):
    with _CPU_SLOT_CREATION:
        slot = getattr(context, "_startup_cpu_slot", None)
        if slot is None:
            slot = threading.Lock()
            context._startup_cpu_slot = slot
        return slot


@contextmanager
def background_cpu_slot(context):
    # 요청이 공유하는 함수 안이 아니라 뒤 worker의 바깥 경계에서만 잡는다.
    with cpu_slot(context):
        yield
