"""Temporary-search lifecycle and request boundaries shared by WS and HTTP."""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
import json

from core.temporary_search import temporary_search

command_workspace = ContextVar("search_workspace", default=None)
TEMPORARY_SEARCH_COMMAND_TYPES = {"begin_temporary_search", "end_temporary_search", "get_temporary_search_state"}


async def finish_thread_call(runner, *args, **kwargs):
    """Cancellation of a live WS task must not leave its worker mutating a new pool."""
    task = asyncio.create_task(runner(*args, **kwargs))
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(task)
            break
        except asyncio.CancelledError:
            if task.done():
                raise
            cancelled = True
    if cancelled:
        raise asyncio.CancelledError
    return result


async def send_state(ws, manager, **extra):
    payload = manager.payload(getattr(ws, "_search_session_id", ""))
    payload.update(extra)
    await ws.send_text(json.dumps(payload, ensure_ascii=False))


async def _finish(context, clients, run_in_thread, broadcast_json):
    manager = temporary_search(context)
    error = None
    try:
        while manager.busy():
            await asyncio.sleep(0.1)
        if manager.desired:
            await finish_thread_call(run_in_thread, manager.begin, manager.request_owner)
        # An owner can disconnect while the clone is being made.
        if not manager.desired:
            manager.end()
    except Exception as exc:
        error = str(exc)
    finally:
        manager.transition = False
        manager.task = None
    for client in list(clients):
        try:
            await send_state(client, manager, **({"error": error} if error else {}))
        except Exception:
            pass
    state = context.search_state_payload()
    state["workspace_changed"] = True
    state["tag_filter_settled"] = True
    await broadcast_json(clients, state)
    await broadcast_json(clients, {"type": "options", **context.get_options()})


async def handle_temporary_search_command(ws, context, clients, command, *, run_in_thread, broadcast_json):
    manager = temporary_search(context)
    kind = command.get("type")
    owner = getattr(ws, "_search_session_id", "")
    if kind == "get_temporary_search_state":
        await send_state(ws, manager)
        return
    if (manager.active and manager.owner != owner) or (manager.transition and manager.request_owner != owner):
        await send_state(ws, manager, error="다른 창에서 임시 검색을 사용 중입니다.")
        return
    desired = kind == "begin_temporary_search"
    if not manager.transition and desired == manager.active:
        await send_state(ws, manager)
        return
    manager.desired = desired
    manager.request_owner = owner
    manager.transition = True
    await send_state(ws, manager)
    if manager.task is None:
        manager.task = asyncio.create_task(_finish(context, clients, run_in_thread, broadcast_json))


def recover_disconnected_owner(context, clients, owner, *, run_in_thread, broadcast_json):
    manager = temporary_search(context)
    if not ((manager.active and manager.owner == owner)
            or (manager.transition and manager.request_owner == owner)):
        return
    manager.desired = False
    manager.transition = True
    manager.request_owner = owner
    if manager.task is None:
        manager.task = asyncio.create_task(_finish(context, clients, run_in_thread, broadcast_json))


def register_search_workspace_http_boundary(app, context):
    """Generation bridges follow the app's active pool; browser uploads prove ownership.

    This preserves the existing ComfyUI/REST bridge contract. Both kinds of work
    drain before a switch, so an external generation cannot cross the boundary.
    """
    from fastapi.responses import JSONResponse

    @app.middleware("http")
    async def search_workspace_boundary(request, call_next):
        path = request.url.path
        generation = path in {"/api/random", "/api/comfyui/random", "/api/generate"}
        scoped = generation or path == "/api/search/parquet/upload"
        tracked = scoped or request.method not in {"GET", "HEAD", "OPTIONS"}
        if not tracked:
            return await call_next(request)
        manager = temporary_search(context)
        workspace = request.headers.get("X-NAIA-Search-Workspace")
        owner = manager.owner if (workspace == manager.workspace_id and path == "/api/search/parquet/upload"
                                  and request.headers.get("X-NAIA-Search-Owner") == manager.upload_token) else ""
        stopping = path.endswith(("/stop", "/cancel"))
        if path == "/api/queue/action":
            try:
                payload = await request.json()
                stopping = isinstance(payload, dict) and payload.get("action") in {"pause", "clear", "remove"}
            except Exception:
                pass
        allowed = workspace in (None, manager.workspace_id) if generation else manager.permits(owner, workspace)
        if (manager.transition and not stopping) or (scoped and not allowed):
            return JSONResponse({"error": "임시 검색 전환 중이거나 다른 창에서 사용 중입니다."}, status_code=409)
        manager.operations += 1
        token = command_workspace.set(manager.workspace_id)
        try:
            return await finish_thread_call(call_next, request)
        finally:
            command_workspace.reset(token)
            manager.operations -= 1
