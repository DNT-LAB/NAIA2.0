"""Chunked parquet reader — load a large parquet in row-batch chunks.

Startup restore and custom parquet load/merge used a single blocking
``pd.read_parquet`` of the whole file, which on a large temp/runner pool stalls
the search pool readiness (and, on low-spec machines, the whole app) while the
one long GIL-holding conversion runs. Reading in batches lets the caller report
progress and yields the GIL between batches so an asyncio event loop stays
responsive during the load. The returned DataFrame is identical to
``pd.read_parquet`` (columns/dtypes) for the index-less parquets we write
(``to_parquet(index=False)``); callers reset_index anyway.

The progress callback receives ``(loaded_rows, total_rows)`` — ``total_rows`` is
read from the file metadata up front (0 if unavailable), and is called once with
``(0, total)`` before the first batch so a UI can show a determinate bar.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

ProgressCallback = Callable[[int, int], None]

# Rows per batch. 100k keeps each to_pandas() conversion short (frequent GIL
# release / progress ticks) without fragmenting into thousands of tiny frames.
DEFAULT_BATCH_ROWS = 100_000


def _rewindable(source: Any) -> Any:
    """Normalize a source (path / bytes / file-like) to something pyarrow and
    pandas can open — re-openable across the chunked pass and the atomic
    fallback. Raw ``bytes`` are wrapped fresh each call; file-likes are seeked
    to 0; everything else is treated as a filesystem path."""
    if isinstance(source, (bytes, bytearray)):
        import io

        return io.BytesIO(source)
    if hasattr(source, "read"):
        try:
            source.seek(0)
        except Exception:
            pass
        return source
    return str(source)


def _pd_read(source: Any, columns: Optional[list[str]]):
    import pandas as pd

    return pd.read_parquet(_rewindable(source), columns=columns)


def parquet_total_rows(source: Path | str | bytes) -> int:
    """Best-effort row count from parquet metadata (0 if unreadable)."""
    try:
        import pyarrow.parquet as pq

        meta = pq.ParquetFile(_rewindable(source)).metadata
        return int(meta.num_rows) if meta is not None else 0
    except Exception:
        return 0


def read_parquet_chunked(
    path: Path | str | bytes,
    *,
    progress: Optional[ProgressCallback] = None,
    batch_rows: int = DEFAULT_BATCH_ROWS,
    columns: Optional[list[str]] = None,
) -> Any:
    """Read a parquet source (filesystem path, raw ``bytes``, or file-like) in
    row batches, returning one concatenated DataFrame.

    Falls back to a plain ``pd.read_parquet`` if pyarrow batch iteration is
    unavailable or the file has no row batches. ``progress(loaded, total)`` is
    invoked after ``(0, total)`` and once per batch; callback errors are
    swallowed so a UI hiccup never fails the load.
    """
    def _tick(loaded: int, total: int) -> None:
        if progress is None:
            return
        try:
            progress(loaded, total)
        except Exception:
            pass

    try:
        import pyarrow.parquet as pq
    except Exception:
        frame = _pd_read(path, columns)
        _tick(len(frame), len(frame))
        return frame

    try:
        parquet_file = pq.ParquetFile(_rewindable(path))
    except Exception:
        frame = _pd_read(path, columns)
        _tick(len(frame), len(frame))
        return frame

    total = int(parquet_file.metadata.num_rows) if parquet_file.metadata is not None else 0
    _tick(0, total)

    frames: list[Any] = []
    loaded = 0
    try:
        iterator = (
            parquet_file.iter_batches(batch_size=batch_rows, columns=columns)
            if columns
            else parquet_file.iter_batches(batch_size=batch_rows)
        )
        for batch in iterator:
            frames.append(batch.to_pandas())
            loaded += batch.num_rows
            _tick(loaded, total or loaded)
    except Exception:
        # Any mid-stream failure → fall back to the atomic read so callers still
        # get a correct frame (progress just won't be granular for the retry).
        frame = _pd_read(path, columns)
        _tick(len(frame), len(frame))
        return frame

    if not frames:
        frame = _pd_read(path, columns)
        _tick(len(frame), len(frame))
        return frame
    if len(frames) == 1:
        return frames[0].reset_index(drop=True)
    import pandas as pd

    return pd.concat(frames, ignore_index=True)


# ── Search-pool load progress broadcast ──────────────────────────────────────
# Progress is surfaced to the Remote Web clients as ``search_loading`` WS
# payloads published over the context event bus (a headless_routes bridge
# broadcasts them to every client). A load smaller than the threshold stays
# silent so a fast pool never flashes the Tag/Tag-Filter lock overlay.
SEARCH_LOADING_EVENT = "search_pool_broadcast"
DEFAULT_LOADING_THRESHOLD = 200_000  # rows


def _publish(context: Any, payload: dict) -> None:
    try:
        context.publish(SEARCH_LOADING_EVENT, payload)
    except Exception:
        pass


def _set_loading_state(context: Any, active: bool, loaded: int, total: int) -> None:
    try:
        context._search_pool_loading = {
            "active": bool(active),
            "loaded": int(loaded),
            "total": int(total),
        }
    except Exception:
        pass


def make_search_load_progress(
    context: Any,
    *,
    threshold: int = DEFAULT_LOADING_THRESHOLD,
) -> tuple[ProgressCallback, Callable[[], None]]:
    """Build ``(progress, done)`` for an announced chunked pool load.

    ``progress(loaded, total)`` is handed to ``read_parquet_chunked``; on the
    first tick it decides — from ``total`` — whether the load is big enough to
    announce (lock + progress) or stays silent. ``done()`` MUST be called once
    after the frame is installed (or the load is abandoned) to clear the loading
    flag and release the client lock. Both are exception-safe.
    """
    # Route through the context's shared depth-counted pool-loading ownership so a
    # parquet LOAD and a concurrent tag-filter FILTER can't clear each other's
    # loading flag (they share one counter; the flag stays until BOTH end). Fall
    # back to direct state writes for contexts without the ownership API (test
    # doubles). Crucially, a silent (small) load NEVER touches the flag now, so it
    # can't clobber a concurrently-active filter.
    use_owner = hasattr(context, "pool_loading_begin")
    state = {"announced": False, "silent": False}

    def _begin(total: int) -> None:
        if use_owner:
            context.pool_loading_begin("load")
            context.pool_loading_progress("load", 0, int(total or 0))
        else:
            _set_loading_state(context, True, 0, total)
            _publish(context, {"type": "search_loading", "loading": True, "loaded": 0, "total": int(total or 0)})

    def _tick(loaded: int, total: int) -> None:
        if use_owner:
            context.pool_loading_progress("load", int(loaded), int(total or loaded))
        else:
            _set_loading_state(context, True, loaded, total)
            _publish(context, {"type": "search_loading", "loading": True, "loaded": int(loaded), "total": int(total or loaded)})

    def _finish() -> None:
        if use_owner:
            context.pool_loading_end()
        else:
            _set_loading_state(context, False, 0, 0)
            _publish(context, {"type": "search_loading", "loading": False})

    def progress(loaded: int, total: int) -> None:
        if state["silent"]:
            return
        if not state["announced"]:
            state["announced"] = True
            if total and total < threshold:
                state["silent"] = True
                return
            _begin(total)
            return
        _tick(loaded, total)

    def done() -> None:
        # Only the announced (non-silent) load owns a begin, so only it ends. A
        # silent load leaves the shared flag untouched (no clobber).
        if state["announced"] and not state["silent"]:
            _finish()

    return progress, done


__all__ = [
    "read_parquet_chunked",
    "parquet_total_rows",
    "make_search_load_progress",
    "DEFAULT_BATCH_ROWS",
    "SEARCH_LOADING_EVENT",
    "DEFAULT_LOADING_THRESHOLD",
]
