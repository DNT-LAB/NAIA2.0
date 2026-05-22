from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response

from core.web_session_context import WebSessionContext


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
