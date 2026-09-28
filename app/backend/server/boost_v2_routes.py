"""앱 llama-server(Boost v2 · Assist v2 공용) 상태 · 모델 다운로드 라우트.

설정 저장(모델 · 할당 장치 포함)은 PE 모듈 경로(``set_module_param('prompt_engineering', 'boost_v2_settings', …)``)가
맡고, 여기는 폴링이 필요한 것(상태·다운로드 진행)만 둔다. 모델 다운로드(3~14 GB)와 엔진 내리기는
NAIA 가 도는 PC 에서만 — install-manager 와 같은 루프백 가드.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.backend.server.install_manager_routes import _is_local_request


async def _model_id(request: Request) -> str | None:
    """본문 {"model": "e4b"} — 없으면(옛 화면) 설정에서 고른 모델."""
    try:
        body = await request.json()
    except Exception:
        return None
    return str(body.get("model") or "") or None if isinstance(body, dict) else None


def _loopback_only() -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": "AI 모델 다운로드·엔진 제어는 NAIA 가 실행 중인 PC 에서만 가능합니다."},
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
        cancel_model_download,
        get_boost_runtime,
        get_engine_installer,
        prime_runtime,
        release_boost_runtime,
        start_model_download,
        stop_boost_runtime,
        warm_boost_runtime,
    )

    def _on_auto_boost_changed(*args: Any) -> None:
        """Auto Boost 토글(PE 서비스가 publish) — 켤 때 엔진을 미리 올리고(첫 Random 이 로드를 안 기다리게), 끌 때
        Boost 의 임대를 놓는다(아무도 안 쥐면 바로 내린다 — Assist 가 방금 썼으면 그 임대가 끝날 때).
        옛 ollama_routes 에 있던 구독의 v2 몫이다(Ollama 상주 관리는 회수, 2026-09-26)."""
        enabled = bool(getattr(context, "ollama_auto_boost", False))
        if args and isinstance(args[0], dict) and "enabled" in args[0]:
            enabled = bool(args[0]["enabled"])
        try:
            if enabled:
                warm_boost_runtime(context)
            else:
                release_boost_runtime(context)
        except Exception:
            pass

    try:
        context.subscribe("ollama_auto_boost_changed", _on_auto_boost_changed)
    except Exception:
        pass

    def _on_device_changed(*_args: Any) -> None:
        """할당 장치나 모델을 바꿨다 — Auto Boost 가 켜져 있으면 새 설정으로 곧바로 다시 띄운다(도는 요청은 끝까지 간 뒤).
        꺼져 있으면 떠 있던 옛 엔진만 정리한다(다음에 켤 때 새 장치로 뜬다). 어느 쪽이든 새 모델 · 장치는 한 번
        태워 둔다(처음이면 셰이더 준비로 첫 요청이 수십 초 — prime_runtime)."""
        try:
            if getattr(context, "ollama_auto_boost", False):
                warm_boost_runtime(context)
            elif getattr(context, "boost_llama_runtime", None) is not None:
                get_boost_runtime(context)  # configure -> 옛 설정의 엔진이 놀고 있으면 내린다
            prime_runtime(context)
        except Exception:
            pass

    try:
        context.subscribe("boost_v2_device_changed", _on_device_changed)
    except Exception:
        pass

    @app.get("/api/boost-v2/status")
    async def boost_v2_status_route():
        return await run_in_thread(boost_v2_status, context)

    @app.post("/api/boost-v2/model/download")
    async def boost_v2_model_download(request: Request):
        if not _is_local_request(request):
            return _loopback_only()
        model_id = await _model_id(request)
        result = await run_in_thread(start_model_download, context, model_id)
        return result if result.get("ok") else JSONResponse(result, status_code=409)

    @app.post("/api/boost-v2/model/download/cancel")
    async def boost_v2_model_download_cancel(request: Request):
        if not _is_local_request(request):
            return _loopback_only()
        return await run_in_thread(cancel_model_download, context)

    @app.post("/api/boost-v2/engine/download")
    async def boost_v2_engine_download(request: Request):
        """엔진이 동봉되지 않은 설치(소스 체크아웃)에서 공식 llama.cpp Vulkan 판(35 MB, 해시 고정)을 받는다."""
        if not _is_local_request(request):
            return _loopback_only()
        return await run_in_thread(get_engine_installer(context).start)

    @app.post("/api/boost-v2/unload")
    async def boost_v2_unload(request: Request):
        if not _is_local_request(request):
            return _loopback_only()
        result = await run_in_thread(stop_boost_runtime, context)
        return {"ok": True, **(result or {})}
