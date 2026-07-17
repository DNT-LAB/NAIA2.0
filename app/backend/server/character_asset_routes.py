"""Character Asset REST routes — gallery, save, slot apply, reference generation.

Web port of the desktop character asset storage (Dev0714). Thin wrappers over
core.headless_character_asset_service; modeled on character_viewer_routes.
"""

from __future__ import annotations

import io
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from app.backend.server.result_display_routes import (
    history_item_from_viewer_path,
    validate_viewer_path,
)
from app.backend.server.websocket_broadcast import broadcast_json
from core.headless_character_asset_service import MAX_GENERATION_COUNT, PNG_SIGNATURE
from core.headless_generation_service import HeadlessGenerationService
from core.web_session_context import WebSessionContext


AsyncRunner = Callable[..., Awaitable[Any]]
GenerationRunnerStarter = Callable[[WebSessionContext, set[Any]], None]

PRIVATE_CACHE_HEADERS = {"Cache-Control": "private, max-age=3600"}


def _asset_service(context: WebSessionContext):
    return context._character_asset_service()


def _generation_service(context: WebSessionContext) -> HeadlessGenerationService:
    service = getattr(context, "headless_generation_service", None)
    if service is None:
        service = HeadlessGenerationService(context)
        context.headless_generation_service = service
    return service


