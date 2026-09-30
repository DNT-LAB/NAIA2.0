"""Assist v2 라우트 — 기억이 짧은 One-Shot 만능 어시스트(Ctrl+O).

검색·조립 결과만 돌려주고 프롬프트·Random 연결·생성은 화면이 사용자의 버튼으로 한다.
엔진(Boost v2 와 공유)을 올리는 것은 원격 클라이언트에서도 된다 — Random 이 Boost 를 부를 때와 같다.
한국어 분석기(Kiwi) 설치만은 NAIA 가 도는 PC 에서만 — 그 PC 의 파이썬 환경에 패키지를 넣는 일이다.
"""

from __future__ import annotations

import uuid
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.backend.server.install_manager_routes import _is_local_request


def register_assist_v2_routes(
    app: FastAPI,
    context: Any,
    *,
    run_in_thread: Callable[..., Awaitable[Any]],
    clients: set[Any] | None = None,
    start_generation_runner: Callable[..., Any] | None = None,
    broadcast_json: Callable[..., Awaitable[None]] | None = None,
) -> None:
    from app.backend.server.assist_v2_service import (
        AssistError,
        apply_source_row,
        assist_names,
        assist_status,
        boost_result,
        generation_request,
        get_kiwi_installer,
        run_assist,
        warm_assist,
    )

    async def _broadcast(message: dict[str, Any]) -> None:
        if clients is not None and broadcast_json is not None:
            await broadcast_json(clients, message)

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

    @app.post("/api/assist/generate")
    async def assist_generate_route(request: Request):
        """[생성] Assist 결과를 **가상 프롬프트**로 한 장 생성한다 — 메인 프롬프트·캐릭터 칸은 그대로다
        (사용자 지정 2026-09-24). 메인은 이벤트 맵 [생성] 과 같은 바이패스(파이프라인·PE 앞뒤), 캐릭터는
        이 요청에만 싣는다(`generation_request`). 끝의 문장은 태그 필터를 거치지 않고 메인 끝에(source_row['sentence']).
        boost = [부스트 생성](사용자 지정 09-30) — 파이프라인 뒤 Auto Boost 와 같은 길로 부스트하고, 안 되면 생성하지 않는다
        (부스트를 청했는데 부스트 없는 한 장을 뽑으면 시간 · Anlas 만 쓴다)."""
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "JSON 요청이 아닙니다."}, status_code=400)
        try:
            source_row, overrides = generation_request(context, payload)
        except AssistError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        from app.backend.server.event_preset_routes import (
            _generate_event_preset_prompt, _generation_service, _preset_source_to_generation_command)

        request_id = str(payload.get("requestId") or uuid.uuid4().hex)
        try:
            processed = await run_in_thread(
                _generate_event_preset_prompt, context, source_row,
                overrides={}, request_id=request_id, source="assist")
            if not processed.success:
                return JSONResponse({"ok": False, "error": processed.error or "프롬프트를 만들지 못했습니다."},
                                    status_code=400)
            if payload.get("boost"):
                why = await boost_result(context, processed, update_context=False)
                if why:
                    return JSONResponse({"ok": False, "code": "boost_failed", "error": why}, status_code=409)
            # ⚠️ 명령에는 등급을 **비워서** 넘긴다 - 명령을 만드는 쪽이 source_row 의 등급으로 Quick Filter
            #    (검색 등급)를 바꾼다(set_active_ratings). 한 장 뽑았다고 사용자의 검색 조건이 바뀌면 안 된다.
            #    생성 기록(메타데이터)에는 원래 등급을 다시 싣는다.
            result = {"requestId": request_id, "sourceRow": {**source_row, "rating": ""},
                      "sourceName": f"assist:{request_id}"}
            command = _preset_source_to_generation_command(
                context, result, source="preset", overrides=overrides,
                prompt_override=processed.prompt, prompt_run_id_override=processed.prompt_run_id)
            command["overrides"]["_source_row_data"] = source_row
            command["overrides"]["_remote_queue_label"] = "assist"
            dispatch = await run_in_thread(_generation_service(context).enqueue_remote_request, command)
        except RuntimeError as exc:
            return JSONResponse({"ok": False, "code": "blocked", "error": str(exc)}, status_code=409)
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        except Exception as exc:                                  # pragma: no cover
            print(f"Headless Remote: assist generate failed - {exc}", flush=True)
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
        if not dispatch.ok:
            return JSONResponse({"ok": False, "code": "blocked", **dispatch.websocket_payload()}, status_code=409)
        if start_generation_runner is not None and clients is not None \
                and getattr(context, "headless_generation_execute_enabled", False):
            start_generation_runner(context, clients)
        return {"ok": True, "requestId": request_id, "prompt": processed.prompt,
                "characters": list(overrides.get("characters") or []), "boosted": bool(payload.get("boost"))}

    @app.post("/api/assist/apply")
    async def assist_apply_route(request: Request):
        """[프롬프트에 넣기] · [부스트 넣기] — Assist 결과를 Random 과 같은 파이프라인(PE 앞뒤 · 자동 숨김 · remove_*)에 태워
        메인 프롬프트로 보낸다(prompt_generated 브로드캐스트 — 예전 /api/event-map/apply 와 같은 일, 출처는 'assist').
        끝의 문장은 태그 필터를 거치지 않고 메인 끝에(source_row['sentence']). boost 면 Auto Boost 와 같은 길로 부스트한 뒤
        넣는다(사용자 지정 09-30) — 부스트가 안 되면 부스트 없이 넣고 까닭을 돌려준다(칸은 파이프라인에서 이미 바뀌었다 —
        서버 상태와 화면을 맞춘다)."""
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "JSON 요청이 아닙니다."}, status_code=400)
        try:
            source_row = apply_source_row(context, payload)
        except AssistError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        from app.backend.server.generation_commands import _broadcast_wildcard_state, random_service

        request_id = str(payload.get("requestId") or uuid.uuid4().hex)
        try:
            result = await run_in_thread(
                random_service(context).generate_from_source_row,
                source_row, random_request_id=request_id, source="assist", update_context=True)
        except Exception as exc:                                  # pragma: no cover
            print(f"Headless Remote: assist apply failed - {exc}", flush=True)
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
        if not result.success:
            return JSONResponse({"ok": False, "error": result.error or "프롬프트를 만들지 못했습니다."}, status_code=400)
        warning = None
        if payload.get("boost"):
            warning = await boost_result(context, result, update_context=True)
            if warning is None:
                try:
                    context.save_remote_ui_state()                # 파이프라인이 저장한 것은 부스트 전 글이다
                except Exception:
                    pass
        await _broadcast(result.websocket_payload())
        for message in result.extra_messages:
            await _broadcast(message)
        if clients is not None:
            try:
                await _broadcast_wildcard_state(context, clients)
            except Exception:
                pass
        out = {"ok": True, "requestId": request_id, "prompt": result.prompt, "promptRunId": result.prompt_run_id,
               "boosted": bool(payload.get("boost")) and warning is None}
        if warning:
            out["warning"] = warning
        return out

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
