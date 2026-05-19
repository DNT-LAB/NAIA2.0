"""PyQt-free FastAPI app for the headless Remote Web Session path."""

from __future__ import annotations

import json
import asyncio
import mimetypes
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from core.headless_generation_service import HeadlessGenerationService
from core.headless_random_prompt_service import HeadlessRandomPromptService
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


async def _handle_random_command(
    ws: WebSocket,
    context: WebSessionContext,
    command: dict[str, Any] | None = None,
) -> None:
    command = command if isinstance(command, dict) else {}
    overrides = command.get("overrides") if isinstance(command.get("overrides"), dict) else None
    request_id = str(command.get("random_request_id") or command.get("requestId") or "")
    result = await _to_thread(
        _random_service(context).generate,
        active_ratings=_active_ratings_from_command(command),
        overrides=overrides,
        random_request_id=request_id,
    )
    await ws.send_text(json.dumps(result.websocket_payload(), ensure_ascii=False))


async def _handle_generate_command(
    ws: WebSocket,
    context: WebSessionContext,
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


async def _handle_json_command(
    ws: WebSocket,
    context: WebSessionContext,
    client_host: str,
    command: dict[str, Any],
) -> None:
    command_type = str(command.get("type") or "").strip()
    if command_type == "sync":
        await _send_sync_messages(ws, context, client_host)
    elif command_type == "set_option":
        context.set_option(str(command.get("key") or ""), command.get("value"))
        await ws.send_text(json.dumps({"type": "options", **context.get_options()}))
    elif command_type == "set_mode":
        context.set_api_mode(str(command.get("mode") or ""))
        await ws.send_text(json.dumps({"type": "mode", "mode": context.get_api_mode()}))
        await ws.send_text(json.dumps(context.api_status_payload(client_host), ensure_ascii=False))
    elif command_type == "set_prompt":
        context.prompt_text = str(command.get("prompt") or "")
        context.negative_prompt_text = str(command.get("negative") or "")
        await ws.send_text(json.dumps({
            "type": "prompt_sync",
            "prompt": context.prompt_text,
            "negative": context.negative_prompt_text,
        }, ensure_ascii=False))
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
        await ws.send_text(json.dumps({
            "type": "search_state",
            "count": 0,
            "active_ratings": ["g", "s", "q", "e"],
            "rating_counts": {},
            "filter_preferences": {},
        }, ensure_ascii=False))
    elif command_type == "get_module_state":
        module_id = str(command.get("module_id") or "")
        await ws.send_text(json.dumps({
            "type": "module_state",
            "module_id": module_id,
            "available": False,
            "headless": True,
            "state": {},
        }, ensure_ascii=False))
    elif command_type == "random":
        await _handle_random_command(ws, context, command)
    elif command_type == "generate":
        await _handle_generate_command(ws, context, command)
    else:
        await ws.send_text(json.dumps({
            "type": "toast",
            "level": "info",
            "message": f"Headless command ignored: {command_type or 'unknown'}",
        }, ensure_ascii=False))


async def _handle_text_command(
    ws: WebSocket,
    context: WebSessionContext,
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
        await _handle_generate_command(ws, context)
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
    app = FastAPI(title="NAIA Remote Headless")
    app.state.web_session_context = session_context

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

    @app.get("/api/latest-image")
    async def api_latest_image():
        return JSONResponse({"error": "No image generated yet"}, status_code=404)

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await ws.accept()
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
                        await _handle_json_command(ws, session_context, client_host, command)
                    else:
                        await _handle_text_command(ws, session_context, client_host, data)
                else:
                    await _handle_text_command(ws, session_context, client_host, data)
        except WebSocketDisconnect:
            return

    return app


__all__ = ["create_headless_app"]
