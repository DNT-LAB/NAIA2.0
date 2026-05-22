from __future__ import annotations

import io
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from core import result_image_payload_service as result_images
from core.headless_generation_service import HeadlessGenerationService
from core.web_session_context import WebSessionContext


PROMPT_ENGINEERING_PRESET_MODES = ("NAI", "WEBUI", "COMFYUI")
AsyncRunner = Callable[..., Awaitable[Any]]
JsonBroadcaster = Callable[[set[Any], dict[str, Any]], Awaitable[None]]
GenerationRunnerStarter = Callable[[WebSessionContext, set[Any]], None]


def prompt_highlight_empty_index() -> dict[str, object]:
    return {
        "version": "headless-empty",
        "groups": {},
        "tags": {},
        "stats": {
            "source": "headless",
            "total": 0,
        },
    }


def _no_cache_headers() -> dict[str, str]:
    return {"Cache-Control": "no-store, max-age=0"}


def _generation_service(context: WebSessionContext) -> HeadlessGenerationService:
    service = getattr(context, "headless_generation_service", None)
    if service is None:
        service = HeadlessGenerationService(context)
        context.headless_generation_service = service
    return service


def _image_media_type_for_path(image_path: str | Path) -> str:
    return result_images.image_media_type_for_path(image_path)


def _tag_data_roots(context: WebSessionContext) -> list[Path]:
    roots: list[Path] = []
    runtime_paths = getattr(context, "runtime_paths", None)
    if runtime_paths is not None:
        roots.append(runtime_paths.data_dir)
    roots.append(Path(context.repo_root) / "data")
    return roots


def tag_lookup_info(context: WebSessionContext, tag: str) -> dict[str, Any]:
    raw_tags = getattr(context, "kr_tags_raw", None)
    if not isinstance(raw_tags, dict) or not raw_tags:
        from core.kr_tag_loader import load_kr_tag_records
        from core.tag_relation_ranker import TagRelationRanker

        load_result = load_kr_tag_records(context.repo_root, data_roots=_tag_data_roots(context))
        raw_tags = load_result.raw
        context.kr_tags_raw = raw_tags
        context.tag_relation_ranker = TagRelationRanker(raw_tags) if raw_tags else None
    if not raw_tags:
        return {}
    tag_lower = re.sub(r"\\([()])", r"\1", str(tag or "").strip()).lower()
    info = raw_tags.get(tag_lower)
    if not info:
        return {}
    result = {
        "tag": info.get("_tag", tag),
        "count": info.get("freq", 0),
        "desc": info.get("description", ""),
        "group": info.get("group", ""),
        "subgroup": info.get("subgroup", ""),
        "cat": info.get("_cat", ""),
    }
    relations = info.get("relations", {}) if isinstance(info.get("relations"), dict) else {}
    parents = relations.get("parent", [])
    if isinstance(parents, str):
        parents = [parents]
    ranker = getattr(context, "tag_relation_ranker", None)
    if ranker is not None:
        parents = ranker.valid_implications(tag_lower, info, limit=8)
    if parents:
        result["implications"] = parents[:8]
    if ranker is not None:
        related = ranker.rank_related(tag_lower, info, limit=8)
    else:
        related = []
        seen = set(parents)
        for relation_key in ("siblings", "word_match"):
            values = relations.get(relation_key, [])
            if isinstance(values, str):
                values = [values]
            for value in values:
                if value not in seen:
                    seen.add(value)
                    related.append(value)
    if related:
        result["related"] = related[:8]
    extra_info = {}
    for extra_tag in list(result.get("implications", [])) + list(result.get("related", [])):
        extra = raw_tags.get(str(extra_tag).strip().lower())
        if not extra:
            continue
        extra_info[str(extra_tag)] = {
            "tag": extra.get("_tag", str(extra_tag)),
            "count": extra.get("freq", 0),
            "desc": extra.get("description", ""),
            "group": extra.get("group", ""),
            "subgroup": extra.get("subgroup", ""),
            "cat": extra.get("_cat", ""),
        }
    if extra_info:
        result["extra_tag_info"] = extra_info
    return result


