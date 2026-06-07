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


def register_sequence_preset_routes(
    app: FastAPI,
    session_context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
    clients: set[Any],
    broadcast_json: JsonBroadcaster,
    start_generation_runner: GenerationRunnerStarter,
) -> None:
    # 시퀀스 생성 동시 직렬화 락(앱 단위). 공유 EventStreamRuntime 을 무장/해제하는 구간을
    # 두 시퀀스 요청이 겹쳐 서로의 freeze 를 짓밟지 않도록 한다. 가드→무장은 추가로 동기
    # 실행(아래 핸들러)이라 Storyteller/Random 과의 TOCTOU 도 막는다.
    freeze_lock = asyncio.Lock()

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
        payload = await _read_json(req)
        service = sequence_preset_service(session_context)
        try:
            result = await run_in_thread(service.generation_sources, payload)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse(
                {"error": f"Sequence generate failed: {exc}"}, status_code=500
            )

        batch_id = uuid.uuid4().hex
        random = _random_service(session_context)
        generation = _generation_service(session_context)
        active_ratings = session_context.get_active_ratings()
        api_mode = session_context.get_api_mode()
        total = result["total"]
        enqueued: list[dict[str, Any]] = []

        def _coerce_dim(value: Any) -> int | None:
            try:
                parsed = int(float(value))
            except (TypeError, ValueError):
                return None
            return parsed if parsed > 0 else None

        # 정체성 동결을 위해 공유 EventStreamRuntime 을 잠시 무장한다. 가드→무장→스냅샷 캡처는
        # 반드시 await 없이 동기로 실행한다: 단일 스레드 asyncio 가 이 구간을 원자적으로 처리하므로
        # (a) 동시 Sequence/Storyteller 가 가드를 통과해 서로의 freeze 를 짓밟거나(clobber),
        # (b) 동시 Random 이 미무장→무장 전이의 부분 상태/미완 스냅샷을 관측하는 TOCTOU 를 막는다.
        # freeze_lock 은 Sequence 요청 간 직렬화(겹친 두 배치 방지)를 추가로 보장한다.
        async with freeze_lock:
            # --- 동기 임계구역: 가드 (충돌 시 거부) ---
            es_existing = getattr(session_context, "event_stream_runtime", None)
            # is_active 는 Storyteller 자동 사이클과 1.5식 수동 진행을 모두 포착한다
            # (storyteller.is_running() 만으로는 수동 진행을 놓침 — 검증).
            if (es_existing is not None and getattr(es_existing, "is_active", False)) \
                    or session_context._storyteller_service().is_running():
                return JSONResponse(
                    {"error": "Event Stream / Storyteller가 실행 중입니다. 먼저 정지한 뒤 시퀀스를 생성하세요."},
                    status_code=409,
                )
            if session_context._automation_service().is_running():
                return JSONResponse(
                    {"error": "Automation이 실행 중입니다. 정지한 뒤 시퀀스를 생성하세요."},
                    status_code=409,
                )
            if getattr(session_context, "is_generating", False):
                return JSONResponse(
                    {"error": "생성이 진행 중입니다. 완료된 뒤 시퀀스를 생성하세요."},
                    status_code=409,
                )
            queue = getattr(session_context, "generation_queue_manager", None)
            if queue is not None and (queue.is_paused() or not queue.is_empty()):
                return JSONResponse(
                    {"error": "생성 큐가 비어있지 않습니다. 큐를 비운 뒤 시퀀스를 생성하세요."},
                    status_code=409,
                )

            # 시드(첫 이미지 기준 고정): 사용자가 고정 시드를 켜 두고 유효값이 있으면 그 값을,
            # 아니면 배치 전체에 쓸 시드를 1회만 추첨해 전 프레임에 박는다(사용자 결정: "매번 1회
            # 추첨해 고정"). seed + seed_fixed 를 함께 박아야 _normalize_numbers 가 재추첨하지
            # 않는다(default-0 트랩 회피). remote_params(라이브 세션 값)만 읽고 세션은 변경 안 함.
            user_seed_fixed = session_context._coerce_bool(
                session_context.remote_params.get("seed_fixed", False)
            )
            raw_seed = session_context.remote_params.get("seed", "")
            try:
                user_seed = int(float(raw_seed)) if str(raw_seed).strip() != "" else None
            except (TypeError, ValueError):
                user_seed = None
            if user_seed_fixed and user_seed is not None and user_seed >= 0:
                pinned_seed = user_seed
            else:
                pinned_seed = _rng.randint(0, 9_999_999_999)

            # 해상도(첫 이미지 기준 고정): 세션 width/height 를 전 프레임에 동일 적용하고 per-frame
            # auto-fit 을 끈다. resolution 문자열은 정규화가 width/height 로 재계산하므로 width/height
            # 가 진실의 원천. 각 차원을 독립 고정(비대칭 입력도 보존); 판독 실패한 차원은 정규화
            # 기본값으로 전 프레임 동일하게 통일된다.
            fixed_w = _coerce_dim(session_context.remote_params.get("width"))
            fixed_h = _coerce_dim(session_context.remote_params.get("height"))

            # --- 동기 무장 + 정체성 스냅샷 1회 캡처(가드와 같은 임계구역, await 없음) ---
            from core.event_tree import LegacyStoryNodeSpec

            event_stream = session_context._create_event_stream_runtime()
            event_stream.start_linear(
                [LegacyStoryNodeSpec(node_id="sequence.freeze", name="Sequence")],
                run_id=f"sequence-{batch_id}",
            )
            try:
                event_stream.ensure_freeze_snapshot()
                frozen_chars = event_stream.get_frozen_character_params()
            except Exception as exc:
                # 캡처 실패: 무장 상태로 남기지 않도록 즉시 해제 후 명확히 실패 반환.
                try:
                    event_stream.stop()
                except Exception:
                    pass
                return JSONResponse(
                    {"error": f"Sequence freeze arm failed: {exc}"}, status_code=500
                )

            try:
                # 프레임별: freeze 로 아티스트/와일드카드 고정된 PE 경유 조립(메인 컨텍스트 비오염)
                # → 정체성(시드/해상도/캐릭터) baking → enqueue. 한 프레임 실패해도 나머지 진행.
                # 각 프레임을 try/except 로 감싸 예외에도 frames[] 가 항상 프레임당 1엔트리 보장.
                for source in result["sources"]:
                    idx = source["index"]
                    try:
                        source_row = source["sourceRow"]
                        request_id = f"seqpreset-{batch_id[:8]}-{idx}"
                        assembled = await run_in_thread(
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
                        overrides: dict[str, Any] = {
                            "input": assembled.prompt,
                            "_raw_input": assembled.prompt,
                            "_source_row_data": dict(source_row),
                            "_source_name": request_id,
                            "_remote_queue_source": "SequencePreset",
                            "_remote_queue_label": "sequence_preset",
                            "sequence_preset_request": True,
                            "sequence_preset_request_id": request_id,
                            "sequence_preset_group_id": batch_id,
                            "sequence_preset_frame": f"{idx + 1}/{total}",
                            # 첫 이미지 기준 시드 고정.
                            "seed": pinned_seed,
                            "seed_fixed": True,
                            # 첫 이미지 기준 해상도 고정(per-frame auto-fit 차단).
                            "auto_fit_resolution": False,
                        }
                        if fixed_w:
                            overrides["width"] = fixed_w
                        if fixed_h:
                            overrides["height"] = fixed_h
                        if fixed_w and fixed_h:
                            overrides["resolution"] = f"{fixed_w} x {fixed_h}"
                        # NAI 캐릭터 프롬프트 동결: 동결 캐릭터를 커맨드 params 에 baking → freeze
                        # 해제(큐 드레인) 후에도 EarlyBinding 경로로 적용된다. uc 길이를 캐릭터 수에
                        # 맞춰(부족분=빈 네거티브 패딩, 초과분=절단) NAICharacterData 검증을 항상
                        # 통과시켜 동결 캐릭터가 조용히 드롭되지 않게 한다(정상 경로는 이미 일치).
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
                        dispatch = await run_in_thread(generation.enqueue_remote_request, command)
                        enqueued.append({
                            "index": idx, "ok": bool(dispatch.ok),
                            "prompt": assembled.prompt,
                            "requestId": getattr(dispatch.request, "request_id", "") if dispatch.ok else "",
                            "error": "" if dispatch.ok else (dispatch.blocked_reason or "enqueue blocked"),
                        })
                    except Exception as exc:  # 프레임 단위 격리 — 전체 요청이 500 으로 죽지 않게
                        enqueued.append({"index": idx, "ok": False, "error": f"frame error: {exc}"})
            finally:
                # Freeze 는 조립 동안에만 필요(정체성은 baking 완료). 항상 해제해 공유 런타임이
                # 무장 상태로 남지 않게 한다(이후 일반 Random 이 allocator 로 빠지는 것 방지).
                # stop 은 동기·경량(publish only)이라 스레드 없이 호출한다.
                try:
                    event_stream.stop()
                except Exception:
                    pass

        ok_count = sum(1 for e in enqueued if e["ok"])
        if ok_count and session_context.headless_generation_execute_enabled:
            start_generation_runner(session_context, clients)
        await broadcast_json(clients, {
            "type": "sequence_preset_queued",
            "groupId": result["groupId"],
            "batchId": batch_id,
            "total": total,
            "enqueued": ok_count,
            "seed": pinned_seed,
        })
        return {
            "ok": ok_count > 0,
            "status": "sequence_queued",
            "groupId": result["groupId"],
            "batchId": batch_id,
            "total": total,
            "enqueued": ok_count,
            "seed": pinned_seed,
            "frames": enqueued,
        }
