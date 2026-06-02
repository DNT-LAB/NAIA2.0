from __future__ import annotations

from functools import partial
import json
import uuid
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from app.backend.server.anlas_poller import broadcast_anlas, ensure_anlas_poller
from app.backend.server.api_control_commands import (
    API_CONTROL_COMMAND_TYPES,
    handle_api_control_command,
)
from app.backend.server.autocomplete_commands import (
    AUTOCOMPLETE_COMMAND_TYPES,
    handle_autocomplete_command,
)
from app.backend.server.depth_search_commands import (
    DEPTH_SEARCH_COMMAND_TYPES,
    handle_depth_search_command,
)
from app.backend.server.generation_commands import (
    GENERATION_COMMAND_TYPES,
    enqueue_generation_request,
    enqueue_headless_generation_commands,
    enqueue_prompt_from_module,
    handle_bootstrap_random_command,
    handle_depth_generate_command,
    handle_generate_command,
    handle_random_command,
)
from app.backend.server.grok_i2i_commands import (  # Grok I2I (제거 가능)
    GROK_I2I_COMMAND_TYPES,
    handle_grok_command,
)
from app.backend.server.grok_i2v_commands import (  # Grok I2V (제거 가능)
    GROK_ANIMATE_COMMAND_TYPES,
    GROK_I2V_COMMAND_TYPES,
    handle_grok_animate_command,
    handle_grok_video_command,
)
from app.backend.server.nai_director_commands import (  # NAI Director Tools (제거 가능)
    NAI_DIRECTOR_COMMAND_TYPES,
    handle_nai_director_command,
)
from app.backend.server.module_commands import (
    MODULE_COMMAND_TYPES,
    handle_module_command,
)
from app.backend.server.prompt_engineering_commands import (
    HIRES_OVERLAY_COMMAND_TYPES,
    handle_hires_overlay_command,
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
    refresh_active_api_options_if_configured,
    send_sync_messages,
)
from core.web_session_context import WebSessionContext


RunInThread = Callable[..., Awaitable[Any]]
BroadcastJson = Callable[[set[WebSocket], dict[str, Any]], Awaitable[None]]
GenerationRunnerStarter = Callable[[WebSessionContext, set[WebSocket]], None]


def register_websocket_session(
    app: FastAPI,
    context: WebSessionContext,
    *,
    clients: set[WebSocket],
    run_in_thread: RunInThread,
    broadcast_json: BroadcastJson,
    start_generation_runner: GenerationRunnerStarter,
) -> None:
    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await ws.accept()
        clients.add(ws)
        session_id = uuid.uuid4().hex[:8]
        client_host = client_host_from_websocket(ws)
        try:
            await send_startup_messages(
                ws,
                context,
                run_in_thread=run_in_thread,
                session_id=session_id,
                client_host=client_host,
            )
            ensure_anlas_poller(context, clients)
            await broadcast_anlas(context, clients)
            while True:
                data = await ws.receive_text()
                if data.startswith("{"):
                    try:
                        command = json.loads(data)
                    except json.JSONDecodeError:
                        command = {"type": ""}
                    if isinstance(command, dict):
                        await handle_json_command(
                            ws,
                            context,
                            clients,
                            client_host,
                            command,
                            run_in_thread=run_in_thread,
                            broadcast_json=broadcast_json,
                            start_generation_runner=start_generation_runner,
                        )
                    else:
                        await handle_text_command(
                            ws,
                            context,
                            clients,
                            client_host,
                            data,
                            run_in_thread=run_in_thread,
                            start_generation_runner=start_generation_runner,
                        )
                else:
                    await handle_text_command(
                        ws,
                        context,
                        clients,
                        client_host,
                        data,
                        run_in_thread=run_in_thread,
                        start_generation_runner=start_generation_runner,
                    )
        except WebSocketDisconnect:
            clients.discard(ws)
            return
        finally:
            clients.discard(ws)


def client_host_from_websocket(ws: WebSocket) -> str:
    try:
        if ws.client is not None:
            host = str(ws.client.host or "")
            if host == "testclient":
                return "127.0.0.1"
            return host
    except Exception:
        pass
    return ""


async def send_startup_messages(
    ws: WebSocket,
    context: WebSessionContext,
    *,
    run_in_thread: RunInThread,
    session_id: str,
    client_host: str,
) -> None:
    await refresh_active_api_options_if_configured(context, run_in_thread=run_in_thread)
    for message in context.initial_websocket_messages(
        session_id=session_id,
        client_host=client_host,
    ):
        await ws.send_text(json.dumps(message, ensure_ascii=False))
    await ws.send_text(json.dumps({"type": "lazy_indices_ready"}))


