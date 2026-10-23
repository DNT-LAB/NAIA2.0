"""Event compression API; prompt and generation actions never consume pool rows."""
from __future__ import annotations

import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.event_compress import CommitError, ensure_event_compress, check_event_compress


def register_event_compress_routes(
    app: FastAPI, session_context, *, run_in_thread, clients=None,
    broadcast_json=None, start_generation_runner=None,
):
    def response(payload, status=200):
        return JSONResponse(payload, status_code=status,
                            headers={"Cache-Control": "no-store, max-age=0"})

    def error(code, message, status=400):
        return response({"ok": False, "code": code, "message": message}, status)

    async def payload_for(request):
        try:
            value = await request.json()
        except (ValueError, TypeError):
            raise ValueError("Expected a JSON object")
        if not isinstance(value, dict):
            raise ValueError("Expected a JSON object")
        return value

    async def broadcast(message):
        if clients is not None and broadcast_json is not None:
            await broadcast_json(clients, message)

    @app.get("/api/event-compress/state")
    async def event_compress_state():
        def get_state():
            check_event_compress(session_context)
            return ensure_event_compress(session_context).state()
        return response(await run_in_thread(get_state))

    @app.post("/api/event-compress/toggle")
    async def event_compress_toggle(req: Request):
        try:
            payload = await payload_for(req)
            if type(payload.get("enabled")) is not bool:
                raise ValueError("enabled must be a boolean")
        except ValueError as exc:
            return error("bad_request", str(exc))
        service = ensure_event_compress(session_context)
        return response(await run_in_thread(service.toggle, payload["enabled"]))

    def tag_cut(min_tags, max_tags):
        try:
            lower = None if min_tags is None else int(min_tags)
            upper = None if max_tags is None else int(max_tags)
        except ValueError:
            raise ValueError("min_tags and max_tags must be integers")
        if (lower is not None and lower < 0) or (upper is not None and upper < 0):
            raise ValueError("min_tags and max_tags must be non-negative")
        if lower is not None and upper is not None and lower > upper:
            raise ValueError("min_tags must not exceed max_tags")
        return lower, upper

    @app.get("/api/event-compress/events")
    async def event_compress_events(sort: str = "desc", q: str = "", offset: int = 0, limit: int = 60,
                                    min_tags: str | None = None, max_tags: str | None = None):
        if sort not in ("asc", "desc") or offset < 0 or limit < 1:
            return error("bad_request", "Invalid sort, offset or limit")
        try:
            lower, upper = tag_cut(min_tags, max_tags)
        except ValueError as exc:
            return error("bad_request", str(exc))
        try:
            result = await run_in_thread(ensure_event_compress(session_context).events,
                                         sort, q, offset, limit, lower, upper)
        except RuntimeError as exc:
            return error("internal_error", str(exc), 500)
        return response(result)

    @app.post("/api/event-compress/commit")
    async def event_compress_commit(req: Request):
        try:
            payload = await payload_for(req)
            for key in ("min_tags", "max_tags"):
                if payload.get(key) is not None and type(payload[key]) is not int:
                    raise ValueError("min_tags and max_tags must be integers or null")
            lower, upper = tag_cut(payload.get("min_tags"), payload.get("max_tags"))
            q = payload.get("q", "")
            signature = payload.get("events_signature")
            if not isinstance(q, str) or not isinstance(signature, str) or not signature:
                raise ValueError("q must be a string and events_signature is required")
        except ValueError as exc:
            return error("bad_request", str(exc))
        try:
            result = await run_in_thread(ensure_event_compress(session_context).commit,
                                         signature, lower, upper, q)
        except CommitError as exc:
            return error(exc.code, str(exc), exc.status)
        except (OSError, RuntimeError) as exc:
            return error("internal_error", str(exc), 500)
        return response(result)

    @app.get("/api/event-compress/tags")
    async def event_compress_tags(q: str = "", min_tags: str | None = None,
                                 max_tags: str | None = None, limit: str = "20"):
        try:
            lower, upper = tag_cut(min_tags, max_tags)
            count = int(limit)
            if not 1 <= count <= 100:
                raise ValueError("limit must be between 1 and 100")
        except ValueError as exc:
            return error("bad_request", str(exc))
        try:
            result = await run_in_thread(ensure_event_compress(session_context).tags,
                                         q, lower, upper, count)
        except RuntimeError as exc:
            return error("internal_error", str(exc), 500)
        return response(result)

    async def source(payload):
        key = payload.get("key")
        if not isinstance(key, str) or not key:
            raise ValueError("key is required")
        return await run_in_thread(ensure_event_compress(session_context).source_row, key)

    @app.post("/api/event-compress/random")
    async def event_compress_random(req: Request):
        try:
            payload = await payload_for(req)
            source_row = await source(payload)
        except ValueError as exc:
            return error("bad_request", str(exc))
        except KeyError:
            return error("not_found", "Event no longer exists", 404)
        except RuntimeError as exc:
            return error("internal_error", str(exc), 500)
        from app.backend.server.generation_commands import random_service, _broadcast_wildcard_state

        request_id = str(payload.get("requestId") or uuid.uuid4().hex)
        try:
            result = await run_in_thread(
                random_service(session_context).generate_from_source_row, source_row,
                random_request_id=request_id, source="event_compress", update_context=True)
        except Exception as exc:
            return error("internal_error", str(exc), 500)
        if not result.success:
            return error("pipeline_failed", result.error)
        await broadcast(result.websocket_payload())
        for message in result.extra_messages:
            await broadcast(message)
        if clients is not None:
            try:
                await _broadcast_wildcard_state(session_context, clients)
            except Exception:
                pass
        return response({"ok": True, "prompt": result.prompt, "requestId": request_id,
                         "promptRunId": result.prompt_run_id})

    @app.post("/api/event-compress/generate")
    async def event_compress_generate(req: Request):
        try:
            payload = await payload_for(req)
            source_row = await source(payload)
        except ValueError as exc:
            return error("bad_request", str(exc))
        except KeyError:
            return error("not_found", "Event no longer exists", 404)
        except RuntimeError as exc:
            return error("internal_error", str(exc), 500)
        from app.backend.server.event_preset_routes import (
            _generate_event_preset_prompt, _generation_service, _preset_source_to_generation_command,
        )
        request_id = str(payload.get("requestId") or uuid.uuid4().hex)
        try:
            processed = await run_in_thread(
                _generate_event_preset_prompt, session_context, source_row,
                overrides={}, request_id=request_id, source="event_compress")
            if not processed.success:
                return error("pipeline_failed", processed.error or "Prompt processing failed")
            command = _preset_source_to_generation_command(
                session_context,
                {"requestId": request_id, "sourceRow": source_row,
                 "sourceName": f"event_compress:{request_id}"},
                source="preset", overrides={}, prompt_override=processed.prompt,
                prompt_run_id_override=processed.prompt_run_id)
            command["overrides"]["_remote_queue_label"] = "event_compress"
            dispatch = await run_in_thread(_generation_service(session_context).enqueue_remote_request, command)
        except RuntimeError as exc:
            return error("blocked", str(exc), 409)
        except ValueError as exc:
            return error("bad_request", str(exc))
        except Exception as exc:
            return error("internal_error", str(exc), 500)
        if not dispatch.ok:
            return response({"ok": False, "code": "blocked", **dispatch.websocket_payload()}, 409)
        if start_generation_runner is not None and clients is not None \
                and getattr(session_context, "headless_generation_execute_enabled", False):
            start_generation_runner(session_context, clients)
        return response({"ok": True, "status": "generation_requested", "requestId": request_id,
                         "prompt": processed.prompt, "promptRunId": processed.prompt_run_id})
