from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from core.web_session_context import WebSessionContext


CUSTOM_PARQUET_SCOPE = "custom_parquet"
TAG_ARCHIVE_SCOPE = "tag_archive"


def _tag_archive_sort_key(path: Path) -> tuple[int, str]:
    try:
        return int(path.stem.split("_", 1)[1]), path.name
    except (IndexError, ValueError):
        return 10**9, path.name


def rating_counts_from_frame(frame: Any) -> dict[str, int]:
    if frame is None or getattr(frame, "empty", True) or "rating" not in frame.columns:
        return {rating: 0 for rating in "gsqe"}
    counts = frame["rating"].value_counts()
    return {rating: int(counts.get(rating, 0)) for rating in "gsqe"}


def search_base_frame(context: WebSessionContext):
    base = getattr(context, "search_results_master_base_snapshot", None)
    if base is not None and not getattr(base, "empty", True):
        return base.copy()
    snapshot = getattr(context, "search_results_snapshot", None)
    if snapshot is not None and not getattr(snapshot, "empty", True):
        context.search_results_master_base_snapshot = snapshot.copy()
        return snapshot.copy()
    if context.search_results is not None and not context.search_results.is_empty():
        frame = context.search_results.get_dataframe().copy()
        context.search_results_master_base_snapshot = frame.copy()
        return frame
    return None


def filter_source_frame(
    frame: Any,
    *,
    query: str = "",
    exclude: str = "",
    ratings: set[str] | None = None,
    tag_ids: set[Any] | None = None,
):
    if frame is None or getattr(frame, "empty", True):
        return frame
    filtered = frame.copy()
    if query or exclude:
        from core.search_engine import SearchEngine

        engine = SearchEngine()
        for column in engine.TAG_COLUMNS:
            if column not in filtered.columns:
                filtered[column] = ""
        filtered = engine._apply_filters(filtered, str(query or ""), str(exclude or ""))
        if "tags_string" in filtered.columns:
            filtered = filtered.drop(columns=["tags_string"])
    if tag_ids and "id" in filtered.columns:
        filtered = filtered[filtered["id"].isin(tag_ids)]
    if ratings and "rating" in filtered.columns:
        filtered = filtered[filtered["rating"].isin(ratings)]
    return filtered.copy()


def tag_archive_parquet_sources(context: WebSessionContext) -> list[tuple[Path, str]]:
    sources = getattr(context, "tag_archive_parquet_sources", None)
    if callable(sources):
        return sources()
    root = Path(getattr(context, "repo_root", Path.cwd()))
    tag_dir = root / "data" / "tags"
    if not tag_dir.is_dir():
        return []
    return [
        (path.resolve(), "source tag archive parquet")
        for path in sorted(tag_dir.glob("tags_*.parquet"), key=_tag_archive_sort_key)
        if path.is_file()
    ]


def search_tag_archive_frame(
    sources: list[tuple[Path, str]],
    *,
    query: str,
    exclude: str,
    ratings: set[str],
):
    import pandas as pd
    from core.search_engine import SearchEngine

    search_params = {
        "query": query,
        "exclude_query": exclude,
        "rating_g": "g" in ratings,
        "rating_s": "s" in ratings,
        "rating_q": "q" in ratings,
        "rating_e": "e" in ratings,
    }
    engine = SearchEngine()
    frames: list[Any] = []
    for path, _label in sources:
        result = engine.search_in_file(str(path), search_params)
        if result is not None and not getattr(result, "empty", True):
            frames.append(result)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def apply_search_runtime_filters(context: WebSessionContext) -> dict[str, Any]:
    source = getattr(context, "search_results_snapshot", None)
    if source is None or getattr(source, "empty", True):
        source = search_base_frame(context)
        if source is not None and not getattr(source, "empty", True):
            context.search_results_snapshot = source.copy()
    filtered = filter_source_frame(
        source,
        ratings=context.get_active_ratings(),
        tag_ids=getattr(context, "active_tag_filter_ids", None),
    )
    if filtered is None or getattr(filtered, "empty", True):
        import pandas as pd

        context.search_results.set_dataframe(pd.DataFrame())
    else:
        context.search_results.set_dataframe(filtered)
    return context.search_state_payload()


