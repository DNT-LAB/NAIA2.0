"""
Event Preset - Preload all partitions sequentially.

Usage:
    python -m ui.event_preset.preload_all_partitions
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from ui.event_preset.data_manager import EventPresetDataManager


def preload_all(
    data_manager: EventPresetDataManager | None = None,
    progress_callback=None,
) -> dict:
    dm = data_manager or EventPresetDataManager()

    if not dm.is_data_available():
        print("[ERROR] Data file not found.")
        return {"total": 0, "loaded": 0, "failed": [], "elapsed_sec": 0.0}

    partitions = sorted(dm.get_available_partitions())
    total = len(partitions)
    print(f"Found {total} partitions. Loading...\n")

    loaded = 0
    failed: list[str] = []
    t_start = time.perf_counter()

    for i, name in enumerate(partitions):
        t0 = time.perf_counter()
        try:
            data = dm.load_partition_data(name)
            combo_rows = len(data.get("combo", []))
            expr_rows = len(data.get("expression", []))
            cloth_rows = len(data.get("clothing", []))
            char_rows = len(data.get("characteristic", []))
            catalog_rows = len(data.get("catalog", []))
            elapsed_ms = (time.perf_counter() - t0) * 1000

            print(
                f"  [{i+1:>2}/{total}] {name:<45s} "
                f"combo={combo_rows:>6,}  expr={expr_rows:>6,}  "
                f"cloth={cloth_rows:>6,}  char={char_rows:>6,}  "
                f"catalog={catalog_rows:>5,}  "
                f"({elapsed_ms:>6.0f}ms)"
            )
            loaded += 1

            if progress_callback:
                progress_callback(i + 1, total, name, elapsed_ms)

        except Exception as e:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            print(f"  [{i+1:>2}/{total}] {name:<45s} FAILED: {e}  ({elapsed_ms:.0f}ms)")
            failed.append(name)

    elapsed_sec = time.perf_counter() - t_start
    print(f"\n{'='*80}")
    print(f"Done: {loaded}/{total} partitions loaded ({elapsed_sec:.1f}s)")
    if failed:
        print(f"Failed: {', '.join(failed)}")
    print(f"{'='*80}")

    return {
        "total": total,
        "loaded": loaded,
        "failed": failed,
        "elapsed_sec": elapsed_sec,
    }


if __name__ == "__main__":
    preload_all()
