"""Read-only searches are available remotely; changing what the host indexes is not."""
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
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


def _forbidden():
    return JSONResponse({"ok": False, "error": "Output index changes require a loopback client."}, status_code=403)


def register_output_index_routes(app: FastAPI, context, *, run_in_thread):
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

    @app.get("/api/output-index/suggest")
    async def suggest(q: str = "", limit: int = Query(20, ge=1, le=500),
                      include: list[str] = Query(default=[]), exclude: list[str] = Query(default=[])):
        return await run_in_thread(service().suggest, q, limit, include, exclude)

    @app.get("/api/output-index/file")
    async def file(request: Request, row: int):
        if len(request.query_params.multi_items()) != 1:
            raise HTTPException(422, "Expected a row number only")
        path = await run_in_thread(service().file_path, row)
        if path is None:
            raise HTTPException(404, "Image not found")
        return FileResponse(path)

    @app.post("/api/output-index/decode")
    async def decode(request: Request):
        if not _is_local_request(request):
            return _forbidden()
        rid = (await object_body(request)).get("root_id")
        if type(rid) is not int:
            raise HTTPException(422, "Expected an integer root_id")
        await change(service().request_decode, rid)
        return {"ok": True}
