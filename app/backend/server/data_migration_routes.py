"""Routes for importing a legacy NAIA checkout's user data into user_root.

Loopback-gated: these endpoints read/write the *server's* filesystem (the machine
the backend runs on), so a remote Remote Web client must not be able to trigger a
filesystem import. Only same-machine (loopback) callers are allowed.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.data_migration_service import DataMigrationService
from core.headless_payload_utils import is_loopback_host
from core.web_session_context import WebSessionContext

AsyncRunner = Callable[..., Awaitable[Any]]


def data_migration_service(context: WebSessionContext) -> DataMigrationService:
    service = getattr(context, "data_migration_service", None)
    if service is None:
        service = DataMigrationService(context)
        context.data_migration_service = service
    return service


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


async def _json_body(req: Request) -> dict[str, Any]:
    try:
        payload = await req.json()
    except Exception:
        payload = {}
    return payload if isinstance(payload, dict) else {}


def register_data_migration_routes(
    app: FastAPI,
    session_context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
) -> None:
    @app.post("/api/data-migration/preview")
    async def api_data_migration_preview(req: Request):
        if not _is_local_request(req):
            return JSONResponse(
                {"ok": False, "runtime": "web", "error": "데이터 가져오기는 로컬에서만 가능합니다."},
                status_code=403,
            )
        body = await _json_body(req)
        source = str(body.get("source") or "").strip()
        if not source:
            return JSONResponse({"ok": False, "error": "가져올 폴더 경로가 비어 있습니다."}, status_code=400)
        try:
            result = await run_in_thread(data_migration_service(session_context).preview, source)
            return {"ok": result.get("error") is None, "runtime": "web", **result}
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"미리보기 실패: {exc}"}, status_code=500)

    @app.post("/api/data-migration/import")
    async def api_data_migration_import(req: Request):
        if not _is_local_request(req):
            return JSONResponse(
                {"ok": False, "runtime": "web", "error": "데이터 가져오기는 로컬에서만 가능합니다."},
                status_code=403,
            )
        body = await _json_body(req)
        source = str(body.get("source") or "").strip()
        if not source:
            return JSONResponse({"ok": False, "error": "가져올 폴더 경로가 비어 있습니다."}, status_code=400)
        conflict = str(body.get("conflict") or "skip")
        include = body.get("include")
        include = [str(item) for item in include] if isinstance(include, list) else None
        try:
            result = await run_in_thread(
                data_migration_service(session_context).import_from,
                source,
                conflict=conflict,
                include=include,
            )
            status = 200 if result.get("ok") else 400
            return JSONResponse({"runtime": "web", **result}, status_code=status)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"가져오기 실패: {exc}"}, status_code=500)

    @app.post("/api/data-migration/nai-token")
    async def api_data_migration_nai_token(req: Request):
        if not _is_local_request(req):
            return JSONResponse(
                {"ok": False, "runtime": "web", "error": "토큰 가져오기는 로컬에서만 가능합니다."},
                status_code=403,
            )
        body = await _json_body(req)
        source = str(body.get("source") or "").strip()
        if not source:
            return JSONResponse({"ok": False, "error": "가져올 폴더 경로가 비어 있습니다."}, status_code=400)
        overwrite = bool(body.get("overwrite"))
        try:
            result = await run_in_thread(
                data_migration_service(session_context).import_nai_token,
                source,
                overwrite=overwrite,
            )
            # ``needs_confirm`` is not an error — the client must prompt and retry
            # with ``overwrite`` — so surface it with a 200 alongside successes.
            status = 200 if (result.get("ok") or result.get("needs_confirm")) else 400
            return JSONResponse({"runtime": "web", **result}, status_code=status)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"토큰 가져오기 실패: {exc}"}, status_code=500)
