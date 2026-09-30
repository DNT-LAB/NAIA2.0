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

    def remember(what, exc):
        # 설치 쪽 요청(검사 · 설치 · 엔진 켜기 …)의 실패 - 진단 정보(마지막 요청 오류)에 Traceback 까지. except 안에서.
        if what:
            try:
                service_for(context).remember_error(what, exc)
            except Exception:   # 기억하다 실패해도 응답은 그대로
                pass

    async def call(request, action, *, local=False, body=False, png=False, missing_404=False, what=None):
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
            remember(what, exc)
            code = exc.code
            status = 422 if code in ("PARAM_OUT_OF_RANGE", "PATH_INVALID", "PATH_NOT_WRITABLE", "LORA_NOT_FOUND", "LORA_INVALID", "LORA_NAME_CONFLICT", "LORA_THUMB_INVALID", "LORA_KEYWORD_INVALID") else 409
            if missing_404 and code in ("LORA_NOT_FOUND", "HISTORY_NOT_FOUND"):
                status = 404
            if code.startswith("ENGINE_START"):
                status = 500
            return JSONResponse({"ok": False, "code": code, "error": str(exc), "detail": getattr(exc, "detail", "")}, status_code=status)
        except (ValueError, TypeError) as exc:
            remember(what, exc)
            return JSONResponse({"ok": False, "code": "PARAM_OUT_OF_RANGE", "error": "요청 형식을 확인해 주세요."}, status_code=422)
        except OSError as exc:
            remember(what, exc)
            return JSONResponse({"ok": False, "code": "PATH_NOT_WRITABLE", "error": "파일 또는 폴더에 접근하지 못했습니다.", "detail": str(exc)}, status_code=422)
        except Exception as exc:
            # 예기치 않은 오류 - 예전엔 FastAPI 의 500(글자 없음)이라 화면에 '요청 실패 (500)' 뿐이었다. 어디서 났는지는 진단 정보에.
            remember(what, exc)
            return JSONResponse({"ok": False, "code": "INTERNAL_ERROR", "detail": f"{type(exc).__name__}: {exc}",
                                 "error": "예기치 않은 오류가 났습니다 - [자세히] 에서 확인해 주세요."}, status_code=500)

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
        return await call(request, service_for(context).inspect, local=True, body=True, what="PC 검사")

    @app.post("/api/anima-engine/prepare")
    async def prepare(request: Request):
        return await call(request, service_for(context).prepare, local=True, body=True, what="설치")

    @app.post("/api/anima-engine/cancel")
    async def cancel(request: Request):
        return await call(request, lambda _: service_for(context).cancel(), local=True, what="설치 취소")

    @app.post("/api/anima-engine/select")
    async def select(request: Request):
        return await call(request, lambda data: service_for(context).select(data.get("engine")), body=True, what="엔진 선택")

    @app.post("/api/anima-engine/engine/start")
    async def start(request: Request):
        return await call(request, lambda _: service_for(context).start_engine(), local=True, what="엔진 켜기")

    @app.post("/api/anima-engine/engine/stop")
    async def stop(request: Request):
        return await call(request, lambda _: service_for(context).stop_engine(), local=True, what="엔진 끄기")

    @app.get("/api/anima-engine/loras")
    async def loras():
        return await run_in_thread(service_for(context).loras)

    @app.put("/api/anima-engine/loras")
    async def put_loras(request: Request):
        return await call(request, lambda data: service_for(context).put_loras(data.get("chain")), body=True)

    @app.put("/api/anima-engine/loras/keyword")
    async def put_keyword(request: Request):
        # LoRA 예약어 - 체인 저장처럼 원격 기기도(사용자 데이터 · 이 PC 의 파일은 안 건드린다). 겹침 = 409
        return await call(request, service_for(context).put_keyword, body=True, missing_404=True)

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

    @app.get("/api/anima-engine/loras/history")
    async def lora_history(request: Request, name: str = ""):
        # PNG 칸의 [히스토리] - 이 LoRA 를 켜고 만든 그림이 앞(읽기만 · 원격 기기도 - PNG 넣기와 같다)
        return await call(request, lambda _: service_for(context).history_candidates(name))

    @app.post("/api/anima-engine/loras/thumb/history")
    async def put_thumb_from_history(request: Request):
        return await call(request, service_for(context).thumb_from_history, body=True, missing_404=True)

    @app.post("/api/anima-engine/loras/open-folder")
    async def open_folder(request: Request):
        # Folder opening follows artist-thumb's local-PC rule, without the install/tunnel gate.
        if not _is_local_request(request):
            return JSONResponse({"ok": False, "code": "LOCAL_ONLY", "error": "폴더 열기는 로컬 PC에서만 가능합니다."}, status_code=403)
        return await call(request, service_for(context).open_lora_folder, body=True, missing_404=True)

    @app.get("/api/anima-engine/models")
    async def models():
        # PARAMS Model 줄 [Manage] - 고를 수 있는 모델 · 모델 폴더(읽기만 · 원격 기기도)
        return await run_in_thread(service_for(context).models)

    @app.post("/api/anima-engine/models/refresh")
    async def refresh_models(request: Request):
        # [새로고침] - 원격 기기도(폴더를 다시 보고 켜진 엔진에게 목록을 다시 묻는다). 엔진을 내리는 것은 이 PC 에서만
        host = request.client.host if request.client else ""
        local = _is_local_request(request) and context.setup_gate(host)[0]
        return await call(request, lambda data: service_for(context).refresh_models(data, may_restart=local), body=True)

    @app.post("/api/anima-engine/models/open-folder")
    async def open_model_folder(request: Request):
        # LoRA 폴더 열기와 같은 규칙(이 PC 에서만 - 설치 · 터널 문은 안 본다)
        if not _is_local_request(request):
            return JSONResponse({"ok": False, "code": "LOCAL_ONLY", "error": "폴더 열기는 로컬 PC에서만 가능합니다."}, status_code=403)
        return await call(request, service_for(context).open_model_folder, body=True)

    @app.post("/api/anima-engine/settings")
    async def settings(request: Request):
        return await call(request, service_for(context).update_settings, local=True, body=True, what="설정 바꾸기")

    def since_of(raw):
        return None if raw in (None, "") else max(0, int(raw))      # 숫자가 아니면 ValueError -> 422

    @app.get("/api/anima-engine/engine/log")
    async def engine_log(request: Request):
        # 엔진이 켜지는 동안의 ComfyUI 출력 - 생성 화면의 임시 콘솔(읽기만 · 원격 기기도 - 상태 조회와 같다)
        raw = request.query_params.get("since")
        return await call(request, lambda _: service_for(context).engine_log(since_of(raw)))

    @app.get("/api/anima-engine/diagnostics")
    async def diagnostics(request: Request):
        # 실패 화면의 [자세히] · [에러 로그 복사] - nvidia-smi · 그래픽 카드 조회를 이 PC 에서 돌린다(검사와 같은 로컬 규칙)
        return await call(request, lambda _: service_for(context).diagnostics(), local=True)
