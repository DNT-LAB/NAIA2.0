from __future__ import annotations

import asyncio
import random
import uuid
from typing import Any

from fastapi import WebSocket

from app.backend.server.artist_thumbnail_routes import artist_thumbnail_service
from app.backend.server.character_viewer_routes import character_viewer_service
from app.backend.server.generation_commands import (
    generation_service,
    persist_prompt_engineering_settings,
    random_service,
)
from app.backend.server.anlas_poller import (
    broadcast_anlas,
    broadcast_anlas_if_vibe_encoded,
    schedule_subscription_refresh,
    usage_badge_active,
)
from app.backend.server.prompt_tools_routes import save_prompt_engineering_thumbnail_bytes
from app.backend.server.websocket_broadcast import broadcast_image, broadcast_json, broadcast_preview_image
from core import result_image_payload_service as result_images
# 특수 요청 판정은 core와 공유한다(Storyteller Use Vibe가 같은 기준으로 plain generate를
# 가르므로) — 정의가 두 군데로 갈라지지 않게 core/auto_generation_flags.py가 단일 출처.
from core.auto_generation_flags import (
    AUTO_GENERATE_SUPPRESSED_FLAGS,
    REFERENCE_INSET_PIN_MARKER,
    SPECIAL_REQUEST_TYPES,
    is_special_request,
)
from core.event_stream_vibe import (
    EVENT_STREAM_VIBE_CAPTURE_KEY,
    SEQUENCE_VIBE_IE,
    SEQUENCE_VIBE_STRENGTH,
    halve_floor_strength,
)
from core.headless_image_module_param_service import (
    CHARACTER_REFERENCE_LIVE_REFETCH_KEYS,
    REFERENCE_INSET_LIVE_REFETCH_KEYS,
    VIBE_TRANSFER_LIVE_REFETCH_KEYS,
)
from core.web_session_context import WebSessionContext

# Event/Remote Preset completions count toward a running Automation's count/timer.
# Server-side preset continuation remains suppressed; the frontend owns that loop.
_AUTOMATION_BINDABLE_DESPITE_SUPPRESSION = {
    "event_preset_request",
    "remote_preset_request",
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
    # WEBUI custom payload is a live session setting committed to remote_params (via the editor's
    # Apply). Don't pin it into auto-gen continuation overrides, or an Apply mid-run would be
    # ignored — dropping it lets each iteration re-merge the CURRENT remote_params value.
    "webui_custom_payload",
    "webui_custom_payload_enabled",
}

# Auto Gen continuation 에서 overrides 로 핀하면 안 되는 라이브 PARAMS 의 예외(전용 로직이 관리).
# seed: 매 반복 -1 리셋(랜덤 재시드) 또는 seed_fixed 시 유지. resolution/width/height/random_resolution:
# Rnd Res 재추첨/Auto Res 가 별도 처리.
# ⚠️ 이 예외는 **전용 로직이 실제로 돈다는 전제** 위에 서 있다. Rnd Res OFF + Prompt Fix ON
#    이면 하나도 안 돌아 핀이 영원히 살았다(2026-08-29 실측). 그래서
#    `_maybe_continue_auto_generation` 이 전용 로직 **앞에서** 해상도 셋을 먼저 놓는다 -
#    여기 예외 목록은 그 뒤에 **쓰인 값**을 지키는 용도로만 남는다.
AUTO_GEN_PARAM_PIN_EXEMPT = {"seed", "seed_fixed", "resolution", "width", "height", "random_resolution"}


def _drop_live_param_overrides(overrides: dict[str, Any], remote_params: Any) -> None:
    """Auto Gen continuation: PARAMS 패널 값(steps/cfg/sampler/scheduler/model + ComfyUI
    sampling_mode/rescale_cfg/anima_weight/comfyui_workflow*, WEBUI hr_* 등)은 모두 remote_params
    에 사는 라이브 세션 설정이다 — webui_custom_payload 와 같은 클래스. 직전 생성에서 baked 된 값이
    overrides 로 핀되면 enqueue 의 ``params.update(overrides)`` 가 라이브 ``params.update(remote_params)``
    를 덮어써 Auto Gen 도중 PARAMS 변경이 무시된다(특히 ComfyUI/ANIMA 사용자 리포트). remote_params
    에 존재하는 키를 overrides 에서 제거해 매 반복 라이브 재조회되게 한다(seed/해상도 계열 제외)."""
    try:
        for key in list(remote_params or {}):
            if key not in AUTO_GEN_PARAM_PIN_EXEMPT:
                overrides.pop(key, None)
    except Exception:
        pass


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


async def _broadcast_img2img_generation_state(
    context: WebSessionContext,
    clients: set[WebSocket],
) -> None:
    """Broadcast the lightweight session lifecycle without resending image/mask data."""
    service = _img2img_lifecycle_service(context)
    if service is not None:
        await broadcast_json(clients, service.generation_event_payload())


def _img2img_lifecycle_service(context: WebSessionContext):
    factory = getattr(context, "_img2img_service", None)
    if not callable(factory):
        return None
    try:
        return factory()
    except Exception:
        return None


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


# ── Ollama Auto Boost 오버랩(프리페치) ───────────────────────────────────────
# 일반 Auto Gen/Automation에서 boost(느린 LLM)를 이미지 생성 대기와 겹쳐 "공짜"로 만든다.
#   생산자: 현재 이미지 enqueue 직전, 다음 랜덤 행을 예약(pop)하고 그 행의 raw 태그로 boost를
#           백그라운드 계산해 1슬롯 홀더에 채운다(부작용 0 — full generate는 안 함).
#   소비자: continuation에서 홀더가 유효하면 예약 행을 generate(source_row_override)로 소비하고
#           미리 만든 boost를 concat. 무효/미준비/실패면 동기 폴백(Phase 1).
# Story/Preset/특수요청·prompt_fixed·활성 태그필터는 제외(Codex 정제안). depth=1.
_PREFETCH_BOOST_GRACE = 3.0  # 소비 시 boost가 아직이면 이만큼만 기다리고, 안 되면 이번 컷 boost 생략.


def _ollama_boost_settings_token(context: WebSessionContext) -> tuple:
    """prefetch 유효성용 설정 토큰(해시 가능). 설정(가중치·effort·include) 변경 시 stale
    감지 — 옛 effort/입력으로 만든 boost를 새 설정으로 삽입하는 걸 막는다(Codex Must-fix 3)."""
    try:
        from app.backend.server.ollama_routes import ollama_boost_settings

        s = ollama_boost_settings(context)
        return (
            round(float(s.get("nl_weight", 1.0)), 3), str(s.get("effort") or "rich"),
            bool(s.get("include_prefix")), bool(s.get("include_postfix")), bool(s.get("include_e621")),
            bool(s.get("allow_scent_style", True)), bool(s.get("allow_material_style", True)),
            bool(s.get("allow_light_style", True)),
        )
    except Exception:
        return ()


def _auto_gen_prefetch_state_key(context: WebSessionContext, ratings) -> tuple:
    """예약 행/boost 유효성 토큰. 검색풀 교체(재검색)·등급·API모드·토글·boost 설정 변경을 잡는다.
    (풀 count는 매 생성 변하므로 제외 — 풀 advance는 명시 무효화[수동 random]로 처리.)"""
    return (
        id(getattr(context, "search_results", None)),
        tuple(sorted(ratings or [])),
        str(getattr(context, "current_api_mode", "") or ""),
        bool(getattr(context, "ollama_auto_boost", False)),
        _ollama_boost_settings_token(context),
    )


def _auto_gen_prefetch_eligible(context: WebSessionContext, request) -> bool:
    """프리페치 자격: 토글 ON·일반 Auto Gen(또는 Automation)·Story/Preset/특수 아님·
    prompt_fixed 아님·활성 태그필터 없음."""
    if not getattr(context, "ollama_auto_boost", False):
        return False
    # include_*(prefix/postfix/e621) 중 하나라도 ON이면 prefetch 비활성 → 동기 폴백. 오버랩
    # 선행 단계는 raw store 값(와일드카드 미전개)·파이프라인 전이라, sync 경로(processed
    # context: 전개된 prefix/postfix + 산출된 e621)와 입력이 달라진다. 정확성 우선(Codex
    # Must-fix 4 + round2 minor). 기본(모두 OFF)은 prefetch 유지 — 입력=장면 태그만이라 양 경로 동일.
    try:
        from app.backend.server.ollama_routes import ollama_boost_settings

        _obs = ollama_boost_settings(context)
        if _obs.get("include_e621") or _obs.get("include_prefix") or _obs.get("include_postfix"):
            return False
    except Exception:
        pass
    params = getattr(request, "params", {}) or {}
    if not isinstance(params, dict):
        return False
    if str(params.get("event_stream_run_id") or ""):
        return False  # Story
    if is_special_request(params, context._coerce_bool):
        return False  # Preset/특수(img2img·이벤트프리셋·인핸스 등)
    if context._coerce_bool(params.get("prompt_fixed", context.get_options().get("prompt_fixed", False))):
        return False  # 고정 프롬프트 → 새 랜덤 없음
    auto_on = context._coerce_bool(context.get_options().get("auto_generate", False))
    automation_on = bool(str(params.get("automation_run_id") or ""))
    if not (auto_on or automation_on):
        return False
    # wildcard_standalone이면 prepare_next_source가 standalone 행을 우선해 예약 행을 무시한다 —
    # 그러면 boost(예약 행 기반)가 엉뚱한 standalone 프롬프트에 붙으므로 제외(Codex). 요청
    # 단위 플래그(params)를 먼저 보고, 없으면 세션 옵션으로 폴백(요청 우선 — 가드 순서 버그 수정).
    if context._coerce_bool(params.get("wildcard_standalone", context.get_options().get("wildcard_standalone", False))):
        return False
    # 큐가 비고 일시정지 아님일 때만 예약 — 다중/수동 큐 중 예약하면 continuation이
    # _should_continue_auto_generation(큐 비어야 함)에서 거부해 예약이 낭비된다(Codex).
    qm = getattr(context, "generation_queue_manager", None)
    try:
        if qm is None or qm.is_paused() or not qm.is_empty():
            return False
    except Exception:
        return False
    try:
        if random_service(context)._active_tag_filter_state() is not None:
            return False  # 활성 태그필터 — v1 비활성(롤백 복잡도 회피)
    except Exception:
        return False
    return True


def _release_auto_gen_prefetch(context: WebSessionContext) -> None:
    """프리페치 홀더 폐기(예약 행은 버림 — 무시 가능 손실). 진행 중 task는 cancel."""
    holder = getattr(context, "_auto_gen_prefetch", None)
    if holder:
        task = holder.get("task")
        if task is not None and not task.done():
            task.cancel()
    context._auto_gen_prefetch = None


