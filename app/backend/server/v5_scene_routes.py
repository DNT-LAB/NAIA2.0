"""V5 Scene HTTP 라우트 — 지금은 썸네일 하나뿐이다.

씬의 조작(저장·적용·삭제·이름변경)은 전부 범용 `set_module_param('v5_scene', …)` WS
채널을 탄다. **새 WS 메시지 타입을 만들지 않기 위해서**다 — 웹 스모크 계약이 메시지
타입을 순서대로 세기 때문에 브로드캐스트를 하나 더하면 그 뒤가 전부 밀린다.
그림만은 WS 로 실어 나를 수 없어 여기 HTTP 로 둔다(라우트는 계약이 세지 않는다).
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response

from core.web_session_context import WebSessionContext

AsyncRunner = Callable[..., Any]


def v5_scene_service(context: WebSessionContext):
    return context._v5_scene_service()


def register_v5_scene_routes(
    app: FastAPI,
    session_context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
) -> None:
    @app.get("/api/v5-scene/thumbnail")
    async def api_v5_scene_thumbnail(event: str = "", name: str = "", v: str = ""):
        # `v` 는 캐시 버스트용 판(revision)이라 서버가 읽지 않는다. 서비스가 파일
        # mtime/크기로 만들어 URL 에 붙이므로 **내용이 바뀌면 URL 이 바뀐다**.
        # 선례: `/api/character-viewer/thumbnail`.
        try:
            payload = await run_in_thread(
                v5_scene_service(session_context).thumbnail_payload, event, name)
        except Exception as exc:
            return JSONResponse({"error": f"V5 Scene thumbnail failed: {exc}"}, status_code=500)
        if payload is None:
            return JSONResponse({"error": "thumbnail not found"}, status_code=404)
        image_bytes, media_type = payload
        # 씬 썸네일은 **언제나 사용자 것**이다(자기가 만든 그림). 개인 이미지이자
        # 같은 이름으로 덮어써지는 가변물이라 `private`. 위의 `v=` 와 짝이어야 뜻이 산다 —
        # URL 이 그대로면 신선한 캐시가 서버에 닿지도 않아 새 헤더를 받을 기회가 없다.
        return Response(
            content=image_bytes,
            media_type=media_type,
            headers={"Cache-Control": "private, max-age=3600"},
        )
