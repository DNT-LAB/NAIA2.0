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

from core.preview_prompt_markers import (
    END_MARKER,
    START_MARKER,
    extract_between,
    has_markers,
    insert_markers,
    strip_markers,
)
from core.nai_preview_service import (
    PREVIEW_MODEL_KEY,
    PreviewNotFree,
    assert_free,
    build_preview_overrides,
    build_preview_prompt,
)
from core.nai_preview_settings import (
    RESOLUTION_MODES,
    SAMPLERS,
    SCHEDULERS,
    custom_resolution_candidates,
)
from core.nai_preview_settings import load as load_preview_settings
from core.nai_preview_settings import save as save_preview_settings
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
    broadcast_json: Callable[..., Awaitable[Any]],
) -> None:

    def _save_root():
        return getattr(getattr(session_context, "runtime_paths", None), "save_dir", None)

    def _build(request_id: str) -> tuple[dict[str, Any], str, str]:
        settings = load_preview_settings(_save_root())
        overrides = build_preview_overrides(session_context, request_id, settings)
        # ⚠️ **마지막 문.** 여기서 걸리면 아무것도 큐에 안 들어간다.
        assert_free(session_context, overrides)
        prompt = build_preview_prompt(session_context, settings)
        if not prompt:
            raise PreviewNotFree(
                "프리뷰 구간이 없습니다. 톱니 > [프리뷰 표식 삽입] 을 먼저 누르세요.")
        return overrides, prompt, str(settings.get("negative") or "")

    def _pe_prompts() -> tuple[str, str]:
        """지금 모드의 Prefix/Postfix. 표식 자리를 정하는 기준이다."""
        from core.prompt_engineering_settings import get_prompt_engineering_store

        store = get_prompt_engineering_store(session_context)
        settings = store.state(session_context.get_api_mode())["settings"]
        return str(settings.get("pre_prompt") or ""), str(settings.get("post_prompt") or "")

    @app.get("/api/nai-preview/settings")
    async def api_nai_preview_settings_get():
        """설정 + 화면이 그릴 선택지(샘플러·스케줄러·직접 선택 후보)."""
        settings = await run_in_thread(load_preview_settings, _save_root())
        return {
            "settings": settings,
            "options": {
                "resolution_modes": list(RESOLUTION_MODES),
                "samplers": list(SAMPLERS),
                "schedulers": list(SCHEDULERS),
                "custom_resolutions": [
                    {"width": w, "height": h, "label": f"{w} x {h}"}
                    for w, h in custom_resolution_candidates()
                ],
            },
        }

    @app.post("/api/nai-preview/settings")
    async def api_nai_preview_settings_post(req: Request):
        """⚠️ 저장 전에 정규화한다 - 범위를 벗어난 값이 디스크에 남으면 다음 실행에서
           그대로 실린다. `save` 가 clamp 까지 한다."""
        try:
            body = await req.json()
        except Exception:
            return JSONResponse({"error": "Invalid settings body"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "Invalid settings body"}, status_code=400)
        settings = await run_in_thread(save_preview_settings, body, _save_root())
        return {"ok": True, "settings": settings}

    @app.post("/api/nai-preview/markers")
    async def api_nai_preview_markers(req: Request):
        """메인 프롬프트에 프리뷰 구간 표식을 꽂거나 걷는다.

        ⚠️ 표식 계산을 화면에서 하지 않는다 - 규칙(Prefix 마지막부터 · 가중치 벗기기 ·
           뒤집힌 구간 보정)이 두 곳으로 갈리면 한쪽만 고치게 된다.
        """
        try:
            body = await req.json()
        except Exception:
            body = {}
        action = str((body or {}).get("action") or "insert").strip().lower()
        current = str(getattr(session_context, "prompt_text", "") or "")
        if action == "remove":
            updated = strip_markers(current)
        else:
            pre, post = await run_in_thread(_pe_prompts)
            updated = insert_markers(current, pre, post)
        session_context.prompt_text = updated
        await broadcast_json(clients, {
            "type": "prompt_sync",
            "prompt": updated,
            "negative": session_context.negative_prompt_text,
            "negative_prompt": session_context.negative_prompt_text,
            # force - 사용자가 방금 친 글이 아니라 우리가 고쳐 넣은 값이다.
            "force": True,
        })
        return {
            "ok": True,
            "action": action,
            "prompt": updated,
            "hasMarkers": has_markers(updated),
            "segment": extract_between(updated),
        }

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
            overrides, prompt, negative = await run_in_thread(_build, request_id)
        except PreviewNotFree as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"preview build failed: {exc}"}, status_code=500)

        generation = _generation_service(session_context)
        dispatch = await run_in_thread(
            generation.enqueue_remote_request,
            # api_mode 를 못박는다 - 위 확인과 이 enqueue 사이에 모드가 바뀔 수 있다
            # (캐릭터 에셋 벤치가 같은 이유로 같은 일을 한다).
            {
                "type": "generate",
                "api_mode": "NAI",
                "overrides": overrides,
                # 프리뷰는 **자기 프롬프트**로 나간다 - 표식 사이 general 태그에
                # 설정의 선행/후행을 붙인 것. 메인 프롬프트 그대로가 아니다.
                "prompt": prompt,
                "negative_prompt": negative,
            },
        )
        if not dispatch.ok:
            return JSONResponse(dispatch.websocket_payload(), status_code=409)
        if session_context.headless_generation_execute_enabled:
            start_generation_runner(session_context, clients)
        return {
            "ok": True,
            "requestId": request_id,
            "model": PREVIEW_MODEL_KEY,
            "steps": overrides["steps"],
            "width": overrides["width"],
            "height": overrides["height"],
        }
