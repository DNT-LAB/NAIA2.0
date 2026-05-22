from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.web_session_context import WebSessionContext


REMOTE_RESOLUTION_MODES = ("NAI", "WEBUI", "COMFYUI")
AsyncRunner = Callable[..., Awaitable[Any]]
JsonBroadcaster = Callable[[set[Any], dict[str, Any]], Awaitable[None]]


def _normalize_remote_mode(context: WebSessionContext, mode: str | None = None) -> str:
    normalized = str(mode or context.get_api_mode() or "NAI").strip().upper()
    return normalized if normalized in REMOTE_RESOLUTION_MODES else "NAI"


def _default_resolutions_for_mode(mode: str) -> list[str]:
    from core.resolution_utils import ANIMA_RESOLUTION_LABELS, STANDARD_1MP_RESOLUTION_LABELS

    return list(ANIMA_RESOLUTION_LABELS if mode == "COMFYUI" else STANDARD_1MP_RESOLUTION_LABELS)


def _resolution_store_path(context: WebSessionContext) -> Path:
    return context._save_path("resolutions.json")


def _normalize_resolution_list_for_storage(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    normalized: list[str] = []
    seen = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def _load_resolutions_by_mode(context: WebSessionContext) -> dict[str, list[str]]:
    mode_map = {mode: _default_resolutions_for_mode(mode) for mode in REMOTE_RESOLUTION_MODES}
    path = context._existing_save_path("resolutions.json")
    if not path.exists():
        return mode_map
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return mode_map

    legacy_items: list[str] = []
    if isinstance(loaded, list):
        legacy_items = _normalize_resolution_list_for_storage(loaded)
    elif isinstance(loaded, dict):
        legacy_items = _normalize_resolution_list_for_storage(loaded.get("resolutions"))
    if legacy_items:
        for mode in REMOTE_RESOLUTION_MODES:
            mode_map[mode] = list(legacy_items)

    if isinstance(loaded, dict):
        for mode in REMOTE_RESOLUTION_MODES:
            items = _normalize_resolution_list_for_storage(loaded.get(mode))
            if items:
                mode_map[mode] = items
    return mode_map


def _write_resolutions_by_mode(context: WebSessionContext, mode_map: dict[str, list[str]]) -> None:
    path = _resolution_store_path(context)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(mode_map, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_resolution_pair(value: Any) -> tuple[int, int] | None:
    match = re.search(r"(\d+)\s*x\s*(\d+)", str(value or ""), flags=re.IGNORECASE)
    if not match:
        return None
    width = int(match.group(1))
    height = int(match.group(2))
    if width <= 0 or height <= 0:
        return None
    return width, height


def _resolution_multiple_for_mode(mode: str) -> int:
    return 64 if mode == "NAI" else 8


def _normalize_resolution_items_for_save(raw_items: Any, mode: str) -> list[str]:
    if not isinstance(raw_items, list):
        raise ValueError("resolutions must be a list")
    multiple = _resolution_multiple_for_mode(mode)
    normalized: list[str] = []
    seen = set()
    for item in raw_items:
        pair = _parse_resolution_pair(item)
        if not pair:
            raise ValueError(f"invalid resolution: {item}")
        width, height = pair
        if width > 8192 or height > 8192:
            raise ValueError("width and height must be 8192 or less")
        if width % multiple != 0 or height % multiple != 0:
            raise ValueError(f"width and height must be multiples of {multiple}")
        label = f"{width} x {height}"
        if label in seen:
            continue
        seen.add(label)
        normalized.append(label)
    if not normalized:
        raise ValueError("resolution list cannot be empty")
    return normalized


def _resolution_manager_state(context: WebSessionContext, mode: str | None = None) -> dict[str, Any]:
    normalized_mode = _normalize_remote_mode(context, mode)
    resolutions = list(_load_resolutions_by_mode(context).get(normalized_mode) or _default_resolutions_for_mode(normalized_mode))
    current = str(context.remote_params.get("resolution") or "").strip()
    if current not in resolutions:
        current = resolutions[0] if resolutions else ""
    return {
        "ok": True,
        "api_mode": normalized_mode,
        "multiple": _resolution_multiple_for_mode(normalized_mode),
        "max_value": 8192,
        "warning_pixel_area": 1024 * 1024,
        "defaults": _default_resolutions_for_mode(normalized_mode),
        "resolutions": resolutions,
        "current_resolution": current,
    }


def _save_resolution_manager_state(context: WebSessionContext, mode: str, raw_items: Any) -> dict[str, Any]:
    normalized_mode = _normalize_remote_mode(context, mode)
    cleaned = _normalize_resolution_items_for_save(raw_items, normalized_mode)
    mode_map = _load_resolutions_by_mode(context)
    mode_map[normalized_mode] = cleaned
    _write_resolutions_by_mode(context, mode_map)
    if normalized_mode == context.get_api_mode():
        context.remote_params["options_resolution"] = list(cleaned)
        if str(context.remote_params.get("resolution") or "") not in cleaned:
            context.remote_params["resolution"] = cleaned[0]
        context.publish("remote_params_changed", context.generation_param_schema_payload())
    return _resolution_manager_state(context, normalized_mode)


def register_params_workflow_routes(
    app: FastAPI,
    session_context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
    clients: set[Any],
    broadcast_json: JsonBroadcaster,
) -> None:
    @app.get("/api/resolutions")
    async def api_resolutions(mode: str = "", api_mode: str = ""):
        return _resolution_manager_state(session_context, mode or api_mode)

    @app.post("/api/resolutions")
    async def api_save_resolutions(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            result = await run_in_thread(
                _save_resolution_manager_state,
                session_context,
                payload.get("api_mode") or payload.get("mode"),
                payload.get("resolutions"),
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        await broadcast_json(clients, session_context.generation_param_schema_payload())
        return result