def clear_active_tag_filter(context: WebSessionContext) -> dict[str, Any]:
    context.active_tag_filter_ids = None
    context.pending_tag_filter = None
    context.active_tag_filter = None
    context.save_search_filter_state(
        tag_filter=[],
        tag_filter_exclude=[],
        tag_filter_active=False,
    )
    return apply_search_runtime_filters(context)


def run_search_command(context: WebSessionContext, command: dict[str, Any]) -> dict[str, Any]:
    ratings = {
        rating
        for rating in "gsqe"
        if command.get(f"rating_{rating}", True)
    } or set("gsqe")
    query = str(command.get("query") or "")
    exclude = str(command.get("exclude") or "")
    context.search_query_ratings = ratings
    context.save_search_filter_state(query=query, exclude=exclude)

    use_custom_scope = getattr(context, "search_results_scope", "") == CUSTOM_PARQUET_SCOPE
    archive_sources = [] if use_custom_scope else tag_archive_parquet_sources(context)
    if archive_sources:
        searched = search_tag_archive_frame(
            archive_sources,
            query=query,
            exclude=exclude,
            ratings=ratings,
        )
        context.search_results.set_dataframe(searched)
        context.search_results_snapshot = searched.copy()
        context.search_results_master_base_snapshot = searched.copy()
        context.search_results_scope = TAG_ARCHIVE_SCOPE
        context.active_tag_filter_ids = None
        context.pending_tag_filter = None
        context.active_tag_filter = None
        context.save_search_filter_state(tag_filter_active=False)
        return apply_search_runtime_filters(context)

    base = search_base_frame(context)
    if base is None:
        return context.search_state_payload()
    searched = filter_source_frame(base, query=query, exclude=exclude, ratings=ratings)
    context.search_results_snapshot = searched.copy() if searched is not None else None
    context.active_tag_filter_ids = None
    context.pending_tag_filter = None
    context.active_tag_filter = None
    context.save_search_filter_state(tag_filter_active=False)
    return apply_search_runtime_filters(context)


def restore_search_snapshot(context: WebSessionContext) -> dict[str, Any]:
    base = search_base_frame(context)
    if base is not None:
        context.search_results_snapshot = base.copy()
        context.active_tag_filter_ids = None
        context.pending_tag_filter = None
        context.active_tag_filter = None
        context.save_search_filter_state(tag_filter_active=False)
        context.search_results.set_dataframe(base.copy())
    return context.search_state_payload()


def tag_filter_search(context: WebSessionContext, tags: list[Any]) -> dict[str, Any]:
    import pandas as pd

    snapshot = getattr(context, "search_results_snapshot", None)
    if snapshot is None or getattr(snapshot, "empty", True):
        snapshot = search_base_frame(context)
        if snapshot is not None:
            context.search_results_snapshot = snapshot.copy()
    normalized = WebSessionContext.normalize_filter_tags(tags)
    if snapshot is None or getattr(snapshot, "empty", True):
        return {
            "type": "tag_filter_result",
            "count": 0,
            "tags": normalized,
            "rating_counts": rating_counts_from_frame(None),
            "_ids": set(),
        }
    searchable = snapshot.copy()
    tag_columns = [column for column in ("copyright", "character", "artist", "meta", "general") if column in searchable.columns]
    if not tag_columns:
        tag_columns = ["general"]
        searchable["general"] = ""
    tags_text = searchable[tag_columns].fillna("").astype(str).agg(",".join, axis=1).str.lower()
    mask = pd.Series(True, index=searchable.index)
    clean_tags: list[str] = []
    for item in tags:
        raw = str(item or "").strip()
        if not raw:
            continue
        negate = raw.startswith("-")
        clean = raw.lstrip("-").strip().replace("_", " ")
        if not clean:
            continue
        clean_tags.append(("-" if negate else "") + clean)
        hit = tags_text.str.contains(clean.lower(), na=False, regex=False)
        mask &= ~hit if negate else hit
    matched = searchable[mask]
    if "id" in matched.columns:
        ids = set(matched["id"].tolist())
    else:
        ids = set(matched.index.tolist())
    return {
        "type": "tag_filter_result",
        "count": int(len(matched)),
        "tags": clean_tags,
        "rating_counts": rating_counts_from_frame(matched),
        "_ids": ids,
    }


