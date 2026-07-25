"""Interactive 모드 특징 썸네일 서빙.

팩은 ``data/interactive_thumbnails.json`` — {"<axis>/<tag>": "<base64 webp>"}.
tools/build_interactive_thumbnails.py 가 NAI 생성 PNG 로부터 만든다.
포맷 계열은 artist_thumbnail_*.json 과 동일하다(키 -> base64 이미지).

라우트:
    GET /api/interactive-thumb/index          팩에 들어 있는 키 목록(축별)
    GET /api/interactive-thumb?axis=&tag=     webp 바이트
"""

from __future__ import annotations

import base64
import json
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response

PACK_RELATIVE = Path("data") / "interactive_thumbnails.json"
_MEDIA = "image/webp"


class InteractiveThumbnailPack:
    """팩을 한 번 읽어 캐시한다. 파일 mtime 이 바뀌면 다시 읽는다(빌더 재실행 반영)."""

    def __init__(self, repo_root: Path):
        self._path = Path(repo_root) / PACK_RELATIVE
        self._lock = threading.Lock()
        self._data: dict[str, str] = {}
        self._mtime: float | None = None

    def _load_locked(self) -> None:
        try:
            stat = self._path.stat()
        except OSError:
            self._data = {}
            self._mtime = None
            return
        if self._mtime == stat.st_mtime:
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._data = raw if isinstance(raw, dict) else {}
        except Exception:
            self._data = {}
        self._mtime = stat.st_mtime

    def index(self) -> dict[str, list[str]]:
        with self._lock:
            self._load_locked()
            keys = list(self._data.keys())
        grouped: dict[str, list[str]] = {}
        for key in keys:
            axis, _, tag = str(key).partition("/")
            if axis and tag:
                grouped.setdefault(axis, []).append(tag)
        return grouped

    def image(self, axis: str, tag: str) -> bytes:
        key = f"{str(axis).strip()}/{str(tag).strip()}"
        with self._lock:
            self._load_locked()
            encoded = self._data.get(key)
        if not encoded:
            raise FileNotFoundError(key)
        text = str(encoded)
        if text.startswith("data:") and "," in text:
            text = text.split(",", 1)[1]
        return base64.b64decode(text)


def register_interactive_thumbnail_routes(app: FastAPI, context: Any) -> None:
    pack = InteractiveThumbnailPack(getattr(context, "repo_root", Path(".")))

    @app.get("/api/interactive-thumb/index")
    async def api_interactive_thumb_index():
        try:
            return {"axes": pack.index()}
        except Exception as exc:      # pragma: no cover - 방어적
            return JSONResponse({"error": f"thumb index failed: {exc}"}, status_code=500)

    @app.get("/api/interactive-thumb")
    async def api_interactive_thumb(axis: str = "", tag: str = ""):
        if not axis or not tag:
            return JSONResponse({"error": "axis and tag are required"}, status_code=400)
        try:
            blob = pack.image(axis, tag)
        except FileNotFoundError:
            return JSONResponse({"error": "not found"}, status_code=404)
        except Exception as exc:      # pragma: no cover - 방어적
            return JSONResponse({"error": f"thumb failed: {exc}"}, status_code=500)
        return Response(
            content=blob,
            media_type=_MEDIA,
            headers={"Cache-Control": "public, max-age=86400"},
        )
