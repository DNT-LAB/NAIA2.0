"""PyQt-free FastAPI app for the headless Remote Web Session path."""

from __future__ import annotations

from contextlib import asynccontextmanager
import json
import asyncio
import io
import mimetypes
import time
import re
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlparse

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from core import result_image_payload_service as result_images
from core.artist_thumbnail_service import ArtistThumbnailService
from core.character_viewer_service import CharacterViewerService
from core.clothes_preset_service import ClothesPresetService
from core.danbooru_client import DANBOORU_BASE_URL, fetch_danbooru_post
from core.event_preset_download_service import EventPresetDownloadService
from core.event_preset_service import EventPresetService
from core.expression_preset_service import ExpressionPresetService
from core.headless_generation_service import HeadlessGenerationService
from core.headless_random_prompt_service import HeadlessRandomPromptService
from core.preset_composer_service import PresetComposerService
from core.style_thumbnail_service import StyleThumbnailService
from core.web_session_context import WebSessionContext


IMAGE_VIEWER_EXTENSIONS = {".png", ".webp", ".jpg", ".jpeg"}
REMOTE_RESOLUTION_MODES = ("NAI", "WEBUI", "COMFYUI")
PROMPT_ENGINEERING_PRESET_MODES = ("NAI", "WEBUI", "COMFYUI")


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


def _web_file(path: Path, media_type: str):
    if not path.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(str(path), media_type=media_type, headers=_no_cache_headers())


def _prompt_highlight_empty_index() -> dict[str, Any]:
    return {
        "version": "headless-empty",
        "groups": {},
        "tags": {},
        "stats": {
            "source": "headless",
            "total": 0,
        },
    }


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


def _style_thumbnail_service(context: WebSessionContext) -> StyleThumbnailService:
    service = getattr(context, "style_thumbnail_service", None)
    if service is None:
        service = StyleThumbnailService(context.repo_root)
        context.style_thumbnail_service = service
    return service


def _character_viewer_service(context: WebSessionContext) -> CharacterViewerService:
    service = getattr(context, "character_viewer_service", None)
    if service is None:
        service = CharacterViewerService(context.repo_root)
        context.character_viewer_service = service
    return service


def _artist_thumbnail_service(context: WebSessionContext) -> ArtistThumbnailService:
    service = getattr(context, "artist_thumbnail_service", None)
    if service is None:
        service = ArtistThumbnailService(context.repo_root, mode_getter=context.get_api_mode)
        context.artist_thumbnail_service = service
    return service


def _event_preset_service(context: WebSessionContext) -> EventPresetService:
    service = getattr(context, "event_preset_service", None)
    if service is None:
        service = EventPresetService(context.repo_root)
        context.event_preset_service = service
    return service


def _clothes_preset_service(context: WebSessionContext) -> ClothesPresetService:
    service = getattr(context, "clothes_preset_service", None)
    if service is None:
        service = ClothesPresetService(context.repo_root)
        context.clothes_preset_service = service
    return service


def _expression_preset_service(context: WebSessionContext) -> ExpressionPresetService:
    service = getattr(context, "expression_preset_service", None)
    if service is None:
        service = ExpressionPresetService(context.repo_root)
        context.expression_preset_service = service
    return service


def _preset_composer_service(context: WebSessionContext) -> PresetComposerService:
    service = getattr(context, "preset_composer_service", None)
    if service is None:
        service = PresetComposerService(
            _event_preset_service(context),
            axis_providers={"clothes": _clothes_preset_service(context)},
        )
        context.preset_composer_service = service
    return service


def _event_preset_download_service(context: WebSessionContext) -> EventPresetDownloadService:
    service = getattr(context, "event_preset_download_service", None)
    if service is None:
        def refresh_services() -> None:
            context.event_preset_service = EventPresetService(context.repo_root)
            context.preset_composer_service = PresetComposerService(
                context.event_preset_service,
                axis_providers={"clothes": _clothes_preset_service(context)},
            )

        service = EventPresetDownloadService(
            context.repo_root,
            status_provider=lambda: _event_preset_service(context).status(),
            on_complete=refresh_services,
        )
        context.event_preset_download_service = service
    return service


def _event_preset_status(context: WebSessionContext) -> dict[str, Any]:
    status = _event_preset_service(context).status()
    status["download"] = _event_preset_download_service(context).snapshot()
    return status


def _normalize_remote_mode(context: WebSessionContext, mode: str | None = None) -> str:
    normalized = str(mode or context.get_api_mode() or "NAI").strip().upper()
    return normalized if normalized in REMOTE_RESOLUTION_MODES else "NAI"


def _default_resolutions_for_mode(mode: str) -> list[str]:
    from core.resolution_utils import ANIMA_RESOLUTION_LABELS, STANDARD_1MP_RESOLUTION_LABELS

    return list(ANIMA_RESOLUTION_LABELS if mode == "COMFYUI" else STANDARD_1MP_RESOLUTION_LABELS)


def _resolution_store_path(context: WebSessionContext) -> Path:
    return Path(context.repo_root) / "save" / "resolutions.json"


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
    path = _resolution_store_path(context)
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
    return {
        "ok": True,
        "action": action,
        "filename": safe_filename,
        "rows": int(len(frame)),
        "total": int(context.search_results.get_count()),
    }


def _viewer_save_dir(context: WebSessionContext) -> Path:
    return context._current_save_directory()


def _history_item_from_viewer_path(context: WebSessionContext, rel_path: str):
    normalized = str(rel_path or "").replace("\\", "/").strip("/")
    prefix = "__history_item__/"
    if not normalized.startswith(prefix):
        return None
    history_id = normalized[len(prefix):].split("/", 1)[0]
    return context.result_store.get_item(history_id)


def _validate_viewer_path(context: WebSessionContext, rel_path: str) -> Path | None:
    if _history_item_from_viewer_path(context, rel_path):
        return None
    save_dir = _viewer_save_dir(context).resolve()
    target = (save_dir / str(rel_path or "")).resolve()
    try:
        target.relative_to(save_dir)
    except ValueError:
        return None
    if target.is_file() and target.suffix.lower() in IMAGE_VIEWER_EXTENSIONS:
        return target
    return None


def _image_media_type_for_path(image_path: str | Path) -> str:
    return result_images.image_media_type_for_path(image_path)


def _scan_viewer_folder(context: WebSessionContext) -> list[dict[str, Any]]:
    save_dir = _viewer_save_dir(context)
    if not save_dir.exists():
        return []
    entries: list[dict[str, Any]] = []
    for path in save_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in IMAGE_VIEWER_EXTENSIONS:
            continue
        try:
            stat = path.stat()
            rel_path = path.relative_to(save_dir).as_posix()
        except Exception:
            continue
        entries.append({
            "rel_path": rel_path,
            "filename": path.name,
            "size_bytes": stat.st_size,
            "mtime": stat.st_mtime,
            "mtime_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(stat.st_mtime)),
        })
    entries.sort(key=lambda item: item["mtime"], reverse=True)
    return entries


def _build_current_result_asset_payload(context: WebSessionContext) -> dict[str, Any]:
    item = context.result_store.latest_item
    metadata_payload = context.result_store.latest_metadata_payload if isinstance(context.result_store.latest_metadata_payload, dict) else {}
    raw = metadata_payload.get("raw", {}) if isinstance(metadata_payload, dict) else {}
    raw = raw if isinstance(raw, dict) else {}
    summary = metadata_payload.get("summary", {}) if isinstance(metadata_payload, dict) else {}
    summary = summary if isinstance(summary, dict) else {}
    generation_params = getattr(item, "generation_params", None) or raw.get("generation_params", {})
    prompt_context = getattr(item, "prompt_context", None) or raw.get("prompt_context", {})
    source_row = getattr(item, "source_row", None) if item else None
    filepath = str(getattr(item, "filepath", "") or "") if item else ""
    has_file = bool(filepath and Path(filepath).is_file())
    rel_path = getattr(item, "rel_path", "") if item else ""
    mode = str(context.get_api_mode() or "").upper()
    nai_mode = mode == "NAI"
    webui_mode = mode == "WEBUI"
    has_image = bool(item or context.result_store.latest_webp)
    has_generation_params = bool(generation_params)
    has_source_row = source_row is not None
    has_prompt = bool(
        (isinstance(prompt_context, dict) and (prompt_context.get("main_prompt") or prompt_context.get("final_prompt")))
        or (isinstance(generation_params, dict) and generation_params.get("input"))
        or summary.get("prompt")
    )
    can_enhance = bool(item and has_generation_params and (nai_mode or webui_mode))
    return {
        "id": "current",
        "source": "current",
        "path": rel_path,
        "file_path": filepath if has_file else "",
        "label": Path(filepath).name if filepath else (getattr(item, "filename", "Current Result") if item else "Current Result"),
        "image_url": f"/api/history/image/{item.history_id}" if item else ("/api/latest-image" if has_image else ""),
        "metadata_url": f"/api/history/meta/{item.history_id}" if item else "/api/result/metadata",
        "has_image": has_image,
        "has_metadata": bool(metadata_payload or rel_path),
        "can_enhance": can_enhance,
        "capabilities": {
            "load_prompt": bool(has_prompt),
            "reroll": bool(has_source_row),
            "queue": has_generation_params,
            "restore_params": has_generation_params,
            "metadata": bool(metadata_payload or rel_path),
            "paste_image": True,
            "open_file": has_file,
            "save_image": has_image,
            "copy_png": has_image,
            "image_action": bool(has_image and nai_mode),
            "upscale_nai": bool(has_image and nai_mode),
            "enhance": can_enhance,
            "inpaint": bool(has_image and nai_mode),
            "character_reference": bool(item),
            "remote_event": bool(has_source_row),
            "delete": False,
        },
    }


