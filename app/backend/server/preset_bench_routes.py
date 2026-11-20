"""Headless preset bench endpoints."""
from __future__ import annotations

import threading

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from app.backend.server.install_manager_routes import runtime_install_manager
from core.preset_bench_generation import DirectSettingsStore, export_direct_base, generation_commands, preset_bench_bases
from core.preset_bench_service import ALL_POOLS, PresetBenchService, name_subject


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

    # pool 을 비우면 그 갈래의 모든 풀(벤치는 인원 선택 없이 이것만 쓴다).
    @app.get("/api/presets/catalog")
    async def catalog(kind: str, pool: str = ALL_POOLS):
        return await query(preset_bench_service(session_context).catalog, kind, pool)

    @app.get("/api/presets/sets")
    async def sets(kind: str, seed: str, pool: str = ALL_POOLS):
        return await query(preset_bench_service(session_context).sets, kind, pool, seed)

    @app.get("/api/presets/bench/subject")
    async def subject(text: str = ""):
        from app.backend.server.character_viewer_routes import character_viewer_service

        return await query(lambda: name_subject(text, character_viewer_service(session_context).find_by_tag))

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

    @app.get("/api/presets/bench/bases")
    async def bases():
        return await query(preset_bench_bases, session_context)

    @app.get("/api/presets/bench/direct")
    async def direct_list():
        return await query(DirectSettingsStore(session_context.runtime_paths).list_items)

    @app.put("/api/presets/bench/direct/{name:path}")
    async def direct_put(name: str, payload: dict):
        return await query(DirectSettingsStore(session_context.runtime_paths).put, name, payload)

    @app.delete("/api/presets/bench/direct/{name:path}")
    async def direct_delete(name: str):
        return await query(DirectSettingsStore(session_context.runtime_paths).delete, name)

    @app.post("/api/presets/bench/direct/export")
    async def direct_export(payload: dict):
        ok, message = await query(export_direct_base, session_context, payload)
        if not ok:
            return JSONResponse({"error": message}, status_code=409)
        return {"ok": True, "name": message}

    @app.post("/api/presets/bench/generate")
    async def generate(payload: dict):
        from app.backend.server.generation_commands import generation_service
        from core.generation_access_policy import access_policy
        from core.headless_generation_service import HeadlessGenerationDispatch

        if session_context.get_api_mode() != "NAI":
            return JSONResponse({"error": "NAI 모드에서만 생성할 수 있습니다"}, status_code=409)
        request_id, commands = await query(generation_commands, session_context, payload)
        service = generation_service(session_context)
        policy = access_policy(session_context)
        if policy.blocked or not service._credential_for_mode("NAI"):
            reason = policy.reason() if policy.blocked else "NAI credential is not configured."
            blocked = HeadlessGenerationDispatch(None, "NAI", reason).websocket_payload()
            return JSONResponse({**blocked, "queued": 0, "requests": []}, status_code=409)

        requests = []
        try:
            for candidate, command in enumerate(commands):
                dispatch = await run_in_thread(service.enqueue_remote_request, command)
                result = dispatch.websocket_payload()
                if not dispatch.ok:
                    return JSONResponse({**result, "queued": len(requests), "requests": requests}, status_code=409)
                requests.append({"candidate": candidate, "request_id": result["request_id"]})
        finally:
            if requests and session_context.headless_generation_execute_enabled:
                start_generation_runner(session_context, clients)
        return {"ok": True, "request_id": request_id, "queued": len(requests), "requests": requests}
