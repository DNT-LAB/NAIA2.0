from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse

from app.backend.server.websocket_broadcast import broadcast_json as _broadcast_json
from core.headless_generation_service import HeadlessGenerationService
from core.headless_random_prompt_service import HeadlessRandomPromptService
from core.web_session_context import WebSessionContext


GenerationRunnerStarter = Callable[[WebSessionContext, set[WebSocket]], None]
BroadcastJson = Callable[[set[WebSocket], dict[str, Any]], Awaitable[None]]

GENERATION_COMMAND_TYPES = {
    "bootstrap_random",
    "random",
    "generate",
    "depth_generate",
}


def random_service(context: WebSessionContext) -> HeadlessRandomPromptService:
    service = getattr(context, "headless_random_prompt_service", None)
    if service is None:
        service = HeadlessRandomPromptService(context)
        context.headless_random_prompt_service = service
    return service


def generation_service(context: WebSessionContext) -> HeadlessGenerationService:
    service = getattr(context, "headless_generation_service", None)
    if service is None:
        service = HeadlessGenerationService(context)
        context.headless_generation_service = service
    return service


async def enqueue_generation_request(context: WebSessionContext, command: dict[str, Any]) -> Any:
    return await asyncio.to_thread(generation_service(context).enqueue_remote_request, command)


async def persist_prompt_engineering_settings(context: WebSessionContext) -> None:
    await asyncio.to_thread(context.persist_prompt_engineering_settings)


async def _request_json_payload(req: Request) -> dict[str, Any]:
    try:
        payload = await req.json()
    except Exception:
        payload = {}
    return payload if isinstance(payload, dict) else {}


async def _send_json(ws: WebSocket, payload: dict[str, Any]) -> None:
    await ws.send_text(json.dumps(payload, ensure_ascii=False))


async def _broadcast_wildcard_state(context: WebSessionContext, clients: set[WebSocket]) -> None:
    """Push the wildcard module state to every client so an open Wildcard
    Manager (inline or detached) reflects the wildcards just consumed by a
    random/WC-Solo prompt. Cheap no-op when the panel isn't the active module."""
    try:
        payload = context._wildcard_module_state()
    except Exception:
        return
    # 라이브 틱 마커 (generation_runner._broadcast_wildcard_state 와 동일 계약):
    # 프론트는 이 플래그가 있을 때만 런타임 섹션을 in-place 갱신한다.
    payload["live_update"] = True
    await _broadcast_json(clients, payload)


def _active_ratings_from_command(command: dict[str, Any] | None) -> set[str] | None:
    if not isinstance(command, dict):
        return None
    ratings = command.get("ratings")
    if isinstance(ratings, str):
        ratings = list(ratings)
    if not isinstance(ratings, (list, tuple, set)):
        return None
    picked = {str(item).strip().lower() for item in ratings}
    return {rating for rating in ("g", "s", "q", "e") if rating in picked} or None


async def handle_random_command(
    ws: WebSocket,
    context: WebSessionContext,
    clients: set[WebSocket],
    command: dict[str, Any] | None = None,
    *,
    start_generation_runner: GenerationRunnerStarter,
) -> None:
    command = command if isinstance(command, dict) else {}
    overrides = command.get("overrides") if isinstance(command.get("overrides"), dict) else None
    request_id = str(command.get("random_request_id") or command.get("requestId") or "")
    active_ratings = _active_ratings_from_command(command) or context.get_active_ratings()
    result = await asyncio.to_thread(
        random_service(context).generate,
        active_ratings=active_ratings,
        overrides=overrides,
        random_request_id=request_id,
    )
    await persist_prompt_engineering_settings(context)
    await _send_json(ws, result.websocket_payload())
    for message in result.extra_messages:
        await _send_json(ws, message)
    dispatch = await _maybe_enqueue_random_auto_generation(
        context,
        result=result,
        command=command,
        overrides=overrides,
        request_id=request_id,
        queue_source="Random",
    )
    if dispatch is not None:
        await _send_json(ws, dispatch.websocket_payload())
        if not dispatch.ok:
            await _send_json(ws, {
                "type": "toast",
                "level": "error",
                "message": dispatch.blocked_reason,
            })
            await _send_json(ws, {
                "type": "status",
                "is_generating": False,
                "message": "blocked",
            })
        else:
            await _send_generation_queued_state(ws, context)
            if context.headless_generation_execute_enabled:
                start_generation_runner(context, clients)
    # 와일드카드가 소비되었으므로(순차/종속 카운터 전진) 관리 창을 라이브 갱신한다.
    # 모든 ws 전송 이후에 broadcast 하여 클라이언트가 기대하는 메시지 순서를 보존.
    if result.success:
        await _broadcast_wildcard_state(context, clients)


