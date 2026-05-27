from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from fastapi import WebSocket

from core.web_session_context import WebSessionContext


PromptEnqueue = Callable[..., Awaitable[None]]
GenerationCommandsEnqueue = Callable[[WebSocket, WebSessionContext, set[WebSocket], list[dict[str, Any]]], Awaitable[None]]

MODULE_COMMAND_TYPES = {
    "set_module_param",
    "get_module_state",
}


async def _send_json(ws: WebSocket, payload: dict[str, Any]) -> None:
    await ws.send_text(json.dumps(payload, ensure_ascii=False))


async def handle_module_command(
    ws: WebSocket,
    context: WebSessionContext,
    clients: set[WebSocket],
    client_host: str,
    command: dict[str, Any],
    *,
    enqueue_prompt_from_module: PromptEnqueue,
    enqueue_generation_commands: GenerationCommandsEnqueue,
) -> bool:
    command_type = str(command.get("type") or "").strip()
    if command_type not in MODULE_COMMAND_TYPES:
        return False

    if command_type == "get_module_state":
        module_id = str(command.get("module_id") or "")
        await _send_json(ws, context.module_state_payload(module_id, client_host))
        return True

    module_state = context.set_module_param(
        str(command.get("module_id") or ""),
        str(command.get("key") or ""),
        command.get("value"),
        client_host=client_host,
    )
    if module_state is None:
        await _send_json(ws, {
            "type": "toast",
            "level": "info",
            "message": "Module parameter is not supported in this runtime.",
            "runtime": "web",
        })
        return True

    if isinstance(module_state, list):
        generated_prompt = ""
        generated_source = ""
        for item in module_state:
            if isinstance(item, dict):
                await _send_json(ws, item)
                if item.get("type") == "prompt_generated" and item.get("source") == "e621_event":
                    generated_prompt = str(item.get("prompt") or "")
                    generated_source = "E621"
        if generated_prompt:
            await enqueue_prompt_from_module(
                ws,
                context,
                clients,
                prompt=generated_prompt,
                source=generated_source,
            )
        return True

    generation_commands: list[dict[str, Any]] = []
    extra_messages: list[dict[str, Any]] = []
    if isinstance(module_state, dict):
        raw_commands = module_state.pop("_headless_generation_commands", [])
        if isinstance(raw_commands, list):
            generation_commands = [item for item in raw_commands if isinstance(item, dict)]
        raw_messages = module_state.pop("_headless_extra_messages", [])
        if isinstance(raw_messages, list):
            extra_messages = [item for item in raw_messages if isinstance(item, dict)]
    for message in extra_messages:
        await _send_json(ws, message)
    await _send_json(ws, module_state)
    if str(command.get("module_id") or "") == "automation":
        # A timer automation must finish on wall-clock time even when no
        # generation is running; spawn the independent expiry watcher.
        from app.backend.server.generation_runner import ensure_automation_timer_watcher

        ensure_automation_timer_watcher(context, clients)
    if generation_commands:
        await enqueue_generation_commands(ws, context, clients, generation_commands)
    return True
