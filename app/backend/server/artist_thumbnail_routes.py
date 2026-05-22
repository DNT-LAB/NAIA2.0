from __future__ import annotations

import uuid
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from core.artist_thumbnail_service import ArtistThumbnailService
from core.headless_generation_service import HeadlessGenerationService
from core.headless_random_prompt_service import HeadlessRandomPromptService
from core.web_session_context import WebSessionContext


AsyncRunner = Callable[..., Awaitable[Any]]
GenerationRunnerStarter = Callable[[WebSessionContext, set[Any]], None]


def artist_thumbnail_service(context: WebSessionContext) -> ArtistThumbnailService:
    service = getattr(context, "artist_thumbnail_service", None)
    if service is None:
        mode_data_root = None
        runtime_paths = getattr(context, "runtime_paths", None)
        if runtime_paths is not None:
            mode_data_root = runtime_paths.ui_assets_dir / "artist_thumb"
        service = ArtistThumbnailService(
            context.repo_root,
            mode_getter=context.get_api_mode,
            mode_data_root=mode_data_root,
        )
        context.artist_thumbnail_service = service
    return service


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


def register_artist_thumbnail_routes(
    app: FastAPI,
    session_context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
    clients: set[Any],
    start_generation_runner: GenerationRunnerStarter,
) -> None:
    @app.get("/api/artist-thumb/state")
    async def api_artist_thumb_state():
        try:
            return await run_in_thread(artist_thumbnail_service(session_context).state)
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
            return await run_in_thread(
                artist_thumbnail_service(session_context).build_list,
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
            image_bytes, media_type = await run_in_thread(
                artist_thumbnail_service(session_context).image_payload,
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
            image_bytes, media_type = await run_in_thread(
                artist_thumbnail_service(session_context).favorite_image_payload,
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
            return await run_in_thread(
                artist_thumbnail_service(session_context).set_favorite,
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
            return await run_in_thread(
                artist_thumbnail_service(session_context).set_banned,
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
            return await run_in_thread(artist_thumbnail_service(session_context).save_options, payload)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb options failed: {exc}"}, status_code=500)

    @app.get("/api/artist-thumb/download")
    async def api_artist_thumb_download_state():
        try:
            return await run_in_thread(artist_thumbnail_service(session_context).download_snapshot)
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
            return await run_in_thread(artist_thumbnail_service(session_context).start_download, payload.get("mode", ""))
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb download failed: {exc}"}, status_code=500)

    @app.post("/api/artist-thumb/download/cancel")
    async def api_artist_thumb_download_cancel():
        try:
            return await run_in_thread(artist_thumbnail_service(session_context).cancel_download)
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
            peng_override = await run_in_thread(
                artist_thumbnail_service(session_context).random_prompt_override,
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
            result = await run_in_thread(
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
            overrides = await run_in_thread(
                artist_thumbnail_service(session_context).generation_overrides,
                payload,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        dispatch = await run_in_thread(
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
            start_generation_runner(session_context, clients)
        return {"ok": True, **dispatch.websocket_payload()}
