"""Runtime install manager routes.

POST endpoints here mutate ``user_root`` (initialize creates directories +
copies bootstrap files; tag-archive/download starts a long-lived download
thread writing into ``data/tags``). These are server-machine side effects, so
they are loopback-gated the same way the data-migration routes are — a remote
Remote Web client must not be able to start a multi-GB download or scaffold
directories on the host. The read-only ``GET /api/install-manager`` snapshot
stays open so any client can render progress, matching how the data-migration
preview is allowed to surface state but not act on it.
"""

from __future__ import annotations

import threading
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.headless_payload_utils import is_loopback_host
from core.runtime_install_manager import RuntimeInstallManager
from core.web_session_context import WebSessionContext


AsyncRunner = Callable[..., Awaitable[Any]]


def _request_host(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw.startswith("[") and "]" in raw:
        return raw[1:raw.index("]")]
    if raw.count(":") == 1:
        return raw.rsplit(":", 1)[0]
    return raw


def _is_local_request(req: Request) -> bool:
    client_host = ""
    try:
        if req.client is not None:
            client_host = _request_host(str(req.client.host or ""))
    except Exception:
        client_host = ""
    request_host = _request_host(req.headers.get("host") or getattr(req.url, "hostname", "") or "")
    if client_host == "testclient":
        return request_host in {"", "testserver"} or is_loopback_host(request_host)
    return is_loopback_host(client_host) and is_loopback_host(request_host)


def _loopback_only_response() -> JSONResponse:
    return JSONResponse(
        {"ok": False, "runtime": "web", "error": "데이터 초기화/다운로드는 로컬에서만 가능합니다."},
        status_code=403,
    )


def _sanitize_snapshot_for_remote(snapshot: Any) -> Any:
    """Drop host filesystem paths from a snapshot served to a non-loopback
    client. Remote clients only need progress/status to render the bootstrap
    UI; absolute ``user_root``/``data_dir``/``downloads_dir`` paths and the
    sample/resource locations are local-machine details that should not leak.
    """
    if not isinstance(snapshot, dict):
        return snapshot
    sanitized = dict(snapshot)
    runtime = sanitized.get("runtime")
    if isinstance(runtime, dict):
        sanitized["runtime"] = {
            "portable": runtime.get("portable"),
            "data_initialized": runtime.get("data_initialized"),
        }
    sanitized.pop("samples", None)
    # 아카이브가 늘어날 때 여기를 빠뜨리면 절대 경로가 원격으로 샌다.
    for key in ("tag_archive", "tag_archive_increment", "corpus_archive", "event_map"):
        archive = sanitized.get(key)
        if isinstance(archive, dict):
            archive = dict(archive)
            archive.pop("target", None)
            sanitized[key] = archive
    return sanitized


def refresh_after_tag_data(context: WebSessionContext) -> None:
    """태그 데이터가 들어왔다 - 설치 완료 훅과 데이터 가져오기(data_migration_routes)가 **같이** 쓴다.

    자동완성 색인을 비우고 **뒤에서 다시 만든다**(lazy 로딩, 09-27). 전에는 두 입구 모두 비우기만 해서, 그 직후
    처음 친 자동완성이 색인 재생성(8초+)을 떠안고 그동안 그 창의 명령이 전부 멈췄다(사용자 제보: "1g 가 안
    되다가 약 15초 뒤 작동"). 풀이 비어 있으면(첫 설치) 태그 파일을 뒤에서 채운다 - 첫 실행 Tag Filter(1girl,
    solo)도 이어서 걸린다. 가져온 것에 마지막 검색이 있으면 그 풀이 복원되고 첫 실행 필터는 걸리지 않는다.
    """
    from app.backend.server.autocomplete_commands import reset_tag_index

    reset_tag_index(context)
    _load_pool_after_install(context)


def _load_pool_after_install(context: WebSessionContext) -> None:
    """태그 데이터를 방금 받았는데 검색 풀이 비어 있으면(첫 설치) 뒤에서 채운다.

    풀 로딩 알림(`pool_loading_begin/end`)으로 감싼다 - 태그 마지막 조각은 작아서 '조용한 로딩' 이라
    알림이 안 나가는데, 그러면 화면이 풀이 채워진 것을 모른다. 끝(`search_loading` false)을 받으면 화면이
    `get_search_state` 로 다시 묻고, 첫 실행 Tag Filter 표시도 그 답에 실린다(core/first_run_state).
    """
    results = getattr(context, "search_results", None)
    if results is not None and not results.is_empty():
        return

    def _run() -> None:
        begin = getattr(context, "pool_loading_begin", None)
        end = getattr(context, "pool_loading_end", None)
        started = False
        try:
            if callable(begin):
                begin("load")
                started = True
            from app.backend.server.generation_commands import random_service

            random_service(context).warmup()
        except Exception as exc:  # noqa: BLE001 - 설치는 이미 끝났다, 풀은 다음 Random 이 채운다
            print(f"Headless Remote: pool load after tag install failed - {ascii(str(exc))}", flush=True)
        finally:
            if started and callable(end):
                end()

    threading.Thread(target=_run, daemon=True, name="naia-pool-after-install").start()


def runtime_install_manager(context: WebSessionContext) -> RuntimeInstallManager:
    service = getattr(context, "runtime_install_manager", None)
    if service is None:
        runtime_paths = getattr(context, "runtime_paths", None)
        if runtime_paths is None:
            raise RuntimeError("Runtime paths are not available")

        def refresh_tag_state() -> None:
            refresh_after_tag_data(context)

        def refresh_corpus_state() -> None:
            # 새로 설치된 코퍼스를 즉시 쓰려면 경로/메타데이터/파티션 캐시를 모두 버려야 한다.
            # (EventCorpusIndex.invalidate 는 epoch 도 올려서 진행 중이던 질의 결과가
            #  새 캐시에 되살아나는 것을 막는다.)
            from app.backend.server.event_corpus_commands import invalidate_event_corpus_service

            invalidate_event_corpus_service(context)

        def refresh_event_map_state() -> None:
            # 색인이 방금 제자리에 놓였다. 서비스는 "없다" 를 캐시하고 있으므로 버려야
            # 재시작 없이 Ctrl+E 가 연다.
            from app.backend.server.event_map_routes import invalidate_event_map_service

            invalidate_event_map_service(context)

        service = RuntimeInstallManager(
            runtime_paths,
            on_tag_archive_complete=refresh_tag_state,
            on_corpus_archive_complete=refresh_corpus_state,
            on_event_map_complete=refresh_event_map_state,
        )
        context.runtime_install_manager = service
    return service


def register_install_manager_routes(
    app: FastAPI,
    session_context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
) -> None:
    @app.get("/api/install-manager")
    async def api_install_manager_state(req: Request):
        try:
            snapshot = await run_in_thread(runtime_install_manager(session_context).snapshot)
            if not _is_local_request(req):
                return _sanitize_snapshot_for_remote(snapshot)
            return snapshot
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"Install manager state failed: {exc}"}, status_code=500)

    @app.post("/api/install-manager/initialize")
    async def api_install_manager_initialize(req: Request):
        if not _is_local_request(req):
            return _loopback_only_response()
        try:
            return await run_in_thread(runtime_install_manager(session_context).initialize)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"Install manager initialize failed: {exc}"}, status_code=500)

    @app.post("/api/install-manager/tag-archive/download")
    async def api_install_manager_tag_archive_download(req: Request):
        """태그 데이터를 설치한다 - 베이스(150) **뒤에 증분(150~174)까지** 이어 받는다.

        신규 설치가 150개에서 끝나면 안 된다(2026-09-12 사용자 지시). 이미 있는 것은
        건너뛰므로 150개만 가진 사용자가 눌러도 275MB 만 받는다.
        ⚠️ 베이스의 완성 판정(`TAG_ARCHIVE_EXPECTED_COUNT`)은 150 그대로다. 175 로 올리면
           150개를 가진 기존 사용자 전원이 1.4GB 를 다시 받는다.
        """
        if not _is_local_request(req):
            return _loopback_only_response()
        try:
            manager = runtime_install_manager(session_context)
            await run_in_thread(manager.start_tag_data_install)
            return await run_in_thread(manager.snapshot)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"Tag archive download failed: {exc}"}, status_code=500)

    @app.post("/api/install-manager/tag-archive-increment/download")
    async def api_install_manager_tag_increment_download(req: Request):
        """최신 태그 데이터(버킷 150~174). 검색 화면의 버튼이 부른다.

        ⚠️ 베이스가 아직 없으면 거절한다. 1.4GB 를 건너뛰고 275MB 만 받으면
        코퍼스가 반쪽이 되고, 그 상태를 사용자가 알아채기 어렵다.
        """
        if not _is_local_request(req):
            return _loopback_only_response()
        try:
            manager = runtime_install_manager(session_context)
            snapshot = await run_in_thread(manager.snapshot)
            if not (snapshot.get("tag_archive") or {}).get("ready"):
                return JSONResponse(
                    {"ok": False, "error": "기본 태그 데이터를 먼저 설치해야 합니다."},
                    status_code=409,
                )
            await run_in_thread(manager.start_tag_increment_download)
            return await run_in_thread(manager.snapshot)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"Tag increment download failed: {exc}"}, status_code=500)

    @app.post("/api/install-manager/corpus-archive/download")
    async def api_install_manager_corpus_archive_download(req: Request):
        if not _is_local_request(req):
            return _loopback_only_response()
        try:
            manager = runtime_install_manager(session_context)
            await run_in_thread(manager.start_corpus_archive_download)
            return await run_in_thread(manager.snapshot)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"Corpus archive download failed: {exc}"}, status_code=500)

    @app.post("/api/install-manager/corpus-archive/download/cancel")
    async def api_install_manager_corpus_archive_download_cancel(req: Request):
        if not _is_local_request(req):
            return _loopback_only_response()
        try:
            manager = runtime_install_manager(session_context)
            await run_in_thread(manager.cancel_archive_download)
            return await run_in_thread(manager.snapshot)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"Corpus archive download cancel failed: {exc}"}, status_code=500)

    @app.post("/api/install-manager/event-map/download")
    async def api_install_manager_event_map_download(req: Request):
        """이벤트 맵 색인(약 880MB, 파일 하나)을 받는다. Ctrl+E 패널이 부른다.

        ⚠️ 다운로더는 단일 비행이다 - 태그 데이터를 받는 중이면 그 진행 상태가 그대로
           돌아온다(`phase` 로 구분한다). 새 다운로드를 끼워 넣지 않는다.
        """
        if not _is_local_request(req):
            return _loopback_only_response()
        try:
            manager = runtime_install_manager(session_context)
            await run_in_thread(manager.start_event_map_download)
            return await run_in_thread(manager.snapshot)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"Event map download failed: {exc}"}, status_code=500)

    @app.post("/api/install-manager/event-map/download/cancel")
    async def api_install_manager_event_map_download_cancel(req: Request):
        if not _is_local_request(req):
            return _loopback_only_response()
        try:
            manager = runtime_install_manager(session_context)
            await run_in_thread(manager.cancel_archive_download)
            return await run_in_thread(manager.snapshot)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"Event map download cancel failed: {exc}"}, status_code=500)

    @app.post("/api/install-manager/tag-archive/download/cancel")
    async def api_install_manager_tag_archive_download_cancel(req: Request):
        if not _is_local_request(req):
            return _loopback_only_response()
        try:
            manager = runtime_install_manager(session_context)
            await run_in_thread(manager.cancel_tag_archive_download)
            return await run_in_thread(manager.snapshot)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"Tag archive download cancel failed: {exc}"}, status_code=500)
