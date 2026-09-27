"""Managed ANIMA HTTP contract. Host-side mutations require both setup guards."""
from fastapi import Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from app.backend.server.install_manager_routes import _is_local_request
from app.backend.server.anima_engine_service import service_for, licenses_payload
from core.anima_engine.profile import ProfileError
from core.anima_engine.runtime import ManagedEngineError
from core.anima_engine.settings import license_text, THUMB_MAX_BYTES


def register_anima_engine_routes(app, context, *, run_in_thread):
    def guard(request):
        host = request.client.host if request.client else ""
        allowed, reason = context.setup_gate(host)
        if not _is_local_request(request) or not allowed:
            return JSONResponse({"ok": False, "code": "LOCAL_ONLY", "error": reason or "이 작업은 로컬 PC에서만 가능합니다."}, status_code=403)

    async def call(request, action, *, local=False, body=False, png=False, missing_404=False):
        if local:
            denied = guard(request)
            if denied is not None:
                return denied
        try:
            data = await request.json() if body else {}
            if not isinstance(data, dict):
                raise ProfileError("PARAM_OUT_OF_RANGE", field="body")
            if png:
                if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "image/png":
                    raise ProfileError("LORA_THUMB_INVALID")
                data = bytearray()
                async for chunk in request.stream():
                    if len(data) + len(chunk) > THUMB_MAX_BYTES:
                        raise ProfileError("LORA_THUMB_INVALID")
                    data.extend(chunk)
                data = bytes(data)
            return await run_in_thread(action, data)
        except (ProfileError, ManagedEngineError) as exc:
            code = exc.code
            status = 422 if code in ("PARAM_OUT_OF_RANGE", "PATH_INVALID", "PATH_NOT_WRITABLE", "LORA_NOT_FOUND", "LORA_INVALID", "LORA_NAME_CONFLICT", "LORA_THUMB_INVALID") else 409
            if missing_404 and code == "LORA_NOT_FOUND":
                status = 404
            if code.startswith("ENGINE_START"):
                status = 500
            return JSONResponse({"ok": False, "code": code, "error": str(exc), "detail": getattr(exc, "detail", "")}, status_code=status)
        except (ValueError, TypeError):
            return JSONResponse({"ok": False, "code": "PARAM_OUT_OF_RANGE", "error": "요청 형식을 확인해 주세요."}, status_code=422)
        except OSError as exc:
            return JSONResponse({"ok": False, "code": "PATH_NOT_WRITABLE", "error": "파일 또는 폴더에 접근하지 못했습니다.", "detail": str(exc)}, status_code=422)

    @app.get("/api/anima-engine/status")
    async def status():
        return await run_in_thread(service_for(context).status)

    @app.get("/api/anima-engine/licenses")
    async def licenses():
        return licenses_payload()

    @app.get("/api/anima-engine/licenses/{id}")
    async def text(id: str):
        try:
            return PlainTextResponse(license_text(id))
        except KeyError:
            return JSONResponse({"ok": False, "error": "라이선스를 찾지 못했습니다."}, status_code=404)

    @app.post("/api/anima-engine/inspect")
    async def inspect(request: Request):
        return await call(request, service_for(context).inspect, local=True, body=True)

    @app.post("/api/anima-engine/prepare")
    async def prepare(request: Request):
        return await call(request, service_for(context).prepare, local=True, body=True)

    @app.post("/api/anima-engine/cancel")
    async def cancel(request: Request):
        return await call(request, lambda _: service_for(context).cancel(), local=True)

    @app.post("/api/anima-engine/select")
    async def select(request: Request):
        return await call(request, lambda data: service_for(context).select(data.get("engine")), body=True)

    @app.post("/api/anima-engine/engine/start")
    async def start(request: Request):
        return await call(request, lambda _: service_for(context).start_engine(), local=True)

    @app.post("/api/anima-engine/engine/stop")
    async def stop(request: Request):
        return await call(request, lambda _: service_for(context).stop_engine(), local=True)

    @app.get("/api/anima-engine/loras")
    async def loras():
        return await run_in_thread(service_for(context).loras)

    @app.put("/api/anima-engine/loras")
    async def put_loras(request: Request):
        return await call(request, lambda data: service_for(context).put_loras(data.get("chain")), body=True)

    @app.get("/api/anima-engine/loras/thumb")
    async def get_thumb(request: Request, name: str):
        # Unversioned clients must revalidate after a thumbnail is replaced.
        cache = "public, max-age=31536000, immutable" if request.query_params.get("v") else "no-cache"
        return await call(request, lambda _: Response(service_for(context).read_thumb(name), media_type="image/png",
                          headers={"Cache-Control": cache}), missing_404=True)

    @app.put("/api/anima-engine/loras/thumb")
    async def put_thumb(request: Request, name: str):
        return await call(request, lambda data: service_for(context).put_thumb(name, data), png=True, missing_404=True)

    @app.delete("/api/anima-engine/loras/thumb")
    async def delete_thumb(request: Request, name: str):
        return await call(request, lambda _: service_for(context).delete_thumb(name), missing_404=True)

    @app.post("/api/anima-engine/loras/open-folder")
    async def open_folder(request: Request):
        # Folder opening follows artist-thumb's local-PC rule, without the install/tunnel gate.
        if not _is_local_request(request):
            return JSONResponse({"ok": False, "code": "LOCAL_ONLY", "error": "폴더 열기는 로컬 PC에서만 가능합니다."}, status_code=403)
        return await call(request, service_for(context).open_lora_folder, body=True, missing_404=True)

    @app.post("/api/anima-engine/settings")
    async def settings(request: Request):
        return await call(request, service_for(context).update_settings, local=True, body=True)