def _kickoff_auto_gen_prefetch(context: WebSessionContext, request) -> None:
    """이미지 생성 직전 호출 — 다음 랜덤 행 예약 + boost를 백그라운드 선행(현재 생성과 겹침)."""
    try:
        if getattr(context, "_auto_gen_prefetch", None) is not None:
            return  # 이미 채워짐/진행 중
        if not _auto_gen_prefetch_eligible(context, request):
            return
        ratings = context.get_active_ratings()
        reserved = random_service(context).reserve_next_random_row(ratings)
        if reserved is None:
            return
        try:
            general = str(reserved.get("general") or "")
        except Exception:
            general = ""
        from app.backend.server.ollama_routes import ollama_boost_settings, scene_boost_prompt
        from core.scene_boost import strip_weight_syntax

        # prefetch는 모든 include OFF일 때만 동작(eligible 가드) → 입력 = 장면 태그(general)만,
        # 가중치 제거. (prefix/postfix/e621 포함 시엔 prefetch 끄고 동기 폴백이 정확히 처리.)
        boost_settings = ollama_boost_settings(context)
        boost_input = strip_weight_syntax(general) or general
        # Effort([기능2]) 명시 전달 + 설정을 holder에 freeze — 소비 시 kickoff 시점 설정으로
        # 조립해, 생성 중 설정을 바꿔도 옛 boost를 새 설정으로 삽입하지 않는다(Codex Must-fix 3).
        task = asyncio.create_task(
            asyncio.to_thread(
                scene_boost_prompt,
                context,
                boost_input,
                level=boost_settings.get("effort"),
                allow_scent_style=boost_settings.get("allow_scent_style"),
                allow_material_style=boost_settings.get("allow_material_style"),
                allow_light_style=boost_settings.get("allow_light_style"),
                emphasize_framing=boost_settings.get("emphasize_framing"),
            )
        )
        context._auto_gen_prefetch = {
            "state_key": _auto_gen_prefetch_state_key(context, ratings),
            "source_row": reserved,
            "task": task,
            "settings": boost_settings,
        }
    except Exception:
        context._auto_gen_prefetch = None  # 프리페치 실패는 무해 — 소비 시 동기 폴백.


def _apply_prefetched_boost(context: WebSessionContext, result, boost, settings=None) -> None:
    """미리 계산한 boost(구도태그+자연어)를 generate 결과 프롬프트에 concat.
    settings는 kickoff 시 freeze된 것을 받는다(없으면 현재값 — Codex Must-fix 3)."""
    try:
        if not isinstance(boost, dict) or not boost.get("ok"):
            return
        add = boost.get("additions") or {}
        # 구도태그(무가중) + 자연어([기능1] nl_weight 래핑)로 조립 — freeze된 설정 사용.
        from app.backend.server.generation_commands import _compose_addition, _inject_boost_at_main
        if settings is None:
            from app.backend.server.ollama_routes import ollama_boost_settings

            settings = ollama_boost_settings(context)
        text = _compose_addition(add, settings, context)
        if not text:
            return
        prompt = str(getattr(result, "prompt", "") or "")
        # 메인 섹션 끝(e621 위치)에 삽입 — 끝(postfix 뒤)이 아니라 장면 태그 바로 뒤.
        new_prompt = _inject_boost_at_main(prompt, text) if prompt.strip() else text
        result.prompt = new_prompt
        context.prompt_text = new_prompt
        ctx = getattr(result, "context", None)
        if ctx is not None:
            ctx.final_prompt = new_prompt
            if isinstance(getattr(ctx, "metadata", None), dict):
                ctx.metadata["ollama_auto_boost"] = {
                    "rating": boost.get("rating"), "level": boost.get("level"),
                    "additions": add, "prefetched": True, "settings": settings,
                }
    except Exception:
        pass


async def _consume_auto_gen_prefetch(context: WebSessionContext, overrides, request_id):
    """홀더가 유효하면 예약 행을 generate(override)로 소비 + boost concat. 아니면 None(폴백)."""
    holder = getattr(context, "_auto_gen_prefetch", None)
    if not holder:
        return None
    context._auto_gen_prefetch = None  # 원샷 소비
    source_row = holder.get("source_row")
    task = holder.get("task")
    try:
        ratings = context.get_active_ratings()
        if holder.get("state_key") != _auto_gen_prefetch_state_key(context, ratings):
            if task is not None and not task.done():
                task.cancel()
            return None  # stale(재검색/등급/모드/토글 변경) → 다른 행 필요 → 동기 폴백
        # 예약 행으로 full generate(override → pop 없음, random_prompt_triggered 등 정상).
        # boost와 무관하게 항상 이 예약 행을 쓴다(동기 재생성 폴백으로 빠지지 않음).
        result = await asyncio.to_thread(
            random_service(context).generate,
            active_ratings=ratings,
            overrides=overrides,
            random_request_id=request_id,
            source_row_override=source_row,
        )
        if getattr(result, "success", False):
            # boost는 이미지 생성과 겹쳐 대부분 이미 완료. 아직이면 짧게만 기다리고, 그래도
            # 안 되면 이번 컷은 boost 생략한다 — **2차 Ollama 호출은 절대 하지 않는다**(중복/지연 방지).
            try:
                boost = await asyncio.wait_for(asyncio.shield(task), timeout=_PREFETCH_BOOST_GRACE)
                _apply_prefetched_boost(context, result, boost, holder.get("settings"))
            except Exception:
                if task is not None and not task.done():
                    task.cancel()
        return result
    except Exception:
        return None


def _make_nai_preview_callback(clients: set[WebSocket], loop: asyncio.AbstractEventLoop):
    """워커 스레드(asyncio.to_thread)에서 호출되는 NAI 스트리밍 프리뷰 콜백을 만든다.

    콜백은 동기 함수지만 WebSocket 브로드캐스트는 코루틴이므로,
    ``run_coroutine_threadsafe``로 메인 이벤트 루프에 넘긴다(스레드 안전).
    프레임은 fire-and-forget으로 전송한다(워커 블로킹 방지).
    """
    def _cb(image_bytes: bytes, step, total) -> None:
        try:
            info = {"step": int(step), "total": int(total)}
        except Exception:
            info = {}
        try:
            asyncio.run_coroutine_threadsafe(
                broadcast_preview_image(clients, image_bytes, info), loop
            )
        except Exception:
            pass
    return _cb


