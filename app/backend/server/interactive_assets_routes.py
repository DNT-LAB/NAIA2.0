# -*- coding: utf-8 -*-
"""Interactive Assets 라우트 — 캐릭터 조합 스냅샷 · 즐겨찾기.

    GET  /api/interactive-assets/snapshots        목록(메타만) + 검색·필터
    GET  /api/interactive-assets/snapshot         조합 본문(복구용)
    GET  /api/interactive-assets/snapshot/thumb   384px WEBP
    POST /api/interactive-assets/snapshot         조합 기록(프론트가 조합 변경 시 호출)
    POST /api/interactive-assets/snapshot/delete  조합 삭제
    GET  /api/interactive-assets/scenes           씬(이벤트) 목록
    GET  /api/interactive-assets/scene            씬 본문(복구용)
    GET  /api/interactive-assets/scene/thumb      384px WEBP
    POST /api/interactive-assets/scene            씬 기록
    POST /api/interactive-assets/scene/delete     씬 삭제
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
    async def api_interactive_snapshot_thumb(id: str = "", v: str = ""):
        # `v` 는 화면이 붙이는 판(`thumb_rev`)이라 서버가 읽지 않는다. **같은 id 에 새
        # 그림이 덮이므로**(record 의 prompt_hash 재사용) 이것 없이는 캐시된 옛 그림이
        # 계속 나온다. 사용자가 만든 개인 이미지라 `private` 이기도 하다.
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
                        headers={"Cache-Control": "private, max-age=3600"})

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

    # ── 씬(이벤트) ─────────────────────────────────────────────────────────
    # 캐릭터 쪽과 같은 모양이되 **단위가 하나**다: 생성 1회 = 씬 1장.
    # `origin`(known/original) 은 캐릭터 태그 판정이라 씬에는 없다.
    @app.get("/api/interactive-assets/scenes")
    async def api_interactive_scenes(query: str = "", favorite: bool = False,
                                     limit: int = 200, tier: str = "",
                                     folder: str = ""):
        """`tier` = auto(자동 기록) | saved(저장한 씬) | 빈값(전부).

        `folder` 는 저장한 씬에만 의미가 있다. **대카테고리를 주면 그 아래
        소카테고리에 든 것까지 함께** 나온다(사용자 지정 2026-08-12: 대카테고리를
        고르면 그 안의 모든 아이템을 나열). `folder=none` 이면 폴더가 없는 것만.
        """
        def _payload() -> dict[str, Any]:
            svc = interactive_assets_service(session_context)
            rows = list(reversed(svc.load_scene_index()))
            pinned = {f.get("ref") for f in svc.load_favorites()
                      if f.get("type") == "scene"}
            if tier == "saved":
                rows = [r for r in rows if r.get("saved")]
                # 저장한 씬은 **저장한 시각** 순이다 - created_at 은 그림을 만든
                # 때라, 옛 그림을 나중에 저장하면 목록 아래로 파묻힌다.
                rows.sort(key=lambda r: int(r.get("saved_at") or 0), reverse=True)
            elif tier == "auto":
                rows = [r for r in rows if not r.get("saved")]
            q = str(query or "").strip().lower()
            if q:
                rows = [r for r in rows
                        if q in str(r.get("summary", "")).lower()
                        or q in str(r.get("name", "")).lower()]
            if folder == "none":
                rows = [r for r in rows if not str(r.get("folder") or "")]
            elif folder:
                want = svc._folder_and_children(folder)
                rows = [r for r in rows if str(r.get("folder") or "") in want]
            if favorite:
                rows = [r for r in rows if r.get("id") in pinned]
            rows = rows[: max(1, min(int(limit or 200), 500))]
            for r in rows:
                r["favorite"] = r.get("id") in pinned
            return {"count": len(rows), "scenes": rows}

        try:
            return await run_in_thread(_payload)
        except Exception as exc:
            return JSONResponse({"error": f"scenes failed: {exc}"}, status_code=500)

    @app.post("/api/interactive-assets/scene/save")
    async def api_interactive_scene_save(req: Request):
        """자동 기록 하나를 수집으로 올린다(이름·폴더). 본문은 복사하지 않는다."""
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        scene_id = str(payload.get("id") or "")
        if not scene_id:
            return JSONResponse({"error": "id required"}, status_code=400)
        svc = interactive_assets_service(session_context)
        try:
            if payload.get("on") is False:
                ok = await run_in_thread(svc.unsave_scene, scene_id)
                return {"ok": True, "saved": False, "changed": bool(ok)}
            meta = await run_in_thread(svc.save_scene, scene_id,
                                       str(payload.get("name") or ""),
                                       str(payload.get("folder") or ""))
        except Exception as exc:
            return JSONResponse({"error": f"save failed: {exc}"}, status_code=500)
        if meta is None:
            return JSONResponse({"error": "scene not found"}, status_code=404)
        return {"ok": True, "saved": True, "scene": meta}

    @app.post("/api/interactive-assets/scene/lookup")
    async def api_interactive_scene_lookup(req: Request):
        """지금 상태가 이미 기록/저장된 씬인지만 알려준다. 기록하지 않는다."""
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            info = await run_in_thread(
                interactive_assets_service(session_context).lookup_scene,
                payload.get("globals") or {}, payload.get("chars") or [])
        except Exception as exc:
            return JSONResponse({"error": f"lookup failed: {exc}"}, status_code=500)
        return {"ok": True, **info}

    @app.post("/api/interactive-assets/scene/update")
    async def api_interactive_scene_update(req: Request):
        """저장한 씬의 이름/폴더만 고친다. 준 항목만 바뀐다."""
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        scene_id = str(payload.get("id") or "")
        if not scene_id:
            return JSONResponse({"error": "id required"}, status_code=400)
        try:
            meta = await run_in_thread(
                interactive_assets_service(session_context).update_scene, scene_id,
                payload.get("name"), payload.get("folder"))
        except Exception as exc:
            return JSONResponse({"error": f"update failed: {exc}"}, status_code=500)
        if meta is None:
            return JSONResponse({"error": "scene not found"}, status_code=404)
        return {"ok": True, "scene": meta}

    @app.get("/api/interactive-assets/scene/folders")
    async def api_interactive_scene_folders():
        try:
            rows = await run_in_thread(
                interactive_assets_service(session_context).load_scene_folders)
        except Exception as exc:
            return JSONResponse({"error": f"folders failed: {exc}"}, status_code=500)
        return {"count": len(rows), "folders": rows}

    @app.post("/api/interactive-assets/scene/folders")
    async def api_interactive_scene_folder_op(req: Request):
        """`op` = create | rename | delete. 삭제는 **폴더만** 지우고 안의 씬은
        폴더 없음으로 옮긴다 - 정리하다 저장해 둔 씬을 잃으면 되돌릴 수 없다."""
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        svc = interactive_assets_service(session_context)
        op = str(payload.get("op") or "")
        name = str(payload.get("name") or "")
        fid = str(payload.get("id") or "")
        try:
            if op == "create":
                # `parent` 를 주면 소카테고리다. 2단까지만 — 소카테고리를 부모로
                # 주면 서비스가 그 대카테고리 밑으로 붙인다.
                row = await run_in_thread(svc.create_scene_folder, name,
                                          str(payload.get("parent") or ""))
                if row is None:
                    return JSONResponse({"error": "name required"}, status_code=400)
                return {"ok": True, "folder": row}
            if op == "rename":
                ok = await run_in_thread(svc.rename_scene_folder, fid, name)
                if not ok:
                    return JSONResponse({"error": "folder not found"}, status_code=404)
                return {"ok": True}
            if op == "delete":
                ok = await run_in_thread(svc.delete_scene_folder, fid)
                if not ok:
                    return JSONResponse({"error": "folder not found"}, status_code=404)
                return {"ok": True}
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"folder op failed: {exc}"}, status_code=500)
        return JSONResponse({"error": "unknown op"}, status_code=400)

    @app.get("/api/interactive-assets/scene")
    async def api_interactive_scene(id: str = ""):
        """씬 본문 — 씬 값 + 캐릭터의 '상황'(정체성은 프론트가 이미 걷어냈다)."""
        try:
            body = await run_in_thread(
                interactive_assets_service(session_context).load_scene_body,
                str(id or ""))
        except Exception as exc:
            return JSONResponse({"error": f"scene failed: {exc}"}, status_code=500)
        if body is None:
            return JSONResponse({"error": "scene not found"}, status_code=404)
        return body

    @app.get("/api/interactive-assets/scene/thumb")
    async def api_interactive_scene_thumb(id: str = "", v: str = ""):
        # 캐릭터 스냅샷과 같은 계약 — `v` 는 캐시 버스트용, 응답은 `private`.
        def _read() -> bytes | None:
            svc = interactive_assets_service(session_context)
            path = svc.scene_root / f"{str(id or '')}.webp"
            return path.read_bytes() if path.exists() else None

        try:
            raw = await run_in_thread(_read)
        except Exception as exc:
            return JSONResponse({"error": f"thumb failed: {exc}"}, status_code=500)
        if raw is None:
            return JSONResponse({"error": "thumb not found"}, status_code=404)
        return Response(content=raw, media_type="image/webp",
                        headers={"Cache-Control": "private, max-age=3600"})

    @app.post("/api/interactive-assets/scene")
    async def api_interactive_scene_record(req: Request):
        """씬 하나를 남긴다. 같은 씬이면 새로 쌓지 않고 갱신한다.

        `chars` 는 **정체성을 걷어낸 뒤** 온다 — 무엇을 복원하는가의 정의는
        프론트 한 곳에 둔다(백엔드가 슬롯 이름을 또 알면 축이 바뀔 때 갈라진다).
        캐릭터가 없는 씬(배경만)도 유효하므로 빈 목록을 거부하지 않는다.
        """
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        globals_ = payload.get("globals")
        if not isinstance(globals_, dict):
            return JSONResponse({"error": "globals required"}, status_code=400)
        chars = payload.get("chars")
        if not isinstance(chars, list):
            chars = []
        try:
            meta = await run_in_thread(
                interactive_assets_service(session_context).record_scene,
                globals_, chars)
        except Exception as exc:
            return JSONResponse({"error": f"record failed: {exc}"}, status_code=500)
        # 값어치가 없으면 `scene: null` 이다(오류가 아니다). 프론트는 이때
        # `interactive_scene_id` 를 싣지 않는다 - 붙일 카드가 없으므로 썸네일도 없다.
        if meta is None:
            return {"ok": True, "scene": None, "skipped": "empty"}
        return {"ok": True, "scene": meta}

    @app.post("/api/interactive-assets/scene/delete")
    async def api_interactive_scene_delete(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        scene_id = str((payload or {}).get("id") or "")
        if not scene_id:
            return JSONResponse({"error": "id required"}, status_code=400)
        try:
            removed = await run_in_thread(
                interactive_assets_service(session_context).delete_scene, scene_id)
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
