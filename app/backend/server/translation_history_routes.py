"""번역 기록(Translation History) 조회 라우트.

조회(GET)는 모든 클라이언트에 열려 있다(원격 세션도 기록을 렌더해야 함). 반면
**상태를 변경하는 동작**(삭제 / 핀 토글)은 호스트의 로컬 기록 파일을 수정하므로
install-manager/ollama 제어 엔드포인트와 동일하게 **루프백 게이트**를 건다: 원격
Remote Web 클라이언트가 호스트의 번역 기록을 지우거나 핀 상태를 바꿀 수 없어야 한다.

엔드포인트::

    GET    /api/translation-history?q=<검색어>&limit=<N>&direction=<ko->en|en->ko>
    DELETE /api/translation-history/{id}            (로컬 전용)
    POST   /api/translation-history/{id}/pin  {pinned: bool}   (로컬 전용)

``q``가 비어 있으면 (선택한 direction의) 최근 기록을, 있으면 source+translated에 대한
대소문자 무시 부분 문자열 검색 결과를 최신 우선으로 반환한다. GET 응답에는 별도로
``pinned`` 목록(핀 처리된 레코드)도 포함되어 프론트가 2단 패널을 한 번에 그릴 수 있다.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# 삭제/핀은 로컬 머신 부작용 → install-manager/ollama와 동일한 루프백 게이트 재사용.
from app.backend.server.install_manager_routes import _is_local_request
from core.translation_history import (
    delete_translation,
    get_log_path,
    get_pinned_translations,
    get_recent_translations,
    search_translations,
    set_pinned,
)

AsyncRunner = Callable[..., Awaitable[Any]]

# limit 상한(과도한 응답 방지).
_MAX_LIMIT = 500
_DEFAULT_LIMIT = 50


def _loopback_only_response() -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": "번역 기록 수정(삭제/핀)은 NAIA가 실행 중인 PC에서만 가능합니다."},
        status_code=403,
    )


def _clamp_limit(value: int | None) -> int:
    try:
        n = int(value) if value is not None else _DEFAULT_LIMIT
    except Exception:
        n = _DEFAULT_LIMIT
    if n <= 0:
        n = _DEFAULT_LIMIT
    return min(n, _MAX_LIMIT)


def register_translation_history_routes(
    app: FastAPI,
    context: Any = None,
    *,
    run_in_thread: AsyncRunner,
) -> None:
    @app.get("/api/translation-history")
    async def translation_history(
        request: Request,
        q: str = "",
        limit: int = _DEFAULT_LIMIT,
        direction: str | None = None,
    ):
        # 파일 IO(읽기/파싱)라 스레드로 — 이벤트 루프 비차단.
        n = _clamp_limit(limit)
        query = str(q or "").strip()
        dir_filter = str(direction).strip() if direction else None
        # 호스트 파일시스템 절대경로(log_path)는 정보 노출이므로 루프백 클라이언트에만
        # 내려준다(install_manager_routes 가 host 경로를 strip 하는 것과 동일 정책).
        # 원격 Remote Web 세션은 경로를 알 필요가 없다.
        is_local = _is_local_request(request)

        def _collect() -> dict[str, Any]:
            if query or dir_filter:
                records = search_translations(query, limit=n, direction=dir_filter)
            else:
                records = get_recent_translations(limit=n)
            # 핀 목록은 항상 별도로 — 2단 패널(상단 Pinned / 하단 History)을 한 번의
            # GET으로 그릴 수 있게. 검색/필터와 무관하게 핀은 전부 노출한다.
            pinned = get_pinned_translations(limit=_MAX_LIMIT)
            payload: dict[str, Any] = {
                "ok": True,
                "query": query,
                "direction": dir_filter or "",
                "count": len(records),
                "records": records,
                "pinned": pinned,
                "pinned_count": len(pinned),
            }
            if is_local:
                payload["log_path"] = str(get_log_path())
            return payload

        try:
            return await run_in_thread(_collect)
        except Exception as exc:  # pragma: no cover - 방어적; 모듈은 best-effort
            return JSONResponse(
                {"ok": False, "error": str(exc), "records": [], "count": 0},
                status_code=500,
            )

    @app.delete("/api/translation-history/{record_id}")
    async def translation_history_delete(request: Request, record_id: str):
        # 로컬 기록 파일을 수정 → 루프백 전용.
        if not _is_local_request(request):
            return _loopback_only_response()

        def _delete() -> dict[str, Any]:
            ok = delete_translation(record_id)
            return {"ok": bool(ok), "id": record_id, "deleted": bool(ok)}

        try:
            return await run_in_thread(_delete)
        except Exception as exc:  # pragma: no cover - best-effort
            return JSONResponse({"ok": False, "error": str(exc), "id": record_id}, status_code=500)

    @app.post("/api/translation-history/{record_id}/pin")
    async def translation_history_pin(request: Request, record_id: str):
        # 핀 상태(영속)를 변경 → 루프백 전용.
        if not _is_local_request(request):
            return _loopback_only_response()
        pinned = True
        try:
            payload = await request.json()
            if isinstance(payload, dict) and "pinned" in payload:
                pinned = bool(payload.get("pinned"))
        except Exception:
            pinned = True  # 본문 없거나 파싱 실패 → 핀(기본)

        def _pin() -> dict[str, Any]:
            ok = set_pinned(record_id, pinned)
            return {"ok": bool(ok), "id": record_id, "pinned": pinned}

        try:
            return await run_in_thread(_pin)
        except Exception as exc:  # pragma: no cover - best-effort
            return JSONResponse({"ok": False, "error": str(exc), "id": record_id}, status_code=500)


__all__ = ["register_translation_history_routes"]
