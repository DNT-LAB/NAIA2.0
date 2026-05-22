from __future__ import annotations

import uuid
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from app.backend.server.preset_services import (
    clothes_preset_service,
    event_preset_download_service,
    event_preset_status,
    event_preset_service,
    expression_preset_service,
    preset_composer_service,
)
from core.headless_generation_service import HeadlessGenerationService
from core.web_session_context import WebSessionContext


AsyncRunner = Callable[..., Awaitable[Any]]
JsonBroadcaster = Callable[[set[Any], dict[str, Any]], Awaitable[None]]
GenerationRunnerStarter = Callable[[WebSessionContext, set[Any]], None]


def _generation_service(context: WebSessionContext) -> HeadlessGenerationService:
    service = getattr(context, "headless_generation_service", None)
    if service is None:
        service = HeadlessGenerationService(context)
        context.headless_generation_service = service
    return service


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
    payload = event_preset_service(context).bootstrap(
        rating_id,
        person_id,
        search,
        category_id,
        subcategory_id,
        event_id,
        limit,
    )
    payload["download"] = event_preset_download_service(context).snapshot()
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
    prompt_run_id = _record_preset_prompt_run(
        context,
        result,
        source=source,
        request_id=request_id,
        source_row_data=source_row_data,
    )
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
    if prompt_run_id:
        generation_overrides["prompt_run_id"] = prompt_run_id
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


def _record_preset_prompt_run(
    context: WebSessionContext,
    result: dict[str, Any],
    *,
    source: str,
    request_id: str,
    source_row_data: dict[str, Any],
) -> str:
    existing = str(result.get("prompt_run_id") or result.get("promptRunId") or "")
    if existing:
        return existing
    starter = getattr(context, "start_prompt_run", None)
    completer = getattr(context, "complete_prompt_run", None)
    if not callable(starter) or not callable(completer):
        return ""
    import pandas as pd

    prompt = str(
        result.get("promptPreview")
        or (result.get("promptPlan") or {}).get("finalPrompt")
        or source_row_data.get("general")
        or ""
    )
    run = starter(
        source=source,
        source_row=pd.Series(source_row_data, name=f"{source}:{request_id}"),
        settings={"api_mode": context.get_api_mode()},
        external_request_id=request_id,
        metadata={
            "prompt_source": source,
            "requestId": request_id,
        },
    )
    completer(
        run.prompt_run_id,
        final_prompt=prompt,
        metadata={"prompt_source": source},
    )
    result["prompt_run_id"] = run.prompt_run_id
    result["promptRunId"] = run.prompt_run_id
    return run.prompt_run_id


