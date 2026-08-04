# -*- coding: utf-8 -*-
"""Interactive 전용 캐릭터 레퍼런스 라우트.

    GET  /api/interactive-reference/state       현재 목록(썸네일만)
    POST /api/interactive-reference/attach      에셋/보관함/업로드에서 한 장 붙이기
    POST /api/interactive-reference/param       강도·충실도·종류 변경
    POST /api/interactive-reference/remove      한 장 제거
    POST /api/interactive-reference/clear       전부 제거

NAI 캐릭터 레퍼런스 모듈(`/api/module/...` 의 `character_reference`)과 **상태가
독립**이다 — 이유는 `core/headless_interactive_reference_service.py` 첫머리 참조.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.web_session_context import WebSessionContext

AsyncRunner = Callable[..., Awaitable[Any]]


async def _read_json(req: Request) -> dict[str, Any]:
    try:
        payload = await req.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def register_interactive_reference_routes(
    app: FastAPI,
    session_context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
    clients: Any = None,
    broadcast_json: Any = None,
) -> None:
    def _svc():
        return session_context._interactive_reference_service()

    @app.get("/api/interactive-reference/state")
    async def api_interactive_reference_state():
        try:
            return await run_in_thread(lambda: _svc().state())
        except Exception as exc:
            return JSONResponse({"error": f"state failed: {exc}"}, status_code=500)

    @app.post("/api/interactive-reference/attach")
    async def api_interactive_reference_attach(req: Request):
        payload = await _read_json(req)
        source = str(payload.get("source") or "")
        ref = str(payload.get("ref") or "")
        label = str(payload.get("label") or "")

        def _run() -> dict[str, Any]:
            # 이미지 바이트를 어디서 가져오나 — 출처마다 다르다. 원본은 출처가 갖고
            # 있고 여기는 인코딩된 사본만 보관한다(파일을 두 번 두지 않는다).
            if source == "asset":
                svc = session_context._character_asset_service()
                path = svc.resolve_image_path(ref, str(payload.get("variation") or ""))
                return _svc().attach_bytes(path.read_bytes(), label or ref)
            if source == "storage":
                # **파일명만 쓴다.** 클라이언트 값을 그대로 경로에 넣으면
                # `../..` 로 저장 트리 밖의 PNG 를 읽어 썸네일로 노출할 수 있다
                # (2026-08-05 Codex 지적). 기존 CR 라우트도 `Path(...).name` 을 쓴다.
                safe = Path(str(ref)).name
                if not safe or safe != str(ref) or safe.startswith("."):
                    raise ValueError(f"invalid storage ref: {ref!r}")
                # 목록은 레거시 저장 루트까지 훑는다(`_existing_save_dirs`) — 여기서
                # 기본 루트만 보면 목록에는 뜨는데 누르면 404 가 난다.
                for folder in session_context._existing_save_dirs(
                        "character_reference", "images"):
                    path = folder / f"{safe}.png"
                    if path.exists():
                        return _svc().attach_bytes(path.read_bytes(), label or safe)
                raise FileNotFoundError(f"storage image not found: {safe}")
            raise ValueError(f"unknown source: {source!r}")

        try:
            result = await run_in_thread(_run)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"attach failed: {exc}"}, status_code=500)
        return result

    @app.post("/api/interactive-reference/param")
    async def api_interactive_reference_param(req: Request):
        payload = await _read_json(req)
        try:
            return await run_in_thread(
                lambda: _svc().set_param(str(payload.get("file_hash") or ""),
                                         str(payload.get("key") or ""),
                                         payload.get("value")))
        except (ValueError, KeyError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"param failed: {exc}"}, status_code=500)

    @app.post("/api/interactive-reference/remove")
    async def api_interactive_reference_remove(req: Request):
        payload = await _read_json(req)
        try:
            return await run_in_thread(
                lambda: _svc().remove(str(payload.get("file_hash") or "")))
        except Exception as exc:
            return JSONResponse({"error": f"remove failed: {exc}"}, status_code=500)

    @app.post("/api/interactive-reference/clear")
    async def api_interactive_reference_clear():
        try:
            return await run_in_thread(lambda: _svc().clear())
        except Exception as exc:
            return JSONResponse({"error": f"clear failed: {exc}"}, status_code=500)
