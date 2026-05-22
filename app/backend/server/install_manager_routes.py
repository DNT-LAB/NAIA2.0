from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from core.runtime_install_manager import RuntimeInstallManager
from core.web_session_context import WebSessionContext


AsyncRunner = Callable[..., Awaitable[Any]]


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
    async def api_install_manager_initialize():
        try:
            return await run_in_thread(runtime_install_manager(session_context).initialize)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"Install manager initialize failed: {exc}"}, status_code=500)

    @app.post("/api/install-manager/tag-archive/download")
    async def api_install_manager_tag_archive_download():
        try:
            manager = runtime_install_manager(session_context)
            await run_in_thread(manager.start_tag_archive_download)
            return await run_in_thread(manager.snapshot)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"Tag archive download failed: {exc}"}, status_code=500)

    @app.post("/api/install-manager/tag-archive/download/cancel")
    async def api_install_manager_tag_archive_download_cancel():
        try:
            manager = runtime_install_manager(session_context)
            await run_in_thread(manager.cancel_tag_archive_download)
            return await run_in_thread(manager.snapshot)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"Tag archive download cancel failed: {exc}"}, status_code=500)
