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
        item = context.result_store.get_item(history_id)
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
    async def api_character_asset_detail(id: str = ""):
        try:
            return await run_in_thread(_asset_service(session_context).detail, id)
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
        try:
            result = await run_in_thread(
                _asset_service(session_context).apply_to_slot,
                str(payload.get("id") or ""),
                str(payload.get("variation") or ""),
                str(payload.get("mode") or "c1"),
                with_reference,
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
            if with_reference:
                await broadcast_json(
                    clients, session_context.module_state_payload("character_reference")
                )
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
        }

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
        accepted: list[int] = []
        rejected: list[dict[str, Any]] = []
        for candidate in range(count):
            try:
                overrides = await run_in_thread(service.build_generation_overrides, payload, candidate)
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
            except Exception as exc:
                return JSONResponse(
                    {"error": f"Character Asset generate failed: {exc}"}, status_code=500
                )
            dispatch = await run_in_thread(
                generation.enqueue_remote_request,
                {"type": "generate", "overrides": overrides},
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
