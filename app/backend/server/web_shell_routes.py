from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles


def _no_cache_headers() -> dict[str, str]:
    return {"Cache-Control": "no-store, max-age=0"}


def _web_file(path: Path, media_type: str):
    if not path.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(str(path), media_type=media_type, headers=_no_cache_headers())


# 이 모듈의 `_web_file` 은 **확장이 몽키패치하는 자리**다(공식 프론트 확장 경로가
# 없어서 서드파티가 여기를 감싸 서빙되는 JS 뒤에 자기 코드를 덧붙인다).
# 원본을 기억해 두면 '지금 프론트가 확장에 의해 바뀌어 있는가' 를 정직하게 답할 수
# 있다 - 되돌릴 수는 없지만(남의 패치다), **사용자에게 새로고침이 필요하다고
# 알려 줄 수는 있다**(확장을 꺼도 이미 받아 간 페이지에는 그 코드가 살아 있다).
_ORIGINAL_WEB_FILE = _web_file


def web_frontend_is_patched() -> bool:
    """확장이 프론트 서빙을 가로채고 있는가."""
    return _web_file is not _ORIGINAL_WEB_FILE


def _web_asset(root: Path, asset_path: str, *, default_media_type: str = "application/octet-stream"):
    try:
        target = (root / asset_path).resolve()
        root_resolved = root.resolve()
        if not target.is_relative_to(root_resolved):
            return JSONResponse({"error": "not found"}, status_code=404)
    except Exception:
        return JSONResponse({"error": "not found"}, status_code=404)
    if not target.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    media_type = mimetypes.guess_type(str(target))[0] or default_media_type
    if target.suffix.lower() in {".js", ".mjs"}:
        media_type = "text/javascript"
    return FileResponse(str(target), media_type=media_type, headers=_no_cache_headers())


def register_web_shell_routes(app: FastAPI, root_web_dir: Path) -> None:
    mimetypes.add_type("text/javascript", ".mjs")

    js_dir = root_web_dir / "js"
    guides_dir = root_web_dir / "guides"
    if guides_dir.exists():
        app.mount("/guides", StaticFiles(directory=str(guides_dir), html=True), name="remote_guides")

    @app.get("/")
    async def index():
        return _web_file(root_web_dir / "index.html", "text/html")

    @app.get("/bootstrap.html")
    async def bootstrap_migration_page():
        # Standalone first-run migration screen loaded by the Electron shell when
        # the user picks "import from previous NAIA2.0", so migration happens in
        # a focused view before the full app launches.
        return _web_file(root_web_dir / "bootstrap.html", "text/html")

    @app.get("/style.css")
    async def serve_css():
        return _web_file(root_web_dir / "style.css", "text/css")

    @app.get("/app.js")
    async def serve_js():
        return _web_file(root_web_dir / "app.js", "application/javascript")

    @app.get("/js/{asset_path:path}")
    async def serve_js_asset(asset_path: str):
        return _web_asset(js_dir, asset_path, default_media_type="text/javascript")