def _preview_candidates(context: WebSessionContext, preset_name: str, mode: str = "") -> list[Path]:
    safe_name = Path(str(preset_name or "").strip()).name
    if not safe_name or safe_name == "*randomized":
        return []
    mode_key = _normalize_preset_mode(context, mode, allow_empty=True)
    candidates = [
        preview_dir / f"{safe_name}{ext}"
        for preview_dir in context._existing_save_dirs("presets", "previews")
        for ext in (".png", ".webp", ".jpg", ".jpeg")
    ]
    try:
        favorites_path = context._existing_save_path("presets", "favorites.json")
        favorite_items = json.loads(favorites_path.read_text(encoding="utf-8")) if favorites_path.exists() else []
        if any(
            isinstance(item, dict)
            and item.get("name") == safe_name
            and (not mode_key or item.get("mode") == mode_key)
            for item in favorite_items
        ):
            for favorite_dir in context._existing_save_dirs("presets", "favorites"):
                candidates.extend(favorite_dir / f"{safe_name}{ext}" for ext in (".png", ".webp", ".jpg", ".jpeg"))
    except Exception:
        pass
    return candidates


def _preview_path(context: WebSessionContext, preset_name: str, mode: str = "") -> Path | None:
    for candidate in _preview_candidates(context, preset_name, mode):
        try:
            target = candidate.resolve()
        except Exception:
            continue
        if target.is_file():
            return target
    return None


def _normalize_preset_mode(
    context: WebSessionContext,
    mode: str = "",
    *,
    allow_empty: bool = False,
) -> str:
    value = str(mode or "").strip().upper()
    if not value:
        if allow_empty:
            return ""
        current_mode = str(context.get_api_mode() or "").strip().upper()
        return current_mode if current_mode in PROMPT_ENGINEERING_PRESET_MODES else "NAI"
    if value not in PROMPT_ENGINEERING_PRESET_MODES:
        raise ValueError("Invalid preset mode")
    return value


def _thumbnail_target(context: WebSessionContext, preset_name: str) -> Path:
    safe_name = Path(str(preset_name or "").strip()).name
    if not safe_name or safe_name == "*randomized":
        raise ValueError("Preset name is required")
    target_dir = context._save_path("presets", "previews")
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / f"{safe_name}.png"


def _thumbnail_update_payload(context: WebSessionContext, preset_name: str, mode: str = "") -> dict[str, Any]:
    safe_name = Path(str(preset_name or "").strip()).name
    mode_key = _normalize_preset_mode(context, mode, allow_empty=True)
    target = _preview_path(context, safe_name, mode_key)
    if not target:
        target = _thumbnail_target(context, safe_name)
    version = int(target.stat().st_mtime) if target.exists() else int(time.time())
    return {
        "ok": True,
        "name": safe_name,
        "mode": mode_key,
        "has_thumbnail": target.exists(),
        "thumbnail_url": (
            f"/api/prompt-engineering/preset-thumbnail"
            f"?name={quote(safe_name, safe='')}&mode={quote(mode_key, safe='')}&v={version}"
        ),
    }


def save_prompt_engineering_thumbnail_bytes(
    context: WebSessionContext,
    preset_name: str,
    mode: str,
    image_bytes: bytes,
) -> dict[str, Any]:
    if not image_bytes:
        raise ValueError("Image payload is empty")
    if len(image_bytes) > 24 * 1024 * 1024:
        raise ValueError("Image is too large")
    from PIL import Image

    mode_key = _normalize_preset_mode(context, mode, allow_empty=True)
    target = _thumbnail_target(context, preset_name)
    with Image.open(io.BytesIO(image_bytes)) as opened:
        opened.load()
        opened.convert("RGBA").save(target, format="PNG")
    return _thumbnail_update_payload(context, preset_name, mode_key)


def _preset_file(context: WebSessionContext, preset_name: str, mode: str = "") -> Path | None:
    safe_name = Path(str(preset_name or "").strip()).name
    if not safe_name:
        return None
    mode_candidates: list[str] = []
    if mode:
        mode_candidates.append(_normalize_preset_mode(context, mode))
    current_mode = _normalize_preset_mode(context, context.get_api_mode(), allow_empty=True)
    if current_mode and current_mode not in mode_candidates:
        mode_candidates.append(current_mode)
    for fallback_mode in PROMPT_ENGINEERING_PRESET_MODES:
        if fallback_mode not in mode_candidates:
            mode_candidates.append(fallback_mode)
    for mode_name in mode_candidates:
        candidate = context._existing_save_path("presets", mode_name, f"{safe_name}.json")
        if candidate.exists():
            return candidate
    return None