async def run_generation_queue(context: WebSessionContext, clients: set[WebSocket]) -> None:
    if getattr(context, "headless_generation_runner_active", False):
        return
    context.headless_generation_runner_active = True
    try:
        loop = asyncio.get_running_loop()
        while True:
            request = await asyncio.to_thread(context.generation_queue_manager.dequeue_request)
            if request is None:
                break
            request_params = getattr(request, "params", {}) or {}
            img2img_service = _img2img_lifecycle_service(context)
            # 확장 cancel_generation의 dequeue 경합 보강(Codex R1-#2): enqueue 직후
            # 러너가 큐 제거보다 먼저 집어간 요청은 톰스톤으로 실행 직전에 건너뛴다.
            consume_cancel = getattr(context.generation_queue_manager, "consume_cancellation", None)
            if callable(consume_cancel) and consume_cancel(request.request_id):
                print(f"[QUEUE] 취소 예약 소비 — 실행 건너뜀: {request.request_id[:8]}...", flush=True)
                img2img_cancelled = bool(
                    img2img_service
                    and img2img_service.record_generation_failed(
                        request_params,
                        request.request_id,
                        "Generation cancelled",
                    )
                )
                await broadcast_json(clients, context.queue_state_payload())
                if img2img_cancelled:
                    await _broadcast_img2img_generation_state(context, clients)
                continue
            img2img_started = bool(
                img2img_service
                and img2img_service.record_generation_started(request_params, request.request_id)
            )
            context.is_generating = True
            await broadcast_json(clients, {"type": "status", "is_generating": True, "message": "generating"})
            await broadcast_json(clients, context.queue_state_payload())
            if img2img_started:
                await _broadcast_img2img_generation_state(context, clients)
            # Ollama Auto Boost 오버랩 생산자 — 다음 랜덤 행 예약 + boost를 백그라운드 선행해
            # 현재 이미지 생성(아래 execute_request 대기)과 겹친다. 자격 미달이면 no-op.
            _kickoff_auto_gen_prefetch(context, request)
            # Sequence Use Vibe: 라운드 첫 이미지가 인코딩돼 있으면 이후 프레임 실행 직전에
            # 임시 vibe 를 주입한다(enqueue 시점엔 인코딩이 없어 실행 시점 주입). 캡처 프레임/
            # 비활성 런/비NAI/모델 불일치는 no-op.
            _inject_sequence_vibe(context, request)
            # 🎬 NAI 스트리밍 미리보기: 옵션이 켜져 있고 NAI 모드일 때만 프리뷰 콜백 연결
            preview_callback = None
            try:
                streaming_on = bool(context.remote_options.get("nai_streaming_preview", False))
            except Exception:
                streaming_on = False
            if streaming_on and (getattr(request, "params", {}) or {}).get("api_mode") == "NAI":
                preview_callback = _make_nai_preview_callback(clients, loop)
            try:
                stored = await asyncio.to_thread(
                    generation_service(context).execute_request, request,
                    preview_callback,
                )
            except Exception as exc:
                _release_auto_gen_prefetch(context)  # 생성 실패 → 이번 예약 홀더 폐기(stale 방지)
                await _broadcast_generation_error(context, clients, request, str(exc), exc)
                # 실패한 시퀀스 프레임도 라운드 카운트를 진전시켜야 연속 루프가 멈추지 않는다(Codex).
                # ⚠️ 사용량 판정을 **여기서도** 낸다. 아래 성공 완료 경로만 이 답을 세워 두는데,
                #    라운드 마지막 프레임이 넘어지면 완료 알림을 안 거치고 곳장 아래
                #    `_advance_sequence_run` 으로 떨어진다 - 답이 없으면 가드가 통째로 빠지고
                #    다음 묶음이 **그룹 전체** 유료로 들어간다.
                context._auto_gen_quota_stop = (
                    _auto_gen_loop_engaged(context, request)
                    and _auto_gen_quota_exhausted(context)
                )
                # I.Sequence 캔버스 연쇄: 실패하면 이어 붙일 씨앗이 없다. 남은 대기분을
                # 버려 라운드를 지금 닫는다 - 안 그러면 다음 컷이 영영 안 들어가고
                # `completed < total` 이라 런이 살아 있는 채로 멈춘다.
                try:
                    _isq_run = str((getattr(request, "params", {}) or {}).get(
                        "inpaint_sequence_run_id") or "")
                    if _isq_run:
                        _dropped = context._inpaint_sequence_run_service().abandon_pending(_isq_run)
                        if _dropped:
                            print(f"[i.sequence] frame failed - dropped {_dropped} pending cut(s)",
                                  flush=True)
                except Exception:
                    pass
                try:
                    await _advance_sequence_run(context, clients, request)
                except Exception:
                    pass
                continue
            # ── V4.5 프리뷰 ─────────────────────────────────────────
            # 사용자 지정: "저장이 되지 않는 이미지". 디스크에도 안 쓰고 히스토리에도
            # 안 남긴다 - 여기서 갈라져 나가므로 아래 auto_save / broadcast_image /
            # viewer_new_image_payload 를 **하나도** 타지 않는다.
            # ⚠️ 캐릭터 '즉시 생성' 은 **여기로 오지 않는다**(사용자 제보 2026-09-02:
            #    "사용자는 Results에 결과가 남는 것을 원할 것 입니다"). 평소 길로 흘러
            #    디스크·히스토리·Result 탭을 모두 탄다 - 그래야 메타데이터로 PE 설정이
            #    실제로 실렸는지도 확인할 수 있다.
            _params = getattr(request, "params", {}) or {}
            if _params.get("nai_preview_request"):
                context.is_generating = False
                await _finish_nai_preview(context, clients, request, stored)
                continue

            img2img_completed = bool(
                img2img_service
                and img2img_service.record_generation_completed(request_params, request.request_id)
            )
            auto_save_result = await _auto_save_generated_history_item(context, stored.item)

            context.is_generating = False
            # ⚠️ 완료 알림은 **모든 클라이언트에게** 간다. 지금까지 알맹이가 없어서, 탭 두
            #    개가 각자 V5 연속 생성을 돌리면 서로의 완료를 자기 것으로 세고 각자 다음
            #    컷을 냈다 - 시키지 않은 그림에 돈이 나간다(Codex 리뷰 BLOCK).
            #    요청에 실려 온 런 표를 그대로 되돌려 주면 각 탭이 **자기 것만** 센다.
            #    타입은 그대로라 웹 스모크 계약(타입을 순서대로 셈)에도 안 걸린다.
            # ⚠️ 사용량 판정은 **완료 알림보다 먼저** 내린다. 프런트가 도는 루프
            #    (V5 Scene 연속 생성)는 바로 이 알림을 보고 다음 컷을 내므로, 나중에
            #    따로 알리면 이미 한 장이 더 나간 뒤다(Codex BLOCK 2026-08-25).
            #    `_maybe_continue_auto_generation` 은 여기서 낸 답을 그대로 쓴다.
            context._auto_gen_quota_stop = (
                _auto_gen_loop_engaged(context, request)
                and _auto_gen_quota_exhausted(context)
            )
            await broadcast_json(clients, {
                "type": "status",
                "is_generating": False,
                "message": "completed",
                "v5_scene_run": str((request_params or {}).get("v5_scene_run") or ""),
                "quota_exhausted": bool(context._auto_gen_quota_stop),
            })
            # ComfyUI 서버가 생성 이미지에 메타데이터를 남기지 않아(예: --disable-metadata)
            # NAIA가 자체 메타데이터를 삽입한 경우, 세션당 한 번만 경고 토스트로 알린다.
            if getattr(stored, "comfyui_metadata_injected", False) and not getattr(
                context, "comfyui_metadata_warning_emitted", False
            ):
                context.comfyui_metadata_warning_emitted = True
                await broadcast_json(clients, {
                    "type": "toast",
                    "level": "warning",
                    "message": (
                        "ComfyUI가 생성 이미지에 메타데이터를 남기지 않았습니다"
                        "(예: --disable-metadata). NAIA가 자체 메타데이터를 삽입해 저장합니다."
                    ),
                })
            params = getattr(request, "params", {}) or {}
            if params.get("prompt_preset_thumbnail_request"):
                await _broadcast_prompt_preset_thumbnail_update(context, clients, stored, params)
            if params.get("character_viewer_request"):
                await _save_character_viewer_thumbnail(context, stored, params)
            if params.get("character_instant_request"):
                # ⚠️ **결과를 빼돌리지 않는다.** 위에서 이미 저장·히스토리·Result 를
                #    다 탔다. 여기서는 프리뷰 창에 **한 번 더** 띄울 뿐이다 -
                #    사용자 제보 2026-09-02: "캐릭터 모듈은 Result 윈도우를 덮으므로,
                #    프리뷰가 보여야 합니다."
                await _broadcast_character_instant_preview(clients, stored, params)
            if params.get("artist_thumb_request"):
                await _save_artist_thumbnail(context, stored, params)
            if params.get("character_asset_request"):
                # 벤치 후보는 화면에 떠 있는 동안 저장 가능해야 한다 - 결과 저장소가
                # 상한을 넘겨 퇴출해도 캐릭터 에셋 서비스가 bounded FIFO로 붙잡는다.
                try:
                    context._character_asset_service().retain_candidate(stored.item)
                except Exception as exc:
                    print(f"[CharacterAsset] candidate retain failed: {exc}")
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
            # ComfyUI 자동 EPS↔ANIMA 스왑이 3회차에 성공했으면 모드를 확정한다 —
            # 프런트 UI 플래그 + 백엔드 remote_params(Auto Gen 연속 SSOT) 갱신 + 노란 경고.
            await _commit_comfyui_mode_swap(context, clients, getattr(stored, "comfyui_mode_swap", None))
            # NAI 생성은 Anlas를 소비한다 — 완료 직후 잔량을 재조회해 pill에 즉시 반영한다
            # (future01 패리티; 5분 폴링/재연결을 기다리지 않음). NAI 모드 한정 — 다른 백엔드는
            # Anlas와 무관해 불필요한 브로드캐스트만 낸다. build_anlas_payload가 NAI+토큰일 때만
            # 실측 조회하고, 프런트는 값이 감소했을 때만 pill을 점멸시킨다(소비 시각 피드백).
            if str(context.get_api_mode() or "").upper() == "NAI":
                # 이번 세션에 **무료로** 나간 장수. 배지가 퍼센트 대신 이 값을 쓴다 -
                # 퍼센트는 정수라 1% 가 약 17장이어서 한 장 뽑아도 안 움직인다.
                try:
                    from core.nai_free_usage import note_generation

                    note_generation(context, params)
                except Exception as exc:  # noqa: BLE001 - 집계 실패가 생성을 막으면 안 된다
                    print(f"[warn] free-usage count failed: {exc}", flush=True)
                if usage_badge_active(context):
                    # V5 는 Anlas 가 아니라 **별도 사용량 풀**을 쓴다. 생성해도 배지가
                    # 안 줄어든다는 지적(2026-08-21) — 사용량 조회를 세션 시작·모델
                    # 변경에만 걸어 두고 생성 경로에는 안 걸어 뒀다.
                    # 캐시를 버리고(force) 한 요청으로 Anlas·사용량을 함께 갱신한다.
                    # **기다리지 않는다** - 생성 완료 처리를 조회가 붙잡으면 안 된다.
                    schedule_subscription_refresh(context, clients, force=True)
                else:
                    # V5 가 아니면 예전 그대로 Anlas 만. 메시지 수가 바뀌지 않아야
                    # 릴리즈 웹 스모크의 생성 커맨드 계약이 어긋나지 않는다.
                    try:
                        await broadcast_anlas(context, clients)
                    except Exception:
                        pass
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
            # Sequence Use Vibe: 라운드 첫 이미지(캡처 stamp)가 완료되면 그 결과를 인코딩(2 Anlas)
            # 해 이후 프레임에 적용할 임시 vibe 로 보관한다. 다음 프레임 dequeue 전(같은 루프 반복
            # 안에서 await)이라 두 번째 컷부터 곧바로 주입된다. 비NAI/이미 인코딩됨/실패는 no-op.
            await _capture_sequence_vibe(context, clients, request, stored)
            # I.Sequence 캔버스 연쇄 — 다음 컷을 지금 넣는다. `_advance_sequence_run`
            # 보다 **먼저**여야 한다: 그쪽은 큐가 비어 있어야 다음 그룹으로 넘어가므로,
            # 뒤에 두면 라운드가 안 끝났는데 새 그룹이 시작될 수 있다.
            await _chain_inpaint_sequence_frame(context, clients, request, stored)
            # Guard the auto-continue (prompt gen / PE persist / enqueue) so a raised
            # exception after a story page was counted still cleans up the cycle
            # (_broadcast_generation_error fails the stamped story) instead of leaving the
            # freeze + Auto Gen armed.
            try:
                await _maybe_continue_auto_generation(context, clients, request)
            except Exception as exc:
                await _broadcast_generation_error(context, clients, request, str(exc), exc)
            await broadcast_json(clients, context.queue_state_payload())
            await broadcast_json(clients, context.auto_save_state_payload())
            if isinstance(auto_save_result, dict) and auto_save_result.get("error"):
                await broadcast_json(clients, {
                    "type": "toast",
                    "level": "error",
                    "message": f"Auto Save failed: {auto_save_result['error']}",
                })
            if img2img_completed:
                await _broadcast_img2img_generation_state(context, clients)
    finally:
        context.is_generating = False
        context.headless_generation_runner_active = False
        # 큐 루프 종료(정상/중단/예외) — 남은 예약 홀더는 폐기(detached task 누수·stale 방지).
        _release_auto_gen_prefetch(context)


# Sequence 와 I.Sequence 는 **같은 기계**를 쓴다 - 프레임에 박힌 키 이름만 다르다.
# 둘을 따로 짜면 이 파일의 돈 가드(사용량 0% 차단)가 둘로 갈라 한쪽만 고치는 날이
# 온다 - 그래서 본체는 하나로 두고 여기서 종류만 갈라낸다(2026-08-25).
#   (run_id 키, Vibe 캡처 stamp 키, 런 서비스 접근자, 모듈 상태 접근자, 연속 라우트 모듈)
_SEQUENCE_KINDS = (
    ("sequence_run_id", "sequence_vibe_capture", "_sequence_run_service",
     "_sequence_run_module_state", "app.backend.server.sequence_preset_routes"),
    ("inpaint_sequence_run_id", "inpaint_sequence_vibe_capture", "_inpaint_sequence_run_service",
     "_inpaint_sequence_run_module_state", "app.backend.server.inpaint_sequence_routes"),
)


def _sequence_kind_for(request):
    """이 요청이 어느 시퀀스의 프레임인가. 시퀀스 프레임이 아니면 None."""
    params = getattr(request, "params", None)
    if not isinstance(params, dict):
        return None
    for kind in _SEQUENCE_KINDS:
        if str(params.get(kind[0]) or ""):
            return kind
    return None


