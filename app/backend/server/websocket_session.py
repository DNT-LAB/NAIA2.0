from __future__ import annotations

import asyncio
from functools import partial
import json
import uuid
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from core.seam_observer import seam_observer  # 관측 전용(기본 OFF) WS-command 계측

from app.backend.server.anlas_poller import (
    ensure_anlas_poller,
    note_usage_badge_model,
    refresh_usage_if_model_changed,
    schedule_subscription_refresh,
)
from app.backend.server.api_control_commands import (
    API_CONTROL_COMMAND_TYPES,
    handle_api_control_command,
)
from app.backend.server.nai_account_commands import (
    NAI_ACCOUNT_COMMAND_TYPES,
    handle_nai_account_command,
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
from core.temporary_search import temporary_search
from app.backend.server.temporary_search_commands import (
    TEMPORARY_SEARCH_COMMAND_TYPES, command_workspace, finish_thread_call,
    handle_temporary_search_command, recover_disconnected_owner,
    register_search_workspace_http_boundary, send_state as send_temporary_search_state,
)


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

# 2026-10-30: get_search_state 뒤 Quick Preset 응답이 실측 37초 대기했다.
# 다른 소켓은 풀 복원 중에도 실행되므로, 이 연결에서 검색에 의존하는 명령만 lane 으로 기다린다.
# 검색 의존 = handle_json_command 의 scoped + 임시 검색 + 생성 시작 명령 + live + text.
# 비검색 명령은 검색 의존 항목을 추월하되, 먼저 큐에 든 비검색 항목은 추월하지 않는다(FIFO).
# 인라인 실행은 모든 대기 항목을 추월할 수 있을 때만. bootstrap_random 은 기존 사전 조회만 우회한다.
HEAVY_DISPATCH_TYPES = {"get_search_state", "bootstrap_random"}
HEAVY_LANE_BYPASS = {
    "tag_search", "tag_filter_ac", "autocomplete", "autocomplete_translate",
    "autocomplete_vibe_cluster", "translate_text", "interactive_autocomplete", "interactive_related",
}
SEARCH_DEPENDENT_TYPES = (
    TEMPORARY_SEARCH_COMMAND_TYPES | SEARCH_COMMAND_TYPES | DEPTH_SEARCH_COMMAND_TYPES | GENERATION_COMMAND_TYPES
    | LIVE_DISPATCH_TYPES | GROK_I2I_COMMAND_TYPES | GROK_I2V_COMMAND_TYPES | NAI_DIRECTOR_COMMAND_TYPES
    | {"tag_filter_assign", "result_enhance", "result_upscale", "result_outpaint"}
)
GENERATION_MODULE_KEYS = {
    "e621_event": {"generate"},
    "img2img": {"generate"},
    "storyteller": {"run_cycle"},
    "automation": {"start", "persist_automation"},  # Auto Gen 을 켜 진행 중인 생성 루프를 이어갈 수 있다.
}


def _is_search_dependent(command: dict[str, Any] | str) -> bool:
    if not isinstance(command, dict):
        return True
    ctype = str(command.get("type") or "").strip()
    if ctype in SEARCH_DEPENDENT_TYPES:
        return True
    key = str(command.get("key") or "").strip()
    if ctype == "set_option":
        return key in {"stop_autogen_on_tag_exhaust", "auto_generate"}
    if ctype == "set_module_param":
        module_id = str(command.get("module_id") or "").strip()
        # 확장 setting:* 는 일반 값뿐 아니라 생성/큐 시작이 가능한 action 콜백도 실행한다.
        return key in GENERATION_MODULE_KEYS.get(module_id, ()) or (
            module_id == "extensions" and key.startswith("setting:")
        )
    return False


def _may_overtake(command: dict[str, Any], pending: dict[str, Any] | str) -> bool:
    if _is_search_dependent(command):
        return False
    if isinstance(pending, dict) and str(pending.get("type") or "").strip() == "bootstrap_random":
        ctype = str(command.get("type") or "").strip()
        e621_read = ctype == "autocomplete" and str(command.get("source") or "") == "e621"
        return ctype in HEAVY_LANE_BYPASS and not e621_read
    return _is_search_dependent(pending)


async def _run_lane_command(
    ws: WebSocket,
    context: WebSessionContext,
    clients: set[WebSocket],
    client_host: str,
    command: dict[str, Any] | str,
    *,
    run_in_thread: RunInThread,
    broadcast_json: BroadcastJson,
    start_generation_runner: GenerationRunnerStarter,
    after: asyncio.Task | None,
) -> None:
    """앞서 큐에 들어온 lane 항목 뒤에 실행하고, 실패해도 다음 항목은 진행한다."""
    try:
        if after is not None:
            await asyncio.shield(after)
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
            refresh_usage_if_model_changed(context, clients)
        else:
            await handle_text_command(
                ws,
                context,
                clients,
                client_host,
                command,
                run_in_thread=run_in_thread,
                start_generation_runner=start_generation_runner,
            )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        ctype = str(command.get("type") or "").strip() if isinstance(command, dict) else command
        print(f"[warn] lane WebSocket command {ascii(ctype)} failed: {ascii(exc)}", flush=True)
        try:
            await ws.send_text(json.dumps(
                {"type": "toast", "message": f"{ctype} failed: {exc}", "level": "error"},
                ensure_ascii=False,
            ))
        except Exception:
            pass


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
    after: asyncio.Task | None = None,
) -> None:
    """백그라운드 태스크로 라이브 명령을 실행. 예외가 receive 루프로 새지 않도록 격리하고
    실패 시 토스트로 알린다(create_task 라 호출부 try/except 가 잡지 못함)."""
    try:
        if after is not None:
            # 최신 live 요청의 취소가 공유 lane 작업까지 취소하면 안 된다.
            await asyncio.shield(after)
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
    register_search_workspace_http_boundary(app, context)
    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await ws.accept()
        clients.add(ws)
        session_id = uuid.uuid4().hex[:8]
        ws._search_session_id = session_id
        client_host = client_host_from_websocket(ws)
        # B4: 동일 연결의 동시 send 를 직렬화한다 — 백그라운드 라이브-필터 태스크와 인라인 핸들러가
        # 동시에 보내도 프레임이 섞이지 않게(asyncio 단일 스레드라 Lock 1개로 충분). send_text/
        # send_bytes/send_json 이 모두 통과하는 ASGI 레벨 ws.send 를 감싸 전 경로를 직렬화한다
        # (send_text 만 감싸면 grok send_json·이미지 broadcast send_bytes 가 빠져나간다 — Codex 지적).
        _raw_send = ws.send
        _send_lock = asyncio.Lock()
        connection_closed = False

        async def _locked_send(message, *args, **kwargs):
            if message.get("text", "").startswith("{"):
                payload = json.loads(message["text"])
                payload["_search_workspace"] = command_workspace.get() or temporary_search(context).workspace_id
                message = {**message, "text": json.dumps(payload, ensure_ascii=False)}
            async with _send_lock:
                # finish_thread_call 은 취소 뒤에도 내부 작업을 마칠 수 있다. 끊긴 소켓에는 보내지 않는다.
                if connection_closed:
                    return
                return await _raw_send(message, *args, **kwargs)

        ws.send = _locked_send  # type: ignore[method-assign]
        live_tasks: set[asyncio.Task] = set()
        lane_tasks: dict[asyncio.Task, dict[str, Any] | str] = {}
        lane_tail: asyncio.Task | None = None

        def enqueue_lane(command: dict[str, Any] | str) -> None:
            nonlocal lane_tail
            task = asyncio.create_task(_run_lane_command(
                ws,
                context,
                clients,
                client_host,
                command,
                run_in_thread=run_in_thread,
                broadcast_json=broadcast_json,
                start_generation_runner=start_generation_runner,
                after=lane_tail,
            ))
            lane_tasks[task] = command
            lane_tail = task
            task.add_done_callback(lane_tasks.pop)

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
            # **V5 사용량 한도는 폴링하지 않는다.** 켠 첫 상태가 V5 면 여기서 1회,
            # 그 뒤로는 모델/모드가 바뀔 때만 조회한다(사용자 지정 2026-08-19).
            # Anlas 와 **같은 요청 하나**로 받는다 - 따로 부르면 이 API 의 산발적
            # read timeout 때문에 한쪽만 실패한다(실측: Anlas 는 떴는데 배지만 없음).
            #
            # 여기서도 기다리지 않는다 - 기다리면 아래 수신 루프 진입이 늦어져
            # 접속 직후 사용자가 누른 것들이 최대 16초 동안 먹히지 않는다.
            schedule_subscription_refresh(context, clients)
            note_usage_badge_model(context)
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
                        if ctype in HEAVY_DISPATCH_TYPES:
                            enqueue_lane(command)
                        elif ctype in LIVE_DISPATCH_TYPES:
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
                                after=lane_tail,
                            ))
                            live_tasks.add(live_task)
                            live_by_type[ctype] = live_task
                            live_task.add_done_callback(live_tasks.discard)
                        else:
                            if any(not task.done() and not _may_overtake(command, pending)
                                   for task, pending in lane_tasks.items()):
                                enqueue_lane(command)
                                continue
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
                            # 이 커맨드가 모델을 바꿨으면 사용량 배지를 갱신한다.
                            # ⚠️ 모델을 바꾸는 길이 여럿이라(프리셋 적용은 핸들러를
                            # 안 거치고 set_param 을 직접 부른다) 커맨드별로 걸지 않고
                            # **결과**를 본다. 안 바뀌었으면 비용은 조회 한 번이다.
                            refresh_usage_if_model_changed(context, clients)
                    else:
                        if lane_tail is not None and not lane_tail.done():
                            enqueue_lane(data)
                            continue
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
                    if lane_tail is not None and not lane_tail.done():
                        enqueue_lane(data)
                        continue
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
            connection_closed = True
            recover_disconnected_owner(context, clients, session_id,
                                       run_in_thread=run_in_thread, broadcast_json=broadcast_json)
            # 연결 종료 시 라이브/lane 태스크 정리(누수/끊긴 소켓 send 방지).
            for _task in list(live_tasks | set(lane_tasks)):
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
    await send_temporary_search_state(ws, temporary_search(context))
    await refresh_active_api_options_if_configured(context, run_in_thread=run_in_thread)
    for message in context.initial_websocket_messages(
        session_id=session_id,
        client_host=client_host,
    ):
        await ws.send_text(json.dumps(message, ensure_ascii=False))
    await ws.send_text(json.dumps({"type": "lazy_indices_ready"}))
    # 첫 화면이 첫 상태를 다 받았다 - 미뤄 둔 무거운 색인 예열이 이걸 기다린다(headless_lifespan._after_startup_gate ·
    # 사용자 제보 2026-10-22: 화면이 빨리 뜬 뒤 예열과 겹쳐 첫 상태가 늦게 와 UI 가 '날아간' 것처럼 보였다).
    context.headless_first_client_ready = True


