"""Assist v2 라우트 — 기억이 짧은 One-Shot 만능 어시스트(Ctrl+O).

검색·조립 결과만 돌려주고 프롬프트·Random 연결·생성은 화면이 사용자의 버튼으로 한다.
엔진(Boost v2 와 공유)을 올리는 것은 원격 클라이언트에서도 된다 — Random 이 Boost 를 부를 때와 같다.
한국어 분석기(Kiwi) 설치만은 NAIA 가 도는 PC 에서만 — 그 PC 의 파이썬 환경에 패키지를 넣는 일이다.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.backend.server.install_manager_routes import _is_local_request


def register_assist_v2_routes(
    app: FastAPI,
    context: Any,
    *,
    run_in_thread: Callable[..., Awaitable[Any]],
) -> None:
    from app.backend.server.assist_v2_service import (
        assist_names,
        assist_status,
        get_kiwi_installer,
        run_assist,
        warm_assist,
    )

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

    @app.post("/api/assist/names")
    async def assist_names_route(request: Request):
        """입력하는 동안 칠할 캐릭터 이름과 후보(모델 없이). 후보가 여럿이면 화면이 사용자에게 고르게 한다."""
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "JSON 요청이 아닙니다."}, status_code=400)
        return await run_in_thread(assist_names, context, payload)

    @app.get("/api/assist/status")
    async def assist_status_route():
        """엔진·한국어 층·Kiwi 설치 진행(폴링용)."""
        return await run_in_thread(assist_status, context)

    @app.post("/api/assist/kiwi/install")
    async def assist_kiwi_install_route(request: Request):
        """한국어 분석기(Kiwi, 약 90MB)를 지금 파이썬 환경에 설치한다 — 사용자가 [설치]를 눌렀을 때만."""
        if not _is_local_request(request):
            return JSONResponse(
                {"ok": False, "error": "한국어 분석기 설치는 NAIA 가 실행 중인 PC 에서만 할 수 있습니다."},
                status_code=403,
            )
        state = await run_in_thread(get_kiwi_installer(context).start)
        return {"ok": True, **state}
