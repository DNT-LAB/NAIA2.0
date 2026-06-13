"""GitHub URL 확장 설치 라우트 (loopback 전용).

설치는 host 파일시스템에 코드를 배치하는 부작용이라, install-manager 라우트와
동일하게 loopback-gated 한다 — 원격 Remote Web 클라이언트가 임의 GitHub URL로
host에 확장을 깔지 못하게 막는다(RCE 방지). 읽기 전용 상태 조회는 누구나(진행률
렌더용).
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.extension_install_service import ExtensionInstallService
from core.headless_payload_utils import is_loopback_host
from core.web_session_context import WebSessionContext


AsyncRunner = Callable[..., Awaitable[Any]]


def _request_host(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw.startswith("[") and "]" in raw:
        return raw[1:raw.index("]")]
    if raw.count(":") == 1:
        return raw.rsplit(":", 1)[0]
    return raw


def _is_local_request(req: Request) -> bool:
    client_host = ""
    try:
        if req.client is not None:
            client_host = _request_host(str(req.client.host or ""))
    except Exception:
        client_host = ""
    request_host = _request_host(req.headers.get("host") or getattr(req.url, "hostname", "") or "")
    if client_host == "testclient":
        return request_host in {"", "testserver"} or is_loopback_host(request_host)
    return is_loopback_host(client_host) and is_loopback_host(request_host)


def _loopback_only() -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": "확장 설치는 로컬에서만 가능합니다."},
        status_code=403,
    )


def extension_install_service(context: WebSessionContext) -> ExtensionInstallService:
    service = getattr(context, "extension_install_service", None)
    if service is None:
        runtime_paths = getattr(context, "runtime_paths", None)
        if runtime_paths is None:
            raise RuntimeError("Runtime paths are not available")
        service = ExtensionInstallService(runtime_paths.extensions_dir)
        context.extension_install_service = service
    return service


def register_extension_install_routes(
    app: FastAPI,
    context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
) -> None:
    @app.get("/api/extensions/install")
    async def api_extension_install_state(req: Request):
        try:
            return await run_in_thread(extension_install_service(context).snapshot)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"설치 상태 조회 실패: {exc}"}, status_code=500)

    @app.post("/api/extensions/install")
    async def api_extension_install_start(req: Request):
        if not _is_local_request(req):
            return _loopback_only()
        try:
            body = await req.json()
        except Exception:
            body = {}
        url = str((body or {}).get("url") or "").strip()
        if not url:
            return JSONResponse({"ok": False, "error": "GitHub 주소를 입력하세요."}, status_code=400)
        try:
            return await run_in_thread(extension_install_service(context).start, url)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"설치 시작 실패: {exc}"}, status_code=500)

    @app.post("/api/extensions/install/cancel")
    async def api_extension_install_cancel(req: Request):
        if not _is_local_request(req):
            return _loopback_only()
        try:
            return await run_in_thread(extension_install_service(context).cancel)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"설치 취소 실패: {exc}"}, status_code=500)