def character_asset_thumb_payload(
    context: WebSessionContext,
    character_id: str,
    variation: str = "",
    size: str = "",
) -> tuple[bytes, str]:
    path = _asset_service(context).resolve_image_path(character_id, variation)
    size_key = str(size or "").strip().lower()
    if size_key == "grid":
        cache = getattr(context, "character_asset_thumb_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            context.character_asset_thumb_cache = cache
        stat = path.stat()
        cache_key = (str(path), stat.st_mtime_ns, stat.st_size, size_key)
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        from PIL import Image

        with Image.open(path) as image:
            image.thumbnail((384, 384), Image.Resampling.BILINEAR)
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGB")
            buffer = io.BytesIO()
            image.save(buffer, "WEBP", quality=72, method=0)
        payload = (buffer.getvalue(), "image/webp")
        if len(cache) > 256:
            cache.clear()
        cache[cache_key] = payload
        return payload
    return path.read_bytes(), "image/png"


def _history_item_png_bytes(item: Any) -> bytes:
    """Original PNG bytes for an in-memory history item - no re-encoding, ever.

    Only ``raw_bytes`` that is already a PNG qualifies: the asset contract needs
    the generator's own PNG (NAI Comment intact). ``png_payload_override`` is
    itself a re-encoded PNG built from non-PNG backends (ComfyUI WebP), so it is
    deliberately NOT accepted - such results carry no NAI character block and
    would only produce a never-applicable asset.
    """
    raw = getattr(item, "raw_bytes", None)
    if raw and bytes(raw).startswith(PNG_SIGNATURE):
        return bytes(raw)
    raise ValueError("history item is not an original PNG result")


def _resolve_source_bytes(context: WebSessionContext, source: dict[str, Any]) -> bytes:
    """Resolve a discriminated save source to PNG bytes.

    Only two kinds exist by contract: an in-memory history item or a validated
    viewer rel_path (save-dir containment enforced; `__history_item__/` paths
    resolve to in-memory items). The frontend pins the target at staging time -
    there is deliberately no floating "current result" kind, so a result that
    arrives between staging and saving cannot swap the saved image.
    """
    kind = str((source or {}).get("kind") or "").strip().lower()
    if kind == "history":
        history_id = str(source.get("history_id") or "").strip()
        # candidate_item: 히스토리에서 퇴출됐어도 캐릭터 에셋 후보는 리스가 살려둔다.
        item = _asset_service(context).candidate_item(history_id)
        if item is None:
            raise FileNotFoundError("history item not found (already evicted?)")
        return _history_item_png_bytes(item)
    if kind == "viewer":
        rel_path = str(source.get("rel_path") or "").strip()
        item = history_item_from_viewer_path(context, rel_path)
        if item is not None:
            return _history_item_png_bytes(item)
        path = validate_viewer_path(context, rel_path)
        if path is None:
            raise ValueError("invalid viewer path")
        return path.read_bytes()
    raise ValueError(f"unknown source kind: {kind or '(empty)'}")


async def _read_json(req: Request) -> dict[str, Any]:
    try:
        payload = await req.json()
    except Exception:
        payload = {}
    return payload if isinstance(payload, dict) else {}


def register_character_asset_routes(
    app: FastAPI,
    session_context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
    clients: set[Any],
    start_generation_runner: GenerationRunnerStarter,
) -> None:
    @app.get("/api/character-asset/list")
    async def api_character_asset_list():
        try:
            return await run_in_thread(_asset_service(session_context).list_state)
        except Exception as exc:
            return JSONResponse({"error": f"Character Asset list failed: {exc}"}, status_code=500)

    @app.get("/api/character-asset/detail")
    async def api_character_asset_detail(id: str = "", variation: str = ""):
        try:
            return await run_in_thread(_asset_service(session_context).detail, id, variation)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Character Asset detail failed: {exc}"}, status_code=500)

    @app.get("/api/character-asset/thumb")
    async def api_character_asset_thumb(id: str = "", variation: str = "", size: str = "", v: str = ""):
        try:
            image_bytes, media_type = await run_in_thread(
                character_asset_thumb_payload, session_context, id, variation, size
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Character Asset thumb failed: {exc}"}, status_code=500)
        return Response(content=image_bytes, media_type=media_type, headers=PRIVATE_CACHE_HEADERS)

    @app.get("/api/character-asset/image")
    async def api_character_asset_image(id: str = "", variation: str = "", v: str = ""):
        try:
            path = await run_in_thread(_asset_service(session_context).resolve_image_path, id, variation)
            image_bytes = await run_in_thread(path.read_bytes)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Character Asset image failed: {exc}"}, status_code=500)
        return Response(content=image_bytes, media_type="image/png", headers=PRIVATE_CACHE_HEADERS)

    @app.post("/api/character-asset/save")
    async def api_character_asset_save(req: Request):
        payload = await _read_json(req)
        try:
            data = await run_in_thread(
                _resolve_source_bytes, session_context, payload.get("source") or {}
            )
            result = await run_in_thread(
                _asset_service(session_context).save_bytes, data, payload.get("target") or {}
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Character Asset save failed: {exc}"}, status_code=500)
        return {"ok": True, **result}

    @app.post("/api/character-asset/apply")
    async def api_character_asset_apply(req: Request):
        payload = await _read_json(req)
        with_reference = bool(payload.get("with_reference"))
        with_inset = bool(payload.get("with_inset"))
        try:
            result = await run_in_thread(
                _asset_service(session_context).apply_to_slot,
                str(payload.get("id") or ""),
                str(payload.get("variation") or ""),
                str(payload.get("mode") or "c1"),
                with_reference,
                with_inset,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Character Asset apply failed: {exc}"}, status_code=500)
        # Push the refreshed module states to every client so open panels and
        # launcher badges reflect the applied slot / reference immediately.
        try:
            await broadcast_json(clients, session_context.module_state_payload("character"))
            # C1 단독도 기존 CR을 전부 끄므로(references_disabled) CR 패널 갱신 필요.
            if with_reference or result.get("references_disabled"):
                await broadcast_json(
                    clients, session_context.module_state_payload("character_reference")
                )
            if with_reference:
                await broadcast_json(
                    clients, session_context.module_state_payload("vibe_transfer")
                )
        except Exception as exc:
            print(f"[CharacterAsset] module state broadcast failed: {exc}")
        return {
            "ok": True,
            "character_prompt": result.get("character_prompt", ""),
            "character_uc": result.get("character_uc", ""),
            "reference_attached": bool(result.get("reference_attached")),
            "references_disabled": bool(result.get("references_disabled")),
            "reference_inset": result.get("reference_inset"),
        }

    @app.get("/api/character-asset/inset/state")
    async def api_character_asset_inset_state():
        # 리로드 후 프론트가 핀 배지를 복원할 근거 - 백엔드 핀은 리로드와 무관하게
        # 살아 있으므로(생성이 계속 인셋으로 나감) 표시 불일치를 막아야 한다.
        return _asset_service(session_context).reference_inset_state()

    @app.post("/api/character-asset/inset/unpin")
    async def api_character_asset_inset_unpin():
        released = _asset_service(session_context).clear_reference_inset_pin()
        return {"ok": True, "released": released}

    @app.post("/api/character-asset/rename")
    async def api_character_asset_rename(req: Request):
        payload = await _read_json(req)
        try:
            result = await run_in_thread(
                _asset_service(session_context).rename,
                str(payload.get("id") or ""),
                str(payload.get("display_name") or ""),
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Character Asset rename failed: {exc}"}, status_code=500)
        return {"ok": True, **result}

    @app.post("/api/character-asset/update-prompt")
    async def api_character_asset_update_prompt(req: Request):
        payload = await _read_json(req)
        try:
            result = await run_in_thread(
                _asset_service(session_context).update_prompt,
                str(payload.get("id") or ""),
                str(payload.get("character_prompt") or ""),
                str(payload.get("character_uc") or ""),
                str(payload.get("variation") or ""),
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse(
                {"error": f"Character Asset prompt update failed: {exc}"}, status_code=500
            )
        return {"ok": True, **result}

    @app.post("/api/character-asset/delete")
    async def api_character_asset_delete(req: Request):
        payload = await _read_json(req)
        try:
            deleted = await run_in_thread(
                _asset_service(session_context).delete, str(payload.get("id") or "")
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"Character Asset delete failed: {exc}"}, status_code=500)
        return {"ok": bool(deleted)}

    @app.post("/api/character-asset/delete-variation")
    async def api_character_asset_delete_variation(req: Request):
        payload = await _read_json(req)
        try:
            deleted = await run_in_thread(
                _asset_service(session_context).delete_variation,
                str(payload.get("id") or ""),
                str(payload.get("hash") or ""),
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse(
                {"error": f"Character Asset variation delete failed: {exc}"}, status_code=500
            )
        return {"ok": bool(deleted)}

    @app.post("/api/character-asset/promote")
    async def api_character_asset_promote(req: Request):
        payload = await _read_json(req)
        try:
            promoted = await run_in_thread(
                _asset_service(session_context).promote,
                str(payload.get("id") or ""),
                str(payload.get("hash") or ""),
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Character Asset promote failed: {exc}"}, status_code=500)
        return {"ok": bool(promoted)}

    @app.get("/api/character-asset/bench/defaults")
    async def api_character_asset_bench_defaults(id: str = ""):
        try:
            service = _asset_service(session_context)
            defaults = await run_in_thread(service.bench_defaults)
            # id는 optional: 생성 벤치는 아직 캐릭터가 없어 PRIMARY만 unavailable로
            # 내려가고 CURRENT/PRESET은 그대로 쓸 수 있다.
            defaults["prompt_profiles"] = await run_in_thread(
                service.bench_prompt_profiles, str(id or "")
            )
            return defaults
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"bench defaults failed: {exc}"}, status_code=500)

    @app.post("/api/character-asset/bench/enhance")
    async def api_character_asset_bench_enhance(req: Request):
        payload = await _read_json(req)
        service = _asset_service(session_context)
        generation = _generation_service(session_context)
        try:
            overrides = await run_in_thread(service.build_bench_enhance_overrides, payload, 0)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"bench enhance failed: {exc}"}, status_code=500)
        dispatch = await run_in_thread(
            generation.enqueue_remote_request,
            # api_mode pinned - same reasoning as bench/generate below.
            {"type": "generate", "api_mode": "NAI", "overrides": overrides},
        )
        if not dispatch.ok:
            return JSONResponse(
                {"error": str(dispatch.websocket_payload().get("message") or "enhance dispatch failed")},
                status_code=409,
            )
        if session_context.headless_generation_execute_enabled:
            start_generation_runner(session_context, clients)
        return {"ok": True, "accepted": [0]}

    @app.post("/api/character-asset/bench/generate")
    async def api_character_asset_bench_generate(req: Request):
        payload = await _read_json(req)
        try:
            count = int(payload.get("count") or 1)
        except (TypeError, ValueError):
            count = 1
        count = max(1, min(MAX_GENERATION_COUNT, count))
        service = _asset_service(session_context)
        generation = _generation_service(session_context)
        # 배치 사전검증(Codex BLOCK) - 전 후보 빌드 성공 후에만 enqueue. 실패 시
        # HTTP 에러가 곧 "아무것도 큐에 없음"을 뜻해야 프론트 전체-실패 표시가 참이 된다.
        overrides_batch: list[dict[str, Any]] = []
        for candidate in range(count):
            try:
                overrides_batch.append(
                    await run_in_thread(service.build_bench_overrides, payload, candidate)
                )
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
            except FileNotFoundError as exc:
                return JSONResponse({"error": str(exc)}, status_code=404)
            except Exception as exc:
                return JSONResponse({"error": f"bench generate failed: {exc}"}, status_code=500)
        accepted: list[int] = []
        rejected: list[dict[str, Any]] = []
        for candidate, overrides in enumerate(overrides_batch):
            dispatch = await run_in_thread(
                generation.enqueue_remote_request,
                # api_mode is pinned: the NAI check ran in build_bench_overrides,
                # but the mode could flip between that await and this enqueue
                # (img2img service does the same).
                {"type": "generate", "api_mode": "NAI", "overrides": overrides},
            )
            if dispatch.ok:
                accepted.append(candidate)
            else:
                rejected.append({"candidate": candidate, **dispatch.websocket_payload()})
        if accepted:
            await run_in_thread(
                service.save_bench_defaults,
                str(payload.get("generation_mode") or "inpaint"),
                str(payload.get("main_prompt") or ""),
                str(payload.get("extra_negative") or ""),
            )
            if session_context.headless_generation_execute_enabled:
                start_generation_runner(session_context, clients)
        return {
            "ok": bool(accepted),
            "request_id": str(payload.get("request_id") or ""),
            "accepted": accepted,
            "rejected": rejected,
        }

    @app.post("/api/character-asset/bench/save")
    async def api_character_asset_bench_save(req: Request):
        payload = await _read_json(req)
        try:
            result = await run_in_thread(
                _asset_service(session_context).save_bench_result,
                str(payload.get("id") or ""),
                str(payload.get("history_id") or ""),
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"bench save failed: {exc}"}, status_code=500)
        return {"ok": True, **result}

    @app.get("/api/character-asset/candidate/image")
    async def api_character_asset_candidate_image(history_id: str = ""):
        # /api/history/image는 result_store만 조회해 퇴출 즉시 404다. 벤치 후보는
        # 리스가 붙잡고 있으므로(저장이 가능한 상태) 이미지도 리스에서 내준다 -
        # 안 그러면 "저장은 되는데 미리보기는 깨진" 모순이 생긴다(Codex).
        item = _asset_service(session_context).candidate_item(history_id)
        if item is None:
            return JSONResponse({"error": "candidate is no longer available"}, status_code=404)
        try:
            image_bytes = _history_item_png_bytes(item)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return Response(content=image_bytes, media_type="image/png", headers=PRIVATE_CACHE_HEADERS)

    @app.post("/api/character-asset/candidate/pin")
    async def api_character_asset_candidate_pin(req: Request):
        # 인페인트 핀: 원본 PNG를 서버가 복사해 붙잡는다 - 히스토리 퇴출/리스
        # FIFO 밀림과 무관하게, 사용자가 해제할 때까지 유효(핀 계약).
        payload = await _read_json(req)
        try:
            result = await run_in_thread(
                _asset_service(session_context).pin_candidate,
                str(payload.get("history_id") or ""),
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"candidate pin failed: {exc}"}, status_code=500)
        return {"ok": True, **result}

    @app.post("/api/character-asset/candidate/unpin")
    async def api_character_asset_candidate_unpin(req: Request):
        payload = await _read_json(req)
        released = _asset_service(session_context).unpin_candidate(str(payload.get("pin_id") or ""))
        return {"ok": True, "released": released}

    @app.get("/api/character-asset/candidate/pin-image")
    async def api_character_asset_candidate_pin_image(pin_id: str = ""):
        pin = _asset_service(session_context).pinned_candidate(pin_id)
        if pin is None:
            return JSONResponse({"error": "pinned candidate not found"}, status_code=404)
        return Response(content=pin["png"], media_type="image/png", headers=PRIVATE_CACHE_HEADERS)

    @app.get("/api/character-asset/random-character")
    async def api_character_asset_random_character(parts: str = "", gender: str = "girl"):
        requested = [part for part in str(parts or "").split(",") if part.strip()]
        try:
            return await run_in_thread(
                _asset_service(session_context).roll_random_character, requested, gender
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"random character roll failed: {exc}"}, status_code=500)

    @app.post("/api/character-asset/random-outfit")
    async def api_character_asset_random_outfit(req: Request):
        payload = await _read_json(req)
        owned = payload.get("owned")
        try:
            return await run_in_thread(
                _asset_service(session_context).roll_outfit_swap,
                str(payload.get("prompt") or ""),
                owned if isinstance(owned, list) else [],
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"outfit roll failed: {exc}"}, status_code=500)

    @app.get("/api/character-asset/reference/storage")
    async def api_character_asset_reference_storage():
        try:
            return await run_in_thread(_asset_service(session_context).reference_storage_list)
        except Exception as exc:
            return JSONResponse({"error": f"reference storage list failed: {exc}"}, status_code=500)

    @app.post("/api/character-asset/reference/upload")
    async def api_character_asset_reference_upload(req: Request):
        # 계약: raw 이미지 bytes 본문 하나만 받는다(data URL 병행 금지 - Codex).
        # 포맷은 Pillow가 여는 것이면 무엇이든 허용하고 저장 시 PNG로 정규화한다
        # (UI의 image/* accept와 일치). 저장소는 모델 독립적인 자산 라이브러리라
        # 여기선 모델을 막지 않는다; 실제 사용은 generate의 effective-model 게이트가 거부.
        try:
            data = await req.body()
            result = await run_in_thread(_asset_service(session_context).save_reference_image, data)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"reference upload failed: {exc}"}, status_code=500)
        return {"ok": True, **result}

    @app.post("/api/character-asset/generate")
    async def api_character_asset_generate(req: Request):
        payload = await _read_json(req)
        try:
            count = int(payload.get("count") or 1)
        except (TypeError, ValueError):
            count = 1
        count = max(1, min(MAX_GENERATION_COUNT, count))
        service = _asset_service(session_context)
        generation = _generation_service(session_context)
        # 배치 사전검증(Codex BLOCK): 후보 N의 빌드 실패로 HTTP 에러를 돌려줄 때
        # 앞 후보가 이미 큐에 들어가 있으면 안 된다(과금됐는데 프론트는 전체 실패
        # 표시). 모든 오버라이드를 먼저 빌드하고, 전부 통과했을 때만 enqueue.
        overrides_batch: list[dict[str, Any]] = []
        for candidate in range(count):
            try:
                overrides_batch.append(
                    await run_in_thread(service.build_generation_overrides, payload, candidate)
                )
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
            except FileNotFoundError as exc:
                # 유실된 인페인트 핀 등 - 500이 아니라 404로(프론트가 재핀 안내)
                return JSONResponse({"error": str(exc)}, status_code=404)
            except Exception as exc:
                return JSONResponse(
                    {"error": f"Character Asset generate failed: {exc}"}, status_code=500
                )
        accepted: list[int] = []
        rejected: list[dict[str, Any]] = []
        for candidate, overrides in enumerate(overrides_batch):
            dispatch = await run_in_thread(
                generation.enqueue_remote_request,
                {"type": "generate", "api_mode": "NAI", "overrides": overrides},
            )
            if dispatch.ok:
                accepted.append(candidate)
            else:
                rejected.append({"candidate": candidate, **dispatch.websocket_payload()})
        if accepted and session_context.headless_generation_execute_enabled:
            start_generation_runner(session_context, clients)
        return {
            "ok": bool(accepted),
            "request_id": str(payload.get("request_id") or ""),
            "accepted": accepted,
            "rejected": rejected,
        }
