"""PyQt-free FastAPI app for the headless Remote Web Session path."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI

from app.backend.server.artist_thumbnail_routes import register_artist_thumbnail_routes
from app.backend.server.character_viewer_routes import register_character_viewer_routes
from app.backend.server.danbooru_routes import register_danbooru_routes
from app.backend.server.event_preset_routes import register_event_preset_routes
from app.backend.server.generation_runner import ensure_generation_runner
from app.backend.server.headless_lifespan import create_headless_lifespan
from app.backend.server.install_manager_routes import register_install_manager_routes
from app.backend.server.params_workflow_routes import register_params_workflow_routes
from app.backend.server.prompt_tools_routes import register_prompt_tools_routes
from app.backend.server.result_display_routes import register_result_display_routes
from app.backend.server.state_routes import register_state_routes
from app.backend.server.style_thumbnail_routes import register_style_thumbnail_routes
from app.backend.server.web_shell_routes import register_web_shell_routes
from app.backend.server.websocket_session import register_websocket_session
from app.backend.server.websocket_broadcast import broadcast_json
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
    app.state.remote_web_dir = str(root_web_dir)
    register_web_shell_routes(app, root_web_dir)

    register_state_routes(
        app,
        session_context,
        run_in_thread=_to_thread,
        clients=app.state.headless_clients,
        broadcast_json=broadcast_json,
        start_generation_runner=ensure_generation_runner,
    )
    register_install_manager_routes(app, session_context, run_in_thread=_to_thread)
    register_params_workflow_routes(
        app,
        session_context,
        run_in_thread=_to_thread,
        clients=app.state.headless_clients,
        broadcast_json=broadcast_json,
    )
    register_prompt_tools_routes(
        app,
        session_context,
        run_in_thread=_to_thread,
        clients=app.state.headless_clients,
        broadcast_json=broadcast_json,
        start_generation_runner=ensure_generation_runner,
    )
    register_style_thumbnail_routes(app, session_context, run_in_thread=_to_thread)
    register_danbooru_routes(app, session_context, run_in_thread=_to_thread)
    register_event_preset_routes(
        app,
        session_context,
        run_in_thread=_to_thread,
        clients=app.state.headless_clients,
        broadcast_json=broadcast_json,
        start_generation_runner=ensure_generation_runner,
    )
    register_artist_thumbnail_routes(
        app,
        session_context,
        run_in_thread=_to_thread,
        clients=app.state.headless_clients,
        start_generation_runner=ensure_generation_runner,
    )
    register_character_viewer_routes(
        app,
        session_context,
        run_in_thread=_to_thread,
        clients=app.state.headless_clients,
        start_generation_runner=ensure_generation_runner,
    )
    register_result_display_routes(
        app,
        session_context,
        run_in_thread=_to_thread,
        clients=app.state.headless_clients,
        broadcast_json=broadcast_json,
    )

    register_websocket_session(
        app,
        session_context,
        clients=app.state.headless_clients,
        run_in_thread=_to_thread,
        broadcast_json=broadcast_json,
        start_generation_runner=ensure_generation_runner,
    )

    return app


__all__ = ["create_headless_app"]
