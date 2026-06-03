from __future__ import annotations

import io
import json
import re
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.backend.server.search_runtime import save_runner_parquet
from core.web_session_context import WebSessionContext


REMOTE_RESOLUTION_MODES = ("NAI", "WEBUI", "COMFYUI")
AsyncRunner = Callable[..., Awaitable[Any]]
JsonBroadcaster = Callable[[set[Any], dict[str, Any]], Awaitable[None]]


def _normalize_remote_mode(context: WebSessionContext, mode: str | None = None) -> str:
    normalized = str(mode or context.get_api_mode() or "NAI").strip().upper()
    return normalized if normalized in REMOTE_RESOLUTION_MODES else "NAI"


def _default_resolutions_for_mode(mode: str) -> list[str]:
    # COMFYUI/ANIMA defaults to the 1MP band (1024x1024 .. 832x1216 .. 1216x832), same as
    # NAI/WEBUI. The full ANIMA range (512..1792) is opt-in via the Res Preset bands
    # (draft/compact/standard/hd/.../max) or by adding entries in Manage Resolution, so a
    # fresh COMFYUI session no longer lists every 512..1536 resolution by default.
    from core.resolution_utils import STANDARD_1MP_RESOLUTION_LABELS

    return list(STANDARD_1MP_RESOLUTION_LABELS)


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


def _comfyui_workflow_state_payload(context: WebSessionContext) -> dict[str, Any]:
    has_custom = bool(context.remote_params.get("comfyui_workflow_has_custom", False))
    workflow_type = context.remote_params.get("comfyui_workflow_type")
    workflow_type_text = str(workflow_type or "").strip().lower()
    is_bypass = workflow_type_text in {"bypass", "free"}
    workflow_label = str(
        context.remote_params.get("comfyui_workflow_label")
        or ("Bypass Workflow" if is_bypass else ("Custom Workflow" if has_custom else "Basic Workflow"))
    )
    return {
        "type": "comfyui_workflow_state",
        "has_custom": has_custom,
        "workflow_label": workflow_label,
        "workflow_type": "bypass" if is_bypass else workflow_type,
        "model_compat": context.remote_params.get("comfyui_workflow_model_compat"),
        "locked_loader_class": context.remote_params.get("comfyui_workflow_locked_loader_class"),
        "locked_model_display": context.remote_params.get("comfyui_workflow_locked_model_display"),
    }


def _extract_comfyui_workflow_metadata_from_image(image_bytes: bytes) -> dict[str, Any]:
    from utils.comfyui_png_metadata import extract_comfyui_workflow_metadata_from_upload_bytes

    if not image_bytes:
        raise ValueError("Workflow upload payload is empty")
    if len(image_bytes) > 64 * 1024 * 1024:
        raise ValueError("Workflow upload is too large")
    info = extract_comfyui_workflow_metadata_from_upload_bytes(image_bytes)
    workflow_text = info.get("workflow") or info.get("workflow_api")
    prompt_text = info.get("prompt") or info.get("workflow_api")
    if not workflow_text or not prompt_text:
        raise ValueError("Image does not include ComfyUI workflow metadata")
    try:
        workflow = json.loads(workflow_text) if isinstance(workflow_text, str) else workflow_text
        prompt_api = json.loads(prompt_text) if isinstance(prompt_text, str) else prompt_text
    except Exception as exc:
        raise ValueError(f"ComfyUI workflow metadata is invalid: {exc}") from exc
    if not isinstance(workflow, dict) or not isinstance(prompt_api, dict):
        raise ValueError("ComfyUI workflow metadata is invalid")
    return {
        "workflow": prompt_api if "nodes" in workflow else workflow,
        "workflow_ui": workflow if "nodes" in workflow else None,
        "metadata": info,
    }


def _apply_comfyui_workflow_metadata(
    context: WebSessionContext,
    metadata: dict[str, Any] | None,
    *,
    workflow_mode: str = "custom",
) -> dict[str, Any]:
    from core.comfyui_workflow_manager import ComfyUIWorkflowManager

    metadata = metadata or {}
    raw_metadata = metadata.get("metadata")
    if not isinstance(raw_metadata, dict):
        raise ValueError("ComfyUI workflow metadata is invalid")

    manager = ComfyUIWorkflowManager()
    analysis = manager.analyze_workflow_for_ui(raw_metadata, workflow_mode=workflow_mode)
    if not analysis.get("success"):
        raise ValueError(str(analysis.get("error_message") or "ComfyUI workflow validation failed"))
    if not manager.load_workflow_from_metadata(raw_metadata, workflow_mode=workflow_mode):
        raise ValueError("ComfyUI workflow could not be loaded")

    node_map = manager.user_workflow_node_map or {}
    workflow = manager.user_workflow
    if not isinstance(workflow, dict):
        raise ValueError("ComfyUI workflow metadata is invalid")
    workflow_type = node_map.get("workflow_type")
    is_bypass = str(workflow_type or "").strip().lower() in {"bypass", "free"}
    context.remote_params["comfyui_workflow"] = workflow
    context.remote_params["_comfyui_workflow_ui"] = manager.user_workflow_ui
    context.remote_params["comfyui_workflow_has_custom"] = True
    context.remote_params["comfyui_workflow_label"] = "Bypass Workflow" if is_bypass else "Custom Workflow"
    context.remote_params["comfyui_workflow_type"] = "bypass" if is_bypass else workflow_type
    context.remote_params["comfyui_workflow_model_compat"] = node_map.get("model_compat")
    context.remote_params["comfyui_workflow_node_map"] = dict(node_map)
    context.remote_params["comfyui_workflow_locked_loader_class"] = node_map.get("locked_loader_class")
    context.remote_params["comfyui_workflow_locked_model_display"] = node_map.get("locked_model_display")
    context.publish("comfyui_workflow_changed", _comfyui_workflow_state_payload(context))
    return {
        "ok": True,
        "workflow": _comfyui_workflow_state_payload(context),
        "params": context.generation_param_schema_payload(),
    }


