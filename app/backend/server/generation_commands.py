from __future__ import annotations

import asyncio
import json
import random
import uuid
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse

from app.backend.server.anlas_poller import broadcast_anlas_if_vibe_encoded
from app.backend.server.websocket_broadcast import broadcast_json as _broadcast_json
from core.headless_generation_service import HeadlessGenerationService
from core.headless_random_prompt_service import HeadlessRandomPromptService
from core.resolution_utils import (
    anima_resolution_preset_candidates,
    nearest_anima_preset_resolution,
    nearest_standard_1mp_resolution,
    parse_resolution_pair,
)
from core.web_session_context import WebSessionContext


GenerationRunnerStarter = Callable[[WebSessionContext, set[WebSocket]], None]
BroadcastJson = Callable[[set[WebSocket], dict[str, Any]], Awaitable[None]]

GENERATION_COMMAND_TYPES = {
    "bootstrap_random",
    "random",
    "generate",
    "depth_generate",
}

# --- ComfyUI random resolution contract (ports future01 bb47537) ---------------
# The external "NAIA Bridge" ComfyUI client reads top-level width/height from the
# /api/comfyui/random response. The headless payload only carried a NESTED
# detected_resolution (and only when auto_fit produced one), so a normal ComfyUI
# random call returned no width/height and the client raised a RuntimeError. These
# helpers guarantee a top-level resolution for the ComfyUI path ONLY (NAI/WEBUI and
# the shared websocket_payload are untouched).
_DEFAULT_COMFYUI_RESOLUTION = (832, 1216)