def _inject_sequence_vibe(context: WebSessionContext, request) -> None:
    """Sequence Use Vibe: 실행 직전, 라운드 첫 이미지의 인코딩이 준비돼 있으면 이 프레임의 NAI vibe
    EarlyBinding(``request.nai_vibe_transfer`` — api_service 가 실제로 보내는 출처)에 임시 vibe 1장을
    append 한다. 사용자 Vibe Transfer 가 있으면 그 뒤에 붙어 공존하되, 기존 vibe 들의 RS 는 절반
    (퍼센트 floor)으로 줄여 첫 이미지 vibe 가 상대적으로 더 지배하게 한다. 사용자 vibe 가 없으면
    임시 vibe 단독으로 바인딩된다. 중요: ``request.params`` 는 건드리지 않는다 — 저장 메타/리플레이는
    params 기준이라 임시 vibe 가 자동으로 비영속(휘발)이다(마커/strip 불필요). 캡처 프레임 자신·
    비활성 런·비NAI·모델 불일치·중복·NAID3·최대 vibe 초과는 no-op. enqueue 시점엔 인코딩이 없으므로
    주입은 반드시 여기서 한다."""
    params = getattr(request, "params", None)
    if not isinstance(params, dict):
        return
    kind = _sequence_kind_for(request)
    if kind is None:
        return
    run_key, capture_key, accessor = kind[0], kind[1], kind[2]
    run_id = str(params.get(run_key) or "")
    if not run_id or params.get(capture_key):
        return  # 시퀀스 프레임 아님 / 캡처 프레임 자신은 vibe 소스라 주입 대상 아님
    svc = getattr(context, accessor)()
    if not svc.is_running(run_id):
        return
    # 게이트는 프레임에 baking 된 값으로 본다(라이브 컨텍스트가 아니라) — 생성 도중 사용자가
    # 모드/모델을 바꿔도 이 NAI 프레임은 baking 된 모드/모델로 처리된다(Codex: 컨텍스트 드리프트).
    if str(params.get("api_mode") or "").upper() != "NAI":
        return  # 생성 단계 silent 차단
    injection = svc.vibe_injection(run_id)
    if not injection:
        return  # 아직 첫 이미지 인코딩 전(또는 인코딩 실패) — vibe 없이 진행
    encoding = str(injection.get("encoding") or "")
    if not encoding:
        return
    # 인코딩은 모델 종속 — 캡처 모델과 이 프레임의 baking 모델이 다르면 주입하지 않는다(NAI 오류
    # 방지). 한 라운드의 전 프레임은 동일 모델로 enqueue 되므로 정상 경로에선 항상 일치한다.
    vibe_model = str(injection.get("model") or "")
    if vibe_model and vibe_model != str(params.get("model") or ""):
        return
    from core.generation_request import NAIVibeTransferData

    existing = getattr(request, "nai_vibe_transfer", None)
    if existing is not None:
        # NAID3 (IE 리스트 존재)는 인코딩 vibe 와 혼용 불가 — 주입 skip(애초 NAID3 encode 실패라
        # 도달 불가, 방어적).
        if getattr(existing, "reference_information_extracted_multiple", None):
            return
        refs = list(existing.reference_image_multiple or [])
        strengths = list(existing.reference_strength_multiple or [])
        normalize = bool(existing.normalize)
    else:
        refs, strengths = [], []
        normalize = bool(getattr(context, "vibe_transfer_normalize", False))
    if encoding in refs:
        return  # 이미 실려 있음(이중 방어)
    # 기존 refs 길이에 맞춰 strengths 정렬 후, 임시 vibe 와 공존하는 기존(EarlyBinding) vibe 들의
    # RS 를 절반(퍼센트 floor)으로 줄인다 — 첫 이미지 vibe 가 상대적으로 더 지배하도록(사용자 요청).
    # 임시 vibe 자신은 시퀀스 전용 RS(SEQUENCE_VIBE_STRENGTH) 유지.
    strengths = (strengths + [0.6] * len(refs))[:len(refs)]
    strengths = [halve_floor_strength(s) for s in strengths]
    refs.append(encoding)
    strengths.append(SEQUENCE_VIBE_STRENGTH)
    try:
        from core.nai_vibe_limits import MAX_NAI_VIBE_REFERENCES

        if len(refs) > MAX_NAI_VIBE_REFERENCES:
            return  # NAI 최대 vibe 수 초과 → 주입 skip(400 방지)
    except Exception:
        pass
    try:
        request.nai_vibe_transfer = NAIVibeTransferData(
            reference_image_multiple=refs,
            reference_strength_multiple=strengths,
            normalize=normalize,
        )
    except Exception:
        pass  # 검증(길이/범위) 실패 시 vibe 없이 진행(시퀀스를 막지 않음)


async def _chain_inpaint_sequence_frame(
    context: WebSessionContext,
    clients: set[WebSocket],
    request,
    stored,
) -> bool:
    """I.Sequence 캔버스 연쇄: 방금 나온 컷을 캔버스에 붙여 다음 컷을 큐에 넣는다.

    직전 컷의 **결과 이미지**가 있어야 다음 캔버스를 만들 수 있어서, 라운드의 전
    프레임을 한 번에 넣는 t2i 방식으로는 성립하지 않는다. 라우트는 첫 컷만 넣고
    나머지를 런 상태에 재워 두며, 여기서 완료마다 한 장씩 꺼내 이어 붙인다.

    ⚠️ 이어 붙일 씨앗은 **잘라낸 절반**이다. 2컷부터는 결과가 캔버스(두 칸)이므로
       통째로 다시 붙이면 칸이 반씩 줄며 그림이 뭉갠다.
    ⚠️ 실패해도 조용히 접는다(False). 라운드 카운트는 `_advance_sequence_run` 이
       따로 세므로, 여기서 예외를 올리면 그 진행까지 멈춰 런이 영영 안 끝난다.
    """
    params = getattr(request, "params", None)
    if not isinstance(params, dict):
        return False
    run_id = str(params.get("inpaint_sequence_run_id") or "")
    if not run_id:
        return False
    svc = context._inpaint_sequence_run_service()
    if not svc.is_running(run_id):
        return False

    # ⚠️ **할당량 판정을 여기서 본다.** 이 함수는 `_maybe_continue_auto_generation`
    #    보다 **먼저** 돌기 때문에(라운드가 넘어가기 전에 이어 붙여야 해서), 그쪽이
    #    정지를 처리하기 전에 유료 한 장이 이미 큐에 들어간다. 판정은 완료 알림
    #    직전에 세워 둔 답을 **읽기만** 한다 - 지우는 것은 그쪽 몫이다(Codex #1).
    if getattr(context, "_auto_gen_quota_stop", False):
        svc.abandon_pending(run_id)
        print("[i.sequence] chain stopped: free quota exhausted", flush=True)
        return False

    nxt = svc.pop_next_frame(run_id)
    if not nxt:
        return False   # 이 라운드의 마지막 컷이었다

    def _give_up(reason: str) -> bool:
        """⚠️ 프레임은 이미 **꺼내져 지워졌다.** 여기서 그냥 돌아가면 다음 컷이 영영
        큐에 안 들어가고 `completed < total_frames` 라 라운드가 안 닫혀, 런이 살아
        있는 채로 멈춰 다음 시작까지 막는다(Codex #3). 남은 대기분을 버려 닫는다."""
        dropped = svc.abandon_pending(run_id)
        print(f"[i.sequence] chain stopped: {reason} (dropped {dropped} pending cut(s))",
              flush=True)
        return False

    image = getattr(getattr(stored, "item", None), "image", None)
    if image is None:
        return _give_up("no result image")

    from utils.sequence_canvas_chain import inpaint_payload

    direction = svc.direction(run_id)
    try:
        # ⚠️ **여기서 자르지 않는다.** 저장 직전(`HeadlessGenerationService.execute_request`
        #    -> `_isq_crop_result`)에서 이미 새 절반만 남겨 뒀다 - 여기서 또 자르면
        #    씨앗이 1/4 이 되어 다음 컷이 통째로 어긋난다. 자르는 자리는 하나여야 한다.
        #    (1컷 t2i 는 애초에 안 잘리므로 그대로 씨앗이 된다.)
        payload = await asyncio.to_thread(inpaint_payload, image, direction)
    except Exception as exc:   # noqa: BLE001
        return _give_up(f"canvas build failed: {exc}")

    command = nxt.get("command") or {}
    overrides = dict(command.get("overrides") or {})
    overrides.update(payload)
    command = {**command, "overrides": overrides}
    try:
        dispatch = await asyncio.to_thread(
            generation_service(context).enqueue_remote_request, command
        )
    except Exception as exc:   # noqa: BLE001
        return _give_up(f"enqueue failed: {exc}")
    if not getattr(dispatch, "ok", False):
        return _give_up("enqueue blocked")
    try:
        await broadcast_json(clients, context._inpaint_sequence_run_module_state())
    except Exception:
        pass
    return True


async def _capture_sequence_vibe(context: WebSessionContext, clients: set[WebSocket], request, stored) -> None:
    """Sequence Use Vibe: 캡처 stamp 가 달린 라운드 첫 이미지의 생성 결과를 인코딩(2 Anlas)해
    이후 프레임용 임시 vibe 로 보관한다. 라운드당 1회만(이미 인코딩됐으면 skip). 비NAI/소스 없음/
    인코딩 실패는 경고 토스트 후 vibe 없이 계속(사용자 확정 — 실패가 시퀀스를 막지 않는다)."""
    params = getattr(request, "params", None)
    if not isinstance(params, dict):
        return
    kind = _sequence_kind_for(request)
    if kind is None:
        return
    run_key, capture_key, accessor = kind[0], kind[1], kind[2]
    run_id = str(params.get(run_key) or "")
    if not run_id or str(params.get(capture_key) or "") != run_id:
        return
    svc = getattr(context, accessor)()
    if not svc.is_running(run_id) or not svc.wants_vibe(run_id):
        return
    if svc.vibe_injection(run_id):
        return  # 이 라운드는 이미 인코딩됨
    # 게이트/모델은 프레임에 baking 된 값을 쓴다(라이브 컨텍스트 아님) — 생성 도중 사용자가 모드/
    # 모델을 바꿔도 이 NAI 프레임은 baking 된 모드로 인코딩하고, 그 모델을 보관한다. 그래야 이후
    # 프레임(동일 baking 모델)에 정확히 주입되고 엉뚱한 모델로 2 Anlas 를 쓰지 않는다(Codex).
    if str(params.get("api_mode") or "").upper() != "NAI":
        return  # 생성 단계 silent 차단
    model = str(params.get("model") or "")
    raw = getattr(getattr(stored, "item", None), "raw_bytes", b"") or b""
    if not raw:
        await broadcast_json(clients, {
            "type": "toast", "level": "warning",
            "message": "Vibe 사용: 인코딩할 첫 이미지를 찾지 못해 vibe 없이 계속합니다.",
        })
        return
    try:
        from core.headless_vibe_transfer_service import encode_vibe_bytes

        encoding = await asyncio.to_thread(
            encode_vibe_bytes, context, raw, SEQUENCE_VIBE_IE, model_key=(model or None)
        )
    except Exception as exc:
        await broadcast_json(clients, {
            "type": "toast", "level": "warning",
            "message": f"Vibe 사용 인코딩 실패 — vibe 없이 계속합니다: {exc}",
        })
        return
    svc.set_vibe_encoding(run_id, encoding, model)
    await broadcast_json(clients, {
        "type": "toast", "level": "success",
        "message": (f"Vibe 사용: 첫 이미지 인코딩 완료 — IE {SEQUENCE_VIBE_IE:.1f}, "
                    f"RS {SEQUENCE_VIBE_STRENGTH:.1f} (2 Anlas). 이후 컷에 적용됩니다."),
    })
    # 인코딩(2 Anlas) 차감을 pill 에 즉시 반영(5분 폴링 대기 없이).
    try:
        await broadcast_anlas(context, clients)
    except Exception:
        pass


