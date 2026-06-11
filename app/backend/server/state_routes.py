from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.web_session_context import WebSessionContext


AsyncRunner = Callable[..., Awaitable[Any]]
JsonBroadcaster = Callable[[set[Any], dict[str, Any]], Awaitable[None]]
GenerationRunnerStarter = Callable[[WebSessionContext, set[Any]], None]


def register_state_routes(
    app: FastAPI,
    session_context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
    clients: set[Any],
    broadcast_json: JsonBroadcaster,
    start_generation_runner: GenerationRunnerStarter,
) -> None:
    @app.get("/api/status")
    async def api_status():
        return session_context.http_status_payload()

    @app.get("/api/pipeline/prompt-runs")
    async def api_pipeline_prompt_runs(limit: int = 50):
        return session_context.prompt_runs_payload(limit=limit)

    @app.get("/api/pipeline/prompt-runs/{prompt_run_id}")
    async def api_pipeline_prompt_run(prompt_run_id: str):
        payload = session_context.get_prompt_run_payload(prompt_run_id, include_source_row=True)
        if payload is None:
            return JSONResponse({"error": "prompt run not found"}, status_code=404)
        return payload

    @app.get("/api/queue/state")
    async def api_queue_state():
        return session_context.queue_state_payload()

    @app.post("/api/queue/action")
    async def api_queue_action(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        action = str(payload.get("action") or "").strip().lower()
        manager = session_context.generation_queue_manager
        if action == "pause":
            await run_in_thread(manager.pause_queue)
        elif action == "resume":
            await run_in_thread(manager.resume_queue)
            if session_context.headless_generation_execute_enabled:
                start_generation_runner(session_context, clients)
        elif action == "clear":
            await run_in_thread(manager.clear_queue)
        elif action == "remove":
            request_id = str(payload.get("request_id") or payload.get("id") or "").strip()
            if not request_id:
                return JSONResponse({"error": "request_id is required"}, status_code=400)
            removed = await run_in_thread(manager.remove_request, request_id)
            if not removed:
                return JSONResponse({"error": "request not found"}, status_code=404)
        else:
            return JSONResponse({"error": "Unsupported queue action"}, status_code=400)
        state = session_context.queue_state_payload()
        await broadcast_json(clients, state)
        return {"ok": True, "action": action, "queue": state}

    def runtime_capabilities_payload() -> dict[str, Any]:
        return {
            "runtime": "web",
            "right_tabs": {
                "result": True,
                "pngInfo": True,
                "thumb": True,
                "artists": True,
                "characters": True,
                "studio": True,
                # Settings 탭(좌: 카테고리, 우: 콘텐츠) — Global(placeholder) + Extension 관리.
                "settings": True,
            },
            "retired_tabs": {},
        }

    @app.get("/api/runtime/capabilities")
    async def api_runtime_capabilities():
        return runtime_capabilities_payload()
