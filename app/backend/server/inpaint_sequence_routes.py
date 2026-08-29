"""I.Sequence (Inpaint Sequence) REST — /api/inpaint-sequence/*

⚠️ 이것은 ``sequence_preset_routes`` 의 **생성 3종 복제본**이다(사용자 지정 2026-08-25).
   검색·다운로드 REST 와 락·유틸은 원본에서 import 해 **공유**한다 - 같은 이벤트
   데이터셋을 서빙하므로 띄울 이유가 없다. 따로 가지는 것은 런 상태와 생성 경로뿐이다.

이번 단계는 **복제까지**다 - 프레임은 아직 원본과 똑같이 독립 t2i 로 나간다.
목표는 직전 이미지를 캔버스에 붙이고 빈 절반만 inpaint 로 메꾸는 캔버스 연쇄이며
(원본 `C:/VNR/NAIA2.0/tabs/turbo_event_sequence` 의 방식), 그 교체는 다음 단계에서 한다.

⚠️ ``_SEQ_LOCK`` 은 원본과 **같은 락을 쓴다.** 따로 가지면 둘이 동시에 freeze 를
   무장해 서로의 스냅샷을 짓밟는다. 실행 자체의 상호 배제는 `guard_can_start` 가 맡는다.
"""
from __future__ import annotations

import asyncio
import random as _rng
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.backend.server.sequence_preset_routes import (
    _SEQ_LOCK,
    _coerce_dim,
    _generation_service,
    _random_service,
    _read_json,
    _roll_random_resolution,
    sequence_preset_service,
)
from core.web_session_context import WebSessionContext
from utils.sequence_canvas_chain import SAMPLE_SIZE

AsyncRunner = Callable[..., Awaitable[Any]]
JsonBroadcaster = Callable[[set[Any], dict[str, Any]], Awaitable[None]]
GenerationRunnerStarter = Callable[[WebSessionContext, set[Any]], None]