async def _advance_sequence_run(context: WebSessionContext, clients: set[WebSocket], request) -> bool:
    """Sequence 프레임 완료(성공·실패 공통) 처리. 시퀀스 프레임이면 라운드 카운트를 진전시키고,
    라운드 완료 시 Auto Gen ON·큐 빔이면 다음 랜덤 그룹으로 연속(continue_sequence_run), 아니면
    종료한다. 시퀀스 프레임이 아니면 False(미처리). 성공 완료(_maybe_continue)와 실행 실패(except)
    양쪽에서 호출돼 실패 프레임도 카운트되므로 루프가 영구 정지하지 않는다(Codex MUST-FIX)."""
    kind = _sequence_kind_for(request)
    if kind is None:
        return False
    run_key, _capture_key, accessor, state_accessor, routes_module = kind
    params = getattr(request, "params", {}) or {}
    sequence_run_id = str(params.get(run_key) or "")
    seq_service = getattr(context, accessor)()
    if not sequence_run_id or not seq_service.is_running(sequence_run_id):
        return False
    module_state = getattr(context, state_accessor)
    policy = seq_service.record_generation_completed(sequence_run_id)
    try:
        await broadcast_json(clients, module_state())
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
        # ⚠️ 다음 라운드는 '한 장' 이 아니라 **그룹 전체**다. 성공 완료는 위쪽
        #    `_maybe_continue_auto_generation` 이 먼저 걸러 여기까지 오지 않지만,
        #    실행 실패(except)는 그 문을 안 지나고 곳장 이리로 온다 - 그 경로가 세워 둔
        #    답을 여기서 받아 끊는다. 안 끊으면 마지막 프레임 하나가 넘어졌을 뿐인데
        #    새 묶음이 유료로 나간다(2026-08-25).
        if getattr(context, "_auto_gen_quota_stop", False):
            context._auto_gen_quota_stop = False
            await _stop_auto_generation_for_quota(context, clients)
            # 그쪽이 이 런을 stopped 로 끝내고 알린다 - 아래에서 또 '완료' 로 끝내지 않는다.
            return True
        import importlib

        continue_run = importlib.import_module(routes_module).continue_sequence_run
        advanced = await continue_run(context, clients, sequence_run_id, broadcast_json)
    if not advanced:
        finish = seq_service.finish(sequence_run_id, reason="complete")
        try:
            await broadcast_json(clients, module_state())
        except Exception:
            pass
        for message in finish.get("messages", []):
            await broadcast_json(clients, message)
    return True


def _auto_gen_loop_engaged(context: WebSessionContext, request=None) -> bool:
    """지금 무언가가 **스스로 다음 장을 부르고 있는가.**

    아니면 멈출 것이 없다 - 수동 생성 한 장에 "자동 생성을 해제했습니다" 토스트를
    띄우면 하지도 않은 일을 했다고 말하는 셈이다.

    ⚠️ 루프의 주인이 **서버만은 아니다.** V5 Scene 연속 생성은 프런트가 돌리며 공용
       `auto_generate` 를 켜지 않는다 - 그것만 보면 "아무도 안 돈다" 로 읽혀 가드가
       통째로 안 걸렸다(Codex BLOCK 2026-08-25). 요청에 실려 온 런 표로 알아본다.
    ⚠️ 시퀀스도 마찬가지로 자기 런을 돈다.
    """
    try:
        params = getattr(request, "params", {}) or {}
        if isinstance(params, dict) and str(params.get("v5_scene_run") or ""):
            return True
        if context._coerce_bool(context.get_options().get("auto_generate", False)):
            return True
        return bool(context._storyteller_service().is_running()
                    or context._automation_service().is_running()
                    or context._sequence_run_service().is_running()
                    or context._inpaint_sequence_run_service().is_running())
    except Exception:   # noqa: BLE001
        return False


def _auto_gen_quota_exhausted(context: WebSessionContext) -> bool:
    """'사용량 0% 도달 시 자동 생성 해제' 가 켜져 있고, 실제로 닿았는가.

    ⚠️ 기준은 **이번 생성이 쓸 계정들**이다. 계정을 하나 지목했으면 그 계정 하나가
       기준이 된다(`generation_quota_exhausted` 주석 참조).

    스위치와 판정을 **여기서 함께** 본다 - 스위치가 꺼져 있으면 계정 파일도 사용량도
    읽을 이유가 없다.
    """
    try:
        from core.nai_account_service import (
            STOP_ON_EXHAUSTED_KEY,
            NaiAccountService,
            generation_quota_exhausted,
        )

        if not bool(NaiAccountService(context).load().get(STOP_ON_EXHAUSTED_KEY, False)):
            return False
        return generation_quota_exhausted(context)
    except Exception:   # noqa: BLE001 - 안전장치 하나 때문에 루프가 죽으면 안 된다
        return False


# 루프가 소유한 요청임을 알려 주는 표식. 사용자가 손수 넣은 배치에는 하나도 없다.
_LOOP_RUN_KEYS = ("sequence_run_id", "inpaint_sequence_run_id",
                  "event_stream_run_id", "automation_run_id")


def _drop_queued_loop_frames(context: WebSessionContext) -> int:
    """루프가 소유한 **대기 중** 프레임을 큐에서 걷어낸다.

    ⚠️ 런을 `finish` 로 닫는 것만으로는 **이미 큐에 든 프레임이 안 멈춘다.** 그대로
       나가서 돈을 태운다 - 인페인트로 화면이 넘어간 뒤에도 시퀀스 컷이 계속
       생성됐다(Codex HIGH 2026-08-28). 런을 닫는 자리와 큐를 비우는 자리가
       달라서 생긴 구멍이라, **멈추는 함수 안에서 함께** 처리한다.
    ⚠️ 사용자가 손수 걸어 둔 배치는 이 표식이 없다 - 건드리지 않는다. 큐를 통째로
       지우면 "스무 장 걸어 두고 인페인트로 한 장 보러 갔다" 가 파괴된다.
    ⚠️ 러너가 이미 집어간 한 장은 큐에 없어 못 뺀다 - 실행 직전 건너뛰기를 예약해
       둔다(러너가 `consume_cancellation` 으로 소비한다).
    """
    manager = getattr(context, "generation_queue_manager", None)
    if manager is None:
        return 0
    try:
        pending = manager.get_all_requests()
    except Exception:
        return 0
    dropped = 0
    for request in pending:
        params = getattr(request, "params", None)
        if not isinstance(params, dict):
            continue
        if not any(str(params.get(key) or "") for key in _LOOP_RUN_KEYS):
            continue
        request_id = str(getattr(request, "request_id", "") or "")
        if not request_id:
            continue
        try:
            if manager.remove_request(request_id):
                dropped += 1
            else:
                manager.mark_cancelled(request_id)
        except Exception:
            continue
    return dropped


async def stop_all_generation_loops(
    context: WebSessionContext,
    clients: set[WebSocket],
) -> list[dict[str, Any]]:
    """도는 것을 **전부** 멈추고, 화면에 보낼 메시지를 돌려준다(토스트는 부르는 쪽이).

    Storyteller/Automation/Sequence 가 돌고 있으면 그쪽 `finish` 로 끝낸다 - 그것들이
    Auto Gen 스위치의 주인이라, 옵션만 끄면 런타임이 무장한 채 남아 다음 수동 생성이
    다시 루프를 탄다. 아무도 안 돌고 있으면 옵션을 직접 내린다.

    ⚠️ 부르는 자리가 둘이다: 무료 사용량 0%(아래)와 **인페인트 진입**(세션이 화면을
       잡는 동안 일반 생성이 계속 나가면 안 된다 - 사용자 지정 2026-08-27).
       각자 따로 짜면 한쪽이 시퀀스나 프리페치를 빠뜨린다.
    """
    _release_auto_gen_prefetch(context)
    story = context._storyteller_service()
    automation = context._automation_service()
    messages: list[dict[str, Any]] = []
    # ⚠️ 시퀀스는 **따로** 끝낸다(elif 가 아니다). 자기 런을 돌기 때문에 아래 컨트롤러
    #    들과 동시에 살아 있을 수 있고, 안 끝내면 런타임이 무장한 채 남아 다음 완료가
    #    다시 다음 묶음을 넣는다(Codex BLOCK 2026-08-25).
    for _run_key, _capture_key, _accessor, _state_accessor, _routes in _SEQUENCE_KINDS:
        sequence = getattr(context, _accessor)()
        if not sequence.is_running():
            continue
        finish = sequence.finish(sequence.active_run_id(), reason="stopped")
        try:
            await broadcast_json(clients, getattr(context, _state_accessor)())
        except Exception:
            pass
        messages.extend(finish.get("messages", []))
    if story.is_running():
        messages.extend(story.finish(story.active_run_id(), reason="stopped").get("messages", []))
        await _broadcast_storyteller_state(context, clients)
    elif automation.is_running():
        messages.extend(automation.finish(automation.active_run_id(), reason="stopped").get("messages", []))
        await _broadcast_automation_state(context, clients)
    elif context._coerce_bool(context.get_options().get("auto_generate", False)):
        context.set_option("auto_generate", False)
        messages.append({"type": "options", **context.get_options()})
    # ⚠️ **여기가 마지막 목이다.** 위에서 런을 다 닫아도 이미 큐에 든 프레임은 그대로
    #    나간다 - 멈췄다고 말해 놓고 돈이 계속 샜다([[feedback_gate_at_the_neck]]).
    if _drop_queued_loop_frames(context):
        messages.append(context.queue_state_payload())
    return messages


async def _stop_auto_generation_for_quota(
    context: WebSessionContext,
    clients: set[WebSocket],
) -> None:
    """무료 사용량이 마르면 도는 것을 멈추고 **왜 멈췄는지** 알린다."""
    messages = await stop_all_generation_loops(context, clients)
    # 기준이 상태에 따라 다르다 - 계정을 지목했으면 그 계정 하나가 기준이다.
    # 그대로 "모든 계정" 이라 말하면 남은 무료 풀까지 마른 줄로 읽힌다.
    try:
        from core.nai_account_service import NaiAccountService

        picked = NaiAccountService(context).forced_account()
    except Exception:   # noqa: BLE001 - 문구 하나 때문에 정지 처리가 죽으면 안 된다
        picked = ""
    messages.append(context._toast(
        ("선택한 계정의 무료 사용량이 0% 입니다. 자동 생성을 해제했습니다."
         if picked else "모든 계정의 무료 사용량이 0% 입니다. 자동 생성을 해제했습니다."),
        level="warning",
    ))
    for message in messages:
        await broadcast_json(clients, message)


