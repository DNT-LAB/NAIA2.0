from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from core.web_session_context import WebSessionContext
from core.headless_payload_utils import is_loopback_host
from core.ref_vibe_library import LibraryError, get_ref_vibe_library


AsyncRunner = Callable[..., Awaitable[Any]]


def _safe_name(value: str) -> str:
    name = Path(str(value or "").strip()).name
    return "" if name in {"", ".", ".."} else name


def _thumbnail_cache(context: WebSessionContext) -> dict[tuple[str, int, int], bytes]:
    cache = getattr(context, "module_storage_thumbnail_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        context.module_storage_thumbnail_cache = cache
    return cache


def _thumbnail_payload(context: WebSessionContext, image_path: Path) -> bytes:
    stat = image_path.stat()
    cache_key = (str(image_path), int(stat.st_mtime_ns), int(stat.st_size))
    cache = _thumbnail_cache(context)
    cached = cache.get(cache_key)
    if isinstance(cached, bytes):
        return cached

    from PIL import Image

    with Image.open(image_path) as image:
        image.load()
        thumb = image.convert("RGB")
        thumb.thumbnail((256, 256), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        thumb.save(buffer, "WEBP", quality=78, method=4)
    payload = buffer.getvalue()
    if len(cache) > 256:
        cache.clear()
    cache[cache_key] = payload
    return payload


def _character_reference_thumb(context: WebSessionContext, file_hash: str) -> bytes:
    safe_hash = _safe_name(file_hash)
    if not safe_hash:
        raise FileNotFoundError("Character Reference thumbnail not found")
    image_path = context._existing_save_path("character_reference", "images", f"{safe_hash}.png")
    if not image_path.exists():
        raise FileNotFoundError("Character Reference thumbnail not found")
    return _thumbnail_payload(context, image_path)


def _vibe_transfer_thumb(context: WebSessionContext, model: str, file_hash: str) -> bytes:
    safe_model = _safe_name(model)
    safe_hash = _safe_name(file_hash)
    if not safe_model or not safe_hash:
        raise FileNotFoundError("Vibe Transfer thumbnail not found")
    image_path = context._existing_save_path("vibe_transfer", safe_model, "images", f"{safe_hash}.png")
    if not image_path.exists():
        raise FileNotFoundError("Vibe Transfer thumbnail not found")
    return _thumbnail_payload(context, image_path)


def register_module_storage_routes(
    app: FastAPI,
    session_context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
) -> None:
    async def library_call(method, *args, **kwargs):
        def work():
            library = get_ref_vibe_library(session_context)
            return getattr(library, method)(*args, **kwargs)

        try:
            return JSONResponse(await run_in_thread(work))
        except LibraryError as exc:
            return JSONResponse({"error": str(exc)}, status_code=exc.status)

    @app.get("/api/ref-vibe/library")
    async def api_ref_vibe_library(kind: str, model: str = "", filter: str = "all", category_id: str = "",
                                   q: str = "", sort: str = "recent", offset: int = 0, limit: int = 60):
        return await library_call("list_items", kind, model=model, filter=filter, category_id=category_id,
                                  q=q, sort=sort, offset=offset, limit=limit)

    @app.post("/api/ref-vibe/library/item")
    async def api_ref_vibe_item(body: dict):
        return await library_call("edit_item", body.get("kind"), body.get("file_hash"),
                                  model=body.get("model", ""),
                                  **{k: body[k] for k in ("name", "favorite") if k in body})

    @app.post("/api/ref-vibe/library/category")
    async def api_ref_vibe_category(body: dict):
        return await library_call("change_category", body.get("kind"), body.get("op"),
                                  category_id=body.get("category_id", ""), name=body.get("name", ""),
                                  order=body.get("order"), model=body.get("model", ""))

    @app.post("/api/ref-vibe/library/move")
    async def api_ref_vibe_move(body: dict):
        return await library_call("move_items", body.get("kind"), body.get("file_hashes"),
                                  category_id=body.get("category_id", ""), model=body.get("model", ""))

    async def clusters_call(method, *args):
        from core.ref_vibe_clusters import get_ref_vibe_clusters

        def work():
            return getattr(get_ref_vibe_clusters(session_context), method)(*args)

        try:
            return JSONResponse(await run_in_thread(work))
        except LibraryError as exc:
            return JSONResponse({"error": str(exc)}, status_code=exc.status)

    @app.get("/api/ref-vibe/clusters")
    async def api_ref_vibe_clusters():
        return await clusters_call("list_clusters")

    @app.post("/api/ref-vibe/clusters")
    async def api_ref_vibe_change_cluster(request: Request, body: dict):
        if body.get("op") == "delete" and not is_loopback_host(request.client.host if request.client else ""):
            return JSONResponse({"error": "Cluster deletion is loopback only"}, status_code=403)
        return await clusters_call("change_cluster", body)

    @app.post("/api/ref-vibe/library/delete")
    async def api_ref_vibe_delete(request: Request, body: dict):
        if not is_loopback_host(request.client.host if request.client else ""):
            return JSONResponse({"error": "Storage deletion is loopback only"}, status_code=403)
        if body.get("kind") != "character_reference":
            return JSONResponse({"error": "Use Vibe delete_storage for vibe items"}, status_code=400)
        return await library_call("delete_character", body.get("file_hash"))

    @app.get("/api/module-storage/character-reference/thumb")
    async def api_character_reference_storage_thumb(file_hash: str = ""):
        try:
            payload = await run_in_thread(_character_reference_thumb, session_context, file_hash)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Character Reference thumbnail failed: {exc}"}, status_code=500)
        return Response(
            content=payload,
            media_type="image/webp",
            headers={"Cache-Control": "private, max-age=3600"},
        )

    @app.get("/api/module-storage/vibe/thumb")
    async def api_vibe_transfer_storage_thumb(model: str = "", file_hash: str = ""):
        try:
            payload = await run_in_thread(_vibe_transfer_thumb, session_context, model, file_hash)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Vibe Transfer thumbnail failed: {exc}"}, status_code=500)
        return Response(
            content=payload,
            media_type="image/webp",
            headers={"Cache-Control": "private, max-age=3600"},
        )
