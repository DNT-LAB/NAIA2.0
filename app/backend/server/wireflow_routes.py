"""Wire-Flow REST — /api/wireflow/*(사용자 지시 2026-10-31).

조건부 와일드카드 워크플로우(노드 그래프)의 공용 목록 · 저장 · 모드. 저장소 = `core/wireflow_store.py`.
바뀌면 WS `{"type": "wireflow_state"}` 를 뿌린다 - 다른 창(탭)이 목록 · W 단추를 다시 읽는다.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.web_session_context import WebSessionContext
from core.wireflow_store import WireFlowError, WireFlowStore, wireflow_store

AsyncRunner = Callable[..., Awaitable[Any]]
JsonBroadcaster = Callable[[set[Any], dict[str, Any]], Awaitable[None]]


def _no_store() -> dict[str, str]:
    return {"Cache-Control": "no-store"}


def _error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "message": message}, status_code=status, headers=_no_store())


async def _read_json(req: Request) -> dict[str, Any]:
    try:
        payload = await req.json()
    except Exception:
        payload = {}
    return payload if isinstance(payload, dict) else {}


def register_wireflow_routes(
    app: FastAPI,
    session_context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
    clients: set[Any] | None = None,
    broadcast_json: JsonBroadcaster | None = None,
) -> None:
    def _store() -> WireFlowStore:
        store = wireflow_store(session_context)
        if store is None:
            raise WireFlowError("저장 위치를 찾지 못했습니다.")
        return store

    async def _broadcast() -> None:
        if clients is not None and broadcast_json is not None:
            await broadcast_json(clients, {"type": "wireflow_state"})

    @app.get("/api/wireflow")
    async def api_wireflow_state():
        try:
            state = await run_in_thread(_store().state)
        except WireFlowError as exc:
            return _error(str(exc))
        return JSONResponse({"ok": True, **state}, headers=_no_store())

    @app.get("/api/wireflow/workflow")
    async def api_wireflow_workflow(id: str = ""):
        try:
            workflow = await run_in_thread(_store().get, id)
        except WireFlowError as exc:
            return _error(str(exc), 404)
        return JSONResponse({"ok": True, "workflow": workflow}, headers=_no_store())

    @app.post("/api/wireflow/test")
    async def api_wireflow_test(req: Request):
        """캔버스의 그래프(저장 안 된 것도)를 테스트 입력으로 한 번 흘린다 - 노드마다 Probe. 읽기 전용(생성 · 저장 없음)."""
        body = await _read_json(req)
        from core.wireflow_runner import run_wireflow_test

        try:
            result = await run_in_thread(run_wireflow_test, session_context, body.get("graph"), body.get("input"))
        except WireFlowError as exc:
            return _error(str(exc))
        return JSONResponse({"ok": True, **result}, headers=_no_store())

    @app.post("/api/wireflow")
    async def api_wireflow_change(req: Request):
        """save_new(name, graph) · save(id, graph) · rename(id, name) · delete(id) · activate(id | '') · mode(on)."""
        body = await _read_json(req)
        action = body.get("action")
        created = ""
        try:
            store = _store()
            if action == "save_new":
                created = await run_in_thread(store.save_new, body.get("name"), body.get("graph"))
            elif action == "save":
                await run_in_thread(store.save, body.get("id"), body.get("graph"))
            elif action == "rename":
                await run_in_thread(store.rename, body.get("id"), body.get("name"))
            elif action == "delete":
                await run_in_thread(store.delete, body.get("id"))
            elif action == "activate":
                await run_in_thread(store.activate, body.get("id") or "")
            elif action == "mode":
                await run_in_thread(store.set_mode, body.get("on") is True)
            else:
                return _error("지원하지 않는 작업입니다.")
            state = await run_in_thread(store.state)
        except WireFlowError as exc:
            return _error(str(exc))
        await _broadcast()
        return JSONResponse({"ok": True, "created": created, **state}, headers=_no_store())
