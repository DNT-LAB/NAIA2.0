"""Ollama 로컬 어시스턴트 라우트.

상태/진행률 조회(GET)는 모든 클라이언트에 열려 있다(원격 세션도 진행률을
렌더해야 함). 호스트 머신에 부작용을 일으키는 동작 — ``ollama serve`` 스폰,
수 GB 모델 다운로드, 취소 — 은 install-manager/data-migration과 동일하게
루프백 게이트를 건다: 원격 Remote Web 클라이언트가 호스트에서 프로세스를
띄우거나 대용량 다운로드를 시작할 수 없어야 한다.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.backend.server.install_manager_routes import _is_local_request
from core.ollama_assistant_service import OllamaAssistantService
from core.web_session_context import WebSessionContext

AsyncRunner = Callable[..., Awaitable[Any]]


def _loopback_only_response() -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": "Ollama 제어(서버 시작/모델 다운로드)는 NAIA가 실행 중인 PC에서만 가능합니다."},
        status_code=403,
    )


def register_ollama_routes(
    app: FastAPI,
    context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
) -> None:
    def service() -> OllamaAssistantService:
        existing = getattr(context, "ollama_assistant_service", None)
        if existing is None:
            existing = OllamaAssistantService()
            context.ollama_assistant_service = existing
        return existing

    @app.get("/api/ollama/status")
    async def ollama_status(request: Request, model: str | None = None, fresh: int = 0):
        # 서브프로세스 프로브(+HTTP)라 스레드로 — 이벤트 루프 비차단.
        # 비-루프백 클라이언트에는 호스트 인벤토리(버전/모델 목록/엔드포인트)를
        # 제외한 요약만 준다 (install-manager의 원격 새니타이즈와 동일 결정).
        # fresh=1(다시 확인 버튼)은 CLI 프로브 캐시를 우회한다.
        local = _is_local_request(request)
        return await run_in_thread(
            lambda: service().status(model, include_details=local, fresh=bool(fresh) and local)
        )

    @app.post("/api/ollama/server/start")
    async def ollama_server_start(request: Request):
        if not _is_local_request(request):
            return _loopback_only_response()
        return await run_in_thread(service().start_server)

    @app.post("/api/ollama/pull")
    async def ollama_pull(request: Request):
        if not _is_local_request(request):
            return _loopback_only_response()
        model = None
        try:
            payload = await request.json()
            if isinstance(payload, dict):
                model = payload.get("model")
        except Exception:
            model = None
        return await run_in_thread(service().start_pull, model)

    @app.get("/api/ollama/pull/status")
    async def ollama_pull_status():
        return service().pull_state()

    @app.post("/api/ollama/pull/cancel")
    async def ollama_pull_cancel(request: Request):
        if not _is_local_request(request):
            return _loopback_only_response()
        return service().cancel_pull()
