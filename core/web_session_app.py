"""PyQt-free FastAPI app for the headless Remote Web Session path."""

from __future__ import annotations

import copy
from contextlib import asynccontextmanager
import json
import asyncio
import io
import math
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from app.backend.server.autocomplete_commands import (
    AUTOCOMPLETE_COMMAND_TYPES,
    ensure_tag_search_index,
    handle_autocomplete_command,
)
from app.backend.server.api_control_commands import (
    API_CONTROL_COMMAND_TYPES,
    handle_api_control_command,
)
from app.backend.server.artist_thumbnail_routes import register_artist_thumbnail_routes
from app.backend.server.character_viewer_routes import register_character_viewer_routes
from app.backend.server.danbooru_routes import register_danbooru_routes
from app.backend.server.depth_search_commands import (
    DEPTH_SEARCH_COMMAND_TYPES,
    handle_depth_search_command,
)
from app.backend.server.event_preset_routes import register_event_preset_routes
from app.backend.server.install_manager_routes import register_install_manager_routes
from app.backend.server.headless_retired_commands import (
    HEADLESS_RETIRED_COMMAND_TYPES,
    handle_headless_retired_command,
)
from app.backend.server.module_commands import (
    MODULE_COMMAND_TYPES,
    handle_module_command,
)
from app.backend.server.params_workflow_routes import register_params_workflow_routes
from app.backend.server.prompt_engineering_commands import (
    HIRES_OVERLAY_COMMAND_TYPES,
    handle_hires_overlay_command,
)
from app.backend.server.prompt_tools_routes import (
    register_prompt_tools_routes,
    save_prompt_engineering_thumbnail_bytes,
)
from app.backend.server.result_display_routes import (
    register_result_display_routes,
    resolve_result_image_action_source,
)
from app.backend.server.search_commands import (
    SEARCH_COMMAND_TYPES,
    handle_search_command,
)
from app.backend.server.state_routes import register_state_routes
from app.backend.server.style_thumbnail_routes import register_style_thumbnail_routes
from app.backend.server.web_shell_routes import register_web_shell_routes
from app.web import resolve_remote_web_dir
from core import result_image_payload_service as result_images
from core.headless_generation_service import HeadlessGenerationService
from core.headless_random_prompt_service import HeadlessRandomPromptService
from core.web_session_context import WebSessionContext


def _client_host(ws: WebSocket) -> str:
    try:
        if ws.client is not None:
            host = str(ws.client.host or "")
            if host == "testclient":
                return "127.0.0.1"
            return host
    except Exception:
        pass
    return ""


def _no_cache_headers() -> dict[str, str]:
    return {"Cache-Control": "no-store, max-age=0"}


async def _send_startup_messages(
    ws: WebSocket,
    context: WebSessionContext,
    *,
    session_id: str,
    client_host: str,
) -> None:
    for message in context.initial_websocket_messages(
        session_id=session_id,
        client_host=client_host,
    ):
        await ws.send_text(json.dumps(message, ensure_ascii=False))
    await ws.send_text(json.dumps({"type": "lazy_indices_ready"}))


async def _send_sync_messages(ws: WebSocket, context: WebSessionContext, client_host: str) -> None:
    messages = [
        {"type": "mode", "mode": context.get_api_mode()},
        {"type": "options", **context.get_options()},
        context.generation_param_schema_payload(),
        context.queue_state_payload(),
        context.api_status_payload(client_host),
        {"type": "lazy_indices_ready"},
    ]
    for message in messages:
        await ws.send_text(json.dumps(message, ensure_ascii=False))


async def _broadcast_json(clients: set[WebSocket], data: dict[str, Any]) -> None:
    text = json.dumps(data, ensure_ascii=False)
    dead = []
    for client in list(clients):
        try:
            await client.send_text(text)
        except Exception:
            dead.append(client)
    for client in dead:
        clients.discard(client)


async def _broadcast_image(clients: set[WebSocket], webp_bytes: bytes, metadata: dict[str, Any]) -> None:
    meta_text = json.dumps({"type": "image_meta", **metadata}, ensure_ascii=False)
    dead = []
    for client in list(clients):
        try:
            await client.send_text(meta_text)
            await client.send_bytes(webp_bytes)
        except Exception:
            dead.append(client)
    for client in dead:
        clients.discard(client)


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