def _record_prompt_preview_run(
    context: WebSessionContext,
    result: dict[str, Any],
    *,
    source: str,
    request_id: str,
    prompt: str,
    source_row_data: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    existing = str(result.get("prompt_run_id") or result.get("promptRunId") or "")
    if existing:
        return existing
    starter = getattr(context, "start_prompt_run", None)
    completer = getattr(context, "complete_prompt_run", None)
    if not callable(starter) or not callable(completer):
        return ""

    clean_request_id = str(request_id or result.get("requestId") or uuid.uuid4().hex)
    result["requestId"] = clean_request_id
    source_row = dict(source_row_data or {})
    source_row.setdefault("general", prompt)
    source_row.setdefault("prompt_preview_source", source)
    run = starter(
        source=source,
        source_row=source_row,
        settings=settings or {},
        external_request_id=clean_request_id,
        metadata={
            "prompt_source": source,
            "preview": True,
            **(metadata or {}),
        },
    )
    completer(
        run.prompt_run_id,
        final_prompt=prompt,
        metadata={
            "prompt_source": source,
            "preview": True,
            **(metadata or {}),
        },
    )
    result["prompt_run_id"] = run.prompt_run_id
    result["promptRunId"] = run.prompt_run_id
    return run.prompt_run_id


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
    prompt_run_id = str(result.get("prompt_run_id") or result.get("promptRunId") or "")
    if prompt_run_id:
        payload["prompt_run_id"] = prompt_run_id
        payload["promptRunId"] = prompt_run_id
    if source == "event_preset":
        payload["event_preset_request_id"] = request_id
        payload["selected"] = result.get("selected") or {}
        payload["event"] = result.get("event") or {}
    elif source == "preset":
        payload["remote_preset_request_id"] = request_id
        payload["promptPlan"] = result.get("promptPlan") or {}
    return payload


def register_event_preset_routes(
    app: FastAPI,
    session_context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
    clients: set[Any],
    broadcast_json: JsonBroadcaster,
    start_generation_runner: GenerationRunnerStarter,
) -> None:
    @app.get("/api/event-preset/status")
    async def api_event_preset_status():
        try:
            return await run_in_thread(event_preset_status, session_context)
        except Exception as exc:
            return JSONResponse({"error": f"Event Preset status failed: {exc}"}, status_code=500)

    @app.get("/api/event-preset/download")
    async def api_event_preset_download_state():
        try:
            return await run_in_thread(event_preset_download_service(session_context).snapshot)
        except Exception as exc:
            return JSONResponse({"error": f"Event Preset download state failed: {exc}"}, status_code=500)

    @app.post("/api/event-preset/download")
    async def api_event_preset_download():
        try:
            return await run_in_thread(event_preset_download_service(session_context).start)
        except Exception as exc:
            return JSONResponse({"error": f"Event Preset download failed: {exc}"}, status_code=500)

    @app.post("/api/event-preset/download/cancel")
    async def api_event_preset_download_cancel():
        try:
            return await run_in_thread(event_preset_download_service(session_context).cancel)
        except Exception as exc:
            return JSONResponse({"error": f"Event Preset download cancel failed: {exc}"}, status_code=500)

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
            return await run_in_thread(
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
            return await run_in_thread(event_preset_service(session_context).select, payload)
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
            result = await run_in_thread(event_preset_service(session_context).prompt_preview, payload)
            if isinstance(result, dict):
                prompt = str(result.get("prompt") or "")
                request_id = str(result.get("requestId") or payload.get("requestId") or payload.get("request_id") or "")
                _record_prompt_preview_run(
                    session_context,
                    result,
                    source="event_preset_preview",
                    request_id=request_id,
                    prompt=prompt,
                    source_row_data={
                        "general": prompt,
                        "rating": payload.get("ratingId") or "s",
                        "event_preset_preview": True,
                    },
                    settings=payload,
                    metadata={"api_mode": session_context.get_api_mode()},
                )
            return result
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
            result = await run_in_thread(preset_composer_service(session_context).prompt_preview, payload)
            if isinstance(result, dict):
                prompt_plan = result.get("promptPlan") if isinstance(result.get("promptPlan"), dict) else {}
                prompt = str(prompt_plan.get("finalPrompt") or "")
                request_id = str(result.get("requestId") or payload.get("requestId") or payload.get("request_id") or "")
                _record_prompt_preview_run(
                    session_context,
                    result,
                    source="preset_preview",
                    request_id=request_id,
                    prompt=prompt,
                    source_row_data={
                        "general": prompt,
                        "remote_preset_request_id": request_id,
                        "remote_preset_preview": True,
                    },
                    settings=payload,
                    metadata={
                        "api_mode": session_context.get_api_mode(),
                        "active_axes": prompt_plan.get("activeAxes") or [],
                    },
                )
            return result
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
            result = await run_in_thread(preset_composer_service(session_context).generation_source, payload)
            command = _preset_source_to_generation_command(
                session_context,
                result,
                source="preset",
                overrides=payload.get("overrides") if isinstance(payload.get("overrides"), dict) else {},
            )
            dispatch = await run_in_thread(_generation_service(session_context).enqueue_remote_request, command)
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
        await broadcast_json(
            clients,
            _preset_prompt_generated_payload(session_context, result, source="preset"),
        )
        if session_context.headless_generation_execute_enabled:
            start_generation_runner(session_context, clients)
        return {
            "ok": True,
            "status": "generation_requested",
            "requestId": result.get("requestId") or dispatch.request_id,
            "promptRunId": result.get("promptRunId") or result.get("prompt_run_id") or dispatch.websocket_payload().get("prompt_run_id") or "",
            "promptPlan": result.get("promptPlan") or {},
        }

    @app.post("/api/event-preset/generate")
    async def api_event_preset_generate(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            result = await run_in_thread(event_preset_service(session_context).generation_source, payload)
            command = _preset_source_to_generation_command(
                session_context,
                result,
                source="event_preset",
                overrides=payload.get("overrides") if isinstance(payload.get("overrides"), dict) else {},
            )
            dispatch = await run_in_thread(_generation_service(session_context).enqueue_remote_request, command)
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
        await broadcast_json(
            clients,
            _preset_prompt_generated_payload(session_context, result, source="event_preset"),
        )
        if session_context.headless_generation_execute_enabled:
            start_generation_runner(session_context, clients)
        return {
            "ok": True,
            "status": "generation_requested",
            "requestId": result.get("requestId") or dispatch.request_id,
            "promptRunId": result.get("promptRunId") or result.get("prompt_run_id") or dispatch.websocket_payload().get("prompt_run_id") or "",
            "selected": result.get("selected") or {},
            "promptPreview": result.get("promptPreview") or "",
            "event": result.get("event") or {},
        }

    @app.get("/api/event-preset/thumbnail")
    async def api_event_preset_thumbnail(eventId: str = "", tag: str = "", size: str = ""):
        try:
            image_bytes, media_type = await run_in_thread(
                event_preset_service(session_context).thumbnail_payload,
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

    @app.get("/api/clothes-preset/status")
    async def api_clothes_preset_status():
        try:
            return await run_in_thread(clothes_preset_service(session_context).status)
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
            return await run_in_thread(clothes_preset_service(session_context).bootstrap, payload)
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
            return await run_in_thread(clothes_preset_service(session_context).select, payload)
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
            return await run_in_thread(clothes_preset_service(session_context).lucky, payload)
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
            return await run_in_thread(clothes_preset_service(session_context).prompt_fragment, payload)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"Clothes Preset prompt fragment failed: {exc}"}, status_code=500)

    @app.get("/api/expression-preset/status")
    async def api_expression_preset_status():
        try:
            return await run_in_thread(expression_preset_service(session_context).status)
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
            return await run_in_thread(expression_preset_service(session_context).bootstrap, payload)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"Expression Preset bootstrap failed: {exc}"}, status_code=500)
