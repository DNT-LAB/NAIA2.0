from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, WebSocket

from app.backend.server.artist_thumbnail_routes import register_artist_thumbnail_routes
from app.backend.server.character_asset_routes import register_character_asset_routes
from app.backend.server.character_viewer_routes import register_character_viewer_routes
from app.backend.server.v5_scene_routes import register_v5_scene_routes
from app.backend.server.data_migration_routes import register_data_migration_routes
from app.backend.server.danbooru_routes import register_danbooru_routes
from app.backend.server.grok_routes import register_grok_routes  # Grok 연동 (제거 가능)
from app.backend.server.event_preset_routes import register_event_preset_routes
from app.backend.server.extension_install_routes import register_extension_install_routes
from app.backend.server.font_routes import register_font_routes
from app.backend.server.interactive_thumbnail_routes import register_interactive_thumbnail_routes
from app.backend.server.interactive_advice_routes import register_interactive_advice_routes
from app.backend.server.tag_combo_routes import register_tag_combo_routes
from app.backend.server.interactive_assets_routes import register_interactive_assets_routes
from app.backend.server.interactive_reference_routes import (
    register_interactive_reference_routes,
)
from app.backend.server.generation_commands import register_generation_rest_routes
from app.backend.server.inpaint_sequence_routes import register_inpaint_sequence_routes
from app.backend.server.sequence_preset_routes import register_sequence_preset_routes
from app.backend.server.generation_runner import ensure_generation_runner
from app.backend.server.install_manager_routes import register_install_manager_routes
from app.backend.server.module_storage_routes import register_module_storage_routes
from app.backend.server.nai_model_routes import register_nai_model_routes
from app.backend.server.ollama_routes import register_ollama_routes
from app.backend.server.tagger_routes import register_tagger_routes
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


def _register_extension_queue_bridge(context: WebSessionContext, clients: set[WebSocket]) -> None:
    """확장 → 생성 러너 기동 브릿지(ctx.start_generation_queue의 수신단).

    ``enqueue_generation``은 큐에 넣기만 하고, 소비 루프는 큐가 비면 끝난다.
    패널 버튼처럼 **생성 흐름 밖에서** 넣은 요청은 이 브릿지가 러너를 깨워야
    소비된다. 코어(``core/``)가 ``app/backend`` 의 러너를 직접 import 할 수는
    없으므로 토스트와 같은 이벤트 브릿지 모양을 쓴다.

    ``extension_queue_start_bridge`` 를 컨텍스트에 달아 둔다 — 코어가 "받는 쪽이
    있는가" 를 정직하게 판단하는 근거다(없으면 ok=False 로 돌린다)."""
    import asyncio

    def _on_queue_start(payload: Any) -> None:
        try:
            loop = getattr(context, "headless_main_loop", None)
            if loop is None:
                return
            # ensure_generation_runner 는 멱등이다(돌고 있으면 no-op). 다만 태스크
            # 생성이므로 반드시 메인 루프 위에서 불러야 한다.
            loop.call_soon_threadsafe(lambda: ensure_generation_runner(context, clients))
        except Exception:
            pass

    context.subscribe("extension_queue_start", _on_queue_start)
    context.extension_queue_start_bridge = _on_queue_start


def _register_extension_confirm_bridge(context: WebSessionContext, clients: set[WebSocket]) -> None:
    """확장 → 사용자 확인 대화 브릿지(ctx.request_confirmation의 수신단).

    사용자의 선택은 프런트가 ``set_module_param`` 으로 되돌려 보내며, 그것은
    패널 action 버튼을 누른 것과 **같은 경로**다(선언된 action 필드만 실행된다).

    ``extension_confirm_reach`` 로 현재 붙은 클라이언트 수를 코어에 노출한다 —
    아무도 없는데 "띄웠다" 고 답하면 확장이 오지 않을 답을 기다린다."""
    import asyncio

    def _on_confirm(payload: Any) -> None:
        try:
            if not isinstance(payload, dict):
                return
            loop = getattr(context, "headless_main_loop", None)
            if loop is None:
                return
            message = dict(payload)
            message["type"] = "extension_confirm"
            loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(broadcast_json(clients, message))
            )
        except Exception:
            pass

    context.subscribe("extension_confirm", _on_confirm)
    context.extension_confirm_reach = lambda: len(clients)


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
    _register_extension_queue_bridge(context, clients)
    _register_extension_confirm_bridge(context, clients)

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
    register_tagger_routes(app, context, run_in_thread=run_in_thread)
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
    register_inpaint_sequence_routes(
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
    register_interactive_advice_routes(app, context, run_in_thread=run_in_thread)
    register_tag_combo_routes(app, context, run_in_thread=run_in_thread)
    register_interactive_assets_routes(app, context, run_in_thread=run_in_thread)
    register_interactive_reference_routes(app, context, run_in_thread=run_in_thread)
    register_v5_scene_routes(app, context, run_in_thread=run_in_thread)
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