def _random_service(context: WebSessionContext) -> HeadlessRandomPromptService:
    service = getattr(context, "headless_random_prompt_service", None)
    if service is None:
        service = HeadlessRandomPromptService(context)
        context.headless_random_prompt_service = service
    return service


def _generation_service(context: WebSessionContext) -> HeadlessGenerationService:
    service = getattr(context, "headless_generation_service", None)
    if service is None:
        service = HeadlessGenerationService(context)
        context.headless_generation_service = service
    return service


def _clamp_result_enhance_number(value: Any, minimum: float, maximum: float, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return min(maximum, max(minimum, number))


def _coerce_result_enhance_bool(value: Any, fallback: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return fallback
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return fallback


def _normalize_result_enhance_config(
    context: WebSessionContext,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    current = context.result_enhance_config if isinstance(context.result_enhance_config, dict) else {}
    upscale_value = payload.get("upscale", current.get("upscale", 1.5))
    try:
        upscale = 1.0 if abs(float(upscale_value) - 1.0) < 0.01 else 1.5
    except (TypeError, ValueError):
        upscale = 1.5
    strength = round(
        _clamp_result_enhance_number(payload.get("strength", current.get("strength", 0.2)), 0.1, 0.9, 0.2),
        1,
    )
    noise = round(
        _clamp_result_enhance_number(payload.get("noise", current.get("noise", 0.0)), 0.0, 0.1, 0.0),
        1,
    )
    return {
        "type": "result_enhance_config",
        "upscale": upscale,
        "strength": strength,
        "noise": noise,
        "available": True,
        "headless": True,
    }


def _normalize_webui_result_enhance_hires_settings(
    context: WebSessionContext,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    payload_settings = payload.get("hires_settings") if isinstance(payload.get("hires_settings"), dict) else {}
    merged = {**dict(context.remote_params or {}), **payload_settings}
    return {
        "enable_hr": True,
        "hr_scale": round(_clamp_result_enhance_number(merged.get("hr_scale"), 1.0, 4.0, 2.0), 1),
        "hr_upscaler": str(merged.get("hr_upscaler") or "Latent (nearest-exact)").strip() or "Latent (nearest-exact)",
        "denoising_strength": round(
            _clamp_result_enhance_number(merged.get("denoising_strength"), 0.0, 1.0, 0.5),
            2,
        ),
        "hires_steps": int(_clamp_result_enhance_number(merged.get("hires_steps"), 0, 150, 10)),
        "hr_cfg": round(_clamp_result_enhance_number(merged.get("hr_cfg"), 0.0, 30.0, 7.0), 1),
        "webui_hiresfix_assist": _coerce_result_enhance_bool(merged.get("webui_hiresfix_assist"), False),
        "webui_hiresfix_assist_target": 768
            if str(merged.get("webui_hiresfix_assist_target") or "").strip() == "768"
            else 512,
    }


def _round_result_enhance_size(value: float) -> int:
    return max(64, int(math.ceil(float(value) / 64.0) * 64))


def _result_enhance_dimension(value: Any, fallback: int) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return int(fallback)
    return max(1, number)


def _apply_webui_result_enhance_size_policy(
    context: WebSessionContext,
    params: dict[str, Any],
    base_w: int,
    base_h: int,
) -> tuple[int, int, float]:
    payload = {"width": base_w, "height": base_h}
    scale = _clamp_result_enhance_number(params.get("hr_scale"), 1.0, 4.0, 2.0)
    try:
        from core.api_service import APIService

        if params.get("webui_hiresfix_assist"):
            payload["width"], payload["height"] = APIService._nearest_hiresfix_assist_resolution(
                payload["width"],
                payload["height"],
                params.get("webui_hiresfix_assist_target", 512),
            )
            service = getattr(context, "api_service", None) or APIService(context)
            scale = service._fit_webui_hiresfix_assist_scale(payload, scale)
    except Exception:
        payload = {"width": base_w, "height": base_h}
    payload_w = _result_enhance_dimension(payload.get("width"), base_w)
    payload_h = _result_enhance_dimension(payload.get("height"), base_h)
    scale = round(_clamp_result_enhance_number(scale, 1.0, 4.0, 2.0), 1)
    params["width"] = payload_w
    params["height"] = payload_h
    params["hr_scale"] = scale
    new_w = max(1, int(math.floor((payload_w * scale) + 0.5)))
    new_h = max(1, int(math.floor((payload_h * scale) + 0.5)))
    return new_w, new_h, scale


def _prompt_from_result_context(
    context: WebSessionContext,
    params: dict[str, Any],
    prompt_context: dict[str, Any],
) -> None:
    if not params.get("input"):
        prompt = (
            prompt_context.get("main_prompt")
            or prompt_context.get("final_prompt")
            or prompt_context.get("prompt")
            or context.prompt_text
            or ""
        )
        params["input"] = str(prompt)
    params["_raw_input"] = str(params.get("_raw_input") or params.get("input") or "")
    if not params.get("negative_prompt"):
        params["negative_prompt"] = str(
            prompt_context.get("negative_prompt")
            or prompt_context.get("uc")
            or context.negative_prompt_text
            or ""
        )


def _prepare_result_enhance_command(
    context: WebSessionContext,
    payload: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    from PIL import Image
    from utils.webui_generation_info import extract_webui_seed

    payload = payload if isinstance(payload, dict) else {}
    current_mode = str(context.get_api_mode() or "").upper()
    requested_mode = str(payload.get("mode") or "").upper()
    if current_mode not in {"NAI", "WEBUI"}:
        raise RuntimeError("Enhance is available in NAI or WEBUI mode only")
    mode = current_mode
    if requested_mode in {"NAI", "WEBUI"} and requested_mode != current_mode:
        raise RuntimeError("Enhance mode changed; refresh the result selection")

    image_bytes, label, generation_params, prompt_context = resolve_result_image_action_source(context, payload)
    if not generation_params:
        raise RuntimeError("Generation parameters are unavailable")
    with Image.open(io.BytesIO(image_bytes)) as image:
        orig_w, orig_h = image.size
    params = copy.deepcopy(generation_params)
    _prompt_from_result_context(context, params, prompt_context)
    for key in ("credential", "schema_only", "options_model", "options_sampler", "options_scheduler", "options_resolution"):
        params.pop(key, None)

    if mode == "NAI":
        config = _normalize_result_enhance_config(context, payload)
        upscale = float(config["upscale"])
        new_w, new_h = (orig_w, orig_h) if upscale == 1.0 else (
            _round_result_enhance_size(orig_w * 1.5),
            _round_result_enhance_size(orig_h * 1.5),
        )
        params.update({
            "image_bytes": image_bytes,
            "strength": float(config["strength"]),
            "noise": float(config["noise"]),
            "width": new_w,
            "height": new_h,
            "api_mode": "NAI",
            "result_enhance_request": True,
            "result_enhance_backend": "NAI",
            "result_enhance_upscale": upscale,
            "result_enhance_strength": float(config["strength"]),
            "result_enhance_source_size": [orig_w, orig_h],
            "result_enhance_preview_size": [new_w, new_h],
            "_remote_queue_source": "NAI Enhance",
            "_remote_queue_label": label,
        })
        params.pop("type", None)
        params.pop("mask_bytes", None)
        params.pop("_skip_vibe_transfer_late_binding", None)
        message = "Enhance queued"
    else:
        hires_settings = _normalize_webui_result_enhance_hires_settings(context, payload)
        params.pop("type", None)
        params.pop("image_bytes", None)
        params.pop("mask_bytes", None)
        params.pop("strength", None)
        params.pop("noise", None)
        base_w = _result_enhance_dimension(params.get("width"), orig_w)
        base_h = _result_enhance_dimension(params.get("height"), orig_h)
        seed = extract_webui_seed(params)
        if seed is None:
            raise RuntimeError("WEBUI result seed is unavailable; cannot reproduce source image for Enhance")
        params.update({
            **hires_settings,
            "width": base_w,
            "height": base_h,
            "seed": seed,
            "seed_fixed": True,
            "random_resolution": False,
            "resolution_preset_enabled": False,
            "resolution": f"{base_w} x {base_h}",
            "api_mode": "WEBUI",
            "result_enhance_request": True,
            "result_enhance_backend": "WEBUI",
            "result_enhance_source_size": [orig_w, orig_h],
            "_remote_queue_source": "WEBUI Enhance",
            "_remote_queue_label": label,
        })
        new_w, new_h, upscale = _apply_webui_result_enhance_size_policy(context, params, base_w, base_h)
        params.update({
            "result_enhance_upscale": upscale,
            "result_enhance_strength": params.get("denoising_strength", 0.5),
            "result_enhance_hr_upscaler": params.get("hr_upscaler", ""),
            "result_enhance_hires_steps": params.get("hires_steps", 10),
            "result_enhance_hr_cfg": params.get("hr_cfg", 7.0),
            "result_enhance_preview_size": [new_w, new_h],
        })
        message = "Enhance queued"

    return {
        "type": "generate",
        "api_mode": mode,
        "overrides": params,
    }, {
        "type": "result_enhance_state",
        "running": True,
        "message": message,
        "api_mode": mode,
        "source_size": [orig_w, orig_h],
        "preview_size": params.get("result_enhance_preview_size", [orig_w, orig_h]),
        "headless": True,
    }


async def _handle_random_command(
    ws: WebSocket,
    context: WebSessionContext,
    command: dict[str, Any] | None = None,
) -> None:
    command = command if isinstance(command, dict) else {}
    overrides = command.get("overrides") if isinstance(command.get("overrides"), dict) else None
    request_id = str(command.get("random_request_id") or command.get("requestId") or "")
    active_ratings = _active_ratings_from_command(command) or context.get_active_ratings()
    result = await _to_thread(
        _random_service(context).generate,
        active_ratings=active_ratings,
        overrides=overrides,
        random_request_id=request_id,
    )
    await ws.send_text(json.dumps(result.websocket_payload(), ensure_ascii=False))


async def _handle_generate_command(
    ws: WebSocket,
    context: WebSessionContext,
    clients: set[WebSocket],
    command: dict[str, Any] | None = None,
) -> None:
    command = command if isinstance(command, dict) else {}
    result = await _to_thread(_generation_service(context).enqueue_remote_request, command)
    await ws.send_text(json.dumps(result.websocket_payload(), ensure_ascii=False))
    if not result.ok:
        await ws.send_text(json.dumps({
            "type": "toast",
            "level": "error",
            "message": result.blocked_reason,
        }, ensure_ascii=False))
        await ws.send_text(json.dumps({
            "type": "status",
            "is_generating": False,
            "message": "blocked",
        }, ensure_ascii=False))
        return
    await ws.send_text(json.dumps({
        "type": "status",
        "is_generating": False,
        "message": "queued",
    }, ensure_ascii=False))
    await ws.send_text(json.dumps(context.queue_state_payload(), ensure_ascii=False))
    if context.headless_generation_execute_enabled:
        _ensure_generation_runner(context, clients)


async def _enqueue_prompt_from_module(
    ws: WebSocket,
    context: WebSessionContext,
    clients: set[WebSocket],
    *,
    prompt: str,
    source: str,
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
    result = await _to_thread(_generation_service(context).enqueue_remote_request, command)
    await ws.send_text(json.dumps(result.websocket_payload(), ensure_ascii=False))
    if not result.ok:
        await ws.send_text(json.dumps({
            "type": "toast",
            "level": "error",
            "message": result.blocked_reason,
        }, ensure_ascii=False))
        return
    await ws.send_text(json.dumps({
        "type": "status",
        "is_generating": False,
        "message": "queued",
    }, ensure_ascii=False))
    await ws.send_text(json.dumps(context.queue_state_payload(), ensure_ascii=False))
    if context.headless_generation_execute_enabled:
        _ensure_generation_runner(context, clients)


async def _enqueue_headless_generation_commands(
    ws: WebSocket,
    context: WebSessionContext,
    clients: set[WebSocket],
    commands: list[dict[str, Any]],
) -> None:
    queued = 0
    for command in commands:
        if not isinstance(command, dict):
            continue
        result = await _to_thread(_generation_service(context).enqueue_remote_request, command)
        await ws.send_text(json.dumps(result.websocket_payload(), ensure_ascii=False))
        if not result.ok:
            await ws.send_text(json.dumps({
                "type": "toast",
                "level": "error",
                "message": result.blocked_reason,
            }, ensure_ascii=False))
            continue
        queued += 1
    if queued:
        await ws.send_text(json.dumps({
            "type": "status",
            "is_generating": False,
            "message": "queued",
        }, ensure_ascii=False))
        await ws.send_text(json.dumps({
            "type": "toast",
            "level": "success",
            "message": f"{queued} generation request(s) queued",
        }, ensure_ascii=False))
        await ws.send_text(json.dumps(context.queue_state_payload(), ensure_ascii=False))
        if context.headless_generation_execute_enabled:
            _ensure_generation_runner(context, clients)


def _ensure_generation_runner(context: WebSessionContext, clients: set[WebSocket]) -> None:
    task = getattr(context, "headless_generation_runner_task", None)
    if task is not None and not task.done():
        return
    context.headless_generation_runner_task = asyncio.create_task(_run_generation_queue(context, clients))


async def _run_generation_queue(context: WebSessionContext, clients: set[WebSocket]) -> None:
    if getattr(context, "headless_generation_runner_active", False):
        return
    context.headless_generation_runner_active = True
    try:
        while True:
            request = await _to_thread(context.generation_queue_manager.dequeue_request)
            if request is None:
                break
            context.is_generating = True
            await _broadcast_json(clients, {"type": "status", "is_generating": True, "message": "generating"})
            await _broadcast_json(clients, context.queue_state_payload())
            try:
                stored = await _to_thread(_generation_service(context).execute_request, request)
            except Exception as exc:
                context.is_generating = False
                message = str(exc)
                params = getattr(request, "params", {}) or {}
                await _broadcast_json(clients, {"type": "status", "is_generating": False, "message": "error"})
                await _broadcast_json(clients, {"type": "toast", "level": "error", "message": message})
                await _broadcast_json(clients, {"type": "generation_error", "message": message})
                if params.get("result_enhance_request"):
                    await _broadcast_json(clients, {
                        "type": "result_enhance_state",
                        "running": False,
                        "success": False,
                        "message": message,
                        "request_id": str(params.get("result_enhance_request_id") or request.request_id),
                        "headless": True,
                    })
                if params.get("event_preset_request"):
                    await _broadcast_json(clients, {
                        "type": "event_preset_generation_error",
                        "requestId": str(params.get("event_preset_request_id") or ""),
                        "message": message,
                    })
                if params.get("remote_preset_request"):
                    await _broadcast_json(clients, {
                        "type": "preset_generation_error",
                        "requestId": str(params.get("remote_preset_request_id") or ""),
                        "message": message,
                    })
                await _broadcast_json(clients, context.queue_state_payload())
                continue

            context.is_generating = False
            await _broadcast_json(clients, {"type": "status", "is_generating": False, "message": "completed"})
            params = getattr(request, "params", {}) or {}
            if params.get("prompt_preset_thumbnail_request"):
                try:
                    png_bytes, _ = result_images.history_item_png_payload(stored.item, label=stored.item.filename)
                    thumbnail_payload = await _to_thread(
                        save_prompt_engineering_thumbnail_bytes,
                        context,
                        str(params.get("prompt_preset_thumbnail_name") or ""),
                        str(params.get("prompt_preset_thumbnail_mode") or ""),
                        png_bytes,
                    )
                    await _broadcast_json(clients, {
                        "type": "prompt_engineering_preset_thumbnail_updated",
                        "request_id": str(params.get("prompt_preset_thumbnail_request_id") or ""),
                        **thumbnail_payload,
                    })
                except Exception as exc:
                    await _broadcast_json(clients, {
                        "type": "toast",
                        "level": "error",
                        "message": f"Preset thumbnail save failed: {exc}",
                    })
            if params.get("result_enhance_request"):
                await _broadcast_json(clients, {
                    "type": "result_enhance_state",
                    "running": False,
                    "success": True,
                    "message": "Enhance complete",
                    "request_id": str(params.get("result_enhance_request_id") or request.request_id),
                    "headless": True,
                })
            await _broadcast_image(clients, stored.item.webp_bytes, stored.image_meta)
            await _broadcast_json(clients, context.result_store.viewer_new_image_payload(stored.item))
            await _broadcast_json(clients, context.queue_state_payload())
    finally:
        context.is_generating = False
        context.headless_generation_runner_active = False


async def _handle_json_command(
    ws: WebSocket,
    context: WebSessionContext,
    clients: set[WebSocket],
    client_host: str,
    command: dict[str, Any],
) -> None:
    command_type = str(command.get("type") or "").strip()
    if command_type == "sync":
        await _send_sync_messages(ws, context, client_host)
    elif command_type == "set_option":
        context.set_option(str(command.get("key") or ""), command.get("value"))
        await _broadcast_json(clients, {"type": "options", **context.get_options()})
    elif command_type == "set_mode":
        requested_mode = str(command.get("mode") or "").strip().upper()
        if requested_mode not in {"NAI", "WEBUI", "COMFYUI"}:
            await ws.send_text(json.dumps({
                "type": "mode_result",
                "success": False,
                "mode": requested_mode,
                "message": f"Unknown mode: {requested_mode}",
            }, ensure_ascii=False))
            return
        token_key = {
            "NAI": "nai_token",
            "WEBUI": "webui_url",
            "COMFYUI": "comfyui_url",
        }[requested_mode]
        if not str(context.secure_token_manager.get_token(token_key) or ""):
            await ws.send_text(json.dumps({
                "type": "mode_result",
                "success": False,
                "mode": requested_mode,
                "message": f"{requested_mode} API is not connected",
            }, ensure_ascii=False))
            await ws.send_text(json.dumps(context.api_status_payload(client_host), ensure_ascii=False))
            return
        context.set_api_mode(requested_mode)
        await _broadcast_json(clients, {
            "type": "mode_result",
            "success": True,
            "mode": context.get_api_mode(),
            "message": f"{context.get_api_mode()} mode active",
        })
        await _broadcast_json(clients, {"type": "mode", "mode": context.get_api_mode()})
        await _broadcast_json(clients, context.generation_param_schema_payload())
        await ws.send_text(json.dumps(context.api_status_payload(client_host), ensure_ascii=False))
    elif command_type == "set_prompt":
        context.prompt_text = str(command.get("prompt") or "")
        context.negative_prompt_text = str(command.get("negative_prompt", command.get("negative")) or "")
        await ws.send_text(json.dumps({
            "type": "prompt_sync",
            "prompt": context.prompt_text,
            "negative": context.negative_prompt_text,
        }, ensure_ascii=False))
    elif command_type == "set_param":
        context.set_param(str(command.get("key") or ""), command.get("value"))
        await _broadcast_json(clients, context.generation_param_schema_payload())
    elif command_type in SEARCH_COMMAND_TYPES:
        await handle_search_command(
            ws,
            context,
            command,
            run_in_thread=_to_thread,
        )
    elif command_type in API_CONTROL_COMMAND_TYPES:
        await handle_api_control_command(
            ws,
            context,
            client_host,
            command,
            run_in_thread=_to_thread,
        )
    elif command_type in HEADLESS_RETIRED_COMMAND_TYPES:
        await handle_headless_retired_command(ws, context, client_host, command)
    elif command_type in AUTOCOMPLETE_COMMAND_TYPES:
        await handle_autocomplete_command(
            ws,
            context,
            command,
            run_in_thread=_to_thread,
        )
    elif command_type in DEPTH_SEARCH_COMMAND_TYPES:
        await handle_depth_search_command(
            ws,
            context,
            command,
            run_in_thread=_to_thread,
        )
    elif command_type in HIRES_OVERLAY_COMMAND_TYPES:
        await handle_hires_overlay_command(
            ws,
            context,
            command,
            run_in_thread=_to_thread,
        )
    elif command_type in MODULE_COMMAND_TYPES:
        await handle_module_command(
            ws,
            context,
            clients,
            client_host,
            command,
            enqueue_prompt_from_module=_enqueue_prompt_from_module,
            enqueue_generation_commands=_enqueue_headless_generation_commands,
        )
    elif command_type == "result_enhance":
        try:
            generation_command, enhance_state = await _to_thread(_prepare_result_enhance_command, context, command)
            result = await _to_thread(_generation_service(context).enqueue_remote_request, generation_command)
        except Exception as exc:
            message = f"Enhance request failed: {exc}"
            await ws.send_text(json.dumps({
                "type": "result_enhance_state",
                "running": False,
                "success": False,
                "message": message,
                "headless": True,
            }, ensure_ascii=False))
            await ws.send_text(json.dumps({
                "type": "toast",
                "level": "error",
                "message": message,
                "headless": True,
            }, ensure_ascii=False))
            return
        await ws.send_text(json.dumps(result.websocket_payload(), ensure_ascii=False))
        if not result.ok:
            await ws.send_text(json.dumps({
                "type": "result_enhance_state",
                "running": False,
                "success": False,
                "message": result.blocked_reason,
                "headless": True,
            }, ensure_ascii=False))
            await ws.send_text(json.dumps({
                "type": "toast",
                "level": "error",
                "message": result.blocked_reason,
                "headless": True,
            }, ensure_ascii=False))
            return
        await ws.send_text(json.dumps(enhance_state, ensure_ascii=False))
        await ws.send_text(json.dumps({
            "type": "status",
            "is_generating": False,
            "message": "queued",
        }, ensure_ascii=False))
        await ws.send_text(json.dumps({
            "type": "toast",
            "level": "success",
            "message": "Enhance queued",
        }, ensure_ascii=False))
        await ws.send_text(json.dumps(context.queue_state_payload(), ensure_ascii=False))
        if context.headless_generation_execute_enabled:
            _ensure_generation_runner(context, clients)
    elif command_type == "set_result_enhance_config":
        config = _normalize_result_enhance_config(context, command)
        context.result_enhance_config = {
            "upscale": config["upscale"],
            "strength": config["strength"],
            "noise": config["noise"],
        }
        await ws.send_text(json.dumps({**config, "_session_echo": True}, ensure_ascii=False))
        await ws.send_text(json.dumps({
            "type": "toast",
            "level": "success",
            "message": "Enhance settings updated",
            "headless": True,
        }, ensure_ascii=False))
    elif command_type == "result_image_action":
        action = str(command.get("action") or "image_action")
        if action not in {"img2img", "inpaint"}:
            await ws.send_text(json.dumps({
                "type": "toast",
                "level": "error",
                "message": "Unsupported result image action",
                "headless": True,
            }, ensure_ascii=False))
            return
        if context.get_api_mode() != "NAI":
            await ws.send_text(json.dumps({
                "type": "toast",
                "level": "error",
                "message": "Img2Img/Inpaint is available in NAI mode only",
                "headless": True,
            }, ensure_ascii=False))
            return
        try:
            image_bytes, label, generation_params, prompt_context = await _to_thread(
                resolve_result_image_action_source,
                context,
                command,
            )
            state = await _to_thread(
                context.open_img2img_session_from_bytes,
                image_bytes,
                label=label,
                mode=action,
                generation_params=generation_params,
                prompt_context=prompt_context,
            )
        except Exception as exc:
            await ws.send_text(json.dumps({
                "type": "toast",
                "level": "error",
                "message": f"Image action failed: {exc}",
                "headless": True,
            }, ensure_ascii=False))
            return
        await ws.send_text(json.dumps(state, ensure_ascii=False))
        await ws.send_text(json.dumps({
            "type": "toast",
            "level": "success",
            "message": f"{'Inpaint' if action == 'inpaint' else 'Img2Img'} session ready",
            "headless": True,
        }, ensure_ascii=False))
    elif command_type == "random":
        await _handle_random_command(ws, context, command)
    elif command_type == "generate":
        await _handle_generate_command(ws, context, clients, command)
    else:
        await ws.send_text(json.dumps({
            "type": "toast",
            "level": "info",
            "message": f"Headless command ignored: {command_type or 'unknown'}",
        }, ensure_ascii=False))


async def _handle_text_command(
    ws: WebSocket,
    context: WebSessionContext,
    clients: set[WebSocket],
    client_host: str,
    data: str,
) -> None:
    if data == "sync":
        await _send_sync_messages(ws, context, client_host)
        return
    if data == "random":
        await _handle_random_command(ws, context)
        return
    if data == "generate":
        await _handle_generate_command(ws, context, clients)
        return
    await ws.send_text(json.dumps({
        "type": "toast",
        "level": "info",
        "message": f"Headless command ignored: {data}",
    }, ensure_ascii=False))


async def _to_thread(func, /, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)


def create_headless_app(
    context: WebSessionContext | None = None,
    *,
    web_dir: Path | str | None = None,
) -> FastAPI:
    """Create the PyQt-free Remote Web FastAPI app."""

    session_context = context or WebSessionContext()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        async def run_warmup() -> None:
            try:
                ok = await _to_thread(_random_service(session_context).warmup)
                session_context.headless_random_warmup_done = bool(ok)
                print(
                    "Headless Remote: random prompt runtime warmup "
                    + ("ready" if ok else "finished without search rows"),
                    flush=True,
                )
            except Exception as exc:
                session_context.headless_random_warmup_error = str(exc)
                print(f"Headless Remote: random prompt runtime warmup failed - {exc}", flush=True)

        async def run_tag_index_warmup() -> None:
            try:
                await _to_thread(ensure_tag_search_index, session_context)
                print(
                    f"Headless Remote: tag autocomplete index ready ({len(getattr(session_context, 'kr_tags_raw', {}) or {}):,} tags)",
                    flush=True,
                )
            except Exception as exc:
                session_context.headless_tag_index_warmup_error = str(exc)
                print(f"Headless Remote: tag autocomplete index warmup failed - {exc}", flush=True)

        task = getattr(session_context, "headless_random_warmup_task", None)
        if task is None or task.done():
            session_context.headless_random_warmup_task = asyncio.create_task(run_warmup())
        tag_task = getattr(session_context, "headless_tag_index_warmup_task", None)
        if tag_task is None or tag_task.done():
            session_context.headless_tag_index_warmup_task = asyncio.create_task(run_tag_index_warmup())
        yield

    app = FastAPI(title="NAIA Remote Headless", lifespan=lifespan)
    app.state.web_session_context = session_context
    app.state.headless_clients = set()

    root_web_dir = (
        Path(web_dir).resolve()
        if web_dir is not None
        else resolve_remote_web_dir(session_context.repo_root)
    )
    app.state.remote_web_dir = str(root_web_dir)
    register_web_shell_routes(app, root_web_dir)

    register_state_routes(
        app,
        session_context,
        run_in_thread=_to_thread,
        clients=app.state.headless_clients,
        broadcast_json=_broadcast_json,
        start_generation_runner=_ensure_generation_runner,
    )
    register_install_manager_routes(app, session_context, run_in_thread=_to_thread)
    register_params_workflow_routes(
        app,
        session_context,
        run_in_thread=_to_thread,
        clients=app.state.headless_clients,
        broadcast_json=_broadcast_json,
    )
    register_prompt_tools_routes(
        app,
        session_context,
        run_in_thread=_to_thread,
        clients=app.state.headless_clients,
        broadcast_json=_broadcast_json,
        start_generation_runner=_ensure_generation_runner,
    )
    register_style_thumbnail_routes(app, session_context, run_in_thread=_to_thread)
    register_danbooru_routes(app, session_context, run_in_thread=_to_thread)
    register_event_preset_routes(
        app,
        session_context,
        run_in_thread=_to_thread,
        clients=app.state.headless_clients,
        broadcast_json=_broadcast_json,
        start_generation_runner=_ensure_generation_runner,
    )
    register_artist_thumbnail_routes(
        app,
        session_context,
        run_in_thread=_to_thread,
        clients=app.state.headless_clients,
        start_generation_runner=_ensure_generation_runner,
    )
    register_character_viewer_routes(
        app,
        session_context,
        run_in_thread=_to_thread,
        clients=app.state.headless_clients,
        start_generation_runner=_ensure_generation_runner,
    )
    register_result_display_routes(
        app,
        session_context,
        run_in_thread=_to_thread,
        clients=app.state.headless_clients,
        broadcast_json=_broadcast_json,
    )

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await ws.accept()
        clients: set[WebSocket] = app.state.headless_clients
        clients.add(ws)
        session_id = uuid.uuid4().hex[:8]
        client_host = _client_host(ws)
        try:
            await _send_startup_messages(
                ws,
                session_context,
                session_id=session_id,
                client_host=client_host,
            )
            while True:
                data = await ws.receive_text()
                if data.startswith("{"):
                    try:
                        command = json.loads(data)
                    except json.JSONDecodeError:
                        command = {"type": ""}
                    if isinstance(command, dict):
                        await _handle_json_command(ws, session_context, clients, client_host, command)
                    else:
                        await _handle_text_command(ws, session_context, clients, client_host, data)
                else:
                    await _handle_text_command(ws, session_context, clients, client_host, data)
        except WebSocketDisconnect:
            clients.discard(ws)
            return
        finally:
            clients.discard(ws)

    return app


__all__ = ["create_headless_app"]
