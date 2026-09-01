# -*- coding: utf-8 -*-
"""NAI V4.5 Preview 라우트 — 구도만 먼저 보는 무료 생성 한 장.

설계와 비용 근거는 `core/nai_preview_service.py` 주석에 있다. 여기서는 그 오버라이드를
**기존 생성 큐에 그대로 태운다** — 계정 분배 · 직렬화 · 실패 처리를 다시 짜지 않기
위해서다(캐릭터 에셋 벤치가 쓰는 것과 같은 통로).

⚠️ NAI 모드에서만 뜻이 있다. 다른 백엔드에서는 4.5 라는 모델이 없다.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.nai_preview_service import (
    PREVIEW_MODEL_KEY,
    PREVIEW_STEPS,
    PreviewNotFree,
    assert_free,
    build_preview_overrides,
)
from core.headless_generation_service import HeadlessGenerationService
from core.web_session_context import WebSessionContext


def _generation_service(context: WebSessionContext) -> HeadlessGenerationService:
    service = getattr(context, "headless_generation_service", None)
    if service is None:
        service = HeadlessGenerationService(context)
        context.headless_generation_service = service
    return service

AsyncRunner = Callable[..., Awaitable[Any]]


def register_nai_preview_routes(
    app: FastAPI,
    session_context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
    clients: set[Any],
    start_generation_runner: Callable[..., Any],
) -> None:

    def _build(request_id: str) -> dict[str, Any]:
        overrides = build_preview_overrides(session_context, request_id)
        # ⚠️ **마지막 문.** 여기서 걸리면 아무것도 큐에 안 들어간다.
        assert_free(session_context, overrides)
        return overrides

    @app.post("/api/nai-preview/generate")
    async def api_nai_preview_generate(req: Request):
        request_id = ""
        try:
            body = await req.json()
            request_id = str((body or {}).get("requestId") or "")
        except Exception:
            request_id = ""

        if str(session_context.get_api_mode() or "").upper() != "NAI":
            return JSONResponse(
                {"error": "Preview 는 NAI 모드에서만 사용할 수 있습니다."}, status_code=400)

        try:
            overrides = await run_in_thread(_build, request_id)
        except PreviewNotFree as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"preview build failed: {exc}"}, status_code=500)

        generation = _generation_service(session_context)
        dispatch = await run_in_thread(
            generation.enqueue_remote_request,
            # api_mode 를 못박는다 - 위 확인과 이 enqueue 사이에 모드가 바뀔 수 있다
            # (캐릭터 에셋 벤치가 같은 이유로 같은 일을 한다).
            {"type": "generate", "api_mode": "NAI", "overrides": overrides},
        )
        if not dispatch.ok:
            return JSONResponse(dispatch.websocket_payload(), status_code=409)
        if session_context.headless_generation_execute_enabled:
            start_generation_runner(session_context, clients)
        return {
            "ok": True,
            "requestId": request_id,
            "model": PREVIEW_MODEL_KEY,
            "steps": PREVIEW_STEPS,
            "width": overrides["width"],
            "height": overrides["height"],
        }
