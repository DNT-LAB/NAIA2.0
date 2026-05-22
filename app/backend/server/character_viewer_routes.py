from __future__ import annotations

import io
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from core.character_viewer_service import CharacterViewerService
from core.headless_generation_service import HeadlessGenerationService
from core.web_session_context import WebSessionContext


AsyncRunner = Callable[..., Awaitable[Any]]
GenerationRunnerStarter = Callable[[WebSessionContext, set[Any]], None]


def character_viewer_service(context: WebSessionContext) -> CharacterViewerService:
    service = getattr(context, "character_viewer_service", None)
    if service is None:
        save_root = context.runtime_paths.save_dir if context.runtime_paths is not None else None
        service = CharacterViewerService(context.repo_root, save_root=save_root)
        context.character_viewer_service = service
    return service


def _generation_service(context: WebSessionContext) -> HeadlessGenerationService:
    service = getattr(context, "headless_generation_service", None)
    if service is None:
        service = HeadlessGenerationService(context)
        context.headless_generation_service = service
    return service


def _image_media_type(image_bytes: bytes) -> str:
    if image_bytes.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def character_viewer_thumbnail_payload(
    context: WebSessionContext,
    group: str,
    character: str,
    variant: str = "",
    size: str = "",
) -> tuple[bytes, str]:
    service = character_viewer_service(context)
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


def register_character_viewer_routes(
    app: FastAPI,
    session_context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
    clients: set[Any],
    start_generation_runner: GenerationRunnerStarter,
) -> None:
    @app.get("/api/character-viewer/state")
    async def api_character_viewer_state():
        try:
            state = await run_in_thread(character_viewer_service(session_context).state)
            state["generation_delay_ms"] = 500
            return state
        except Exception as exc:
            return JSONResponse({"error": f"Character Viewer state failed: {exc}"}, status_code=500)

    @app.get("/api/character-viewer/groups")
    async def api_character_viewer_groups(query: str = ""):
        try:
            return await run_in_thread(character_viewer_service(session_context).build_groups, query)
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
            return await run_in_thread(
                character_viewer_service(session_context).build_list,
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
            return await run_in_thread(
                character_viewer_service(session_context).build_detail,
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
            return await run_in_thread(
                character_viewer_service(session_context).build_prompt,
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
            return await run_in_thread(character_viewer_service(session_context).save_options, payload)
        except Exception as exc:
            return JSONResponse({"error": f"Character Viewer options failed: {exc}"}, status_code=500)

    @app.get("/api/character-viewer/thumbnail")
    async def api_character_viewer_thumbnail(group: str = "", character: str = "", variant: str = "", size: str = ""):
        try:
            image_bytes, media_type = await run_in_thread(
                character_viewer_thumbnail_payload,
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
            overrides = await run_in_thread(
                character_viewer_service(session_context).build_generation_overrides,
                payload,
                session_context.get_api_mode(),
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        dispatch = await run_in_thread(
            _generation_service(session_context).enqueue_remote_request,
            {"type": "generate", "overrides": overrides},
        )
        if not dispatch.ok:
            return JSONResponse(dispatch.websocket_payload(), status_code=409)
        if session_context.headless_generation_execute_enabled:
            start_generation_runner(session_context, clients)
        return {"ok": True, **dispatch.websocket_payload()}