async def _do_round(session_context: WebSessionContext, thread_run, *, group_id: int, run_id: str,
                    fix_seed: bool = True, fix_resolution: bool = True, use_vibe: bool = False,
                    query: dict[str, Any] | None = None):
    """한 이벤트 그룹의 전 프레임을 fresh freeze 로 조립·baking·enqueue. _SEQ_LOCK 보유 가정.
    라운드마다 새 정체성(아티스트/캐릭터 와일드카드 롤)·새 시드(Seed Fixed면 사용자값)·해상도.
    정체성은 커맨드 params 에 baking 되어 freeze 해제(큐 드레인) 후에도 유지된다. 반환 (enqueued, total).

    Vibe 사용(``use_vibe``, NAI 전용): 라운드의 첫 OK 프레임이 '마지막이 아닐 때'(OK ≥ 2) 그
    프레임에 캡처 stamp(``inpaint_sequence_vibe_capture``=run_id)를 단다 — 러너가 그 첫 이미지 생성 완료
    후 인코딩(2 Anlas)해 이후 프레임에 임시 vibe 로 주입한다(이벤트 스트림 Use Vibe 메커니즘의
    시퀀스 포팅). enqueue 시점엔 인코딩이 없으므로 주입은 러너의 실행 시점에 이뤄진다."""
    from core.event_tree import LegacyStoryNodeSpec

    random = _random_service(session_context)
    generation = _generation_service(session_context)
    active_ratings = session_context.get_active_ratings()
    api_mode = session_context.get_api_mode()
    # 비NAI 에서는 인코딩/주입 자체를 수행하지 않는다(생성 단계 silent 차단) — 캡처 stamp 미부착.
    vibe_enabled = bool(use_vibe) and str(api_mode or "").upper() == "NAI"

    sources = await thread_run(
        sequence_preset_service(session_context).generation_sources, {"groupId": group_id}
    )
    total = sources["total"]
    enqueued: list[dict[str, Any]] = []

    # 시드(첫 프레임 기준, 라운드 단위 고정): Seed Fixed면 그 값, 아니면 라운드마다 새로 1회 추첨.
    user_seed_fixed = session_context._coerce_bool(session_context.remote_params.get("seed_fixed", False))
    raw_seed = session_context.remote_params.get("seed", "")
    try:
        user_seed = int(float(raw_seed)) if str(raw_seed).strip() != "" else None
    except (TypeError, ValueError):
        user_seed = None
    pinned_seed = user_seed if (user_seed_fixed and user_seed is not None and user_seed >= 0) \
        else _rng.randint(0, 9_999_999_999)
    # 해상도(라운드 단위 고정): Rnd Res 면 라운드마다 1회 추첨(req5 새 해상도), 아니면 세션 값.
    fixed_w = _coerce_dim(session_context.remote_params.get("width"))
    fixed_h = _coerce_dim(session_context.remote_params.get("height"))
    if session_context._coerce_bool(session_context.remote_params.get("random_resolution", False)):
        rw, rh = _roll_random_resolution(session_context)
        if rw and rh:
            fixed_w, fixed_h = rw, rh
    # 모델(라운드 단위 고정): api_mode 처럼 라운드 시작 시 1회 캡처해 전 프레임에 baking 한다 —
    # 조립/enqueue 가 프레임별 async 라 도중에 사용자가 모델을 바꾸면 enqueue 가 그때그때의 live
    # remote_params 를 복사해 한 라운드에 모델이 섞일 수 있다. 라운드 정체성 일관성 + Vibe 사용의
    # 캡처/주입 모델 일치를 위해 모델도 고정한다(Codex R2). _current_model_key() 는 remote_params
    # ['model'] 또는 기본 'NAID4.5F'(api_service 기본과 동일)를 돌려주므로 항상 구체값 → 모델
    # 미설정 시작에도 무조건 baking 해 라운드 내 드리프트를 차단한다(Codex R3).
    round_model = session_context._current_model_key()

    # fresh freeze 무장(라운드마다 새 캡처). 캡처 실패 시 stop 후 재던진다.
    event_stream = session_context._create_event_stream_runtime()
    event_stream.start_linear(
        [LegacyStoryNodeSpec(node_id="inpaint_sequence.freeze", name="I.Sequence")], run_id=run_id
    )
    try:
        event_stream.ensure_freeze_snapshot()
        frozen_chars = event_stream.get_frozen_character_params()
    except Exception:
        try:
            event_stream.stop()
        except Exception:
            pass
        raise

    # 연쇄 방향(컷이 이어 붙는 축). 원본과 같은 이름을 쓴다 - horizontal = 캔버스가
    # 세로로 길고 컷이 위->아래로 이어진다.
    _q = query if isinstance(query, dict) else {}
    direction = "vertical" if str(_q.get("direction") or "").lower() == "vertical" else "horizontal"

    prev_prompt: str | None = None   # 라운드 내 직전 enqueue 프롬프트(연속 중복 skip용)
    # 조립(assemble)과 enqueue 를 분리한다 — 첫 OK 프레임이 '마지막이 아닌지'(OK ≥ 2)를 알아야
    # Vibe 캡처 stamp 를 달지 말지 정할 수 있기 때문(루프 도중엔 이후 OK 프레임 존재를 모름).
    # enqueued 는 idx 순서를 유지(실패/중복은 즉시, OK 는 enqueue 후 placeholder 를 채움).
    pending: list[dict[str, Any]] = []   # enqueue 대기 OK 프레임 {pos, command, idx, prompt}
    try:
        for source in sources["sources"]:
            idx = source["index"]
            try:
                source_row = source["sourceRow"]
                request_id = f"{run_id[-12:]}-{idx}"
                assembled = await thread_run(
                    random.generate_from_source_row,
                    source_row,
                    active_ratings=active_ratings,
                    random_request_id=request_id,
                    source="inpaint_sequence",
                    update_context=False,
                )
                if not assembled.success:
                    enqueued.append({"index": idx, "ok": False,
                                     "error": assembled.error or "assembly failed"})
                    continue
                # ⚠️ **중복 프롬프트 skip 을 하지 않는다(2026-08-28).**
                #
                # 예전에는 "시드 고정 + 직전과 같은 프롬프트 = 같은 시드/해상도라 동일
                # 이미지" 라는 근거로 걸렀다. **t2i 시절의 논리다.** 캔버스 연쇄에서는
                # 컷마다 **입력 캔버스가 다르다**(직전 컷의 결과가 절반에 붙는다) -
                # 같은 프롬프트·같은 시드라도 결과가 달라진다.
                #
                # 그대로 두면 조용히 시퀀스를 잘라먹는다. 라이브 실측(2026-08-28):
                # 3컷 이벤트가 "1컷 생성 큐 등록 (중복 2컷 생략)" 으로 한 컷이 됐다.
                # 사용자는 3컷을 골랐는데 1컷을 받는다.
                #
                # `prev_prompt` 는 더 쓰지 않지만 아래 흐름을 건드리지 않으려 유지한다.
                prev_prompt = assembled.prompt
                overrides: dict[str, Any] = {
                    "input": assembled.prompt,
                    "_raw_input": assembled.prompt,
                    "_source_row_data": dict(source_row),
                    "_source_name": request_id,
                    "_remote_queue_source": "InpaintSequence",
                    "_remote_queue_label": "inpaint_sequence",
                    "inpaint_sequence_request": True,
                    "inpaint_sequence_request_id": request_id,
                    "inpaint_sequence_group_id": str(group_id),
                    "inpaint_sequence_frame": f"{idx + 1}/{total}",
                    # Auto Gen 연속 바인딩 키 — 러너가 이 stamp 로 라운드 완료를 카운트한다.
                    "inpaint_sequence_run_id": run_id,
                }
                # 모델 고정(라운드 단위): 전 프레임 동일 모델 → 정체성 일관 + Vibe 캡처/주입 모델 일치.
                overrides["model"] = round_model
                # 고정 토글(하단 UI): SEED 고정 시 라운드 단위 시드 박기, 해상도 고정 시 width/height
                # 박고 per-frame auto-fit 차단. 미체크면 기본 동작(프레임별 시드/해상도)에 맡긴다.
                if fix_seed:
                    overrides["seed"] = pinned_seed
                    overrides["seed_fixed"] = True
                # ⚠️ **해상도는 연쇄가 소유한다.** 첫 컷은 SAMPLE, 이어지는 컷은 CANVAS
                #    (정확히 두 배)여야 붙인 절반과 생성 절반의 치수가 맞는다. 사용자의
                #    고정 해상도를 여기서 쓰면 캔버스 기하가 깨져 잘라낸 컷이 밀린다.
                #    `fixed_w/h` 는 그대로 두되(다음 라운드 추첨 등 다른 쓰임) 프레임에는
                #    싣지 않는다.
                overrides["auto_fit_resolution"] = False
                overrides["width"], overrides["height"] = SAMPLE_SIZE[direction]
                overrides["resolution"] = f"{overrides['width']} x {overrides['height']}"
                if frozen_chars and frozen_chars.get("characters"):
                    chars = list(frozen_chars.get("characters") or [])
                    ucs = list(frozen_chars.get("uc") or [])
                    ucs = (ucs + [""] * len(chars))[:len(chars)]
                    overrides["characters"] = chars
                    overrides["uc"] = ucs
                    positions = frozen_chars.get("character_positions") or []
                    if positions:
                        overrides["character_positions"] = list(positions)
                command = {
                    "type": "generate",
                    "api_mode": api_mode,
                    "prompt": assembled.prompt,
                    "negative_prompt": session_context.negative_prompt_text,
                    "overrides": overrides,
                }
                if assembled.prompt_run_id:
                    command["prompt_run_id"] = assembled.prompt_run_id
                pos = len(enqueued)
                enqueued.append({"index": idx, "ok": False, "prompt": assembled.prompt})  # placeholder
                pending.append({"pos": pos, "command": command, "idx": idx, "prompt": assembled.prompt})
            except Exception as exc:  # 프레임 단위 격리
                enqueued.append({"index": idx, "ok": False, "error": f"frame error: {exc}"})
        # Vibe 사용: 첫 OK 프레임이 '마지막이 아닐 때'(OK ≥ 2)만 캡처 stamp. OK 1개면 적용 대상이
        # 없으므로 인코딩하지 않는다(Anlas 낭비 방지 — 사용자 사양 "자신이 큐의 마지막이 아닐 때").
        if vibe_enabled and len(pending) >= 2:
            pending[0]["command"]["overrides"]["inpaint_sequence_vibe_capture"] = run_id
        # ⚠️ **첫 컷 하나만 넣는다.** 캔버스 연쇄는 직전 컷의 *결과 이미지*가 있어야
        #    다음 캔버스를 만들 수 있다 - 전 프레임을 한 번에 넣던 t2i 시절 방식으로는
        #    성립하지 않는다. 나머지는 런 상태에 재워 두고 러너가 완료마다 한 장씩
        #    이어 붙인다(`_chain_inpaint_sequence_frame`).
        for item in pending[1:]:
            item["command"]["overrides"]["inpaint_sequence_canvas"] = True
            # 자를 방향도 함께 싣는다. 저장 직전(`_isq_crop_result`)이 이 값을 보고
            # 새 절반을 남긴다 - 런 상태를 못 보는 자리라 프레임에 실어 보내야 한다.
            item["command"]["overrides"]["inpaint_sequence_direction"] = direction
            enqueued[item["pos"]] = {
                "index": item["idx"], "ok": True, "prompt": item["prompt"],
                "requestId": "", "error": "", "chained": True,
            }
        if pending:
            head = pending[0]
            try:
                dispatch = await thread_run(generation.enqueue_remote_request, head["command"])
                enqueued[head["pos"]] = {
                    "index": head["idx"], "ok": bool(dispatch.ok), "prompt": head["prompt"],
                    "requestId": getattr(dispatch.request, "request_id", "") if dispatch.ok else "",
                    "error": "" if dispatch.ok else (dispatch.blocked_reason or "enqueue blocked"),
                }
                if not dispatch.ok:
                    # 첫 컷이 막히면 연쇄가 시작될 수 없다 - 대기분도 통째로 접는다.
                    for item in pending[1:]:
                        enqueued[item["pos"]]["ok"] = False
                        enqueued[item["pos"]]["error"] = "first frame blocked"
                    pending = pending[:1]
            except Exception as exc:
                enqueued[head["pos"]] = {"index": head["idx"], "ok": False,
                                         "prompt": head["prompt"], "error": f"enqueue error: {exc}"}
                for item in pending[1:]:
                    enqueued[item["pos"]]["ok"] = False
                    enqueued[item["pos"]]["error"] = "first frame failed"
                pending = pending[:1]
        chained_frames = [
            {"command": item["command"], "index": item["idx"], "prompt": item["prompt"]}
            for item in pending[1:]
        ]
    finally:
        try:
            event_stream.stop()
        except Exception:
            pass
    return enqueued, total, pinned_seed, chained_frames, direction


