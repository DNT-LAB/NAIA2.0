from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Any, Awaitable, Callable

from fastapi import FastAPI

from app.backend.server.autocomplete_commands import build_tag_index
from app.backend.server.generation_commands import random_service
from app.backend.server.interactive_assets_routes import interactive_assets_service
from app.backend.server.search_runtime import save_runner_parquet
from app.backend.server.startup_work import (
    apply_switch_interval_policy,
    background_cpu_slot,
    restore_switch_interval,
    restore_switch_interval_after_startup,
)
from core.search_pool_writer import search_pool_writer
from core.extension_runtime import load_extensions
from core.web_session_context import WebSessionContext


RunInThread = Callable[..., Awaitable[Any]]


def create_headless_lifespan(context: WebSessionContext, *, run_in_thread: RunInThread):
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        apply_switch_interval_policy()
        # 메인 이벤트 루프 핸들 — 코어(임의 스레드)에서 WS 브로드캐스트를 예약하는
        # 브릿지(확장 토스트 등)가 call_soon_threadsafe 대상으로 쓴다.
        context.headless_main_loop = asyncio.get_running_loop()
        try:
            from core.anima_engine.install import recover_interrupted
            from core.anima_engine.integration import save_root_of
            recover_interrupted(save_root_of(context))
        except Exception as exc:
            print(f"Headless Remote: ANIMA recovery failed - {ascii(str(exc))}", flush=True)
        # 이 user-data 에 ANIMA 설치 위치가 없는데 표준 자리에 이미 끝난 설치가 있으면 가져다 쓴다(사용자 제보 09-29:
        # 격리 시험의 새 user-data 가 '설치 (0KB)' 를 보였다). 모드 선택 · 생성이 ANIMA 탭의 첫 상태 조회보다 먼저
        # 올 수 있어 기동 때 한 번 한다(상태 조회도 한다 - 켜 둔 사이 다른 NAIA 가 설치한 경우).
        try:
            from app.backend.server.anima_engine_service import service_for as anima_service_for
            anima_service_for(context).adopt_installed()
        except Exception as exc:
            print(f"Headless Remote: ANIMA adopt skipped - {ascii(str(exc))}", flush=True)
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
        # 첫 설치인가(태그 아카이브 없이 켜졌다) - 풀이 처음 채워질 때 Tag Filter "1girl, solo" 를 건다
        # (core/first_run_state). 아래 워밍업이 풀을 채우기 **전에** 정해 둬야 한다.
        try:
            from core.first_run_state import note_startup

            note_startup(context)
        except Exception as exc:
            print(f"Headless Remote: first-run note skipped - {ascii(str(exc))}", flush=True)
        task = getattr(context, "headless_random_warmup_task", None)
        if task is None or task.done():
            context.headless_random_warmup_task = asyncio.create_task(_run_random_warmup(context, run_in_thread))
        # ⚠️ 무거운 색인 예열 둘(태그 자동완성 20만 · 캐릭터 검색)은 **Electron 의 첫 initialize 응답 뒤에** 시작한다
        #    (2026-10-22 포터블 시작 실패: 둘이 시작 직후 CPU 를 붙잡아 10초 제한의 initialize 가 시간 초과).
        #    initialize 가 안 오는 경우(브라우저만)에는 NAIA_STARTUP_WARMUP_DELAY 초(기본 8) 뒤에 시작한다.
        gate = asyncio.Event()
        context.headless_startup_gate = gate
        tag_task = getattr(context, "headless_tag_index_warmup_task", None)
        if tag_task is None or tag_task.done():
            context.headless_tag_index_warmup_task = asyncio.create_task(
                _after_startup_gate(gate, _run_tag_index_warmup, context, run_in_thread))
        character_task = getattr(context, "headless_character_index_warmup_task", None)
        if character_task is None or character_task.done():
            context.headless_character_index_warmup_task = asyncio.create_task(
                _after_startup_gate(gate, _run_character_index_warmup, context, run_in_thread))
        # 0.9ms GIL 간격은 시작 예열 동안만 - 끝나면 원래 값으로(세션 중 CPU 작업이 겹칠 때의 손해를 피한다).
        # 지난 lifespan 의 waiter 가 남았으면 버린다 - 옛 예열 task 를 보고 새 예열 도중에 되돌리면 안 된다.
        _cancel_task(getattr(context, "headless_switch_interval_restore_task", None))
        context.headless_switch_interval_restore_task = asyncio.create_task(
            restore_switch_interval_after_startup(context))
        # ⚠️ 캐릭터 확장 팩은 시작 경로에서 받지 않는다(사용자 지시 2026-10-22) - 시작 경로에서 받기를 걸었더니 포터블의
        #    install-manager/initialize 가 시간 초과로 죽었다. 화면이 다 뜬 뒤 app.js 가 한 번 요청하고(로컬 화면),
        #    원격 화면만 쓰는 경우를 위해 서버도 첫 initialize(또는 지연) 뒤 20초에 한 번 스스로 시작한다(뒤쪽 작업 - 시작을 막지 않는다).
        pack_task = getattr(context, "headless_character_pack_autostart_task", None)
        if pack_task is None or pack_task.done():
            context.headless_character_pack_autostart_task = asyncio.create_task(
                _after_startup_gate(gate, _run_character_pack_autostart, context, run_in_thread))
        try:
            yield
        finally:
            # 예열이 안 끝난 채 닫혀도 0.9ms 를 남기지 않는다 - waiter 가 첫 실행 전에 취소되면 그 finally 도 안 돈다.
            _cancel_task(getattr(context, "headless_switch_interval_restore_task", None))
            restore_switch_interval()
            try:
                from core.anima_engine.runtime import stop_all
                await run_in_thread(stop_all)
            except Exception as exc:
                print(f"Headless Remote: ANIMA shutdown failed - {ascii(str(exc))}", flush=True)
            try:
                await run_in_thread(context.persist_prompt_engineering_settings)
            except Exception as exc:
                print(f"Headless Remote: prompt engineering shutdown save failed - {exc}", flush=True)
            try:
                # 응답 뒤로 미룬 풀 기록(core/search_pool_writer.py)을 먼저 끝낸다 - 안 그러면 종료가
                # 쓰는 중인 last-search 를 끊는다. 끝나지 않으면 기다림을 접고 진행(best-effort).
                await run_in_thread(search_pool_writer(context).flush, 60.0)
            except Exception as exc:
                print(f"Headless Remote: search pool write flush failed - {exc}", flush=True)
            try:
                await run_in_thread(save_runner_parquet, context)
            except Exception as exc:
                print(f"Headless Remote: runner parquet shutdown save failed - {exc}", flush=True)
            try:
                # Tag Filter 이어 하기(사용자 2026-10-18) - 정상 종료 때 남은 행 색인을 쓴다. 포터블은 이 finally 까지
                # 못 오고 강제로 꺼지므로 Electron 이 먼저 POST /api/session/prepare-shutdown 으로 같은 저장을 시킨다.
                from core.tag_filter_remaining import save_remaining

                await run_in_thread(save_remaining, context)
            except Exception as exc:
                print(f"Headless Remote: tag filter remaining shutdown save failed - {ascii(str(exc))}", flush=True)
            # 정상 종료면 청소 흔적을 지운다 - 다음 부팅이 죽은 pid 를 붙들고
            # 청소를 건너뛰지 않게. 강제 종료면 남지만 그때는 pid 생존 확인이
            # 걸러 준다(Codex 11차).
            try:
                await run_in_thread(interactive_assets_service(context).release_sweep_owner)
            except Exception as exc:
                print(f"Headless Remote: interactive sweep owner release failed - {exc}", flush=True)

    return lifespan


