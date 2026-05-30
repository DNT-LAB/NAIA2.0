from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import WebSocket

from app.backend.server.character_viewer_routes import character_viewer_service
from app.backend.server.generation_commands import (
    generation_service,
    persist_prompt_engineering_settings,
    random_service,
)
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


async def _broadcast_automation_state(context: WebSessionContext, clients: set[WebSocket]) -> None:
    """Broadcast the automation runtime as a proper ``module_state`` message.

    The runner pushes automation state on each generation completion, delay
    transition, and failure. These must carry the ``module_state`` envelope
    (``type`` + ``module_id``) or the frontend dispatcher drops them — which is
    why the live remaining time/count never updated in the web UI.
    """
    state = context._automation_service().state()
    await broadcast_json(clients, context._module_state_payload("automation", state))


async def _broadcast_wildcard_state(context: WebSessionContext, clients: set[WebSocket]) -> None:
    """Push the wildcard module state so an open Wildcard Manager updates live.

    Sequential/dependent counters advance and the used-wildcard list changes on
    every generation, but the panel previously only refreshed when reopened
    (``get_module_state``). The frontend dispatcher re-renders the wildcard panel
    only while it is the active/detached module, so this is a cheap no-op for
    users who don't have it open.
    """
    try:
        payload = context._wildcard_module_state()
    except Exception:
        return
    # 라이브 틱 마커: 프론트는 이 플래그가 있을 때만 런타임 섹션을 in-place 갱신하고
    # 파일 브라우저/전체 구조는 보존한다. 마커가 없으면(열기·reload 등) 기존 full rebuild.
    payload["live_update"] = True
    await broadcast_json(clients, payload)


def ensure_generation_runner(context: WebSessionContext, clients: set[WebSocket]) -> None:
    task = getattr(context, "headless_generation_runner_task", None)
    if task is not None and not task.done():
        return
    context.headless_generation_runner_task = asyncio.create_task(run_generation_queue(context, clients))


def ensure_automation_timer_watcher(context: WebSessionContext, clients: set[WebSocket]) -> None:
    """Start the independent timer-expiry watcher for the running automation.

    A timer automation must finish on wall-clock time even when no generation
    is running (future01 QTimer parity). ``record_generation_completed`` only
    sees timer expiry on the next completion, so a timer with idle/stalled
    generation would never finish without this watcher.
    """
    service = context._automation_service()
    run_id = service.active_run_id()
    if not run_id or service.timer_remaining_seconds(run_id) is None:
        return
    task = getattr(context, "automation_timer_watcher_task", None)
    if task is not None and not task.done():
        return
    context.automation_timer_watcher_task = asyncio.create_task(
        _run_automation_timer_watcher(context, clients)
    )


async def _run_automation_timer_watcher(context: WebSessionContext, clients: set[WebSocket]) -> None:
    service = context._automation_service()
    try:
        while True:
            run_id = service.active_run_id()
            if not run_id:
                return
            remaining = service.timer_remaining_seconds(run_id)
            if remaining is None:
                # Not a timer run (count/unlimited finish elsewhere) — stop watching.
                return
            if remaining <= 0:
                policy = service.finish(run_id, reason="timer_complete")
                await _broadcast_automation_state(context, clients)
                for message in policy.get("messages", []):
                    await broadcast_json(clients, message)
                return
            await asyncio.sleep(min(max(remaining, 0.2), 1.0))
    finally:
        context.automation_timer_watcher_task = None


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
            if params.get("character_viewer_request"):
                await _save_character_viewer_thumbnail(context, stored, params)
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
            # 직전 생성에 사용된 와일드카드(순차/종속 카운터 + Used)를 라이브 반영.
            # auto-continue 가 다음 프롬프트로 context 를 덮어쓰기 전에 push 한다.
            await _broadcast_wildcard_state(context, clients)
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
    params = getattr(request, "params", {}) or {}
    automation_run_id = str(params.get("automation_run_id") or "")
    # The Automation controller never tags requests itself (Start only sets the
    # run conditions and engages Auto Gen). Bind a plain Auto Generate completion
    # to the live controller so its timer/count limit is enforced and Auto Gen is
    # disabled when the limit is reached.
    if not automation_run_id and _automation_should_bind(context, request):
        automation_run_id = context._automation_service().active_run_id()
    hold_prompt = False
    if automation_run_id:
        policy = context._automation_service().record_generation_completed(automation_run_id)
        hold_prompt = bool(policy.get("hold_prompt", False))
        await _broadcast_automation_state(context, clients)
        for message in policy.get("messages", []):
            await broadcast_json(clients, message)
        if not policy.get("continue"):
            return False
        delay_seconds = float(policy.get("delay_seconds") or 0.0)
        if delay_seconds > 0:
            context._automation_service().begin_delay(automation_run_id, delay_seconds)
            await _broadcast_automation_state(context, clients)
            if not await _wait_for_automation_delay(context, automation_run_id, delay_seconds):
                await _broadcast_automation_state(context, clients)
                return False
            context._automation_service().end_delay(automation_run_id)
            await _broadcast_automation_state(context, clients)

    if not _should_continue_auto_generation(context, request):
        return False

    prompt_fixed = context._coerce_bool(
        context.get_options().get("prompt_fixed", params.get("prompt_fixed", False))
    )
    # Repeat Count(자동화): hold_prompt면 새 프롬프트를 뽑지 않고 직전 프롬프트를 재사용한다.
    effective_prompt_fixed = prompt_fixed or hold_prompt
    overrides = _auto_generation_overrides(params)
    overrides["auto_generate"] = True
    overrides["prompt_fixed"] = effective_prompt_fixed
    # Auto Gen은 매 반복마다 새 랜덤 시드를 사용한다 (사용자가 seed_fixed로 명시 고정한 경우 제외).
    # 특히 prompt_fixed면 프롬프트가 동일하므로, 직전 생성의 구체 시드를 그대로 재사용하면
    # 같은 이미지만 반복된다. seed=-1로 리셋해 시드 정규화에서 재랜덤화되도록 한다.
    if not context._coerce_bool(overrides.get("seed_fixed", params.get("seed_fixed", False))):
        overrides["seed"] = -1
    queue_source = "Automation" if automation_run_id else "Auto Generate"
    overrides["_remote_queue_source"] = queue_source
    overrides["_remote_queue_label"] = queue_source

    request_id = f"auto-{uuid.uuid4().hex}"
    prompt = str(params.get("input") or params.get("_raw_input") or context.prompt_text or "")
    negative = str(params.get("negative_prompt") or context.negative_prompt_text or "")

    if not effective_prompt_fixed:
        result = await asyncio.to_thread(
            random_service(context).generate,
            active_ratings=context.get_active_ratings(),
            overrides=overrides,
            random_request_id=request_id,
        )
        await persist_prompt_engineering_settings(context)
        payload = result.websocket_payload()
        if not result.success:
            await broadcast_json(clients, payload)
            await broadcast_json(clients, {
                "type": "toast",
                "level": "error",
                "message": payload.get("message") or "Auto Generate stopped: random prompt failed.",
            })
            if automation_run_id:
                failure = context._automation_service().fail(
                    automation_run_id,
                    str(payload.get("message") or "random prompt failed"),
                )
                await _broadcast_automation_state(context, clients)
                for message in failure.get("messages", []):
                    await broadcast_json(clients, message)
            return False

        payload["source"] = "automation" if automation_run_id else "auto_generate"
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
        if automation_run_id:
            failure = context._automation_service().fail(automation_run_id, dispatch.blocked_reason)
            await _broadcast_automation_state(context, clients)
            for message in failure.get("messages", []):
                await broadcast_json(clients, message)
        return False
    await broadcast_json(clients, {"type": "status", "is_generating": False, "message": "queued"})
    return True


