"""PyQt-free FastAPI app for the headless Remote Web Session path."""

from __future__ import annotations

import copy
from contextlib import asynccontextmanager
import json
import asyncio
import io
import math
import time
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from app.backend.server.api_control_commands import (
    API_CONTROL_COMMAND_TYPES,
    handle_api_control_command,
)
from app.backend.server.artist_thumbnail_routes import register_artist_thumbnail_routes
from app.backend.server.character_viewer_routes import register_character_viewer_routes
from app.backend.server.danbooru_routes import register_danbooru_routes
from app.backend.server.event_preset_routes import register_event_preset_routes
from app.backend.server.install_manager_routes import register_install_manager_routes
from app.backend.server.preset_services import (
    clothes_preset_service as _clothes_preset_service,
    event_preset_service as _event_preset_service,
    expression_preset_service as _expression_preset_service,
)
from app.backend.server.params_workflow_routes import register_params_workflow_routes
from app.backend.server.prompt_tools_routes import (
    register_prompt_tools_routes,
    save_prompt_engineering_thumbnail_bytes,
    tag_lookup_info,
)
from app.backend.server.result_display_routes import (
    register_result_display_routes,
    resolve_result_image_action_source,
)
from app.backend.server.state_routes import register_state_routes
from app.backend.server.style_thumbnail_routes import register_style_thumbnail_routes
from app.backend.server.web_shell_routes import register_web_shell_routes
from app.web import resolve_remote_web_dir
from core import result_image_payload_service as result_images
from core.headless_generation_service import HeadlessGenerationService
from core.headless_random_prompt_service import HeadlessRandomPromptService
from core.web_session_context import WebSessionContext


def _client_host(ws: WebSocket) -> str:
    try:
        if ws.client is not None:
            host = str(ws.client.host or "")
            if host == "testclient":
                return "127.0.0.1"
            return host
    except Exception:
        pass
    return ""


def _no_cache_headers() -> dict[str, str]:
    return {"Cache-Control": "no-store, max-age=0"}


async def _send_startup_messages(
    ws: WebSocket,
    context: WebSessionContext,
    *,
    session_id: str,
    client_host: str,
) -> None:
    for message in context.initial_websocket_messages(
        session_id=session_id,
        client_host=client_host,
    ):
        await ws.send_text(json.dumps(message, ensure_ascii=False))
    await ws.send_text(json.dumps({"type": "lazy_indices_ready"}))


async def _send_sync_messages(ws: WebSocket, context: WebSessionContext, client_host: str) -> None:
    messages = [
        {"type": "mode", "mode": context.get_api_mode()},
        {"type": "options", **context.get_options()},
        context.generation_param_schema_payload(),
        context.queue_state_payload(),
        context.api_status_payload(client_host),
        {"type": "lazy_indices_ready"},
    ]
    for message in messages:
        await ws.send_text(json.dumps(message, ensure_ascii=False))


async def _broadcast_json(clients: set[WebSocket], data: dict[str, Any]) -> None:
    text = json.dumps(data, ensure_ascii=False)
    dead = []
    for client in list(clients):
        try:
            await client.send_text(text)
        except Exception:
            dead.append(client)
    for client in dead:
        clients.discard(client)


async def _broadcast_image(clients: set[WebSocket], webp_bytes: bytes, metadata: dict[str, Any]) -> None:
    meta_text = json.dumps({"type": "image_meta", **metadata}, ensure_ascii=False)
    dead = []
    for client in list(clients):
        try:
            await client.send_text(meta_text)
            await client.send_bytes(webp_bytes)
        except Exception:
            dead.append(client)
    for client in dead:
        clients.discard(client)


def _active_ratings_from_command(command: dict[str, Any] | None) -> set[str] | None:
    if not isinstance(command, dict):
        return None
    ratings = command.get("ratings")
    if isinstance(ratings, str):
        ratings = list(ratings)
    if not isinstance(ratings, (list, tuple, set)):
        return None
    picked = {str(item).strip().lower() for item in ratings}
    return {rating for rating in ("g", "s", "q", "e") if rating in picked} or None


def _random_service(context: WebSessionContext) -> HeadlessRandomPromptService:
    service = getattr(context, "headless_random_prompt_service", None)
    if service is None:
        service = HeadlessRandomPromptService(context)
        context.headless_random_prompt_service = service
    return service


def _generation_service(context: WebSessionContext) -> HeadlessGenerationService:
    service = getattr(context, "headless_generation_service", None)
    if service is None:
        service = HeadlessGenerationService(context)
        context.headless_generation_service = service
    return service


def _rating_counts_from_frame(frame: Any) -> dict[str, int]:
    if frame is None or getattr(frame, "empty", True) or "rating" not in frame.columns:
        return {rating: 0 for rating in "gsqe"}
    counts = frame["rating"].value_counts()
    return {rating: int(counts.get(rating, 0)) for rating in "gsqe"}


def _search_base_frame(context: WebSessionContext):
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