def _coerce_resolution_flag(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _positive_resolution_from_params(params: Any) -> tuple[int, int] | None:
    if not isinstance(params, dict):
        return None
    width = params.get("width")
    height = params.get("height")
    if (width is None or height is None) and params.get("resolution"):
        parsed = parse_resolution_pair(params.get("resolution"))
        if parsed:
            width, height = parsed
    try:
        width = int(width)
        height = int(height)
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return width, height


def _source_row_resolution(source_row: Any) -> tuple[int, int] | None:
    if source_row is None:
        return None
    getter = getattr(source_row, "get", None)
    try:
        if callable(getter):
            width = getter("image_width")
            height = getter("image_height")
        else:
            width = source_row["image_width"]
            height = source_row["image_height"]
        width = int(width)
        height = int(height)
    except (TypeError, ValueError, KeyError):
        return None
    if width <= 0 or height <= 0:
        return None
    return width, height


def _resolve_comfyui_response_resolution(result: Any, overrides: Any) -> tuple[int, int, str]:
    """Always return (width, height, source) for a ComfyUI random response.

    Fallback chain mirrors future01 RemoteBridge._comfyui_random_response_resolution:
    auto_fit result -> explicit request override -> preset snap (source row or random
    preset pick) -> nearest standard 1MP for source dims -> guaranteed default.
    """
    detected = getattr(result, "detected_resolution", None)
    if detected:
        try:
            return int(detected[0]), int(detected[1]), "detected_fit"
        except (TypeError, ValueError, IndexError):
            pass

    explicit = _positive_resolution_from_params(overrides if isinstance(overrides, dict) else None)
    if explicit:
        return explicit[0], explicit[1], "explicit"

    context = getattr(result, "context", None)
    settings = getattr(context, "settings", None) if context is not None else None
    source_pair = _source_row_resolution(getattr(context, "source_row", None))

    preset_flag = None
    if isinstance(overrides, dict) and overrides.get("resolution_preset_enabled") is not None:
        preset_flag = overrides.get("resolution_preset_enabled")
    elif isinstance(settings, dict):
        preset_flag = settings.get("resolution_preset_enabled")
    preset_id = None
    if isinstance(overrides, dict):
        preset_id = overrides.get("resolution_preset")
    if preset_id is None and isinstance(settings, dict):
        preset_id = settings.get("resolution_preset")

    if _coerce_resolution_flag(preset_flag):
        if source_pair:
            sw, sh = source_pair
            width, height = nearest_anima_preset_resolution(sw, sh, preset_id)
            return width, height, ("detected" if (width, height) == (sw, sh) else "detected_fit")
        candidates = anima_resolution_preset_candidates(preset_id)
        if candidates:
            width, height = random.choice(candidates)
            return int(width), int(height), "random"

    if source_pair:
        sw, sh = source_pair
        width, height = nearest_standard_1mp_resolution(sw, sh)
        return width, height, ("detected" if (width, height) == (sw, sh) else "detected_fit")

    width, height = _DEFAULT_COMFYUI_RESOLUTION
    return width, height, "default"


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


async def persist_prompt_engineering_settings(context: WebSessionContext) -> None:
    await asyncio.to_thread(context.persist_prompt_engineering_settings)


async def _request_json_payload(req: Request) -> dict[str, Any]:
    try:
        payload = await req.json()
    except Exception:
        payload = {}
    return payload if isinstance(payload, dict) else {}


async def _send_json(ws: WebSocket, payload: dict[str, Any]) -> None:
    await ws.send_text(json.dumps(payload, ensure_ascii=False))


async def _broadcast_wildcard_state(context: WebSessionContext, clients: set[WebSocket]) -> None:
    """Push the wildcard module state to every client so an open Wildcard
    Manager (inline or detached) reflects the wildcards just consumed by a
    random/WC-Solo prompt. Cheap no-op when the panel isn't the active module."""
    try:
        payload = context._wildcard_module_state()
    except Exception:
        return
    # 라이브 틱 마커 (generation_runner._broadcast_wildcard_state 와 동일 계약):
    # 프론트는 이 플래그가 있을 때만 런타임 섹션을 in-place 갱신한다.
    payload["live_update"] = True
    await _broadcast_json(clients, payload)


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


def invalidate_auto_gen_prefetch(context: WebSessionContext) -> None:
    """풀을 advance하는 경로(수동/REST random)에서 Auto Gen 프리페치 예약을 폐기한다.
    state_key는 풀 *교체*만 잡으므로(advance는 못 잡음) pop 어긋남을 명시 방어. best-effort."""
    holder = getattr(context, "_auto_gen_prefetch", None)
    if not holder:
        return
    task = holder.get("task")
    try:
        if task is not None and not task.done():
            task.cancel()
    except Exception:
        pass
    context._auto_gen_prefetch = None


def _inject_boost_at_main(prompt: str, addition: str) -> str:
    """boost 추가분을 메인 섹션 끝(=postfix 앞)에 끼워 넣는다 — e621 Auto-Boost와 같은 위치.
    final_prompt는 `prefix \\n\\n main \\n\\n postfix` 구조라 마지막 "\\n\\n"(main/postfix
    경계) 앞에 삽입한다. 경계가 없으면(단일 섹션) 끝에 덧붙인다(폴백)."""
    addition = str(addition or "").strip().strip(",").strip()
    if not addition:
        return prompt
    idx = prompt.rfind("\n\n")
    if idx == -1:
        return prompt.rstrip(" ,") + ", " + addition
    head, tail = prompt[:idx], prompt[idx:]
    return head.rstrip(" ,") + ", " + addition + tail


def _e621_meta_tags(ctx: Any) -> list:
    """context.metadata['e621_boost_tags']에서 태그명만 추출. 실제 shape은 dict 리스트
    ({'tag': ...}); 문자열 리스트도 방어적으로 허용(Codex Must-fix 2)."""
    meta = getattr(ctx, "metadata", None) or {}
    out = []
    for it in (meta.get("e621_boost_tags") or []):
        if isinstance(it, dict):
            t = it.get("tag")
        else:
            t = it
        if t:
            out.append(str(t))
    return out


def _build_boost_input(result: Any, settings: dict) -> "str | None":
    """[기능3] Ollama 입력 구성. base = 원시 장면 태그(source_row['general']) — 인물수/주체
    (1girl 등; 포매터가 main_tags→prefix_tags로 옮겨 main만으론 사라짐, Codex Must-fix 1)를
    포함하고 e621 boost 미포함(파이프라인이 main_tags에 append하기 전). 기본(모두 OFF)=장면만.
    선택 시 prefix/postfix는 **와일드카드 출력만**(고정 아티스트/퀄리티 태그 제외 — 사용자
    요청), e621은 metadata(dict→tag)를 가중치 제거 후 추가."""
    from core.scene_boost import strip_weight_syntax

    ctx = getattr(result, "context", None)
    if ctx is None:
        return None
    meta = getattr(ctx, "metadata", None) or {}

    # 후처리(remove_color/object/features 등) + 와일드카드 전개를 반영한 main 스냅샷을 우선
    # 근거로 쓴다. raw source_row['general']은 전처리 *전*이라, 사용자가 remove_color 등으로
    # 제거한 색/객체/특징을 부스트가 prose로 되살려 그 설정을 무력화했다(_step_3 캡처본 사용).
    # 스냅샷 없으면 후처리 main_tags, 그것도 없으면 raw general 폴백.
    base = ""
    boost_main = meta.get("boost_main_tags")
    if isinstance(boost_main, list) and any(str(t).strip() for t in boost_main):
        base = ", ".join(str(t) for t in boost_main)
    if not base.strip():
        base = ", ".join(str(t) for t in (getattr(ctx, "main_tags", None) or []))
    if not base.strip():
        src = getattr(ctx, "source_row", None)
        if src is not None:
            try:
                base = str(src.get("general") or "")
            except Exception:
                base = ""

    parts = [strip_weight_syntax(base)]
    if settings.get("include_prefix"):
        # 고정 태그(아티스트/퀄리티)는 제외하고 prefix의 와일드카드 출력만(_step_3에서 캡처).
        pre_wc = meta.get("prefix_wildcard_tags") or []
        parts.append(strip_weight_syntax(", ".join(str(t) for t in pre_wc)))
    if settings.get("include_postfix"):
        post_wc = meta.get("postfix_wildcard_tags") or []
        parts.append(strip_weight_syntax(", ".join(str(t) for t in post_wc)))
    if settings.get("include_e621"):
        e_tags = _e621_meta_tags(ctx)
        if e_tags:
            parts.append(strip_weight_syntax(", ".join(e_tags)))
    # NAI v4/v4.5 캐릭터 프롬프트(이번 run의 전개본)도 접지에 포함 — 부스트가 캐릭터 의상/행위/
    # 소품을 참조할 수 있고, 환각 가드가 캐릭터 태그를 미입력으로 오판해 드롭하지 않는다.
    # (Phase3 freeze가 random-time 롤을 생성까지 고정하므로 부스트 접지 = 실제 생성 캐릭터.)
    char_prompts = (getattr(ctx, "settings", None) or {}).get("characters") or []
    for cp in char_prompts:
        cs = strip_weight_syntax(str(cp or ""))
        if cs:
            parts.append(cs)
    inp = ", ".join(p for p in parts if p)
    return inp or None


def _compose_addition(add: dict, settings: dict, context: WebSessionContext) -> str:
    """삽입 문자열 조립: 구도태그(무가중) + 자연어([기능1] nl_weight 래핑). 메인 섹션에 삽입.

    WEBUI/ComfyUI에서는 ``()`` 가 가중치 문법이므로, LLM 자연어 묘사에 들어 있는
    **리터럴 괄호**를 ``\\(`` ``\\)`` 로 이스케이프한다. Auto Boost는 파이프라인 *이후*에
    삽입돼 ``prompt_processor._escape_main_tags_parens`` 를 우회하므로, 여기서 직접
    처리하지 않으면 'soft glow (warm tone)' 같은 구절의 괄호가 A1111/ComfyUI 가중치
    파서에 오인식돼 강조가 깨진다(nl_weight>1로 ``(...:w)`` 래핑 시엔 중첩까지 발생).
    NAI는 파이프라인과 동일하게 이스케이프하지 않는다(가중치 wrap 괄호는 보존)."""
    from core.scene_boost import format_nl_weight

    is_nai = str(getattr(context, "current_api_mode", "") or "").upper() == "NAI"
    comp_parts = [str(c) for c in (add.get("composition_tags") or []) if str(c).strip()]
    desc_parts = [str(d) for d in (add.get("descriptions") or []) if str(d).strip()]
    if not is_nai:
        from core.prompt_processor import _escape_parens_in_content

        comp_parts = [_escape_parens_in_content(c) for c in comp_parts]
        desc_parts = [_escape_parens_in_content(d) for d in desc_parts]
    comp_str = ", ".join(comp_parts)
    desc_str = ", ".join(desc_parts)
    if desc_str:
        desc_str = format_nl_weight(desc_str, settings.get("nl_weight", 1.0), is_nai)
    return ", ".join(p for p in [comp_str, desc_str] if p)


async def apply_ollama_auto_boost(context: WebSessionContext, result: Any) -> bool:
    """Ollama Auto Boost — random 결과 프롬프트를 Scene Boost로 강화(스레드, best-effort).

    토글 OFF/Ollama 미준비/빈 프롬프트면 no-op. 성공 시 result.prompt·context.prompt_text·
    result.context(final_prompt+metadata)를 부스트본으로 갱신하고 True를 반환한다. 어떤
    실패에서도 raise하지 않으며 원문을 유지한다(생성 루프 불변). Auto Gen(파트4)에서도 재사용.
    """
    try:
        if not getattr(result, "success", False) or not getattr(context, "ollama_auto_boost", False):
            return False
        prompt = str(getattr(result, "prompt", "") or "")
        if not prompt.strip():
            return False
        from app.backend.server.ollama_routes import ollama_boost_settings, scene_boost_prompt

        settings = ollama_boost_settings(context)
        # [기능3] Ollama 입력 = 메인 장면 태그 + 선택된 prefix/postfix/e621(가중치 제거). 폴백=전체.
        boost_input = _build_boost_input(result, settings) or prompt
        # 설정을 이 호출에 freeze해 입력 구성과 boost stage 옵션이 서로 갈라지지 않게 한다.
        boosted = await asyncio.to_thread(
            scene_boost_prompt,
            context,
            boost_input,
            level=settings.get("effort"),
            allow_scent_style=settings.get("allow_scent_style"),
            allow_material_style=settings.get("allow_material_style"),
            allow_light_style=settings.get("allow_light_style"),
            emphasize_framing=settings.get("emphasize_framing"),
        )
        if not isinstance(boosted, dict) or not boosted.get("ok"):
            return False
        # 구도태그(무가중) + 자연어([기능1] nl_weight 래핑)를 메인 섹션 끝(e621 위치)에 삽입.
        add = boosted.get("additions") or {}
        addition = _compose_addition(add, settings, context)
        if not addition:
            return False
        new_prompt = _inject_boost_at_main(prompt, addition)
        if new_prompt == prompt:
            return False
        result.prompt = new_prompt
        context.prompt_text = new_prompt
        ctx = getattr(result, "context", None)
        if ctx is not None:
            try:
                ctx.final_prompt = new_prompt
                if isinstance(getattr(ctx, "metadata", None), dict):
                    ctx.metadata["ollama_auto_boost"] = {
                        "rating": boosted.get("rating"),
                        "level": boosted.get("level"),
                        "additions": add,
                        "settings": settings,
                    }
            except Exception:
                pass
        return True
    except Exception:
        return False


def _random_pool_has_hidden_rows(context: WebSessionContext) -> bool:
    """현재 rating/태그 필터로 가려졌을 뿐 실제 행은 남아 있는지(=필터 완화로 회복 가능한지)."""
    search_results = getattr(context, "search_results", None)
    if search_results is not None:
        try:
            if search_results.get_count() > 0:
                return True
        except Exception:
            pass
    for attr in ("search_results_snapshot", "search_results_master_base_snapshot"):
        frame = getattr(context, attr, None)
        if frame is not None and not getattr(frame, "empty", True):
            return True
    return False


def _reset_random_pool_to_gsqe(context: WebSessionContext) -> dict[str, Any]:
    """막힌 랜덤 풀 회복: 풀 등급을 gsqe로 강제 + 활성 태그필터 '할당' 해제(저장 칩은 보존) 후
    재적용. 재적용된 search_state(payload)를 반환한다. (등급은 디스크+메모리 모두 gsqe로 영속.)"""
    from app.backend.server.search_runtime import clear_active_tag_filter

    context.save_search_filter_state(ratings=["g", "s", "q", "e"])
    # reset_draft=False: 활성 태그필터 '할당'만 해제(in-memory active_tag_filter/ids=None →
    # 재시도 pop 이 전체 풀에서 성공)하되, 사용자가 저장한 include/exclude 칩(draft)은 보존한다.
    # 막힌 풀 회복이 저장 필터를 삭제하면 안 된다(Codex High#2) — 칩은 비활성으로 남아 재적용 가능.
    # (save 가 끝에 remote_active_ratings = state["ratings"] = gsqe 유지)
    return clear_active_tag_filter(context, False)


async def handle_random_command(
    ws: WebSocket,
    context: WebSessionContext,
    clients: set[WebSocket],
    command: dict[str, Any] | None = None,
    *,
    start_generation_runner: GenerationRunnerStarter,
) -> None:
    command = command if isinstance(command, dict) else {}
    overrides = command.get("overrides") if isinstance(command.get("overrides"), dict) else None
    request_id = str(command.get("random_request_id") or command.get("requestId") or "")
    active_ratings = _active_ratings_from_command(command) or context.get_active_ratings()
    # 수동 random은 풀을 advance하므로 Auto Gen 프리페치 예약행을 무효화(폐기).
    invalidate_auto_gen_prefetch(context)
    # 영속된 활성 태그필터가 아직 in-memory 로 재조립되지 않았으면(재시작/가져오기 직후) 백엔드가
    # 직접 재구성한다. 안 하면 필터가 무시된 전체 풀에서 뽑혀(result.success=True) 아래 failsafe 도
    # 안 걸리고, 표시 카운트(필터 기준)와 실제 풀(전체)이 어긋난다(사용자 리포트). no-op if already assigned.
    from app.backend.server.search_runtime import reconstruct_active_tag_filter
    await asyncio.to_thread(reconstruct_active_tag_filter, context)
    result = await asyncio.to_thread(
        random_service(context).generate,
        active_ratings=active_ratings,
        overrides=overrides,
        random_request_id=request_id,
    )
    # Fail-safe: 풀이 비어 보이지만(등급/Quick Filter 과제한) 실제 행이 남아 있으면 gsqe 로 강제
    # 초기화하고 1회 재시도 — 사용자가 '처리할 프롬프트가 더 이상 없습니다'로 막히지 않게 자동
    # 회복한다. (등급 desync = 검색이 풀을 gsqe 로 열어도 프론트가 gsq 로 되돌려 explicit 결과를
    # 못 뽑던 케이스 / stale 태그필터가 풀을 비운 케이스 모두 흡수.) 이미 gsqe·태그필터 없음이면
    # 재시도해도 의미 없으므로 건너뛴다.
    pool_already_full = set(active_ratings) == {"g", "s", "q", "e"} and not (
        getattr(context, "active_tag_filter", None) or getattr(context, "active_tag_filter_ids", None)
    )
    if (
        not result.success
        and not bool((overrides or {}).get("wildcard_standalone"))
        and not pool_already_full
        and _random_pool_has_hidden_rows(context)
    ):
        recovered_state = await asyncio.to_thread(_reset_random_pool_to_gsqe, context)
        await _broadcast_json(clients, recovered_state)
        await _broadcast_json(clients, {
            "type": "toast",
            "level": "warning",
            "message": "랜덤 풀이 비어 있어 등급을 전체(G/S/Q/E)로 열고 태그 필터를 해제했습니다. (저장한 필터 칩은 보존됨)",
        })
        result = await asyncio.to_thread(
            random_service(context).generate,
            active_ratings={"g", "s", "q", "e"},
            overrides=overrides,
            random_request_id=request_id,
        )
    # 수동 1회 random: 그 시점에 동기 부스트(프런트가 Random 버튼을 응답까지 disable).
    # Auto Gen 오버랩(파트4)은 별도 — 여기는 단발 경로.
    await apply_ollama_auto_boost(context, result)
    await persist_prompt_engineering_settings(context)
    # prompt_generated 는 유니캐스트가 아니라 브로드캐스트한다 — 요청 소켓이 half-open/끊긴 직후라도
    # (재연결한 새 소켓 포함) 모든 클라이언트가 좌측 패널에 적용 프롬프트를 받게 한다(RC-1: 적용은
    # 됐는데 좌측 창에 안 뜨던 버그). source 는 "random" 유지 — 프런트는 패널 갱신은 무조건 수용하고
    # 버튼 unlock 만 request-id 일치로 게이트한다(isMyRandom). extra_messages 도 함께 브로드캐스트.
    await _broadcast_json(clients, result.websocket_payload())
    for message in result.extra_messages:
        await _broadcast_json(clients, message)
    dispatch = await _maybe_enqueue_random_auto_generation(
        context,
        result=result,
        command=command,
        overrides=overrides,
        request_id=request_id,
        queue_source="Random",
    )
    if dispatch is not None:
        await _send_json(ws, dispatch.websocket_payload())
        if not dispatch.ok:
            await _send_json(ws, {
                "type": "toast",
                "level": "error",
                "message": dispatch.blocked_reason,
            })
            await _send_json(ws, {
                "type": "status",
                "is_generating": False,
                "message": "blocked",
            })
        else:
            await _send_generation_queued_state(ws, context)
            if context.headless_generation_execute_enabled:
                start_generation_runner(context, clients)
    # 와일드카드가 소비되었으므로(순차/종속 카운터 전진) 관리 창을 라이브 갱신한다.
    # 모든 ws 전송 이후에 broadcast 하여 클라이언트가 기대하는 메시지 순서를 보존.
    if result.success:
        await _broadcast_wildcard_state(context, clients)
        # 스트림(스토리/수동 진행) 활성 시 수동 랜덤도 시퀀스를 전진시키므로(1.5 모델)
        # Random 버튼 (n/m) 배지·패널 위치를 즉시 갱신한다.
        event_stream_runtime = getattr(context, "event_stream_runtime", None)
        if event_stream_runtime is not None and getattr(event_stream_runtime, "is_active", False):
            try:
                await _broadcast_json(clients, context._event_stream_module_state())
            except Exception:
                pass
    # Use Vibe 인코딩(2 Anlas)이 이 랜덤(스텝 전진)에서 일어났다면 잔액 차감을 pill에
    # 즉시 반영한다(generate 실패여도 인코딩은 일어났을 수 있어 무조건 검사 — no-op 안전).
    await broadcast_anlas_if_vibe_encoded(context, clients)


async def handle_bootstrap_random_command(
    ws: WebSocket,
    context: WebSessionContext,
    clients: set[WebSocket],
    command: dict[str, Any] | None = None,
    *,
    broadcast_json: BroadcastJson,
) -> None:
    command = command if isinstance(command, dict) else {}
    if str(context.prompt_text or "").strip():
        context.bootstrap_random_prompt_issued = True
        await _send_json(ws, {
            "type": "prompt_sync",
            "prompt": context.prompt_text,
            "negative": context.negative_prompt_text,
            "negative_prompt": context.negative_prompt_text,
        })
        return
    if getattr(context, "bootstrap_random_prompt_issued", False):
        return
    if getattr(context, "bootstrap_random_prompt_inflight", False):
        return

    context.bootstrap_random_prompt_inflight = True
    try:
        overrides = command.get("overrides") if isinstance(command.get("overrides"), dict) else None
        request_id = str(command.get("random_request_id") or command.get("requestId") or "")
        active_ratings = _active_ratings_from_command(command) or context.get_active_ratings()
        result = await asyncio.to_thread(
            random_service(context).generate,
            active_ratings=active_ratings,
            overrides=overrides,
            random_request_id=request_id,
        )
        await persist_prompt_engineering_settings(context)
        payload = result.websocket_payload()
        if result.success:
            context.bootstrap_random_prompt_issued = True
            payload["source"] = "bootstrap_random"
            await broadcast_json(clients, payload)
            for message in result.extra_messages:
                await broadcast_json(clients, message)
            await _broadcast_wildcard_state(context, clients)
        else:
            await _send_json(ws, payload)
            for message in result.extra_messages:
                await _send_json(ws, message)
    finally:
        context.bootstrap_random_prompt_inflight = False


async def run_random_fallback_for_empty_prompt(
    context: WebSessionContext,
    clients: set[WebSocket],
    *,
    broadcast_json: BroadcastJson,
) -> bool:
    """Bug 2b final fallback — when the prompt box is still empty after the preset
    restore (mode switch), run a single Random so a freshly-entered mode never
    shows an empty box. Mirrors the bootstrap-random path (sync boost + persist +
    broadcast result/wildcard state) but carries NO bootstrap guards and dispatches
    NO auto-generation. Returns True iff a non-empty prompt was produced.

    Best-effort: any failure is swallowed (logged) and returns False so a Random
    hiccup never aborts the surrounding mode switch — the box just stays empty."""
    if str(context.prompt_text or "").strip():
        return False
    try:
        # This advances the pool just like a manual/REST Random, so discard any
        # Auto Gen prefetch reservation first (parity with handle_random_command).
        invalidate_auto_gen_prefetch(context)
        active_ratings = context.get_active_ratings()
        result = await asyncio.to_thread(
            random_service(context).generate,
            active_ratings=active_ratings,
            overrides=None,
            random_request_id="",
        )
        # 단발 random과 동일하게 그 시점 동기 부스트 적용(Ollama Auto Boost ON일 때).
        await apply_ollama_auto_boost(context, result)
        await persist_prompt_engineering_settings(context)
        if getattr(result, "success", False):
            payload = result.websocket_payload()
            # Tag as bootstrap_random so the client accepts it as a non-pending
            # generated prompt (full apply: box + generated-resolution + highlight).
            # The default source "random" is only accepted against a pending user
            # Random, so it would silently drop here (Codex finding).
            payload["source"] = "bootstrap_random"
            await broadcast_json(clients, payload)
            for message in result.extra_messages:
                await broadcast_json(clients, message)
            await _broadcast_wildcard_state(context, clients)
        return bool(getattr(result, "success", False) and str(context.prompt_text or "").strip())
    except Exception as exc:  # noqa: BLE001 — never let the fallback break mode switch
        print(f"Remote Web: empty-prompt Random fallback failed: {exc}", flush=True)
        return False


async def handle_generate_command(
    ws: WebSocket,
    context: WebSessionContext,
    clients: set[WebSocket],
    command: dict[str, Any] | None = None,
    *,
    start_generation_runner: GenerationRunnerStarter,
) -> None:
    command = command if isinstance(command, dict) else {}
    await persist_prompt_engineering_settings(context)
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


def _refine_source_row_data(row: Any) -> dict[str, Any]:
    """Convert a sampled depth row (pandas Series) into a JSON/NaN-safe dict for
    ``_source_row_data`` so the queued GenerationRequest.source_row reconstructs
    the *sampled* row rather than the prior ``context.current_source_row``
    (which generate_from_source_row(update_context=False) restores before the
    enqueue boundary)."""
    import pandas as pd

    data: dict[str, Any] = {}
    try:
        raw = row.to_dict()
    except Exception:
        return data
    for key, value in raw.items():
        try:
            if pd.isna(value):
                data[str(key)] = None
                continue
        except (TypeError, ValueError):
            pass
        if isinstance(value, (str, int, float, bool)) or value is None:
            data[str(key)] = value
        else:
            data[str(key)] = str(value)
    return data


async def handle_depth_generate_command(
    ws: WebSocket,
    context: WebSessionContext,
    clients: set[WebSocket],
    command: dict[str, Any] | None = None,
    *,
    start_generation_runner: GenerationRunnerStarter,
) -> None:
    """Generate one image from the Refine (심층검색) sampled row.

    The sampled row is assembled through PromptProcessor/PE via
    ``generate_from_source_row(update_context=False)`` so the *main* prompt box is
    never overwritten and no ``prompt_generated`` is broadcast. The assembled
    prompt is then queued through ``handle_generate_command`` (shared enqueue/ack
    path) with the sampled row carried as ``_source_row_data`` and a Refine queue
    label, reusing the event_preset override pattern.
    """
    command = command if isinstance(command, dict) else {}

    state = context.depth_state if isinstance(getattr(context, "depth_state", None), dict) else None
    row = state.get("sample") if state is not None else None
    if row is None and state is not None:
        current = state.get("current")
        if current is not None and not getattr(current, "empty", True):
            row = current.sample(n=1).iloc[0]
            state["sample"] = row
    if row is None:
        await _send_json(ws, {"type": "depth_sample", "ok": False, "reason": "empty"})
        return

    active_ratings = _active_ratings_from_command(command) or context.get_active_ratings()
    request_id = str(
        command.get("random_request_id")
        or command.get("requestId")
        or f"refine-{uuid.uuid4().hex}"
    )

    # PE assembly with NO side effects on the main prompt context:
    # update_context=False restores current_source_row/current_prompt_context/
    # prompt_text/negative_prompt_text and skips the prompt_generated publish.
    result = await asyncio.to_thread(
        random_service(context).generate_from_source_row,
        row,
        active_ratings=active_ratings,
        random_request_id=request_id,
        source="refine_sample",
        update_context=False,
    )
    await persist_prompt_engineering_settings(context)
    if not result.success:
        await _send_json(ws, {
            "type": "toast",
            "level": "error",
            "message": result.error or "Refine generation failed",
        })
        return

    # Reuse the event_preset override pattern EXACTLY: carry the sampled row as
    # _source_row_data so HeadlessGenerationService._source_row() reconstructs the
    # sampled row (not the restored prior current_source_row), tag the queue source.
    gen_overrides: dict[str, Any] = {
        "input": result.prompt,
        "_raw_input": result.prompt,
        "_source_row_data": _refine_source_row_data(row),
        "_remote_queue_source": "Refine",
        "_remote_queue_label": "Refine",
    }
    name = getattr(row, "name", None)
    if name is not None:
        gen_overrides["_source_name"] = str(name)
    if result.detected_resolution:
        width, height = result.detected_resolution
        gen_overrides["width"] = width
        gen_overrides["height"] = height
        gen_overrides["resolution"] = f"{width} x {height}"

    gen_command: dict[str, Any] = {
        "type": "generate",
        "prompt": result.prompt,
        "negative_prompt": context.negative_prompt_text,
        "request_id": f"{request_id}:generate",
        "overrides": gen_overrides,
    }
    if result.prompt_run_id:
        gen_command["prompt_run_id"] = result.prompt_run_id

    # Delegate enqueue/queue/ack to the shared generate handler (no prompt_generated).
    await handle_generate_command(
        ws,
        context,
        clients,
        gen_command,
        start_generation_runner=start_generation_runner,
    )


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


async def _rollback_storyteller_command(
    ws: WebSocket,
    context: WebSessionContext,
    command: dict[str, Any],
    reason: str,
) -> None:
    """Roll the Storyteller cycle back when a stamped page-1 command fails to enqueue
    (returned not-ok OR raised) — otherwise the freeze + Auto Gen stay armed with nothing
    running."""
    run_id = str((command.get("overrides") or {}).get("event_stream_run_id") or "")
    if run_id and context._storyteller_service().is_running(run_id):
        policy = context._storyteller_service().fail(run_id, reason)
        await _send_json(ws, context._storyteller_service().state())
        for message in policy.get("messages", []):
            await _send_json(ws, message)


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
        try:
            result = await enqueue_generation_request(context, command)
        except Exception as exc:
            await _send_json(ws, {
                "type": "toast",
                "level": "error",
                "message": f"Generation enqueue failed: {exc}",
            })
            await _rollback_storyteller_command(ws, context, command, str(exc))
            continue
        await _send_json(ws, result.websocket_payload())
        if not result.ok:
            await _send_json(ws, {
                "type": "toast",
                "level": "error",
                "message": result.blocked_reason,
            })
            await _rollback_storyteller_command(ws, context, command, result.blocked_reason)
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


def _should_auto_generate_after_random(
    context: WebSessionContext,
    command: dict[str, Any],
    overrides: dict[str, Any] | None,
) -> bool:
    if command.get("respect_naia_autogen", True) is False:
        return False
    if command.get("force_naia_skip_generate") is True:
        return False
    request_overrides = overrides if isinstance(overrides, dict) else {}
    # 자동 사이클(Storyteller run)이 도는 동안의 수동 랜덤은 허용하되(스텝 전진/박스 갱신),
    # 생성 연쇄는 하지 않는다 — 스토리 루프와 경쟁하는 평행 auto-gen 루프 방지.
    # 수동 진행 모드(사이클 미실행)와 스토리 페이지 자체는 영향 없음.
    if not request_overrides.get("_storyteller_page"):
        try:
            if context._storyteller_service().is_running():
                return False
        except Exception:
            pass
    requested = request_overrides.get("auto_generate", context.get_options().get("auto_generate", False))
    return bool(context._coerce_bool(requested))


async def _maybe_enqueue_random_auto_generation(
    context: WebSessionContext,
    *,
    result,
    command: dict[str, Any],
    overrides: dict[str, Any] | None,
    request_id: str,
    queue_source: str,
):
    if not result.success:
        return None
    if not _should_auto_generate_after_random(context, command, overrides):
        return None

    generation_overrides = dict(overrides) if isinstance(overrides, dict) else {}
    generation_overrides["auto_generate"] = True
    generation_overrides["_remote_queue_source"] = queue_source
    generation_overrides["_remote_queue_label"] = queue_source
    # 첫 홉(수동 Random → Auto Gen 시작) 해상도 처리를 continuation 루프(generation_runner)와 일치시킨다:
    # Rnd Res 가 켜져 있으면 먼저 새 랜덤 해상도를 굴려 두고(폴백), AutoRes(detected)가 나오면 그 값으로
    # 덮어쓴다(AutoRes 우선 = '3→1 fallback'). 이게 없으면 dims 없는 소스 행에서 random 폴백이 걸리지
    # 않아 직전 고정 해상도가 그대로 박힌다(첫홉 갭). _reroll 은 random_resolution 이 꺼져 있으면 no-op.
    from app.backend.server.generation_runner import _reroll_random_resolution
    _reroll_random_resolution(context, generation_overrides)
    if result.detected_resolution:
        width, height = result.detected_resolution
        generation_overrides["width"] = width
        generation_overrides["height"] = height
        generation_overrides["resolution"] = f"{width} x {height}"

    generation_command: dict[str, Any] = {
        "type": "generate",
        "prompt": result.prompt,
        "negative_prompt": context.negative_prompt_text,
        "request_id": f"{request_id}:generate" if request_id else f"random-{uuid.uuid4().hex}:generate",
        "overrides": generation_overrides,
    }
    if result.prompt_run_id:
        generation_command["prompt_run_id"] = result.prompt_run_id

    dispatch = await enqueue_generation_request(context, generation_command)
    return dispatch


def register_generation_rest_routes(
    app: FastAPI,
    context: WebSessionContext,
    *,
    clients: set[WebSocket],
    start_generation_runner: GenerationRunnerStarter,
) -> None:
    """Register future01-compatible REST generation entrypoints.

    The canonical Remote Web path is websocket based, but older Web Session
    tools and ComfyUI integrations still call these REST routes.
    """

    @app.post("/api/generate")
    async def api_generate(req: Request):
        command = await _request_json_payload(req)
        command = dict(command)
        command.setdefault("type", "generate")
        await persist_prompt_engineering_settings(context)
        result = await enqueue_generation_request(context, command)
        payload = result.websocket_payload()
        if not result.ok:
            return JSONResponse(payload, status_code=400)
        if context.headless_generation_execute_enabled:
            start_generation_runner(context, clients)
        return {
            "status": "generation_requested",
            **payload,
            "queue": context.queue_state_payload(),
        }

    @app.post("/api/random")
    async def api_random(req: Request):
        command = await _request_json_payload(req)
        overrides = command.get("overrides") if isinstance(command.get("overrides"), dict) else None
        request_id = str(command.get("random_request_id") or command.get("requestId") or "")
        active_ratings = _active_ratings_from_command(command) or context.get_active_ratings()
        invalidate_auto_gen_prefetch(context)  # REST random도 풀 advance → 예약 무효화
        # WS Random과 동일하게 영속 활성 태그필터를 백엔드가 재조립(재시작/가져오기 후 REST random 이
        # 필터를 무시하고 전체 풀에서 뽑는 것 방지 — Codex F3). no-op if already assigned.
        from app.backend.server.search_runtime import reconstruct_active_tag_filter
        await asyncio.to_thread(reconstruct_active_tag_filter, context)
        result = await asyncio.to_thread(
            random_service(context).generate,
            active_ratings=active_ratings,
            overrides=overrides,
            random_request_id=request_id,
        )
        # WebSocket Random과 동일하게 Ollama Auto Boost 적용(토글 OFF면 no-op) — Codex round2 관찰.
        await apply_ollama_auto_boost(context, result)
        await persist_prompt_engineering_settings(context)
        # Use Vibe 인코딩(2 Anlas) 발생 시 잔액 차감 즉시 반영(REST random 경로).
        await broadcast_anlas_if_vibe_encoded(context, clients)
        payload = result.websocket_payload()
        if not result.success:
            return JSONResponse(payload, status_code=400)
        dispatch = await _maybe_enqueue_random_auto_generation(
            context,
            result=result,
            command=command,
            overrides=overrides,
            request_id=request_id,
            queue_source="Random",
        )
        if dispatch and dispatch.ok and context.headless_generation_execute_enabled:
            start_generation_runner(context, clients)
        return {
            "status": "random_generation_requested",
            "naia_started_generation": bool(dispatch and dispatch.ok),
            "generation": dispatch.websocket_payload() if dispatch is not None else None,
            **payload,
            "extra_messages": result.extra_messages,
        }

    @app.post("/api/comfyui/random")
    async def api_comfyui_random(req: Request):
        command = await _request_json_payload(req)
        if command.get("overrides") is not None and not isinstance(command.get("overrides"), dict):
            return JSONResponse({"error": "overrides must be a dict"}, status_code=400)
        if command.get("peng_override") is not None and not isinstance(command.get("peng_override"), dict):
            return JSONResponse({"error": "peng_override must be a dict"}, status_code=400)
        overrides = command.get("overrides") if isinstance(command.get("overrides"), dict) else {}
        overrides = dict(overrides)
        respect_autogen = command.get("respect_naia_autogen", True) is not False
        force_skip = command.get("force_naia_skip_generate") is True
        requested_auto_generate = overrides.get("auto_generate", context.get_options().get("auto_generate", False))
        will_naia_generate = bool(context._coerce_bool(requested_auto_generate) and respect_autogen and not force_skip)
        overrides["auto_generate"] = will_naia_generate
        peng_override = command.get("peng_override") if isinstance(command.get("peng_override"), dict) else None
        request_id = str(command.get("request_id") or command.get("random_request_id") or command.get("requestId") or uuid.uuid4())
        try:
            timeout = float(command.get("timeout") or 30)
        except (TypeError, ValueError):
            timeout = 30.0
        timeout = min(max(timeout, 1.0), 300.0)
        active_ratings = _active_ratings_from_command(command) or context.get_active_ratings()
        previous_peng_override = getattr(context, "session_p_eng_override", None)
        if peng_override is not None:
            context.session_p_eng_override = peng_override
        invalidate_auto_gen_prefetch(context)  # 이 REST random도 풀 advance → 예약 무효화
        try:
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        random_service(context).generate,
                        active_ratings=active_ratings,
                        overrides=overrides,
                        random_request_id=request_id,
                    ),
                    timeout=timeout,
                )
            finally:
                if peng_override is not None and getattr(context, "session_p_eng_override", None) is peng_override:
                    context.session_p_eng_override = previous_peng_override
        except asyncio.TimeoutError:
            return JSONResponse({
                "ok": False,
                "error": "Timed out waiting for random prompt generation",
                "request_id": request_id,
            }, status_code=504)
        await persist_prompt_engineering_settings(context)
        payload = result.websocket_payload()
        if not result.success:
            return JSONResponse(payload, status_code=400)
        # Guarantee a top-level resolution (ports future01 bb47537) so the external
        # NAIA Bridge ComfyUI client never sees a missing width/height, and feed the
        # same dims into NAIA's own auto-generation so it matches the response.
        res_w, res_h, res_source = _resolve_comfyui_response_resolution(result, overrides)
        if res_w and res_h:
            # Authoritative for this ComfyUI path: res_w/res_h already honors a valid
            # explicit override (the resolver returns it first), so assigning here keeps
            # NAIA's auto-generation in lock-step with the response and overwrites any
            # invalid/nonpositive width/height the caller may have sent.
            overrides["width"] = res_w
            overrides["height"] = res_h
            overrides["resolution"] = f"{res_w} x {res_h}"
        generation_result = await _maybe_enqueue_random_auto_generation(
            context,
            result=result,
            command=command,
            overrides=overrides,
            request_id=request_id,
            queue_source="ComfyUI Random",
        )
        generation_payload = generation_result.websocket_payload() if generation_result is not None else None
        will_naia_generate = bool(generation_result and generation_result.ok)
        if will_naia_generate and context.headless_generation_execute_enabled:
            start_generation_runner(context, clients)
        # 조건부 규칙(neg 타겟)이 이 프롬프트 런에 기록한 네거티브 조작을 응답 네거티브에
        # 병합한다. 외부 NAIA Bridge ComfyUI 클라이언트는 enqueue 합류점을 지나지 않고
        # 이 응답의 negative_prompt로 자기 서버에서 생성하므로, 병합이 없으면 조건부
        # 네거티브가 누락된다(NAIA 자체 auto-gen은 enqueue에서 이미 병합되어 일치한다).
        # context.negative_prompt_text(사용자 박스)는 오염하지 않고 응답 문자열만 병합.
        bridge_negative = generation_service(context).merge_conditional_negative(
            context.negative_prompt_text, result.prompt_run_id
        )
        response = {
            "ok": True,
            "status": "prompt_generated",
            "request_id": request_id,
            "prompt": result.prompt,
            "naia_started_generation": will_naia_generate,
            "generation": generation_payload,
            **payload,
            "extra_messages": result.extra_messages,
        }
        # 조건부 병합된 브릿지 네거티브는 **payload 이후에 박아 권위적으로 만든다 — 향후
        # websocket_payload에 negative_prompt가 추가돼도 병합본을 덮어쓰지 못하게 잠근다.
        response["negative_prompt"] = bridge_negative
        # Top-level resolution contract (set AFTER **payload so it is authoritative;
        # the nested detected_resolution from payload is preserved for Remote Web).
        if res_w and res_h:
            response["width"] = res_w
            response["height"] = res_h
            response["resolution"] = f"{res_w} x {res_h}"
            response["resolution_source"] = res_source
        return response

    @app.get("/api/comfyui/health")
    async def api_comfyui_health():
        return {
            "ok": True,
            "api_mode": context.get_api_mode(),
            "is_generating": bool(context.is_generating or getattr(context, "headless_generation_runner_active", False)),
            "queue": context.queue_state_payload(),
            "runtime": "web",
        }