async def handle_json_command(
    ws: WebSocket,
    context: WebSessionContext,
    clients: set[WebSocket],
    client_host: str,
    command: dict[str, Any],
    *,
    run_in_thread: RunInThread,
    broadcast_json: BroadcastJson,
    start_generation_runner: GenerationRunnerStarter,
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
            run_in_thread=run_in_thread,
        )
    elif command_type in SEARCH_COMMAND_TYPES:
        await handle_search_command(
            ws,
            context,
            command,
            run_in_thread=run_in_thread,
        )
    elif command_type in API_CONTROL_COMMAND_TYPES:
        await handle_api_control_command(
            ws,
            context,
            client_host,
            command,
            run_in_thread=run_in_thread,
        )
    elif command_type in AUTOCOMPLETE_COMMAND_TYPES:
        await handle_autocomplete_command(
            ws,
            context,
            command,
            run_in_thread=run_in_thread,
        )
    elif command_type in DEPTH_SEARCH_COMMAND_TYPES:
        await handle_depth_search_command(
            ws,
            context,
            command,
            run_in_thread=run_in_thread,
        )
    elif command_type in HIRES_OVERLAY_COMMAND_TYPES:
        await handle_hires_overlay_command(
            ws,
            context,
            command,
            run_in_thread=run_in_thread,
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
                start_generation_runner=start_generation_runner,
            ),
            enqueue_generation_commands=partial(
                enqueue_headless_generation_commands,
                start_generation_runner=start_generation_runner,
            ),
        )
    elif command_type in RESULT_COMMAND_TYPES:
        await handle_result_command(
            ws,
            context,
            clients,
            command,
            run_in_thread=run_in_thread,
            enqueue_generation_request=enqueue_generation_request,
            start_generation_runner=start_generation_runner,
        )
    elif command_type in GROK_I2I_COMMAND_TYPES:  # Grok I2I (제거 가능)
        await handle_grok_command(
            ws,
            context,
            clients,
            command,
            run_in_thread=run_in_thread,
        )
    elif command_type in GROK_I2V_COMMAND_TYPES:  # Grok I2V (제거 가능)
        await handle_grok_video_command(
            ws,
            context,
            clients,
            command,
            run_in_thread=run_in_thread,
        )
    elif command_type in GROK_ANIMATE_COMMAND_TYPES:  # Grok 영상 프리뷰 (제거 가능)
        await handle_grok_animate_command(
            ws,
            context,
            clients,
            command,
            run_in_thread=run_in_thread,
        )
    elif command_type in NAI_DIRECTOR_COMMAND_TYPES:  # NAI Director Tools (제거 가능)
        await handle_nai_director_command(
            ws,
            context,
            clients,
            command,
            run_in_thread=run_in_thread,
        )
    elif command_type in GENERATION_COMMAND_TYPES:
        if command_type == "bootstrap_random":
            await handle_bootstrap_random_command(
                ws,
                context,
                clients,
                command,
                broadcast_json=broadcast_json,
            )
        elif command_type == "random":
            await handle_random_command(
                ws,
                context,
                clients,
                command,
                start_generation_runner=start_generation_runner,
            )
        elif command_type == "depth_generate":
            await handle_depth_generate_command(
                ws,
                context,
                clients,
                command,
                start_generation_runner=start_generation_runner,
            )
        else:
            await handle_generate_command(
                ws,
                context,
                clients,
                command,
                start_generation_runner=start_generation_runner,
            )
    else:
        await ws.send_text(json.dumps({
            "type": "toast",
            "level": "info",
            "message": f"Unsupported command ignored: {command_type or 'unknown'}",
        }, ensure_ascii=False))


async def handle_text_command(
    ws: WebSocket,
    context: WebSessionContext,
    clients: set[WebSocket],
    client_host: str,
    data: str,
    *,
    run_in_thread: RunInThread,
    start_generation_runner: GenerationRunnerStarter,
) -> None:
    if data == "sync":
        await send_sync_messages(ws, context, client_host, run_in_thread=run_in_thread)
        return
    if data == "random":
        await handle_random_command(
            ws,
            context,
            clients,
            start_generation_runner=start_generation_runner,
        )
        return
    if data == "generate":
        await handle_generate_command(
            ws,
            context,
            clients,
            start_generation_runner=start_generation_runner,
        )
        return
    await ws.send_text(json.dumps({
        "type": "toast",
        "level": "info",
        "message": f"Unsupported command ignored: {data}",
    }, ensure_ascii=False))
