# -*- coding: utf-8 -*-
"""Interactive Assets 라우트 — 캐릭터 조합 스냅샷 · 즐겨찾기.

    GET  /api/interactive-assets/snapshots        목록(메타만) + 검색·필터
    GET  /api/interactive-assets/snapshot         조합 본문(복구용)
    GET  /api/interactive-assets/snapshot/thumb   384px WEBP
    POST /api/interactive-assets/snapshot         조합 기록(프론트가 조합 변경 시 호출)
    POST /api/interactive-assets/favorite         즐겨찾기 토글

목록은 **본문을 읽지 않는다** — 인덱스의 `summary` 로 검색이 되도록 만들었다.
500개의 조합 본문을 매번 읽으면 목록이 느려진다.

서비스는 Interactive 모드에서만 쓰이므로 지연 생성한다(`core/interactive_assets_service`).
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from core.interactive_assets_service import InteractiveAssetsService
from core.web_session_context import WebSessionContext

AsyncRunner = Callable[..., Awaitable[Any]]


def interactive_assets_service(context: WebSessionContext) -> InteractiveAssetsService:
    service = getattr(context, "interactive_assets_service", None)
    if service is None:
        service = InteractiveAssetsService(context)
        context.interactive_assets_service = service
    return service


def register_interactive_assets_routes(
    app: FastAPI,
    session_context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
) -> None:
    @app.get("/api/interactive-assets/snapshots")
    async def api_interactive_snapshots(query: str = "", origin: str = "",
                                        favorite: bool = False, limit: int = 200):
        """메타 목록. 최신이 앞이다. `origin` = original|known, `favorite` = 즐겨찾기만."""
        def _payload() -> dict[str, Any]:
            svc = interactive_assets_service(session_context)
            rows = list(reversed(svc.load_index()))
            pinned = {f.get("ref") for f in svc.load_favorites()
                      if f.get("type") == "snapshot"}
            q = str(query or "").strip().lower()
            if q:
                rows = [r for r in rows if q in str(r.get("summary", "")).lower()]
            if origin in ("original", "known"):
                rows = [r for r in rows if r.get("origin") == origin]
            if favorite:
                rows = [r for r in rows if r.get("id") in pinned]
            rows = rows[: max(1, min(int(limit or 200), 500))]
            for r in rows:
                r["favorite"] = r.get("id") in pinned
            return {"count": len(rows), "snapshots": rows}

        try:
            return await run_in_thread(_payload)
        except Exception as exc:
            return JSONResponse({"error": f"snapshots failed: {exc}"}, status_code=500)

    @app.get("/api/interactive-assets/snapshot")
    async def api_interactive_snapshot(id: str = ""):
        """조합 본문. 사용자가 목록에서 고를 때만 읽는다."""
        try:
            body = await run_in_thread(
                interactive_assets_service(session_context).load_body, str(id or ""))
        except Exception as exc:
            return JSONResponse({"error": f"snapshot failed: {exc}"}, status_code=500)
        if body is None:
            return JSONResponse({"error": "snapshot not found"}, status_code=404)
        return body

    @app.get("/api/interactive-assets/snapshot/thumb")
    async def api_interactive_snapshot_thumb(id: str = ""):
        def _read() -> bytes | None:
            svc = interactive_assets_service(session_context)
            path = svc.snapshot_root / f"{str(id or '')}.webp"
            return path.read_bytes() if path.exists() else None

        try:
            raw = await run_in_thread(_read)
        except Exception as exc:
            return JSONResponse({"error": f"thumb failed: {exc}"}, status_code=500)
        if raw is None:
            return JSONResponse({"error": "thumb not found"}, status_code=404)
        return Response(content=raw, media_type="image/webp",
                        headers={"Cache-Control": "public, max-age=3600"})

    @app.post("/api/interactive-assets/snapshot")
    async def api_interactive_snapshot_record(req: Request):
        """캐릭터 한 명당 에셋 하나를 남긴다. 같은 캐릭터는 새로 쌓지 않고 갱신한다."""
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        chars = payload.get("chars") if isinstance(payload, dict) else None
        if not isinstance(chars, list) or not chars:
            return JSONResponse({"error": "chars required"}, status_code=400)
        # 씬 값은 받지 않는다 — 캐릭터 에셋에 씬 사본을 두지 않기로 했다.
        # 옛 프론트가 `globals` 를 보내도 그냥 무시된다(오류 아님).
        try:
            metas = await run_in_thread(
                interactive_assets_service(session_context).record, chars)
        except Exception as exc:
            return JSONResponse({"error": f"record failed: {exc}"}, status_code=500)
        # 캐릭터 수만큼 나온다. `snapshot` 은 남겨 두되 **첫 장만** 가리킨다 —
        # 이 키만 보는 호출부가 두 번째 캐릭터를 조용히 잃지 않도록 `snapshots` 를
        # 쓰게 하고, 옛 키는 깨지지 않을 정도로만 남긴다.
        return {"ok": True, "snapshots": metas,
                "snapshot": metas[0] if metas else None}

    @app.post("/api/interactive-assets/snapshot/delete")
    async def api_interactive_snapshot_delete(req: Request):
        """조합 하나를 지운다. 되돌릴 수 없다(본문 + 썸네일 + 즐겨찾기 참조)."""
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        snapshot_id = str((payload or {}).get("id") or "")
        if not snapshot_id:
            return JSONResponse({"error": "id required"}, status_code=400)
        try:
            removed = await run_in_thread(
                interactive_assets_service(session_context).delete_snapshot, snapshot_id)
        except Exception as exc:
            return JSONResponse({"error": f"delete failed: {exc}"}, status_code=500)
        return {"ok": True, "removed": bool(removed)}

    @app.post("/api/interactive-assets/favorite")
    async def api_interactive_favorite(req: Request):
        """즐겨찾기 토글. 실체가 아니라 참조만 담는다."""
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            on = await run_in_thread(
                interactive_assets_service(session_context).toggle_favorite,
                str(payload.get("type") or ""), str(payload.get("ref") or ""),
                str(payload.get("label") or ""))
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except RuntimeError as exc:
            # 즐겨찾기 파일이 깨져 옆으로 치운 직후다. 빈 목록 위에 바로 쓰지 않는다.
            return JSONResponse({"error": str(exc)}, status_code=409)
        except Exception as exc:
            return JSONResponse({"error": f"favorite failed: {exc}"}, status_code=500)
        return {"ok": True, "on": on}