def _thumbnail_generation_prompt(context: WebSessionContext, preset_name: str, mode: str = "") -> str:
    pieces: list[str] = []
    preset_file = _preset_file(context, preset_name, mode)
    if preset_file:
        try:
            data = json.loads(preset_file.read_text(encoding="utf-8"))
            settings = data.get("module_settings", {}) if isinstance(data, dict) else {}
            pre_prompt = str(settings.get("pre_prompt", "") or "").strip()
            if pre_prompt:
                pieces.append(pre_prompt)
        except Exception:
            pass
    pieces.append("1girl, original, solo, upper body")
    return ", ".join(piece for piece in pieces if piece)


def register_prompt_tools_routes(
    app: FastAPI,
    session_context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
    clients: set[Any],
    broadcast_json: JsonBroadcaster,
    start_generation_runner: GenerationRunnerStarter,
) -> None:

    @app.get("/api/prompt-highlight-index")
    async def api_prompt_highlight_index():
        return Response(
            content=json.dumps(prompt_highlight_empty_index(), ensure_ascii=False),
            media_type="application/json",
            headers=_no_cache_headers(),
        )

    @app.get("/api/tag/lookup")
    async def api_tag_lookup(tag: str = ""):
        try:
            return await run_in_thread(tag_lookup_info, session_context, tag)
        except Exception as exc:
            return JSONResponse({"error": f"Tag lookup failed: {exc}"}, status_code=500)

    @app.get("/api/prompt-engineering/preset-thumbnail")
    async def api_prompt_engineering_preset_thumbnail(name: str = "", mode: str = "", v: str = ""):
        try:
            target = await run_in_thread(_preview_path, session_context, name, mode)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        if not target:
            return JSONResponse({"error": "Preset thumbnail not found"}, status_code=404)
        return FileResponse(
            str(target),
            media_type=_image_media_type_for_path(target),
            headers=_no_cache_headers(),
        )

    @app.post("/api/prompt-engineering/preset-thumbnail/upload")
    async def api_prompt_engineering_preset_thumbnail_upload(req: Request, name: str = "", mode: str = ""):
        try:
            image_bytes = await req.body()
            payload = await run_in_thread(
                save_prompt_engineering_thumbnail_bytes,
                session_context,
                name,
                mode,
                image_bytes,
            )
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"Preset thumbnail upload failed: {exc}"}, status_code=500)
        await broadcast_json(clients, {
            "type": "prompt_engineering_preset_thumbnail_updated",
            **payload,
        })
        return payload

    @app.post("/api/prompt-engineering/preset-thumbnail/generate")
    async def api_prompt_engineering_preset_thumbnail_generate(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            name = Path(str(payload.get("name") or "").strip()).name
            mode = _normalize_preset_mode(session_context, payload.get("mode") or "")
            if not name or name == "*randomized":
                raise ValueError("Preset name is required")
            if not _preset_file(session_context, name, mode):
                raise FileNotFoundError(f"Preset not found: {name}")
            request_id = str(payload.get("request_id") or uuid.uuid4().hex)
            prompt = _thumbnail_generation_prompt(session_context, name, mode)
            overrides = {
                "input": prompt,
                "_raw_input": prompt,
                "negative_prompt": session_context.negative_prompt_text,
                "width": 1088,
                "height": 960,
                "random_resolution": False,
                "prompt_preset_thumbnail_request": True,
                "prompt_preset_thumbnail_request_id": request_id,
                "prompt_preset_thumbnail_name": name,
                "prompt_preset_thumbnail_mode": mode,
                "_skip_vibe_transfer_late_binding": True,
                "_remote_queue_source": "Preset Thumb",
                "_remote_queue_label": name,
            }
            dispatch = await run_in_thread(
                _generation_service(session_context).enqueue_remote_request,
                {"type": "generate", "overrides": overrides},
            )
        except FileNotFoundError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=404)
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"Preset thumbnail generation failed: {exc}"}, status_code=500)
        if not dispatch.ok:
            return JSONResponse(dispatch.websocket_payload(), status_code=409)
        await broadcast_json(clients, session_context.queue_state_payload())
        if session_context.headless_generation_execute_enabled:
            start_generation_runner(session_context, clients)
        return {
            "ok": True,
            "status": "generation_requested",
            "request_id": request_id,
            "name": name,
            "mode": mode,
            "vibe_active": False,
            "vibe_count": 0,
            "message": f"{name} 임시 썸네일 생성을 요청했습니다.",
        }
