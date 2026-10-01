"""외부 ComfyUI(API 모드) 서버 출력 - Generate 콘솔(app/web/remote/js/features/comfyServerConsole.mjs)이 읽는다.

읽기만 한다(원격 기기도 - 관리형 /api/anima-engine/engine/log 와 같은 규칙). 외부 서버를 켜거나 끄지 않고, 화면이 준 URL 을
열지 않는다(저장된 comfyui_url 만 - comfyui_server_log_service).
"""
from fastapi import Request
from fastapi.responses import JSONResponse

from app.backend.server.comfyui_server_log_service import server_log_payload


def register_comfyui_server_log_routes(app, context, *, run_in_thread):
    @app.get("/api/comfyui/server-log")
    async def comfyui_server_log(request: Request):
        # since 없음 = 지금부터(기준선) · fresh=1 = 간격과 관계없이 지금 서버를 읽는다(생성이 끝난 뒤의 마지막 조회)
        raw = request.query_params.get("since")
        try:
            since = None if raw in (None, "") else max(0, int(raw))
        except ValueError:
            return JSONResponse({"ok": False, "code": "PARAM_OUT_OF_RANGE", "error": "since 는 숫자여야 합니다."},
                                status_code=422)
        fresh = request.query_params.get("fresh") in ("1", "true")
        return await run_in_thread(server_log_payload, context, since, fresh)
