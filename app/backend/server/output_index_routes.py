"""Search and preview remotely. Host file actions require a loopback client."""
import os
import subprocess
import sys
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from app.backend.server.install_manager_routes import _is_local_request


class _Query(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    include: list[StrictStr] = Field(default_factory=list)
    exclude: list[StrictStr] = Field(default_factory=list)
    source: list[Literal["unknown", "NAI", "WEBUI", "ComfyUI", "COMFYUI", "NAIA"]] | None = None
    roots: list[StrictInt] | None = None
    text: str = ""
    sort: Literal["mtime_desc", "mtime_asc"] = "mtime_desc"
    offset: Annotated[int, Field(ge=0)] = 0
    limit: Annotated[int, Field(ge=1, le=500)] = 100
    dir_id: StrictInt | None = None


class _Folders(BaseModel):
    """Same filters as _Query; the page counts folders, not images."""
    model_config = ConfigDict(extra="forbid", strict=True)
    include: list[StrictStr] = Field(default_factory=list)
    exclude: list[StrictStr] = Field(default_factory=list)
    source: list[Literal["unknown", "NAI", "WEBUI", "ComfyUI", "COMFYUI", "NAIA"]] | None = None
    roots: list[StrictInt] | None = None
    text: str = ""
    sort: Literal["mtime_desc", "mtime_asc"] = "mtime_desc"
    offset: Annotated[int, Field(ge=0)] = 0
    limit: Annotated[int, Field(ge=1, le=200)] = 40
    samples: Annotated[int, Field(ge=1, le=12)] = 3


def _forbidden():
    return JSONResponse({"ok": False, "error": "Output index changes require a loopback client."}, status_code=403)


def _file_id(value):
    """'뿌리id:경로' -> (int, str). 화면이 본 그림의 이름표다."""
    if value is None:
        return None
    root_id, sep, rel = value.partition(":")
    if not sep or not root_id.isascii() or not root_id.isdigit() or len(root_id) > 18:
        raise HTTPException(422, "Expected id as root_id:path")
    return int(root_id), rel


def _int_or_none(value):
    """본문의 정수 하나(epoch) - 없으면 None. bool 은 정수가 아니다."""
    if value is None:
        return None
    if type(value) is not int:
        raise HTTPException(422, "Expected an integer epoch")
    return value


def _delete(service, rows, context, expect=None, epoch=None):
    from app.backend.server.result_display_routes import _move_to_trash

    removed_paths = set()

    def trash(path):
        if not _move_to_trash(path):
            return False
        removed_paths.add(os.path.normcase(os.path.abspath(path)))
        return True

    result = service.delete_rows(rows, trash, expect, epoch)
    store = getattr(context, "result_store", None)
    payloads = []
    if store is not None:
        with store.history_mutation():
            for item in store.history_snapshot():
                if item.filepath and os.path.normcase(os.path.abspath(item.filepath)) in removed_paths:
                    removed = store.remove_item(item, deleted=True)
                    if removed is not None:
                        payloads.append(store.viewer_removed_payload(removed))
        result["history_removed"] = [payload["rel_path"] for payload in payloads]
    return result, payloads


def _read_metadata(service, row, context, epoch=None):
    from app.backend.server.result_display_routes import (
        _metadata_for_disk_image, _with_current_wildcard_frozen_state,
    )

    path = service.file_path(row, epoch=epoch)
    if path is None:
        raise FileNotFoundError("Image not found")
    payload = _metadata_for_disk_image(path, path.name, include_full=True)
    return _with_current_wildcard_frozen_state(context, payload)


def _open_location(service, row, epoch=None):
    path = service.file_path(row, epoch=epoch)
    if path is None:
        raise HTTPException(404, "Image not found")
    if sys.platform == "win32":
        args = ["explorer.exe", f"/select,{path}"]
    elif sys.platform == "darwin":
        args = ["open", "-R", str(path)]
    else:
        args = ["xdg-open", str(path.parent)]
    subprocess.Popen(args)
    return {"ok": True, "folder": str(path.parent)}


def register_output_index_routes(app: FastAPI, context, *, run_in_thread, clients=None, broadcast_json=None):
    def service():
        from core.output_index.service import output_index_service
        return output_index_service(context)

    async def object_body(request):
        try:
            data = await request.json()
        except ValueError as exc:
            raise HTTPException(422, "Expected a JSON object") from exc
        if not isinstance(data, dict):
            raise HTTPException(422, "Expected a JSON object")
        return data

    async def change(func, *args):
        try:
            return await run_in_thread(func, *args)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.get("/api/output-index/status")
    async def status(request: Request):
        result = await run_in_thread(service().status)
        if not _is_local_request(request):
            for root in result["roots"]:
                root.pop("path", None)
            if result["last_error"]:
                result["last_error"] = "Index operation failed"
        return result

    @app.post("/api/output-index/roots")
    async def roots(request: Request):
        if not _is_local_request(request):
            return _forbidden()
        body = await object_body(request)
        action = body.get("action")
        rid = body.get("root_id")
        if action == "add" and isinstance(body.get("path"), str):
            rid = await change(service().add_root, body["path"])
        elif action == "remove" and type(rid) is int:
            await change(service().remove_root, rid)
        elif action in ("enable", "set_enabled") and type(rid) is int and type(body.get("enabled")) is bool:
            await change(service().set_root_enabled, rid, body["enabled"])
        else:
            raise HTTPException(422, "Expected add/path, remove/root_id or set_enabled/root_id/enabled")
        return {"ok": True, "root_id": rid}

    @app.post("/api/output-index/rescan")
    async def rescan(request: Request):
        if not _is_local_request(request):
            return _forbidden()
        service().request_rescan()
        return {"ok": True}

    @app.post("/api/output-index/query")
    async def query(body: _Query):
        return await run_in_thread(service().query, **body.model_dump())

    @app.post("/api/output-index/folders")
    async def folders(body: _Folders):
        return await run_in_thread(service().folders, **body.model_dump())

    # 최근 검색어 · 즐겨찾기 - 원격(휴대폰)에서도 같은 목록을 쓴다. 파일 작업이 아니라 이 PC 제한은 없다.
    @app.get("/api/output-index/saved")
    async def saved_state():
        from core.output_index.saved_searches import saved_searches
        return await run_in_thread(saved_searches(context).state)

    @app.post("/api/output-index/saved")
    async def saved_change(request: Request):
        from core.output_index.saved_searches import saved_searches
        body = await object_body(request)
        try:
            return await run_in_thread(saved_searches(context).apply, body)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/output-index/suggest")
    async def suggest(q: str = "", limit: int = Query(20, ge=1, le=500),
                      include: list[str] = Query(default=[]), exclude: list[str] = Query(default=[])):
        return await run_in_thread(service().suggest, q, limit, include, exclude)

    @app.get("/api/output-index/file")
    async def file(request: Request, row: int, id: str | None = None, epoch: int | None = None):
        params = request.query_params
        if params.keys() - {"row", "id", "epoch"} or len(params.multi_items()) != len(params):
            raise HTTPException(422, "Expected a row number only")
        path = await run_in_thread(service().checked_path, row, _file_id(id), epoch)
        if path is None:
            raise HTTPException(404, "Image not found")
        return FileResponse(path)

    @app.get("/api/output-index/thumb")
    async def thumb(request: Request, row: int, size: Literal["128", "192", "256", "384"] = "256", id: str | None = None,
                    epoch: int | None = None):
        params = request.query_params
        if params.keys() - {"row", "size", "id", "epoch"} or len(params.multi_items()) != len(params):
            raise HTTPException(422, "Expected a row and optional size")
        # id = 화면이 본 '뿌리id:경로' - 지금 그 행이 다른 그림이면 404(캐시에 남의 그림이 붙지 않게).
        expect = _file_id(id)
        try:
            data = await run_in_thread(service().thumbnail, row, int(size), expect, epoch)
        except (OSError, ValueError, Image.DecompressionBombError):
            # 깨진 파일 · 지워진 파일 - 격자 한 칸이 500 으로 콘솔을 채우지 않게 404 로 둔다.
            data = None
        if data is None:
            raise HTTPException(404, "Image not found")
        return Response(data, media_type="image/webp", headers={"Cache-Control": "private, max-age=86400"})

    @app.get("/api/output-index/meta")
    async def meta(row: int, epoch: int | None = None):
        result = await run_in_thread(service().metadata, row, epoch)
        if result is None:
            raise HTTPException(404, "Image not found")
        return result

    @app.get("/api/output-index/metadata")
    async def metadata(request: Request, row: int, epoch: int | None = None):
        params = request.query_params
        if params.keys() - {"row", "epoch"} or len(params.multi_items()) != len(params):
            raise HTTPException(422, "Expected a row number only")
        try:
            return await run_in_thread(_read_metadata, service(), row, context, epoch)
        except FileNotFoundError as exc:
            raise HTTPException(404, "Image not found") from exc
        except Exception as exc:
            # The exception text can carry absolute paths - keep it in the server log only.
            print(f"[output-index] metadata read failed for row {row}: {type(exc).__name__}")
            return JSONResponse({"error": "Metadata extract failed"}, status_code=400)

    @app.post("/api/output-index/delete")
    async def delete(request: Request):
        if not _is_local_request(request):
            return _forbidden()
        body = await object_body(request)
        rows = body.get("rows")
        if (not {"rows"} <= body.keys() <= {"rows", "expect", "epoch"} or not isinstance(rows, list) or not 1 <= len(rows) <= 200
                or any(type(row) is not int for row in rows) or len(set(rows)) != len(rows)):
            raise HTTPException(422, "Expected 1 to 200 unique integer rows")
        # expect = 화면이 본 [뿌리 id, 경로] - 행마다 하나. 있으면 다른 그림을 지우지 않게 대조한다.
        expect = body.get("expect")
        if "expect" in body:
            if (not isinstance(expect, list) or len(expect) != len(rows)
                    or any(not isinstance(e, list) or len(e) != 2 or type(e[0]) is not int
                           or not isinstance(e[1], str) for e in expect)):
                raise HTTPException(422, "Expected one [root_id, path] per row")
            expect = [(e[0], e[1]) for e in expect]
        epoch = _int_or_none(body.get("epoch")) if "epoch" in body else None
        if "epoch" in body and epoch is None:
            raise HTTPException(422, "Expected an integer epoch")
        result, payloads = await change(_delete, service(), rows, context, expect, epoch)
        if broadcast_json is not None and clients is not None and payloads:
            for payload in payloads:
                await broadcast_json(clients, payload)
            await broadcast_json(clients, context.auto_save_state_payload())
        return result

    @app.post("/api/output-index/open-location")
    async def open_location(request: Request):
        if not _is_local_request(request):
            return _forbidden()
        body = await object_body(request)
        if not {"row"} <= body.keys() <= {"row", "epoch"} or type(body["row"]) is not int:
            raise HTTPException(422, "Expected an integer row")
        if "epoch" in body and type(body["epoch"]) is not int:
            raise HTTPException(422, "Expected an integer epoch")
        return await run_in_thread(_open_location, service(), body["row"], body.get("epoch"))
