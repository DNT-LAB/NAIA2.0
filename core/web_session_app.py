"""PyQt-free FastAPI app for the headless Remote Web Session path."""

from __future__ import annotations

from contextlib import asynccontextmanager
from functools import partial
import json
import asyncio
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from app.backend.server.autocomplete_commands import (
    AUTOCOMPLETE_COMMAND_TYPES,
    ensure_tag_search_index,
    handle_autocomplete_command,
)
from app.backend.server.api_control_commands import (
    API_CONTROL_COMMAND_TYPES,
    handle_api_control_command,
)
from app.backend.server.artist_thumbnail_routes import register_artist_thumbnail_routes
from app.backend.server.character_viewer_routes import register_character_viewer_routes
from app.backend.server.danbooru_routes import register_danbooru_routes
from app.backend.server.depth_search_commands import (
    DEPTH_SEARCH_COMMAND_TYPES,
    handle_depth_search_command,
)
from app.backend.server.event_preset_routes import register_event_preset_routes
from app.backend.server.generation_commands import (
    GENERATION_COMMAND_TYPES,
    enqueue_generation_request,
    enqueue_headless_generation_commands,
    enqueue_prompt_from_module,
    handle_generate_command,
    handle_random_command,
    random_service,
)
from app.backend.server.generation_runner import ensure_generation_runner
from app.backend.server.install_manager_routes import register_install_manager_routes
from app.backend.server.headless_retired_commands import (
    HEADLESS_RETIRED_COMMAND_TYPES,
    handle_headless_retired_command,
)
from app.backend.server.module_commands import (
    MODULE_COMMAND_TYPES,
    handle_module_command,
)
from app.backend.server.params_workflow_routes import register_params_workflow_routes
from app.backend.server.prompt_engineering_commands import (
    HIRES_OVERLAY_COMMAND_TYPES,
    handle_hires_overlay_command,
)
from app.backend.server.prompt_tools_routes import register_prompt_tools_routes
from app.backend.server.result_display_routes import (
    register_result_display_routes,
)
from app.backend.server.result_commands import (
    RESULT_COMMAND_TYPES,
    handle_result_command,
)
from app.backend.server.search_commands import (
    SEARCH_COMMAND_TYPES,
    handle_search_command,
)
from app.backend.server.session_commands import (
    SESSION_COMMAND_TYPES,
    handle_session_command,
    send_sync_messages,
)
from app.backend.server.state_routes import register_state_routes
from app.backend.server.style_thumbnail_routes import register_style_thumbnail_routes
from app.backend.server.web_shell_routes import register_web_shell_routes
from app.backend.server.websocket_broadcast import broadcast_json
from app.web import resolve_remote_web_dir
from core.web_session_context import WebSessionContext


def _client_host(ws: WebSocket) -> str:
    try:
        if ws.client is not None:
            host = str(ws.client.host or "")
            if host == "testclient":
                return "127.0.0.1"
            return host
    except Exception:
        pass
    return ""


def _no_cache_headers() -> dict[str, str]:
    return {"Cache-Control": "no-store, max-age=0"}


async def _send_startup_messages(
    ws: WebSocket,
    context: WebSessionContext,
    *,
    session_id: str,
    client_host: str,
) -> None:
    for message in context.initial_websocket_messages(
        session_id=session_id,
        client_host=client_host,
    ):
        await ws.send_text(json.dumps(message, ensure_ascii=False))
    await ws.send_text(json.dumps({"type": "lazy_indices_ready"}))


