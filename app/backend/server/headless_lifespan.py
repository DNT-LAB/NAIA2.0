from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, Awaitable, Callable

from fastapi import FastAPI

from app.backend.server.autocomplete_commands import ensure_tag_search_index
from app.backend.server.generation_commands import random_service
from app.backend.server.interactive_assets_routes import interactive_assets_service
from app.backend.server.search_runtime import save_runner_parquet
from core.extension_runtime import load_extensions
from core.web_session_context import WebSessionContext


RunInThread = Callable[..., Awaitable[Any]]


def create_headless_lifespan(context: WebSessionContext, *, run_in_thread: RunInThread):
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # 메인 이벤트 루프 핸들 — 코어(임의 스레드)에서 WS 브로드캐스트를 예약하는
        # 브릿지(확장 토스트 등)가 call_soon_threadsafe 대상으로 쓴다.
        context.headless_main_loop = asyncio.get_running_loop()
        # 사용자 확장 로드(user-data/extensions). 워밍업 프롬프트에도 확장 훅이
        # 적용되도록 warmup 태스크 생성 전에 동기 로드한다. 개별 확장 실패는
        # 내부에서 격리되며, 이 try는 로더 자체 결함이 부팅을 막는 것만 방지한다.
        try:
            load_extensions(context)
        except Exception as exc:
            print(f"Headless Remote: extension load skipped - {exc}", flush=True)
        # 저장하지 않은 Interactive 기록은 지난 세션의 죽은 데이터다 - 마지막 몇
        # 개만 남기고 쓸어낸다(사용자 지정 2026-08-12). **종료가 아니라 부팅에서**
        # 한다: 강제 종료된 세션은 종료 훅이 안 돌아 '다음에 열면 깨끗하다'가
        # 안 지켜진다. 실패해도 부팅을 막지 않는다.
        try:
            swept = interactive_assets_service(context).sweep_unsaved()
            if swept.get("snapshots") or swept.get("scenes"):
                print(
                    "Headless Remote: interactive sweep removed "
                    f"{swept.get('snapshots', 0)} assets / {swept.get('scenes', 0)} scenes",
                    flush=True,
                )
        except Exception as exc:
            print(f"Headless Remote: interactive sweep skipped - {exc}", flush=True)
        task = getattr(context, "headless_random_warmup_task", None)
        if task is None or task.done():
            context.headless_random_warmup_task = asyncio.create_task(_run_random_warmup(context, run_in_thread))
        tag_task = getattr(context, "headless_tag_index_warmup_task", None)
        if tag_task is None or tag_task.done():
            context.headless_tag_index_warmup_task = asyncio.create_task(_run_tag_index_warmup(context, run_in_thread))
        try:
            yield
        finally:
            try:
                await run_in_thread(context.persist_prompt_engineering_settings)
            except Exception as exc:
                print(f"Headless Remote: prompt engineering shutdown save failed - {exc}", flush=True)
            try:
                await run_in_thread(save_runner_parquet, context)
            except Exception as exc:
                print(f"Headless Remote: runner parquet shutdown save failed - {exc}", flush=True)

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
