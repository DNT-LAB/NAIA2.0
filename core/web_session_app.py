"""PyQt-free FastAPI app for the headless Remote Web Session path."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI

from app.backend.server.headless_lifespan import create_headless_lifespan
from app.backend.server.headless_routes import register_headless_routes
from app.web import resolve_remote_web_dir
from core.web_session_context import WebSessionContext


async def _to_thread(func, /, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)


def create_headless_app(
    context: WebSessionContext | None = None,
    *,
    web_dir: Path | str | None = None,
) -> FastAPI:
    """Create the PyQt-free Remote Web FastAPI app."""

    session_context = context or WebSessionContext()

    app = FastAPI(
        title="NAIA Remote Headless",
        lifespan=create_headless_lifespan(session_context, run_in_thread=_to_thread),
    )
    app.state.web_session_context = session_context
    app.state.headless_clients = set()

    root_web_dir = (
        Path(web_dir).resolve()
        if web_dir is not None
        else resolve_remote_web_dir(session_context.repo_root)
    )
    register_headless_routes(
        app,
        session_context,
        root_web_dir,
        clients=app.state.headless_clients,
        run_in_thread=_to_thread,
    )

    return app


__all__ = ["create_headless_app"]