async def handle_json_command(
    ws, context, clients, client_host, command, *, run_in_thread, broadcast_json, start_generation_runner,
) -> None:
    kind = str(command.get("type") or "").strip()
    if kind in TEMPORARY_SEARCH_COMMAND_TYPES:
        await handle_temporary_search_command(ws, context, clients, command,
            run_in_thread=run_in_thread, broadcast_json=broadcast_json)
        return
    scoped = (kind in SEARCH_COMMAND_TYPES | DEPTH_SEARCH_COMMAND_TYPES | GENERATION_COMMAND_TYPES
              or (kind == "set_option" and command.get("key") == "stop_autogen_on_tag_exhaust"))
    manager = temporary_search(context)
    if scoped and not manager.permits(getattr(ws, "_search_session_id", ""), command.get("_search_workspace")):
        await ws.send_text(json.dumps({"type": "toast", "level": "warning",
            "message": "임시 검색을 전환 중이거나 다른 창에서 사용 중입니다."}, ensure_ascii=False))
        return
    # Non-search commands can enqueue generation via modules/queue controls too.
    # Do not let one start while the search aggregate is being copied/restored.
    stopping = kind == "set_option" and command.get("key") == "auto_generate" and not context._coerce_bool(command.get("value"))
    if manager.transition and not scoped and not stopping and not kind.startswith("get_") and kind not in AUTOCOMPLETE_COMMAND_TYPES:
        await ws.send_text(json.dumps({"type": "toast", "level": "warning",
            "message": "검색 전환을 마친 뒤 다시 시도해주세요."}, ensure_ascii=False))
        return
    manager.operations += 1
    token = command_workspace.set(manager.workspace_id)
    try:
        async def guarded_runner(*args, **kwargs):
            return await finish_thread_call(run_in_thread, *args, **kwargs)
        await finish_thread_call(_dispatch_json_command, ws, context, clients, client_host, command,
            run_in_thread=guarded_runner if scoped else run_in_thread,
            broadcast_json=broadcast_json, start_generation_runner=start_generation_runner)
    finally:
        command_workspace.reset(token)
        manager.operations -= 1


async def _dispatch_json_command(
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
            clients=clients,
        )
    elif command_type in NAI_ACCOUNT_COMMAND_TYPES:
        await handle_nai_account_command(
            ws,
            context,
            client_host,
            command,
            run_in_thread=run_in_thread,
            clients=clients,
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
        if not temporary_search(context).permits("", None):
            await send_temporary_search_state(ws, temporary_search(context))
            return
        await handle_random_command(
            ws,
            context,
            clients,
            start_generation_runner=start_generation_runner,
        )
        return
    if data == "generate":
        if not temporary_search(context).permits("", None):
            await send_temporary_search_state(ws, temporary_search(context))
            return
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