async def handle_bootstrap_random_command(
    ws: WebSocket,
    context: WebSessionContext,
    clients: set[WebSocket],
    command: dict[str, Any] | None = None,
    *,
    broadcast_json: BroadcastJson,
) -> None:
    command = command if isinstance(command, dict) else {}
    if str(context.prompt_text or "").strip():
        context.bootstrap_random_prompt_issued = True
        await _send_json(ws, {
            "type": "prompt_sync",
            "prompt": context.prompt_text,
            "negative": context.negative_prompt_text,
            "negative_prompt": context.negative_prompt_text,
        })
        return
    if getattr(context, "bootstrap_random_prompt_issued", False):
        return
    if getattr(context, "bootstrap_random_prompt_inflight", False):
        return

    context.bootstrap_random_prompt_inflight = True
    try:
        overrides = command.get("overrides") if isinstance(command.get("overrides"), dict) else None
        request_id = str(command.get("random_request_id") or command.get("requestId") or "")
        active_ratings = _active_ratings_from_command(command) or context.get_active_ratings()
        result = await asyncio.to_thread(
            random_service(context).generate,
            active_ratings=active_ratings,
            overrides=overrides,
            random_request_id=request_id,
        )
        await persist_prompt_engineering_settings(context)
        payload = result.websocket_payload()
        if result.success:
            context.bootstrap_random_prompt_issued = True
            payload["source"] = "bootstrap_random"
            await broadcast_json(clients, payload)
            for message in result.extra_messages:
                await broadcast_json(clients, message)
            await _broadcast_wildcard_state(context, clients)
        else:
            await _send_json(ws, payload)
            for message in result.extra_messages:
                await _send_json(ws, message)
    finally:
        context.bootstrap_random_prompt_inflight = False


async def handle_generate_command(
    ws: WebSocket,
    context: WebSessionContext,
    clients: set[WebSocket],
    command: dict[str, Any] | None = None,
    *,
    start_generation_runner: GenerationRunnerStarter,
) -> None:
    command = command if isinstance(command, dict) else {}
    await persist_prompt_engineering_settings(context)
    result = await enqueue_generation_request(context, command)
    await _send_json(ws, result.websocket_payload())
    if not result.ok:
        await _send_json(ws, {
            "type": "toast",
            "level": "error",
            "message": result.blocked_reason,
        })
        await _send_json(ws, {
            "type": "status",
            "is_generating": False,
            "message": "blocked",
        })
        return
    await _send_generation_queued_state(ws, context)
    if context.headless_generation_execute_enabled:
        start_generation_runner(context, clients)


def _refine_source_row_data(row: Any) -> dict[str, Any]:
    """Convert a sampled depth row (pandas Series) into a JSON/NaN-safe dict for
    ``_source_row_data`` so the queued GenerationRequest.source_row reconstructs
    the *sampled* row rather than the prior ``context.current_source_row``
    (which generate_from_source_row(update_context=False) restores before the
    enqueue boundary)."""
    import pandas as pd

    data: dict[str, Any] = {}
    try:
        raw = row.to_dict()
    except Exception:
        return data
    for key, value in raw.items():
        try:
            if pd.isna(value):
                data[str(key)] = None
                continue
        except (TypeError, ValueError):
            pass
        if isinstance(value, (str, int, float, bool)) or value is None:
            data[str(key)] = value
        else:
            data[str(key)] = str(value)
    return data