def _build_saved_result_asset_payload(context: WebSessionContext, rel_path: str) -> dict[str, Any] | None:
    item = _history_item_from_viewer_path(context, rel_path)
    target = _validate_viewer_path(context, rel_path)
    if not item and target is None:
        return None
    normalized_path = str(rel_path or "").replace("\\", "/")
    if target is not None:
        try:
            normalized_path = target.relative_to(_viewer_save_dir(context).resolve()).as_posix()
        except Exception:
            pass
    stat = None
    if target is not None:
        try:
            stat = target.stat()
        except Exception:
            stat = None
    mode = str(context.get_api_mode() or "").upper()
    nai_mode = mode == "NAI"
    webui_mode = mode == "WEBUI"
    has_generation_params = bool(getattr(item, "generation_params", None)) if item else False
    has_source_row = getattr(item, "source_row", None) is not None if item else False
    can_enhance = bool(item and has_generation_params and (nai_mode or webui_mode))
    image_url = f"/api/history/image/{item.history_id}" if item else f"/api/viewer/image/{quote(normalized_path)}"
    metadata_url = f"/api/history/meta/{item.history_id}" if item else f"/api/viewer/meta?path={quote(normalized_path, safe='')}"
    return {
        "id": f"saved:{normalized_path}",
        "source": "saved",
        "path": normalized_path,
        "file_path": str(target) if target is not None else "",
        "label": target.name if target is not None else getattr(item, "filename", "History Image"),
        "image_url": image_url,
        "metadata_url": metadata_url,
        "has_image": True,
        "has_metadata": True,
        "can_enhance": can_enhance,
        "size_bytes": stat.st_size if stat else None,
        "mtime": stat.st_mtime if stat else None,
        "capabilities": {
            "load_prompt": True,
            "reroll": has_source_row,
            "queue": has_generation_params,
            "restore_params": True,
            "metadata": True,
            "paste_image": True,
            "open_file": bool(target),
            "save_image": True,
            "copy_png": True,
            "image_action": bool(item and nai_mode),
            "upscale_nai": nai_mode,
            "enhance": can_enhance,
            "inpaint": False,
            "character_reference": False,
            "remote_event": False,
            "delete": False,
        },
    }


def _build_input_metadata_payload(image, image_bytes: bytes, label: str, mime_type: str = "") -> dict[str, Any]:
    info = dict(getattr(image, "info", {}) or {})
    parsed_info: dict[str, Any] = {}
    for key, value in info.items():
        if isinstance(value, bytes):
            try:
                value = value.decode("utf-8", errors="replace")
            except Exception:
                value = str(value)
        if isinstance(value, str) and value.strip().startswith(("{", "[")):
            try:
                parsed_info[key] = json.loads(value)
                continue
            except Exception:
                pass
        if isinstance(value, (str, int, float, bool)) or value is None:
            parsed_info[key] = value
        else:
            parsed_info[key] = str(value)

    raw_params = parsed_info.get("naia_generation_params") if isinstance(parsed_info.get("naia_generation_params"), dict) else {}
    prompt_context = parsed_info.get("naia_prompt_context") if isinstance(parsed_info.get("naia_prompt_context"), dict) else {}
    prompt = ""
    negative = ""
    if isinstance(prompt_context, dict):
        prompt = str(prompt_context.get("main_prompt") or prompt_context.get("final_prompt") or "")
    if isinstance(raw_params, dict):
        prompt = prompt or str(raw_params.get("input") or raw_params.get("prompt") or "")
        negative = str(raw_params.get("negative_prompt") or raw_params.get("uc") or "")
    if not prompt:
        prompt = str(parsed_info.get("prompt") or "")
    if not negative:
        negative = str(parsed_info.get("negative") or parsed_info.get("uc") or "")

    summary = {
        "width": image.width,
        "height": image.height,
        "mode": image.mode,
        "mime_type": mime_type,
    }
    if prompt:
        summary["prompt"] = prompt
    if negative:
        summary["negative"] = negative
    for key in ("seed", "steps", "sampler", "cfg_scale", "scale", "model"):
        if isinstance(raw_params, dict) and raw_params.get(key) not in ("", None):
            summary[key] = raw_params.get(key)
        elif parsed_info.get(key) not in ("", None):
            summary[key] = parsed_info.get(key)

    return {
        "source": "input",
        "label": label,
        "summary": summary,
        "raw": {
            "image": {
                "width": image.width,
                "height": image.height,
                "mode": image.mode,
                "format": image.format,
                "size_kb": len(image_bytes) // 1024,
                "mime_type": mime_type,
            },
            "metadata": parsed_info,
        },
        "has_metadata": bool(parsed_info),
    }


def _metadata_for_disk_image(path: Path, label: str = "", include_full: bool = False) -> dict[str, Any]:
    from PIL import Image

    raw_bytes = path.read_bytes()
    with Image.open(io.BytesIO(raw_bytes)) as image:
        image.load()
        payload = _build_input_metadata_payload(
            image,
            raw_bytes,
            label or path.name,
            _image_media_type_for_path(path),
        )
    payload["source"] = "saved"
    if not include_full:
        return payload.get("summary", {})
    return payload


def _prompt_engineering_preview_candidates(context: WebSessionContext, preset_name: str, mode: str = "") -> list[Path]:
    safe_name = Path(str(preset_name or "").strip()).name
    if not safe_name or safe_name == "*randomized":
        return []
    mode_key = _normalize_prompt_engineering_preset_mode(context, mode, allow_empty=True)
    preview_dir = Path(context.repo_root) / "save" / "presets" / "previews"
    candidates = [preview_dir / f"{safe_name}{ext}" for ext in (".png", ".webp", ".jpg", ".jpeg")]
    try:
        favorites_path = Path(context.repo_root) / "save" / "presets" / "favorites.json"
        favorite_items = json.loads(favorites_path.read_text(encoding="utf-8")) if favorites_path.exists() else []
        if any(
            isinstance(item, dict)
            and item.get("name") == safe_name
            and (not mode_key or item.get("mode") == mode_key)
            for item in favorite_items
        ):
            favorite_dir = Path(context.repo_root) / "save" / "presets" / "favorites"
            candidates.extend(favorite_dir / f"{safe_name}{ext}" for ext in (".png", ".webp", ".jpg", ".jpeg"))
    except Exception:
        pass
    return candidates


def _prompt_engineering_preview_path(context: WebSessionContext, preset_name: str, mode: str = "") -> Path | None:
    for candidate in _prompt_engineering_preview_candidates(context, preset_name, mode):
        try:
            target = candidate.resolve()
        except Exception:
            continue
        if target.is_file():
            return target
    return None


def _normalize_prompt_engineering_preset_mode(
    context: WebSessionContext,
    mode: str = "",
    *,
    allow_empty: bool = False,
) -> str:
    value = str(mode or "").strip().upper()
    if not value:
        if allow_empty:
            return ""
        current_mode = str(context.get_api_mode() or "").strip().upper()
        return current_mode if current_mode in PROMPT_ENGINEERING_PRESET_MODES else "NAI"
    if value not in PROMPT_ENGINEERING_PRESET_MODES:
        raise ValueError("Invalid preset mode")
    return value


def _prompt_engineering_thumbnail_target(context: WebSessionContext, preset_name: str) -> Path:
    safe_name = Path(str(preset_name or "").strip()).name
    if not safe_name or safe_name == "*randomized":
        raise ValueError("Preset name is required")
    target_dir = Path(context.repo_root) / "save" / "presets" / "previews"
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / f"{safe_name}.png"


def _prompt_engineering_thumbnail_update_payload(context: WebSessionContext, preset_name: str, mode: str = "") -> dict[str, Any]:
    safe_name = Path(str(preset_name or "").strip()).name
    mode_key = _normalize_prompt_engineering_preset_mode(context, mode, allow_empty=True)
    target = _prompt_engineering_preview_path(context, safe_name, mode_key)
    if not target:
        target = _prompt_engineering_thumbnail_target(context, safe_name)
    version = int(target.stat().st_mtime) if target.exists() else int(time.time())
    return {
        "ok": True,
        "name": safe_name,
        "mode": mode_key,
        "has_thumbnail": target.exists(),
        "thumbnail_url": (
            f"/api/prompt-engineering/preset-thumbnail"
            f"?name={quote(safe_name, safe='')}&mode={quote(mode_key, safe='')}&v={version}"
        ),
    }