def _clear_comfyui_workflow(context: WebSessionContext) -> dict[str, Any]:
    for key in (
        "comfyui_workflow",
        "_comfyui_workflow_ui",
        "comfyui_workflow_has_custom",
        "comfyui_workflow_label",
        "comfyui_workflow_type",
        "comfyui_workflow_model_compat",
        "comfyui_workflow_node_map",
        "comfyui_workflow_locked_loader_class",
        "comfyui_workflow_locked_model_display",
    ):
        context.remote_params.pop(key, None)
    context.publish("comfyui_workflow_changed", _comfyui_workflow_state_payload(context))
    return {
        "ok": True,
        "workflow": _comfyui_workflow_state_payload(context),
        "params": context.generation_param_schema_payload(),
    }


def _apply_uploaded_search_parquet(context: WebSessionContext, content: bytes, action: str, filename: str) -> dict[str, Any]:
    if action not in {"load", "merge"}:
        raise ValueError("action must be load or merge")
    safe_filename = Path(str(filename or "uploaded.parquet")).name
    if not safe_filename.lower().endswith(".parquet"):
        raise ValueError("Only .parquet files are supported")
    if not content:
        raise ValueError("Uploaded parquet is empty")

    import pandas as pd

    frame = pd.read_parquet(io.BytesIO(content))
    if action == "load":
        context.search_results.set_dataframe(frame)
    else:
        context.search_results.append_dataframe(frame)
    context.search_results_snapshot = context.search_results.get_dataframe().copy()
    context.search_results_master_base_snapshot = context.search_results_snapshot.copy()
    context.search_results_scope = "custom_parquet"
    save_runner_parquet(context)
    return {
        "ok": True,
        "action": action,
        "filename": safe_filename,
        "rows": int(len(frame)),
        "total": int(context.search_results.get_count()),
    }


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

    @app.post("/api/search/parquet/upload")
    async def api_search_parquet_upload(req: Request):
        action = str(req.query_params.get("action") or "").strip().lower()
        filename = str(req.query_params.get("filename") or "uploaded.parquet")
        content = await req.body()
        try:
            result = await run_in_thread(_apply_uploaded_search_parquet, session_context, content, action, filename)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"Parquet upload failed: {exc}"}, status_code=400)
        await broadcast_json(clients, session_context.search_state_payload())
        return result

    @app.get("/api/comfyui/workflow/state")
    async def api_comfyui_workflow_state():
        return _comfyui_workflow_state_payload(session_context)

    @app.get("/api/comfyui/web")
    async def api_comfyui_web():
        url = str(session_context.secure_token_manager.get_token("comfyui_url") or "").strip()
        if not url:
            return JSONResponse({"ok": False, "error": "ComfyUI URL is not configured"}, status_code=404)
        if not url.startswith(("http://", "https://")):
            url = f"http://{url}"
        return RedirectResponse(url)

    @app.post("/api/comfyui/workflow/upload")
    async def api_comfyui_workflow_upload(req: Request):
        image_bytes = await req.body()
        try:
            metadata = await run_in_thread(_extract_comfyui_workflow_metadata_from_image, image_bytes)
            result = await run_in_thread(_apply_comfyui_workflow_metadata, session_context, metadata, workflow_mode="custom")
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        await broadcast_json(clients, result["workflow"])
        await broadcast_json(clients, result["params"])
        return result

    @app.post("/api/comfyui/workflow/bypass/upload")
    async def api_comfyui_workflow_bypass_upload(req: Request):
        image_bytes = await req.body()
        try:
            metadata = await run_in_thread(_extract_comfyui_workflow_metadata_from_image, image_bytes)
            result = await run_in_thread(_apply_comfyui_workflow_metadata, session_context, metadata, workflow_mode="bypass")
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        await broadcast_json(clients, result["workflow"])
        await broadcast_json(clients, result["params"])
        return result

    @app.post("/api/comfyui/workflow/free/upload")
    async def api_comfyui_workflow_free_upload(req: Request):
        return await api_comfyui_workflow_bypass_upload(req)

    @app.post("/api/comfyui/workflow/default")
    async def api_comfyui_workflow_default():
        result = await run_in_thread(_clear_comfyui_workflow, session_context)
        await broadcast_json(clients, result["workflow"])
        await broadcast_json(clients, result["params"])
        return result
