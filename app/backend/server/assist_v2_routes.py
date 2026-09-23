"""Assist v2 라우트 — 기억이 짧은 One-Shot 만능 어시스트(Ctrl+O).

읽기 전용이다: 검색·조립 결과만 돌려주고 프롬프트·Random 연결·생성은 화면이 사용자의 버튼으로 한다.
엔진(Boost v2 와 공유)을 올리는 것은 원격 클라이언트에서도 된다 — Random 이 Boost 를 부를 때와 같다.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


def register_assist_v2_routes(
    app: FastAPI,
    context: Any,
    *,
    run_in_thread: Callable[..., Awaitable[Any]],
) -> None:
    from app.backend.server.assist_v2_service import assist_status, run_assist, warm_assist

    @app.post("/api/assist")
    async def assist_route(request: Request):
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "JSON 요청이 아닙니다."}, status_code=400)
        result = await run_in_thread(run_assist, context, payload)
        return JSONResponse(result, status_code=200 if result.get("ok") else 400)

    @app.post("/api/assist/warm")
    async def assist_warm_route():
        """창을 열 때: Kiwi·엔진을 뒤에서 올리고 지금 상태를 돌려준다(기다리지 않는다)."""
        warm_assist(context)
        return await run_in_thread(assist_status, context)
