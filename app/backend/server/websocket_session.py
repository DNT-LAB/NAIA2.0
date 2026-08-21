from __future__ import annotations

import asyncio
from functools import partial
import json
import uuid
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from core.seam_observer import seam_observer  # 관측 전용(기본 OFF) WS-command 계측

from app.backend.server.anlas_poller import (
    broadcast_anlas,
    broadcast_nai_usage,
    ensure_anlas_poller,
)
from app.backend.server.api_control_commands import (
    API_CONTROL_COMMAND_TYPES,
    handle_api_control_command,
)
from app.backend.server.autocomplete_commands import (
    AUTOCOMPLETE_COMMAND_TYPES,
    handle_autocomplete_command,
)
from app.backend.server.event_corpus_commands import (
    EVENT_CORPUS_COMMAND_TYPES,
    handle_event_corpus_command,
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

# B4: 무거운 라이브 태그필터 검색은 백그라운드 태스크로 디스패치한다 — receive 루프가 막히지
# 않아 검색이 도는 동안에도 다음 키 입력(autocomplete 등)이 즉시 읽혀 응답한다. 대형 풀(100만+
# 행)에서 첫 칩 검색이 수십 초 걸려도 UI(autocomplete)가 죽지 않게 하는 것이 목적.
# assign 은 B3 재사용으로 가벼워 인라인 유지(검색 결과 round-trip 이후에만 도착하므로 순서 보존).
# event_corpus_query 도 같은 이유로 백그라운드 디스패치한다(대형 파티션 집계).
# 단 seq 카운터는 커맨드 계열별로 분리한다 — 공유하면 태그필터 검색이 진행 중인 코퍼스
# 질의를 superseded 로 죽이고(그 반대도) 서로를 무효화한다.
LIVE_DISPATCH_TYPES = {"tag_filter_search", "event_corpus_query"}


async def _run_live_command(
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
    """백그라운드 태스크로 라이브 명령을 실행. 예외가 receive 루프로 새지 않도록 격리하고
    실패 시 토스트로 알린다(create_task 라 호출부 try/except 가 잡지 못함)."""
    try:
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
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        try:
            await ws.send_text(json.dumps(
                {"type": "toast", "message": f"Tag filter failed: {exc}", "level": "error"},
                ensure_ascii=False,
            ))
        except Exception:
            pass


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
        # B4: 동일 연결의 동시 send 를 직렬화한다 — 백그라운드 라이브-필터 태스크와 인라인 핸들러가
        # 동시에 보내도 프레임이 섞이지 않게(asyncio 단일 스레드라 Lock 1개로 충분). send_text/
        # send_bytes/send_json 이 모두 통과하는 ASGI 레벨 ws.send 를 감싸 전 경로를 직렬화한다
        # (send_text 만 감싸면 grok send_json·이미지 broadcast send_bytes 가 빠져나간다 — Codex 지적).
        _raw_send = ws.send
        _send_lock = asyncio.Lock()

        async def _locked_send(message, *args, **kwargs):
            async with _send_lock:
                return await _raw_send(message, *args, **kwargs)

        ws.send = _locked_send  # type: ignore[method-assign]
        live_tasks: set[asyncio.Task] = set()
        # 커맨드 계열별 최신 in-flight task. 새 요청이 오면 이전 것을 취소해 적재를 막는다.
        live_by_type: dict[str, asyncio.Task] = {}
        # Latest-search ownership is per websocket. A search typed in another
        # browser tab must not supersede this tab's still-valid result.
        tag_filter_seq_guard = {"seq": 0}
        event_corpus_seq_guard = {"seq": 0}
        live_seq_guards = {
            "tag_filter_search": tag_filter_seq_guard,
            "event_corpus_query": event_corpus_seq_guard,
        }
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
            # **V5 사용량 한도는 폴링하지 않는다.** 프로그램을 켠 첫 상태가 V5 면
            # 여기서 1회, 그 뒤로는 모델/모드가 V5 로 바뀔 때만 조회한다(사용자 지정
            # 2026-08-19). V5 가 아니면 네트워크를 타지 않는다.
            await broadcast_nai_usage(context, clients)
            while True:
                data = await ws.receive_text()
                if data.startswith("{"):
                    try:
                        command = json.loads(data)
                    except json.JSONDecodeError:
                        command = {"type": ""}
                    if isinstance(command, dict):
                        ctype = str(command.get("type") or "").strip()
                        if ctype in {"tag_filter_search", "tag_filter_assign"}:
                            command["_tag_filter_client_key"] = session_id
                        if ctype in LIVE_DISPATCH_TYPES:
                            # B4: 무거운 검색을 백그라운드로 — receive 루프는 즉시 다음 메시지를
                            # 읽어 autocomplete 가 검색 중에도 응답한다. seq 로 superseded 검색 폐기.
                            guard = live_seq_guards[ctype]
                            guard["seq"] += 1
                            seq = guard["seq"]
                            command["_seq"] = seq
                            command["_seq_guard"] = guard
                            # 계열당 in-flight 1개로 제한한다. seq guard 는 stale 결과의
                            # '전송'만 막을 뿐 task/future 적재는 막지 못한다 — 칩을 연타하면
                            # 죽은 집계들이 executor worker 를 계속 점유한다.
                            # (to_thread 취소가 스레드를 멈추지는 않지만, 콜백과 송신은 끊기고
                            #  task 누적은 사라진다. 서비스 쪽 should_abort 가 청크 경계에서
                            #  협조적으로 빠져나온다.)
                            previous = live_by_type.get(ctype)
                            if previous is not None and not previous.done():
                                previous.cancel()
                            live_task = asyncio.create_task(_run_live_command(
                                ws,
                                context,
                                clients,
                                client_host,
                                command,
                                run_in_thread=run_in_thread,
                                broadcast_json=broadcast_json,
                                start_generation_runner=start_generation_runner,
                            ))
                            live_tasks.add(live_task)
                            live_by_type[ctype] = live_task
                            live_task.add_done_callback(live_tasks.discard)
                        else:
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
            # 연결 종료 시 백그라운드 라이브-필터 태스크 정리(누수/끊긴 소켓 send 방지).
            for _task in list(live_tasks):
                _task.cancel()
            guard = getattr(context, "search_pool_state_guard", None)
            if callable(guard):
                with guard():
                    pending_by_client = getattr(context, "pending_tag_filters", None)
                    pending = (
                        pending_by_client.pop(session_id, None)
                        if isinstance(pending_by_client, dict) else None
                    )
                    if getattr(context, "pending_tag_filter", None) is pending:
                        context.pending_tag_filter = None
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
    if seam_observer.enabled:
        seam_observer.observe_command(command_type)
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
            clients=clients,
            broadcast_json=broadcast_json,
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
    elif command_type in EVENT_CORPUS_COMMAND_TYPES:
        await handle_event_corpus_command(
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
