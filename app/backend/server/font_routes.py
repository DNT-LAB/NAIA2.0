"""Settings > Global > 폰트 - 사용자 추가 폰트 라우트.

업로드된 폰트는 ``ui_assets/fonts`` 에 저장되어 모든 접속 기기(데스크톱/모바일)에서
동일하게 내려받을 수 있다. 어떤 폰트를 쓸지 고르는 "선택" 자체는 기기별 취향이므로
프런트의 localStorage 가 갖고 있고 서버는 관여하지 않는다.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from core.font_asset_service import MAX_FONT_BYTES, FontAssetService, FontValidationError
from core.web_session_context import WebSessionContext


AsyncRunner = Callable[..., Awaitable[Any]]


def font_asset_service(context: WebSessionContext, root_web_dir: Path | None = None) -> FontAssetService:
    service = getattr(context, "font_asset_service", None)
    if service is None:
        runtime_paths = getattr(context, "runtime_paths", None)
        if runtime_paths is None:
            # 저장소 내부(repo_root)로 폴백하면 안 된다 - runtime_write_policy 가
            # "repository data/** · repository root" 쓰기를 금지한다. 런타임 경로를
            # 못 얻는 상황은 배선 오류이므로 조용히 다른 곳에 쓰지 말고 드러낸다.
            raise RuntimeError("runtime_paths is required to resolve the font asset directory")
        fonts_dir = runtime_paths.ui_assets_dir / "fonts"
        bundled = (root_web_dir / "fonts") if root_web_dir is not None else None
        service = FontAssetService(fonts_dir, bundled_dir=bundled)
        context.font_asset_service = service
    return service


def register_font_routes(
    app: FastAPI,
    session_context: WebSessionContext,
    root_web_dir: Path,
    *,
    run_in_thread: AsyncRunner,
) -> None:
    def _service() -> FontAssetService:
        return font_asset_service(session_context, root_web_dir)

    @app.get("/api/fonts")
    async def api_fonts_list():
        try:
            return await run_in_thread(_service().list_fonts)
        except Exception as exc:
            return JSONResponse({"error": f"Font list failed: {exc}"}, status_code=500)

    # 본문을 메모리에 받는 라우트라 동시 업로드 수를 묶어 둔다. 상한이 없으면
    # N개 요청이 각각 MAX_FONT_BYTES 까지 동시에 점유할 수 있다(서버는 0.0.0.0 바인딩).
    upload_slots = asyncio.Semaphore(2)

    @app.post("/api/fonts/upload")
    async def api_fonts_upload(req: Request, filename: str = ""):
        # 서버는 기본적으로 0.0.0.0 에 바인딩되므로(LAN 접속 기능) 본문을 통째로
        # 버퍼링하기 전에 Content-Length 로 먼저 걸러 낸다. 헤더가 없거나 거짓말이면
        # save_font 의 길이 검사가 최종 방어선이다.
        limit_mb = MAX_FONT_BYTES // (1024 * 1024)
        too_large = JSONResponse(
            {"ok": False, "error": f"폰트 파일이 너무 큽니다. (최대 {limit_mb}MB)"},
            status_code=413,
        )
        declared = req.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_FONT_BYTES:
            return too_large
        try:
            # 저장소가 이미 가득 찼으면 본문을 받기 전에 거절한다. 받고 나서 거절하면
            # 어차피 버릴 데이터를 위해 최대 40MB 를 메모리에 올리게 된다.
            await run_in_thread(_service().assert_can_accept, declared)
        except FontValidationError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=507)
        except Exception:
            pass  # 사전 점검 실패는 치명적이지 않다 - save_font 가 최종 판정한다

        async with upload_slots:
            # Content-Length 가 없거나 거짓일 수 있으므로 본문을 스트리밍하며 누적 상한을
            # 건다. req.body() 로 통째로 받으면 헤더를 속인 요청이 그대로 메모리에 올라간다.
            chunks: list[bytes] = []
            total = 0
            async for chunk in req.stream():
                total += len(chunk)
                if total > MAX_FONT_BYTES:
                    return too_large
                chunks.append(chunk)
            data = b"".join(chunks)
        try:
            return await run_in_thread(_service().save_font, filename, data)
        except FontValidationError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"Font upload failed: {exc}"}, status_code=500)

    @app.delete("/api/fonts/{font_id}")
    async def api_fonts_delete(font_id: str):
        try:
            return await run_in_thread(_service().delete_font, font_id)
        except FileNotFoundError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"Font delete failed: {exc}"}, status_code=500)

    @app.get("/fonts/{filename}")
    async def serve_font(filename: str):
        try:
            target, media_type = _service().resolve_file(filename)
        except FileNotFoundError:
            return JSONResponse({"error": "not found"}, status_code=404)
        except Exception:
            return JSONResponse({"error": "not found"}, status_code=404)
        # 폰트 본문은 파일명이 바뀌지 않는 한 불변이므로 캐시를 허용한다.
        return FileResponse(
            str(target),
            media_type=media_type,
            headers={"Cache-Control": "public, max-age=86400"},
        )
