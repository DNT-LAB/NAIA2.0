"""Loader for the per-bucket date map (data/tag_bucket_dates.json) that powers
the search date-cutoff slider. Maps each tag-archive bucket to its id range and
YYYY/MM date span. Static data; cached after first load per resolved path."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# First-run default end date. The default range = full history up to this month.
DEFAULT_END_YM = "2025/03"

_CACHE: dict[str, dict[str, Any]] = {}


def _candidate_paths(context: Any) -> list[Path]:
    paths: list[Path] = []
    runtime = getattr(context, "runtime_paths", None)
    if runtime is not None:
        try:
            paths.append(Path(runtime.data_dir) / "tag_bucket_dates.json")
        except Exception:
            pass
        try:
            paths.append(Path(runtime.resource_path("data")) / "tag_bucket_dates.json")
        except Exception:
            pass
    root = Path(getattr(context, "repo_root", Path.cwd()) or Path.cwd())
    paths.append(root / "data" / "tag_bucket_dates.json")
    # de-dupe preserving order
    seen: set[str] = set()
    unique: list[Path] = []
    for p in paths:
        key = str(p)
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def load_bucket_dates(context: Any) -> dict[str, Any]:
    """Return {version, bucket_count, buckets:[...]}. Empty payload if absent."""
    for path in _candidate_paths(context):
        key = str(path)
        if key in _CACHE:
            return _CACHE[key]
        try:
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, list):  # tolerate bare-list format
                    data = {"version": 1, "bucket_count": len(data), "buckets": data}
                _CACHE[key] = data
                return data
        except Exception:
            continue
    return {"version": 1, "bucket_count": 0, "buckets": []}


def default_bucket_range(buckets: list[dict[str, Any]]) -> tuple[int, int]:
    """First-run default: start at bucket 0, end at the last bucket whose end
    date is on or before DEFAULT_END_YM (date-based so it survives archive growth)."""
    if not buckets:
        return (0, 0)
    last = len(buckets) - 1
    end = max(
        (int(b.get("bucket", i)) for i, b in enumerate(buckets) if str(b.get("end_ym", "")) <= DEFAULT_END_YM),
        default=last,
    )
    return (0, end)


def clamp_bucket_range(start: Any, end: Any, bucket_count: int) -> tuple[int, int]:
    """Coerce a (start, end) request into a valid in-range, ordered pair."""
    last = max(0, bucket_count - 1)
    try:
        s = int(start)
    except (TypeError, ValueError):
        s = 0
    try:
        e = int(end)
    except (TypeError, ValueError):
        e = last
    s = min(max(s, 0), last)
    e = min(max(e, 0), last)
    if s > e:
        s, e = e, s
    return (s, e)
