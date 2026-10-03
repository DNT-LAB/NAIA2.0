"""이미지 톤 인스펙터 라우트 - 히스토리 그림 한 장 · 두 장의 전후 비교 · 올린 그림 한 장.

재는 일은 전부 `core/image_tone_inspector.py` 가 한다. 여기는 그림을 찾아 넘기고 결과를 잠깐 들고 있을 뿐이다.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core import image_tone_inspector as tone
from core.image_tone_reference import REFERENCE, axis_positions
from core.image_tone_advisor import advise, apply_suggestions, guide, normalize_fields
from core.web_session_context import WebSessionContext


AsyncRunner = Callable[..., Awaitable[Any]]

MAX_UPLOAD_BYTES = 48 * 1024 * 1024
CACHE_SIZE = 64


class ToneInspectService:
    """히스토리 그림의 측정을 들고 있는다. 히스토리 항목은 한 번 만들어지면 안 바뀌므로 id 로 기억해도 된다."""

    def __init__(self, context: WebSessionContext):
        self.context = context
        self._cache: OrderedDict[tuple[str, bool], dict[str, Any]] = OrderedDict()

    def _image_bytes(self, history_id: str) -> bytes:
        image_bytes, _media_type = self.context.result_store.history_image_payload(history_id)
        return image_bytes

    def history(self, history_id: str, spectrum: bool = False) -> dict[str, Any]:
        key = (str(history_id), bool(spectrum))
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached
        result = tone.inspect_image(self._image_bytes(history_id), spectrum=spectrum)
        result["history_id"] = str(history_id)
        self._cache[key] = result
        while len(self._cache) > CACHE_SIZE:
            self._cache.popitem(last=False)
        return result

    def history_with_axes(self, history_id: str, spectrum: bool = False) -> dict[str, Any]:
        result = self.history(history_id, spectrum)
        # Add only to this response; cached compare/image output stays compatible.
        return {**result, "axes": axis_positions(result),
                "reference": {key: REFERENCE[key] for key in ("schema", "sample", "images", "built_at")},
                # 화면이 '이 그림이 내가 청한 시험 생성의 결과인가' 를 가린다.
                "generation_request_id": self._generation_request_id(history_id)}

    def _generation_request_id(self, history_id: str) -> str:
        getter = getattr(self.context.result_store, "get_item", None)
        item = getter(history_id) if callable(getter) else None
        params = getattr(item, "generation_params", None)
        return str(params.get("generation_request_id") or "") if isinstance(params, dict) else ""

    def advice(self, history_id: str, fields: dict[str, str] | None) -> dict[str, Any]:
        result = self.history(history_id)
        if fields is None:
            metadata = self.context.result_store.history_meta_payload(history_id)
            fields = {"prompt": metadata.get("prompt", ""), "negative_prompt": metadata.get("negative", "")}
        axes = axis_positions(result)
        return {"history_id": history_id, "axes": axes, **advise(axes, fields), "guide": guide()}

    def prepare_trial(self, history_id: str, items: list[dict[str, Any]], allow_paid: bool) -> dict[str, Any]:
        """같은 그림을 **같은 시드 · 같은 설정**으로, 보정만 얹어 다시 뽑을 요청을 만든다.

        사용자의 프롬프트 칸 · 프리셋은 건드리지 않는다 - 고치는 것은 그 그림이 실제로 생성된 프롬프트의 사본이다.
        """
        from app.backend.server.result_display_routes import _history_item_replay_params
        from core.nai_anlas_cost import estimate_anlas_cost

        getter = getattr(self.context.result_store, "get_item", None)
        item = getter(history_id) if callable(getter) else None
        if item is None:
            raise FileNotFoundError("History item not found")
        params = _history_item_replay_params(item)
        prompt = str(params.get("input") or params.get("_raw_input") or "")
        if not prompt.strip():
            raise ValueError("이 그림에는 생성 정보가 없어 시험 생성을 할 수 없습니다")
        try:
            seed = int(params.get("seed"))
        except (TypeError, ValueError):
            seed = -1
        if seed < 0:
            raise ValueError("이 그림의 시드를 알 수 없어 시험 생성을 할 수 없습니다")
        applied = apply_suggestions(
            {"prompt": prompt, "negative_prompt": str(params.get("negative_prompt") or "")}, items)
        if not applied["changes"]:
            raise ValueError("이 보정은 그 그림의 프롬프트에 이미 들어 있습니다")
        params.update({
            "input": applied["fields"]["prompt"], "_raw_input": applied["fields"]["prompt"],
            "negative_prompt": applied["fields"]["negative_prompt"],
            "seed": seed, "seed_fixed": True,
            "_remote_queue_source": "Inspector Trial", "_remote_queue_label": "Inspector · " + ", ".join(str(item.get("suggestion_id")) for item in items),
        })
        cost = estimate_anlas_cost(self.context, params)
        if cost > 0 and not allow_paid:
            return {"ok": False, "needs_confirmation": True, "anlas_cost": cost}
        return {"ok": True, "params": params, "seed": seed, "anlas_cost": cost,
                "fields": applied["fields"], "changes": applied["changes"]}

    def compare(self, before_id: str, after_id: str) -> dict[str, Any]:
        before, after = self.history(before_id), self.history(after_id)
        return {
            "before": before,
            "after": after,
            "delta": tone.compare_inspections(before, after),
            # 크기가 같을 때만 - 같은 시드 · 같은 프롬프트의 전후 비교용.
            "pixel_delta": tone.pixel_delta(self._image_bytes(before_id), self._image_bytes(after_id)),
        }


def tone_inspect_service(context: WebSessionContext) -> ToneInspectService:
    service = getattr(context, "tone_inspect_service", None)
    if service is None:
        service = ToneInspectService(context)
        context.tone_inspect_service = service
    return service


def register_image_inspect_routes(
    app: FastAPI,
    session_context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
    clients: Any = None,
    broadcast_json: Callable[..., Awaitable[Any]] | None = None,
) -> None:
    @app.get("/api/inspect/tone/history/{history_id}")
    async def api_inspect_tone_history(history_id: str, spectrum: str = "false"):
        value = spectrum.lower()
        if value not in ("true", "t", "1", "yes", "y", "on", "false", "f", "0", "no", "n", "off"):
            return JSONResponse({"error": "spectrum must be a boolean"}, status_code=400)
        try:
            return await run_in_thread(tone_inspect_service(session_context).history_with_axes, history_id,
                                       value in ("true", "t", "1", "yes", "y", "on"))
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Tone inspect failed: {exc}"}, status_code=500)

    @app.get("/api/inspect/tone/compare")
    async def api_inspect_tone_compare(before: str = "", after: str = ""):
        if not before or not after:
            return JSONResponse({"error": "before and after history ids are required"}, status_code=400)
        try:
            return await run_in_thread(tone_inspect_service(session_context).compare, before, after)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Tone compare failed: {exc}"}, status_code=500)

    @app.post("/api/inspect/tone/image")
    async def api_inspect_tone_image(request: Request, spectrum: bool = False):
        body = await request.body()
        if not body:
            return JSONResponse({"error": "image body is empty"}, status_code=400)
        if len(body) > MAX_UPLOAD_BYTES:
            return JSONResponse({"error": "image is too large"}, status_code=413)
        try:
            return await run_in_thread(tone.inspect_image, body, tone.MAX_SIDE, spectrum)
        except Exception as exc:
            return JSONResponse({"error": f"Not a readable image: {exc}"}, status_code=400)


    @app.post("/api/inspect/tone/advise")
    async def api_inspect_tone_advise(request: Request):
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("Request body must be an object")
            history_id = body.get("history_id")
            if not isinstance(history_id, str) or not history_id.strip():
                raise ValueError("history_id must be a nonempty string")
            fields = body.get("fields")
            if "fields" in body:
                normalize_fields(fields)
        except (ValueError, TypeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        try:
            return await run_in_thread(tone_inspect_service(session_context).advice, history_id, fields)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"Tone advise failed: {exc}"}, status_code=500)

    @app.post("/api/inspect/tone/apply")
    async def api_inspect_tone_apply(request: Request):
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("Request body must be an object")
            fields = body.get("fields", {})
            normalize_fields(fields)
            return apply_suggestions(fields, _items(body))
        except (ValueError, TypeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.post("/api/inspect/tone/trial")
    async def api_inspect_tone_trial(request: Request):
        """보정을 얹어 **같은 시드로 한 장** 시험 생성한다. 사용자의 프롬프트 · 프리셋은 그대로다."""
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("Request body must be an object")
            history_id = body.get("history_id")
            if not isinstance(history_id, str) or not history_id.strip():
                raise ValueError("history_id must be a nonempty string")
            items = _items(body)
        except (ValueError, TypeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        try:
            prepared = await run_in_thread(tone_inspect_service(session_context).prepare_trial,
                                           history_id, items, body.get("allow_paid") is True)
        except FileNotFoundError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except (ValueError, TypeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        if not prepared["ok"]:
            # 유료(Anlas)면 묻고 다시 보내게 한다 - 여기서 조용히 쓰지 않는다.
            return JSONResponse(prepared, status_code=409)
        from app.backend.server.generation_commands import generation_service

        params = prepared.pop("params")
        command = {"type": "generate", "prompt": params["input"], "negative_prompt": params["negative_prompt"],
                   "overrides": params, "priority": 100}
        dispatch = await run_in_thread(generation_service(session_context).enqueue_remote_request, command)
        if not dispatch.ok:
            return JSONResponse({"ok": False, "error": dispatch.blocked_reason}, status_code=400)
        if broadcast_json is not None and clients is not None:
            await broadcast_json(clients, dispatch.websocket_payload())
            await broadcast_json(clients, session_context.queue_state_payload())
        return {**prepared, "generation_request_id": dispatch.request_id}


def _items(body: dict[str, Any]) -> list[dict[str, Any]]:
    """보정 목록. `items` 가 있으면 그것을, 없으면 한 건짜리 옛 모양(suggestion_id · level · strength)을 받는다."""
    if "items" in body:
        return body["items"]
    if not isinstance(body.get("suggestion_id"), str):
        raise ValueError("suggestion_id must be a string")
    return [{"suggestion_id": body["suggestion_id"], "level": body.get("level"), "strength": body.get("strength", 1.0)}]