def _save_prompt_engineering_thumbnail_bytes(
    context: WebSessionContext,
    preset_name: str,
    mode: str,
    image_bytes: bytes,
) -> dict[str, Any]:
    if not image_bytes:
        raise ValueError("Image payload is empty")
    if len(image_bytes) > 24 * 1024 * 1024:
        raise ValueError("Image is too large")
    from PIL import Image

    mode_key = _normalize_prompt_engineering_preset_mode(context, mode, allow_empty=True)
    target = _prompt_engineering_thumbnail_target(context, preset_name)
    with Image.open(io.BytesIO(image_bytes)) as opened:
        opened.load()
        opened.convert("RGBA").save(target, format="PNG")
    return _prompt_engineering_thumbnail_update_payload(context, preset_name, mode_key)


def _prompt_engineering_preset_file(context: WebSessionContext, preset_name: str, mode: str = "") -> Path | None:
    safe_name = Path(str(preset_name or "").strip()).name
    if not safe_name:
        return None
    mode_candidates: list[str] = []
    if mode:
        mode_candidates.append(_normalize_prompt_engineering_preset_mode(context, mode))
    current_mode = _normalize_prompt_engineering_preset_mode(context, context.get_api_mode(), allow_empty=True)
    if current_mode and current_mode not in mode_candidates:
        mode_candidates.append(current_mode)
    for fallback_mode in PROMPT_ENGINEERING_PRESET_MODES:
        if fallback_mode not in mode_candidates:
            mode_candidates.append(fallback_mode)
    for mode_name in mode_candidates:
        candidate = Path(context.repo_root) / "save" / "presets" / mode_name / f"{safe_name}.json"
        if candidate.exists():
            return candidate
    return None


def _prompt_engineering_thumbnail_generation_prompt(context: WebSessionContext, preset_name: str, mode: str = "") -> str:
    pieces: list[str] = []
    preset_file = _prompt_engineering_preset_file(context, preset_name, mode)
    if preset_file:
        try:
            data = json.loads(preset_file.read_text(encoding="utf-8"))
            settings = data.get("module_settings", {}) if isinstance(data, dict) else {}
            pre_prompt = str(settings.get("pre_prompt", "") or "").strip()
            if pre_prompt:
                pieces.append(pre_prompt)
        except Exception:
            pass
    pieces.append("1girl, original, solo, upper body")
    return ", ".join(piece for piece in pieces if piece)


def _comfyui_workflow_state_payload(context: WebSessionContext) -> dict[str, Any]:
    has_custom = bool(context.remote_params.get("comfyui_workflow_has_custom", False))
    return {
        "type": "comfyui_workflow_state",
        "has_custom": has_custom,
        "workflow_label": str(context.remote_params.get("comfyui_workflow_label") or ("Custom Workflow" if has_custom else "Basic Workflow")),
        "model_compat": context.remote_params.get("comfyui_workflow_model_compat"),
        "locked_loader_class": context.remote_params.get("comfyui_workflow_locked_loader_class"),
        "locked_model_display": context.remote_params.get("comfyui_workflow_locked_model_display"),
    }


def _extract_comfyui_workflow_metadata_from_png(image_bytes: bytes) -> dict[str, Any]:
    from PIL import Image

    if not image_bytes:
        raise ValueError("Image payload is empty")
    if len(image_bytes) > 64 * 1024 * 1024:
        raise ValueError("Image is too large")
    with Image.open(io.BytesIO(image_bytes)) as opened:
        opened.load()
        info = dict(getattr(opened, "info", {}) or {})
    workflow_text = info.get("workflow") or info.get("workflow_api")
    prompt_text = info.get("prompt") or info.get("workflow_api")
    if not workflow_text or not prompt_text:
        raise ValueError("PNG does not include ComfyUI workflow metadata")
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
    }


def _apply_comfyui_workflow_metadata(context: WebSessionContext, metadata: dict[str, Any] | None) -> dict[str, Any]:
    metadata = metadata or {}
    workflow = metadata.get("workflow")
    if not isinstance(workflow, dict):
        raise ValueError("ComfyUI workflow metadata is invalid")
    context.remote_params["comfyui_workflow"] = workflow
    context.remote_params["_comfyui_workflow_ui"] = metadata.get("workflow_ui")
    context.remote_params["comfyui_workflow_has_custom"] = True
    context.remote_params["comfyui_workflow_label"] = "Custom Workflow"
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
        "comfyui_workflow_model_compat",
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


def _event_preset_bootstrap(
    context: WebSessionContext,
    rating_id: str = "s",
    person_id: str = "1girl_solo",
    search: str = "",
    category_id: str = "",
    subcategory_id: str = "",
    event_id: str = "",
    limit: int | None = None,
) -> dict[str, Any]:
    payload = _event_preset_service(context).bootstrap(
        rating_id,
        person_id,
        search,
        category_id,
        subcategory_id,
        event_id,
        limit,
    )
    payload["download"] = _event_preset_download_service(context).snapshot()
    return payload


