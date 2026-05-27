from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, WebSocket

from app.backend.server.artist_thumbnail_routes import register_artist_thumbnail_routes
from app.backend.server.character_viewer_routes import register_character_viewer_routes
from app.backend.server.data_migration_routes import register_data_migration_routes
from app.backend.server.danbooru_routes import register_danbooru_routes
from app.backend.server.event_preset_routes import register_event_preset_routes
from app.backend.server.generation_commands import register_generation_rest_routes
from app.backend.server.generation_runner import ensure_generation_runner
from app.backend.server.install_manager_routes import register_install_manager_routes
from app.backend.server.module_storage_routes import register_module_storage_routes
from app.backend.server.params_workflow_routes import register_params_workflow_routes
from app.backend.server.prompt_tools_routes import register_prompt_tools_routes
from app.backend.server.result_display_routes import register_result_display_routes
from app.backend.server.state_routes import register_state_routes
from app.backend.server.style_thumbnail_routes import register_style_thumbnail_routes
from app.backend.server.web_shell_routes import register_web_shell_routes
from app.backend.server.websocket_broadcast import broadcast_json
from app.backend.server.websocket_session import register_websocket_session
from core.web_session_context import WebSessionContext


RunInThread = Callable[..., Awaitable[Any]]


def register_headless_routes(
    app: FastAPI,
    context: WebSessionContext,
    root_web_dir: Path,
    *,
    clients: set[WebSocket],
    run_in_thread: RunInThread,
) -> None:
    app.state.remote_web_dir = str(root_web_dir)
    register_web_shell_routes(app, root_web_dir)

    register_state_routes(
        app,
        context,
        run_in_thread=run_in_thread,
        clients=clients,
        broadcast_json=broadcast_json,
        start_generation_runner=ensure_generation_runner,
    )
    register_generation_rest_routes(
        app,
        context,
        clients=clients,
        start_generation_runner=ensure_generation_runner,
    )
    register_install_manager_routes(app, context, run_in_thread=run_in_thread)
    register_params_workflow_routes(
        app,
        context,
        run_in_thread=run_in_thread,
        clients=clients,
        broadcast_json=broadcast_json,
    )
    register_prompt_tools_routes(
        app,
        context,
        run_in_thread=run_in_thread,
        clients=clients,
        broadcast_json=broadcast_json,
        start_generation_runner=ensure_generation_runner,
    )
    register_style_thumbnail_routes(app, context, run_in_thread=run_in_thread)
    register_module_storage_routes(app, context, run_in_thread=run_in_thread)
    register_data_migration_routes(app, context, run_in_thread=run_in_thread)
    register_danbooru_routes(app, context, run_in_thread=run_in_thread)
    register_event_preset_routes(
        app,
        context,
        run_in_thread=run_in_thread,
        clients=clients,
        broadcast_json=broadcast_json,
        start_generation_runner=ensure_generation_runner,
    )
    register_artist_thumbnail_routes(
        app,
        context,
        run_in_thread=run_in_thread,
        clients=clients,
        start_generation_runner=ensure_generation_runner,
    )
    register_character_viewer_routes(
        app,
        context,
        run_in_thread=run_in_thread,
        clients=clients,
        start_generation_runner=ensure_generation_runner,
    )
    register_result_display_routes(
        app,
        context,
        run_in_thread=run_in_thread,
        clients=clients,
        broadcast_json=broadcast_json,
    )
    register_websocket_session(
        app,
        context,
        clients=clients,
        run_in_thread=run_in_thread,
        broadcast_json=broadcast_json,
        start_generation_runner=ensure_generation_runner,
    )
