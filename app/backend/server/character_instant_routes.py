# -*- coding: utf-8 -*-
"""캐릭터 '즉시 생성' 라우트.

설계와 비용 근거는 `core/character_instant_service.py` 주석에 있다. 여기서는 그
오버라이드를 **기존 생성 큐에 그대로 태운다** — 계정 분배 · 직렬화 · 실패 처리를
다시 짜지 않기 위해서다(V4.5 프리뷰가 쓰는 것과 같은 통로).

⚠️ NAI 모드에서만 뜻이 있다 — `characters` 는 다른 백엔드가 안 읽는다.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.character_instant_service import (
    build_instant_overrides,
    build_instant_prompt,
    detect_subject,
)
from core.headless_generation_service import HeadlessGenerationService
from core.web_session_context import WebSessionContext

AsyncRunner = Callable[..., Awaitable[Any]]


def _generation_service(context: WebSessionContext) -> HeadlessGenerationService:
    service = getattr(context, "headless_generation_service", None)
    if service is None:
        service = HeadlessGenerationService(context)
        context.headless_generation_service = service
    return service


def _find_frame(context: WebSessionContext, uuid: str) -> dict[str, Any] | None:
    """uuid 로 캐릭터 프레임을 찾는다.

    ⚠️ **index 로 받지 않는다.** 화면이 요청을 만든 뒤 도착하기까지 정렬이 한 번
       지나가면 그 번호는 이미 남의 것이다 - 엉뚱한 캐릭터가 나간다.
    """
    from core.character_settings import _frame_uuid
    from core.headless_character_service import HeadlessCharacterService

    if not uuid:
        return None
    # ⚠️ 파일이 아니라 **서비스의 캐시**를 읽는다 - 그것이 지금 화면이 보고 있는
    #    상태다(set_param 은 캐시를 고치고 저장한다).
    service = getattr(context, "headless_character_service", None)
    if service is None:
        service = HeadlessCharacterService(context)
        context.headless_character_service = service
    settings = service.settings_cache()
    for frame in settings.get("character_frames") or []:
        if isinstance(frame, dict) and _frame_uuid(frame) == uuid:
            return frame
    return None


def register_character_instant_routes(
    app: FastAPI,
    session_context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
    clients: set[Any],
    start_generation_runner: Callable[..., Any],
) -> None:

    @app.post("/api/character/instant-generate")
    async def api_character_instant_generate(req: Request):
        try:
            body = await req.json()
        except Exception:
            body = {}
        uuid = str((body or {}).get("uuid") or "")
        request_id = str((body or {}).get("requestId") or "")

        if str(session_context.get_api_mode() or "").upper() != "NAI":
            return JSONResponse(
                {"error": "즉시 생성은 NAI 모드에서만 사용할 수 있습니다."}, status_code=400)

        frame = await run_in_thread(_find_frame, session_context, uuid)
        if frame is None:
            return JSONResponse({"error": "그 캐릭터를 찾지 못했습니다."}, status_code=404)
        if not str(frame.get("prompt") or "").strip():
            return JSONResponse(
                {"error": "빈 캐릭터는 생성할 것이 없습니다."}, status_code=400)

        prompt = await run_in_thread(build_instant_prompt, session_context, frame)
        overrides = build_instant_overrides(request_id, frame)

        generation = _generation_service(session_context)
        dispatch = await run_in_thread(
            generation.enqueue_remote_request,
            {
                # ⚠️ 모드를 못박는다 - 위 확인과 이 enqueue 사이에 바뀔 수 있다.
                "type": "generate",
                "api_mode": "NAI",
                "overrides": overrides,
                # 메인 프롬프트는 **자기 것**으로 나간다(PE 선행 + 1girl|1boy + 후행).
                "prompt": prompt,
            },
        )
        if not dispatch.ok:
            return JSONResponse(dispatch.websocket_payload(), status_code=409)
        if session_context.headless_generation_execute_enabled:
            start_generation_runner(session_context, clients)
        return {
            "ok": True,
            "requestId": request_id,
            "subject": detect_subject(frame.get("prompt")),
            "prompt": prompt,
            # 화면이 메인 프롬프트 창에 적을 값(아티스트 Random Prompt 와 같은 사양).
            "character": overrides["characters"][0],
        }