def _preset_source_to_generation_command(
    context: WebSessionContext,
    result: dict[str, Any],
    *,
    source: str,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_row_data = result.get("sourceRow") if isinstance(result.get("sourceRow"), dict) else {}
    if not source_row_data.get("general"):
        raise ValueError("Preset prompt source is empty.")
    request_id = str(result.get("requestId") or uuid.uuid4().hex)
    result["requestId"] = request_id
    generation_overrides = dict(overrides or {})
    result_overrides = result.get("overrides") if isinstance(result.get("overrides"), dict) else {}
    generation_overrides.update(result_overrides)
    generation_overrides.update({
        "input": str(source_row_data.get("general") or ""),
        "_raw_input": str(source_row_data.get("general") or ""),
        "_source_row_data": source_row_data,
        "_source_name": str(result.get("sourceName") or f"{source}:{request_id}"),
        "_remote_queue_source": "Preset",
        "_remote_queue_label": source,
    })
    if source == "event_preset":
        generation_overrides.update({
            "event_preset_request": True,
            "event_preset_request_id": request_id,
        })
    elif source == "preset":
        generation_overrides.update({
            "remote_preset_request": True,
            "remote_preset_request_id": request_id,
        })
    rating = str(source_row_data.get("rating") or "").strip()
    if rating in {"g", "s", "q", "e"}:
        context.set_active_ratings([rating])
    return {
        "type": "generate",
        "api_mode": generation_overrides.get("api_mode") or context.get_api_mode(),
        "prompt": str(source_row_data.get("general") or ""),
        "negative_prompt": (
            str(generation_overrides.get("negative_prompt") or "")
            if "negative_prompt" in generation_overrides
            else str(context.negative_prompt_text or "")
        ),
        "overrides": generation_overrides,
    }


def _preset_prompt_generated_payload(
    context: WebSessionContext,
    result: dict[str, Any],
    *,
    source: str,
) -> dict[str, Any]:
    request_id = str(result.get("requestId") or "")
    source_row_data = result.get("sourceRow") if isinstance(result.get("sourceRow"), dict) else {}
    prompt = str(
        result.get("promptPreview")
        or (result.get("promptPlan") or {}).get("finalPrompt")
        or source_row_data.get("general")
        or ""
    )
    payload: dict[str, Any] = {
        "type": "prompt_generated",
        "source": source,
        "prompt": prompt,
        "requestId": request_id,
        "remaining": context.search_results.get_count() if context.search_results else 0,
        "rating_counts": context.search_state_payload().get("rating_counts", {}),
    }
    if source == "event_preset":
        payload["event_preset_request_id"] = request_id
        payload["selected"] = result.get("selected") or {}
        payload["event"] = result.get("event") or {}
    elif source == "preset":
        payload["remote_preset_request_id"] = request_id
        payload["promptPlan"] = result.get("promptPlan") or {}
    return payload


def _tag_lookup_info(context: WebSessionContext, tag: str) -> dict[str, Any]:
    raw_tags = getattr(context, "kr_tags_raw", None)
    if not isinstance(raw_tags, dict) or not raw_tags:
        from core.kr_tag_loader import load_kr_tag_records
        from core.tag_relation_ranker import TagRelationRanker

        load_result = load_kr_tag_records(context.repo_root)
        raw_tags = load_result.raw
        context.kr_tags_raw = raw_tags
        context.tag_relation_ranker = TagRelationRanker(raw_tags) if raw_tags else None
    if not raw_tags:
        return {}
    tag_lower = re.sub(r"\\([()])", r"\1", str(tag or "").strip()).lower()
    info = raw_tags.get(tag_lower)
    if not info:
        return {}
    result = {
        "tag": info.get("_tag", tag),
        "count": info.get("freq", 0),
        "desc": info.get("description", ""),
        "group": info.get("group", ""),
        "subgroup": info.get("subgroup", ""),
        "cat": info.get("_cat", ""),
    }
    relations = info.get("relations", {}) if isinstance(info.get("relations"), dict) else {}
    parents = relations.get("parent", [])
    if isinstance(parents, str):
        parents = [parents]
    ranker = getattr(context, "tag_relation_ranker", None)
    if ranker is not None:
        parents = ranker.valid_implications(tag_lower, info, limit=8)
    if parents:
        result["implications"] = parents[:8]
    if ranker is not None:
        related = ranker.rank_related(tag_lower, info, limit=8)
    else:
        related = []
        seen = set(parents)
        for relation_key in ("siblings", "word_match"):
            values = relations.get(relation_key, [])
            if isinstance(values, str):
                values = [values]
            for value in values:
                if value not in seen:
                    seen.add(value)
                    related.append(value)
    if related:
        result["related"] = related[:8]
    extra_info = {}
    for extra_tag in list(result.get("implications", [])) + list(result.get("related", [])):
        extra = raw_tags.get(str(extra_tag).strip().lower())
        if not extra:
            continue
        extra_info[str(extra_tag)] = {
            "tag": extra.get("_tag", str(extra_tag)),
            "count": extra.get("freq", 0),
            "desc": extra.get("description", ""),
            "group": extra.get("group", ""),
            "subgroup": extra.get("subgroup", ""),
            "cat": extra.get("_cat", ""),
        }
    if extra_info:
        result["extra_tag_info"] = extra_info
    return result


def _normalize_danbooru_browser_url(value: str = "") -> str:
    text = str(value or "").strip()
    if not text:
        return f"{DANBOORU_BASE_URL}/posts?tags=rating%3Ageneral&z=5"
    if text.isdigit():
        return f"{DANBOORU_BASE_URL}/posts/{text}"
    if text.startswith("//"):
        text = "https:" + text
    elif text.startswith("/"):
        text = urljoin(DANBOORU_BASE_URL, text)
    elif re.match(r"^(?:www\.)?danbooru\.donmai\.us(?:/|$)", text, re.IGNORECASE):
        text = "https://" + text
    elif not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", text):
        text = f"{DANBOORU_BASE_URL}/posts?tags={quote(text, safe=':-_~')}"

    parsed = urlparse(text)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or hostname not in {"danbooru.donmai.us", "www.danbooru.donmai.us"}:
        raise ValueError("Danbooru URL, post ID, or tag query is required")
    return text


def _load_characteristic_tags(context: WebSessionContext) -> set[str]:
    path = Path(context.repo_root) / "data" / "characteristic_list.txt"
    try:
        return {
            line.strip().replace("_", " ")
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
    except Exception:
        return set()


def _fallback_danbooru_prompt(tags: dict[str, Any]) -> str:
    general_tags = tags.get("general") if isinstance(tags, dict) and isinstance(tags.get("general"), list) else []
    return ", ".join(map(str, general_tags))


def _danbooru_prompt_preview(context: WebSessionContext, tags: dict[str, Any]) -> str:
    try:
        _random_service(context)._ensure_headless_runtime()
        service = getattr(context, "prompt_generation_service", None)
        settings = {
            "api_mode": context.get_api_mode(),
            "auto_generate": False,
            "prompt_fixed": False,
            "wildcard_standalone": False,
        }
        if service is not None and hasattr(service, "generate_instant_source_silent"):
            prompt = service.generate_instant_source_silent(tags, settings)
            if prompt:
                return str(prompt)
    except Exception as exc:
        print(f"Headless Remote: Danbooru prompt preview failed — {exc}", flush=True)
    return _fallback_danbooru_prompt(tags)


def _build_danbooru_post_payload(context: WebSessionContext, query: str) -> dict[str, Any]:
    post = fetch_danbooru_post(
        query,
        characteristic_tags=_load_characteristic_tags(context),
    )
    post["prompt"] = _danbooru_prompt_preview(context, post.get("tags", {}))
    return post


def _image_media_type(image_bytes: bytes) -> str:
    if image_bytes.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def _character_viewer_thumbnail_payload(
    context: WebSessionContext,
    group: str,
    character: str,
    variant: str = "",
    size: str = "",
) -> tuple[bytes, str]:
    service = _character_viewer_service(context)
    path = service.thumbnail_path(str(group or ""), str(character or ""), str(variant or ""))
    size_key = str(size or "").strip().lower()
    if size_key == "grid":
        cache = getattr(context, "character_viewer_grid_thumb_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            context.character_viewer_grid_thumb_cache = cache
        stat = path.stat()
        cache_key = (str(path), stat.st_mtime_ns, stat.st_size, size_key)
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        from PIL import Image

        with Image.open(path) as image:
            image.thumbnail((384, 384), Image.Resampling.BILINEAR)
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGB")
            buffer = io.BytesIO()
            image.save(buffer, "WEBP", quality=72, method=0)
        payload = (buffer.getvalue(), "image/webp")
        if len(cache) > 256:
            cache.clear()
        cache[cache_key] = payload
        return payload

    raw = path.read_bytes()
    return raw, _image_media_type(raw)


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
                        _save_prompt_engineering_thumbnail_bytes,
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
        context.negative_prompt_text = str(command.get("negative") or "")
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
        await ws.send_text(json.dumps(context.search_state_payload(), ensure_ascii=False))
    elif command_type == "probe_api":
        allowed, reason = context.setup_gate(client_host)
        if not allowed:
            await ws.send_text(json.dumps({
                "type": "setup_blocked",
                "command": "probe_api",
                "reason": reason,
            }, ensure_ascii=False))
            return
        results = await _to_thread(context.probe_api)
        await ws.send_text(json.dumps({
            "type": "probe_result",
            "command": "probe_api",
            "results": results,
        }, ensure_ascii=False))
    elif command_type in {"verify_nai", "verify_webui", "verify_comfyui"}:
        allowed, reason = context.setup_gate(client_host)
        if not allowed:
            await ws.send_text(json.dumps({
                "type": "setup_blocked",
                "command": command_type,
                "reason": reason,
            }, ensure_ascii=False))
            return
        mode = {
            "verify_nai": "NAI",
            "verify_webui": "WEBUI",
            "verify_comfyui": "COMFYUI",
        }[command_type]
        raw_value = command.get("token") if mode == "NAI" else command.get("url")
        result = await _to_thread(context.verify_api, mode, str(raw_value or ""))
        await ws.send_text(json.dumps(result, ensure_ascii=False))
        await ws.send_text(json.dumps(context.api_status_payload(client_host), ensure_ascii=False))
    elif command_type == "clear_api":
        allowed, reason = context.setup_gate(client_host)
        if not allowed:
            await ws.send_text(json.dumps({
                "type": "setup_blocked",
                "command": command_type,
                "reason": reason,
            }, ensure_ascii=False))
            return
        result = await _to_thread(context.clear_api, str(command.get("mode") or ""))
        await ws.send_text(json.dumps(result, ensure_ascii=False))
        await ws.send_text(json.dumps(context.api_status_payload(client_host), ensure_ascii=False))
    elif command_type == "set_cloudflared_enabled":
        allowed, reason = context.cloudflared_gate(client_host)
        if not allowed:
            await ws.send_text(json.dumps({
                "type": "toast",
                "level": "error",
                "message": reason,
                "reason": reason,
            }, ensure_ascii=False))
            return
        result = await _to_thread(context.set_cloudflared_enabled, bool(command.get("enabled", False)))
        if not result.get("success", False):
            await ws.send_text(json.dumps({
                "type": "toast",
                "level": "error",
                "message": result.get("error") or result.get("status_text") or "Cloudflared failed",
            }, ensure_ascii=False))
        await ws.send_text(json.dumps(context.api_status_payload(client_host), ensure_ascii=False))
    elif command_type == "get_search_state":
        await ws.send_text(json.dumps(context.search_state_payload(), ensure_ascii=False))
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
            await ws.send_text(json.dumps(module_state, ensure_ascii=False))
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
        await ws.send_text(json.dumps({
            "type": "result_enhance_state",
            "running": False,
            "success": False,
            "message": "Result enhance is not available in the headless runtime yet.",
            "headless": True,
        }, ensure_ascii=False))
        await ws.send_text(json.dumps({
            "type": "toast",
            "level": "info",
            "message": "Headless command retired: result_enhance",
            "headless": True,
        }, ensure_ascii=False))
    elif command_type == "set_result_enhance_config":
        await ws.send_text(json.dumps({
            "type": "result_enhance_config",
            "upscale": command.get("upscale", 1.5),
            "strength": command.get("strength", 0.2),
            "noise": command.get("noise", 0.0),
            "available": False,
            "headless": True,
        }, ensure_ascii=False))
    elif command_type == "result_image_action":
        action = str(command.get("action") or "image_action")
        await ws.send_text(json.dumps({
            "type": "toast",
            "level": "info",
            "message": f"Headless command retired: result_image_action/{action}",
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

        task = getattr(session_context, "headless_random_warmup_task", None)
        if task is None or task.done():
            session_context.headless_random_warmup_task = asyncio.create_task(run_warmup())
        yield

    app = FastAPI(title="NAIA Remote Headless", lifespan=lifespan)
    app.state.web_session_context = session_context
    app.state.headless_clients = set()

    root_web_dir = Path(web_dir) if web_dir is not None else Path(__file__).resolve().parent.parent / "ui" / "remote_web"
    mimetypes.add_type("text/javascript", ".mjs")

    js_dir = root_web_dir / "js"
    if js_dir.exists():
        app.mount("/js", StaticFiles(directory=str(js_dir)), name="remote_js")
    guides_dir = root_web_dir / "guides"
    if guides_dir.exists():
        app.mount("/guides", StaticFiles(directory=str(guides_dir), html=True), name="remote_guides")

    @app.get("/")
    async def index():
        return _web_file(root_web_dir / "index.html", "text/html")

    @app.get("/style.css")
    async def serve_css():
        return _web_file(root_web_dir / "style.css", "text/css")

    @app.get("/app.js")
    async def serve_js():
        return _web_file(root_web_dir / "app.js", "application/javascript")

    @app.get("/api/status")
    async def api_status():
        return session_context.http_status_payload()

    @app.get("/api/queue/state")
    async def api_queue_state():
        return session_context.queue_state_payload()

    @app.post("/api/queue/action")
    async def api_queue_action(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        action = str(payload.get("action") or "").strip().lower()
        manager = session_context.generation_queue_manager
        if action == "pause":
            await _to_thread(manager.pause_queue)
        elif action == "resume":
            await _to_thread(manager.resume_queue)
            if session_context.headless_generation_execute_enabled:
                _ensure_generation_runner(session_context, app.state.headless_clients)
        elif action == "clear":
            await _to_thread(manager.clear_queue)
        elif action == "remove":
            request_id = str(payload.get("request_id") or payload.get("id") or "").strip()
            if not request_id:
                return JSONResponse({"error": "request_id is required"}, status_code=400)
            removed = await _to_thread(manager.remove_request, request_id)
            if not removed:
                return JSONResponse({"error": "request not found"}, status_code=404)
        else:
            return JSONResponse({"error": "Unsupported queue action"}, status_code=400)
        state = session_context.queue_state_payload()
        await _broadcast_json(app.state.headless_clients, state)
        return {"ok": True, "action": action, "queue": state}

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
            result = await _to_thread(
                _save_resolution_manager_state,
                session_context,
                payload.get("api_mode") or payload.get("mode"),
                payload.get("resolutions"),
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        await _broadcast_json(app.state.headless_clients, session_context.generation_param_schema_payload())
        return result

    @app.post("/api/search/parquet/upload")
    async def api_search_parquet_upload(req: Request):
        action = str(req.query_params.get("action") or "").strip().lower()
        filename = str(req.query_params.get("filename") or "uploaded.parquet")
        content = await req.body()
        try:
            result = await _to_thread(_apply_uploaded_search_parquet, session_context, content, action, filename)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"Parquet upload failed: {exc}"}, status_code=400)
        await _broadcast_json(app.state.headless_clients, session_context.search_state_payload())
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
            metadata = await _to_thread(_extract_comfyui_workflow_metadata_from_png, image_bytes)
            result = await _to_thread(_apply_comfyui_workflow_metadata, session_context, metadata)
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        await _broadcast_json(app.state.headless_clients, result["workflow"])
        await _broadcast_json(app.state.headless_clients, result["params"])
        return result

    @app.post("/api/comfyui/workflow/default")
    async def api_comfyui_workflow_default():
        result = await _to_thread(_clear_comfyui_workflow, session_context)
        await _broadcast_json(app.state.headless_clients, result["workflow"])
        await _broadcast_json(app.state.headless_clients, result["params"])
        return result

    @app.get("/api/prompt-highlight-index")
    async def api_prompt_highlight_index():
        return Response(
            content=json.dumps(_prompt_highlight_empty_index(), ensure_ascii=False),
            media_type="application/json",
            headers=_no_cache_headers(),
        )

    @app.get("/api/headless/capabilities")
    async def api_headless_capabilities():
        return {
            "headless": True,
            "right_tabs": {
                "result": True,
                "pngInfo": True,
                "thumb": True,
                "artists": True,
                "characters": True,
                "studio": True,
                "settings": False,
            },
            "retired_tabs": {},
        }

    @app.get("/api/event-preset/status")
    async def api_event_preset_status():
        try:
            return await _to_thread(_event_preset_status, session_context)
        except Exception as exc:
            return JSONResponse({"error": f"Event Preset status failed: {exc}"}, status_code=500)

    @app.get("/api/event-preset/download")
    async def api_event_preset_download_state():
        try:
            return await _to_thread(_event_preset_download_service(session_context).snapshot)
        except Exception as exc:
            return JSONResponse({"error": f"Event Preset download state failed: {exc}"}, status_code=500)

    @app.post("/api/event-preset/download")
    async def api_event_preset_download():
        try:
            return await _to_thread(_event_preset_download_service(session_context).start)
        except Exception as exc:
            return JSONResponse({"error": f"Event Preset download failed: {exc}"}, status_code=500)

    @app.post("/api/event-preset/download/cancel")
    async def api_event_preset_download_cancel():
        try:
            return await _to_thread(_event_preset_download_service(session_context).cancel)
        except Exception as exc:
            return JSONResponse({"error": f"Event Preset download cancel failed: {exc}"}, status_code=500)

    @app.get("/api/tag/lookup")
    async def api_tag_lookup(tag: str = ""):
        try:
            return await _to_thread(_tag_lookup_info, session_context, tag)
        except Exception as exc:
            return JSONResponse({"error": f"Tag lookup failed: {exc}"}, status_code=500)

    @app.post("/api/danbooru/post")
    async def api_danbooru_post(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        query = str(payload.get("query") or req.query_params.get("query") or "").strip()
        try:
            return await _to_thread(_build_danbooru_post_payload, session_context, query)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"Danbooru lookup failed: {exc}"}, status_code=502)

    @app.post("/api/danbooru/browser/open")
    async def api_danbooru_browser_open(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        query = str(payload.get("url") or payload.get("query") or req.query_params.get("url") or "").strip()
        try:
            target_url = _normalize_danbooru_browser_url(query)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return {"ok": True, "url": target_url, "headless": True, "open_external": True}

    @app.get("/api/event-preset/bootstrap")
    async def api_event_preset_bootstrap(
        ratingId: str = "s",
        personId: str = "1girl_solo",
        search: str = "",
        categoryId: str = "",
        subcategoryId: str = "",
        eventId: str = "",
        limit: int = 0,
    ):
        try:
            return await _to_thread(
                _event_preset_bootstrap,
                session_context,
                ratingId,
                personId,
                search,
                categoryId,
                subcategoryId,
                eventId,
                limit or None,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"Event Preset bootstrap failed: {exc}"}, status_code=500)

    @app.post("/api/event-preset/select")
    async def api_event_preset_select(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await _to_thread(_event_preset_service(session_context).select, payload)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Event Preset select failed: {exc}"}, status_code=500)

    @app.post("/api/event-preset/prompt-preview")
    async def api_event_preset_prompt_preview(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await _to_thread(_event_preset_service(session_context).prompt_preview, payload)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"Event Preset prompt preview failed: {exc}"}, status_code=500)

    @app.post("/api/preset/prompt-preview")
    async def api_preset_prompt_preview(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await _to_thread(_preset_composer_service(session_context).prompt_preview, payload)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"Preset prompt preview failed: {exc}"}, status_code=500)

    @app.post("/api/preset/generate")
    async def api_preset_generate(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            result = await _to_thread(_preset_composer_service(session_context).generation_source, payload)
            command = _preset_source_to_generation_command(
                session_context,
                result,
                source="preset",
                overrides=payload.get("overrides") if isinstance(payload.get("overrides"), dict) else {},
            )
            dispatch = await _to_thread(_generation_service(session_context).enqueue_remote_request, command)
        except RuntimeError as exc:
            return JSONResponse({"error": str(exc)}, status_code=409)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Preset generate failed: {exc}"}, status_code=500)
        if not dispatch.ok:
            return JSONResponse(dispatch.websocket_payload(), status_code=409)
        await _broadcast_json(
            app.state.headless_clients,
            _preset_prompt_generated_payload(session_context, result, source="preset"),
        )
        if session_context.headless_generation_execute_enabled:
            _ensure_generation_runner(session_context, app.state.headless_clients)
        return {
            "ok": True,
            "status": "generation_requested",
            "requestId": result.get("requestId") or dispatch.request_id,
            "promptPlan": result.get("promptPlan") or {},
        }

    @app.get("/api/clothes-preset/status")
    async def api_clothes_preset_status():
        try:
            return await _to_thread(_clothes_preset_service(session_context).status)
        except Exception as exc:
            return JSONResponse({"error": f"Clothes Preset status failed: {exc}"}, status_code=500)

    @app.post("/api/clothes-preset/bootstrap")
    async def api_clothes_preset_bootstrap(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await _to_thread(_clothes_preset_service(session_context).bootstrap, payload)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"Clothes Preset bootstrap failed: {exc}"}, status_code=500)

    @app.post("/api/clothes-preset/select")
    async def api_clothes_preset_select(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await _to_thread(_clothes_preset_service(session_context).select, payload)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"Clothes Preset select failed: {exc}"}, status_code=500)

    @app.post("/api/clothes-preset/lucky")
    async def api_clothes_preset_lucky(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await _to_thread(_clothes_preset_service(session_context).lucky, payload)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"Clothes Preset lucky failed: {exc}"}, status_code=500)

    @app.post("/api/clothes-preset/prompt-fragment")
    async def api_clothes_preset_prompt_fragment(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await _to_thread(_clothes_preset_service(session_context).prompt_fragment, payload)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"Clothes Preset prompt fragment failed: {exc}"}, status_code=500)

    @app.get("/api/expression-preset/status")
    async def api_expression_preset_status():
        try:
            return await _to_thread(_expression_preset_service(session_context).status)
        except Exception as exc:
            return JSONResponse({"error": f"Expression Preset status failed: {exc}"}, status_code=500)

    @app.post("/api/expression-preset/bootstrap")
    async def api_expression_preset_bootstrap(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await _to_thread(_expression_preset_service(session_context).bootstrap, payload)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"Expression Preset bootstrap failed: {exc}"}, status_code=500)

    @app.post("/api/event-preset/generate")
    async def api_event_preset_generate(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            result = await _to_thread(_event_preset_service(session_context).generation_source, payload)
            command = _preset_source_to_generation_command(
                session_context,
                result,
                source="event_preset",
                overrides=payload.get("overrides") if isinstance(payload.get("overrides"), dict) else {},
            )
            dispatch = await _to_thread(_generation_service(session_context).enqueue_remote_request, command)
        except RuntimeError as exc:
            return JSONResponse({"error": str(exc)}, status_code=409)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Event Preset generate failed: {exc}"}, status_code=500)
        if not dispatch.ok:
            return JSONResponse(dispatch.websocket_payload(), status_code=409)
        await _broadcast_json(
            app.state.headless_clients,
            _preset_prompt_generated_payload(session_context, result, source="event_preset"),
        )
        if session_context.headless_generation_execute_enabled:
            _ensure_generation_runner(session_context, app.state.headless_clients)
        return {
            "ok": True,
            "status": "generation_requested",
            "requestId": result.get("requestId") or dispatch.request_id,
            "selected": result.get("selected") or {},
            "promptPreview": result.get("promptPreview") or "",
            "event": result.get("event") or {},
        }

    @app.get("/api/event-preset/thumbnail")
    async def api_event_preset_thumbnail(eventId: str = "", tag: str = "", size: str = ""):
        try:
            image_bytes, media_type = await _to_thread(
                _event_preset_service(session_context).thumbnail_payload,
                eventId,
                tag,
                size,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except (FileNotFoundError, KeyError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Event Preset thumbnail failed: {exc}"}, status_code=500)
        return Response(
            content=image_bytes,
            media_type=media_type,
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @app.get("/api/prompt-engineering/preset-thumbnail")
    async def api_prompt_engineering_preset_thumbnail(name: str = "", mode: str = "", v: str = ""):
        try:
            target = await _to_thread(_prompt_engineering_preview_path, session_context, name, mode)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        if not target:
            return JSONResponse({"error": "Preset thumbnail not found"}, status_code=404)
        return FileResponse(
            str(target),
            media_type=_image_media_type_for_path(target),
            headers=_no_cache_headers(),
        )

    @app.post("/api/prompt-engineering/preset-thumbnail/upload")
    async def api_prompt_engineering_preset_thumbnail_upload(req: Request, name: str = "", mode: str = ""):
        try:
            image_bytes = await req.body()
            payload = await _to_thread(
                _save_prompt_engineering_thumbnail_bytes,
                session_context,
                name,
                mode,
                image_bytes,
            )
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"Preset thumbnail upload failed: {exc}"}, status_code=500)
        await _broadcast_json(app.state.headless_clients, {
            "type": "prompt_engineering_preset_thumbnail_updated",
            **payload,
        })
        return payload

    @app.post("/api/prompt-engineering/preset-thumbnail/generate")
    async def api_prompt_engineering_preset_thumbnail_generate(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            name = Path(str(payload.get("name") or "").strip()).name
            mode = _normalize_prompt_engineering_preset_mode(session_context, payload.get("mode") or "")
            if not name or name == "*randomized":
                raise ValueError("Preset name is required")
            if not _prompt_engineering_preset_file(session_context, name, mode):
                raise FileNotFoundError(f"Preset not found: {name}")
            request_id = str(payload.get("request_id") or uuid.uuid4().hex)
            prompt = _prompt_engineering_thumbnail_generation_prompt(session_context, name, mode)
            overrides = {
                "input": prompt,
                "_raw_input": prompt,
                "negative_prompt": session_context.negative_prompt_text,
                "width": 1088,
                "height": 960,
                "random_resolution": False,
                "prompt_preset_thumbnail_request": True,
                "prompt_preset_thumbnail_request_id": request_id,
                "prompt_preset_thumbnail_name": name,
                "prompt_preset_thumbnail_mode": mode,
                "_skip_vibe_transfer_late_binding": True,
                "_remote_queue_source": "Preset Thumb",
                "_remote_queue_label": name,
            }
            dispatch = await _to_thread(
                _generation_service(session_context).enqueue_remote_request,
                {"type": "generate", "overrides": overrides},
            )
        except FileNotFoundError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=404)
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"Preset thumbnail generation failed: {exc}"}, status_code=500)
        if not dispatch.ok:
            return JSONResponse(dispatch.websocket_payload(), status_code=409)
        await _broadcast_json(app.state.headless_clients, session_context.queue_state_payload())
        if session_context.headless_generation_execute_enabled:
            _ensure_generation_runner(session_context, app.state.headless_clients)
        return {
            "ok": True,
            "status": "generation_requested",
            "request_id": request_id,
            "name": name,
            "mode": mode,
            "vibe_active": False,
            "vibe_count": 0,
            "message": f"{name} 임시 썸네일 생성을 요청했습니다.",
        }

    @app.get("/api/artist-thumb/state")
    async def api_artist_thumb_state():
        try:
            return await _to_thread(_artist_thumbnail_service(session_context).state)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb state failed: {exc}"}, status_code=500)

    @app.get("/api/artist-thumb/list")
    async def api_artist_thumb_list(
        mode: str = "",
        filter: str = "all",
        query: str = "",
        page: int = 0,
        per_page: int = 48,
        random_sample: bool = False,
    ):
        try:
            return await _to_thread(
                _artist_thumbnail_service(session_context).build_list,
                mode,
                filter,
                query,
                page,
                per_page,
                random_sample,
            )
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb list failed: {exc}"}, status_code=500)

    @app.get("/api/artist-thumb/image")
    async def api_artist_thumb_image(mode: str = "", artist: str = ""):
        try:
            image_bytes, media_type = await _to_thread(
                _artist_thumbnail_service(session_context).image_payload,
                mode,
                artist,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except (FileNotFoundError, KeyError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb image failed: {exc}"}, status_code=500)
        return Response(
            content=image_bytes,
            media_type=media_type,
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @app.get("/api/artist-thumb/favorite-image")
    async def api_artist_thumb_favorite_image(artist: str = ""):
        try:
            image_bytes, media_type = await _to_thread(
                _artist_thumbnail_service(session_context).favorite_image_payload,
                artist,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except (FileNotFoundError, KeyError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb favorite image failed: {exc}"}, status_code=500)
        return Response(
            content=image_bytes,
            media_type=media_type,
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @app.post("/api/artist-thumb/favorite")
    async def api_artist_thumb_favorite(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await _to_thread(
                _artist_thumbnail_service(session_context).set_favorite,
                payload.get("artist", ""),
                bool(payload.get("favorite", True)),
                payload.get("mode", ""),
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb favorite failed: {exc}"}, status_code=500)

    @app.post("/api/artist-thumb/ban")
    async def api_artist_thumb_ban(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await _to_thread(
                _artist_thumbnail_service(session_context).set_banned,
                payload.get("artist", ""),
                bool(payload.get("banned", True)),
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb ban failed: {exc}"}, status_code=500)

    @app.post("/api/artist-thumb/options")
    async def api_artist_thumb_options(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await _to_thread(_artist_thumbnail_service(session_context).save_options, payload)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb options failed: {exc}"}, status_code=500)

    @app.get("/api/artist-thumb/download")
    async def api_artist_thumb_download_state():
        try:
            return await _to_thread(_artist_thumbnail_service(session_context).download_snapshot)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb download state failed: {exc}"}, status_code=500)

    @app.post("/api/artist-thumb/download")
    async def api_artist_thumb_download(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await _to_thread(_artist_thumbnail_service(session_context).start_download, payload.get("mode", ""))
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb download failed: {exc}"}, status_code=500)

    @app.post("/api/artist-thumb/download/cancel")
    async def api_artist_thumb_download_cancel():
        try:
            return await _to_thread(_artist_thumbnail_service(session_context).cancel_download)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb download cancel failed: {exc}"}, status_code=500)

    @app.post("/api/artist-thumb/random-prompt")
    async def api_artist_thumb_random_prompt(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        artist_prompt = str(payload.get("artist_prompt") or "").strip()
        if not artist_prompt:
            return JSONResponse({"error": "artist_prompt is required"}, status_code=400)
        try:
            from core.prompt_engineering_settings import get_prompt_engineering_store

            module_settings = get_prompt_engineering_store(session_context).collect_settings(
                session_context.get_api_mode()
            )
            peng_override = await _to_thread(
                _artist_thumbnail_service(session_context).random_prompt_override,
                artist_prompt,
                module_settings,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb random prompt setup failed: {exc}"}, status_code=500)

        request_id = str(uuid.uuid4())
        previous_override = getattr(session_context, "session_p_eng_override", None)
        session_context.session_p_eng_override = peng_override
        try:
            result = await _to_thread(
                _random_service(session_context).generate,
                active_ratings=session_context.get_active_ratings(),
                overrides={"auto_generate": False},
                random_request_id=request_id,
            )
        finally:
            if getattr(session_context, "session_p_eng_override", None) is peng_override:
                session_context.session_p_eng_override = previous_override
        if not result.success:
            return JSONResponse(result.websocket_payload(), status_code=500)
        return {
            "request_id": request_id,
            "prompt": result.prompt,
            "negative_prompt": session_context.negative_prompt_text,
            "remaining": result.remaining,
            "source": "artist_thumb_random",
            "detected_resolution": result.detected_resolution,
        }

    @app.post("/api/artist-thumb/generate")
    async def api_artist_thumb_generate(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            overrides = await _to_thread(
                _artist_thumbnail_service(session_context).generation_overrides,
                payload,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        dispatch = await _to_thread(
            _generation_service(session_context).enqueue_remote_request,
            {
                "type": "generate",
                "api_mode": overrides.get("api_mode") or session_context.get_api_mode(),
                "overrides": overrides,
            },
        )
        if not dispatch.ok:
            return JSONResponse(dispatch.websocket_payload(), status_code=409)
        if session_context.headless_generation_execute_enabled:
            _ensure_generation_runner(session_context, app.state.headless_clients)
        return {"ok": True, **dispatch.websocket_payload()}

    @app.get("/api/thumb/state")
    async def api_thumb_state():
        try:
            return await _to_thread(_style_thumbnail_service(session_context).state)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Thumb state failed: {exc}"}, status_code=500)

    @app.get("/api/thumb/category/{category_key}")
    async def api_thumb_category(category_key: str):
        try:
            return await _to_thread(_style_thumbnail_service(session_context).category_payload, category_key)
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Thumb category failed: {exc}"}, status_code=500)

    @app.get("/api/thumb/image")
    async def api_thumb_image(tag: str = ""):
        try:
            image_bytes, media_type = await _to_thread(_style_thumbnail_service(session_context).image_payload, tag)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Thumb image failed: {exc}"}, status_code=500)
        return Response(
            content=image_bytes,
            media_type=media_type,
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @app.get("/api/character-viewer/state")
    async def api_character_viewer_state():
        try:
            state = await _to_thread(_character_viewer_service(session_context).state)
            state["generation_delay_ms"] = 500
            return state
        except Exception as exc:
            return JSONResponse({"error": f"Character Viewer state failed: {exc}"}, status_code=500)

    @app.get("/api/character-viewer/groups")
    async def api_character_viewer_groups(query: str = ""):
        try:
            return await _to_thread(_character_viewer_service(session_context).build_groups, query)
        except Exception as exc:
            return JSONResponse({"error": f"Character Viewer groups failed: {exc}"}, status_code=500)

    @app.get("/api/character-viewer/list")
    async def api_character_viewer_list(
        group: str = "",
        query: str = "",
        page: int = 0,
        per_page: int = 48,
        thumb_first: bool = True,
        include_all: bool = False,
    ):
        try:
            group_key = str(group or CharacterViewerService.GROUP_ALL)
            return await _to_thread(
                _character_viewer_service(session_context).build_list,
                group_key,
                query,
                page,
                per_page,
                thumb_first,
                include_all,
            )
        except Exception as exc:
            return JSONResponse({"error": f"Character Viewer list failed: {exc}"}, status_code=500)

    @app.post("/api/character-viewer/detail")
    async def api_character_viewer_detail(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await _to_thread(
                _character_viewer_service(session_context).build_detail,
                str(payload.get("group") or ""),
                str(payload.get("character") or ""),
                str(payload.get("variant") or ""),
                payload.get("options") if isinstance(payload.get("options"), dict) else {},
                session_context.get_api_mode(),
            )
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Character Viewer detail failed: {exc}"}, status_code=500)

    @app.post("/api/character-viewer/prompt")
    async def api_character_viewer_prompt(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await _to_thread(
                _character_viewer_service(session_context).build_prompt,
                str(payload.get("group") or ""),
                str(payload.get("character") or ""),
                str(payload.get("variant") or ""),
                payload.get("options") if isinstance(payload.get("options"), dict) else payload,
                session_context.get_api_mode(),
            )
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Character Viewer prompt failed: {exc}"}, status_code=500)

    @app.post("/api/character-viewer/options")
    async def api_character_viewer_options(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await _to_thread(_character_viewer_service(session_context).save_options, payload)
        except Exception as exc:
            return JSONResponse({"error": f"Character Viewer options failed: {exc}"}, status_code=500)

    @app.get("/api/character-viewer/thumbnail")
    async def api_character_viewer_thumbnail(group: str = "", character: str = "", variant: str = "", size: str = ""):
        try:
            image_bytes, media_type = await _to_thread(
                _character_viewer_thumbnail_payload,
                session_context,
                group,
                character,
                variant,
                size,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except (FileNotFoundError, KeyError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Character Viewer thumbnail failed: {exc}"}, status_code=500)
        return Response(
            content=image_bytes,
            media_type=media_type,
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @app.post("/api/character-viewer/generate")
    async def api_character_viewer_generate(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            overrides = await _to_thread(
                _character_viewer_service(session_context).build_generation_overrides,
                payload,
                session_context.get_api_mode(),
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        dispatch = await _to_thread(
            _generation_service(session_context).enqueue_remote_request,
            {"type": "generate", "overrides": overrides},
        )
        if not dispatch.ok:
            return JSONResponse(dispatch.websocket_payload(), status_code=409)
        if session_context.headless_generation_execute_enabled:
            _ensure_generation_runner(session_context, app.state.headless_clients)
        return {"ok": True, **dispatch.websocket_payload()}

    @app.get("/api/latest-image")
    async def api_latest_image():
        try:
            image_bytes, media_type = session_context.result_store.latest_image_payload()
        except FileNotFoundError:
            return JSONResponse({"error": "No image generated yet"}, status_code=404)
        return Response(
            content=image_bytes,
            media_type=media_type,
            headers={"Content-Disposition": result_images.download_content_disposition("naia_latest.webp")},
        )

    @app.get("/api/result/image/png")
    async def api_result_image_png(source: str = "", path: str = ""):
        try:
            requested_path = str(path or "").strip()
            normalized_source = str(source or "").strip().lower()
            item = _history_item_from_viewer_path(session_context, path)
            target = _validate_viewer_path(session_context, path)
            if item is not None:
                png_bytes, filename = result_images.history_item_png_payload(item, label=item.filename)
            elif target is not None:
                png_bytes, filename = result_images.image_file_to_png_payload(target)
            elif requested_path or normalized_source == "saved":
                raise FileNotFoundError("Image not found")
            else:
                png_bytes, filename = session_context.result_store.current_png_payload()
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        return Response(
            content=png_bytes,
            media_type="image/png",
            headers={"Content-Disposition": result_images.download_content_disposition(filename)},
        )

    @app.get("/api/result/image/original")
    async def api_result_image_original(source: str = "", path: str = ""):
        requested_path = str(path or "").strip()
        normalized_source = str(source or "").strip().lower()
        item = _history_item_from_viewer_path(session_context, path)
        target = _validate_viewer_path(session_context, path)
        try:
            if item is not None:
                image_bytes, media_type = result_images.history_item_image_payload(item)
                filename = item.filename
            elif target is not None:
                return FileResponse(
                    str(target),
                    media_type=_image_media_type_for_path(target),
                    filename=target.name,
                    headers={"Content-Disposition": result_images.download_content_disposition(target.name)},
                )
            elif requested_path or normalized_source == "saved":
                raise FileNotFoundError("Image not found")
            else:
                image_bytes, media_type = session_context.result_store.latest_image_payload()
                filename = "naia_latest.webp"
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        return Response(
            content=image_bytes,
            media_type=media_type,
            headers={"Content-Disposition": result_images.download_content_disposition(filename)},
        )

    @app.post("/api/result/clipboard/png")
    async def api_result_clipboard_png():
        return JSONResponse({
            "error": "Native clipboard copy is not available in the headless runtime; use the browser clipboard path.",
            "headless": True,
        }, status_code=400)

    @app.get("/api/clipboard/png")
    async def api_clipboard_png():
        return JSONResponse({
            "error": "Native clipboard read is not available in the headless runtime.",
            "headless": True,
        }, status_code=404)

    @app.get("/api/result/asset/current")
    async def api_current_result_asset():
        asset = _build_current_result_asset_payload(session_context)
        if not asset.get("has_image"):
            return JSONResponse({"error": "No image generated yet"}, status_code=404)
        return asset

    @app.get("/api/result/asset/saved")
    async def api_saved_result_asset(path: str = ""):
        asset = _build_saved_result_asset_payload(session_context, path)
        if not asset:
            return JSONResponse({"error": "not found"}, status_code=404)
        return asset

    @app.post("/api/image/fetch")
    async def api_image_fetch(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        url = str(payload.get("url") or req.query_params.get("url") or "").strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return JSONResponse({"error": "Only http/https image URLs are supported"}, status_code=400)

        def _fetch_remote_image() -> tuple[bytes, str]:
            import ipaddress
            import socket
            import urllib.request
            from PIL import Image

            def validate_public_url(candidate_url: str) -> None:
                candidate = urlparse(candidate_url)
                if candidate.scheme not in {"http", "https"} or not candidate.hostname:
                    raise ValueError("Only http/https image URLs are supported")
                addresses = socket.getaddrinfo(candidate.hostname, None)
                for address in addresses:
                    ip = ipaddress.ip_address(address[4][0])
                    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
                        raise ValueError("Private or loopback image URLs are not allowed")

            validate_public_url(url)
            request = urllib.request.Request(url, headers={"User-Agent": "NAIA-Headless/1.0"})
            with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310 - URL is validated above.
                final_url = response.geturl()
                if final_url and final_url != url:
                    validate_public_url(final_url)
                image_bytes = response.read(64 * 1024 * 1024 + 1)
                if len(image_bytes) > 64 * 1024 * 1024:
                    raise ValueError("Image is too large")
                media_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            if not media_type.startswith("image/"):
                with Image.open(io.BytesIO(image_bytes)) as opened:
                    opened.load()
                    media_type = {
                        "PNG": "image/png",
                        "JPEG": "image/jpeg",
                        "WEBP": "image/webp",
                        "GIF": "image/gif",
                        "BMP": "image/bmp",
                        "TIFF": "image/tiff",
                    }.get((opened.format or "").upper(), "")
            if not media_type.startswith("image/"):
                raise ValueError("URL did not return an image")
            return image_bytes, media_type

        try:
            image_bytes, media_type = await _to_thread(_fetch_remote_image)
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return Response(content=image_bytes, media_type=media_type, headers={"Cache-Control": "no-store"})

    @app.post("/api/metadata/extract")
    async def api_metadata_extract(req: Request):
        image_bytes = await req.body()
        if not image_bytes:
            return JSONResponse({"error": "No image data"}, status_code=400)
        if len(image_bytes) > 64 * 1024 * 1024:
            return JSONResponse({"error": "Image is too large"}, status_code=413)
        label = (req.query_params.get("label") or "Input Image")[:120]
        mime_type = req.headers.get("content-type", "")

        def _extract():
            from PIL import Image

            with Image.open(io.BytesIO(image_bytes)) as image:
                image.load()
                return _build_input_metadata_payload(image, image_bytes, label, mime_type)

        try:
            return await _to_thread(_extract)
        except Exception as exc:
            return JSONResponse({"error": f"Invalid image: {exc}"}, status_code=400)

    @app.get("/api/result/metadata")
    async def api_result_metadata():
        payload = session_context.result_store.latest_metadata_payload
        if payload is None:
            return JSONResponse({"error": "No image generated yet"}, status_code=404)
        return payload

    @app.get("/api/history/list")
    async def api_history_list(page: int = 0, per_page: int = 30):
        return session_context.result_store.history_list(page=page, per_page=per_page)

    @app.post("/api/history/open-folder")
    async def api_history_open_folder():
        def _open_folder():
            import os
            import subprocess
            import sys

            folder = _viewer_save_dir(session_context)
            folder.mkdir(parents=True, exist_ok=True)
            if sys.platform.startswith("darwin"):
                subprocess.Popen(["open", str(folder)])
            elif os.name == "nt":
                os.startfile(str(folder))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(folder)])
            return str(folder)

        try:
            opened = await _to_thread(_open_folder)
            return {"ok": True, "path": opened}
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

    @app.get("/api/viewer/list")
    async def api_viewer_list(page: int = 0, per_page: int = 30, scope: str = "memory"):
        page = max(0, int(page or 0))
        per_page = min(100, max(1, int(per_page or 30)))
        if str(scope or "").lower() in {"disk", "saved", "all"}:
            entries = await _to_thread(_scan_viewer_folder, session_context)
            resolved_scope = "disk"
        else:
            payload = session_context.result_store.history_list(page=page, per_page=per_page)
            payload["scope"] = "memory"
            return payload
        start = page * per_page
        end = start + per_page
        return {
            "total": len(entries),
            "page": page,
            "per_page": per_page,
            "scope": resolved_scope,
            "images": entries[start:end],
        }

    @app.get("/api/viewer/thumb/{path:path}")
    async def api_viewer_thumb(path: str, size: int = 0):
        item = _history_item_from_viewer_path(session_context, path)
        target = _validate_viewer_path(session_context, path)
        if item is None and target is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        if item is not None:
            thumb_bytes = session_context.result_store.history_thumb_payload(item.history_id, size)
        else:
            from PIL import Image

            with Image.open(str(target)) as image:
                image.load()
                thumb = image.copy()
                max_side = min(max(int(size or 256), 50), 1024)
                thumb.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
                buffer = io.BytesIO()
                thumb.save(buffer, format="WEBP", quality=85, method=4)
                thumb_bytes = buffer.getvalue()
        return Response(content=thumb_bytes, media_type="image/webp")

    @app.get("/api/viewer/image/{path:path}")
    async def api_viewer_image(path: str):
        item = _history_item_from_viewer_path(session_context, path)
        target = _validate_viewer_path(session_context, path)
        if item is not None:
            try:
                image_bytes, media_type = result_images.history_item_image_payload(item)
            except FileNotFoundError:
                return JSONResponse({"error": "not found"}, status_code=404)
            return Response(content=image_bytes, media_type=media_type)
        if target is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return FileResponse(str(target), media_type=_image_media_type_for_path(target))

    @app.get("/api/viewer/image/")
    async def api_viewer_image_empty():
        return JSONResponse({"error": "not found"}, status_code=404)

    @app.get("/api/viewer/meta")
    async def api_viewer_meta_query(path: str = "", full: bool = False):
        return await api_viewer_meta(path, full)

    @app.get("/api/viewer/meta/{path:path}")
    async def api_viewer_meta(path: str, full: bool = False):
        item = _history_item_from_viewer_path(session_context, path)
        target = _validate_viewer_path(session_context, path)
        if item is not None:
            return session_context.result_store.history_meta_payload(item.history_id, include_full=full)
        if target is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        try:
            return await _to_thread(_metadata_for_disk_image, target, target.name, full)
        except Exception as exc:
            return JSONResponse({"error": f"Metadata extract failed: {exc}"}, status_code=400)

    @app.get("/api/viewer/{kind}/{path:path}")
    async def api_viewer_dynamic_kind(kind: str, path: str, size: int = 0, full: bool = False):
        normalized_kind = str(kind or "").strip().lower()
        if normalized_kind == "thumb":
            return await api_viewer_thumb(path, size)
        if normalized_kind == "image":
            return await api_viewer_image(path)
        if normalized_kind == "meta":
            return await api_viewer_meta(path, full)
        return JSONResponse({"error": "unsupported viewer asset kind"}, status_code=400)

    @app.get("/api/history/image/{history_id}")
    async def api_history_image(history_id: str):
        try:
            image_bytes, media_type = session_context.result_store.history_image_payload(history_id)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        return Response(content=image_bytes, media_type=media_type)

    @app.get("/api/history/thumb/{history_id}")
    async def api_history_thumb(history_id: str, size: int = 0):
        try:
            thumb_bytes = session_context.result_store.history_thumb_payload(history_id, size)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        return Response(content=thumb_bytes, media_type="image/webp")

    @app.get("/api/history/meta/{history_id}")
    async def api_history_meta(history_id: str, full: bool = False):
        try:
            return session_context.result_store.history_meta_payload(history_id, include_full=full)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)

    @app.post("/api/history/unsaved/save-all")
    async def api_history_unsaved_save_all():
        try:
            return session_context.save_unsaved_history()
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)

    @app.get("/api/history/unsaved/download")
    async def api_history_unsaved_download():
        try:
            zip_bytes, filename = session_context.result_store.unsaved_zip_payload()
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        return Response(
            content=zip_bytes,
            media_type="application/zip",
            headers={"Content-Disposition": result_images.download_content_disposition(filename)},
        )

    @app.get("/api/history/{kind}/{history_id}")
    async def api_history_dynamic_kind(kind: str, history_id: str, size: int = 0, full: bool = False):
        normalized_kind = str(kind or "").strip().lower()
        if normalized_kind == "thumb":
            return await api_history_thumb(history_id, size)
        if normalized_kind == "image":
            return await api_history_image(history_id)
        if normalized_kind == "meta":
            return await api_history_meta(history_id, full)
        return JSONResponse({"error": "unsupported history asset kind"}, status_code=400)

    @app.post("/api/result/open-location")
    async def api_result_open_location():
        return JSONResponse({
            "error": "Open location is a desktop-only action in the headless runtime.",
            "headless": True,
        }, status_code=400)

    @app.post("/api/result/action/reroll")
    async def api_result_action_reroll():
        return JSONResponse({
            "error": "Result reroll from saved desktop state is not available in the headless runtime yet.",
            "headless": True,
        }, status_code=400)

    @app.post("/api/result/action/queue")
    async def api_result_action_queue():
        return JSONResponse({
            "error": "Result queue replay from saved desktop state is not available in the headless runtime yet.",
            "headless": True,
        }, status_code=400)

    @app.post("/api/result/action/save")
    async def api_result_action_save():
        return JSONResponse({
            "error": "Desktop result save action is retired; use auto-save or unsaved history save-all.",
            "headless": True,
        }, status_code=400)

    @app.post("/api/result/action/delete")
    async def api_result_action_delete():
        return JSONResponse({
            "error": "Desktop result delete action is retired in the headless runtime.",
            "headless": True,
        }, status_code=400)

    @app.post("/api/image-action/{action}")
    async def api_image_action(action: str):
        return JSONResponse({
            "error": f"Image action '{action}' is desktop-only in the headless runtime.",
            "headless": True,
        }, status_code=400)

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