async def _maybe_continue_auto_generation(
    context: WebSessionContext,
    clients: set[WebSocket],
    request,
) -> bool:
    params = getattr(request, "params", {}) or {}

    # Sequence 연속 생성(Auto Gen): 시퀀스 프레임이면 _advance_sequence_run 이 라운드 카운트를
    # 진전시키고(완료 시 다음 랜덤 그룹 연속 또는 종료) True 를 돌려준다. 시퀀스는 '그룹 전체'를
    # 새로 넣으므로 아래 제네릭 프롬프트 재롤 경로를 타면 안 된다 — 처리됐으면 곧장 return.
    # 무료 사용량이 모두 마르면 여기서 끊는다(사용자 지정).
    #
    # ⚠️ **맨 앞이다.** 바로 아래 `_advance_sequence_run` 은 시퀀스 요청이면 곧장
    #    돌아가므로, 뒤에 두면 시퀀스 연속 생성이 가드를 통째로 건너뛰고 라운드마다
    #    새 묶음을 유료로 넣는다(Codex BLOCK 2026-08-25).
    # ⚠️ **Automation 정책보다도 먼저다** - 아래 record_generation_completed 는
    #    "계속" 이라 말할 수 있고, 그 말을 들으면 그 다음 장부터 Anlas 로 나간다.
    # ⚠️ 판정은 **완료 알림 직전에** 이미 내려 두었다(그 알림에 실어 프런트 루프도
    #    멈추게 해야 하므로). 여기서 다시 재지 않고 그 답을 그대로 쓴다 - 두 번 재면
    #    그 사이에 폴러가 캐시를 바꿔 알림과 서버 판단이 어긋날 수 있다.
    if getattr(context, "_auto_gen_quota_stop", False):
        context._auto_gen_quota_stop = False
        await _stop_auto_generation_for_quota(context, clients)
        return False

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
            _release_auto_gen_prefetch(context)  # 스토리 종료 → 예약 홀더 폐기
            return False
    elif automation_run_id:
        policy = context._automation_service().record_generation_completed(automation_run_id)
        hold_prompt = bool(policy.get("hold_prompt", False))
        await _broadcast_automation_state(context, clients)
        for message in policy.get("messages", []):
            await broadcast_json(clients, message)
        if not policy.get("continue"):
            _release_auto_gen_prefetch(context)  # Automation 종료/카운트 소진 → 예약 홀더 폐기
            return False
        delay_seconds = float(policy.get("delay_seconds") or 0.0)
        if delay_seconds > 0:
            context._automation_service().begin_delay(automation_run_id, delay_seconds)
            await _broadcast_automation_state(context, clients)
            if not await _wait_for_automation_delay(context, automation_run_id, delay_seconds):
                await _broadcast_automation_state(context, clients)
                _release_auto_gen_prefetch(context)  # 딜레이 중단 → 예약 홀더 폐기
                return False
            context._automation_service().end_delay(automation_run_id)
            await _broadcast_automation_state(context, clients)

    if not _should_continue_auto_generation(context, request):
        _release_auto_gen_prefetch(context)  # 루프 중단(Auto Gen off·큐 점유·특수) → 예약 홀더 폐기
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
    # Pristine base negative for the next iteration. The request's base_negative_prompt
    # is captured BEFORE conditional merge (enqueue_remote_request) and is present on
    # every GenerationRequest, so it is the authoritative pristine value even when it is
    # legitimately empty. Only fall back to params/context when the field is ABSENT
    # (legacy request) — a truthiness-based `or` would let an empty base leak back to the
    # conditionally-merged params value and re-start the accumulation for empty-negative users.
    if hasattr(request, "base_negative_prompt"):
        base_negative = str(request.base_negative_prompt or "")
    else:
        base_negative = str(params.get("negative_prompt") or context.negative_prompt_text or "")
    overrides["negative_prompt"] = base_negative
    overrides["auto_generate"] = True
    overrides["prompt_fixed"] = effective_prompt_fixed
    # Auto Gen은 매 반복마다 새 랜덤 시드를 사용한다 (사용자가 seed_fixed로 명시 고정한 경우 제외).
    # 특히 prompt_fixed면 프롬프트가 동일하므로, 직전 생성의 구체 시드를 그대로 재사용하면
    # 같은 이미지만 반복된다. seed=-1로 리셋해 시드 정규화에서 재랜덤화되도록 한다.
    if not context._coerce_bool(overrides.get("seed_fixed", params.get("seed_fixed", False))):
        overrides["seed"] = -1
    # ⚠️ **앞 반복의 해상도 핀을 여기서 놓아 준다.**
    #    `_auto_generation_overrides` 는 직전 생성의 params 를 그대로 물고 오는데,
    #    enqueue 가 `params.update(remote_params)` **다음에** `params.update(overrides)`
    #    를 하므로 그 핀이 라이브 값을 이긴다 - 사용자가 Auto Gen 도중 바꾼 해상도가
    #    조용히 무시된다(화면만 바뀐다).
    #    실측 2026-08-29 (Auto Gen 4장): 1장째 뒤 Prompt Fix 를 켜고 해상도를
    #    1216x832 로 바꿨는데 **4장 내내 832x1216** 로 나갔다.
    #    Rnd Res OFF + Prompt Fix ON 이면 아래 전용 로직(재추첨 / 감지값 / 스토리
    #    플랜)이 **하나도 안 돌아** 핀이 영원히 산다.
    #    조건을 따지지 않는다 - 전용 로직이 돌면 그것이 다시 써 넣고, 하나도 안 돌면
    #    라이브 `remote_params` 값이 적용된다. 어느 쪽이든 옳다.
    #    ⚠️ 셋을 **함께** 놓아야 한다. `resolution` 만 놓고 width/height 를 남기면
    #       라벨과 치수가 어긋난 채로 나간다(하류는 치수를 먼저 본다).
    #    ⚠️ **놓기만 해서는 안 된다.** `remote_params` 자체가 셋을 따로 들고 있고,
    #       `set_param("resolution", ...)` 은 **그 키 하나만** 갱신한다 - 치수는 낡은 채
    #       남는다(실측: 저장된 COMFYUI 평면이 `resolution '1408 x 960'` 인데
    #       `width 1280 / height 1024` 로 이미 어긋나 있었다). 그냥 놓으면
    #       `params.update(remote_params)` 가 그 낡은 치수를 실어 오고, 하류
    #       `_normalize_resolution` 이 치수를 먼저 보므로 라벨이 진다.
    #       그래서 **라이브 라벨에서 셋을 다시 만들어** overrides 에 넣는다 -
    #       overrides 가 remote_params 보다 뒤에 얹히므로 라벨이 권위를 갖는다.
    #       (Codex 리뷰 2026-08-29 HIGH. 실제 세션 파일로 확인했다.)
    for _res_key in ("resolution", "width", "height"):
        overrides.pop(_res_key, None)
    _live_label = (getattr(context, "remote_params", None) or {}).get("resolution")
    _live_w, _live_h = _parse_resolution_label(_live_label)
    if _live_w and _live_h:
        overrides["resolution"] = f"{_live_w} x {_live_h}"
        overrides["width"] = _live_w
        overrides["height"] = _live_h
    # Rnd Res must re-roll every Auto Gen iteration, exactly like a manual Random
    # press. The frontend picks a random resolution per click (_collectCurrentParams),
    # but this server-side loop reuses the previous params, so without this the
    # resolution stays frozen when Rnd Res is on without Auto Res. (Auto Res still
    # wins afterwards via detected_resolution when both are enabled.)
    _reroll_random_resolution(context, overrides)
    # Character Reference(NAI v4.5)도 Auto Gen 매 반복마다 라이브 UI 상태를 다시 읽어야 한다.
    # 직전 생성의 baked params(apply_headless_image_module_params 가 director_reference_* 를
    # 구워 넣음)가 overrides 로 핀되면, 다음 생성의 apply() 가 'director_reference_descriptions
    # 이미 존재' 가드(headless_image_module_param_service.apply)에 걸려 라이브 재조회를 건너뛴다
    # → 사용자가 Auto Gen 도중 캐릭터 레퍼런스를 끄거나 strength/fidelity 를 바꿔도 반영되지
    # 않는다(사용자 버그 리포트). seed/Rnd Res/vibe 와 동일하게, active_params() 가 만들어내는
    # director_reference_* 키를 모두 제거해(비활성 시 잔재 키가 남지 않도록) 매 반복 라이브
    # character_reference_frames 에서 새로 조립되게 한다.
    for key in CHARACTER_REFERENCE_LIVE_REFETCH_KEYS:
        overrides.pop(key, None)
    # Vibe Transfer(NAI 모듈 프레임)도 char-ref와 동일 — Auto Gen 매 반복 라이브 재조회. 직전
    # 생성의 baked reference_image_multiple이 overrides로 핀되면 apply()의 'reference_image_multiple
    # 존재' 가드가 active_vibe_transfer_params() 라이브 재조립을 건너뛴다 → Auto Gen 도중 vibe를
    # 교체/삭제/강도조절해도 생성 시작 시점 vibe가 계속 적용되던 버그(사용자 리포트). 클러스터 vibe도
    # load_cluster가 모듈 프레임으로 넣으므로 함께 갱신된다. story 'Use Vibe'의 '딱 1장' 보장도 이
    # pop으로 충족된다(직전 일반+스트림 vibe 제거 → enqueue에서 라이브 일반 + 현재 스트림 1장 재조립).
    for key in VIBE_TRANSFER_LIVE_REFETCH_KEYS:
        overrides.pop(key, None)
    # 레퍼런스 인셋 핀도 라이브 재조회 - baked 캔버스/type이 overrides로 핀되면
    # 핀 해제 후에도 계속 인셋 인페인트로 나간다. 마커가 있을 때만 pop한다
    # (width/height는 일반 키 - 무조건 pop하면 남의 해상도를 지운다).
    if overrides.get(REFERENCE_INSET_PIN_MARKER):
        for key in REFERENCE_INSET_LIVE_REFETCH_KEYS:
            overrides.pop(key, None)
    # PARAMS 패널 값(라이브 remote_params)도 char-ref/vibe 와 동일하게 매 반복 라이브 재조회되게
    # overrides 에서 제거한다 — Auto Gen 도중 PARAMS(특히 ComfyUI/ANIMA) 변경 미반영 버그 수정.
    _drop_live_param_overrides(overrides, getattr(context, "remote_params", {}))
    if story_run_id:
        # Carry the story run id so the next completion re-binds to this same cycle.
        overrides["event_stream_run_id"] = story_run_id
        queue_source = "Storyteller"
    elif automation_run_id:
        queue_source = "Automation"
    else:
        queue_source = "Auto Generate"
    overrides["_remote_queue_source"] = queue_source
    overrides["_remote_queue_label"] = queue_source

    request_id = f"auto-{uuid.uuid4().hex}"
    prompt = str(params.get("input") or params.get("_raw_input") or context.prompt_text or "")
    negative = base_negative

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
            # Rnd Res 결정은 _reroll_random_resolution 과 동일하게 라이브 remote_params 우선 —
            # 그래야 라이브-ON/핀-OFF(stale) 상태에서 이 게이트가 방금 재추첨한 해상도를 base 로
            # 되돌리지 않는다(Codex 리뷰 잔여 우려 해소).
            _rp = getattr(context, "remote_params", None) or {}
            if not context._coerce_bool(_rp.get("random_resolution", overrides.get("random_resolution", False))):
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

    # 이 continuation이 프리페치를 소비하지 않는 경우(고정 프롬프트/스토리/특수)엔 예약 홀더 폐기.
    if effective_prompt_fixed or story_run_id or is_special_request(params, context._coerce_bool):
        _release_auto_gen_prefetch(context)
    if not effective_prompt_fixed:
        result = None
        # Ollama Auto Boost 오버랩 소비 — 유효한 예약행+boost가 있으면 그대로 사용(이미지
        # 생성과 겹쳐 이미 계산됨 → 지연 0). 일반 Auto Gen/Automation만. Story(고정 정체성)는
        # 시도 안 하고, Preset/특수는 위 _should_continue_auto_generation이 이미 차단.
        if not story_run_id and not is_special_request(params, context._coerce_bool):
            result = await _consume_auto_gen_prefetch(context, overrides, request_id)
        if result is None:
            # 폴백: 동기 generate + 동기 boost(Phase 1). 남은 프리페치 홀더는 정리.
            _release_auto_gen_prefetch(context)
            result = await asyncio.to_thread(
                random_service(context).generate,
                active_ratings=context.get_active_ratings(),
                overrides=overrides,
                random_request_id=request_id,
            )
            if not story_run_id and not is_special_request(params, context._coerce_bool):
                from app.backend.server.generation_commands import apply_ollama_auto_boost
                await apply_ollama_auto_boost(context, result)
        # ⚠️ **풀이 비었으면 수동 Random 과 똑같이 되살린다**(사용자 지정 2026-08-31).
        #    예전에는 회복이 수동 경로에만 있어서, Auto Gen 도중 태그가 소진되면
        #    생성만 멈추고 Auto Gen 은 켜진 채로 남았다. 사양은 한 자리에 있고
        #    (`recover_exhausted_random_pool`) 둘이 같이 쓴다.
        #    사용자가 Tag Filter 의 [Auto Gen 상태에서 태그 소진시 자동 중단] 을 켜 두면
        #    되살리지 않는다 - 아래 실패 분기가 Auto Gen 체크까지 함께 해제한다.
        stop_on_exhaust = context._coerce_bool(
            context.get_options().get("stop_autogen_on_tag_exhaust", False))
        if not stop_on_exhaust:
            from app.backend.server.generation_commands import recover_exhausted_random_pool
            result = await recover_exhausted_random_pool(
                context, clients, result,
                active_ratings=context.get_active_ratings(),
                overrides=overrides,
                request_id=request_id,
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
                "message": (
                    "태그를 다 써서 Auto Gen 을 멈췄습니다. (Tag Filter 의 자동 중단 설정)"
                    if stop_on_exhaust else
                    (payload.get("message") or "Auto Generate stopped: random prompt failed.")
                ),
            })
            # ⚠️ 루프만 끝내고 스위치를 켜 둔 채 나가면, 화면은 '돌고 있다' 고 말하는데
            #    아무것도 안 돈다(사용자 제보 2026-08-31). 회복까지 실패했으면 끈다.
            if not story_run_id and not automation_run_id:
                if context._coerce_bool(context.get_options().get("auto_generate", False)):
                    context.set_option("auto_generate", False)
                    await broadcast_json(clients, {"type": "options", **context.get_options()})
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

    # ⚠️ **여기서 한 번 더 본다.** 위쪽 `_should_continue_auto_generation` 검사와 이
    #    줄 사이에 프롬프트 생성(`to_thread`)·Ollama boost·broadcast 가 여럿 끼어
    #    있어서, 그 사이에 인페인트 세션이 열리거나 사용자가 Auto Gen 을 꺼도 이
    #    한 장은 그대로 유료로 나갔다(Codex HIGH 2026-08-28).
    #    판정은 순수 읽기라 두 번 불러도 부작용이 없다 - 값이 나가는 **마지막 한 줄**
    #    앞에 거는 것이 규칙이다([[feedback_gate_at_the_neck]]).
    if not _should_continue_auto_generation(context, request):
        _release_auto_gen_prefetch(context)
        return False

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
    """Whether a completed request should count against the running Automation.

    Event/Remote Preset completions consume the Automation limit even though they
    remain suppressed from the separate server-side Auto Generate continuation.
    Other suppressed and special requests never consume the limit.
    """
    if not context._automation_service().is_running():
        return False
    params = getattr(request, "params", {}) or {}
    if not isinstance(params, dict):
        return False
    if any(
        context._coerce_bool(params.get(key, False))
        for key in AUTO_GENERATE_SUPPRESSED_FLAGS
        if key not in _AUTOMATION_BINDABLE_DESPITE_SUPPRESSION
    ):
        return False
    request_type = str(params.get("type") or "").strip().lower()
    if request_type in SPECIAL_REQUEST_TYPES and not context._coerce_bool(
        params.get(REFERENCE_INSET_PIN_MARKER, False)
    ):
        # 레퍼런스 인셋 핀 생성은 type=inpaint지만 plain - Automation 카운트에 포함.
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
    # 플래그+type 판정은 is_special_request(SSOT)로 - 인라인 복제는 레퍼런스 인셋
    # 마커 화이트리스트(type=inpaint여도 plain)를 놓쳐 인셋 핀 상태에서 Auto Gen
    # 연쇄가 조용히 멈췄다(사용자 결함 제보 2026-07-18).
    if is_special_request(params, context._coerce_bool):
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
    # Rnd Res 결정값(random_resolution / resolution_preset_enabled / resolution_preset)은 라이브
    # remote_params 를 우선 읽는다 — Auto Gen 도중 Rnd Res·프리셋 토글을 즉시 반영(핀된 overrides
    # 는 fallback). (Codex 리뷰: reroll 결정이 직전 핀값을 써서 한 박자 stale 했음.)
    rp = getattr(context, "remote_params", None) or {}
    if not context._coerce_bool(rp.get("random_resolution", overrides.get("random_resolution", False))):
        return
    from core.resolution_utils import (
        ANIMA_RESOLUTION_PRESET_LABELS,
        NAI_RESOLUTION_PRESET_LABELS,
        STANDARD_1MP_RESOLUTION_LABELS,
        normalize_anima_resolution_preset_id,
        normalize_nai_resolution_preset_id,
    )

    mode = str(overrides.get("api_mode") or context.get_api_mode() or "").strip().upper()
    labels: tuple[str, ...] = ()
    if mode in {"WEBUI", "COMFYUI"} and context._coerce_bool(
        rp.get("resolution_preset_enabled", overrides.get("resolution_preset_enabled", False))
    ):
        preset = normalize_anima_resolution_preset_id(
            rp.get("resolution_preset", overrides.get("resolution_preset"))
        )
        labels = ANIMA_RESOLUTION_PRESET_LABELS.get(preset) or ()
    elif mode == "NAI" and context._coerce_bool(
        rp.get("nai_resolution_preset_enabled",
               overrides.get("nai_resolution_preset_enabled", False))
    ):
        # NAI 밴드는 키가 따로다(위 import 주석 참조). 여기서 안 갈라 주면 Auto Gen
        # 이 밴드를 무시하고 저장된 전체 목록에서 뽑아, 화면이 보여 준 밴드 밖
        # 해상도로 생성이 나간다 - 그러면 Anlas 유료 경고와도 어긋난다.
        labels = NAI_RESOLUTION_PRESET_LABELS.get(
            normalize_nai_resolution_preset_id(
                rp.get("nai_resolution_preset", overrides.get("nai_resolution_preset"))
            )
        ) or ()
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
            # Interactive 모드 캐릭터 소유권 마커. 유실되면 continuation 2회차부터 캐릭터
            # 모듈 프레임과 Character Reference 가 다시 새어 들어온다(Interactive 는 캐릭터를
            # overrides.characters 로 직접 싣고 모듈 경로를 차단한다). 활성 캐릭터가 없는
            # Interactive 세션에서는 characters 키 자체가 없어 이 플래그가 유일한 방어선이다.
            "_skip_character_late_binding",
            "_skip_character_reference_late_binding",
            # Interactive 전용 레퍼런스 바인딩 마커. 유실되면 continuation
            # 2회차부터 레퍼런스가 통째로 빠진다.
            "_interactive_reference_binding",
            # 인셋 마커가 유실되면 continuation의 인셋 키 pop 가드가 영영 발동하지
            # 않아 baked 캔버스(type/image_bytes)가 다음 반복에 박제된다.
            REFERENCE_INSET_PIN_MARKER,
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



