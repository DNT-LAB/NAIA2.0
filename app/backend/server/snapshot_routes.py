"""Snapshot image route; mutations use the existing generic module channel."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response

from core.web_session_context import WebSessionContext


def register_snapshot_routes(
    app: FastAPI, session_context: WebSessionContext, *, run_in_thread: Callable[..., Any],
) -> None:
    from app.backend.server.search_runtime import (
        apply_search_runtime_filters, reconstruct_active_tag_filter, reset_active_tag_filter_assignment,
    )

    def rebuild_filter():
        # 비활성 태그 필터도 등급은 적용해야 한다. 활성 재조립은 내부에서 이미 적용한다.
        if not reconstruct_active_tag_filter(session_context):
            apply_search_runtime_filters(session_context)

    session_context._snapshot_service().register_search_runtime(
        reset_filter=lambda: reset_active_tag_filter_assignment(session_context),
        rebuild_filter=rebuild_filter,
    )

    @app.get("/api/snapshot/image")
    async def api_snapshot_image(name: str = "", v: str = ""):
        payload = await run_in_thread(session_context._snapshot_service().image_payload, name)
        if payload is None:
            return JSONResponse({"error": "snapshot image not found"}, status_code=404)
        image_bytes, media_type = payload
        return Response(content=image_bytes, media_type=media_type,
                        headers={"Cache-Control": "private, max-age=3600"})
