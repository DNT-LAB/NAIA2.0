"""On-demand checks against the generation session's configured WebUI."""

import requests
from fastapi import HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from app.backend.server.install_manager_routes import _is_local_request
from core.api_service import APIService
from core.headless_generation_service import credential_for_mode
from core.webui_custom_payload import normalize_custom_payload
from core.webui_lora_service import OFFLINE, WebuiLoraService


class LoraFolder(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None


class LoraName(LoraFolder):
    name: str = Field(min_length=1)


class LoraThumbQuery(LoraName):
    v: int | None = None


class LoraHistoryThumb(LoraName):
    history_id: str = Field(min_length=1)


class LoraMeta(LoraName):
    favorite: StrictBool | None = None
    default_strength: float | None = Field(default=None, ge=-2, le=2, strict=True)


def _check_payload(context, text):
    result = normalize_custom_payload(text)
    scripts = result.pop("scripts")
    rows = result["scripts"] = [
        {"name": name, "args_count": len(script.get("args", [])), "webui": "unknown", "script_args_max": None}
        for name, script in scripts.items()
    ]
    if not result["ok"] or not rows:
        return result

    try:
        base = APIService._normalize_webui_url(credential_for_mode(context, "WEBUI"))
        response = requests.get(f"{base}/sdapi/v1/script-info", timeout=3)
        response.raise_for_status()
        entries = response.json()
        if not isinstance(entries, list):
            raise ValueError("Expected a script-info list")
        catalog = {}
        for entry in entries:
            name = entry["name"].casefold()
            # Forge lists both pipelines. Prefer txt2img when both describe a script.
            if name not in catalog or not entry.get("is_img2img"):
                catalog[name] = entry
    except (requests.RequestException, ValueError, TypeError, KeyError, AttributeError):
        result["issues"].append({"level": "warn", "script": None, "message": "WebUI 에 연결하지 못해 확인을 건너뜁니다."})
        return result

    for row in rows:
        entry = catalog.get(row["name"].casefold())
        if entry is None:
            row["webui"] = "missing"
            continue
        maximum = len(entry.get("args") or [])
        row["script_args_max"] = maximum
        if not entry.get("is_alwayson"):
            row["webui"] = "not_alwayson"
        elif row["args_count"] > maximum:
            row["webui"] = "too_many_args"
            result["issues"].append({"level": "warn", "script": row["name"],
                                     "message": f"WebUI가 받는 args {maximum}개를 초과했습니다."})
        else:
            row["webui"] = "present"
    return result


def register_webui_routes(app, context, *, run_in_thread):
    @app.post("/api/webui/custom-payload/check")
    async def check_custom_payload(body: dict):
        return await run_in_thread(_check_payload, context, body.get("text"))

    service = WebuiLoraService(context)

    async def call(action, *args):
        try:
            return await run_in_thread(action, *args)
        except requests.RequestException:
            return JSONResponse({"available": [], "warnings": [OFFLINE]}, status_code=503)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc))
        except OSError:
            raise HTTPException(500, "LoRA 파일 또는 폴더에 접근하지 못했습니다.")

    @app.get("/api/webui/loras")
    async def loras(refresh: bool = False):
        return await call(service.listing, refresh)

    @app.get("/api/webui/loras/thumb")
    async def lora_thumb(query: LoraThumbQuery = Query()):
        result = await call(service.thumbnail, query.name)
        if isinstance(result, Response):
            return result
        data, mime = result
        return Response(data, media_type=mime, headers={"Cache-Control": "no-store"})

    @app.delete("/api/webui/loras/thumb")
    async def delete_lora_thumb(query: LoraName = Query()):
        return await call(service.delete_thumb, query.name)

    @app.get("/api/webui/loras/history")
    async def lora_history(query: LoraName = Query()):
        return await call(service.history, query.name)

    @app.post("/api/webui/loras/thumb/history")
    async def save_history_thumb(body: LoraHistoryThumb):
        return await call(service.save_history_thumb, body.name, body.history_id)

    @app.put("/api/webui/loras/meta")
    async def lora_meta(body: LoraMeta):
        changes = body.model_dump(exclude={"name"}, exclude_none=True)
        if not changes:
            raise HTTPException(422, "즐겨찾기 또는 기본 강도를 지정해 주세요.")
        return await call(service.update_meta, body.name, changes)

    @app.post("/api/webui/loras/open-folder")
    async def open_lora_folder(request: Request, body: LoraFolder):
        return await call(service.open_folder, body.name, _is_local_request(request))
