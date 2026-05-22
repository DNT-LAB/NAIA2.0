from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from core.web_session_context import WebSessionContext


def register_state_routes(app: FastAPI, session_context: WebSessionContext) -> None:
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