async def start_inpaint_sequence_run(
    session_context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
    clients: set[Any],
    broadcast_json: JsonBroadcaster,
    start_generation_runner: GenerationRunnerStarter,
    query: dict[str, Any],
    explicit_group_id: Any,
    auto_gen: bool,
):
    """Random(랜덤 그룹) 또는 Generate(특정 그룹) 진입점. 가드→그룹 결정→fresh freeze enqueue→run 시작.
    Auto Gen ON 이면 러너가 라운드 완료마다 다음 랜덤 그룹으로 연속한다(continue_sequence_run)."""
    svc = session_context._inpaint_sequence_run_service()
    async with _SEQ_LOCK:
        guard = svc.guard_can_start()
        if guard:
            return JSONResponse({"error": guard}, status_code=409)
        if explicit_group_id is not None:
            group_id = int(explicit_group_id)
        else:
            pick = await run_in_thread(
                sequence_preset_service(session_context).pick_random_group, query
            )
            if not pick.get("ok") or pick.get("groupId") is None:
                return JSONResponse(
                    {"error": pick.get("error") or "no matching groups"}, status_code=404
                )
            group_id = int(pick["groupId"])
        run_id = svc.new_run_id()
        # REST 하드닝: 문자열 "false"/"0" 등도 정확히 해석(_coerce_bool) — UI는 실제 boolean 을
        # 보내지만 외부 REST 호출 방어(Codex LOW).
        coerce = session_context._coerce_bool
        fix_seed = coerce(query.get("fixSeed", True))
        fix_resolution = coerce(query.get("fixResolution", True))
        use_vibe = coerce(query.get("useVibe", False))
        try:
            enqueued, total, pinned_seed, chained, direction = await _do_round(
                session_context, run_in_thread, group_id=group_id, run_id=run_id,
                fix_seed=fix_seed, fix_resolution=fix_resolution, use_vibe=use_vibe,
                query=query,
            )
        except Exception as exc:
            return JSONResponse({"error": f"Sequence freeze/assemble failed: {exc}"}, status_code=500)
        ok_count = sum(1 for e in enqueued if e["ok"])
        if ok_count:
            # total_frames = 실제 enqueue 된 프레임 수(ok_count) — 컨트롤러는 '완료'를 세므로
            # 일부 프레임이 실패하면 sources total 이 아니라 enqueue 된 수로 라운드 완결을 판정한다.
            svc.begin(run_id=run_id, query=query, group_id=group_id,
                      total_frames=ok_count, auto_gen=auto_gen, use_vibe=use_vibe,
                      pending_frames=chained, direction=direction)
    if ok_count and session_context.headless_generation_execute_enabled:
        start_generation_runner(session_context, clients)
    try:
        await broadcast_json(clients, session_context._inpaint_sequence_run_module_state())
    except Exception:
        pass
    return {
        "ok": ok_count > 0,
        "status": "inpaint_sequence_run_started",
        "groupId": group_id,
        "runId": run_id if ok_count else "",
        "total": total,
        "enqueued": ok_count,
        "seed": pinned_seed,
        "autoGen": bool(auto_gen),
        "frames": enqueued,
    }


