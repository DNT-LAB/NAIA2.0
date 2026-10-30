"""Process switch policy and a per-context background CPU slot."""
from __future__ import annotations

import math
import os
import sys
import threading
from contextlib import contextmanager


_switch_interval_applied = False
_CPU_SLOT_CREATION = threading.Lock()


def apply_switch_interval_policy() -> None:
    global _switch_interval_applied
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
    # 세션 중 복원하지 않는다 - 뒤늦은 예열/캐시 기록에도 같은 정책을 쓴다.
    _switch_interval_applied = True
    print(f"Headless Remote: GIL switch interval {old:g} -> {sys.getswitchinterval():g} seconds", flush=True)


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
