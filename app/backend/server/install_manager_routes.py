"""Runtime install manager routes.

POST endpoints here mutate ``user_root`` (initialize creates directories +
copies bootstrap files; tag-archive/download starts a long-lived download
thread writing into ``data/tags``). These are server-machine side effects, so
they are loopback-gated the same way the data-migration routes are — a remote
Remote Web client must not be able to start a multi-GB download or scaffold
directories on the host. The read-only ``GET /api/install-manager`` snapshot
stays open so any client can render progress, matching how the data-migration
preview is allowed to surface state but not act on it.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.headless_payload_utils import is_loopback_host
from core.runtime_install_manager import RuntimeInstallManager
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


def _loopback_only_response() -> JSONResponse:
    return JSONResponse(
        {"ok": False, "runtime": "web", "error": "데이터 초기화/다운로드는 로컬에서만 가능합니다."},
        status_code=403,
    )


def runtime_install_manager(context: WebSessionContext) -> RuntimeInstallManager:
    service = getattr(context, "runtime_install_manager", None)
    if service is None:
        runtime_paths = getattr(context, "runtime_paths", None)
        if runtime_paths is None:
            raise RuntimeError("Runtime paths are not available")

        def refresh_tag_state() -> None:
            context.tag_search_index = None
            context.kr_tags_raw = {}
            context.autocomplete_state.kr_tags_loaded = False

        service = RuntimeInstallManager(
            runtime_paths,
            on_tag_archive_complete=refresh_tag_state,
        )
        context.runtime_install_manager = service
    return service


def register_install_manager_routes(
    app: FastAPI,
    session_context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
) -> None:
    @app.get("/api/install-manager")
    async def api_install_manager_state():
        try:
            return await run_in_thread(runtime_install_manager(session_context).snapshot)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"Install manager state failed: {exc}"}, status_code=500)

    @app.post("/api/install-manager/initialize")
    async def api_install_manager_initialize(req: Request):
        if not _is_local_request(req):
            return _loopback_only_response()
        try:
            return await run_in_thread(runtime_install_manager(session_context).initialize)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"Install manager initialize failed: {exc}"}, status_code=500)

    @app.post("/api/install-manager/tag-archive/download")
    async def api_install_manager_tag_archive_download(req: Request):
        if not _is_local_request(req):
            return _loopback_only_response()
        try:
            manager = runtime_install_manager(session_context)
            await run_in_thread(manager.start_tag_archive_download)
            return await run_in_thread(manager.snapshot)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"Tag archive download failed: {exc}"}, status_code=500)

    @app.post("/api/install-manager/tag-archive/download/cancel")
    async def api_install_manager_tag_archive_download_cancel(req: Request):
        if not _is_local_request(req):
            return _loopback_only_response()
        try:
            manager = runtime_install_manager(session_context)
            await run_in_thread(manager.cancel_tag_archive_download)
            return await run_in_thread(manager.snapshot)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"Tag archive download cancel failed: {exc}"}, status_code=500)
