from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response

from core.style_thumbnail_service import StyleThumbnailService
from core.web_session_context import WebSessionContext


AsyncRunner = Callable[..., Awaitable[Any]]


def style_thumbnail_service(context: WebSessionContext) -> StyleThumbnailService:
    service = getattr(context, "style_thumbnail_service", None)
    if service is None:
        service = StyleThumbnailService(context.repo_root)
        context.style_thumbnail_service = service
    return service


def register_style_thumbnail_routes(
    app: FastAPI,
    session_context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
) -> None:
    @app.get("/api/thumb/state")
    async def api_thumb_state():
        try:
            return await run_in_thread(style_thumbnail_service(session_context).state)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Thumb state failed: {exc}"}, status_code=500)

    @app.get("/api/thumb/category/{category_key}")
    async def api_thumb_category(category_key: str):
        try:
            return await run_in_thread(style_thumbnail_service(session_context).category_payload, category_key)
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Thumb category failed: {exc}"}, status_code=500)

    @app.get("/api/thumb/image")
    async def api_thumb_image(tag: str = ""):
        try:
            image_bytes, media_type = await run_in_thread(style_thumbnail_service(session_context).image_payload, tag)
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
