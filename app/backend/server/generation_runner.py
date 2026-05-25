from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import WebSocket

from app.backend.server.generation_commands import generation_service, random_service
from app.backend.server.prompt_tools_routes import save_prompt_engineering_thumbnail_bytes
from app.backend.server.websocket_broadcast import broadcast_image, broadcast_json
from core import result_image_payload_service as result_images
from core.web_session_context import WebSessionContext


AUTO_GENERATE_SUPPRESSED_FLAGS = {
    "artist_thumb_request",
    "character_viewer_request",
    "event_preset_request",
    "interactive_mode_request",
    "prompt_preset_thumbnail_request",
    "remote_preset_request",
    "result_enhance_request",
    "studio_request",
    "turbo_sequence_request",
}

AUTO_GENERATE_DROPPED_PARAM_KEYS = {
    "_generation_request",
    "credential",
    "generation_request_id",
    "promptRunId",
    "prompt_run_id",
    "requestId",
    "request_id",
    "result_enhance_request_id",
}


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
            auto_save_result = await _auto_save_generated_history_item(context, stored.item)

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
                    "runtime": "web",
                })
            await broadcast_image(clients, stored.item.webp_bytes, stored.image_meta)
            await broadcast_json(clients, context.result_store.viewer_new_image_payload(stored.item))
            await _maybe_continue_auto_generation(context, clients, request)
            await broadcast_json(clients, context.queue_state_payload())
            await broadcast_json(clients, context.auto_save_state_payload())
            if isinstance(auto_save_result, dict) and auto_save_result.get("error"):
                await broadcast_json(clients, {
                    "type": "toast",
                    "level": "error",
                    "message": f"Auto Save failed: {auto_save_result['error']}",
                })
    finally:
        context.is_generating = False
        context.headless_generation_runner_active = False


async def _maybe_continue_auto_generation(
    context: WebSessionContext,
    clients: set[WebSocket],
    request,
) -> bool:
    if not _should_continue_auto_generation(context, request):
        return False

    params = getattr(request, "params", {}) or {}
    prompt_fixed = context._coerce_bool(
        context.get_options().get("prompt_fixed", params.get("prompt_fixed", False))
    )
    overrides = _auto_generation_overrides(params)
    overrides["auto_generate"] = True
    overrides["prompt_fixed"] = prompt_fixed
    overrides["_remote_queue_source"] = "Auto Generate"
    overrides["_remote_queue_label"] = "Auto Generate"

    request_id = f"auto-{uuid.uuid4().hex}"
    prompt = str(params.get("input") or params.get("_raw_input") or context.prompt_text or "")
    negative = str(params.get("negative_prompt") or context.negative_prompt_text or "")

    if not prompt_fixed:
        result = await asyncio.to_thread(
            random_service(context).generate,
            active_ratings=context.get_active_ratings(),
            overrides=overrides,
            random_request_id=request_id,
        )
        payload = result.websocket_payload()
        if not result.success:
            await broadcast_json(clients, payload)
            await broadcast_json(clients, {
                "type": "toast",
                "level": "error",
                "message": payload.get("message") or "Auto Generate stopped: random prompt failed.",
            })
            return False

        payload["source"] = "auto_generate"
        await broadcast_json(clients, payload)
        for message in result.extra_messages:
            await broadcast_json(clients, message)
        prompt = result.prompt
        negative = context.negative_prompt_text
        if result.detected_resolution:
            width, height = result.detected_resolution
            overrides["width"] = width
            overrides["height"] = height
            overrides["resolution"] = f"{width} x {height}"

    dispatch = await asyncio.to_thread(
        generation_service(context).enqueue_remote_request,
        {
            "type": "generate",
            "prompt": prompt,
            "negative_prompt": negative,
            "request_id": f"{request_id}:generate",
            "overrides": overrides,
        },
    )
    await broadcast_json(clients, dispatch.websocket_payload())
    if not dispatch.ok:
        await broadcast_json(clients, {
            "type": "toast",
            "level": "error",
            "message": dispatch.blocked_reason,
        })
        return False
    await broadcast_json(clients, {"type": "status", "is_generating": False, "message": "queued"})
    return True


def _should_continue_auto_generation(context: WebSessionContext, request) -> bool:
    if not context._coerce_bool(context.get_options().get("auto_generate", False)):
        return False
    queue_manager = context.generation_queue_manager
    if queue_manager.is_paused() or not queue_manager.is_empty():
        return False
    params = getattr(request, "params", {}) or {}
    if not isinstance(params, dict):
        return False
    if any(context._coerce_bool(params.get(key, False)) for key in AUTO_GENERATE_SUPPRESSED_FLAGS):
        return False
    request_type = str(params.get("type") or "").strip().lower()
    if request_type in {"img2img", "inpaint", "outpaint", "auto_outpainting"}:
        return False
    return True


def _auto_generation_overrides(params: dict[str, Any]) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for key, value in params.items():
        if key in AUTO_GENERATE_DROPPED_PARAM_KEYS:
            continue
        if str(key).startswith("_") and key not in {
            "_remote_web_session_params",
            "_remote_queue_source",
            "_remote_queue_label",
            "_skip_vibe_transfer_late_binding",
        }:
            continue
        overrides[key] = value
    return overrides


async def _auto_save_generated_history_item(context: WebSessionContext, item):
    if not context._coerce_bool(context.auto_save_state.get("auto_save", True)):
        return None
    try:
        return await asyncio.to_thread(context.save_history_item, item)
    except Exception as exc:
        return {"error": str(exc)}


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
            "runtime": "web",
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