def _cancel_task(task) -> None:
    if task is not None and not task.done():
        task.cancel()


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
    def _build() -> None:
        with background_cpu_slot(context):
            build_tag_index(context)

    try:
        # 만드는 동안 들어온 자동완성은 '준비 중' 으로 곧바로 답을 받는다(autocomplete_commands._pending_reply) -
        # 잠금을 기다리며 그 창의 명령 흐름을 붙잡지 않는다.
        await run_in_thread(_build)
        print(
            f"Headless Remote: tag autocomplete index ready ({len(getattr(context, 'kr_tags_raw', {}) or {}):,} tags)",
            flush=True,
        )
    except Exception as exc:
        context.headless_tag_index_warmup_error = str(exc)
        print(f"Headless Remote: tag autocomplete index warmup failed - {exc}", flush=True)
        return
    finally:
        # 화면의 첫 상태 베일이 이걸 기다린다(/api/startup-status) - 실패해도 끝은 끝이다(베일이 갇히지 않게).
        context.headless_tag_index_warmup_done = True
    # Assist 한국어 층(이름 칩 · Kiwi)을 뒤에서 미리 — 창을 열 때 시작하면 켜자마자 친 이름의 첫 칩까지 20초였다(09-26).
    # 태그 사전을 이미 읽은 뒤라 그 몫은 기다리지 않는다. Kiwi 가 없으면(처음 쓸 때 설치) 조용히 넘어간다.
    try:
        from app.backend.server.assist_v2_service import _warm_korean_async

        _warm_korean_async(context)
    except Exception as exc:
        print(f"Headless Remote: assist korean warmup failed - {exc}", flush=True)