async def _broadcast_character_instant_preview(clients, stored, params) -> None:
    """캐릭터 즉시 생성 결과를 프리뷰 창에도 띄운다.

    ⚠️ 결과 저장소에서 **빼지 않는다**(프리뷰와 다른 점). 이 그림은 평소 생성이라
       히스토리에 남아야 한다 - 여기서 빼면 사용자가 Results 에서 못 찾는다.
    """
    import base64

    item = stored.item
    executed = getattr(item, "generation_params", None) or {}
    await broadcast_json(clients, {
        "type": "nai_preview_result",
        "requestId": str(params.get("character_instant_request_id") or ""),
        # 창이 갈래를 안다 - [Save] 는 감추고(이미 저장됐다) [Generate] 는 이 캐릭터로
        # 다시 뽑는다.
        "kind": "character",
        "uuid": str(params.get("character_instant_uuid") or ""),
        "title": str(params.get("nai_preview_title") or ""),
        "width": int(params.get("width") or 0),
        "height": int(params.get("height") or 0),
        "steps": int(params.get("steps") or 0),
        "model": str(params.get("model") or ""),
        "characters": [str(c) for c in (executed.get("_executed_characters") or [])],
        "image": base64.b64encode(item.webp_bytes).decode("ascii"),
    })


async def _finish_nai_preview(context: WebSessionContext, clients, request, stored) -> None:
    """프리뷰 한 장을 프리뷰 창으로 보내고 **흔적을 지운다**.

    ⚠️ `execute_request` 는 이미 결과 저장소에 넣어 두었다. 안 빼면 새로고침했을 때
       히스토리에 나타난다 - 사용자는 저장한 적이 없는 그림을 보게 된다.
    ⚠️ 그래도 **바이트는 들고 있는다**([Save] 를 누르면 그때 되살린다). 화면이 base64 를
       되보내게 하면 큰 본문이 왕복하고, 그 사이 사용자가 다른 프리뷰를 뽑으면 어느
       것을 저장하는지 헷갈린다.
    """
    import base64

    params = getattr(request, "params", {}) or {}
    item = stored.item
    # 실행본 기록은 결과 항목이 들고 있다(위 주석 참조).
    executed = getattr(item, "generation_params", None) or {}
    # [Save] 가 쓸 한 칸. 다음 프리뷰가 덮는다 - 마지막 것만 저장할 수 있다.
    context.nai_preview_last_item = item
    try:
        context.result_store.remove_item(item)
    except Exception as exc:
        print(f"[NaiPreview] result store cleanup failed: {exc}", flush=True)

    await broadcast_json(clients, {
        "type": "status",
        "is_generating": False,
        "message": "completed",
    })
    await broadcast_json(clients, {
        "type": "nai_preview_result",
        "requestId": str(params.get("nai_preview_request_id") or ""),
        # 창의 머리글. 프리뷰와 즉시 생성이 **같은 창**을 쓰므로 무엇을 보고 있는지
        # 말해 줘야 한다(기본값은 프리뷰 - 옛 경로가 이 키를 안 싣는다).
        "title": str(params.get("nai_preview_title") or ""),
        # ⚠️ **정말로 실려 나간** 캐릭터다. `api_service` 가 페이로드를 만들 때 적는
        #    `_executed_characters` 라, 요청에 적은 것이 아니라 `char_captions` 에
        #    들어간 것 - '전달됐는가' 를 여기서 확인할 수 있다.
        #
        # ⚠️ **요청이 아니라 결과 항목에서 읽는다.** 생성 서비스가
        #    `params = dict(request.params)` 로 사본을 뜨고 실행하므로, api_service 가
        #    적은 값은 요청 쪽으로 **안 돌아온다**(라이브 실측: 캐릭터가 실제로는
        #    실려 나갔는데 여기서는 빈 배열이었다).
        "characters": [str(c) for c in (executed.get("_executed_characters") or [])],
        "width": int(params.get("width") or 0),
        "height": int(params.get("height") or 0),
        "steps": int(params.get("steps") or 0),
        "model": str(params.get("model") or ""),
        "image": base64.b64encode(item.webp_bytes).decode("ascii"),
    })