async def continue_sequence_run(session_context: WebSessionContext, clients, run_id: str,
                                broadcast_json: JsonBroadcaster) -> bool:
    """러너 호출: 라운드 완료 후 다음 랜덤 그룹을 fresh freeze 로 enqueue. True=다음 라운드 시작됨.
    enqueue 는 asyncio.to_thread 로(러너 컨텍스트엔 route 의 run_in_thread 가 없음 — Codex #3)."""
    svc = session_context._inpaint_sequence_run_service()
    query = svc.query(run_id)
    last = svc.last_group_id(run_id)
    pick = await asyncio.to_thread(
        sequence_preset_service(session_context).pick_random_group, query, exclude_group_id=last
    )
    if not pick.get("ok") or pick.get("groupId") is None:
        return False
    group_id = int(pick["groupId"])
    coerce = session_context._coerce_bool
    fix_seed = coerce(query.get("fixSeed", True))
    fix_resolution = coerce(query.get("fixResolution", True))
    use_vibe = coerce(query.get("useVibe", False))
    async with _SEQ_LOCK:
        if not svc.is_running(run_id):
            return False
        try:
            enqueued, _total, _seed, chained, direction = await _do_round(
                session_context, asyncio.to_thread, group_id=group_id, run_id=run_id,
                fix_seed=fix_seed, fix_resolution=fix_resolution, use_vibe=use_vibe,
                query=query,
            )
        except Exception:
            return False
        ok_count = sum(1 for e in enqueued if e["ok"])
        if not ok_count:
            return False
        svc.begin_round(run_id, group_id=group_id, total_frames=ok_count,
                        pending_frames=chained, direction=direction)
    try:
        await broadcast_json(clients, session_context._inpaint_sequence_run_module_state())
    except Exception:
        pass
    return True


