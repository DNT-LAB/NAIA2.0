from __future__ import annotations

import asyncio
import random
import uuid
from typing import Any

from fastapi import WebSocket

from app.backend.server.character_viewer_routes import character_viewer_service
from app.backend.server.generation_commands import (
    generation_service,
    persist_prompt_engineering_settings,
    random_service,
)
from app.backend.server.anlas_poller import broadcast_anlas_if_vibe_encoded
from app.backend.server.prompt_tools_routes import save_prompt_engineering_thumbnail_bytes
from app.backend.server.websocket_broadcast import broadcast_image, broadcast_json
from core import result_image_payload_service as result_images
# 특수 요청 판정은 core와 공유한다(Storyteller Use Vibe가 같은 기준으로 plain generate를
# 가르므로) — 정의가 두 군데로 갈라지지 않게 core/auto_generation_flags.py가 단일 출처.
from core.auto_generation_flags import AUTO_GENERATE_SUPPRESSED_FLAGS, SPECIAL_REQUEST_TYPES
from core.event_stream_vibe import EVENT_STREAM_VIBE_CAPTURE_KEY
from core.web_session_context import WebSessionContext

AUTO_GENERATE_DROPPED_PARAM_KEYS = {
    "_generation_request",
    "credential",
    "generation_request_id",
    "promptRunId",
    "prompt_run_id",
    "requestId",
    "request_id",
    "result_enhance_request_id",
    # WEBUI custom payload is a live session setting committed to remote_params (via the editor's
    # Apply). Don't pin it into auto-gen continuation overrides, or an Apply mid-run would be
    # ignored — dropping it lets each iteration re-merge the CURRENT remote_params value.
    "webui_custom_payload",
    "webui_custom_payload_enabled",
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


async def _broadcast_storyteller_state(context: WebSessionContext, clients: set[WebSocket]) -> None:
    """Broadcast the Storyteller cycle runtime as a module_state message so the panel's
    live page progress (completed/target) updates on every completion. The service's
    state() already returns a wrapped module_state payload."""
    await broadcast_json(clients, context._storyteller_service().state())


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
                # 실패한 시퀀스 프레임도 라운드 카운트를 진전시켜야 연속 루프가 멈추지 않는다(Codex).
                try:
                    await _advance_sequence_run(context, clients, request)
                except Exception:
                    pass
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
            for _evicted in stored.evicted_payloads:
                await broadcast_json(clients, _evicted)
            # 직전 생성에 사용된 와일드카드(순차/종속 카운터 + Used)를 라이브 반영.
            # auto-continue 가 다음 프롬프트로 context 를 덮어쓰기 전에 push 한다.
            await _broadcast_wildcard_state(context, clients)
            # 스트림(스토리/수동 진행) 활성 시 시퀀스 위치를 라이브 반영 — Random 버튼의
            # (n/m) 배지와 패널의 현재 스텝 표시가 생성마다 갱신된다.
            event_stream_runtime = getattr(context, "event_stream_runtime", None)
            if event_stream_runtime is not None and getattr(event_stream_runtime, "is_active", False):
                try:
                    await broadcast_json(clients, context._event_stream_module_state())
                except Exception:
                    pass
            # Storyteller Use Vibe: use_vibe 스텝의 완료 이미지를 런타임에 보관한다(Anlas 0).
            # stamp의 run_id가 활성 런과 일치할 때만 — stale/특수 완료의 오캡처를 stamp-only
            # 바인딩으로 차단. seq는 완료 역순 도착 시 '가장 나중에 시작한' 생성이 이기게
            # 하는 단조 게이트. 인코딩(2 Anlas)은 다음 스텝 전진 시점에 1회만 일어난다.
            vibe_capture = params.get(EVENT_STREAM_VIBE_CAPTURE_KEY)
            if vibe_capture and event_stream_runtime is not None:
                store_vibe = getattr(event_stream_runtime, "store_vibe_source", None)
                if callable(store_vibe):
                    capture_run = (
                        vibe_capture.get("run_id") if isinstance(vibe_capture, dict) else vibe_capture
                    )
                    capture_seq = (
                        vibe_capture.get("seq") if isinstance(vibe_capture, dict) else None
                    )
                    try:
                        store_vibe(
                            stored.item.raw_bytes,
                            run_id=str(capture_run or ""),
                            seq=capture_seq,
                        )
                    except Exception:
                        pass
            # Guard the auto-continue (prompt gen / PE persist / enqueue) so a raised
            # exception after a story page was counted still cleans up the cycle
            # (_broadcast_generation_error fails the stamped story) instead of leaving the
            # freeze + Auto Gen armed.
            try:
                await _maybe_continue_auto_generation(context, clients, request)
            except Exception as exc:
                await _broadcast_generation_error(context, clients, request, str(exc))
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


async def _advance_sequence_run(context: WebSessionContext, clients: set[WebSocket], request) -> bool:
    """Sequence 프레임 완료(성공·실패 공통) 처리. 시퀀스 프레임이면 라운드 카운트를 진전시키고,
    라운드 완료 시 Auto Gen ON·큐 빔이면 다음 랜덤 그룹으로 연속(continue_sequence_run), 아니면
    종료한다. 시퀀스 프레임이 아니면 False(미처리). 성공 완료(_maybe_continue)와 실행 실패(except)
    양쪽에서 호출돼 실패 프레임도 카운트되므로 루프가 영구 정지하지 않는다(Codex MUST-FIX)."""
    params = getattr(request, "params", {}) or {}
    sequence_run_id = str(params.get("sequence_run_id") or "")
    if not sequence_run_id or not context._sequence_run_service().is_running(sequence_run_id):
        return False
    seq_service = context._sequence_run_service()
    policy = seq_service.record_generation_completed(sequence_run_id)
    try:
        await broadcast_json(clients, context._sequence_run_module_state())
    except Exception:
        pass
    for message in policy.get("messages", []):
        await broadcast_json(clients, message)
    if not policy.get("round_done"):
        return True  # 라운드 진행 중 — 남은 프레임은 큐가 그대로 드레인
    # 라운드 완료 — Auto Gen ON(라이브) + 큐 빔이면 다음 랜덤 그룹 연속, 아니면 종료.
    auto_gen = context._coerce_bool(context.get_options().get("auto_generate", False))
    queue_manager = context.generation_queue_manager
    advanced = False
    if auto_gen and not queue_manager.is_paused() and queue_manager.is_empty():
        from app.backend.server.sequence_preset_routes import continue_sequence_run
        advanced = await continue_sequence_run(context, clients, sequence_run_id, broadcast_json)
    if not advanced:
        finish = seq_service.finish(sequence_run_id, reason="complete")
        try:
            await broadcast_json(clients, context._sequence_run_module_state())
        except Exception:
            pass
        for message in finish.get("messages", []):
            await broadcast_json(clients, message)
    return True


async def _maybe_continue_auto_generation(
    context: WebSessionContext,
    clients: set[WebSocket],
    request,
) -> bool:
    params = getattr(request, "params", {}) or {}

    # Sequence 연속 생성(Auto Gen): 시퀀스 프레임이면 _advance_sequence_run 이 라운드 카운트를
    # 진전시키고(완료 시 다음 랜덤 그룹 연속 또는 종료) True 를 돌려준다. 시퀀스는 '그룹 전체'를
    # 새로 넣으므로 아래 제네릭 프롬프트 재롤 경로를 타면 안 된다 — 처리됐으면 곧장 return.
    if await _advance_sequence_run(context, clients, request):
        return False

    # Run-policy controller bound to this completion. Storyteller and Automation each own
    # the single Auto Generate loop and are mutually exclusive; Storyteller takes
    # precedence. The controller never tags the FIRST request itself (Start only arms Auto
    # Gen), so bind a plain Auto Gen completion to the live controller so its page/timer/
    # count limit is enforced and Auto Gen is disabled when the limit is reached.
    # Storyteller binds ONLY via the explicit run-id stamp that start_cycle and each
    # continuation put on the request — never by "a story is running" — so a stale,
    # manual, or special (img2img/preset/etc.) untagged completion can't be miscounted
    # as a page of the cycle.
    story_run_id = str(params.get("event_stream_run_id") or "")
    if story_run_id and not context._storyteller_service().is_running(story_run_id):
        story_run_id = ""

    automation_run_id = ""
    if not story_run_id:
        automation_run_id = str(params.get("automation_run_id") or "")
        if not automation_run_id and _automation_should_bind(context, request):
            automation_run_id = context._automation_service().active_run_id()

    hold_prompt = False
    if story_run_id:
        policy = context._storyteller_service().record_generation_completed(story_run_id)
        await _broadcast_storyteller_state(context, clients)
        for message in policy.get("messages", []):
            await broadcast_json(clients, message)
        if not policy.get("continue"):
            return False
    elif automation_run_id:
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
        # A story page was just counted but the loop can't continue (Auto Gen turned off,
        # queue paused, etc.). Finish the story so the freeze snapshot + runtime don't stay
        # stuck armed below the page target.
        if story_run_id and context._storyteller_service().is_running(story_run_id):
            policy = context._storyteller_service().finish(story_run_id, reason="stopped")
            await _broadcast_storyteller_state(context, clients)
            for message in policy.get("messages", []):
                await broadcast_json(clients, message)
        return False

    prompt_fixed = context._coerce_bool(
        context.get_options().get("prompt_fixed", params.get("prompt_fixed", False))
    )
    # Repeat Count(자동화): hold_prompt면 새 프롬프트를 뽑지 않고 직전 프롬프트를 재사용한다.
    # 단, 스토리는 매 페이지 새 구도를 뽑아야 하므로 prompt_fixed/hold_prompt를 무시한다.
    effective_prompt_fixed = (prompt_fixed or hold_prompt) and not story_run_id
    overrides = _auto_generation_overrides(params)
    overrides["auto_generate"] = True
    overrides["prompt_fixed"] = effective_prompt_fixed
    # Auto Gen은 매 반복마다 새 랜덤 시드를 사용한다 (사용자가 seed_fixed로 명시 고정한 경우 제외).
    # 특히 prompt_fixed면 프롬프트가 동일하므로, 직전 생성의 구체 시드를 그대로 재사용하면
    # 같은 이미지만 반복된다. seed=-1로 리셋해 시드 정규화에서 재랜덤화되도록 한다.
    if not context._coerce_bool(overrides.get("seed_fixed", params.get("seed_fixed", False))):
        overrides["seed"] = -1
    # Rnd Res must re-roll every Auto Gen iteration, exactly like a manual Random
    # press. The frontend picks a random resolution per click (_collectCurrentParams),
    # but this server-side loop reuses the previous params, so without this the
    # resolution stays frozen when Rnd Res is on without Auto Res. (Auto Res still
    # wins afterwards via detected_resolution when both are enabled.)
    _reroll_random_resolution(context, overrides)
    if story_run_id:
        # Carry the story run id so the next completion re-binds to this same cycle.
        overrides["event_stream_run_id"] = story_run_id
        queue_source = "Storyteller"
        # 직전 페이지 params에 바인딩된 vibe reference(일반+스트림)가 overrides로 핀되지
        # 않게 제거 — 다음 페이지는 enqueue 시점에 라이브 일반 vibe + 현재 스트림 vibe
        # 1장을 새로 받는다(누적/고착 차단, Use Vibe '딱 1장' 보장의 1차 방어).
        for key in (
            "reference_image_multiple",
            "reference_strength_multiple",
            "normalize_reference_strength_multiple",
            "reference_information_extracted_multiple",
        ):
            overrides.pop(key, None)
    elif automation_run_id:
        queue_source = "Automation"
    else:
        queue_source = "Auto Generate"
    overrides["_remote_queue_source"] = queue_source
    overrides["_remote_queue_label"] = queue_source

    request_id = f"auto-{uuid.uuid4().hex}"
    prompt = str(params.get("input") or params.get("_raw_input") or context.prompt_text or "")
    negative = str(params.get("negative_prompt") or context.negative_prompt_text or "")

    # Storyteller 다음 페이지의 스텝별 해상도 계획. carry(의상/배경 유지)는 더 이상
    # 여기서 다루지 않는다 — EventStreamRuntime이 prepare 시점에 노드 policy로 직접
    # 적용한다(수동 진행/자동 사이클 공통).
    story_plan = None
    if story_run_id:
        # 사이클 페이지 마커: 수동 랜덤과 구분(연쇄 억제 예외 등).
        overrides["_storyteller_page"] = True
        story_plan = context._storyteller_service().page_plan(story_run_id)
        # 'default' 스텝: 이전 스텝이 stamped한 해상도가 이 페이지로 상속되지 않게 시작
        # 시점 베이스(UI 값)로 복원한다. Rnd Res가 켜져 있으면 방금 재추첨한 값을 존중하고,
        # Auto Res(detected)는 생성 후 정상 적용된다. 스텝이 해상도를 지정하면 생성 후
        # 그 값이 최종 우선.
        if story_plan is not None and not (story_plan.get("width") and story_plan.get("height")):
            if not context._coerce_bool(overrides.get("random_resolution", False)):
                base = story_plan.get("base_resolution") or {}
                if base.get("width") and base.get("height"):
                    overrides["width"] = base["width"]
                    overrides["height"] = base["height"]
                    overrides["resolution"] = (
                        base.get("resolution") or f"{base['width']} x {base['height']}"
                    )
                else:
                    overrides.pop("width", None)
                    overrides.pop("height", None)
                    overrides.pop("resolution", None)

    if not effective_prompt_fixed:
        result = await asyncio.to_thread(
            random_service(context).generate,
            active_ratings=context.get_active_ratings(),
            overrides=overrides,
            random_request_id=request_id,
        )
        await persist_prompt_engineering_settings(context)
        # Use Vibe 인코딩(2 Anlas)이 이 페이지 전진에서 일어났다면 잔액 차감 즉시 반영
        # (자동 사이클 continuation 경로).
        await broadcast_anlas_if_vibe_encoded(context, clients)
        payload = result.websocket_payload()
        if not result.success:
            await broadcast_json(clients, payload)
            await broadcast_json(clients, {
                "type": "toast",
                "level": "error",
                "message": payload.get("message") or "Auto Generate stopped: random prompt failed.",
            })
            if story_run_id:
                failure = context._storyteller_service().fail(
                    story_run_id,
                    str(payload.get("message") or "random prompt failed"),
                )
                await _broadcast_storyteller_state(context, clients)
                for message in failure.get("messages", []):
                    await broadcast_json(clients, message)
            elif automation_run_id:
                failure = context._automation_service().fail(
                    automation_run_id,
                    str(payload.get("message") or "random prompt failed"),
                )
                await _broadcast_automation_state(context, clients)
                for message in failure.get("messages", []):
                    await broadcast_json(clients, message)
            return False

        payload["source"] = (
            "storyteller" if story_run_id
            else ("automation" if automation_run_id else "auto_generate")
        )
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
        if story_run_id:
            # 스텝별 해상도는 Auto Res/Rnd Res 값보다 우선한다.
            if story_plan and story_plan.get("width") and story_plan.get("height"):
                overrides["width"] = story_plan["width"]
                overrides["height"] = story_plan["height"]
                overrides["resolution"] = f"{story_plan['width']} x {story_plan['height']}"
            # 이번 페이지 해상도 기록('previous' 해상도용). carry 추출은 런타임 담당.
            context._storyteller_service().record_page_outcome(
                story_run_id,
                width=overrides.get("width"),
                height=overrides.get("height"),
            )

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
        if story_run_id:
            failure = context._storyteller_service().fail(story_run_id, dispatch.blocked_reason)
            await _broadcast_storyteller_state(context, clients)
            for message in failure.get("messages", []):
                await broadcast_json(clients, message)
        elif automation_run_id:
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
    if request_type in SPECIAL_REQUEST_TYPES:
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
    if request_type in SPECIAL_REQUEST_TYPES:
        return False
    return True


def _parse_resolution_label(label: Any) -> tuple[int | None, int | None]:
    try:
        parts = str(label or "").lower().replace("×", "x").split("x")
        if len(parts) == 2:
            return int(parts[0].strip()), int(parts[1].strip())
    except (ValueError, TypeError):
        pass
    return None, None


def _reroll_random_resolution(context: WebSessionContext, overrides: dict[str, Any]) -> None:
    """Re-pick a random resolution for the next Auto Gen iteration when Rnd Res is on.

    Auto Gen loops server-side, so the frontend's per-click random pick
    (_collectCurrentParams) never re-rolls — only the seed and Auto Res do. Mirror
    the manual Random behaviour here, drawing from the same option set the dropdown
    offers (NAI standard 1MP labels, or the resolution preset labels for WEBUI/COMFYUI).
    """
    if not context._coerce_bool(overrides.get("random_resolution", False)):
        return
    from core.resolution_utils import (
        ANIMA_RESOLUTION_PRESET_LABELS,
        STANDARD_1MP_RESOLUTION_LABELS,
        normalize_anima_resolution_preset_id,
    )

    mode = str(overrides.get("api_mode") or context.get_api_mode() or "").strip().upper()
    labels: tuple[str, ...] = ()
    if mode in {"WEBUI", "COMFYUI"} and context._coerce_bool(overrides.get("resolution_preset_enabled", False)):
        preset = normalize_anima_resolution_preset_id(overrides.get("resolution_preset"))
        labels = ANIMA_RESOLUTION_PRESET_LABELS.get(preset) or ()
    if not labels:
        # Res Preset이 아니면 해상도 매니저가 저장한 모드별 사용자 목록에서 추첨
        # — 드롭다운(프론트 per-click 추첨)과 동일한 모집단. 목록을 2개로 줄였는데
        # Auto Gen이 기본 7종 전체에서 뽑던 버그 수정.
        try:
            labels = tuple(context.resolution_options_for_mode(mode))
        except Exception:
            labels = ()
    if not labels:
        labels = STANDARD_1MP_RESOLUTION_LABELS
    if not labels:
        return
    picked = random.choice(labels)
    overrides["resolution"] = picked
    width, height = _parse_resolution_label(picked)
    if width and height:
        overrides["width"] = width
        overrides["height"] = height


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
    story_run_id = str(params.get("event_stream_run_id") or "")
    if story_run_id and context._storyteller_service().is_running(story_run_id):
        failure = context._storyteller_service().fail(story_run_id, message)
        await _broadcast_storyteller_state(context, clients)
        for extra_message in failure.get("messages", []):
            await broadcast_json(clients, extra_message)
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
    if params.get("sequence_preset_request"):
        await broadcast_json(clients, {
            "type": "sequence_preset_generation_error",
            "requestId": str(params.get("sequence_preset_request_id") or ""),
            "groupId": str(params.get("sequence_preset_group_id") or ""),
            "frame": str(params.get("sequence_preset_frame") or ""),
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