async def _auto_save_generated_history_item(context: WebSessionContext, item):
    if not context._coerce_bool(context.auto_save_state.get("auto_save", True)):
        return None
    try:
        return await asyncio.to_thread(context.save_history_item, item)
    except Exception as exc:
        return {"error": str(exc)}


_COMFYUI_MODE_LABELS = {"eps": "EPS", "v_prediction": "V-Pred", "anima": "ANIMA"}


async def _commit_comfyui_mode_swap(
    context: WebSessionContext,
    clients: set[WebSocket],
    swap,
) -> None:
    """ComfyUI 자동 EPS↔ANIMA 스왑이 성공(3회차)했을 때만 호출된다 — 모드를 확정한다.

    백엔드 ``remote_params``(Auto Gen 연속 + 이후 생성의 sampling_mode SSOT)와 프런트
    UI 플래그를 새 모드로 동기화하고, 노란 경고 토스트로 자동 전환을 사용자에게 알린다.
    실패한 생성에는 ``stored.comfyui_mode_swap`` 이 실리지 않으므로 호출되지 않는다
    (= 실패 시 스왑 미확정/원복).
    """
    if not isinstance(swap, dict):
        return
    new_mode = str(swap.get("to") or "").strip().lower()
    new_wf = str(swap.get("to_workflow_type") or "").strip().lower()
    from_mode = str(swap.get("from") or "").strip().lower()
    if new_mode not in {"eps", "anima"}:
        return
    # 백엔드 SSOT 갱신 — Auto Gen 연속/이후 생성이 확정된 모드를 쓰도록.
    try:
        rp = getattr(context, "remote_params", None)
        if isinstance(rp, dict):
            # 스테일니스 가드: 생성 중 사용자가 모드를 바꿨으면(라이브 != 원래 from) 확정을
            # 건너뛴다 — 자동 스왑이 사용자의 라이브 선택을 덮어쓰지(stomp) 않도록.
            live_mode = str(
                rp.get("sampling_mode") or rp.get("comfyui_sampling_mode") or ""
            ).strip().lower()
            if live_mode and from_mode and live_mode != from_mode:
                return
            rp["sampling_mode"] = new_mode
            rp["comfyui_sampling_mode"] = new_mode
            if new_wf:
                rp["workflow_type"] = new_wf
    except Exception:
        pass
    # 프런트 UI 플래그 확정(setSamplingMode 경유).
    await broadcast_json(clients, {
        "type": "comfyui_sampling_mode_swapped",
        "sampling_mode": new_mode,
        "workflow_type": new_wf,
        "from": from_mode,
    })
    # 노란 경고 토스트.
    from_label = _COMFYUI_MODE_LABELS.get(from_mode, from_mode or "?")
    to_label = _COMFYUI_MODE_LABELS.get(new_mode, new_mode)
    await broadcast_json(clients, {
        "type": "toast",
        "level": "warning",
        "message": (
            f"ComfyUI 생성이 2회 실패해 모드를 {from_label}→{to_label}(으)로 자동 전환했습니다. "
            f"3회차에 성공하여 모드를 {to_label}(으)로 확정합니다."
        ),
    })


async def _broadcast_generation_error(
    context: WebSessionContext,
    clients: set[WebSocket],
    request,
    message: str,
    error: BaseException | None = None,
) -> None:
    context.is_generating = False
    # 고른 모델을 레지스트리가 모른다 - 이건 사용자가 **다시 고르면 풀리는** 실패다.
    # 원문("등록되지 않은 NAI 모델 키입니다")은 계정 등록 문제처럼 읽혀서, 무엇을
    # 해야 하는지 말해 주는 문장으로 바꾸고 화면이 알아볼 표식을 싣는다.
    # ⚠️ 새 메시지 타입을 만들지 않고 **기존 것에 필드만** 더한다 - 웹 스모크 계약이
    #    타입을 순서대로 세기 때문이다.
    from core.nai_model_registry import UnknownNaiModelError

    model_unknown = isinstance(error, UnknownNaiModelError)
    if model_unknown:
        stale = getattr(error, "model_key", "")
        message = "모델을 다시 골라 주세요 - 저장된 모델을 알 수 없습니다"
        if stale:
            message = f"{message} ({stale})"
    params = getattr(request, "params", {}) or {}
    img2img_service = _img2img_lifecycle_service(context)
    img2img_failed = bool(
        img2img_service
        and img2img_service.record_generation_failed(params, request.request_id, message)
    )
    # 실패에도 런 표를 싣는다. 안 실으면 남의 실패로 내 연속 생성이 멈춘다(Codex CONCERN).
    _scene_run = str((params or {}).get("v5_scene_run") or "")
    await broadcast_json(clients, {"type": "status", "is_generating": False,
                                  "message": "error", "v5_scene_run": _scene_run})
    await broadcast_json(clients, {"type": "toast", "level": "error", "message": message,
                                  "model_unknown": model_unknown})
    await broadcast_json(clients, {"type": "generation_error", "message": message,
                                  "v5_scene_run": _scene_run,
                                  "model_unknown": model_unknown})
    story_run_id = str(params.get("event_stream_run_id") or "")
    if story_run_id and not context._storyteller_service().is_running(story_run_id):
        story_run_id = ""
    if story_run_id:
        failure = context._storyteller_service().fail(story_run_id, message)
        await _broadcast_storyteller_state(context, clients)
        for extra_message in failure.get("messages", []):
            await broadcast_json(clients, extra_message)
    automation_run_id = ""
    if not story_run_id:
        automation_run_id = str(params.get("automation_run_id") or "")
        if not automation_run_id and _automation_should_bind(context, request):
            automation_run_id = context._automation_service().active_run_id()
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
    if params.get("inpaint_sequence_request"):
        await broadcast_json(clients, {
            "type": "inpaint_sequence_generation_error",
            "requestId": str(params.get("inpaint_sequence_request_id") or ""),
            "groupId": str(params.get("inpaint_sequence_group_id") or ""),
            "frame": str(params.get("inpaint_sequence_frame") or ""),
            "message": message,
        })
    if params.get("character_asset_request"):
        await broadcast_json(clients, {
            "type": "character_asset_generation_error",
            "requestId": str(params.get("character_asset_request_id") or ""),
            "candidate": params.get("character_asset_candidate"),
            "message": message,
        })
    await broadcast_json(clients, context.queue_state_payload())
    if img2img_failed:
        await _broadcast_img2img_generation_state(context, clients)


async def _save_artist_thumbnail(context: WebSessionContext, stored, params: dict) -> None:
    """Artist 탭 생성 결과를 그 아티스트의 썸네일로 남기고, 화면이 알아볼 표식을 싣는다.

    예전에는 아무 데도 저장하지 않아 브라우저 메모리(`resultMemory`)에만 있었고
    재시작하면 사라졌다 - 캐릭터 뷰어와 달리 이쪽은 **처음부터 없던 기능**이다
    (future01 에도 저장 경로가 없었다). 신규로 붙인다(사용자 결정 2026-08-26).

    ⚠️ 표식은 **기존 image_meta 에 필드만** 더한다. 새 WS 메시지 타입을 만들면
       웹 스모크 계약(타입을 순서대로 셈)이 깨진다.
    ⚠️ 저장 실패가 생성을 망치면 안 된다 - 삼키고 로그만 남긴다.
    """
    artist = str(params.get("artist_thumb_artist") or params.get("_remote_queue_label") or "").strip()
    image = getattr(getattr(stored, "item", None), "image", None)
    if not artist or image is None:
        return
    # ⚠️ **모델(폴더) 단위로 저장한다**(사용자 지정). 프레임에 baking 된 모델을 먼저
    #    본다 - 생성이 끝난 뒤 사용자가 모델을 바꿨어도 이 그림은 그때 그 모델의 것이다.
    model = str(params.get("model") or "").strip()
    if not model:
        try:
            model = str(context._current_model_key() or "").strip()
        except Exception:
            model = ""
    saved = None
    try:
        saved = await asyncio.to_thread(
            artist_thumbnail_service(context).save_generated_thumbnail,
            image, artist, model, str(params.get("api_mode") or ""),
        )
    except Exception as exc:   # noqa: BLE001
        print(f"[artist-thumb] thumbnail save failed: {exc}", flush=True)
    meta = stored.image_meta if isinstance(stored.image_meta, dict) else {}
    meta.update({
        "artist_thumb_saved": bool(saved),
        "artist_thumb_url": str(saved.get("url") or "") if isinstance(saved, dict) else "",
        "artist_thumb_model": str(saved.get("model") or "") if isinstance(saved, dict) else "",
        "artist_thumb_api_mode": str(saved.get("api_mode") or "") if isinstance(saved, dict) else "",
    })


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
        # 헤더의 "N thumbnails" 를 고치려고 `state()` 를 다시 부르면 전 캐릭터를 순회한다.
        # 저장 시점에 이미 정확한 값이 나오므로 그대로 실어 보낸다(삭제 경로와 같은 계약).
        "character_viewer_thumbnail_count": (
            int(thumbnail.get("thumbnail_count") or 0) if isinstance(thumbnail, dict) else 0
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