def normalize_custom_parquet_filename(filename: str, *, fallback_prefix: str = "search_export") -> str:
    clean = Path(str(filename or "").strip()).name
    if not clean:
        clean = f"{fallback_prefix}_{time.strftime('%Y%m%d_%H%M%S')}.parquet"
    if not clean.lower().endswith(".parquet"):
        clean += ".parquet"
    return clean


def next_custom_parquet_path(context: WebSessionContext, filename: str, *, fallback_prefix: str = "search_export") -> Path:
    explicit = bool(str(filename or "").strip())
    clean = normalize_custom_parquet_filename(filename, fallback_prefix=fallback_prefix)
    path = context.custom_parquet_dir() / clean
    if explicit or not path.exists():
        return path
    for index in range(2, 1000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{path.stem}_{uuid.uuid4().hex[:8]}{path.suffix}")


def resolve_custom_parquet_path(context: WebSessionContext, filename: str) -> Path | None:
    raw = str(filename or "").strip()
    clean = normalize_custom_parquet_filename(raw)
    if raw and clean != raw:
        return None
    return context.custom_parquet_dir() / clean


def load_or_merge_custom_parquet(
    context: WebSessionContext,
    filename: str,
    *,
    merge: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    path = resolve_custom_parquet_path(context, filename)
    if path is None:
        return context.search_state_payload(), {"type": "toast", "message": "Invalid parquet filename", "level": "error"}
    if not path.exists():
        return context.search_state_payload(), {"type": "toast", "message": f"Parquet not found: {filename}", "level": "error"}
    import pandas as pd

    frame = pd.read_parquet(path)
    if merge:
        current = context.search_results.get_dataframe() if context.search_results else pd.DataFrame()
        if current is not None and not current.empty:
            frame = pd.concat([current, frame], ignore_index=True)
    context.search_results.set_dataframe(frame)
    context.search_results_snapshot = context.search_results.get_dataframe().copy()
    context.search_results_master_base_snapshot = context.search_results_snapshot.copy()
    context.search_results_scope = CUSTOM_PARQUET_SCOPE
    state = context.search_state_payload()
    state["merged" if merge else "loaded"] = path.name
    verb = "merged" if merge else "loaded"
    return state, {"type": "toast", "message": f"{path.name} {verb} ({len(frame):,})", "level": "success"}


def search_parquet_action(context: WebSessionContext, command: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    frame = context.search_results.get_dataframe() if context.search_results else None
    if frame is None or frame.empty:
        return context.search_state_payload(), {"type": "toast", "message": "No search results to save", "level": "error"}
    action = str(command.get("action") or "").strip()
    if action == "export_results":
        path = next_custom_parquet_path(context, str(command.get("filename") or ""), fallback_prefix="search_export")
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False)
        message = f"Exported {path.name} ({len(frame):,})"
    elif action == "save_runner":
        path = context.runner_parquet_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False)
        message = f"Saved runner parquet ({len(frame):,})"
    else:
        return context.search_state_payload(), {"type": "toast", "message": "Unsupported parquet action", "level": "error"}
    return context.search_state_payload(), {"type": "toast", "message": message, "level": "success"}
