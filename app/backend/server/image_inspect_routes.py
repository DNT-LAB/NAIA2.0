"""이미지 톤 인스펙터 라우트 - 히스토리 그림 한 장 · 두 장의 전후 비교 · 올린 그림 한 장.

재는 일은 전부 `core/image_tone_inspector.py` 가 한다. 여기는 그림을 찾아 넘기고 결과를 잠깐 들고 있을 뿐이다.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core import image_tone_inspector as tone
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
) -> None:
    @app.get("/api/inspect/tone/history/{history_id}")
    async def api_inspect_tone_history(history_id: str, spectrum: bool = False):
        try:
            return await run_in_thread(tone_inspect_service(session_context).history, history_id, spectrum)
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
