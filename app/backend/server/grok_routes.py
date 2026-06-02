"""Grok(xAI) 연동 — API 연동 페이지 백엔드 (제거 가능 모듈).

NAIA는 progrok(사용자가 직접 설치하는 xAI OAuth 브리지) 프록시 주소만 보관하고,
연결 확인 시 **로컬 프록시의 /v1/models 만** ping 한다. xAI(api.x.ai)에 직접 접속하지
않으며, 토큰도 NAIA가 보관하지 않는다(프록시가 서버측에서 실 토큰을 주입).

이 기능은 비공식 OAuth 클라이언트에 의존하므로 단기적으로만 동작할 수 있다 →
전체가 한 파일 + 한 줄 등록으로 격리되어 언제든 제거 가능하게 작성했다.

제거 방법: 이 파일 삭제 + headless_routes.py 의 import/`register_grok_routes(...)` 한 줄 삭제.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

import requests
from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse

DEFAULT_GROK_PROXY_URL = "http://127.0.0.1:18645"
_GROK_TEST_TIMEOUT = 6.0


def _grok_video_cache_dir() -> Path:
    """I2V 결과 mp4 임시 캐시 (모달 재생/저장용). user-data 격리."""
    user_data_dir = os.environ.get("NAIA_USER_DATA_DIR")
    base = Path(user_data_dir).expanduser().resolve() if user_data_dir else Path(".")
    path = base / "grok_video_cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def grok_video_cache_path(video_id: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_-]", "", str(video_id or ""))[:64]
    return _grok_video_cache_dir() / f"{safe}.mp4"


def save_grok_video_bytes(data: bytes) -> str:
    """mp4 바이트를 캐시에 저장하고 video_id 반환."""
    video_id = uuid.uuid4().hex
    grok_video_cache_path(video_id).write_bytes(data)
    return video_id


def _open_grok_videos_folder(context) -> dict[str, Any]:
    """자동저장된 영상 폴더(output/grok_videos) 를 OS 탐색기로 연다 (Windows)."""
    from app.backend.server.grok_i2v_commands import grok_videos_output_dir  # lazy: 순환 회피

    folder = grok_videos_output_dir(context)
    try:
        os.startfile(str(folder))  # type: ignore[attr-defined]
    except Exception as exc:
        return {"ok": False, "message": f"폴더 열기 실패: {exc}"}
    return {"ok": True, "path": str(folder)}


def _grok_config_path() -> Path:
    user_data_dir = os.environ.get("NAIA_USER_DATA_DIR")
    base = Path(user_data_dir).expanduser().resolve() / "save" if user_data_dir else Path("save")
    return base / "grok_connection.json"


def normalize_grok_proxy_url(value: str = "") -> str:
    """'127.0.0.1:18645' / '.../v1' / 끝 슬래시 등을 표준 base URL 로 정규화."""
    text = str(value or "").strip()
    if not text:
        return DEFAULT_GROK_PROXY_URL
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", text):
        text = "http://" + text
    if not re.match(r"^https?://", text, re.IGNORECASE):
        raise ValueError("http(s) 프록시 주소가 필요합니다")
    text = re.sub(r"/+$", "", text)
    text = re.sub(r"/v1$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"/+$", "", text)
    return text


def load_grok_config() -> dict[str, Any]:
    try:
        data = json.loads(_grok_config_path().read_text(encoding="utf-8"))
        url = normalize_grok_proxy_url(str(data.get("proxy_url") or ""))
        return {"proxy_url": url, "configured": bool(data.get("configured"))}
    except Exception:
        return {"proxy_url": DEFAULT_GROK_PROXY_URL, "configured": False}


def _save_grok_config(proxy_url: str) -> dict[str, Any]:
    url = normalize_grok_proxy_url(proxy_url)
    path = _grok_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"proxy_url": url, "configured": True}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _clear_grok_config() -> None:
    try:
        _grok_config_path().unlink()
    except FileNotFoundError:
        pass
    except Exception:
        pass


def _grok_auth_file() -> Path:
    # progrok 는 os.homedir()/.progrok/auth.json 에 OAuth 세션을 저장한다 (Windows: USERPROFILE).
    return Path.home() / ".progrok" / "auth.json"


def logout_grok() -> dict[str, Any]:
    """progrok logout 과 동일: ~/.progrok/auth.json 삭제(저장된 xAI 자격증명 제거).
    이후 프록시를 재기동하면 '로그인 필요' 상태가 되어 다른 계정으로 로그인할 수 있다."""
    path = _grok_auth_file()
    existed = path.exists()
    try:
        path.unlink()
    except FileNotFoundError:
        existed = False
    except Exception as exc:
        return {"ok": False, "message": f"로그아웃 실패: {exc}"}
    return {"ok": True, "existed": existed}


def probe_grok_proxy(proxy_url: str) -> dict[str, Any]:
    """로컬 progrok 프록시의 /v1/models 를 ping. 상태 코드로 상황을 구분:
      - 연결 거부/타임아웃 → 프록시 미실행
      - 200 → 연결됨(로그인됨 + 계정 접근 가능)
      - 401 → `progrok login` 필요
      - 403 → 권한 없음(SuperGrok Heavy 티어 필요 가능)
    xAI 에 직접 접속하지 않고 localhost 만 호출한다."""
    try:
        url = normalize_grok_proxy_url(proxy_url)
    except ValueError as exc:
        return {"ok": False, "status": "invalid", "message": str(exc)}
    try:
        resp = requests.get(
            f"{url}/v1/models",
            headers={"Authorization": "Bearer dummy", "Accept": "application/json"},
            timeout=_GROK_TEST_TIMEOUT,
        )
    except requests.exceptions.ConnectionError:
        return {"ok": False, "status": "offline",
                "message": "progrok 프록시에 연결할 수 없습니다. 터미널에서 `progrok proxy` 가 실행 중인지 확인하세요."}
    except requests.exceptions.Timeout:
        return {"ok": False, "status": "timeout",
                "message": "프록시 응답 시간 초과. progrok/네트워크 상태를 확인하세요."}
    except Exception as exc:
        return {"ok": False, "status": "error", "message": f"연결 확인 실패: {exc}"}

    if resp.status_code == 200:
        models: list[str] = []
        try:
            data = resp.json()
            items = data.get("data") if isinstance(data, dict) else None
            if isinstance(items, list):
                models = [str(m.get("id")) for m in items if isinstance(m, dict) and m.get("id")]
        except Exception:
            models = []
        has_image = any("imagine-image" in m for m in models)
        msg = f"연결됨 — 모델 {len(models)}개" + ("" if has_image else " (이미지 모델 미확인)")
        return {"ok": True, "status": "ok", "message": msg, "models": models, "has_image_model": has_image}
    if resp.status_code == 401:
        return {"ok": False, "status": "unauthorized",
                "message": "로그인이 필요합니다 — 터미널에서 `progrok login` 을 실행하세요."}
    if resp.status_code == 403:
        return {"ok": False, "status": "forbidden",
                "message": "권한 없음 — 이 계정/구독에 Grok 이미지 권한이 없을 수 있습니다 (SuperGrok Heavy 티어 필요 가능)."}
    return {"ok": False, "status": "http_error", "message": f"프록시 응답 오류 (HTTP {resp.status_code})."}


async def _safe_json(req: Request) -> dict[str, Any]:
    try:
        data = await req.json()
    except Exception:
        data = {}
    return data if isinstance(data, dict) else {}


def register_grok_routes(app, context=None, *, run_in_thread) -> None:
    """Grok 연동 라우트 등록 (context 는 시그니처 일관성용, 현재 미사용)."""

    @app.get("/api/grok/config")
    async def api_grok_config_get():  # noqa: ANN202
        return load_grok_config()

    @app.post("/api/grok/config")
    async def api_grok_config_set(req: Request):  # noqa: ANN202
        payload = await _safe_json(req)
        try:
            return await run_in_thread(_save_grok_config, str(payload.get("proxy_url") or ""))
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.post("/api/grok/test")
    async def api_grok_test(req: Request):  # noqa: ANN202
        payload = await _safe_json(req)
        raw = str(payload.get("proxy_url") or "").strip()
        proxy_url = raw or load_grok_config()["proxy_url"]
        return await run_in_thread(probe_grok_proxy, proxy_url)

    @app.post("/api/grok/clear")
    async def api_grok_clear():  # noqa: ANN202
        await run_in_thread(_clear_grok_config)
        return {"ok": True}

    @app.post("/api/grok/logout")
    async def api_grok_logout():  # noqa: ANN202
        return await run_in_thread(logout_grok)

    @app.get("/api/grok/video/{video_id}")
    async def api_grok_video_get(video_id: str, download: int = 0):  # noqa: ANN202
        path = grok_video_cache_path(video_id)
        if not path.is_file():
            return JSONResponse({"error": "video not found"}, status_code=404)
        headers = {"Content-Disposition": f'attachment; filename="grok_{video_id}.mp4"'} if download else None
        return FileResponse(str(path), media_type="video/mp4", headers=headers)

    @app.post("/api/grok/videos/open")
    async def api_grok_videos_open():  # noqa: ANN202
        return await run_in_thread(_open_grok_videos_folder, context)