async def handle_depth_generate_command(
    ws: WebSocket,
    context: WebSessionContext,
    clients: set[WebSocket],
    command: dict[str, Any] | None = None,
    *,
    start_generation_runner: GenerationRunnerStarter,
) -> None:
    """Generate one image from the Refine (심층검색) sampled row.

    The sampled row is assembled through PromptProcessor/PE via
    ``generate_from_source_row(update_context=False)`` so the *main* prompt box is
    never overwritten and no ``prompt_generated`` is broadcast. The assembled
    prompt is then queued through ``handle_generate_command`` (shared enqueue/ack
    path) with the sampled row carried as ``_source_row_data`` and a Refine queue
    label, reusing the event_preset override pattern.
    """
    command = command if isinstance(command, dict) else {}

    state = context.depth_state if isinstance(getattr(context, "depth_state", None), dict) else None
    row = state.get("sample") if state is not None else None
    if row is None and state is not None:
        current = state.get("current")
        if current is not None and not getattr(current, "empty", True):
            row = current.sample(n=1).iloc[0]
            state["sample"] = row
    if row is None:
        await _send_json(ws, {"type": "depth_sample", "ok": False, "reason": "empty"})
        return

    active_ratings = _active_ratings_from_command(command) or context.get_active_ratings()
    request_id = str(
        command.get("random_request_id")
        or command.get("requestId")
        or f"refine-{uuid.uuid4().hex}"
    )

    # PE assembly with NO side effects on the main prompt context:
    # update_context=False restores current_source_row/current_prompt_context/
    # prompt_text/negative_prompt_text and skips the prompt_generated publish.
    result = await asyncio.to_thread(
        random_service(context).generate_from_source_row,
        row,
        active_ratings=active_ratings,
        random_request_id=request_id,
        source="refine_sample",
        update_context=False,
    )
    await persist_prompt_engineering_settings(context)
    if not result.success:
        await _send_json(ws, {
            "type": "toast",
            "level": "error",
            "message": result.error or "Refine generation failed",
        })
        return

    # Reuse the event_preset override pattern EXACTLY: carry the sampled row as
    # _source_row_data so HeadlessGenerationService._source_row() reconstructs the
    # sampled row (not the restored prior current_source_row), tag the queue source.
    gen_overrides: dict[str, Any] = {
        "input": result.prompt,
        "_raw_input": result.prompt,
        "_source_row_data": _refine_source_row_data(row),
        "_remote_queue_source": "Refine",
        "_remote_queue_label": "Refine",
    }
    name = getattr(row, "name", None)
    if name is not None:
        gen_overrides["_source_name"] = str(name)
    if result.detected_resolution:
        width, height = result.detected_resolution
        gen_overrides["width"] = width
        gen_overrides["height"] = height
        gen_overrides["resolution"] = f"{width} x {height}"

    gen_command: dict[str, Any] = {
        "type": "generate",
        "prompt": result.prompt,
        "negative_prompt": context.negative_prompt_text,
        "request_id": f"{request_id}:generate",
        "overrides": gen_overrides,
    }
    if result.prompt_run_id:
        gen_command["prompt_run_id"] = result.prompt_run_id

    # Delegate enqueue/queue/ack to the shared generate handler (no prompt_generated).
    await handle_generate_command(
        ws,
        context,
        clients,
        gen_command,
        start_generation_runner=start_generation_runner,
    )


async def enqueue_prompt_from_module(
    ws: WebSocket,
    context: WebSessionContext,
    clients: set[WebSocket],
    *,
    prompt: str,
    source: str,
    start_generation_runner: GenerationRunnerStarter,
) -> None:
    clean_prompt = str(prompt or "").strip()
    if not clean_prompt:
        return
    command = {
        "type": "generate",
        "prompt": clean_prompt,
        "negative_prompt": context.negative_prompt_text,
        "overrides": {
            "input": clean_prompt,
            "_raw_input": clean_prompt,
            "_remote_queue_source": source,
            "_remote_queue_label": source,
        },
    }
    result = await enqueue_generation_request(context, command)
    await _send_json(ws, result.websocket_payload())
    if not result.ok:
        await _send_json(ws, {
            "type": "toast",
            "level": "error",
            "message": result.blocked_reason,
        })
        return
    await _send_generation_queued_state(ws, context)
    if context.headless_generation_execute_enabled:
        start_generation_runner(context, clients)


