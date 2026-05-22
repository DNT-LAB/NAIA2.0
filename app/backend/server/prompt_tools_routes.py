from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.responses import Response

from core.web_session_context import WebSessionContext


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


def register_prompt_tools_routes(app: FastAPI, session_context: WebSessionContext) -> None:
    _ = session_context

    @app.get("/api/prompt-highlight-index")
    async def api_prompt_highlight_index():
        return Response(
            content=json.dumps(prompt_highlight_empty_index(), ensure_ascii=False),
            media_type="application/json",
            headers=_no_cache_headers(),
        )
