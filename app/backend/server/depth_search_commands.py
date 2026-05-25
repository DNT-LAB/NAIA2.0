from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from fastapi import WebSocket

from app.backend.server.search_runtime import (
    clear_active_tag_filter,
    filter_source_frame,
    next_custom_parquet_path,
    search_base_frame,
)
from core.web_session_context import WebSessionContext


AsyncRunner = Callable[..., Awaitable[Any]]

DEPTH_SEARCH_COMMAND_TYPES = {
    "get_depth_state",
    "depth_action",
}


async def _send_json(ws: WebSocket, payload: dict[str, Any]) -> None:
    await ws.send_text(json.dumps(payload, ensure_ascii=False))


def depth_payload(context: WebSessionContext) -> dict[str, Any]:
    state = getattr(context, "depth_state", None)
    if not isinstance(state, dict):
        return {"type": "depth_state", "open": False}
    current = state.get("current")
    original = state.get("original")
    return {
        "type": "depth_state",
        "open": True,
        "count": 0 if current is None or getattr(current, "empty", True) else int(len(current)),
        "original": 0 if original is None or getattr(original, "empty", True) else int(len(original)),
        "query": state.get("query", ""),
        "exclude": state.get("exclude", ""),
        "ratings": state.get("ratings", {rating: True for rating in "eqsg"}),
        "filters": state.get("filters", {}),
        "staging_count": sum(
            0 if item is None or getattr(item, "empty", True) else int(len(item))
            for item in state.get("staging", [])
        ),
        "runtime": "web",
    }


def _numeric_column(frame: Any, name: str) -> str | None:
    candidates = {
        "token_min": ("token_count", "tokens", "estimated_tokens"),
        "token_max": ("token_count", "tokens", "estimated_tokens"),
        "id_min": ("id",),
        "id_max": ("id",),
        "score_min": ("score",),
    }.get(name, ())
    for column in candidates:
        if column in frame.columns:
            return column
    return None


def apply_depth_filters(frame: Any, command: dict[str, Any]):
    filtered = filter_source_frame(
        frame,
        query=str(command.get("query") or ""),
        exclude=str(command.get("exclude") or ""),
        ratings={rating for rating, enabled in (command.get("ratings") or {}).items() if enabled} or set("gsqe"),
    )
    filters = command.get("filters") if isinstance(command.get("filters"), dict) else {}
    if filtered is None or getattr(filtered, "empty", True):
        return filtered
    for name in ("token_min", "id_min", "score_min"):
        spec = filters.get(name) if isinstance(filters.get(name), dict) else {}
        if not spec.get("enabled"):
            continue
        column = _numeric_column(filtered, name)
        if not column:
            continue
        try:
            value = float(spec.get("value"))
        except (TypeError, ValueError):
            continue
        filtered = filtered[filtered[column].astype(float) >= value]
    for name in ("token_max", "id_max"):
        spec = filters.get(name) if isinstance(filters.get(name), dict) else {}
        if not spec.get("enabled"):
            continue
        column = _numeric_column(filtered, name)
        if not column:
            continue
        try:
            value = float(spec.get("value"))
        except (TypeError, ValueError):
            continue
        filtered = filtered[filtered[column].astype(float) <= value]
    if filters.get("rem_char") and "character" in filtered.columns:
        filtered = filtered[filtered["character"].fillna("").astype(str).str.strip() != ""]
    if filters.get("only_empty_char") and "character" in filtered.columns:
        filtered = filtered[filtered["character"].fillna("").astype(str).str.strip() == ""]
    return filtered.copy()


def handle_depth_action(context: WebSessionContext, command: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    action = str(command.get("action") or "").strip()
    if action == "open":
        search_state = None
        if getattr(context, "active_tag_filter_ids", None) is not None or getattr(context, "active_tag_filter", None):
            search_state = clear_active_tag_filter(context)
        base = getattr(context, "search_results_snapshot", None)
        if base is None or getattr(base, "empty", True):
            base = search_base_frame(context)
        if base is None or getattr(base, "empty", True):
            return {"type": "depth_state", "open": False, "error": "no_search_results"}, None
        context.depth_state = {
            "original": base.copy(),
            "current": base.copy(),
            "query": "",
            "exclude": "",
            "ratings": {rating: True for rating in "eqsg"},
            "filters": {},
            "staging": [],
        }
        return depth_payload(context), search_state
    if action == "refresh_from_main":
        if context.search_results is None or context.search_results.is_empty():
            return {"type": "depth_state", "open": False, "error": "no_search_results"}, None
        base = context.search_results.get_dataframe().copy()
        context.depth_state = {
            "original": base.copy(),
            "current": base.copy(),
            "query": "",
            "exclude": "",
            "ratings": {rating: True for rating in "eqsg"},
            "filters": {},
            "staging": [],
        }
        return depth_payload(context), None
    if not isinstance(getattr(context, "depth_state", None), dict):
        return {"type": "depth_state", "open": False}, None
    state = context.depth_state
    if action == "filter":
        state["query"] = str(command.get("query") or "")
        state["exclude"] = str(command.get("exclude") or "")
        state["ratings"] = command.get("ratings") if isinstance(command.get("ratings"), dict) else {
            rating: True for rating in "eqsg"
        }
        state["filters"] = command.get("filters") if isinstance(command.get("filters"), dict) else {}
        state["current"] = apply_depth_filters(state.get("original"), command)
    elif action == "assign":
        current = state.get("current")
        if current is not None:
            context.active_tag_filter_ids = None
            context.pending_tag_filter = None
            context.active_tag_filter = None
            context.save_search_filter_state(tag_filter=[], tag_filter_exclude=[], tag_filter_active=False)
            context.search_results.set_dataframe(current.copy())
            context.search_results_snapshot = current.copy()
        return depth_payload(context), context.search_state_payload()
    elif action == "promote":
        current = state.get("current")
        if current is not None:
            state["original"] = current.copy()
    elif action == "restore":
        original = state.get("original")
        if original is not None:
            state["current"] = original.copy()
    elif action == "stage":
        current = state.get("current")
        if current is not None and not getattr(current, "empty", True):
            state.setdefault("staging", []).append(current.copy())
    elif action == "merge_staging":
        import pandas as pd

        frames = [item for item in state.get("staging", []) if item is not None and not getattr(item, "empty", True)]
        if frames:
            state["current"] = pd.concat(frames, ignore_index=True).drop_duplicates()
    elif action == "clear_staging":
        state["staging"] = []
    elif action == "export":
        current = state.get("current")
        if current is not None and not getattr(current, "empty", True):
            path = next_custom_parquet_path(context, "", fallback_prefix="refine")
            path.parent.mkdir(parents=True, exist_ok=True)
            current.to_parquet(path, index=False)
        return depth_payload(context), context.search_state_payload()
    return depth_payload(context), None


async def handle_depth_search_command(
    ws: WebSocket,
    context: WebSessionContext,
    command: dict[str, Any],
    *,
    run_in_thread: AsyncRunner,
) -> bool:
    command_type = str(command.get("type") or "").strip()
    if command_type not in DEPTH_SEARCH_COMMAND_TYPES:
        return False

    if command_type == "get_depth_state":
        await _send_json(ws, depth_payload(context))
        return True

    depth_state, search_state = await run_in_thread(handle_depth_action, context, command)
    if search_state is not None:
        await _send_json(ws, search_state)
    await _send_json(ws, depth_state)
    return True
