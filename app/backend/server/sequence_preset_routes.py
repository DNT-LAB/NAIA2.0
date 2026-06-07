"""Sequence REST — /api/sequence-preset/*

검색: status / search(태그 include/exclude·rating·프레임수) / sequence(그룹 펼침).
생성: generate — 그룹의 프레임별 source_row 를 Event Preset / Refine 과 동일한
generate_from_source_row(update_context=False) 로 PE 경유 조립한 뒤, _source_row_data 를
carrying 해 생성 큐에 순차 enqueue (메인 프롬프트 박스 비오염, prompt_generated 미발행).
정체성(artist/character)은 PE·캐릭터 파이프라인이 공급, scene 만 프레임별로 바뀐다.

정체성 동결(사용자 결정): NAI 캐릭터 프롬프트 + 와일드카드가 프레임마다 흔들리지 않도록
Event Stream(Storyteller) freeze 메커니즘을 조립 동안만 무장한다 — start_linear +
ensure_freeze_snapshot 로 PE(아티스트/와일드카드)·캐릭터를 1회 동결한 뒤, 동결 캐릭터는
프레임 커맨드 params 에 baking(EarlyBinding 경유)하고 freeze 는 enqueue 후 즉시 stop 한다.
덕분에 큐 드레인(freeze off) 후에도 정체성이 유지되며 Storyteller 컨트롤러와는 비커플링
(자기완결형) 이다. 시드·해상도는 첫 이미지 기준으로 전 프레임 고정. 공유 EventStreamRuntime
충돌(Storyteller/수동/Automation 실행 중)이면 거부한다. Dev0714 EventSearcher 모델의 헤드리스 포팅.
"""
from __future__ import annotations

import asyncio
import random as _rng
import uuid
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.sequence_preset_service import SequencePresetService
from core.web_session_context import WebSessionContext

AsyncRunner = Callable[..., Awaitable[Any]]
JsonBroadcaster = Callable[[set[Any], dict[str, Any]], Awaitable[None]]
GenerationRunnerStarter = Callable[[WebSessionContext, set[Any]], None]


def sequence_preset_service(context: WebSessionContext) -> SequencePresetService:
    service = getattr(context, "sequence_preset_service", None)
    if service is None:
        data_root = None
        runtime_paths = getattr(context, "runtime_paths", None)
        if runtime_paths is not None:
            data_root = runtime_paths.data_dir
        service = SequencePresetService(context.repo_root, data_root=data_root)
        context.sequence_preset_service = service
    return service


def sequence_download_service(context: WebSessionContext):
    svc = getattr(context, "sequence_download_service", None)
    if svc is None:
        from core.sequence_download_service import SequenceDownloadService

        seq = sequence_preset_service(context)
        data_root = None
        runtime_paths = getattr(context, "runtime_paths", None)
        if runtime_paths is not None:
            data_root = runtime_paths.data_dir
        svc = SequenceDownloadService(
            context.repo_root, status_provider=seq.status,
            on_complete=seq.reload, data_root=data_root,
        )
        context.sequence_download_service = svc
    return svc


def _generation_service(context: WebSessionContext):
    from app.backend.server.generation_commands import generation_service

    return generation_service(context)


def _random_service(context: WebSessionContext):
    from app.backend.server.generation_commands import random_service

    return random_service(context)


async def _read_json(req: Request) -> dict[str, Any]:
    try:
        payload = await req.json()
    except Exception:
        payload = {}
    return payload if isinstance(payload, dict) else {}


# 시퀀스 생성 직렬화 락(프로세스 단위). freeze 무장/해제 + run 상태 갱신 구간을 라우트(Random/
# Generate)와 러너(Auto Gen 자동 연속)가 겹쳐 서로의 freeze 를 짓밟지 않도록 한다. 모듈 레벨이라
# 러너의 continue_sequence_run 도 같은 락을 공유한다(헤드리스 단일 세션).
_SEQ_LOCK = asyncio.Lock()


def _coerce_dim(value: Any) -> int | None:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _roll_random_resolution(session_context: WebSessionContext) -> tuple[int | None, int | None]:
    """Rnd Res 모집단(현재 모드 사용자 목록, 폴백=표준 1MP)에서 1회 추첨. 라운드마다 새 해상도용."""
    try:
        labels = list(session_context.resolution_options_for_mode())
    except Exception:
        labels = []
    if not labels:
        try:
            from core.resolution_utils import STANDARD_1MP_RESOLUTION_LABELS
            labels = list(STANDARD_1MP_RESOLUTION_LABELS)
        except Exception:
            labels = []
    if not labels:
        return (None, None)
    try:
        parts = str(_rng.choice(labels)).lower().replace("×", "x").split("x")
        if len(parts) == 2:
            w, h = int(parts[0].strip()), int(parts[1].strip())
            if w > 0 and h > 0:
                return (w, h)
    except (TypeError, ValueError):
        pass
    return (None, None)


