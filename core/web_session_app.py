"""PyQt-free FastAPI app for the headless Remote Web Session path."""

from __future__ import annotations

from contextlib import asynccontextmanager
import json
import asyncio
import io
import mimetypes
import re
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlparse

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from core import result_image_payload_service as result_images
from core.artist_thumbnail_service import ArtistThumbnailService
from core.character_viewer_service import CharacterViewerService
from core.clothes_preset_service import ClothesPresetService
from core.danbooru_client import DANBOORU_BASE_URL, fetch_danbooru_post
from core.event_preset_download_service import EventPresetDownloadService
from core.event_preset_service import EventPresetService
from core.expression_preset_service import ExpressionPresetService
from core.headless_generation_service import HeadlessGenerationService
from core.headless_random_prompt_service import HeadlessRandomPromptService
from core.preset_composer_service import PresetComposerService
from core.style_thumbnail_service import StyleThumbnailService
from core.web_session_context import WebSessionContext


def _client_host(ws: WebSocket) -> str:
    try:
        if ws.client is not None:
            host = str(ws.client.host or "")
            if host == "testclient":
                return "127.0.0.1"
            return host
    except Exception:
        pass
    return ""


def _no_cache_headers() -> dict[str, str]:
    return {"Cache-Control": "no-store, max-age=0"}


def _web_file(path: Path, media_type: str):
    if not path.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(str(path), media_type=media_type, headers=_no_cache_headers())


def _prompt_highlight_empty_index() -> dict[str, Any]:
    return {
        "version": "headless-empty",
        "groups": {},
        "tags": {},
        "stats": {
            "source": "headless",
            "total": 0,
        },
    }


async def _send_startup_messages(
    ws: WebSocket,
    context: WebSessionContext,
    *,
    session_id: str,
    client_host: str,
) -> None:
    for message in context.initial_websocket_messages(
        session_id=session_id,
        client_host=client_host,
    ):
        await ws.send_text(json.dumps(message, ensure_ascii=False))
    await ws.send_text(json.dumps({"type": "lazy_indices_ready"}))


async def _send_sync_messages(ws: WebSocket, context: WebSessionContext, client_host: str) -> None:
    messages = [
        {"type": "mode", "mode": context.get_api_mode()},
        {"type": "options", **context.get_options()},
        context.generation_param_schema_payload(),
        context.queue_state_payload(),
        context.api_status_payload(client_host),
        {"type": "lazy_indices_ready"},
    ]
    for message in messages:
        await ws.send_text(json.dumps(message, ensure_ascii=False))


async def _broadcast_json(clients: set[WebSocket], data: dict[str, Any]) -> None:
    text = json.dumps(data, ensure_ascii=False)
    dead = []
    for client in list(clients):
        try:
            await client.send_text(text)
        except Exception:
            dead.append(client)
    for client in dead:
        clients.discard(client)


async def _broadcast_image(clients: set[WebSocket], webp_bytes: bytes, metadata: dict[str, Any]) -> None:
    meta_text = json.dumps({"type": "image_meta", **metadata}, ensure_ascii=False)
    dead = []
    for client in list(clients):
        try:
            await client.send_text(meta_text)
            await client.send_bytes(webp_bytes)
        except Exception:
            dead.append(client)
    for client in dead:
        clients.discard(client)


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


def _random_service(context: WebSessionContext) -> HeadlessRandomPromptService:
    service = getattr(context, "headless_random_prompt_service", None)
    if service is None:
        service = HeadlessRandomPromptService(context)
        context.headless_random_prompt_service = service
    return service


def _generation_service(context: WebSessionContext) -> HeadlessGenerationService:
    service = getattr(context, "headless_generation_service", None)
    if service is None:
        service = HeadlessGenerationService(context)
        context.headless_generation_service = service
    return service


def _style_thumbnail_service(context: WebSessionContext) -> StyleThumbnailService:
    service = getattr(context, "style_thumbnail_service", None)
    if service is None:
        service = StyleThumbnailService(context.repo_root)
        context.style_thumbnail_service = service
    return service


def _character_viewer_service(context: WebSessionContext) -> CharacterViewerService:
    service = getattr(context, "character_viewer_service", None)
    if service is None:
        service = CharacterViewerService(context.repo_root)
        context.character_viewer_service = service
    return service


def _artist_thumbnail_service(context: WebSessionContext) -> ArtistThumbnailService:
    service = getattr(context, "artist_thumbnail_service", None)
    if service is None:
        service = ArtistThumbnailService(context.repo_root, mode_getter=context.get_api_mode)
        context.artist_thumbnail_service = service
    return service


def _event_preset_service(context: WebSessionContext) -> EventPresetService:
    service = getattr(context, "event_preset_service", None)
    if service is None:
        service = EventPresetService(context.repo_root)
        context.event_preset_service = service
    return service


def _clothes_preset_service(context: WebSessionContext) -> ClothesPresetService:
    service = getattr(context, "clothes_preset_service", None)
    if service is None:
        service = ClothesPresetService(context.repo_root)
        context.clothes_preset_service = service
    return service


def _expression_preset_service(context: WebSessionContext) -> ExpressionPresetService:
    service = getattr(context, "expression_preset_service", None)
    if service is None:
        service = ExpressionPresetService(context.repo_root)
        context.expression_preset_service = service
    return service


def _preset_composer_service(context: WebSessionContext) -> PresetComposerService:
    service = getattr(context, "preset_composer_service", None)
    if service is None:
        service = PresetComposerService(
            _event_preset_service(context),
            axis_providers={"clothes": _clothes_preset_service(context)},
        )
        context.preset_composer_service = service
    return service


def _event_preset_download_service(context: WebSessionContext) -> EventPresetDownloadService:
    service = getattr(context, "event_preset_download_service", None)
    if service is None:
        def refresh_services() -> None:
            context.event_preset_service = EventPresetService(context.repo_root)
            context.preset_composer_service = PresetComposerService(
                context.event_preset_service,
                axis_providers={"clothes": _clothes_preset_service(context)},
            )

        service = EventPresetDownloadService(
            context.repo_root,
            status_provider=lambda: _event_preset_service(context).status(),
            on_complete=refresh_services,
        )
        context.event_preset_download_service = service
    return service


def _event_preset_status(context: WebSessionContext) -> dict[str, Any]:
    status = _event_preset_service(context).status()
    status["download"] = _event_preset_download_service(context).snapshot()
    return status


