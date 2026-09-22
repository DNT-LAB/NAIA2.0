"""Boost v2(llama.cpp) 상태 · 모델 다운로드 라우트.

설정 저장은 PE 모듈 경로(``set_module_param('prompt_engineering', 'boost_v2_settings', …)``)가
맡고, 여기는 폴링이 필요한 것(상태·다운로드 진행)만 둔다. 모델 다운로드(3.1 GiB)와 엔진 내리기는
NAIA 가 도는 PC 에서만 — Ollama pull 과 같은 루프백 가드.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.backend.server.install_manager_routes import _is_local_request


def _loopback_only() -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": "Boost 모델 다운로드·엔진 제어는 NAIA 가 실행 중인 PC 에서만 가능합니다."},
        status_code=403,
    )


def register_boost_v2_routes(
    app: FastAPI,
    context: Any,
    *,
    run_in_thread: Callable[..., Awaitable[Any]],
) -> None:
    from app.backend.server.boost_v2_service import (
        boost_v2_status,
        get_model_downloader,
        stop_boost_runtime,
    )

    @app.get("/api/boost-v2/status")
    async def boost_v2_status_route():
        return await run_in_thread(boost_v2_status, context)

    @app.post("/api/boost-v2/model/download")
    async def boost_v2_model_download(request: Request):
        if not _is_local_request(request):
            return _loopback_only()
        return await run_in_thread(get_model_downloader(context).start)

    @app.post("/api/boost-v2/model/download/cancel")
    async def boost_v2_model_download_cancel(request: Request):
        if not _is_local_request(request):
            return _loopback_only()
        return await run_in_thread(get_model_downloader(context).cancel)

    @app.post("/api/boost-v2/unload")
    async def boost_v2_unload(request: Request):
        if not _is_local_request(request):
            return _loopback_only()
        await run_in_thread(stop_boost_runtime, context)
        return {"ok": True}