async def _run_character_pack_autostart(context: WebSessionContext, run_in_thread: RunInThread) -> None:
    try:
        delay = max(0.0, float(os.environ.get("NAIA_CHARACTER_PACK_AUTOSTART_DELAY", "20") or 0))
    except ValueError:
        delay = 20.0
    if delay > 0:
        await asyncio.sleep(delay)
    try:
        from app.backend.server.install_manager_routes import runtime_install_manager

        await run_in_thread(runtime_install_manager(context).auto_start_character_pack)
    except Exception as exc:
        print(f"Headless Remote: character pack auto start skipped - {ascii(str(exc))}", flush=True)


async def _after_startup_gate(gate: asyncio.Event, warmup, context: WebSessionContext, run_in_thread: RunInThread) -> None:
    """첫 initialize 응답(또는 지연 시간)을 기다렸다가 예열을 돈다 - 위 lifespan 주석 참조."""
    # Electron(NAIA_ELECTRON=1 - v2.0.60 의 main.cjs 도 넘긴다)은 시작 때 initialize 를 반드시 한 번 부른다 - 그 응답까지 기다린다
    # (안 오면 90초 뒤). 브라우저만 쓰면 initialize 가 안 오므로 짧게(기본 8초). 어느 쪽이든 그때 initialize 가 **처리 중**이면
    # 끝날 때까지 기다린다 - 느린 디스크 · 백신 검사로 늦어진 initialize 와 예열이 겹치지 않게(업데이트 호환 리뷰 P1).
    electron = os.environ.get("NAIA_ELECTRON") == "1"
    try:
        delay = max(0.0, float(os.environ.get("NAIA_STARTUP_WARMUP_DELAY", "90" if electron else "8") or 0))
    except ValueError:
        delay = 90.0 if electron else 8.0
    if delay > 0:
        try:
            await asyncio.wait_for(gate.wait(), timeout=delay)
        except asyncio.TimeoutError:
            # 그때 처리 중인 initialize 가 있으면 끝날 때까지 - 단 30초 상한(안 돌아오는 initialize 에 예열이 영영 묶이지 않게).
            loop = asyncio.get_running_loop()
            until = loop.time() + 30.0
            while (getattr(context, "headless_initialize_inflight", 0) > 0 and not gate.is_set()
                   and loop.time() < until):
                await asyncio.sleep(0.2)
        # 그다음 첫 화면이 첫 상태(프롬프트 · 모드 · 옵션 …)를 다 받을 때까지 - 화면이 붙자마자 예열이 CPU 를 잡으면
        # 그 첫 상태가 몇 초 늦어 빈 화면이 보였다(사용자 제보 2026-10-22). 화면이 안 붙으면(원격 서버만 켬) 20초 상한.
        loop = asyncio.get_running_loop()
        until = loop.time() + 20.0
        while not getattr(context, "headless_first_client_ready", False) and loop.time() < until:
            await asyncio.sleep(0.2)
        # init 뒤 첫 모듈 상태 요청까지 답한 뒤 예열한다. 2026-10-30 실측: 겹치면 PE 상태 11.4초,
        # 이벤트 루프 정지 11.3초. 구형 화면/원격 전용은 첫 client 준비 시각부터 짧은 상한만 기다린다.
        try:
            batch_wait = max(0.0, float(os.environ.get("NAIA_STARTUP_UI_BATCH_WAIT", "3.0") or 0))
        except ValueError:
            batch_wait = 3.0
        until = getattr(context, "headless_first_client_ready_at", loop.time()) + batch_wait
        while not getattr(context, "headless_first_ui_batch_done", False) and loop.time() < until:
            await asyncio.sleep(0.2)
    await warmup(context, run_in_thread)


async def _run_character_index_warmup(context: WebSessionContext, run_in_thread: RunInThread) -> None:
    # 베일이 기다리는 태그 예열부터 끝낸다 - 슬롯을 잡은 채 태그 task를 기다리면 안 된다.
    tag_task = getattr(context, "headless_tag_index_warmup_task", None)
    if tag_task is not None:
        # wait 는 태그 쪽 실패/취소를 올리지 않고, 이 task 자신의 취소(종료)는 그대로 올린다.
        await asyncio.wait((tag_task,))
    try:
        from app.backend.server.character_viewer_routes import character_viewer_service

        def _warm() -> None:
            with background_cpu_slot(context):
                character_viewer_service(context).warm_search_index()

        await run_in_thread(_warm)
    except Exception as exc:
        context.headless_character_index_warmup_error = str(exc)
        print(f"Headless Remote: character search index warmup failed - {exc}", flush=True)