def register_inpaint_sequence_routes(
    app: FastAPI,
    session_context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
    clients: set[Any],
    broadcast_json: JsonBroadcaster,
    start_generation_runner: GenerationRunnerStarter,
) -> None:
    """생성 3종만 등록한다. status/search/sequence/download 은 원본 엔드포인트를 그대로
    쓴다(같은 데이터셋) - 프런트가 `/api/sequence-preset/*` 을 그대로 호출한다."""

    @app.post("/api/inpaint-sequence/generate")
    async def api_inpaint_sequence_generate(req: Request):
        payload = await _read_json(req)
        group_id = payload.get("groupId")
        if group_id is None:
            return JSONResponse({"error": "groupId is required."}, status_code=400)
        try:
            gid = int(group_id)
        except (TypeError, ValueError):
            return JSONResponse({"error": "groupId is invalid."}, status_code=400)
        auto_gen = session_context._coerce_bool(
            session_context.get_options().get("auto_generate", False)
        )
        try:
            return await start_inpaint_sequence_run(
                session_context,
                run_in_thread=run_in_thread,
                clients=clients,
                broadcast_json=broadcast_json,
                start_generation_runner=start_generation_runner,
                query=payload,
                explicit_group_id=gid,
                auto_gen=auto_gen,
            )
        except Exception as exc:
            return JSONResponse({"error": f"I.Sequence generate failed: {exc}"}, status_code=500)

    @app.post("/api/inpaint-sequence/random-generate")
    async def api_inpaint_sequence_random_generate(req: Request):
        payload = await _read_json(req)
        auto_gen = session_context._coerce_bool(
            session_context.get_options().get("auto_generate", False)
        )
        try:
            return await start_inpaint_sequence_run(
                session_context,
                run_in_thread=run_in_thread,
                clients=clients,
                broadcast_json=broadcast_json,
                start_generation_runner=start_generation_runner,
                query=payload,
                explicit_group_id=None,
                auto_gen=auto_gen,
            )
        except Exception as exc:
            return JSONResponse(
                {"error": f"I.Sequence random-generate failed: {exc}"}, status_code=500
            )

    @app.post("/api/inpaint-sequence/stop")
    async def api_inpaint_sequence_stop():
        try:
            state = session_context._inpaint_sequence_run_service().stop()
            extra = state.pop("_headless_extra_messages", []) if isinstance(state, dict) else []
            await broadcast_json(clients, session_context._inpaint_sequence_run_module_state())
            for message in extra:
                await broadcast_json(clients, message)
            return state
        except Exception as exc:
            return JSONResponse({"error": f"I.Sequence stop failed: {exc}"}, status_code=500)
