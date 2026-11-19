"""Headless preset bench endpoints."""
from __future__ import annotations

import threading

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

from app.backend.server.install_manager_routes import runtime_install_manager
from core.preset_bench_service import PresetBenchService


_SERVICE_LOCK = threading.Lock()
_STATUS_FIELDS = ("installed", "name", "count", "kinds", "template_version", "quality", "downloading", "progress")


def preset_bench_service(context):
    with _SERVICE_LOCK:
        service = getattr(context, "preset_bench_service", None)
        if service is None:
            service = PresetBenchService(context.runtime_paths)
            context.preset_bench_service = service
        return service


def register_preset_bench_routes(app: FastAPI, session_context, *, run_in_thread, clients, start_generation_runner):
    async def query(method, *args):
        try:
            return await run_in_thread(method, *args)
        except KeyError as exc:
            raise HTTPException(404, "Preset item not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/presets/catalog")
    async def catalog(kind: str, pool: str):
        return await query(preset_bench_service(session_context).catalog, kind, pool)

    @app.get("/api/presets/sets")
    async def sets(kind: str, pool: str, seed: str):
        return await query(preset_bench_service(session_context).sets, kind, pool, seed)

    @app.get("/api/presets/search")
    async def search(q: str, kind: str | None = None):
        return await query(preset_bench_service(session_context).search, q, kind, getattr(session_context, "kr_tags_raw", None))

    @app.get("/api/presets/thumb/{key}")
    async def thumbnail(key: str, req: Request):
        etag, image = await query(preset_bench_service(session_context).thumbnail, key, req.headers.get("if-none-match"))
        headers = {"ETag": etag, "Cache-Control": "private, max-age=86400"}
        if image is None:
            return Response(status_code=304, headers=headers)
        return Response(content=image, media_type="image/webp", headers=headers)

    @app.get("/api/presets/thumb-pack/status")
    async def thumb_pack_status():
        snapshot = await run_in_thread(runtime_install_manager(session_context).snapshot)
        return {key: snapshot["preset_thumbs"][key] for key in _STATUS_FIELDS}

    @app.get("/api/presets/outfit-related")
    async def outfit_related(tag: str, pool: str = "female", ctx: str = ""):
        context = [t.strip() for t in ctx.split("|") if t.strip()]
        return await query(preset_bench_service(session_context).related, tag, pool, context)