async def _do_round(session_context: WebSessionContext, thread_run, *, group_id: int, run_id: str,
                    fix_seed: bool = True, fix_resolution: bool = True, use_vibe: bool = False):
    """한 이벤트 그룹의 전 프레임을 fresh freeze 로 조립·baking·enqueue. _SEQ_LOCK 보유 가정.
    라운드마다 새 정체성(아티스트/캐릭터 와일드카드 롤)·새 시드(Seed Fixed면 사용자값)·해상도.
    정체성은 커맨드 params 에 baking 되어 freeze 해제(큐 드레인) 후에도 유지된다. 반환 (enqueued, total).

    Vibe 사용(``use_vibe``, NAI 전용): 라운드의 첫 OK 프레임이 '마지막이 아닐 때'(OK ≥ 2) 그
    프레임에 캡처 stamp(``sequence_vibe_capture``=run_id)를 단다 — 러너가 그 첫 이미지 생성 완료
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
        [LegacyStoryNodeSpec(node_id="sequence.freeze", name="Sequence")], run_id=run_id
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
                    source="sequence_preset",
                    update_context=False,
                )
                if not assembled.success:
                    enqueued.append({"index": idx, "ok": False,
                                     "error": assembled.error or "assembly failed"})
                    continue
                # 라운드 내 직전 enqueue 프롬프트와 동일하면 skip. PE 태그 제거(작가/캐릭터/구도
                # 압축 등)로 인접 프레임이 같은 최종 프롬프트가 되는 케이스 — 시드 고정 시 같은
                # 시드/해상도라 동일 이미지다. skip 프레임은 ok=False+skipped 라 ok_count(=total_frames)
                # 에서 빠져 라운드 완결·다음 freeze 갱신이 정확하다(2행/마지막행 케이스 포함).
                # ※ 시드 미고정이면 프레임마다 시드가 달라 같은 프롬프트라도 다른 이미지 → dedup 안 함.
                if fix_seed and assembled.prompt == prev_prompt:
                    enqueued.append({"index": idx, "ok": False, "skipped": True,
                                     "prompt": assembled.prompt})
                    continue
                prev_prompt = assembled.prompt
                overrides: dict[str, Any] = {
                    "input": assembled.prompt,
                    "_raw_input": assembled.prompt,
                    "_source_row_data": dict(source_row),
                    "_source_name": request_id,
                    "_remote_queue_source": "SequencePreset",
                    "_remote_queue_label": "sequence_preset",
                    "sequence_preset_request": True,
                    "sequence_preset_request_id": request_id,
                    "sequence_preset_group_id": str(group_id),
                    "sequence_preset_frame": f"{idx + 1}/{total}",
                    # Auto Gen 연속 바인딩 키 — 러너가 이 stamp 로 라운드 완료를 카운트한다.
                    "sequence_run_id": run_id,
                }
                # 모델 고정(라운드 단위): 전 프레임 동일 모델 → 정체성 일관 + Vibe 캡처/주입 모델 일치.
                overrides["model"] = round_model
                # 고정 토글(하단 UI): SEED 고정 시 라운드 단위 시드 박기, 해상도 고정 시 width/height
                # 박고 per-frame auto-fit 차단. 미체크면 기본 동작(프레임별 시드/해상도)에 맡긴다.
                if fix_seed:
                    overrides["seed"] = pinned_seed
                    overrides["seed_fixed"] = True
                if fix_resolution:
                    overrides["auto_fit_resolution"] = False
                    if fixed_w:
                        overrides["width"] = fixed_w
                    if fixed_h:
                        overrides["height"] = fixed_h
                    if fixed_w and fixed_h:
                        overrides["resolution"] = f"{fixed_w} x {fixed_h}"
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
            pending[0]["command"]["overrides"]["sequence_vibe_capture"] = run_id
        # enqueue (idx 순서 유지). 첫 OK 프레임이 큐의 맨 앞 → 가장 먼저 생성·인코딩된다.
        for item in pending:
            try:
                dispatch = await thread_run(generation.enqueue_remote_request, item["command"])
                enqueued[item["pos"]] = {
                    "index": item["idx"], "ok": bool(dispatch.ok), "prompt": item["prompt"],
                    "requestId": getattr(dispatch.request, "request_id", "") if dispatch.ok else "",
                    "error": "" if dispatch.ok else (dispatch.blocked_reason or "enqueue blocked"),
                }
            except Exception as exc:
                enqueued[item["pos"]] = {"index": item["idx"], "ok": False,
                                         "prompt": item["prompt"], "error": f"enqueue error: {exc}"}
    finally:
        try:
            event_stream.stop()
        except Exception:
            pass
    return enqueued, total, pinned_seed


async def start_sequence_run(
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
    svc = session_context._sequence_run_service()
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
            enqueued, total, pinned_seed = await _do_round(
                session_context, run_in_thread, group_id=group_id, run_id=run_id,
                fix_seed=fix_seed, fix_resolution=fix_resolution, use_vibe=use_vibe,
            )
        except Exception as exc:
            return JSONResponse({"error": f"Sequence freeze/assemble failed: {exc}"}, status_code=500)
        ok_count = sum(1 for e in enqueued if e["ok"])
        if ok_count:
            # total_frames = 실제 enqueue 된 프레임 수(ok_count) — 컨트롤러는 '완료'를 세므로
            # 일부 프레임이 실패하면 sources total 이 아니라 enqueue 된 수로 라운드 완결을 판정한다.
            svc.begin(run_id=run_id, query=query, group_id=group_id,
                      total_frames=ok_count, auto_gen=auto_gen, use_vibe=use_vibe)
    if ok_count and session_context.headless_generation_execute_enabled:
        start_generation_runner(session_context, clients)
    try:
        await broadcast_json(clients, session_context._sequence_run_module_state())
    except Exception:
        pass
    return {
        "ok": ok_count > 0,
        "status": "sequence_run_started",
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
    svc = session_context._sequence_run_service()
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
            enqueued, _total, _seed = await _do_round(
                session_context, asyncio.to_thread, group_id=group_id, run_id=run_id,
                fix_seed=fix_seed, fix_resolution=fix_resolution, use_vibe=use_vibe,
            )
        except Exception:
            return False
        ok_count = sum(1 for e in enqueued if e["ok"])
        if not ok_count:
            return False
        svc.begin_round(run_id, group_id=group_id, total_frames=ok_count)
    try:
        await broadcast_json(clients, session_context._sequence_run_module_state())
    except Exception:
        pass
    return True


def register_sequence_preset_routes(
    app: FastAPI,
    session_context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
    clients: set[Any],
    broadcast_json: JsonBroadcaster,
    start_generation_runner: GenerationRunnerStarter,
) -> None:
    @app.get("/api/sequence-preset/status")
    async def api_sequence_preset_status():
        try:
            return await run_in_thread(sequence_preset_service(session_context).status)
        except Exception as exc:
            return JSONResponse(
                {"error": f"Sequence status failed: {exc}"}, status_code=500
            )

    @app.get("/api/sequence-preset/download/status")
    async def api_sequence_download_status():
        try:
            return await run_in_thread(sequence_download_service(session_context).snapshot)
        except Exception as exc:
            return JSONResponse({"error": f"download status failed: {exc}"}, status_code=500)

    @app.post("/api/sequence-preset/download/start")
    async def api_sequence_download_start():
        try:
            return await run_in_thread(sequence_download_service(session_context).start)
        except Exception as exc:
            return JSONResponse({"error": f"download start failed: {exc}"}, status_code=500)

    @app.post("/api/sequence-preset/download/cancel")
    async def api_sequence_download_cancel():
        try:
            return await run_in_thread(sequence_download_service(session_context).cancel)
        except Exception as exc:
            return JSONResponse({"error": f"download cancel failed: {exc}"}, status_code=500)

    @app.post("/api/sequence-preset/search")
    async def api_sequence_preset_search(req: Request):
        payload = await _read_json(req)
        try:
            return await run_in_thread(
                sequence_preset_service(session_context).search, payload
            )
        except Exception as exc:
            return JSONResponse(
                {"error": f"Sequence search failed: {exc}"}, status_code=500
            )

    @app.post("/api/sequence-preset/sequence")
    async def api_sequence_preset_sequence(req: Request):
        payload = await _read_json(req)
        try:
            return await run_in_thread(
                sequence_preset_service(session_context).sequence, payload
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse(
                {"error": f"Sequence expand failed: {exc}"}, status_code=500
            )

    @app.post("/api/sequence-preset/generate")
    async def api_sequence_preset_generate(req: Request):
        # req (1): 팝업에서 보고 있는 특정 그룹의 '연속 생성'. Auto Gen ON 이면 그 그룹 완료 후
        # 러너가 다음 랜덤 그룹으로 연속한다(req 4). payload 에 검색 필터도 실려 와 연속 추첨 모집단이 된다.
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
            return await start_sequence_run(
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
            return JSONResponse({"error": f"Sequence generate failed: {exc}"}, status_code=500)

    @app.post("/api/sequence-preset/random-generate")
    async def api_sequence_preset_random_generate(req: Request):
        # req (2)/(3): 현재 매칭된 전체 셋에서 랜덤 그룹 1개 → 연속 생성. Auto Gen ON 이면 연속 루프 시작.
        payload = await _read_json(req)
        auto_gen = session_context._coerce_bool(
            session_context.get_options().get("auto_generate", False)
        )
        try:
            return await start_sequence_run(
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
            return JSONResponse({"error": f"Sequence random-generate failed: {exc}"}, status_code=500)

    @app.post("/api/sequence-preset/stop")
    async def api_sequence_preset_stop():
        try:
            state = session_context._sequence_run_service().stop()
            extra = state.pop("_headless_extra_messages", []) if isinstance(state, dict) else []
            await broadcast_json(clients, session_context._sequence_run_module_state())
            for message in extra:
                await broadcast_json(clients, message)
            return state
        except Exception as exc:
            return JSONResponse({"error": f"Sequence stop failed: {exc}"}, status_code=500)
