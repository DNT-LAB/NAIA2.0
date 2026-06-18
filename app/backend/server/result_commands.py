from __future__ import annotations

import copy
import io
import json
import math
from typing import Any, Awaitable, Callable

from fastapi import WebSocket

from app.backend.server.result_display_routes import (
    history_item_from_viewer_path,
    resolve_result_image_action_source,
)
from app.backend.server.websocket_broadcast import broadcast_image, broadcast_json
from core.generation_request import GenerationRequest
from core.web_session_context import WebSessionContext


AsyncRunner = Callable[..., Awaitable[Any]]
GenerationEnqueue = Callable[[WebSessionContext, dict[str, Any]], Awaitable[Any]]
GenerationRunnerStarter = Callable[[WebSessionContext, set[WebSocket]], None]

RESULT_COMMAND_TYPES = {
    "result_enhance",
    "set_result_enhance_config",
    "result_image_action",
    "result_upscale",
    "result_outpaint",
}


async def _send_json(ws: WebSocket, payload: dict[str, Any]) -> None:
    await ws.send_text(json.dumps(payload, ensure_ascii=False))


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


def normalize_result_enhance_config(
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
        "runtime": "web",
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


def _enrich_img2img_source_prompt(
    image_bytes: bytes,
    generation_params: dict[str, Any] | None,
    prompt_context: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Recover an external image's prompt/negative from its embedded NAI metadata.

    Used only for the result-context-menu Img2Img/Inpaint path: external (imported /
    saved) images have empty in-app generation_params/prompt_context, so the img2img
    window would otherwise inherit the current prompt box. Leaves generated results
    untouched (they already carry a prompt). Scoped here so the enhance/upscale and
    Grok/Director paths keep their own source semantics.
    """
    gen_params = dict(generation_params or {})
    prompt_ctx = dict(prompt_context or {})
    has_prompt = bool(
        prompt_ctx.get("main_prompt")
        or prompt_ctx.get("final_prompt")
        or prompt_ctx.get("prompt")
        or gen_params.get("input")
    )
    if has_prompt:
        return gen_params, prompt_ctx
    try:
        from utils.image_info import extract_embedded_metadata

        extracted = extract_embedded_metadata(image_bytes)
    except Exception:
        extracted = {}
    if extracted:
        prompt = str(extracted.get("prompt") or "")
        negative = str(extracted.get("negative") or extracted.get("uc") or "")
        if prompt:
            prompt_ctx["main_prompt"] = prompt
        if negative and not gen_params.get("negative_prompt"):
            gen_params["negative_prompt"] = negative
    return gen_params, prompt_ctx


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


def prepare_result_enhance_command(
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
        config = normalize_result_enhance_config(context, payload)
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
        })
    else:
        hires_settings = _normalize_webui_result_enhance_hires_settings(context, payload)
        params.update(hires_settings)
        params["api_mode"] = "WEBUI"
        seed = extract_webui_seed(generation_params)
        if seed is not None:
            params["seed"] = seed
            params["seed_fixed"] = True
        base_w = _result_enhance_dimension(params.get("width"), orig_w)
        base_h = _result_enhance_dimension(params.get("height"), orig_h)
        params.update({
            "init_image_bytes": image_bytes,
            "result_enhance_request": True,
            "result_enhance_backend": "WEBUI",
            "result_enhance_source_size": [orig_w, orig_h],
            "denoising_strength": params.get("denoising_strength", 0.5),
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

    params["result_enhance_source_label"] = label
    generation_command = {
        "type": "generate",
        "api_mode": mode,
        "prompt": str(params.get("input") or ""),
        "negative_prompt": str(params.get("negative_prompt") or ""),
        "overrides": params,
    }
    return generation_command, {
        "type": "result_enhance_state",
        "running": True,
        "success": None,
        "message": "Enhance queued",
        "backend": mode,
        "api_mode": mode,
        "source_size": [orig_w, orig_h],
        "preview_size": params.get("result_enhance_preview_size", [orig_w, orig_h]),
        "request_id": "",
        "runtime": "web",
    }


def _history_item_from_result_payload(context: WebSessionContext, payload: dict[str, Any] | None):
    payload = payload if isinstance(payload, dict) else {}
    source = str(payload.get("source") or "").strip().lower()
    rel_path = str(payload.get("path") or "").strip()
    item = history_item_from_viewer_path(context, rel_path) if rel_path else None
    if item is None and source in {"", "current"}:
        item = context.result_store.latest_item
    return item


def perform_nai_result_upscale(context: WebSessionContext, payload: dict[str, Any] | None):
    if context.get_api_mode() != "NAI":
        raise RuntimeError("NAI 2x upscale is available in NAI mode only")
    image_bytes, label, generation_params, prompt_context = resolve_result_image_action_source(context, payload)
    service = getattr(context, "api_service", None)
    if service is None:
        from core.api_service import APIService

        service = APIService(context)
        context.api_service = service
    result = service.upscale_NAI(None, raw_bytes=image_bytes)
    if not isinstance(result, dict) or result.get("status") != "success":
        raise RuntimeError(str((result or {}).get("message") or "NAI upscale failed"))

    params = copy.deepcopy(generation_params)
    _prompt_from_result_context(context, params, prompt_context)
    for key in ("credential", "schema_only", "options_model", "options_sampler", "options_scheduler", "options_resolution"):
        params.pop(key, None)
    params.update({
        "api_mode": "NAI",
        "result_upscale_request": True,
        "result_upscale_source_label": label,
        "_remote_queue_source": "Result Upscale",
        "_remote_queue_label": label,
    })
    source_item = _history_item_from_result_payload(context, payload)
    request = GenerationRequest(
        params=params,
        source_row=getattr(source_item, "source_row", None),
    )
    stored = context.result_store.add_api_result(result, request)
    if context._coerce_bool(context.auto_save_state.get("auto_save", True)):
        try:
            context.save_history_item(stored.item)
        except Exception:
            pass
    return stored, str(result.get("message") or "NAI 2x upscale complete")


def perform_nai_result_outpaint(context: WebSessionContext, payload: dict[str, Any] | None):
    if context.get_api_mode() != "NAI":
        raise RuntimeError("Outpainting is available in NAI mode only")
    image_bytes, label, generation_params, prompt_context = resolve_result_image_action_source(context, payload)
    service = getattr(context, "api_service", None)
    if service is None:
        from core.api_service import APIService

        service = APIService(context)
        context.api_service = service

    params = copy.deepcopy(generation_params)
    _prompt_from_result_context(context, params, prompt_context)
    for key in ("credential", "schema_only", "options_model", "options_sampler", "options_scheduler", "options_resolution"):
        params.pop(key, None)
    # 원본 항목(img2img/inpaint/이전 outpaint)에서 상속된 raw 바이트/비직렬화 값은 저장 params에
    # 절대 남기지 않는다(메타데이터/히스토리 직렬화 계약 + 결과스토어 비대화 방지, Codex 리뷰
    # HIGH). 또한 상속된 outpaint_canvas_bytes/outpaint_mask_bytes가 api 호출로 새 나가면
    # _single_pass_outpainting이 신규 자동 캔버스 생성을 건너뛰어(잘못된 캔버스) 버린다 →
    # dict(params) 이전에 제거해 새 image_bytes만 auto_outpainting으로 나가게 한다.
    for key in [
        k for k, v in list(params.items())
        if isinstance(v, (bytes, bytearray)) or k in ("full_mask_pil", "type", "cropped_image_request")
    ]:
        params.pop(key, None)
    params.update({
        "api_mode": "NAI",
        "result_outpaint_request": True,
        "result_outpaint_source_label": label,
        "_remote_queue_source": "Result Outpaint",
        "_remote_queue_label": label,
    })
    api_params = dict(params)
    api_params["type"] = "auto_outpainting"
    api_params["image_bytes"] = image_bytes
    result = service.call_generation_api(api_params)
    if not isinstance(result, dict) or result.get("status") != "success":
        raise RuntimeError(str((result or {}).get("message") or "Outpainting failed"))

    source_item = _history_item_from_result_payload(context, payload)
    request = GenerationRequest(
        params=params,
        source_row=getattr(source_item, "source_row", None),
    )
    stored = context.result_store.add_api_result(result, request)
    if context._coerce_bool(context.auto_save_state.get("auto_save", True)):
        try:
            context.save_history_item(stored.item)
        except Exception:
            pass
    return stored, str(result.get("message") or "Outpainting complete")


async def handle_result_command(
    ws: WebSocket,
    context: WebSessionContext,
    clients: set[WebSocket],
    command: dict[str, Any],
    *,
    run_in_thread: AsyncRunner,
    enqueue_generation_request: GenerationEnqueue,
    start_generation_runner: GenerationRunnerStarter,
) -> bool:
    command_type = str(command.get("type") or "").strip()
    if command_type not in RESULT_COMMAND_TYPES:
        return False

    if command_type == "result_upscale":
        await _send_json(ws, {
            "type": "result_upscale_state",
            "running": True,
            "success": None,
            "message": "NAI 2x upscale running",
            "runtime": "web",
        })
        try:
            stored, message = await run_in_thread(perform_nai_result_upscale, context, command)
        except Exception as exc:
            message = f"NAI 2x upscale failed: {exc}"
            await _send_json(ws, {
                "type": "result_upscale_state",
                "running": False,
                "success": False,
                "message": message,
                "runtime": "web",
            })
            await _send_json(ws, {
                "type": "toast",
                "level": "error",
                "message": message,
                "runtime": "web",
            })
            return True
        await broadcast_image(clients, stored.item.webp_bytes, stored.image_meta)
        await broadcast_json(clients, context.result_store.viewer_new_image_payload(stored.item))
        for _evicted in stored.evicted_payloads:
            await broadcast_json(clients, _evicted)
        await broadcast_json(clients, context.auto_save_state_payload())
        await _send_json(ws, {
            "type": "result_upscale_state",
            "running": False,
            "success": True,
            "message": message,
            "runtime": "web",
        })
        await _send_json(ws, {
            "type": "toast",
            "level": "success",
            "message": message,
            "runtime": "web",
        })
        return True

    if command_type == "result_outpaint":
        await _send_json(ws, {
            "type": "toast",
            "level": "info",
            "message": "Outpainting running",
            "runtime": "web",
        })
        try:
            stored, message = await run_in_thread(perform_nai_result_outpaint, context, command)
        except Exception as exc:
            message = f"Outpainting failed: {exc}"
            await _send_json(ws, {
                "type": "toast",
                "level": "error",
                "message": message,
                "runtime": "web",
            })
            return True
        await broadcast_image(clients, stored.item.webp_bytes, stored.image_meta)
        await broadcast_json(clients, context.result_store.viewer_new_image_payload(stored.item))
        for _evicted in stored.evicted_payloads:
            await broadcast_json(clients, _evicted)
        await broadcast_json(clients, context.auto_save_state_payload())
        await _send_json(ws, {
            "type": "toast",
            "level": "success",
            "message": message,
            "runtime": "web",
        })
        return True

    if command_type == "result_enhance":
        # Enhance is a paid, parallel-capable call, so it runs OFF the shared
        # generation queue (like NAI 2x upscale) rather than through
        # enqueue/run_generation_queue. That keeps it from toggling
        # is_generating and locking the Generate button, and lets it run
        # concurrently with a normal generation.
        from app.backend.server.generation_commands import generation_service
        from app.backend.server.generation_runner import _auto_save_generated_history_item

        def _build_enhance_dispatch():
            generation_command, enhance_state = prepare_result_enhance_command(context, command)
            dispatch = generation_service(context).enqueue_remote_request(generation_command, enqueue=False)
            return dispatch, enhance_state

        try:
            dispatch, enhance_state = await run_in_thread(_build_enhance_dispatch)
        except Exception as exc:
            message = f"Enhance request failed: {exc}"
            await _send_json(ws, {
                "type": "result_enhance_state",
                "running": False,
                "success": False,
                "message": message,
                "runtime": "web",
            })
            await _send_json(ws, {
                "type": "toast",
                "level": "error",
                "message": message,
                "runtime": "web",
            })
            return True
        if not dispatch.ok or dispatch.request is None:
            await _send_json(ws, dispatch.websocket_payload())
            await _send_json(ws, {
                "type": "result_enhance_state",
                "running": False,
                "success": False,
                "message": dispatch.blocked_reason,
                "runtime": "web",
            })
            await _send_json(ws, {
                "type": "toast",
                "level": "error",
                "message": dispatch.blocked_reason,
                "runtime": "web",
            })
            return True
        enhance_request_id = str(dispatch.request.request_id)
        await _send_json(ws, enhance_state)
        await _send_json(ws, {
            "type": "result_enhance_state",
            "running": True,
            "success": None,
            "message": "Enhance running",
            "request_id": enhance_request_id,
            "runtime": "web",
        })
        try:
            stored = await run_in_thread(generation_service(context).execute_request, dispatch.request)
        except Exception as exc:
            message = f"Enhance failed: {exc}"
            await _send_json(ws, {
                "type": "result_enhance_state",
                "running": False,
                "success": False,
                "message": message,
                "request_id": enhance_request_id,
                "runtime": "web",
            })
            await _send_json(ws, {
                "type": "toast",
                "level": "error",
                "message": message,
                "runtime": "web",
            })
            return True
        await _auto_save_generated_history_item(context, stored.item)
        await broadcast_image(clients, stored.item.webp_bytes, stored.image_meta)
        await broadcast_json(clients, context.result_store.viewer_new_image_payload(stored.item))
        for _evicted in stored.evicted_payloads:
            await broadcast_json(clients, _evicted)
        await broadcast_json(clients, context.auto_save_state_payload())
        await _send_json(ws, {
            "type": "result_enhance_state",
            "running": False,
            "success": True,
            "message": "Enhance complete",
            "request_id": enhance_request_id,
            "runtime": "web",
        })
        await _send_json(ws, {
            "type": "toast",
            "level": "success",
            "message": "Enhance complete",
            "runtime": "web",
        })
        return True

    if command_type == "set_result_enhance_config":
        config = normalize_result_enhance_config(context, command)
        context.result_enhance_config = {
            "upscale": config["upscale"],
            "strength": config["strength"],
            "noise": config["noise"],
        }
        await _send_json(ws, {**config, "_session_echo": True})
        await _send_json(ws, {
            "type": "toast",
            "level": "success",
            "message": "Enhance settings updated",
            "runtime": "web",
        })
        return True

    action = str(command.get("action") or "image_action")
    if action not in {"img2img", "inpaint"}:
        await _send_json(ws, {
            "type": "toast",
            "level": "error",
            "message": "Unsupported result image action",
            "runtime": "web",
        })
        return True
    if context.get_api_mode() != "NAI":
        await _send_json(ws, {
            "type": "toast",
            "level": "error",
            "message": "Img2Img/Inpaint is available in NAI mode only",
            "runtime": "web",
        })
        return True
    try:
        image_bytes, label, generation_params, prompt_context = await run_in_thread(
            resolve_result_image_action_source,
            context,
            command,
        )
        # External images (imported/saved) carry no in-app params, so without this the
        # img2img/inpaint window would inherit the CURRENT prompt box instead of the
        # image's own prompt. Recover prompt/negative from the image's embedded NAI
        # metadata when the in-app prompt is missing.
        generation_params, prompt_context = await run_in_thread(
            _enrich_img2img_source_prompt,
            image_bytes,
            generation_params,
            prompt_context,
        )
        state = await run_in_thread(
            context.open_img2img_session_from_bytes,
            image_bytes,
            label=label,
            mode=action,
            generation_params=generation_params,
            prompt_context=prompt_context,
        )
    except Exception as exc:
        await _send_json(ws, {
            "type": "toast",
            "level": "error",
            "message": f"Image action failed: {exc}",
            "runtime": "web",
        })
        return True
    await _send_json(ws, state)
    await _send_json(ws, {
        "type": "toast",
        "level": "success",
        "message": f"{'Inpaint' if action == 'inpaint' else 'Img2Img'} session ready",
        "runtime": "web",
    })
    return True
