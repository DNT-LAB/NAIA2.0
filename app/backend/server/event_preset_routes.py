from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.backend.server.preset_services import event_preset_download_service, event_preset_status
from core.web_session_context import WebSessionContext


AsyncRunner = Callable[..., Awaitable[Any]]


def register_event_preset_routes(
    app: FastAPI,
    session_context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
) -> None:
    @app.get("/api/event-preset/status")
    async def api_event_preset_status():
        try:
            return await run_in_thread(event_preset_status, session_context)
        except Exception as exc:
            return JSONResponse({"error": f"Event Preset status failed: {exc}"}, status_code=500)

    @app.get("/api/event-preset/download")
    async def api_event_preset_download_state():
        try:
            return await run_in_thread(event_preset_download_service(session_context).snapshot)
        except Exception as exc:
            return JSONResponse({"error": f"Event Preset download state failed: {exc}"}, status_code=500)

    @app.post("/api/event-preset/download")
    async def api_event_preset_download():
        try:
            return await run_in_thread(event_preset_download_service(session_context).start)
        except Exception as exc:
            return JSONResponse({"error": f"Event Preset download failed: {exc}"}, status_code=500)

    @app.post("/api/event-preset/download/cancel")
    async def api_event_preset_download_cancel():
        try:
            return await run_in_thread(event_preset_download_service(session_context).cancel)
        except Exception as exc:
            return JSONResponse({"error": f"Event Preset download cancel failed: {exc}"}, status_code=500)