def _event_preset_bootstrap(
    context: WebSessionContext,
    rating_id: str = "s",
    person_id: str = "1girl_solo",
    search: str = "",
    category_id: str = "",
    subcategory_id: str = "",
    event_id: str = "",
    limit: int | None = None,
) -> dict[str, Any]:
    payload = _event_preset_service(context).bootstrap(
        rating_id,
        person_id,
        search,
        category_id,
        subcategory_id,
        event_id,
        limit,
    )
    payload["download"] = _event_preset_download_service(context).snapshot()
    return payload


def _preset_source_to_generation_command(
    context: WebSessionContext,
    result: dict[str, Any],
    *,
    source: str,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_row_data = result.get("sourceRow") if isinstance(result.get("sourceRow"), dict) else {}
    if not source_row_data.get("general"):
        raise ValueError("Preset prompt source is empty.")
    request_id = str(result.get("requestId") or uuid.uuid4().hex)
    result["requestId"] = request_id
    generation_overrides = dict(overrides or {})
    result_overrides = result.get("overrides") if isinstance(result.get("overrides"), dict) else {}
    generation_overrides.update(result_overrides)
    generation_overrides.update({
        "input": str(source_row_data.get("general") or ""),
        "_raw_input": str(source_row_data.get("general") or ""),
        "_source_row_data": source_row_data,
        "_source_name": str(result.get("sourceName") or f"{source}:{request_id}"),
        "_remote_queue_source": "Preset",
        "_remote_queue_label": source,
    })
    if source == "event_preset":
        generation_overrides.update({
            "event_preset_request": True,
            "event_preset_request_id": request_id,
        })
    elif source == "preset":
        generation_overrides.update({
            "remote_preset_request": True,
            "remote_preset_request_id": request_id,
        })
    rating = str(source_row_data.get("rating") or "").strip()
    if rating in {"g", "s", "q", "e"}:
        context.set_active_ratings([rating])
    return {
        "type": "generate",
        "api_mode": generation_overrides.get("api_mode") or context.get_api_mode(),
        "prompt": str(source_row_data.get("general") or ""),
        "negative_prompt": (
            str(generation_overrides.get("negative_prompt") or "")
            if "negative_prompt" in generation_overrides
            else str(context.negative_prompt_text or "")
        ),
        "overrides": generation_overrides,
    }


def _preset_prompt_generated_payload(
    context: WebSessionContext,
    result: dict[str, Any],
    *,
    source: str,
) -> dict[str, Any]:
    request_id = str(result.get("requestId") or "")
    source_row_data = result.get("sourceRow") if isinstance(result.get("sourceRow"), dict) else {}
    prompt = str(
        result.get("promptPreview")
        or (result.get("promptPlan") or {}).get("finalPrompt")
        or source_row_data.get("general")
        or ""
    )
    payload: dict[str, Any] = {
        "type": "prompt_generated",
        "source": source,
        "prompt": prompt,
        "requestId": request_id,
        "remaining": context.search_results.get_count() if context.search_results else 0,
        "rating_counts": context.search_state_payload().get("rating_counts", {}),
    }
    if source == "event_preset":
        payload["event_preset_request_id"] = request_id
        payload["selected"] = result.get("selected") or {}
        payload["event"] = result.get("event") or {}
    elif source == "preset":
        payload["remote_preset_request_id"] = request_id
        payload["promptPlan"] = result.get("promptPlan") or {}
    return payload


def _tag_lookup_info(context: WebSessionContext, tag: str) -> dict[str, Any]:
    raw_tags = getattr(context, "kr_tags_raw", None)
    if not isinstance(raw_tags, dict) or not raw_tags:
        from core.kr_tag_loader import load_kr_tag_records
        from core.tag_relation_ranker import TagRelationRanker

        load_result = load_kr_tag_records(context.repo_root)
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


def _normalize_danbooru_browser_url(value: str = "") -> str:
    text = str(value or "").strip()
    if not text:
        return f"{DANBOORU_BASE_URL}/posts?tags=rating%3Ageneral&z=5"
    if text.isdigit():
        return f"{DANBOORU_BASE_URL}/posts/{text}"
    if text.startswith("//"):
        text = "https:" + text
    elif text.startswith("/"):
        text = urljoin(DANBOORU_BASE_URL, text)
    elif re.match(r"^(?:www\.)?danbooru\.donmai\.us(?:/|$)", text, re.IGNORECASE):
        text = "https://" + text
    elif not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", text):
        text = f"{DANBOORU_BASE_URL}/posts?tags={quote(text, safe=':-_~')}"

    parsed = urlparse(text)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or hostname not in {"danbooru.donmai.us", "www.danbooru.donmai.us"}:
        raise ValueError("Danbooru URL, post ID, or tag query is required")
    return text


def _load_characteristic_tags(context: WebSessionContext) -> set[str]:
    path = Path(context.repo_root) / "data" / "characteristic_list.txt"
    try:
        return {
            line.strip().replace("_", " ")
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
    except Exception:
        return set()


def _fallback_danbooru_prompt(tags: dict[str, Any]) -> str:
    general_tags = tags.get("general") if isinstance(tags, dict) and isinstance(tags.get("general"), list) else []
    return ", ".join(map(str, general_tags))


def _danbooru_prompt_preview(context: WebSessionContext, tags: dict[str, Any]) -> str:
    try:
        _random_service(context)._ensure_headless_runtime()
        service = getattr(context, "prompt_generation_service", None)
        settings = {
            "api_mode": context.get_api_mode(),
            "auto_generate": False,
            "prompt_fixed": False,
            "wildcard_standalone": False,
        }
        if service is not None and hasattr(service, "generate_instant_source_silent"):
            prompt = service.generate_instant_source_silent(tags, settings)
            if prompt:
                return str(prompt)
    except Exception as exc:
        print(f"Headless Remote: Danbooru prompt preview failed — {exc}", flush=True)
    return _fallback_danbooru_prompt(tags)


def _build_danbooru_post_payload(context: WebSessionContext, query: str) -> dict[str, Any]:
    post = fetch_danbooru_post(
        query,
        characteristic_tags=_load_characteristic_tags(context),
    )
    post["prompt"] = _danbooru_prompt_preview(context, post.get("tags", {}))
    return post


def _image_media_type(image_bytes: bytes) -> str:
    if image_bytes.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def _character_viewer_thumbnail_payload(
    context: WebSessionContext,
    group: str,
    character: str,
    variant: str = "",
    size: str = "",
) -> tuple[bytes, str]:
    service = _character_viewer_service(context)
    path = service.thumbnail_path(str(group or ""), str(character or ""), str(variant or ""))
    size_key = str(size or "").strip().lower()
    if size_key == "grid":
        cache = getattr(context, "character_viewer_grid_thumb_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            context.character_viewer_grid_thumb_cache = cache
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

    raw = path.read_bytes()
    return raw, _image_media_type(raw)


async def _handle_random_command(
    ws: WebSocket,
    context: WebSessionContext,
    command: dict[str, Any] | None = None,
) -> None:
    command = command if isinstance(command, dict) else {}
    overrides = command.get("overrides") if isinstance(command.get("overrides"), dict) else None
    request_id = str(command.get("random_request_id") or command.get("requestId") or "")
    active_ratings = _active_ratings_from_command(command) or context.get_active_ratings()
    result = await _to_thread(
        _random_service(context).generate,
        active_ratings=active_ratings,
        overrides=overrides,
        random_request_id=request_id,
    )
    await ws.send_text(json.dumps(result.websocket_payload(), ensure_ascii=False))


async def _handle_generate_command(
    ws: WebSocket,
    context: WebSessionContext,
    clients: set[WebSocket],
    command: dict[str, Any] | None = None,
) -> None:
    command = command if isinstance(command, dict) else {}
    result = await _to_thread(_generation_service(context).enqueue_remote_request, command)
    await ws.send_text(json.dumps(result.websocket_payload(), ensure_ascii=False))
    if not result.ok:
        await ws.send_text(json.dumps({
            "type": "toast",
            "level": "error",
            "message": result.blocked_reason,
        }, ensure_ascii=False))
        await ws.send_text(json.dumps({
            "type": "status",
            "is_generating": False,
            "message": "blocked",
        }, ensure_ascii=False))
        return
    await ws.send_text(json.dumps({
        "type": "status",
        "is_generating": False,
        "message": "queued",
    }, ensure_ascii=False))
    await ws.send_text(json.dumps(context.queue_state_payload(), ensure_ascii=False))
    if context.headless_generation_execute_enabled:
        _ensure_generation_runner(context, clients)


async def _enqueue_prompt_from_module(
    ws: WebSocket,
    context: WebSessionContext,
    clients: set[WebSocket],
    *,
    prompt: str,
    source: str,
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
    result = await _to_thread(_generation_service(context).enqueue_remote_request, command)
    await ws.send_text(json.dumps(result.websocket_payload(), ensure_ascii=False))
    if not result.ok:
        await ws.send_text(json.dumps({
            "type": "toast",
            "level": "error",
            "message": result.blocked_reason,
        }, ensure_ascii=False))
        return
    await ws.send_text(json.dumps({
        "type": "status",
        "is_generating": False,
        "message": "queued",
    }, ensure_ascii=False))
    await ws.send_text(json.dumps(context.queue_state_payload(), ensure_ascii=False))
    if context.headless_generation_execute_enabled:
        _ensure_generation_runner(context, clients)


def _ensure_generation_runner(context: WebSessionContext, clients: set[WebSocket]) -> None:
    task = getattr(context, "headless_generation_runner_task", None)
    if task is not None and not task.done():
        return
    context.headless_generation_runner_task = asyncio.create_task(_run_generation_queue(context, clients))


async def _run_generation_queue(context: WebSessionContext, clients: set[WebSocket]) -> None:
    if getattr(context, "headless_generation_runner_active", False):
        return
    context.headless_generation_runner_active = True
    try:
        while True:
            request = await _to_thread(context.generation_queue_manager.dequeue_request)
            if request is None:
                break
            context.is_generating = True
            await _broadcast_json(clients, {"type": "status", "is_generating": True, "message": "generating"})
            await _broadcast_json(clients, context.queue_state_payload())
            try:
                stored = await _to_thread(_generation_service(context).execute_request, request)
            except Exception as exc:
                context.is_generating = False
                message = str(exc)
                params = getattr(request, "params", {}) or {}
                await _broadcast_json(clients, {"type": "status", "is_generating": False, "message": "error"})
                await _broadcast_json(clients, {"type": "toast", "level": "error", "message": message})
                await _broadcast_json(clients, {"type": "generation_error", "message": message})
                if params.get("event_preset_request"):
                    await _broadcast_json(clients, {
                        "type": "event_preset_generation_error",
                        "requestId": str(params.get("event_preset_request_id") or ""),
                        "message": message,
                    })
                if params.get("remote_preset_request"):
                    await _broadcast_json(clients, {
                        "type": "preset_generation_error",
                        "requestId": str(params.get("remote_preset_request_id") or ""),
                        "message": message,
                    })
                await _broadcast_json(clients, context.queue_state_payload())
                continue

            context.is_generating = False
            await _broadcast_json(clients, {"type": "status", "is_generating": False, "message": "completed"})
            await _broadcast_image(clients, stored.item.webp_bytes, stored.image_meta)
            await _broadcast_json(clients, context.result_store.viewer_new_image_payload(stored.item))
            await _broadcast_json(clients, context.queue_state_payload())
    finally:
        context.is_generating = False
        context.headless_generation_runner_active = False


async def _handle_json_command(
    ws: WebSocket,
    context: WebSessionContext,
    clients: set[WebSocket],
    client_host: str,
    command: dict[str, Any],
) -> None:
    command_type = str(command.get("type") or "").strip()
    if command_type == "sync":
        await _send_sync_messages(ws, context, client_host)
    elif command_type == "set_option":
        context.set_option(str(command.get("key") or ""), command.get("value"))
        await _broadcast_json(clients, {"type": "options", **context.get_options()})
    elif command_type == "set_mode":
        requested_mode = str(command.get("mode") or "").strip().upper()
        if requested_mode not in {"NAI", "WEBUI", "COMFYUI"}:
            await ws.send_text(json.dumps({
                "type": "mode_result",
                "success": False,
                "mode": requested_mode,
                "message": f"Unknown mode: {requested_mode}",
            }, ensure_ascii=False))
            return
        token_key = {
            "NAI": "nai_token",
            "WEBUI": "webui_url",
            "COMFYUI": "comfyui_url",
        }[requested_mode]
        if not str(context.secure_token_manager.get_token(token_key) or ""):
            await ws.send_text(json.dumps({
                "type": "mode_result",
                "success": False,
                "mode": requested_mode,
                "message": f"{requested_mode} API is not connected",
            }, ensure_ascii=False))
            await ws.send_text(json.dumps(context.api_status_payload(client_host), ensure_ascii=False))
            return
        context.set_api_mode(requested_mode)
        await _broadcast_json(clients, {
            "type": "mode_result",
            "success": True,
            "mode": context.get_api_mode(),
            "message": f"{context.get_api_mode()} mode active",
        })
        await _broadcast_json(clients, {"type": "mode", "mode": context.get_api_mode()})
        await _broadcast_json(clients, context.generation_param_schema_payload())
        await ws.send_text(json.dumps(context.api_status_payload(client_host), ensure_ascii=False))
    elif command_type == "set_prompt":
        context.prompt_text = str(command.get("prompt") or "")
        context.negative_prompt_text = str(command.get("negative") or "")
        await ws.send_text(json.dumps({
            "type": "prompt_sync",
            "prompt": context.prompt_text,
            "negative": context.negative_prompt_text,
        }, ensure_ascii=False))
    elif command_type == "set_param":
        context.set_param(str(command.get("key") or ""), command.get("value"))
        await _broadcast_json(clients, context.generation_param_schema_payload())
    elif command_type == "set_active_ratings":
        context.set_active_ratings(command.get("ratings"))
        await ws.send_text(json.dumps(context.search_state_payload(), ensure_ascii=False))
    elif command_type == "probe_api":
        allowed, reason = context.setup_gate(client_host)
        if not allowed:
            await ws.send_text(json.dumps({
                "type": "setup_blocked",
                "command": "probe_api",
                "reason": reason,
            }, ensure_ascii=False))
            return
        results = await _to_thread(context.probe_api)
        await ws.send_text(json.dumps({
            "type": "probe_result",
            "command": "probe_api",
            "results": results,
        }, ensure_ascii=False))
    elif command_type in {"verify_nai", "verify_webui", "verify_comfyui"}:
        allowed, reason = context.setup_gate(client_host)
        if not allowed:
            await ws.send_text(json.dumps({
                "type": "setup_blocked",
                "command": command_type,
                "reason": reason,
            }, ensure_ascii=False))
            return
        mode = {
            "verify_nai": "NAI",
            "verify_webui": "WEBUI",
            "verify_comfyui": "COMFYUI",
        }[command_type]
        raw_value = command.get("token") if mode == "NAI" else command.get("url")
        result = await _to_thread(context.verify_api, mode, str(raw_value or ""))
        await ws.send_text(json.dumps(result, ensure_ascii=False))
        await ws.send_text(json.dumps(context.api_status_payload(client_host), ensure_ascii=False))
    elif command_type == "clear_api":
        allowed, reason = context.setup_gate(client_host)
        if not allowed:
            await ws.send_text(json.dumps({
                "type": "setup_blocked",
                "command": command_type,
                "reason": reason,
            }, ensure_ascii=False))
            return
        result = await _to_thread(context.clear_api, str(command.get("mode") or ""))
        await ws.send_text(json.dumps(result, ensure_ascii=False))
        await ws.send_text(json.dumps(context.api_status_payload(client_host), ensure_ascii=False))
    elif command_type == "set_cloudflared_enabled":
        allowed, reason = context.cloudflared_gate(client_host)
        if not allowed:
            await ws.send_text(json.dumps({
                "type": "toast",
                "level": "error",
                "message": reason,
                "reason": reason,
            }, ensure_ascii=False))
            return
        result = await _to_thread(context.set_cloudflared_enabled, bool(command.get("enabled", False)))
        if not result.get("success", False):
            await ws.send_text(json.dumps({
                "type": "toast",
                "level": "error",
                "message": result.get("error") or result.get("status_text") or "Cloudflared failed",
            }, ensure_ascii=False))
        await ws.send_text(json.dumps(context.api_status_payload(client_host), ensure_ascii=False))
    elif command_type == "get_search_state":
        await ws.send_text(json.dumps(context.search_state_payload(), ensure_ascii=False))
    elif command_type == "read_hires_preset_overlay":
        preset_name = str(command.get("preset_name") or "")
        response = await _to_thread(context.hires_overlay_response, preset_name)
        await ws.send_text(json.dumps(response, ensure_ascii=False))
    elif command_type == "write_hires_preset_overlay":
        preset_name = str(command.get("preset_name") or "")
        action = str(command.get("action") or "save")
        if action == "reset":
            ok, message = await _to_thread(context.reset_hires_overlay, preset_name)
        else:
            body = command.get("body") if isinstance(command.get("body"), dict) else {}
            ok, message = await _to_thread(context.write_hires_overlay, preset_name, body)
        await ws.send_text(json.dumps({
            "type": "toast",
            "level": "success" if ok else "error",
            "message": message,
            "headless": True,
        }, ensure_ascii=False))
        if ok:
            response = await _to_thread(context.hires_overlay_response, preset_name)
            await ws.send_text(json.dumps(response, ensure_ascii=False))
    elif command_type == "set_module_param":
        module_state = context.set_module_param(
            str(command.get("module_id") or ""),
            str(command.get("key") or ""),
            command.get("value"),
            client_host=client_host,
        )
        if module_state is None:
            await ws.send_text(json.dumps({
                "type": "toast",
                "level": "info",
                "message": "Headless command retired: set_module_param",
                "headless": True,
            }, ensure_ascii=False))
        elif isinstance(module_state, list):
            generated_prompt = ""
            generated_source = ""
            for item in module_state:
                if isinstance(item, dict):
                    await ws.send_text(json.dumps(item, ensure_ascii=False))
                    if item.get("type") == "prompt_generated" and item.get("source") == "e621_event":
                        generated_prompt = str(item.get("prompt") or "")
                        generated_source = "E621"
            if generated_prompt:
                await _enqueue_prompt_from_module(
                    ws,
                    context,
                    clients,
                    prompt=generated_prompt,
                    source=generated_source,
                )
        else:
            await ws.send_text(json.dumps(module_state, ensure_ascii=False))
    elif command_type == "get_module_state":
        module_id = str(command.get("module_id") or "")
        await ws.send_text(json.dumps(context.module_state_payload(module_id, client_host), ensure_ascii=False))
    elif command_type == "result_upscale":
        await ws.send_text(json.dumps({
            "type": "result_upscale_state",
            "running": False,
            "success": False,
            "message": "NAI 2x upscale is not available in the headless runtime yet.",
            "headless": True,
        }, ensure_ascii=False))
        await ws.send_text(json.dumps({
            "type": "toast",
            "level": "info",
            "message": "Headless command retired: result_upscale",
            "headless": True,
        }, ensure_ascii=False))
    elif command_type == "result_enhance":
        await ws.send_text(json.dumps({
            "type": "result_enhance_state",
            "running": False,
            "success": False,
            "message": "Result enhance is not available in the headless runtime yet.",
            "headless": True,
        }, ensure_ascii=False))
        await ws.send_text(json.dumps({
            "type": "toast",
            "level": "info",
            "message": "Headless command retired: result_enhance",
            "headless": True,
        }, ensure_ascii=False))
    elif command_type == "set_result_enhance_config":
        await ws.send_text(json.dumps({
            "type": "result_enhance_config",
            "upscale": command.get("upscale", 1.5),
            "strength": command.get("strength", 0.2),
            "noise": command.get("noise", 0.0),
            "available": False,
            "headless": True,
        }, ensure_ascii=False))
    elif command_type == "result_image_action":
        action = str(command.get("action") or "image_action")
        await ws.send_text(json.dumps({
            "type": "toast",
            "level": "info",
            "message": f"Headless command retired: result_image_action/{action}",
            "headless": True,
        }, ensure_ascii=False))
    elif command_type == "random":
        await _handle_random_command(ws, context, command)
    elif command_type == "generate":
        await _handle_generate_command(ws, context, clients, command)
    else:
        await ws.send_text(json.dumps({
            "type": "toast",
            "level": "info",
            "message": f"Headless command ignored: {command_type or 'unknown'}",
        }, ensure_ascii=False))


async def _handle_text_command(
    ws: WebSocket,
    context: WebSessionContext,
    clients: set[WebSocket],
    client_host: str,
    data: str,
) -> None:
    if data == "sync":
        await _send_sync_messages(ws, context, client_host)
        return
    if data == "random":
        await _handle_random_command(ws, context)
        return
    if data == "generate":
        await _handle_generate_command(ws, context, clients)
        return
    await ws.send_text(json.dumps({
        "type": "toast",
        "level": "info",
        "message": f"Headless command ignored: {data}",
    }, ensure_ascii=False))


async def _to_thread(func, /, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)


def create_headless_app(
    context: WebSessionContext | None = None,
    *,
    web_dir: Path | str | None = None,
) -> FastAPI:
    """Create the PyQt-free Remote Web FastAPI app."""

    session_context = context or WebSessionContext()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        async def run_warmup() -> None:
            try:
                ok = await _to_thread(_random_service(session_context).warmup)
                session_context.headless_random_warmup_done = bool(ok)
                print(
                    "Headless Remote: random prompt runtime warmup "
                    + ("ready" if ok else "finished without search rows"),
                    flush=True,
                )
            except Exception as exc:
                session_context.headless_random_warmup_error = str(exc)
                print(f"Headless Remote: random prompt runtime warmup failed - {exc}", flush=True)

        task = getattr(session_context, "headless_random_warmup_task", None)
        if task is None or task.done():
            session_context.headless_random_warmup_task = asyncio.create_task(run_warmup())
        yield

    app = FastAPI(title="NAIA Remote Headless", lifespan=lifespan)
    app.state.web_session_context = session_context
    app.state.headless_clients = set()

    root_web_dir = Path(web_dir) if web_dir is not None else Path(__file__).resolve().parent.parent / "ui" / "remote_web"
    mimetypes.add_type("text/javascript", ".mjs")

    js_dir = root_web_dir / "js"
    if js_dir.exists():
        app.mount("/js", StaticFiles(directory=str(js_dir)), name="remote_js")
    guides_dir = root_web_dir / "guides"
    if guides_dir.exists():
        app.mount("/guides", StaticFiles(directory=str(guides_dir), html=True), name="remote_guides")

    @app.get("/")
    async def index():
        return _web_file(root_web_dir / "index.html", "text/html")

    @app.get("/style.css")
    async def serve_css():
        return _web_file(root_web_dir / "style.css", "text/css")

    @app.get("/app.js")
    async def serve_js():
        return _web_file(root_web_dir / "app.js", "application/javascript")

    @app.get("/api/status")
    async def api_status():
        return session_context.http_status_payload()

    @app.get("/api/queue/state")
    async def api_queue_state():
        return session_context.queue_state_payload()

    @app.get("/api/prompt-highlight-index")
    async def api_prompt_highlight_index():
        return Response(
            content=json.dumps(_prompt_highlight_empty_index(), ensure_ascii=False),
            media_type="application/json",
            headers=_no_cache_headers(),
        )

    @app.get("/api/headless/capabilities")
    async def api_headless_capabilities():
        return {
            "headless": True,
            "right_tabs": {
                "result": True,
                "pngInfo": True,
                "thumb": True,
                "artists": True,
                "characters": True,
                "studio": True,
                "settings": False,
            },
            "retired_tabs": {},
        }

    @app.get("/api/event-preset/status")
    async def api_event_preset_status():
        try:
            return await _to_thread(_event_preset_status, session_context)
        except Exception as exc:
            return JSONResponse({"error": f"Event Preset status failed: {exc}"}, status_code=500)

    @app.get("/api/event-preset/download")
    async def api_event_preset_download_state():
        try:
            return await _to_thread(_event_preset_download_service(session_context).snapshot)
        except Exception as exc:
            return JSONResponse({"error": f"Event Preset download state failed: {exc}"}, status_code=500)

    @app.post("/api/event-preset/download")
    async def api_event_preset_download():
        try:
            return await _to_thread(_event_preset_download_service(session_context).start)
        except Exception as exc:
            return JSONResponse({"error": f"Event Preset download failed: {exc}"}, status_code=500)

    @app.post("/api/event-preset/download/cancel")
    async def api_event_preset_download_cancel():
        try:
            return await _to_thread(_event_preset_download_service(session_context).cancel)
        except Exception as exc:
            return JSONResponse({"error": f"Event Preset download cancel failed: {exc}"}, status_code=500)

    @app.get("/api/tag/lookup")
    async def api_tag_lookup(tag: str = ""):
        try:
            return await _to_thread(_tag_lookup_info, session_context, tag)
        except Exception as exc:
            return JSONResponse({"error": f"Tag lookup failed: {exc}"}, status_code=500)

    @app.post("/api/danbooru/post")
    async def api_danbooru_post(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        query = str(payload.get("query") or req.query_params.get("query") or "").strip()
        try:
            return await _to_thread(_build_danbooru_post_payload, session_context, query)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"Danbooru lookup failed: {exc}"}, status_code=502)

    @app.post("/api/danbooru/browser/open")
    async def api_danbooru_browser_open(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        query = str(payload.get("url") or payload.get("query") or req.query_params.get("url") or "").strip()
        try:
            target_url = _normalize_danbooru_browser_url(query)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return {"ok": True, "url": target_url, "headless": True, "open_external": True}

    @app.get("/api/event-preset/bootstrap")
    async def api_event_preset_bootstrap(
        ratingId: str = "s",
        personId: str = "1girl_solo",
        search: str = "",
        categoryId: str = "",
        subcategoryId: str = "",
        eventId: str = "",
        limit: int = 0,
    ):
        try:
            return await _to_thread(
                _event_preset_bootstrap,
                session_context,
                ratingId,
                personId,
                search,
                categoryId,
                subcategoryId,
                eventId,
                limit or None,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"Event Preset bootstrap failed: {exc}"}, status_code=500)

    @app.post("/api/event-preset/select")
    async def api_event_preset_select(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await _to_thread(_event_preset_service(session_context).select, payload)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Event Preset select failed: {exc}"}, status_code=500)

    @app.post("/api/event-preset/prompt-preview")
    async def api_event_preset_prompt_preview(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await _to_thread(_event_preset_service(session_context).prompt_preview, payload)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"Event Preset prompt preview failed: {exc}"}, status_code=500)

    @app.post("/api/preset/prompt-preview")
    async def api_preset_prompt_preview(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await _to_thread(_preset_composer_service(session_context).prompt_preview, payload)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"Preset prompt preview failed: {exc}"}, status_code=500)

    @app.post("/api/preset/generate")
    async def api_preset_generate(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            result = await _to_thread(_preset_composer_service(session_context).generation_source, payload)
            command = _preset_source_to_generation_command(
                session_context,
                result,
                source="preset",
                overrides=payload.get("overrides") if isinstance(payload.get("overrides"), dict) else {},
            )
            dispatch = await _to_thread(_generation_service(session_context).enqueue_remote_request, command)
        except RuntimeError as exc:
            return JSONResponse({"error": str(exc)}, status_code=409)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Preset generate failed: {exc}"}, status_code=500)
        if not dispatch.ok:
            return JSONResponse(dispatch.websocket_payload(), status_code=409)
        await _broadcast_json(
            app.state.headless_clients,
            _preset_prompt_generated_payload(session_context, result, source="preset"),
        )
        if session_context.headless_generation_execute_enabled:
            _ensure_generation_runner(session_context, app.state.headless_clients)
        return {
            "ok": True,
            "status": "generation_requested",
            "requestId": result.get("requestId") or dispatch.request_id,
            "promptPlan": result.get("promptPlan") or {},
        }

    @app.get("/api/clothes-preset/status")
    async def api_clothes_preset_status():
        try:
            return await _to_thread(_clothes_preset_service(session_context).status)
        except Exception as exc:
            return JSONResponse({"error": f"Clothes Preset status failed: {exc}"}, status_code=500)

    @app.post("/api/clothes-preset/bootstrap")
    async def api_clothes_preset_bootstrap(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await _to_thread(_clothes_preset_service(session_context).bootstrap, payload)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"Clothes Preset bootstrap failed: {exc}"}, status_code=500)

    @app.post("/api/clothes-preset/select")
    async def api_clothes_preset_select(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await _to_thread(_clothes_preset_service(session_context).select, payload)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"Clothes Preset select failed: {exc}"}, status_code=500)

    @app.post("/api/clothes-preset/lucky")
    async def api_clothes_preset_lucky(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await _to_thread(_clothes_preset_service(session_context).lucky, payload)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"Clothes Preset lucky failed: {exc}"}, status_code=500)

    @app.post("/api/clothes-preset/prompt-fragment")
    async def api_clothes_preset_prompt_fragment(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await _to_thread(_clothes_preset_service(session_context).prompt_fragment, payload)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"Clothes Preset prompt fragment failed: {exc}"}, status_code=500)

    @app.get("/api/expression-preset/status")
    async def api_expression_preset_status():
        try:
            return await _to_thread(_expression_preset_service(session_context).status)
        except Exception as exc:
            return JSONResponse({"error": f"Expression Preset status failed: {exc}"}, status_code=500)

    @app.post("/api/expression-preset/bootstrap")
    async def api_expression_preset_bootstrap(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await _to_thread(_expression_preset_service(session_context).bootstrap, payload)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"Expression Preset bootstrap failed: {exc}"}, status_code=500)

    @app.post("/api/event-preset/generate")
    async def api_event_preset_generate(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            result = await _to_thread(_event_preset_service(session_context).generation_source, payload)
            command = _preset_source_to_generation_command(
                session_context,
                result,
                source="event_preset",
                overrides=payload.get("overrides") if isinstance(payload.get("overrides"), dict) else {},
            )
            dispatch = await _to_thread(_generation_service(session_context).enqueue_remote_request, command)
        except RuntimeError as exc:
            return JSONResponse({"error": str(exc)}, status_code=409)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Event Preset generate failed: {exc}"}, status_code=500)
        if not dispatch.ok:
            return JSONResponse(dispatch.websocket_payload(), status_code=409)
        await _broadcast_json(
            app.state.headless_clients,
            _preset_prompt_generated_payload(session_context, result, source="event_preset"),
        )
        if session_context.headless_generation_execute_enabled:
            _ensure_generation_runner(session_context, app.state.headless_clients)
        return {
            "ok": True,
            "status": "generation_requested",
            "requestId": result.get("requestId") or dispatch.request_id,
            "selected": result.get("selected") or {},
            "promptPreview": result.get("promptPreview") or "",
            "event": result.get("event") or {},
        }

    @app.get("/api/event-preset/thumbnail")
    async def api_event_preset_thumbnail(eventId: str = "", tag: str = "", size: str = ""):
        try:
            image_bytes, media_type = await _to_thread(
                _event_preset_service(session_context).thumbnail_payload,
                eventId,
                tag,
                size,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except (FileNotFoundError, KeyError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Event Preset thumbnail failed: {exc}"}, status_code=500)
        return Response(
            content=image_bytes,
            media_type=media_type,
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @app.get("/api/artist-thumb/state")
    async def api_artist_thumb_state():
        try:
            return await _to_thread(_artist_thumbnail_service(session_context).state)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb state failed: {exc}"}, status_code=500)

    @app.get("/api/artist-thumb/list")
    async def api_artist_thumb_list(
        mode: str = "",
        filter: str = "all",
        query: str = "",
        page: int = 0,
        per_page: int = 48,
        random_sample: bool = False,
    ):
        try:
            return await _to_thread(
                _artist_thumbnail_service(session_context).build_list,
                mode,
                filter,
                query,
                page,
                per_page,
                random_sample,
            )
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb list failed: {exc}"}, status_code=500)

    @app.get("/api/artist-thumb/image")
    async def api_artist_thumb_image(mode: str = "", artist: str = ""):
        try:
            image_bytes, media_type = await _to_thread(
                _artist_thumbnail_service(session_context).image_payload,
                mode,
                artist,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except (FileNotFoundError, KeyError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb image failed: {exc}"}, status_code=500)
        return Response(
            content=image_bytes,
            media_type=media_type,
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @app.get("/api/artist-thumb/favorite-image")
    async def api_artist_thumb_favorite_image(artist: str = ""):
        try:
            image_bytes, media_type = await _to_thread(
                _artist_thumbnail_service(session_context).favorite_image_payload,
                artist,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except (FileNotFoundError, KeyError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb favorite image failed: {exc}"}, status_code=500)
        return Response(
            content=image_bytes,
            media_type=media_type,
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @app.post("/api/artist-thumb/favorite")
    async def api_artist_thumb_favorite(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await _to_thread(
                _artist_thumbnail_service(session_context).set_favorite,
                payload.get("artist", ""),
                bool(payload.get("favorite", True)),
                payload.get("mode", ""),
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb favorite failed: {exc}"}, status_code=500)

    @app.post("/api/artist-thumb/ban")
    async def api_artist_thumb_ban(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await _to_thread(
                _artist_thumbnail_service(session_context).set_banned,
                payload.get("artist", ""),
                bool(payload.get("banned", True)),
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb ban failed: {exc}"}, status_code=500)

    @app.post("/api/artist-thumb/options")
    async def api_artist_thumb_options(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await _to_thread(_artist_thumbnail_service(session_context).save_options, payload)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb options failed: {exc}"}, status_code=500)

    @app.get("/api/artist-thumb/download")
    async def api_artist_thumb_download_state():
        try:
            return await _to_thread(_artist_thumbnail_service(session_context).download_snapshot)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb download state failed: {exc}"}, status_code=500)

    @app.post("/api/artist-thumb/download")
    async def api_artist_thumb_download(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await _to_thread(_artist_thumbnail_service(session_context).start_download, payload.get("mode", ""))
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb download failed: {exc}"}, status_code=500)

    @app.post("/api/artist-thumb/download/cancel")
    async def api_artist_thumb_download_cancel():
        try:
            return await _to_thread(_artist_thumbnail_service(session_context).cancel_download)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb download cancel failed: {exc}"}, status_code=500)

    @app.post("/api/artist-thumb/random-prompt")
    async def api_artist_thumb_random_prompt(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        artist_prompt = str(payload.get("artist_prompt") or "").strip()
        if not artist_prompt:
            return JSONResponse({"error": "artist_prompt is required"}, status_code=400)
        try:
            from core.prompt_engineering_settings import get_prompt_engineering_store

            module_settings = get_prompt_engineering_store(session_context).collect_settings(
                session_context.get_api_mode()
            )
            peng_override = await _to_thread(
                _artist_thumbnail_service(session_context).random_prompt_override,
                artist_prompt,
                module_settings,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"Artist Thumb random prompt setup failed: {exc}"}, status_code=500)

        request_id = str(uuid.uuid4())
        previous_override = getattr(session_context, "session_p_eng_override", None)
        session_context.session_p_eng_override = peng_override
        try:
            result = await _to_thread(
                _random_service(session_context).generate,
                active_ratings=session_context.get_active_ratings(),
                overrides={"auto_generate": False},
                random_request_id=request_id,
            )
        finally:
            if getattr(session_context, "session_p_eng_override", None) is peng_override:
                session_context.session_p_eng_override = previous_override
        if not result.success:
            return JSONResponse(result.websocket_payload(), status_code=500)
        return {
            "request_id": request_id,
            "prompt": result.prompt,
            "negative_prompt": session_context.negative_prompt_text,
            "remaining": result.remaining,
            "source": "artist_thumb_random",
            "detected_resolution": result.detected_resolution,
        }

    @app.post("/api/artist-thumb/generate")
    async def api_artist_thumb_generate(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            overrides = await _to_thread(
                _artist_thumbnail_service(session_context).generation_overrides,
                payload,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        dispatch = await _to_thread(
            _generation_service(session_context).enqueue_remote_request,
            {
                "type": "generate",
                "api_mode": overrides.get("api_mode") or session_context.get_api_mode(),
                "overrides": overrides,
            },
        )
        if not dispatch.ok:
            return JSONResponse(dispatch.websocket_payload(), status_code=409)
        if session_context.headless_generation_execute_enabled:
            _ensure_generation_runner(session_context, app.state.headless_clients)
        return {"ok": True, **dispatch.websocket_payload()}

    @app.get("/api/thumb/state")
    async def api_thumb_state():
        try:
            return await _to_thread(_style_thumbnail_service(session_context).state)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Thumb state failed: {exc}"}, status_code=500)

    @app.get("/api/thumb/category/{category_key}")
    async def api_thumb_category(category_key: str):
        try:
            return await _to_thread(_style_thumbnail_service(session_context).category_payload, category_key)
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Thumb category failed: {exc}"}, status_code=500)

    @app.get("/api/thumb/image")
    async def api_thumb_image(tag: str = ""):
        try:
            image_bytes, media_type = await _to_thread(_style_thumbnail_service(session_context).image_payload, tag)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Thumb image failed: {exc}"}, status_code=500)
        return Response(
            content=image_bytes,
            media_type=media_type,
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @app.get("/api/character-viewer/state")
    async def api_character_viewer_state():
        try:
            state = await _to_thread(_character_viewer_service(session_context).state)
            state["generation_delay_ms"] = 500
            return state
        except Exception as exc:
            return JSONResponse({"error": f"Character Viewer state failed: {exc}"}, status_code=500)

    @app.get("/api/character-viewer/groups")
    async def api_character_viewer_groups(query: str = ""):
        try:
            return await _to_thread(_character_viewer_service(session_context).build_groups, query)
        except Exception as exc:
            return JSONResponse({"error": f"Character Viewer groups failed: {exc}"}, status_code=500)

    @app.get("/api/character-viewer/list")
    async def api_character_viewer_list(
        group: str = "",
        query: str = "",
        page: int = 0,
        per_page: int = 48,
        thumb_first: bool = True,
        include_all: bool = False,
    ):
        try:
            group_key = str(group or CharacterViewerService.GROUP_ALL)
            return await _to_thread(
                _character_viewer_service(session_context).build_list,
                group_key,
                query,
                page,
                per_page,
                thumb_first,
                include_all,
            )
        except Exception as exc:
            return JSONResponse({"error": f"Character Viewer list failed: {exc}"}, status_code=500)

    @app.post("/api/character-viewer/detail")
    async def api_character_viewer_detail(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await _to_thread(
                _character_viewer_service(session_context).build_detail,
                str(payload.get("group") or ""),
                str(payload.get("character") or ""),
                str(payload.get("variant") or ""),
                payload.get("options") if isinstance(payload.get("options"), dict) else {},
                session_context.get_api_mode(),
            )
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Character Viewer detail failed: {exc}"}, status_code=500)

    @app.post("/api/character-viewer/prompt")
    async def api_character_viewer_prompt(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await _to_thread(
                _character_viewer_service(session_context).build_prompt,
                str(payload.get("group") or ""),
                str(payload.get("character") or ""),
                str(payload.get("variant") or ""),
                payload.get("options") if isinstance(payload.get("options"), dict) else payload,
                session_context.get_api_mode(),
            )
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Character Viewer prompt failed: {exc}"}, status_code=500)

    @app.post("/api/character-viewer/options")
    async def api_character_viewer_options(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await _to_thread(_character_viewer_service(session_context).save_options, payload)
        except Exception as exc:
            return JSONResponse({"error": f"Character Viewer options failed: {exc}"}, status_code=500)

    @app.get("/api/character-viewer/thumbnail")
    async def api_character_viewer_thumbnail(group: str = "", character: str = "", variant: str = "", size: str = ""):
        try:
            image_bytes, media_type = await _to_thread(
                _character_viewer_thumbnail_payload,
                session_context,
                group,
                character,
                variant,
                size,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except (FileNotFoundError, KeyError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Character Viewer thumbnail failed: {exc}"}, status_code=500)
        return Response(
            content=image_bytes,
            media_type=media_type,
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @app.post("/api/character-viewer/generate")
    async def api_character_viewer_generate(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            overrides = await _to_thread(
                _character_viewer_service(session_context).build_generation_overrides,
                payload,
                session_context.get_api_mode(),
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        dispatch = await _to_thread(
            _generation_service(session_context).enqueue_remote_request,
            {"type": "generate", "overrides": overrides},
        )
        if not dispatch.ok:
            return JSONResponse(dispatch.websocket_payload(), status_code=409)
        if session_context.headless_generation_execute_enabled:
            _ensure_generation_runner(session_context, app.state.headless_clients)
        return {"ok": True, **dispatch.websocket_payload()}

    @app.get("/api/latest-image")
    async def api_latest_image():
        try:
            image_bytes, media_type = session_context.result_store.latest_image_payload()
        except FileNotFoundError:
            return JSONResponse({"error": "No image generated yet"}, status_code=404)
        return Response(
            content=image_bytes,
            media_type=media_type,
            headers={"Content-Disposition": result_images.download_content_disposition("naia_latest.webp")},
        )

    @app.get("/api/result/image/png")
    async def api_result_image_png():
        try:
            png_bytes, filename = session_context.result_store.current_png_payload()
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        return Response(
            content=png_bytes,
            media_type="image/png",
            headers={"Content-Disposition": result_images.download_content_disposition(filename)},
        )

    @app.get("/api/result/metadata")
    async def api_result_metadata():
        payload = session_context.result_store.latest_metadata_payload
        if payload is None:
            return JSONResponse({"error": "No image generated yet"}, status_code=404)
        return payload

    @app.get("/api/history/list")
    async def api_history_list(page: int = 0, per_page: int = 30):
        return session_context.result_store.history_list(page=page, per_page=per_page)

    @app.get("/api/history/image/{history_id}")
    async def api_history_image(history_id: str):
        try:
            image_bytes, media_type = session_context.result_store.history_image_payload(history_id)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        return Response(content=image_bytes, media_type=media_type)

    @app.get("/api/history/thumb/{history_id}")
    async def api_history_thumb(history_id: str, size: int = 0):
        try:
            thumb_bytes = session_context.result_store.history_thumb_payload(history_id, size)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        return Response(content=thumb_bytes, media_type="image/webp")

    @app.get("/api/history/meta/{history_id}")
    async def api_history_meta(history_id: str, full: bool = False):
        try:
            return session_context.result_store.history_meta_payload(history_id, include_full=full)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)

    @app.post("/api/history/unsaved/save-all")
    async def api_history_unsaved_save_all():
        try:
            return session_context.save_unsaved_history()
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)

    @app.get("/api/history/unsaved/download")
    async def api_history_unsaved_download():
        try:
            zip_bytes, filename = session_context.result_store.unsaved_zip_payload()
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        return Response(
            content=zip_bytes,
            media_type="application/zip",
            headers={"Content-Disposition": result_images.download_content_disposition(filename)},
        )

    @app.post("/api/result/open-location")
    async def api_result_open_location():
        return JSONResponse({
            "error": "Open location is a desktop-only action in the headless runtime.",
            "headless": True,
        }, status_code=400)

    @app.post("/api/result/action/reroll")
    async def api_result_action_reroll():
        return JSONResponse({
            "error": "Result reroll from saved desktop state is not available in the headless runtime yet.",
            "headless": True,
        }, status_code=400)

    @app.post("/api/result/action/queue")
    async def api_result_action_queue():
        return JSONResponse({
            "error": "Result queue replay from saved desktop state is not available in the headless runtime yet.",
            "headless": True,
        }, status_code=400)

    @app.post("/api/result/action/save")
    async def api_result_action_save():
        return JSONResponse({
            "error": "Desktop result save action is retired; use auto-save or unsaved history save-all.",
            "headless": True,
        }, status_code=400)

    @app.post("/api/result/action/delete")
    async def api_result_action_delete():
        return JSONResponse({
            "error": "Desktop result delete action is retired in the headless runtime.",
            "headless": True,
        }, status_code=400)

    @app.post("/api/image-action/{action}")
    async def api_image_action(action: str):
        return JSONResponse({
            "error": f"Image action '{action}' is desktop-only in the headless runtime.",
            "headless": True,
        }, status_code=400)

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await ws.accept()
        clients: set[WebSocket] = app.state.headless_clients
        clients.add(ws)
        session_id = uuid.uuid4().hex[:8]
        client_host = _client_host(ws)
        try:
            await _send_startup_messages(
                ws,
                session_context,
                session_id=session_id,
                client_host=client_host,
            )
            while True:
                data = await ws.receive_text()
                if data.startswith("{"):
                    try:
                        command = json.loads(data)
                    except json.JSONDecodeError:
                        command = {"type": ""}
                    if isinstance(command, dict):
                        await _handle_json_command(ws, session_context, clients, client_host, command)
                    else:
                        await _handle_text_command(ws, session_context, clients, client_host, data)
                else:
                    await _handle_text_command(ws, session_context, clients, client_host, data)
        except WebSocketDisconnect:
            clients.discard(ws)
            return
        finally:
            clients.discard(ws)

    return app


__all__ = ["create_headless_app"]
