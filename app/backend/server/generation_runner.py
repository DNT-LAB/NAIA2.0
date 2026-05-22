from __future__ import annotations

import asyncio

from fastapi import WebSocket

from app.backend.server.generation_commands import generation_service
from app.backend.server.prompt_tools_routes import save_prompt_engineering_thumbnail_bytes
from app.backend.server.websocket_broadcast import broadcast_image, broadcast_json
from core import result_image_payload_service as result_images
from core.web_session_context import WebSessionContext


def ensure_generation_runner(context: WebSessionContext, clients: set[WebSocket]) -> None:
    task = getattr(context, "headless_generation_runner_task", None)
    if task is not None and not task.done():
        return
    context.headless_generation_runner_task = asyncio.create_task(run_generation_queue(context, clients))


async def run_generation_queue(context: WebSessionContext, clients: set[WebSocket]) -> None:
    if getattr(context, "headless_generation_runner_active", False):
        return
    context.headless_generation_runner_active = True
    try:
        while True:
            request = await asyncio.to_thread(context.generation_queue_manager.dequeue_request)
            if request is None:
                break
            context.is_generating = True
            await broadcast_json(clients, {"type": "status", "is_generating": True, "message": "generating"})
            await broadcast_json(clients, context.queue_state_payload())
            try:
                stored = await asyncio.to_thread(generation_service(context).execute_request, request)
            except Exception as exc:
                await _broadcast_generation_error(context, clients, request, str(exc))
                continue

            context.is_generating = False
            await broadcast_json(clients, {"type": "status", "is_generating": False, "message": "completed"})
            params = getattr(request, "params", {}) or {}
            if params.get("prompt_preset_thumbnail_request"):
                await _broadcast_prompt_preset_thumbnail_update(context, clients, stored, params)
            if params.get("result_enhance_request"):
                await broadcast_json(clients, {
                    "type": "result_enhance_state",
                    "running": False,
                    "success": True,
                    "message": "Enhance complete",
                    "request_id": str(params.get("result_enhance_request_id") or request.request_id),
                    "headless": True,
                })
            await broadcast_image(clients, stored.item.webp_bytes, stored.image_meta)
            await broadcast_json(clients, context.result_store.viewer_new_image_payload(stored.item))
            await broadcast_json(clients, context.queue_state_payload())
    finally:
        context.is_generating = False
        context.headless_generation_runner_active = False


async def _broadcast_generation_error(
    context: WebSessionContext,
    clients: set[WebSocket],
    request,
    message: str,
) -> None:
    context.is_generating = False
    params = getattr(request, "params", {}) or {}
    await broadcast_json(clients, {"type": "status", "is_generating": False, "message": "error"})
    await broadcast_json(clients, {"type": "toast", "level": "error", "message": message})
    await broadcast_json(clients, {"type": "generation_error", "message": message})
    if params.get("result_enhance_request"):
        await broadcast_json(clients, {
            "type": "result_enhance_state",
            "running": False,
            "success": False,
            "message": message,
            "request_id": str(params.get("result_enhance_request_id") or request.request_id),
            "headless": True,
        })
    if params.get("event_preset_request"):
        await broadcast_json(clients, {
            "type": "event_preset_generation_error",
            "requestId": str(params.get("event_preset_request_id") or ""),
            "message": message,
        })
    if params.get("remote_preset_request"):
        await broadcast_json(clients, {
            "type": "preset_generation_error",
            "requestId": str(params.get("remote_preset_request_id") or ""),
            "message": message,
        })
    await broadcast_json(clients, context.queue_state_payload())


async def _broadcast_prompt_preset_thumbnail_update(
    context: WebSessionContext,
    clients: set[WebSocket],
    stored,
    params: dict,
) -> None:
    try:
        png_bytes, _ = result_images.history_item_png_payload(stored.item, label=stored.item.filename)
        thumbnail_payload = await asyncio.to_thread(
            save_prompt_engineering_thumbnail_bytes,
            context,
            str(params.get("prompt_preset_thumbnail_name") or ""),
            str(params.get("prompt_preset_thumbnail_mode") or ""),
            png_bytes,
        )
        await broadcast_json(clients, {
            "type": "prompt_engineering_preset_thumbnail_updated",
            "request_id": str(params.get("prompt_preset_thumbnail_request_id") or ""),
            **thumbnail_payload,
        })
    except Exception as exc:
        await broadcast_json(clients, {
            "type": "toast",
            "level": "error",
            "message": f"Preset thumbnail save failed: {exc}",
        })