def _automation_should_bind(context: WebSessionContext, request) -> bool:
    """Whether a completed request should count against the running Automation
    controller. Mirrors the Auto Generate suppression rules so special requests
    (event preset, character viewer, img2img, etc.) never consume the limit."""
    if not context._automation_service().is_running():
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


def _should_continue_auto_generation(context: WebSessionContext, request) -> bool:
    params = getattr(request, "params", {}) or {}
    if not isinstance(params, dict):
        return False
    automation_run_id = str(params.get("automation_run_id") or "")
    if automation_run_id:
        if not context._automation_service().is_running(automation_run_id):
            return False
    elif not context._coerce_bool(context.get_options().get("auto_generate", False)):
        return False
    queue_manager = context.generation_queue_manager
    if queue_manager.is_paused() or not queue_manager.is_empty():
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


async def _wait_for_automation_delay(
    context: WebSessionContext,
    automation_run_id: str,
    delay_seconds: float,
) -> bool:
    deadline = asyncio.get_running_loop().time() + max(0.0, delay_seconds)
    while True:
        if not context._automation_service().is_running(automation_run_id):
            return False
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return context._automation_service().is_running(automation_run_id)
        await asyncio.sleep(min(1.0, max(0.05, remaining)))


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
    automation_run_id = str(params.get("automation_run_id") or "")
    if automation_run_id:
        failure = context._automation_service().fail(automation_run_id, message)
        await _broadcast_automation_state(context, clients)
        for extra_message in failure.get("messages", []):
            await broadcast_json(clients, extra_message)
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


async def _save_character_viewer_thumbnail(
    context: WebSessionContext,
    stored,
    params: dict,
) -> None:
    """Register a Character Viewer generation result as that character's grid
    thumbnail and enrich the broadcast image_meta so the tab refreshes in place.

    The frontend's handleResultMeta()/refreshThumbnailFromMeta() already consume
    these fields; future02 had built the snapshot in build_generation_overrides
    but never saved the thumbnail or surfaced the fields, so generated images
    never appeared in the Character tab grid."""
    snapshot = params.get("_character_viewer_snapshot")
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    meta = stored.image_meta if isinstance(stored.image_meta, dict) else {}

    thumbnail = None
    if not snapshot.get("save_blocked"):
        try:
            thumbnail = await asyncio.to_thread(
                character_viewer_service(context).save_thumbnail,
                stored.item.image,
                snapshot,
            )
        except Exception as exc:
            print(f"Character Viewer thumbnail save failed: {exc}")

    meta.update({
        "character_viewer_request": True,
        "character_viewer_request_id": str(params.get("character_viewer_request_id") or ""),
        "character_viewer_character": str(params.get("_remote_queue_label") or ""),
        "character_viewer_group": str(snapshot.get("group_key") or ""),
        "character_viewer_character_name": str(snapshot.get("char_name") or ""),
        "character_viewer_variant": str(snapshot.get("variant_label") or ""),
        "character_viewer_thumbnail_saved": bool(thumbnail),
        "character_viewer_thumbnail_url": (
            str(thumbnail.get("url") or "") if isinstance(thumbnail, dict) else ""
        ),
    })


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
