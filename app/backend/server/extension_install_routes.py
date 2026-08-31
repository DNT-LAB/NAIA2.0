"""GitHub URL 확장 설치 라우트 (loopback 전용).

설치는 host 파일시스템에 코드를 배치하는 부작용이라, install-manager 라우트와
동일하게 loopback-gated 한다 — 원격 Remote Web 클라이언트가 임의 GitHub URL로
host에 확장을 깔지 못하게 막는다(RCE 방지). 읽기 전용 상태 조회는 누구나(진행률
렌더용).
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.extension_install_service import ExtensionInstallService
from core.headless_payload_utils import is_loopback_host
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


def _loopback_only() -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": "확장 설치는 로컬에서만 가능합니다."},
        status_code=403,
    )


def extension_install_service(context: WebSessionContext) -> ExtensionInstallService:
    service = getattr(context, "extension_install_service", None)
    if service is None:
        runtime_paths = getattr(context, "runtime_paths", None)
        if runtime_paths is None:
            raise RuntimeError("Runtime paths are not available")
        service = ExtensionInstallService(runtime_paths.extensions_dir)
        context.extension_install_service = service
    return service


def register_extension_install_routes(
    app: FastAPI,
    context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
) -> None:
    @app.get("/api/extensions/install")
    async def api_extension_install_state(req: Request):
        try:
            return await run_in_thread(extension_install_service(context).snapshot)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"설치 상태 조회 실패: {exc}"}, status_code=500)

    @app.get("/api/extensions/update-check")
    async def api_extension_update_check(req: Request):
        """레포 루트의 매니페스트만 읽어 원격 버전을 알려 준다(zip 을 안 받는다).

        ⚠️ 설치와 달리 **루프백 전용이 아니다** - 읽기만 하고 이 기기에 아무것도
        바꾸지 않는다. 원격에서도 "새 판이 있나" 는 볼 수 있어야 한다.
        """
        from core.extension_install_service import compare_versions, fetch_remote_manifest

        url = str(req.query_params.get("url") or "").strip()
        if not url:
            return JSONResponse({"ok": False, "error": "주소가 없습니다."}, status_code=400)
        installed = str(req.query_params.get("installed") or "").strip()
        try:
            remote = await run_in_thread(fetch_remote_manifest, url)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"확인 실패: {exc}"}, status_code=502)
        if not remote.get("found"):
            # 매니페스트가 하위 폴더에 있는 레포는 여기서 못 본다 - 실패가 아니라
            # "모른다" 다. 화면이 그렇게 말한다.
            return {"ok": True, "known": False, "error": remote.get("error") or ""}
        latest = str(remote.get("version") or "")
        return {
            "ok": True,
            "known": True,
            "id": remote.get("id") or "",
            "latest": latest,
            "installed": installed,
            # 설치된 판을 함께 주면 비교도 여기서 한다 - 화면이 버전 규약을 한 벌
            # 더 들면 두 곳이 어긋난다(`0.10.0` vs `0.9.0` 같은 자리에서 갈린다).
            "outdated": bool(installed) and compare_versions(latest, installed) > 0,
        }

    @app.post("/api/extensions/install")
    async def api_extension_install_start(req: Request):
        if not _is_local_request(req):
            return _loopback_only()
        try:
            body = await req.json()
        except Exception:
            body = {}
        url = str((body or {}).get("url") or "").strip()
        if not url:
            return JSONResponse({"ok": False, "error": "GitHub 주소를 입력하세요."}, status_code=400)
        try:
            return await run_in_thread(extension_install_service(context).start, url)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"설치 시작 실패: {exc}"}, status_code=500)

    @app.post("/api/extensions/install/sample")
    async def api_extension_install_sample(req: Request):
        # 번들 샘플 확장 원클릭 설치(로컬 파일 복사) — GitHub 설치와 동일하게 loopback 전용.
        if not _is_local_request(req):
            return _loopback_only()
        try:
            body = await req.json()
        except Exception:
            body = {}
        sample = str((body or {}).get("sample") or "seed_fanout").strip() or "seed_fanout"
        runtime_paths = getattr(context, "runtime_paths", None)
        if runtime_paths is None:
            return JSONResponse({"ok": False, "error": "Runtime paths are not available"}, status_code=500)
        samples_root = runtime_paths.resource_path("release_assets/samples/extensions")
        try:
            return await run_in_thread(
                extension_install_service(context).install_sample, sample, samples_root
            )
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"샘플 설치 실패: {exc}"}, status_code=500)

    @app.post("/api/extensions/install/cancel")
    async def api_extension_install_cancel(req: Request):
        if not _is_local_request(req):
            return _loopback_only()
        try:
            return await run_in_thread(extension_install_service(context).cancel)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"설치 취소 실패: {exc}"}, status_code=500)