async def enqueue_headless_generation_commands(
    ws: WebSocket,
    context: WebSessionContext,
    clients: set[WebSocket],
    commands: list[dict[str, Any]],
    *,
    start_generation_runner: GenerationRunnerStarter,
) -> None:
    queued = 0
    for command in commands:
        if not isinstance(command, dict):
            continue
        result = await enqueue_generation_request(context, command)
        await _send_json(ws, result.websocket_payload())
        if not result.ok:
            await _send_json(ws, {
                "type": "toast",
                "level": "error",
                "message": result.blocked_reason,
            })
            continue
        queued += 1
    if queued:
        await _send_json(ws, {
            "type": "status",
            "is_generating": False,
            "message": "queued",
        })
        await _send_json(ws, {
            "type": "toast",
            "level": "success",
            "message": f"{queued} generation request(s) queued",
        })
        await _send_json(ws, context.queue_state_payload())
        if context.headless_generation_execute_enabled:
            start_generation_runner(context, clients)


async def _send_generation_queued_state(ws: WebSocket, context: WebSessionContext) -> None:
    await _send_json(ws, {
        "type": "status",
        "is_generating": False,
        "message": "queued",
    })
    await _send_json(ws, context.queue_state_payload())


def _should_auto_generate_after_random(
    context: WebSessionContext,
    command: dict[str, Any],
    overrides: dict[str, Any] | None,
) -> bool:
    if command.get("respect_naia_autogen", True) is False:
        return False
    if command.get("force_naia_skip_generate") is True:
        return False
    request_overrides = overrides if isinstance(overrides, dict) else {}
    requested = request_overrides.get("auto_generate", context.get_options().get("auto_generate", False))
    return bool(context._coerce_bool(requested))


async def _maybe_enqueue_random_auto_generation(
    context: WebSessionContext,
    *,
    result,
    command: dict[str, Any],
    overrides: dict[str, Any] | None,
    request_id: str,
    queue_source: str,
):
    if not result.success:
        return None
    if not _should_auto_generate_after_random(context, command, overrides):
        return None

    generation_overrides = dict(overrides) if isinstance(overrides, dict) else {}
    generation_overrides["auto_generate"] = True
    generation_overrides["_remote_queue_source"] = queue_source
    generation_overrides["_remote_queue_label"] = queue_source
    if result.detected_resolution:
        width, height = result.detected_resolution
        generation_overrides["width"] = width
        generation_overrides["height"] = height
        generation_overrides["resolution"] = f"{width} x {height}"

    generation_command: dict[str, Any] = {
        "type": "generate",
        "prompt": result.prompt,
        "negative_prompt": context.negative_prompt_text,
        "request_id": f"{request_id}:generate" if request_id else f"random-{uuid.uuid4().hex}:generate",
        "overrides": generation_overrides,
    }
    if result.prompt_run_id:
        generation_command["prompt_run_id"] = result.prompt_run_id

    dispatch = await enqueue_generation_request(context, generation_command)
    return dispatch


