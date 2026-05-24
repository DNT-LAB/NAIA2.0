from __future__ import annotations

import asyncio
import json
from typing import Any, Callable

from fastapi import WebSocket

from core.headless_generation_service import HeadlessGenerationService
from core.headless_random_prompt_service import HeadlessRandomPromptService
from core.web_session_context import WebSessionContext


GenerationRunnerStarter = Callable[[WebSessionContext, set[WebSocket]], None]

GENERATION_COMMAND_TYPES = {
    "random",
    "generate",
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


async def _send_json(ws: WebSocket, payload: dict[str, Any]) -> None:
    await ws.send_text(json.dumps(payload, ensure_ascii=False))


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
    command: dict[str, Any] | None = None,
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
    await _send_json(ws, result.websocket_payload())
    for message in result.extra_messages:
        await _send_json(ws, message)


async def handle_generate_command(
    ws: WebSocket,
    context: WebSessionContext,
    clients: set[WebSocket],
    command: dict[str, Any] | None = None,
    *,
    start_generation_runner: GenerationRunnerStarter,
) -> None:
    command = command if isinstance(command, dict) else {}
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