def _filter_source_frame(
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


def _apply_search_runtime_filters(context: WebSessionContext) -> dict[str, Any]:
    source = getattr(context, "search_results_snapshot", None)
    if source is None or getattr(source, "empty", True):
        source = _search_base_frame(context)
        if source is not None and not getattr(source, "empty", True):
            context.search_results_snapshot = source.copy()
    filtered = _filter_source_frame(
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


def _run_search_command(context: WebSessionContext, command: dict[str, Any]) -> dict[str, Any]:
    ratings = {
        rating
        for rating in "gsqe"
        if command.get(f"rating_{rating}", True)
    } or set("gsqe")
    query = str(command.get("query") or "")
    exclude = str(command.get("exclude") or "")
    context.save_search_filter_state(query=query, exclude=exclude, ratings=ratings)
    base = _search_base_frame(context)
    if base is None:
        return context.search_state_payload()
    searched = _filter_source_frame(base, query=query, exclude=exclude)
    context.search_results_snapshot = searched.copy() if searched is not None else None
    context.active_tag_filter_ids = None
    context.pending_tag_filter = None
    context.save_search_filter_state(tag_filter_active=False)
    return _apply_search_runtime_filters(context)


def _restore_search_snapshot(context: WebSessionContext) -> dict[str, Any]:
    base = _search_base_frame(context)
    if base is not None:
        context.search_results_snapshot = base.copy()
        context.active_tag_filter_ids = None
        context.pending_tag_filter = None
        context.save_search_filter_state(tag_filter_active=False)
        context.search_results.set_dataframe(base.copy())
    return context.search_state_payload()


def _tag_filter_search(context: WebSessionContext, tags: list[Any]) -> dict[str, Any]:
    import pandas as pd

    snapshot = getattr(context, "search_results_snapshot", None)
    if snapshot is None or getattr(snapshot, "empty", True):
        snapshot = _search_base_frame(context)
        if snapshot is not None:
            context.search_results_snapshot = snapshot.copy()
    normalized = WebSessionContext.normalize_filter_tags(tags)
    if snapshot is None or getattr(snapshot, "empty", True):
        return {"type": "tag_filter_result", "count": 0, "tags": normalized, "rating_counts": _rating_counts_from_frame(None), "_ids": set()}
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
        "rating_counts": _rating_counts_from_frame(matched),
        "_ids": ids,
    }


def _normalize_custom_parquet_filename(filename: str, *, fallback_prefix: str = "search_export") -> str:
    clean = Path(str(filename or "").strip()).name
    if not clean:
        clean = f"{fallback_prefix}_{time.strftime('%Y%m%d_%H%M%S')}.parquet"
    if not clean.lower().endswith(".parquet"):
        clean += ".parquet"
    return clean


def _next_custom_parquet_path(context: WebSessionContext, filename: str, *, fallback_prefix: str = "search_export") -> Path:
    explicit = bool(str(filename or "").strip())
    clean = _normalize_custom_parquet_filename(filename, fallback_prefix=fallback_prefix)
    path = context.custom_parquet_dir() / clean
    if explicit or not path.exists():
        return path
    for index in range(2, 1000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{path.stem}_{uuid.uuid4().hex[:8]}{path.suffix}")


def _resolve_custom_parquet_path(context: WebSessionContext, filename: str) -> Path | None:
    raw = str(filename or "").strip()
    clean = _normalize_custom_parquet_filename(raw)
    if raw and clean != raw:
        return None
    return context.custom_parquet_dir() / clean


def _load_or_merge_custom_parquet(context: WebSessionContext, filename: str, *, merge: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _resolve_custom_parquet_path(context, filename)
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
    state = context.search_state_payload()
    state["merged" if merge else "loaded"] = path.name
    verb = "merged" if merge else "loaded"
    return state, {"type": "toast", "message": f"{path.name} {verb} ({len(frame):,})", "level": "success"}


def _search_parquet_action(context: WebSessionContext, command: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    frame = context.search_results.get_dataframe() if context.search_results else None
    if frame is None or frame.empty:
        return context.search_state_payload(), {"type": "toast", "message": "No search results to save", "level": "error"}
    action = str(command.get("action") or "").strip()
    if action == "export_results":
        path = _next_custom_parquet_path(context, str(command.get("filename") or ""), fallback_prefix="search_export")
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


def _tag_data_roots(context: WebSessionContext) -> list[Path]:
    roots: list[Path] = []
    runtime_paths = getattr(context, "runtime_paths", None)
    if runtime_paths is not None:
        roots.append(runtime_paths.data_dir)
    roots.append(Path(context.repo_root) / "data")
    return roots


def _ensure_tag_search_index(context: WebSessionContext):
    index = getattr(context, "tag_search_index", None)
    if index is not None:
        return index
    from core.kr_tag_loader import load_kr_tag_records
    from core.tag_search_index import TagSearchIndex

    result = load_kr_tag_records(context.repo_root, data_roots=_tag_data_roots(context))
    context.kr_tags_raw = result.raw
    context.autocomplete_state.kr_tags_loaded = bool(result.raw)
    index = TagSearchIndex.from_raw_tag_records(result.raw)
    context.tag_search_index = index
    return index


def _autocomplete_row(result: Any) -> dict[str, Any]:
    entry = result.entry
    return {
        "tag": result.tag,
        "count": int(getattr(entry, "freq", 0) or 0),
        "desc": getattr(entry, "desc", "") or "",
        "group": getattr(entry, "category", "") or "",
        "cat": getattr(entry, "cat", "") or "",
    }


def _search_kr_tags(context: WebSessionContext, query: str, limit: int = 20) -> list[dict[str, Any]]:
    from core.tag_search_index import normalize_search_query

    raw_query = str(query or "")
    q = normalize_search_query(raw_query)
    if not q:
        return []
    cats = None
    if q.startswith("@"):
        cats = {"artist"}
        q = normalize_search_query(q[1:])
    else:
        for prefix in ("artist:", "character:"):
            if q.startswith(prefix):
                cats = {prefix[:-1]}
                q = normalize_search_query(q[len(prefix):])
                break
    if not q:
        return []
    index = _ensure_tag_search_index(context)
    rows = [_autocomplete_row(result) for result in index.search_autocomplete(q, limit=limit, cats=cats)]
    if len(rows) < limit and re.search(r"[가-힣ㄱ-ㅎㅏ-ㅣ]", raw_query):
        seen = {row["tag"] for row in rows}
        for result in index.search_metadata_fallback(q, limit=limit, exclude_noisy_categories=True):
            row = _autocomplete_row(result)
            if row["tag"] in seen:
                continue
            seen.add(row["tag"])
            rows.append(row)
            if len(rows) >= limit:
                break
    return rows[:limit]


def _search_wildcards(context: WebSessionContext, query: str, limit: int = 12) -> list[dict[str, Any]]:
    q = str(query or "").strip().lower()
    if not q:
        return []
    base = context._wildcard_base_dir()
    if not base.exists():
        return []
    results: list[dict[str, Any]] = []
    for path in base.rglob("*.txt"):
        try:
            rel = path.relative_to(base).with_suffix("").as_posix()
            if q not in rel.lower():
                continue
            entries = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            results.append({
                "tag": rel,
                "count": len(entries),
                "desc": f"{len(entries)} entries",
                "group": "wildcard",
                "cat": "",
                "_wc_type": "wildcard",
            })
        except Exception:
            continue
    return sorted(results, key=lambda row: (row["tag"].lower() != q, not row["tag"].lower().startswith(q), row["tag"]))[:limit]


def _search_chunks(context: WebSessionContext, query: str, limit: int = 12) -> list[dict[str, Any]]:
    store = context._instant_wildcard_store()
    tree = dict(store.get("instant_wildcard_tree") or {})
    raw = str(query or "").strip()
    if raw.startswith("$"):
        raw = raw[1:].strip()
    q = raw.lower()

    def preview(value: Any, max_len: int = 96) -> str:
        text = str(value or "").replace("\n", " ").strip()
        return text[:max_len] + "..." if len(text) > max_len else text

    def rank(text: str) -> int | None:
        haystack = str(text or "").lower()
        if not q:
            return 4
        if haystack == q:
            return 0
        if haystack.startswith(q):
            return 1
        if q in haystack:
            return 2
        return None

    rows: list[tuple[int, int, dict[str, Any]]] = []
    if ":" in raw:
        group_name, item_query = raw.split(":", 1)
        q = item_query.strip().lower()
        groups = [(name, items) for name, items in tree.items() if str(name).lower() == group_name.strip().lower()]
    else:
        groups = list(tree.items())
    index = 0
    for group_name, items in groups:
        group_rank = rank(group_name)
        if group_rank is not None and ":" not in raw:
            rows.append((group_rank, index, {
                "tag": str(group_name),
                "value": f"${group_name}:",
                "count": len(items or {}),
                "desc": f"{len(items or {})} entries",
                "group": "chunk group",
                "cat": "",
                "_wc_type": "chunk_group",
            }))
            index += 1
        if isinstance(items, dict):
            for key, value in items.items():
                item_rank = min([r for r in (rank(key), rank(value)) if r is not None], default=None)
                if item_rank is None:
                    continue
                rows.append((item_rank, index, {
                    "tag": str(key),
                    "value": str(value or ""),
                    "count": 0,
                    "desc": preview(value),
                    "group": str(group_name),
                    "cat": "",
                    "preview": str(value or ""),
                    "_wc_type": "chunk",
                }))
                index += 1
    rows.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in rows[:limit]]


def _preset_autocomplete_payload(context: WebSessionContext, query: str, limit: int = 12, preset_context: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        from core.preset_input_bridge import PresetInputBridge, update_app_preset_context

        token = str(query or "").strip()
        if not token.lower().startswith("preset:"):
            token = "preset:" + token
        preset_context = update_app_preset_context(
            context,
            preset_context if isinstance(preset_context, dict) else {},
            source="autocomplete",
        )
        bridge = getattr(context, "preset_autocomplete_bridge", None)
        if bridge is None:
            bridge = PresetInputBridge(
                Path(context.repo_root),
                event_service=_event_preset_service(context),
                clothes_service=_clothes_preset_service(context),
                expression_service=_expression_preset_service(context),
                context=preset_context,
            )
            context.preset_autocomplete_bridge = bridge
        elif hasattr(bridge, "set_context"):
            bridge.set_context(preset_context)
        payload = bridge.suggest(token, limit=limit)
        rows = payload.get("suggestions") or []
        secondary = payload.get("secondaryResults") or payload.get("secondarySuggestions") or []
        if payload.get("stage") in {"loading", "unavailable"}:
            state = payload.get("loadState") or {}
            rows = [{
                "tag": str(state.get("main") or payload.get("stage") or "preset"),
                "value": token,
                "count": 0,
                "desc": str(state.get("message") or "Preset data is not ready."),
                "group": "preset",
                "cat": "preset",
                "_wc_type": "preset_status",
                "disabled": True,
            }]
            secondary = []
        return {
            "query": token,
            "results": rows,
            "secondaryResults": secondary,
            "preset": {
                "axis": payload.get("axis") or "",
                "stage": payload.get("stage") or "",
                "context": payload.get("presetContext") or preset_context,
                "loadState": payload.get("loadState") or {},
                "dataReady": bool(payload.get("dataReady")),
                "secondaryResults": secondary,
            },
        }
    except Exception as exc:
        print(f"Headless Remote: preset autocomplete failed - {exc}", flush=True)
        return {"query": str(query or ""), "results": [], "secondaryResults": [], "preset": {}}


def _depth_payload(context: WebSessionContext) -> dict[str, Any]:
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
        "staging_count": sum(0 if item is None or getattr(item, "empty", True) else int(len(item)) for item in state.get("staging", [])),
        "headless": True,
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


def _apply_depth_filters(frame: Any, command: dict[str, Any]):
    filtered = _filter_source_frame(
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


def _handle_depth_action(context: WebSessionContext, command: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    action = str(command.get("action") or "").strip()
    if action == "open":
        base = getattr(context, "search_results_snapshot", None)
        if base is None or getattr(base, "empty", True):
            base = _search_base_frame(context)
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
        return _depth_payload(context), None
    if not isinstance(getattr(context, "depth_state", None), dict):
        return {"type": "depth_state", "open": False}, None
    state = context.depth_state
    if action == "filter":
        state["query"] = str(command.get("query") or "")
        state["exclude"] = str(command.get("exclude") or "")
        state["ratings"] = command.get("ratings") if isinstance(command.get("ratings"), dict) else {rating: True for rating in "eqsg"}
        state["filters"] = command.get("filters") if isinstance(command.get("filters"), dict) else {}
        state["current"] = _apply_depth_filters(state.get("original"), command)
    elif action == "assign":
        current = state.get("current")
        if current is not None:
            context.active_tag_filter_ids = None
            context.pending_tag_filter = None
            context.save_search_filter_state(tag_filter=[], tag_filter_exclude=[], tag_filter_active=False)
            context.search_results.set_dataframe(current.copy())
            context.search_results_snapshot = current.copy()
        return _depth_payload(context), context.search_state_payload()
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
            path = _next_custom_parquet_path(context, "", fallback_prefix="refine")
            path.parent.mkdir(parents=True, exist_ok=True)
            current.to_parquet(path, index=False)
        return _depth_payload(context), context.search_state_payload()
    return _depth_payload(context), None


def _clamp_result_enhance_number(value: Any, minimum: float, maximum: float, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return min(maximum, max(minimum, number))


def _coerce_result_enhance_bool(value: Any, fallback: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return fallback
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return fallback


def _normalize_result_enhance_config(
    context: WebSessionContext,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    current = context.result_enhance_config if isinstance(context.result_enhance_config, dict) else {}
    upscale_value = payload.get("upscale", current.get("upscale", 1.5))
    try:
        upscale = 1.0 if abs(float(upscale_value) - 1.0) < 0.01 else 1.5
    except (TypeError, ValueError):
        upscale = 1.5
    strength = round(
        _clamp_result_enhance_number(payload.get("strength", current.get("strength", 0.2)), 0.1, 0.9, 0.2),
        1,
    )
    noise = round(
        _clamp_result_enhance_number(payload.get("noise", current.get("noise", 0.0)), 0.0, 0.1, 0.0),
        1,
    )
    return {
        "type": "result_enhance_config",
        "upscale": upscale,
        "strength": strength,
        "noise": noise,
        "available": True,
        "headless": True,
    }


def _normalize_webui_result_enhance_hires_settings(
    context: WebSessionContext,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    payload_settings = payload.get("hires_settings") if isinstance(payload.get("hires_settings"), dict) else {}
    merged = {**dict(context.remote_params or {}), **payload_settings}
    return {
        "enable_hr": True,
        "hr_scale": round(_clamp_result_enhance_number(merged.get("hr_scale"), 1.0, 4.0, 2.0), 1),
        "hr_upscaler": str(merged.get("hr_upscaler") or "Latent (nearest-exact)").strip() or "Latent (nearest-exact)",
        "denoising_strength": round(
            _clamp_result_enhance_number(merged.get("denoising_strength"), 0.0, 1.0, 0.5),
            2,
        ),
        "hires_steps": int(_clamp_result_enhance_number(merged.get("hires_steps"), 0, 150, 10)),
        "hr_cfg": round(_clamp_result_enhance_number(merged.get("hr_cfg"), 0.0, 30.0, 7.0), 1),
        "webui_hiresfix_assist": _coerce_result_enhance_bool(merged.get("webui_hiresfix_assist"), False),
        "webui_hiresfix_assist_target": 768
            if str(merged.get("webui_hiresfix_assist_target") or "").strip() == "768"
            else 512,
    }


def _round_result_enhance_size(value: float) -> int:
    return max(64, int(math.ceil(float(value) / 64.0) * 64))


def _result_enhance_dimension(value: Any, fallback: int) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return int(fallback)
    return max(1, number)


def _apply_webui_result_enhance_size_policy(
    context: WebSessionContext,
    params: dict[str, Any],
    base_w: int,
    base_h: int,
) -> tuple[int, int, float]:
    payload = {"width": base_w, "height": base_h}
    scale = _clamp_result_enhance_number(params.get("hr_scale"), 1.0, 4.0, 2.0)
    try:
        from core.api_service import APIService

        if params.get("webui_hiresfix_assist"):
            payload["width"], payload["height"] = APIService._nearest_hiresfix_assist_resolution(
                payload["width"],
                payload["height"],
                params.get("webui_hiresfix_assist_target", 512),
            )
            service = getattr(context, "api_service", None) or APIService(context)
            scale = service._fit_webui_hiresfix_assist_scale(payload, scale)
    except Exception:
        payload = {"width": base_w, "height": base_h}
    payload_w = _result_enhance_dimension(payload.get("width"), base_w)
    payload_h = _result_enhance_dimension(payload.get("height"), base_h)
    scale = round(_clamp_result_enhance_number(scale, 1.0, 4.0, 2.0), 1)
    params["width"] = payload_w
    params["height"] = payload_h
    params["hr_scale"] = scale
    new_w = max(1, int(math.floor((payload_w * scale) + 0.5)))
    new_h = max(1, int(math.floor((payload_h * scale) + 0.5)))
    return new_w, new_h, scale


def _prompt_from_result_context(
    context: WebSessionContext,
    params: dict[str, Any],
    prompt_context: dict[str, Any],
) -> None:
    if not params.get("input"):
        prompt = (
            prompt_context.get("main_prompt")
            or prompt_context.get("final_prompt")
            or prompt_context.get("prompt")
            or context.prompt_text
            or ""
        )
        params["input"] = str(prompt)
    params["_raw_input"] = str(params.get("_raw_input") or params.get("input") or "")
    if not params.get("negative_prompt"):
        params["negative_prompt"] = str(
            prompt_context.get("negative_prompt")
            or prompt_context.get("uc")
            or context.negative_prompt_text
            or ""
        )


def _prepare_result_enhance_command(
    context: WebSessionContext,
    payload: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    from PIL import Image
    from utils.webui_generation_info import extract_webui_seed

    payload = payload if isinstance(payload, dict) else {}
    current_mode = str(context.get_api_mode() or "").upper()
    requested_mode = str(payload.get("mode") or "").upper()
    if current_mode not in {"NAI", "WEBUI"}:
        raise RuntimeError("Enhance is available in NAI or WEBUI mode only")
    mode = current_mode
    if requested_mode in {"NAI", "WEBUI"} and requested_mode != current_mode:
        raise RuntimeError("Enhance mode changed; refresh the result selection")

    image_bytes, label, generation_params, prompt_context = resolve_result_image_action_source(context, payload)
    if not generation_params:
        raise RuntimeError("Generation parameters are unavailable")
    with Image.open(io.BytesIO(image_bytes)) as image:
        orig_w, orig_h = image.size
    params = copy.deepcopy(generation_params)
    _prompt_from_result_context(context, params, prompt_context)
    for key in ("credential", "schema_only", "options_model", "options_sampler", "options_scheduler", "options_resolution"):
        params.pop(key, None)

    if mode == "NAI":
        config = _normalize_result_enhance_config(context, payload)
        upscale = float(config["upscale"])
        new_w, new_h = (orig_w, orig_h) if upscale == 1.0 else (
            _round_result_enhance_size(orig_w * 1.5),
            _round_result_enhance_size(orig_h * 1.5),
        )
        params.update({
            "image_bytes": image_bytes,
            "strength": float(config["strength"]),
            "noise": float(config["noise"]),
            "width": new_w,
            "height": new_h,
            "api_mode": "NAI",
            "result_enhance_request": True,
            "result_enhance_backend": "NAI",
            "result_enhance_upscale": upscale,
            "result_enhance_strength": float(config["strength"]),
            "result_enhance_source_size": [orig_w, orig_h],
            "result_enhance_preview_size": [new_w, new_h],
            "_remote_queue_source": "NAI Enhance",
            "_remote_queue_label": label,
        })
        params.pop("type", None)
        params.pop("mask_bytes", None)
        params.pop("_skip_vibe_transfer_late_binding", None)
        message = "Enhance queued"
    else:
        hires_settings = _normalize_webui_result_enhance_hires_settings(context, payload)
        params.pop("type", None)
        params.pop("image_bytes", None)
        params.pop("mask_bytes", None)
        params.pop("strength", None)
        params.pop("noise", None)
        base_w = _result_enhance_dimension(params.get("width"), orig_w)
        base_h = _result_enhance_dimension(params.get("height"), orig_h)
        seed = extract_webui_seed(params)
        if seed is None:
            raise RuntimeError("WEBUI result seed is unavailable; cannot reproduce source image for Enhance")
        params.update({
            **hires_settings,
            "width": base_w,
            "height": base_h,
            "seed": seed,
            "seed_fixed": True,
            "random_resolution": False,
            "resolution_preset_enabled": False,
            "resolution": f"{base_w} x {base_h}",
            "api_mode": "WEBUI",
            "result_enhance_request": True,
            "result_enhance_backend": "WEBUI",
            "result_enhance_source_size": [orig_w, orig_h],
            "_remote_queue_source": "WEBUI Enhance",
            "_remote_queue_label": label,
        })
        new_w, new_h, upscale = _apply_webui_result_enhance_size_policy(context, params, base_w, base_h)
        params.update({
            "result_enhance_upscale": upscale,
            "result_enhance_strength": params.get("denoising_strength", 0.5),
            "result_enhance_hr_upscaler": params.get("hr_upscaler", ""),
            "result_enhance_hires_steps": params.get("hires_steps", 10),
            "result_enhance_hr_cfg": params.get("hr_cfg", 7.0),
            "result_enhance_preview_size": [new_w, new_h],
        })
        message = "Enhance queued"

    return {
        "type": "generate",
        "api_mode": mode,
        "overrides": params,
    }, {
        "type": "result_enhance_state",
        "running": True,
        "message": message,
        "api_mode": mode,
        "source_size": [orig_w, orig_h],
        "preview_size": params.get("result_enhance_preview_size", [orig_w, orig_h]),
        "headless": True,
    }


async def _handle_random_command(
    ws: WebSocket,
    context: WebSessionContext,
    command: dict[str, Any] | None = None,
) -> None:
    command = command if isinstance(command, dict) else {}
    overrides = command.get("overrides") if isinstance(command.get("overrides"), dict) else None
    request_id = str(command.get("random_request_id") or command.get("requestId") or "")
    active_ratings = _active_ratings_from_command(command) or context.get_active_ratings()
    result = await _to_thread(
        _random_service(context).generate,
        active_ratings=active_ratings,
        overrides=overrides,
        random_request_id=request_id,
    )
    await ws.send_text(json.dumps(result.websocket_payload(), ensure_ascii=False))


async def _handle_generate_command(
    ws: WebSocket,
    context: WebSessionContext,
    clients: set[WebSocket],
    command: dict[str, Any] | None = None,
) -> None:
    command = command if isinstance(command, dict) else {}
    result = await _to_thread(_generation_service(context).enqueue_remote_request, command)
    await ws.send_text(json.dumps(result.websocket_payload(), ensure_ascii=False))
    if not result.ok:
        await ws.send_text(json.dumps({
            "type": "toast",
            "level": "error",
            "message": result.blocked_reason,
        }, ensure_ascii=False))
        await ws.send_text(json.dumps({
            "type": "status",
            "is_generating": False,
            "message": "blocked",
        }, ensure_ascii=False))
        return
    await ws.send_text(json.dumps({
        "type": "status",
        "is_generating": False,
        "message": "queued",
    }, ensure_ascii=False))
    await ws.send_text(json.dumps(context.queue_state_payload(), ensure_ascii=False))
    if context.headless_generation_execute_enabled:
        _ensure_generation_runner(context, clients)


async def _enqueue_prompt_from_module(
    ws: WebSocket,
    context: WebSessionContext,
    clients: set[WebSocket],
    *,
    prompt: str,
    source: str,
) -> None:
    clean_prompt = str(prompt or "").strip()
    if not clean_prompt:
        return
    command = {
        "type": "generate",
        "prompt": clean_prompt,
        "negative_prompt": context.negative_prompt_text,
        "overrides": {
            "input": clean_prompt,
            "_raw_input": clean_prompt,
            "_remote_queue_source": source,
            "_remote_queue_label": source,
        },
    }
    result = await _to_thread(_generation_service(context).enqueue_remote_request, command)
    await ws.send_text(json.dumps(result.websocket_payload(), ensure_ascii=False))
    if not result.ok:
        await ws.send_text(json.dumps({
            "type": "toast",
            "level": "error",
            "message": result.blocked_reason,
        }, ensure_ascii=False))
        return
    await ws.send_text(json.dumps({
        "type": "status",
        "is_generating": False,
        "message": "queued",
    }, ensure_ascii=False))
    await ws.send_text(json.dumps(context.queue_state_payload(), ensure_ascii=False))
    if context.headless_generation_execute_enabled:
        _ensure_generation_runner(context, clients)


async def _enqueue_headless_generation_commands(
    ws: WebSocket,
    context: WebSessionContext,
    clients: set[WebSocket],
    commands: list[dict[str, Any]],
) -> None:
    queued = 0
    for command in commands:
        if not isinstance(command, dict):
            continue
        result = await _to_thread(_generation_service(context).enqueue_remote_request, command)
        await ws.send_text(json.dumps(result.websocket_payload(), ensure_ascii=False))
        if not result.ok:
            await ws.send_text(json.dumps({
                "type": "toast",
                "level": "error",
                "message": result.blocked_reason,
            }, ensure_ascii=False))
            continue
        queued += 1
    if queued:
        await ws.send_text(json.dumps({
            "type": "status",
            "is_generating": False,
            "message": "queued",
        }, ensure_ascii=False))
        await ws.send_text(json.dumps({
            "type": "toast",
            "level": "success",
            "message": f"{queued} generation request(s) queued",
        }, ensure_ascii=False))
        await ws.send_text(json.dumps(context.queue_state_payload(), ensure_ascii=False))
        if context.headless_generation_execute_enabled:
            _ensure_generation_runner(context, clients)


def _ensure_generation_runner(context: WebSessionContext, clients: set[WebSocket]) -> None:
    task = getattr(context, "headless_generation_runner_task", None)
    if task is not None and not task.done():
        return
    context.headless_generation_runner_task = asyncio.create_task(_run_generation_queue(context, clients))


async def _run_generation_queue(context: WebSessionContext, clients: set[WebSocket]) -> None:
    if getattr(context, "headless_generation_runner_active", False):
        return
    context.headless_generation_runner_active = True
    try:
        while True:
            request = await _to_thread(context.generation_queue_manager.dequeue_request)
            if request is None:
                break
            context.is_generating = True
            await _broadcast_json(clients, {"type": "status", "is_generating": True, "message": "generating"})
            await _broadcast_json(clients, context.queue_state_payload())
            try:
                stored = await _to_thread(_generation_service(context).execute_request, request)
            except Exception as exc:
                context.is_generating = False
                message = str(exc)
                params = getattr(request, "params", {}) or {}
                await _broadcast_json(clients, {"type": "status", "is_generating": False, "message": "error"})
                await _broadcast_json(clients, {"type": "toast", "level": "error", "message": message})
                await _broadcast_json(clients, {"type": "generation_error", "message": message})
                if params.get("result_enhance_request"):
                    await _broadcast_json(clients, {
                        "type": "result_enhance_state",
                        "running": False,
                        "success": False,
                        "message": message,
                        "request_id": str(params.get("result_enhance_request_id") or request.request_id),
                        "headless": True,
                    })
                if params.get("event_preset_request"):
                    await _broadcast_json(clients, {
                        "type": "event_preset_generation_error",
                        "requestId": str(params.get("event_preset_request_id") or ""),
                        "message": message,
                    })
                if params.get("remote_preset_request"):
                    await _broadcast_json(clients, {
                        "type": "preset_generation_error",
                        "requestId": str(params.get("remote_preset_request_id") or ""),
                        "message": message,
                    })
                await _broadcast_json(clients, context.queue_state_payload())
                continue

            context.is_generating = False
            await _broadcast_json(clients, {"type": "status", "is_generating": False, "message": "completed"})
            params = getattr(request, "params", {}) or {}
            if params.get("prompt_preset_thumbnail_request"):
                try:
                    png_bytes, _ = result_images.history_item_png_payload(stored.item, label=stored.item.filename)
                    thumbnail_payload = await _to_thread(
                        save_prompt_engineering_thumbnail_bytes,
                        context,
                        str(params.get("prompt_preset_thumbnail_name") or ""),
                        str(params.get("prompt_preset_thumbnail_mode") or ""),
                        png_bytes,
                    )
                    await _broadcast_json(clients, {
                        "type": "prompt_engineering_preset_thumbnail_updated",
                        "request_id": str(params.get("prompt_preset_thumbnail_request_id") or ""),
                        **thumbnail_payload,
                    })
                except Exception as exc:
                    await _broadcast_json(clients, {
                        "type": "toast",
                        "level": "error",
                        "message": f"Preset thumbnail save failed: {exc}",
                    })
            if params.get("result_enhance_request"):
                await _broadcast_json(clients, {
                    "type": "result_enhance_state",
                    "running": False,
                    "success": True,
                    "message": "Enhance complete",
                    "request_id": str(params.get("result_enhance_request_id") or request.request_id),
                    "headless": True,
                })
            await _broadcast_image(clients, stored.item.webp_bytes, stored.image_meta)
            await _broadcast_json(clients, context.result_store.viewer_new_image_payload(stored.item))
            await _broadcast_json(clients, context.queue_state_payload())
    finally:
        context.is_generating = False
        context.headless_generation_runner_active = False


async def _handle_json_command(
    ws: WebSocket,
    context: WebSessionContext,
    clients: set[WebSocket],
    client_host: str,
    command: dict[str, Any],
) -> None:
    command_type = str(command.get("type") or "").strip()
    if command_type == "sync":
        await _send_sync_messages(ws, context, client_host)
    elif command_type == "set_option":
        context.set_option(str(command.get("key") or ""), command.get("value"))
        await _broadcast_json(clients, {"type": "options", **context.get_options()})
    elif command_type == "set_mode":
        requested_mode = str(command.get("mode") or "").strip().upper()
        if requested_mode not in {"NAI", "WEBUI", "COMFYUI"}:
            await ws.send_text(json.dumps({
                "type": "mode_result",
                "success": False,
                "mode": requested_mode,
                "message": f"Unknown mode: {requested_mode}",
            }, ensure_ascii=False))
            return
        token_key = {
            "NAI": "nai_token",
            "WEBUI": "webui_url",
            "COMFYUI": "comfyui_url",
        }[requested_mode]
        if not str(context.secure_token_manager.get_token(token_key) or ""):
            await ws.send_text(json.dumps({
                "type": "mode_result",
                "success": False,
                "mode": requested_mode,
                "message": f"{requested_mode} API is not connected",
            }, ensure_ascii=False))
            await ws.send_text(json.dumps(context.api_status_payload(client_host), ensure_ascii=False))
            return
        context.set_api_mode(requested_mode)
        await _broadcast_json(clients, {
            "type": "mode_result",
            "success": True,
            "mode": context.get_api_mode(),
            "message": f"{context.get_api_mode()} mode active",
        })
        await _broadcast_json(clients, {"type": "mode", "mode": context.get_api_mode()})
        await _broadcast_json(clients, context.generation_param_schema_payload())
        await ws.send_text(json.dumps(context.api_status_payload(client_host), ensure_ascii=False))
    elif command_type == "set_prompt":
        context.prompt_text = str(command.get("prompt") or "")
        context.negative_prompt_text = str(command.get("negative_prompt", command.get("negative")) or "")
        await ws.send_text(json.dumps({
            "type": "prompt_sync",
            "prompt": context.prompt_text,
            "negative": context.negative_prompt_text,
        }, ensure_ascii=False))
    elif command_type == "set_param":
        context.set_param(str(command.get("key") or ""), command.get("value"))
        await _broadcast_json(clients, context.generation_param_schema_payload())
    elif command_type == "set_active_ratings":
        context.set_active_ratings(command.get("ratings"))
        context.save_search_filter_state(ratings=context.get_active_ratings())
        state = await _to_thread(_apply_search_runtime_filters, context)
        await ws.send_text(json.dumps(state, ensure_ascii=False))
    elif command_type in API_CONTROL_COMMAND_TYPES:
        await handle_api_control_command(
            ws,
            context,
            client_host,
            command,
            run_in_thread=_to_thread,
        )
    elif command_type == "set_desktop_window_visibility":
        await ws.send_text(json.dumps({
            "type": "toast",
            "level": "info",
            "message": "Desktop runtime is not available in headless mode.",
            "headless": True,
        }, ensure_ascii=False))
        await ws.send_text(json.dumps(context.desktop_window_state_payload(client_host), ensure_ascii=False))
    elif command_type == "get_search_state":
        await ws.send_text(json.dumps(context.search_state_payload(), ensure_ascii=False))
    elif command_type == "save_search_filter_state":
        await _to_thread(context.save_search_filter_state_from_payload, command)
    elif command_type == "search":
        await ws.send_text(json.dumps({
            "type": "search_progress",
            "completed": 0,
            "total": 1,
        }, ensure_ascii=False))
        state = await _to_thread(_run_search_command, context, command)
        await ws.send_text(json.dumps({
            "type": "search_progress",
            "completed": 1,
            "total": 1,
        }, ensure_ascii=False))
        await ws.send_text(json.dumps(state, ensure_ascii=False))
    elif command_type in {"load_parquet", "merge_parquet"}:
        state, toast = await _to_thread(
            _load_or_merge_custom_parquet,
            context,
            str(command.get("filename") or ""),
            merge=command_type == "merge_parquet",
        )
        await ws.send_text(json.dumps(state, ensure_ascii=False))
        await ws.send_text(json.dumps(toast, ensure_ascii=False))
    elif command_type == "search_parquet_action":
        state, toast = await _to_thread(_search_parquet_action, context, command)
        await ws.send_text(json.dumps(state, ensure_ascii=False))
        await ws.send_text(json.dumps(toast, ensure_ascii=False))
    elif command_type == "restore_snapshot":
        state = await _to_thread(_restore_search_snapshot, context)
        await ws.send_text(json.dumps(state, ensure_ascii=False))
    elif command_type == "tag_filter_search":
        tags = command.get("tags") if isinstance(command.get("tags"), list) else []
        request_id = str(command.get("request_id") or "")
        result = await _to_thread(_tag_filter_search, context, tags)
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
        await ws.send_text(json.dumps(result, ensure_ascii=False))
    elif command_type == "tag_filter_assign":
        pending = getattr(context, "pending_tag_filter", None)
        request_id = str(command.get("request_id") or "")
        if not pending:
            await ws.send_text(json.dumps({
                "type": "toast",
                "message": "No pending search to assign",
                "level": "error",
            }, ensure_ascii=False))
        elif request_id and str(pending.get("request_id") or "") != request_id:
            await ws.send_text(json.dumps({
                "type": "toast",
                "message": "Tag filter search is stale. Search again.",
                "level": "error",
            }, ensure_ascii=False))
        else:
            context.active_tag_filter_ids = set(pending.get("ids") or set())
            tags = [str(tag) for tag in pending.get("tags", [])]
            context.save_search_filter_state(
                tag_filter=[tag for tag in tags if not tag.startswith("-")],
                tag_filter_exclude=[tag.lstrip("-") for tag in tags if tag.startswith("-")],
                tag_filter_active=True,
            )
            state = await _to_thread(_apply_search_runtime_filters, context)
            await ws.send_text(json.dumps({
                "type": "tag_filter_assigned",
                "count": pending.get("count", 0),
                "tags": tags,
            }, ensure_ascii=False))
            await ws.send_text(json.dumps(state, ensure_ascii=False))
    elif command_type == "tag_filter_clear":
        context.active_tag_filter_ids = None
        context.pending_tag_filter = None
        context.save_search_filter_state(tag_filter=[], tag_filter_exclude=[], tag_filter_active=False)
        state = await _to_thread(_apply_search_runtime_filters, context)
        await ws.send_text(json.dumps({
            "type": "tag_filter_result",
            "count": 0,
            "tags": [],
            "rating_counts": {rating: 0 for rating in "gsqe"},
        }, ensure_ascii=False))
        await ws.send_text(json.dumps(state, ensure_ascii=False))
    elif command_type == "tag_search":
        query = str(command.get("query") or "")
        results = await _to_thread(_search_kr_tags, context, query, 20)
        await ws.send_text(json.dumps({
            "type": "tag_search_result",
            "query": query,
            "results": results,
        }, ensure_ascii=False))
    elif command_type == "tag_filter_ac":
        query = str(command.get("query") or "")
        results = await _to_thread(_search_kr_tags, context, query, 12)
        await ws.send_text(json.dumps({
            "type": "tag_filter_ac_result",
            "query": query,
            "results": results,
        }, ensure_ascii=False))
    elif command_type == "autocomplete":
        query = str(command.get("query") or "")
        results = await _to_thread(_search_kr_tags, context, query, 12)
        await ws.send_text(json.dumps({
            "type": "autocomplete_result",
            "query": query,
            "results": results,
        }, ensure_ascii=False))
    elif command_type == "autocomplete_translate":
        query = str(command.get("query") or "")
        request_id = str(command.get("requestId") or command.get("request_id") or "")
        results = await _to_thread(_search_kr_tags, context, query, 12)
        payload = {
            "type": "autocomplete_result",
            "query": query,
            "results": results,
            "translated_query": "",
        }
        if request_id:
            payload["requestId"] = request_id
        await ws.send_text(json.dumps(payload, ensure_ascii=False))
    elif command_type == "autocomplete_wildcard":
        query = str(command.get("query") or "")
        results = await _to_thread(_search_wildcards, context, query, 12)
        await ws.send_text(json.dumps({
            "type": "autocomplete_result",
            "query": query,
            "results": results,
        }, ensure_ascii=False))
    elif command_type == "autocomplete_chunk":
        query = str(command.get("query") or "")
        results = await _to_thread(_search_chunks, context, query, 12)
        await ws.send_text(json.dumps({
            "type": "autocomplete_result",
            "query": query,
            "results": results,
        }, ensure_ascii=False))
    elif command_type == "autocomplete_vibe_cluster":
        query = str(command.get("query") or "")
        from core.vibe_cluster_resolver import search_vibe_clusters

        results = await _to_thread(search_vibe_clusters, query, 12, context._existing_save_path("vibe_transfer_clusters"))
        await ws.send_text(json.dumps({
            "type": "autocomplete_result",
            "query": query,
            "results": results,
        }, ensure_ascii=False))
    elif command_type == "autocomplete_preset":
        query = str(command.get("query") or "")
        payload = await _to_thread(
            _preset_autocomplete_payload,
            context,
            query,
            12,
            command.get("presetContext") if isinstance(command.get("presetContext"), dict) else command.get("context"),
        )
        await ws.send_text(json.dumps({
            "type": "autocomplete_result",
            "query": payload.get("query", query),
            "results": payload.get("results", []),
            "secondaryResults": payload.get("secondaryResults", []),
            "preset": payload.get("preset") or {},
        }, ensure_ascii=False))
    elif command_type == "tag_lookup":
        info = await _to_thread(tag_lookup_info, context, str(command.get("tag") or ""))
        await ws.send_text(json.dumps({"type": "tag_lookup_result", **info}, ensure_ascii=False))
    elif command_type == "get_depth_state":
        await ws.send_text(json.dumps(_depth_payload(context), ensure_ascii=False))
    elif command_type == "depth_action":
        depth_state, search_state = await _to_thread(_handle_depth_action, context, command)
        if search_state is not None:
            await ws.send_text(json.dumps(search_state, ensure_ascii=False))
        await ws.send_text(json.dumps(depth_state, ensure_ascii=False))
    elif command_type == "read_hires_preset_overlay":
        preset_name = str(command.get("preset_name") or "")
        response = await _to_thread(context.hires_overlay_response, preset_name)
        await ws.send_text(json.dumps(response, ensure_ascii=False))
    elif command_type == "write_hires_preset_overlay":
        preset_name = str(command.get("preset_name") or "")
        action = str(command.get("action") or "save")
        if action == "reset":
            ok, message = await _to_thread(context.reset_hires_overlay, preset_name)
        else:
            body = command.get("body") if isinstance(command.get("body"), dict) else {}
            ok, message = await _to_thread(context.write_hires_overlay, preset_name, body)
        await ws.send_text(json.dumps({
            "type": "toast",
            "level": "success" if ok else "error",
            "message": message,
            "headless": True,
        }, ensure_ascii=False))
        if ok:
            response = await _to_thread(context.hires_overlay_response, preset_name)
            await ws.send_text(json.dumps(response, ensure_ascii=False))
    elif command_type == "set_module_param":
        module_state = context.set_module_param(
            str(command.get("module_id") or ""),
            str(command.get("key") or ""),
            command.get("value"),
            client_host=client_host,
        )
        if module_state is None:
            await ws.send_text(json.dumps({
                "type": "toast",
                "level": "info",
                "message": "Headless command retired: set_module_param",
                "headless": True,
            }, ensure_ascii=False))
        elif isinstance(module_state, list):
            generated_prompt = ""
            generated_source = ""
            for item in module_state:
                if isinstance(item, dict):
                    await ws.send_text(json.dumps(item, ensure_ascii=False))
                    if item.get("type") == "prompt_generated" and item.get("source") == "e621_event":
                        generated_prompt = str(item.get("prompt") or "")
                        generated_source = "E621"
            if generated_prompt:
                await _enqueue_prompt_from_module(
                    ws,
                    context,
                    clients,
                    prompt=generated_prompt,
                    source=generated_source,
                )
        else:
            generation_commands = []
            if isinstance(module_state, dict):
                raw_commands = module_state.pop("_headless_generation_commands", [])
                if isinstance(raw_commands, list):
                    generation_commands = [item for item in raw_commands if isinstance(item, dict)]
            await ws.send_text(json.dumps(module_state, ensure_ascii=False))
            if generation_commands:
                await _enqueue_headless_generation_commands(ws, context, clients, generation_commands)
    elif command_type == "get_module_state":
        module_id = str(command.get("module_id") or "")
        await ws.send_text(json.dumps(context.module_state_payload(module_id, client_host), ensure_ascii=False))
    elif command_type == "result_upscale":
        await ws.send_text(json.dumps({
            "type": "result_upscale_state",
            "running": False,
            "success": False,
            "message": "NAI 2x upscale is not available in the headless runtime yet.",
            "headless": True,
        }, ensure_ascii=False))
        await ws.send_text(json.dumps({
            "type": "toast",
            "level": "info",
            "message": "Headless command retired: result_upscale",
            "headless": True,
        }, ensure_ascii=False))
    elif command_type == "result_enhance":
        try:
            generation_command, enhance_state = await _to_thread(_prepare_result_enhance_command, context, command)
            result = await _to_thread(_generation_service(context).enqueue_remote_request, generation_command)
        except Exception as exc:
            message = f"Enhance request failed: {exc}"
            await ws.send_text(json.dumps({
                "type": "result_enhance_state",
                "running": False,
                "success": False,
                "message": message,
                "headless": True,
            }, ensure_ascii=False))
            await ws.send_text(json.dumps({
                "type": "toast",
                "level": "error",
                "message": message,
                "headless": True,
            }, ensure_ascii=False))
            return
        await ws.send_text(json.dumps(result.websocket_payload(), ensure_ascii=False))
        if not result.ok:
            await ws.send_text(json.dumps({
                "type": "result_enhance_state",
                "running": False,
                "success": False,
                "message": result.blocked_reason,
                "headless": True,
            }, ensure_ascii=False))
            await ws.send_text(json.dumps({
                "type": "toast",
                "level": "error",
                "message": result.blocked_reason,
                "headless": True,
            }, ensure_ascii=False))
            return
        await ws.send_text(json.dumps(enhance_state, ensure_ascii=False))
        await ws.send_text(json.dumps({
            "type": "status",
            "is_generating": False,
            "message": "queued",
        }, ensure_ascii=False))
        await ws.send_text(json.dumps({
            "type": "toast",
            "level": "success",
            "message": "Enhance queued",
        }, ensure_ascii=False))
        await ws.send_text(json.dumps(context.queue_state_payload(), ensure_ascii=False))
        if context.headless_generation_execute_enabled:
            _ensure_generation_runner(context, clients)
    elif command_type == "set_result_enhance_config":
        config = _normalize_result_enhance_config(context, command)
        context.result_enhance_config = {
            "upscale": config["upscale"],
            "strength": config["strength"],
            "noise": config["noise"],
        }
        await ws.send_text(json.dumps({**config, "_session_echo": True}, ensure_ascii=False))
        await ws.send_text(json.dumps({
            "type": "toast",
            "level": "success",
            "message": "Enhance settings updated",
            "headless": True,
        }, ensure_ascii=False))
    elif command_type == "result_image_action":
        action = str(command.get("action") or "image_action")
        if action not in {"img2img", "inpaint"}:
            await ws.send_text(json.dumps({
                "type": "toast",
                "level": "error",
                "message": "Unsupported result image action",
                "headless": True,
            }, ensure_ascii=False))
            return
        if context.get_api_mode() != "NAI":
            await ws.send_text(json.dumps({
                "type": "toast",
                "level": "error",
                "message": "Img2Img/Inpaint is available in NAI mode only",
                "headless": True,
            }, ensure_ascii=False))
            return
        try:
            image_bytes, label, generation_params, prompt_context = await _to_thread(
                resolve_result_image_action_source,
                context,
                command,
            )
            state = await _to_thread(
                context.open_img2img_session_from_bytes,
                image_bytes,
                label=label,
                mode=action,
                generation_params=generation_params,
                prompt_context=prompt_context,
            )
        except Exception as exc:
            await ws.send_text(json.dumps({
                "type": "toast",
                "level": "error",
                "message": f"Image action failed: {exc}",
                "headless": True,
            }, ensure_ascii=False))
            return
        await ws.send_text(json.dumps(state, ensure_ascii=False))
        await ws.send_text(json.dumps({
            "type": "toast",
            "level": "success",
            "message": f"{'Inpaint' if action == 'inpaint' else 'Img2Img'} session ready",
            "headless": True,
        }, ensure_ascii=False))
    elif command_type == "random":
        await _handle_random_command(ws, context, command)
    elif command_type == "generate":
        await _handle_generate_command(ws, context, clients, command)
    else:
        await ws.send_text(json.dumps({
            "type": "toast",
            "level": "info",
            "message": f"Headless command ignored: {command_type or 'unknown'}",
        }, ensure_ascii=False))


async def _handle_text_command(
    ws: WebSocket,
    context: WebSessionContext,
    clients: set[WebSocket],
    client_host: str,
    data: str,
) -> None:
    if data == "sync":
        await _send_sync_messages(ws, context, client_host)
        return
    if data == "random":
        await _handle_random_command(ws, context)
        return
    if data == "generate":
        await _handle_generate_command(ws, context, clients)
        return
    await ws.send_text(json.dumps({
        "type": "toast",
        "level": "info",
        "message": f"Headless command ignored: {data}",
    }, ensure_ascii=False))


async def _to_thread(func, /, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)


def create_headless_app(
    context: WebSessionContext | None = None,
    *,
    web_dir: Path | str | None = None,
) -> FastAPI:
    """Create the PyQt-free Remote Web FastAPI app."""

    session_context = context or WebSessionContext()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        async def run_warmup() -> None:
            try:
                ok = await _to_thread(_random_service(session_context).warmup)
                session_context.headless_random_warmup_done = bool(ok)
                print(
                    "Headless Remote: random prompt runtime warmup "
                    + ("ready" if ok else "finished without search rows"),
                    flush=True,
                )
            except Exception as exc:
                session_context.headless_random_warmup_error = str(exc)
                print(f"Headless Remote: random prompt runtime warmup failed - {exc}", flush=True)

        async def run_tag_index_warmup() -> None:
            try:
                await _to_thread(_ensure_tag_search_index, session_context)
                print(
                    f"Headless Remote: tag autocomplete index ready ({len(getattr(session_context, 'kr_tags_raw', {}) or {}):,} tags)",
                    flush=True,
                )
            except Exception as exc:
                session_context.headless_tag_index_warmup_error = str(exc)
                print(f"Headless Remote: tag autocomplete index warmup failed - {exc}", flush=True)

        task = getattr(session_context, "headless_random_warmup_task", None)
        if task is None or task.done():
            session_context.headless_random_warmup_task = asyncio.create_task(run_warmup())
        tag_task = getattr(session_context, "headless_tag_index_warmup_task", None)
        if tag_task is None or tag_task.done():
            session_context.headless_tag_index_warmup_task = asyncio.create_task(run_tag_index_warmup())
        yield

    app = FastAPI(title="NAIA Remote Headless", lifespan=lifespan)
    app.state.web_session_context = session_context
    app.state.headless_clients = set()

    root_web_dir = (
        Path(web_dir).resolve()
        if web_dir is not None
        else resolve_remote_web_dir(session_context.repo_root)
    )
    app.state.remote_web_dir = str(root_web_dir)
    register_web_shell_routes(app, root_web_dir)

    register_state_routes(
        app,
        session_context,
        run_in_thread=_to_thread,
        clients=app.state.headless_clients,
        broadcast_json=_broadcast_json,
        start_generation_runner=_ensure_generation_runner,
    )
    register_install_manager_routes(app, session_context, run_in_thread=_to_thread)
    register_params_workflow_routes(
        app,
        session_context,
        run_in_thread=_to_thread,
        clients=app.state.headless_clients,
        broadcast_json=_broadcast_json,
    )
    register_prompt_tools_routes(
        app,
        session_context,
        run_in_thread=_to_thread,
        clients=app.state.headless_clients,
        broadcast_json=_broadcast_json,
        start_generation_runner=_ensure_generation_runner,
    )
    register_style_thumbnail_routes(app, session_context, run_in_thread=_to_thread)
    register_danbooru_routes(app, session_context, run_in_thread=_to_thread)
    register_event_preset_routes(
        app,
        session_context,
        run_in_thread=_to_thread,
        clients=app.state.headless_clients,
        broadcast_json=_broadcast_json,
        start_generation_runner=_ensure_generation_runner,
    )
    register_artist_thumbnail_routes(
        app,
        session_context,
        run_in_thread=_to_thread,
        clients=app.state.headless_clients,
        start_generation_runner=_ensure_generation_runner,
    )
    register_character_viewer_routes(
        app,
        session_context,
        run_in_thread=_to_thread,
        clients=app.state.headless_clients,
        start_generation_runner=_ensure_generation_runner,
    )
    register_result_display_routes(
        app,
        session_context,
        run_in_thread=_to_thread,
        clients=app.state.headless_clients,
        broadcast_json=_broadcast_json,
    )

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await ws.accept()
        clients: set[WebSocket] = app.state.headless_clients
        clients.add(ws)
        session_id = uuid.uuid4().hex[:8]
        client_host = _client_host(ws)
        try:
            await _send_startup_messages(
                ws,
                session_context,
                session_id=session_id,
                client_host=client_host,
            )
            while True:
                data = await ws.receive_text()
                if data.startswith("{"):
                    try:
                        command = json.loads(data)
                    except json.JSONDecodeError:
                        command = {"type": ""}
                    if isinstance(command, dict):
                        await _handle_json_command(ws, session_context, clients, client_host, command)
                    else:
                        await _handle_text_command(ws, session_context, clients, client_host, data)
                else:
                    await _handle_text_command(ws, session_context, clients, client_host, data)
        except WebSocketDisconnect:
            clients.discard(ws)
            return
        finally:
            clients.discard(ws)

    return app


__all__ = ["create_headless_app"]
