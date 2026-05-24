from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from fastapi import WebSocket

from app.backend.server.search_runtime import (
    apply_search_runtime_filters,
    clear_active_tag_filter,
    load_or_merge_custom_parquet,
    restore_search_snapshot,
    run_search_command,
    search_parquet_action,
    tag_filter_search,
)
from core.web_session_context import WebSessionContext


AsyncRunner = Callable[..., Awaitable[Any]]

SEARCH_COMMAND_TYPES = {
    "set_active_ratings",
    "get_search_state",
    "save_search_filter_state",
    "search",
    "load_parquet",
    "merge_parquet",
    "search_parquet_action",
    "restore_snapshot",
    "tag_filter_search",
    "tag_filter_assign",
    "tag_filter_clear",
}


async def _send_json(ws: WebSocket, payload: dict[str, Any]) -> None:
    await ws.send_text(json.dumps(payload, ensure_ascii=False))


async def handle_search_command(
    ws: WebSocket,
    context: WebSessionContext,
    command: dict[str, Any],
    *,
    run_in_thread: AsyncRunner,
) -> bool:
    command_type = str(command.get("type") or "").strip()
    if command_type not in SEARCH_COMMAND_TYPES:
        return False

    if command_type == "set_active_ratings":
        context.set_active_ratings(command.get("ratings"))
        context.save_search_filter_state(ratings=context.get_active_ratings())
        state = await run_in_thread(apply_search_runtime_filters, context)
        await _send_json(ws, state)
        return True

    if command_type == "get_search_state":
        await _send_json(ws, context.search_state_payload())
        return True

    if command_type == "save_search_filter_state":
        await run_in_thread(context.save_search_filter_state_from_payload, command)
        return True

    if command_type == "search":
        archive_count = 0
        sources = getattr(context, "tag_archive_parquet_sources", None)
        if callable(sources) and getattr(context, "search_results_scope", "") != "custom_parquet":
            archive_count = len(sources())
        progress_total = max(1, archive_count)
        await _send_json(ws, {
            "type": "search_progress",
            "completed": 0,
            "total": progress_total,
        })
        state = await run_in_thread(run_search_command, context, command)
        await _send_json(ws, {
            "type": "search_progress",
            "completed": progress_total,
            "total": progress_total,
        })
        await _send_json(ws, state)
        return True

    if command_type in {"load_parquet", "merge_parquet"}:
        state, toast = await run_in_thread(
            load_or_merge_custom_parquet,
            context,
            str(command.get("filename") or ""),
            merge=command_type == "merge_parquet",
        )
        await _send_json(ws, state)
        await _send_json(ws, toast)
        return True

    if command_type == "search_parquet_action":
        state, toast = await run_in_thread(search_parquet_action, context, command)
        await _send_json(ws, state)
        await _send_json(ws, toast)
        return True

    if command_type == "restore_snapshot":
        state = await run_in_thread(restore_search_snapshot, context)
        await _send_json(ws, state)
        return True

    if command_type == "tag_filter_search":
        tags = command.get("tags") if isinstance(command.get("tags"), list) else []
        request_id = str(command.get("request_id") or "")
        result = await run_in_thread(tag_filter_search, context, tags)
        ids = result.pop("_ids", set())
        if request_id:
            result["request_id"] = request_id
        context.pending_tag_filter = {
            "tags": result.get("tags", []),
            "ids": ids,
            "count": result.get("count", 0),
            "request_id": request_id,
            "rating_counts": result.get("rating_counts", {}),
        }
        await _send_json(ws, result)
        return True

    if command_type == "tag_filter_assign":
        pending = getattr(context, "pending_tag_filter", None)
        request_id = str(command.get("request_id") or "")
        if not pending:
            await _send_json(ws, {
                "type": "toast",
                "message": "No pending search to assign",
                "level": "error",
            })
            return True
        if request_id and str(pending.get("request_id") or "") != request_id:
            await _send_json(ws, {
                "type": "toast",
                "message": "Tag filter search is stale. Search again.",
                "level": "error",
            })
            return True
        context.active_tag_filter_ids = set(pending.get("ids") or set())
        tags = [str(tag) for tag in pending.get("tags", [])]
        context.active_tag_filter = {
            "tags": tags,
            "ids": set(context.active_tag_filter_ids),
            "count": int(pending.get("count") or 0),
            "request_id": request_id,
            "rating_counts": dict(pending.get("rating_counts") or {}),
        }
        context.save_search_filter_state(
            tag_filter=[tag for tag in tags if not tag.startswith("-")],
            tag_filter_exclude=[tag.lstrip("-") for tag in tags if tag.startswith("-")],
            tag_filter_active=True,
        )
        state = await run_in_thread(apply_search_runtime_filters, context)
        await _send_json(ws, {
            "type": "tag_filter_assigned",
            "count": pending.get("count", 0),
            "tags": tags,
            "rating_counts": pending.get("rating_counts", {}),
        })
        await _send_json(ws, state)
        return True

    if command_type == "tag_filter_clear":
        state = await run_in_thread(clear_active_tag_filter, context)
        await _send_json(ws, {
            "type": "tag_filter_result",
            "count": 0,
            "tags": [],
            "rating_counts": {rating: 0 for rating in "gsqe"},
        })
        await _send_json(ws, state)
        return True

    return False
