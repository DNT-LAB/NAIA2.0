"""User-defined NovelAI model registry REST routes.

The backend deliberately does not guess a future model's wire identifier or
payload schema.  A user supplies the exact API model name and an explicit
compatibility profile; the shared registry then drives generation and NAI
feature gates.
"""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.nai_model_contract import DEFAULT_NAI_MODEL_KEY, normalize_nai_model_key
from core.nai_model_registry import NaiModelRegistry, NaiModelValidationError
from core.web_session_context import WebSessionContext


AsyncRunner = Callable[..., Awaitable[Any]]
JsonBroadcaster = Callable[[set[Any], dict[str, Any]], Awaitable[None]]
MAX_REQUEST_BYTES = 16 * 1024


async def _read_model_entry(request: Request) -> dict[str, Any]:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_REQUEST_BYTES:
        raise NaiModelValidationError("요청 본문이 너무 큽니다.")
    body = await request.body()
    if len(body) > MAX_REQUEST_BYTES:
        raise NaiModelValidationError("요청 본문이 너무 큽니다.")
    try:
        value = json.loads(body or b"{}")
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise NaiModelValidationError("유효한 JSON 객체가 필요합니다.") from exc
    if not isinstance(value, dict):
        raise NaiModelValidationError("모델 항목은 JSON 객체여야 합니다.")
    return value


def _reset_deleted_model_selection(context: WebSessionContext, model_key: str) -> bool:
    """Remove a deleted custom key from live, per-mode, and cached selection state."""

    deleted_key = normalize_nai_model_key(model_key)
    changed = False

    def _reset_mapping(mapping: Any) -> None:
        nonlocal changed
        if not isinstance(mapping, dict):
            return
        if normalize_nai_model_key(mapping.get("model")) == deleted_key:
            mapping["model"] = DEFAULT_NAI_MODEL_KEY
            changed = True

    _reset_mapping(getattr(context, "remote_params", None))

    planes = getattr(context, "remote_param_planes", None)
    if isinstance(planes, dict):
        _reset_mapping(planes.get("NAI"))

    option_cache = getattr(context, "remote_option_cache", None)
    if isinstance(option_cache, dict):
        nai_cache = option_cache.get("NAI")
        if isinstance(nai_cache, dict):
            selected = nai_cache.get("model")
            if (
                isinstance(selected, list)
                and selected
                and normalize_nai_model_key(selected[0]) == deleted_key
            ):
                nai_cache["model"] = [DEFAULT_NAI_MODEL_KEY]
                changed = True
            options = nai_cache.get("options_model")
            if isinstance(options, list):
                filtered = [
                    value
                    for value in options
                    if normalize_nai_model_key(value) != deleted_key
                ]
                if filtered != options:
                    nai_cache["options_model"] = filtered
                    changed = True

    if changed:
        context.save_remote_ui_state()
    return changed


def register_nai_model_routes(
    app: FastAPI,
    session_context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
    clients: set[Any],
    broadcast_json: JsonBroadcaster,
) -> None:
    def _service() -> NaiModelRegistry:
        return session_context._nai_model_registry()

    async def _broadcast_schema() -> None:
        await broadcast_json(
            clients,
            session_context.generation_param_schema_payload(),
        )

    @app.get("/api/nai-models")
    async def api_nai_models_list():
        try:
            return await run_in_thread(_service().state)
        except Exception as exc:
            return JSONResponse(
                {"ok": False, "error": f"NAI model list failed: {exc}"},
                status_code=500,
            )

    @app.post("/api/nai-models")
    async def api_nai_models_upsert(request: Request):
        try:
            entry = await _read_model_entry(request)
            model = await run_in_thread(_service().upsert, entry)
            state = await run_in_thread(_service().state)
            await _broadcast_schema()
            return {"ok": True, "model": model, "state": state}
        except NaiModelValidationError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse(
                {"ok": False, "error": f"NAI model save failed: {exc}"},
                status_code=500,
            )

    @app.delete("/api/nai-models/{model_key}")
    async def api_nai_models_delete(model_key: str):
        try:
            removed = await run_in_thread(_service().delete, model_key)
            selection_reset = await run_in_thread(
                _reset_deleted_model_selection,
                session_context,
                model_key,
            )
            state = await run_in_thread(_service().state)
            await _broadcast_schema()
            return {
                "ok": True,
                "removed": removed,
                "selection_reset": selection_reset,
                "state": state,
            }
        except NaiModelValidationError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        except KeyError:
            return JSONResponse(
                {"ok": False, "error": f"등록된 사용자 모델이 없습니다: {model_key}"},
                status_code=404,
            )
        except Exception as exc:
            return JSONResponse(
                {"ok": False, "error": f"NAI model delete failed: {exc}"},
                status_code=500,
            )
