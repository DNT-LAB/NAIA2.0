from __future__ import annotations

import base64
import io
import json
import time
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import quote, urlparse

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from core import result_image_payload_service as result_images
from core.web_session_context import WebSessionContext


IMAGE_VIEWER_EXTENSIONS = {".png", ".webp", ".jpg", ".jpeg"}
AsyncRunner = Callable[..., Awaitable[Any]]
JsonBroadcaster = Callable[[set[Any], dict[str, Any]], Awaitable[None]]


def _viewer_save_dir(context: WebSessionContext) -> Path:
    return context._current_save_directory()


def history_item_from_viewer_path(context: WebSessionContext, rel_path: str):
    normalized = str(rel_path or "").replace("\\", "/").strip("/")
    prefix = "__history_item__/"
    if not normalized.startswith(prefix):
        return None
    history_id = normalized[len(prefix):].split("/", 1)[0]
    return context.result_store.get_item(history_id)


def validate_viewer_path(context: WebSessionContext, rel_path: str) -> Path | None:
    if history_item_from_viewer_path(context, rel_path):
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


def history_item_from_action_payload(context: WebSessionContext, payload: dict[str, Any] | None):
    payload = payload if isinstance(payload, dict) else {}
    rel_path = str(payload.get("path") or "").strip()
    if not rel_path:
        return None
    return history_item_from_viewer_path(context, rel_path)


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
            "delete": bool(item and not has_file),
        },
    }


def _build_saved_result_asset_payload(context: WebSessionContext, rel_path: str) -> dict[str, Any] | None:
    item = history_item_from_viewer_path(context, rel_path)
    target = validate_viewer_path(context, rel_path)
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
    item_file = Path(str(getattr(item, "filepath", "") or "")) if item else None
    item_has_file = bool(item_file and item_file.is_file())
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
        "file_path": str(target) if target is not None else (str(item_file) if item_has_file else ""),
        "label": target.name if target is not None else (item_file.name if item_has_file else getattr(item, "filename", "History Image")),
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
            "open_file": bool(target or item_has_file),
            "save_image": True,
            "copy_png": True,
            "image_action": bool(item and nai_mode),
            "upscale_nai": nai_mode,
            "enhance": can_enhance,
            "inpaint": False,
            "character_reference": False,
            "remote_event": False,
            "delete": bool(item and not item_has_file),
        },
    }


def resolve_result_image_action_source(
    context: WebSessionContext,
    payload: dict[str, Any] | None,
) -> tuple[bytes, str, dict[str, Any], dict[str, Any]]:
    payload = payload if isinstance(payload, dict) else {}
    source = str(payload.get("source") or "").strip().lower()
    rel_path = str(payload.get("path") or "").strip()
    file_path = str(payload.get("file_path") or payload.get("filePath") or "").strip()
    label = str(payload.get("label") or rel_path or file_path or "Result Image")

    item = history_item_from_viewer_path(context, rel_path) if rel_path else None
    if item is None and (source in {"", "current"} or not rel_path):
        item = context.result_store.latest_item
    if item is not None:
        png_bytes, _ = result_images.history_item_png_payload(item, label=getattr(item, "filename", "") or label)
        generation_params = dict(getattr(item, "generation_params", {}) or {})
        prompt_context = dict(getattr(item, "prompt_context", {}) or {})
        return png_bytes, label or getattr(item, "filename", "") or "Result Image", generation_params, prompt_context

    target = validate_viewer_path(context, rel_path)
    if target is None and file_path:
        candidate = Path(file_path)
        try:
            if candidate.is_file():
                target = candidate
        except Exception:
            target = None
    if target is not None:
        png_bytes, _ = result_images.image_file_to_png_payload(target)
        return png_bytes, label or target.name, {}, {}

    if source in {"", "current"}:
        png_bytes, _ = context.result_store.current_png_payload()
        return png_bytes, label or "Current Result", {}, {}

    raise FileNotFoundError("Result image is unavailable")


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


