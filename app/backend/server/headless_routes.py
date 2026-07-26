from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, WebSocket

from app.backend.server.artist_thumbnail_routes import register_artist_thumbnail_routes
from app.backend.server.character_asset_routes import register_character_asset_routes
from app.backend.server.character_viewer_routes import register_character_viewer_routes
from app.backend.server.data_migration_routes import register_data_migration_routes
from app.backend.server.danbooru_routes import register_danbooru_routes
from app.backend.server.grok_routes import register_grok_routes  # Grok 연동 (제거 가능)
from app.backend.server.event_preset_routes import register_event_preset_routes
from app.backend.server.extension_install_routes import register_extension_install_routes
from app.backend.server.font_routes import register_font_routes
from app.backend.server.interactive_thumbnail_routes import register_interactive_thumbnail_routes
from app.backend.server.interactive_advice_routes import register_interactive_advice_routes
from app.backend.server.generation_commands import register_generation_rest_routes
from app.backend.server.sequence_preset_routes import register_sequence_preset_routes
from app.backend.server.generation_runner import ensure_generation_runner
from app.backend.server.install_manager_routes import register_install_manager_routes
from app.backend.server.module_storage_routes import register_module_storage_routes
from app.backend.server.nai_model_routes import register_nai_model_routes
from app.backend.server.ollama_routes import register_ollama_routes
from app.backend.server.translation_history_routes import register_translation_history_routes
from app.backend.server.params_workflow_routes import register_params_workflow_routes
from app.backend.server.prompt_engineering_filter_routes import register_pe_filter_routes
from app.backend.server.prompt_tools_routes import register_prompt_tools_routes
from app.backend.server.result_display_routes import register_result_display_routes
from app.backend.server.state_routes import register_state_routes
from app.backend.server.style_thumbnail_routes import register_style_thumbnail_routes
from app.backend.server.web_shell_routes import register_web_shell_routes
from app.backend.server.websocket_broadcast import broadcast_json
from app.backend.server.websocket_session import register_websocket_session
from core.web_session_context import WebSessionContext


RunInThread = Callable[..., Awaitable[Any]]


def _register_extension_toast_bridge(context: WebSessionContext, clients: set[WebSocket]) -> None:
    """확장 → 사용자 토스트 브릿지(ctx.show_toast의 수신단).

    코어의 "extension_toast" 이벤트는 임의 스레드(이벤트 루프/생성 워커)에서
    발행되므로, lifespan이 캡처해 둔 메인 루프에 브로드캐스트를 예약한다."""
    import asyncio

    def _on_extension_toast(payload: Any) -> None:
        try:
            data = payload if isinstance(payload, dict) else {}
            message = str(data.get("message") or "").strip()
            if not message:
                return
            level = str(data.get("level") or "info")
            toast = {"type": "toast", "message": message[:300], "level": level}
            loop = getattr(context, "headless_main_loop", None)
            if loop is None:
                return
            loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(broadcast_json(clients, toast))
            )
        except Exception:
            pass

    context.subscribe("extension_toast", _on_extension_toast)


def _register_search_loading_bridge(context: WebSessionContext, clients: set[WebSocket]) -> None:
    """검색 풀 청크 로딩 진행률/완료 브릿지.

    코어(임의 스레드)의 chunked 로더가 발행하는 'search_pool_broadcast' 페이로드
    (search_loading WS 메시지)를 lifespan 이 캡처한 메인 루프에서 전 클라이언트로
    브로드캐스트한다. 프론트는 이 신호로 Tag/Tag Filter 를 잠그고 진행률을 표시한다."""
    import asyncio

    def _on_search_pool_broadcast(payload: Any) -> None:
        try:
            if not isinstance(payload, dict):
                return
            loop = getattr(context, "headless_main_loop", None)
            if loop is None:
                return
            loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(broadcast_json(clients, payload))
            )
        except Exception:
            pass

    context.subscribe("search_pool_broadcast", _on_search_pool_broadcast)


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
    _register_extension_toast_bridge(context, clients)
    _register_search_loading_bridge(context, clients)

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
    register_extension_install_routes(app, context, run_in_thread=run_in_thread)
    register_ollama_routes(app, context, run_in_thread=run_in_thread)
    register_translation_history_routes(app, context, run_in_thread=run_in_thread)
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
    register_font_routes(app, context, root_web_dir, run_in_thread=run_in_thread)
    register_nai_model_routes(
        app,
        context,
        run_in_thread=run_in_thread,
        clients=clients,
        broadcast_json=broadcast_json,
    )
    register_pe_filter_routes(app, context, run_in_thread=run_in_thread)
    register_module_storage_routes(app, context, run_in_thread=run_in_thread)
    register_data_migration_routes(app, context, run_in_thread=run_in_thread)
    register_danbooru_routes(app, context, run_in_thread=run_in_thread)
    register_grok_routes(app, context, run_in_thread=run_in_thread)  # Grok 연동 (제거 가능)
    register_event_preset_routes(
        app,
        context,
        run_in_thread=run_in_thread,
        clients=clients,
        broadcast_json=broadcast_json,
        start_generation_runner=ensure_generation_runner,
    )
    register_sequence_preset_routes(
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
    register_interactive_thumbnail_routes(app, context)
    register_interactive_advice_routes(app, context)
    register_character_viewer_routes(
        app,
        context,
        run_in_thread=run_in_thread,
        clients=clients,
        start_generation_runner=ensure_generation_runner,
    )
    register_character_asset_routes(
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