def register_generation_rest_routes(
    app: FastAPI,
    context: WebSessionContext,
    *,
    clients: set[WebSocket],
    start_generation_runner: GenerationRunnerStarter,
) -> None:
    """Register future01-compatible REST generation entrypoints.

    The canonical Remote Web path is websocket based, but older Web Session
    tools and ComfyUI integrations still call these REST routes.
    """

    @app.post("/api/generate")
    async def api_generate(req: Request):
        command = await _request_json_payload(req)
        command = dict(command)
        command.setdefault("type", "generate")
        await persist_prompt_engineering_settings(context)
        result = await enqueue_generation_request(context, command)
        payload = result.websocket_payload()
        if not result.ok:
            return JSONResponse(payload, status_code=400)
        if context.headless_generation_execute_enabled:
            start_generation_runner(context, clients)
        return {
            "status": "generation_requested",
            **payload,
            "queue": context.queue_state_payload(),
        }

    @app.post("/api/random")
    async def api_random(req: Request):
        command = await _request_json_payload(req)
        overrides = command.get("overrides") if isinstance(command.get("overrides"), dict) else None
        request_id = str(command.get("random_request_id") or command.get("requestId") or "")
        active_ratings = _active_ratings_from_command(command) or context.get_active_ratings()
        result = await asyncio.to_thread(
            random_service(context).generate,
            active_ratings=active_ratings,
            overrides=overrides,
            random_request_id=request_id,
        )
        await persist_prompt_engineering_settings(context)
        payload = result.websocket_payload()
        if not result.success:
            return JSONResponse(payload, status_code=400)
        dispatch = await _maybe_enqueue_random_auto_generation(
            context,
            result=result,
            command=command,
            overrides=overrides,
            request_id=request_id,
            queue_source="Random",
        )
        if dispatch and dispatch.ok and context.headless_generation_execute_enabled:
            start_generation_runner(context, clients)
        return {
            "status": "random_generation_requested",
            "naia_started_generation": bool(dispatch and dispatch.ok),
            "generation": dispatch.websocket_payload() if dispatch is not None else None,
            **payload,
            "extra_messages": result.extra_messages,
        }

    @app.post("/api/comfyui/random")
    async def api_comfyui_random(req: Request):
        command = await _request_json_payload(req)
        if command.get("overrides") is not None and not isinstance(command.get("overrides"), dict):
            return JSONResponse({"error": "overrides must be a dict"}, status_code=400)
        if command.get("peng_override") is not None and not isinstance(command.get("peng_override"), dict):
            return JSONResponse({"error": "peng_override must be a dict"}, status_code=400)
        overrides = command.get("overrides") if isinstance(command.get("overrides"), dict) else {}
        overrides = dict(overrides)
        respect_autogen = command.get("respect_naia_autogen", True) is not False
        force_skip = command.get("force_naia_skip_generate") is True
        requested_auto_generate = overrides.get("auto_generate", context.get_options().get("auto_generate", False))
        will_naia_generate = bool(context._coerce_bool(requested_auto_generate) and respect_autogen and not force_skip)
        overrides["auto_generate"] = will_naia_generate
        peng_override = command.get("peng_override") if isinstance(command.get("peng_override"), dict) else None
        request_id = str(command.get("request_id") or command.get("random_request_id") or command.get("requestId") or uuid.uuid4())
        try:
            timeout = float(command.get("timeout") or 30)
        except (TypeError, ValueError):
            timeout = 30.0
        timeout = min(max(timeout, 1.0), 300.0)
        active_ratings = _active_ratings_from_command(command) or context.get_active_ratings()
        previous_peng_override = getattr(context, "session_p_eng_override", None)
        if peng_override is not None:
            context.session_p_eng_override = peng_override
        try:
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        random_service(context).generate,
                        active_ratings=active_ratings,
                        overrides=overrides,
                        random_request_id=request_id,
                    ),
                    timeout=timeout,
                )
            finally:
                if peng_override is not None and getattr(context, "session_p_eng_override", None) is peng_override:
                    context.session_p_eng_override = previous_peng_override
        except asyncio.TimeoutError:
            return JSONResponse({
                "ok": False,
                "error": "Timed out waiting for random prompt generation",
                "request_id": request_id,
            }, status_code=504)
        await persist_prompt_engineering_settings(context)
        payload = result.websocket_payload()
        if not result.success:
            return JSONResponse(payload, status_code=400)
        generation_result = await _maybe_enqueue_random_auto_generation(
            context,
            result=result,
            command=command,
            overrides=overrides,
            request_id=request_id,
            queue_source="ComfyUI Random",
        )
        generation_payload = generation_result.websocket_payload() if generation_result is not None else None
        will_naia_generate = bool(generation_result and generation_result.ok)
        if will_naia_generate and context.headless_generation_execute_enabled:
            start_generation_runner(context, clients)
        return {
            "ok": True,
            "status": "prompt_generated",
            "request_id": request_id,
            "prompt": result.prompt,
            "negative_prompt": context.negative_prompt_text,
            "naia_started_generation": will_naia_generate,
            "generation": generation_payload,
            **payload,
            "extra_messages": result.extra_messages,
        }

    @app.get("/api/comfyui/health")
    async def api_comfyui_health():
        return {
            "ok": True,
            "api_mode": context.get_api_mode(),
            "is_generating": bool(context.is_generating or getattr(context, "headless_generation_runner_active", False)),
            "queue": context.queue_state_payload(),
            "runtime": "web",
        }
