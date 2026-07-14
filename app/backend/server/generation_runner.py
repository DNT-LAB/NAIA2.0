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
from app.backend.server.anlas_poller import broadcast_anlas, broadcast_anlas_if_vibe_encoded
from app.backend.server.prompt_tools_routes import save_prompt_engineering_thumbnail_bytes
from app.backend.server.websocket_broadcast import broadcast_image, broadcast_json, broadcast_preview_image
from core import result_image_payload_service as result_images
# 특수 요청 판정은 core와 공유한다(Storyteller Use Vibe가 같은 기준으로 plain generate를
# 가르므로) — 정의가 두 군데로 갈라지지 않게 core/auto_generation_flags.py가 단일 출처.
from core.auto_generation_flags import (
    AUTO_GENERATE_SUPPRESSED_FLAGS,
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
# Rnd Res 재추첨/Auto Res 가 별도 처리. 이 키들만 빼고 remote_params 의 나머지 키는 모두 제거한다.
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
                await _broadcast_generation_error(context, clients, request, str(exc))
                # 실패한 시퀀스 프레임도 라운드 카운트를 진전시켜야 연속 루프가 멈추지 않는다(Codex).
                try:
                    await _advance_sequence_run(context, clients, request)
                except Exception:
                    pass
                continue
            img2img_completed = bool(
                img2img_service
                and img2img_service.record_generation_completed(request_params, request.request_id)
            )
            auto_save_result = await _auto_save_generated_history_item(context, stored.item)

            context.is_generating = False
            await broadcast_json(clients, {"type": "status", "is_generating": False, "message": "completed"})
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
            if img2img_completed:
                await _broadcast_img2img_generation_state(context, clients)
    finally:
        context.is_generating = False
        context.headless_generation_runner_active = False
        # 큐 루프 종료(정상/중단/예외) — 남은 예약 홀더는 폐기(detached task 누수·stale 방지).
        _release_auto_gen_prefetch(context)


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
    run_id = str(params.get("sequence_run_id") or "")
    if not run_id or params.get("sequence_vibe_capture"):
        return  # 시퀀스 프레임 아님 / 캡처 프레임 자신은 vibe 소스라 주입 대상 아님
    svc = context._sequence_run_service()
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


async def _capture_sequence_vibe(context: WebSessionContext, clients: set[WebSocket], request, stored) -> None:
    """Sequence Use Vibe: 캡처 stamp 가 달린 라운드 첫 이미지의 생성 결과를 인코딩(2 Anlas)해
    이후 프레임용 임시 vibe 로 보관한다. 라운드당 1회만(이미 인코딩됐으면 skip). 비NAI/소스 없음/
    인코딩 실패는 경고 토스트 후 vibe 없이 계속(사용자 확정 — 실패가 시퀀스를 막지 않는다)."""
    params = getattr(request, "params", None)
    if not isinstance(params, dict):
        return
    run_id = str(params.get("sequence_run_id") or "")
    if not run_id or str(params.get("sequence_vibe_capture") or "") != run_id:
        return
    svc = context._sequence_run_service()
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
    # Rnd Res 결정값(random_resolution / resolution_preset_enabled / resolution_preset)은 라이브
    # remote_params 를 우선 읽는다 — Auto Gen 도중 Rnd Res·프리셋 토글을 즉시 반영(핀된 overrides
    # 는 fallback). (Codex 리뷰: reroll 결정이 직전 핀값을 써서 한 박자 stale 했음.)
    rp = getattr(context, "remote_params", None) or {}
    if not context._coerce_bool(rp.get("random_resolution", overrides.get("random_resolution", False))):
        return
    from core.resolution_utils import (
        ANIMA_RESOLUTION_PRESET_LABELS,
        STANDARD_1MP_RESOLUTION_LABELS,
        normalize_anima_resolution_preset_id,
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
) -> None:
    context.is_generating = False
    params = getattr(request, "params", {}) or {}
    img2img_service = _img2img_lifecycle_service(context)
    img2img_failed = bool(
        img2img_service
        and img2img_service.record_generation_failed(params, request.request_id, message)
    )
    await broadcast_json(clients, {"type": "status", "is_generating": False, "message": "error"})
    await broadcast_json(clients, {"type": "toast", "level": "error", "message": message})
    await broadcast_json(clients, {"type": "generation_error", "message": message})
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
    await broadcast_json(clients, context.queue_state_payload())
    if img2img_failed:
        await _broadcast_img2img_generation_state(context, clients)


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
