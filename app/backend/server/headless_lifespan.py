from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, Awaitable, Callable

from fastapi import FastAPI

from app.backend.server.autocomplete_commands import ensure_tag_search_index
from app.backend.server.generation_commands import random_service
from core.web_session_context import WebSessionContext


RunInThread = Callable[..., Awaitable[Any]]


def create_headless_lifespan(context: WebSessionContext, *, run_in_thread: RunInThread):
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        task = getattr(context, "headless_random_warmup_task", None)
        if task is None or task.done():
            context.headless_random_warmup_task = asyncio.create_task(_run_random_warmup(context, run_in_thread))
        tag_task = getattr(context, "headless_tag_index_warmup_task", None)
        if tag_task is None or tag_task.done():
            context.headless_tag_index_warmup_task = asyncio.create_task(_run_tag_index_warmup(context, run_in_thread))
        yield

    return lifespan


async def _run_random_warmup(context: WebSessionContext, run_in_thread: RunInThread) -> None:
    try:
        ok = await run_in_thread(random_service(context).warmup)
        context.headless_random_warmup_done = bool(ok)
        print(
            "Headless Remote: random prompt runtime warmup "
            + ("ready" if ok else "finished without search rows"),
            flush=True,
        )
    except Exception as exc:
        context.headless_random_warmup_error = str(exc)
        print(f"Headless Remote: random prompt runtime warmup failed - {exc}", flush=True)


async def _run_tag_index_warmup(context: WebSessionContext, run_in_thread: RunInThread) -> None:
    try:
        await run_in_thread(ensure_tag_search_index, context)
        print(
            f"Headless Remote: tag autocomplete index ready ({len(getattr(context, 'kr_tags_raw', {}) or {}):,} tags)",
            flush=True,
        )
    except Exception as exc:
        context.headless_tag_index_warmup_error = str(exc)
        print(f"Headless Remote: tag autocomplete index warmup failed - {exc}", flush=True)