def register_result_display_routes(
    app: FastAPI,
    session_context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
    clients: set[Any],
    broadcast_json: JsonBroadcaster,
) -> None:

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
            item = history_item_from_viewer_path(session_context, path)
            target = validate_viewer_path(session_context, path)
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
        item = history_item_from_viewer_path(session_context, path)
        target = validate_viewer_path(session_context, path)
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
            image_bytes, media_type = await run_in_thread(_fetch_remote_image)
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
            return await run_in_thread(_extract)
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
            opened = await run_in_thread(_open_folder)
            return {"ok": True, "path": opened}
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

    @app.post("/api/viewer/open-folder")
    async def api_viewer_open_folder():
        return await api_history_open_folder()

    @app.get("/api/viewer/list")
    async def api_viewer_list(page: int = 0, per_page: int = 30, scope: str = "memory"):
        page = max(0, int(page or 0))
        per_page = min(100, max(1, int(per_page or 30)))
        if str(scope or "").lower() in {"disk", "saved", "all"}:
            entries = await run_in_thread(_scan_viewer_folder, session_context)
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
        item = history_item_from_viewer_path(session_context, path)
        target = validate_viewer_path(session_context, path)
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
        item = history_item_from_viewer_path(session_context, path)
        target = validate_viewer_path(session_context, path)
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
        item = history_item_from_viewer_path(session_context, path)
        target = validate_viewer_path(session_context, path)
        if item is not None:
            return session_context.result_store.history_meta_payload(item.history_id, include_full=full)
        if target is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        try:
            return await run_in_thread(_metadata_for_disk_image, target, target.name, full)
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
    async def api_result_action_save(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        item = history_item_from_action_payload(session_context, payload)
        if item is None:
            return JSONResponse({"ok": False, "error": "History item not found"}, status_code=400)
        try:
            result = await run_in_thread(session_context.save_history_item, item)
            asset = _build_saved_result_asset_payload(session_context, item.rel_path)
            await broadcast_json(clients, session_context.auto_save_state_payload())
            return {"ok": True, **result, "asset": asset}
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

    @app.post("/api/result/action/delete")
    async def api_result_action_delete(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        item = history_item_from_action_payload(session_context, payload)
        if item is None:
            return JSONResponse({"ok": False, "error": "History item not found"}, status_code=400)

        def _delete_item():
            file_path = str(getattr(item, "filepath", "") or "")
            deleted_file = False
            if file_path:
                target = Path(file_path)
                if target.is_file():
                    target.unlink()
                    deleted_file = True
            removed = session_context.result_store.remove_item(item)
            if removed is None:
                raise FileNotFoundError("History item not found")
            return removed, deleted_file, file_path

        try:
            removed, deleted_file, file_path = await run_in_thread(_delete_item)
            removed_payload = session_context.result_store.viewer_removed_payload(removed)
            await broadcast_json(clients, removed_payload)
            await broadcast_json(clients, session_context.auto_save_state_payload())
            return {
                "ok": True,
                "deleted": True,
                "rel_path": removed.rel_path,
                "history_id": removed.history_id,
                "file_path": file_path,
                "deleted_file": deleted_file,
                "total": removed_payload["total"],
                "remaining": session_context.result_store.unsaved_history_count(),
            }
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

    @app.post("/api/image-action/{action}")
    async def api_image_action(action: str, req: Request):
        action = (action or "").strip().lower()
        if action not in {"img2img", "inpaint", "vibe", "danbooru"}:
            return JSONResponse({"error": "Unsupported action"}, status_code=400)
        image_bytes = await req.body()
        if not image_bytes:
            return JSONResponse({"error": "No image data"}, status_code=400)
        if len(image_bytes) > 64 * 1024 * 1024:
            return JSONResponse({"error": "Image is too large"}, status_code=413)
        label = (req.query_params.get("label") or "Input Image")[:120]
        try:
            if action in {"img2img", "inpaint"}:
                if session_context.get_api_mode() != "NAI":
                    return JSONResponse({"error": "Img2Img/Inpaint is available in NAI mode only"}, status_code=403)
                state = await run_in_thread(
                    session_context.open_img2img_session_from_bytes,
                    image_bytes,
                    label=label,
                    mode=action,
                )
                await broadcast_json(clients, state)
                return {
                    "ok": True,
                    "action": action,
                    "state": state,
                    "message": f"{'Inpaint' if action == 'inpaint' else 'Img2Img'} session ready",
                }
            if action == "vibe":
                if session_context.get_api_mode() != "NAI":
                    return JSONResponse({"error": "Vibe Transfer is available in NAI mode only"}, status_code=403)
                module_state = await run_in_thread(
                    session_context.set_module_param,
                    "vibe_transfer",
                    "upload_image",
                    base64.b64encode(image_bytes).decode("ascii"),
                )
                if isinstance(module_state, dict):
                    await broadcast_json(clients, module_state)
                return {
                    "ok": True,
                    "action": action,
                    "state": module_state,
                    "message": "Vibe Transfer image added",
                }
        except Exception as exc:
            return JSONResponse({"error": f"Image action failed: {exc}"}, status_code=500)
        return JSONResponse({
            "error": "Danbooru image interrogation is not available in the headless runtime yet.",
            "headless": True,
        }, status_code=400)