async def _handle_json_command(
    ws: WebSocket,
    context: WebSessionContext,
    clients: set[WebSocket],
    client_host: str,
    command: dict[str, Any],
) -> None:
    command_type = str(command.get("type") or "").strip()
    if command_type in SESSION_COMMAND_TYPES:
        await handle_session_command(
            ws,
            context,
            clients,
            client_host,
            command,
            broadcast_json=broadcast_json,
        )
    elif command_type in SEARCH_COMMAND_TYPES:
        await handle_search_command(
            ws,
            context,
            command,
            run_in_thread=_to_thread,
        )
    elif command_type in API_CONTROL_COMMAND_TYPES:
        await handle_api_control_command(
            ws,
            context,
            client_host,
            command,
            run_in_thread=_to_thread,
        )
    elif command_type in HEADLESS_RETIRED_COMMAND_TYPES:
        await handle_headless_retired_command(ws, context, client_host, command)
    elif command_type in AUTOCOMPLETE_COMMAND_TYPES:
        await handle_autocomplete_command(
            ws,
            context,
            command,
            run_in_thread=_to_thread,
        )
    elif command_type in DEPTH_SEARCH_COMMAND_TYPES:
        await handle_depth_search_command(
            ws,
            context,
            command,
            run_in_thread=_to_thread,
        )
    elif command_type in HIRES_OVERLAY_COMMAND_TYPES:
        await handle_hires_overlay_command(
            ws,
            context,
            command,
            run_in_thread=_to_thread,
        )
    elif command_type in MODULE_COMMAND_TYPES:
        await handle_module_command(
            ws,
            context,
            clients,
            client_host,
            command,
            enqueue_prompt_from_module=partial(
                enqueue_prompt_from_module,
                start_generation_runner=ensure_generation_runner,
            ),
            enqueue_generation_commands=partial(
                enqueue_headless_generation_commands,
                start_generation_runner=ensure_generation_runner,
            ),
        )
    elif command_type in RESULT_COMMAND_TYPES:
        await handle_result_command(
            ws,
            context,
            clients,
            command,
            run_in_thread=_to_thread,
            enqueue_generation_request=enqueue_generation_request,
            start_generation_runner=ensure_generation_runner,
        )
    elif command_type in GENERATION_COMMAND_TYPES:
        if command_type == "random":
            await handle_random_command(ws, context, command)
        else:
            await handle_generate_command(
                ws,
                context,
                clients,
                command,
                start_generation_runner=ensure_generation_runner,
            )
    else:
        await ws.send_text(json.dumps({
            "type": "toast",
            "level": "info",
            "message": f"Headless command ignored: {command_type or 'unknown'}",
        }, ensure_ascii=False))


async def _handle_text_command(
    ws: WebSocket,
    context: WebSessionContext,
    clients: set[WebSocket],
    client_host: str,
    data: str,
) -> None:
    if data == "sync":
        await send_sync_messages(ws, context, client_host)
        return
    if data == "random":
        await handle_random_command(ws, context)
        return
    if data == "generate":
        await handle_generate_command(
            ws,
            context,
            clients,
            start_generation_runner=ensure_generation_runner,
        )
        return
    await ws.send_text(json.dumps({
        "type": "toast",
        "level": "info",
        "message": f"Headless command ignored: {data}",
    }, ensure_ascii=False))


async def _to_thread(func, /, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)


def create_headless_app(
    context: WebSessionContext | None = None,
    *,
    web_dir: Path | str | None = None,
) -> FastAPI:
    """Create the PyQt-free Remote Web FastAPI app."""

    session_context = context or WebSessionContext()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        async def run_warmup() -> None:
            try:
                ok = await _to_thread(random_service(session_context).warmup)
                session_context.headless_random_warmup_done = bool(ok)
                print(
                    "Headless Remote: random prompt runtime warmup "
                    + ("ready" if ok else "finished without search rows"),
                    flush=True,
                )
            except Exception as exc:
                session_context.headless_random_warmup_error = str(exc)
                print(f"Headless Remote: random prompt runtime warmup failed - {exc}", flush=True)

        async def run_tag_index_warmup() -> None:
            try:
                await _to_thread(ensure_tag_search_index, session_context)
                print(
                    f"Headless Remote: tag autocomplete index ready ({len(getattr(session_context, 'kr_tags_raw', {}) or {}):,} tags)",
                    flush=True,
                )
            except Exception as exc:
                session_context.headless_tag_index_warmup_error = str(exc)
                print(f"Headless Remote: tag autocomplete index warmup failed - {exc}", flush=True)

        task = getattr(session_context, "headless_random_warmup_task", None)
        if task is None or task.done():
            session_context.headless_random_warmup_task = asyncio.create_task(run_warmup())
        tag_task = getattr(session_context, "headless_tag_index_warmup_task", None)
        if tag_task is None or tag_task.done():
            session_context.headless_tag_index_warmup_task = asyncio.create_task(run_tag_index_warmup())
        yield

    app = FastAPI(title="NAIA Remote Headless", lifespan=lifespan)
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

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await ws.accept()
        clients: set[WebSocket] = app.state.headless_clients
        clients.add(ws)
        session_id = uuid.uuid4().hex[:8]
        client_host = _client_host(ws)
        try:
            await _send_startup_messages(
                ws,
                session_context,
                session_id=session_id,
                client_host=client_host,
            )
            while True:
                data = await ws.receive_text()
                if data.startswith("{"):
                    try:
                        command = json.loads(data)
                    except json.JSONDecodeError:
                        command = {"type": ""}
                    if isinstance(command, dict):
                        await _handle_json_command(ws, session_context, clients, client_host, command)
                    else:
                        await _handle_text_command(ws, session_context, clients, client_host, data)
                else:
                    await _handle_text_command(ws, session_context, clients, client_host, data)
        except WebSocketDisconnect:
            clients.discard(ws)
            return
        finally:
            clients.discard(ws)

    return app


__all__ = ["create_headless_app"]
