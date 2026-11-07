"""가이드 편집기(개발 전용) - /guides 뷰어의 [편집] 이 부르는 쓰기 라우트.

**저장소 사본에서만 켜진다.** 백엔드 루트에 `.git` 이 있을 때만 라우트를 등록한다. 포터블 ·
릴리즈 사본(resources/naia-backend)에는 `.git` 이 없으므로 라우트 자체가 없다 - 프론트는
`/api/guide-editor/status` 가 404 면 [편집] 단추를 만들지 않는다.
켜져 있어도 로컬 PC 요청만 받는다(클라이언트 · Host 둘 다 루프백 - cloudflared 터널은 Host 로 걸러진다).

쓰는 곳은 `app/web/remote/guides/` 하나뿐이다:
- `catalog.json`  : 목차(분류 · 순서 · 제목 · 요약)
- `<id>.html`     : 문서 본문 - `<main class="page">` 안쪽만 바꾸고 머리(원래 스타일)는 그대로 둔다
- `assets/`       : Ctrl+V 로 붙여넣은 그림 - 긴 변 1600px · WebP 로 다시 인코딩한다(메타데이터 제거)
"""
from __future__ import annotations

import io
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.headless_payload_utils import is_loopback_host

DOC_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
RESERVED_IDS = {"welcome", "index", "catalog", "assets"}
MAX_IMAGE_BYTES = 40 * 1024 * 1024
MAX_HTML_CHARS = 2_000_000
MAX_SIDE = 1600
LOSSY_QUALITY = 88
# 무손실이 손실보다 이만큼까지 크면 무손실을 쓴다(화면 캡처의 글자가 선명한 쪽).
LOSSLESS_TOLERANCE = 1.25
PAGE_MAIN_RE = re.compile(r'(<main class="page"[^>]*>)(.*)(</main>)', re.S)
FORBIDDEN_HTML_RE = re.compile(r"<\s*script|javascript:|<\s*/\s*main", re.I)

NEW_DOC_TEMPLATE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="document.css?v=4">
<style>html {{ overflow: auto; }} .page {{ max-width: 708px; margin: 0 auto; padding: 48px 24px 64px; }}</style>
</head>
<body>
<main class="page">
<p>여기에 내용을 씁니다.</p>
</main>
</body>
</html>
"""


def guide_editor_enabled(root_web_dir: Path) -> bool:
    """저장소 사본에서 도는가 - 백엔드 루트(app/web/remote 의 세 단계 위)에 `.git` 이 있다."""
    try:
        return (Path(root_web_dir).resolve().parents[2] / ".git").exists()
    except (OSError, IndexError):
        return False


def _request_host(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw.startswith("[") and "]" in raw:
        return raw[1:raw.index("]")]
    if raw.count(":") == 1:
        return raw.rsplit(":", 1)[0]
    return raw


def _is_local_request(req: Request) -> bool:
    client_host = ""
    try:
        if req.client is not None:
            client_host = _request_host(str(req.client.host or ""))
    except Exception:
        client_host = ""
    request_host = _request_host(req.headers.get("host") or getattr(req.url, "hostname", "") or "")
    if client_host == "testclient":
        return request_host in {"", "testserver"} or is_loopback_host(request_host)
    return is_loopback_host(client_host) and is_loopback_host(request_host)


def _fail(message: str, status: int = 400, code: str = "BAD_REQUEST") -> JSONResponse:
    return JSONResponse({"ok": False, "code": code, "error": message}, status_code=status)


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def compress_guide_image(data: bytes) -> tuple[bytes, dict[str, Any]]:
    """붙여넣은 그림을 가이드용 WebP 로 바꾼다.

    - 긴 변이 MAX_SIDE 를 넘으면 줄인다.
    - 투명도가 사실상 없으면(최소 알파 250 이상 - NAI 그림의 숨은 메타데이터 자리) 알파를 버린다.
    - 무손실 · 손실 둘 다 만들어 무손실이 LOSSLESS_TOLERANCE 배 이하면 무손실(캡처), 아니면 손실(일러스트).
    - PNG 글자 청크 · EXIF 는 옮기지 않는다(프롬프트가 저장소로 새지 않게).
    """
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(data)) as src:
        src.load()
        image = ImageOps.exif_transpose(src)
        if image.mode == "P" and "transparency" in image.info:
            image = image.convert("RGBA")
        if image.mode in ("RGBA", "LA"):
            image = image.convert("RGBA")
            if image.getchannel("A").getextrema()[0] >= 250:
                image = image.convert("RGB")
        elif image.mode != "RGB":
            image = image.convert("RGB")
        original_size = image.size
        if max(image.size) > MAX_SIDE:
            image.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
        lossless = io.BytesIO()
        image.save(lossless, "WEBP", lossless=True, quality=80, method=4)
        lossy = io.BytesIO()
        image.save(lossy, "WEBP", quality=LOSSY_QUALITY, method=6)
    use_lossless = lossless.tell() <= lossy.tell() * LOSSLESS_TOLERANCE
    out = (lossless if use_lossless else lossy).getvalue()
    return out, {
        "mode": "lossless" if use_lossless else "lossy",
        "width": image.size[0],
        "height": image.size[1],
        "original_width": original_size[0],
        "original_height": original_size[1],
        "bytes_in": len(data),
        "bytes_out": len(out),
    }


def replace_page_body(document: str, body: str) -> str:
    match = PAGE_MAIN_RE.search(document)
    if match is None:
        raise ValueError('문서에 <main class="page"> 가 없습니다.')
    return document[:match.end(1)] + "\n" + body.strip() + "\n" + document[match.start(3):]


def _clean_text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def validate_catalog(payload: Any, guides_dir: Path) -> dict[str, Any]:
    pages = payload.get("pages") if isinstance(payload, dict) else None
    if not isinstance(pages, list) or not pages or len(pages) > 200:
        raise ValueError("pages 는 1~200개 목록이어야 합니다.")
    seen: set[str] = set()
    clean: list[dict[str, str]] = []
    for page in pages:
        if not isinstance(page, dict):
            raise ValueError("목차 항목이 객체가 아닙니다.")
        doc_id = str(page.get("id") or "")
        if not DOC_ID_RE.match(doc_id) or doc_id in RESERVED_IDS:
            raise ValueError(f"문서 이름이 올바르지 않습니다: {doc_id!r}")
        if doc_id in seen:
            raise ValueError(f"문서 이름이 겹칩니다: {doc_id}")
        seen.add(doc_id)
        if not (guides_dir / f"{doc_id}.html").is_file():
            raise ValueError(f"문서 파일이 없습니다: {doc_id}.html")
        title = _clean_text(page.get("title"), 80)
        category = _clean_text(page.get("category"), 40)
        if not title or not category:
            raise ValueError(f"제목과 분류는 비울 수 없습니다: {doc_id}")
        clean.append({
            "id": doc_id,
            "category": category,
            "title": title,
            "summary": _clean_text(page.get("summary"), 300),
            "keywords": _clean_text(page.get("keywords"), 200),
            "file": f"{doc_id}.html",
        })
    return {"version": 1, "pages": clean}


def _catalog_bytes(catalog: dict[str, Any]) -> bytes:
    return (json.dumps(catalog, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _read_catalog(guides_dir: Path) -> dict[str, Any]:
    return json.loads((guides_dir / "catalog.json").read_text(encoding="utf-8"))


def register_guide_editor_routes(app: FastAPI, root_web_dir: Path) -> None:
    if not guide_editor_enabled(root_web_dir):
        return
    guides_dir = Path(root_web_dir) / "guides"
    assets_dir = guides_dir / "assets"

    @app.get("/api/guide-editor/status")
    async def guide_editor_status(request: Request):
        if not _is_local_request(request):
            return _fail("가이드 편집은 로컬 PC 에서만 됩니다.", 403, "LOCAL_ONLY")
        return {"ok": True, "enabled": True, "max_side": MAX_SIDE}

    @app.post("/api/guide-editor/assets")
    async def guide_editor_upload_asset(request: Request):
        if not _is_local_request(request):
            return _fail("가이드 편집은 로컬 PC 에서만 됩니다.", 403, "LOCAL_ONLY")
        doc_id = str(request.query_params.get("doc") or "")
        if not DOC_ID_RE.match(doc_id):
            return _fail("문서 이름이 올바르지 않습니다.")
        data = await request.body()
        if not data:
            return _fail("그림이 비어 있습니다.")
        if len(data) > MAX_IMAGE_BYTES:
            return _fail("그림이 너무 큽니다(40MB 초과).", 413, "TOO_LARGE")
        try:
            encoded, info = compress_guide_image(data)
        except Exception as exc:
            return _fail(f"그림을 읽지 못했습니다: {exc}")
        assets_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        name = f"{doc_id}-{stamp}.webp"
        counter = 2
        while (assets_dir / name).exists():
            name = f"{doc_id}-{stamp}-{counter}.webp"
            counter += 1
        _write_atomic(assets_dir / name, encoded)
        return {"ok": True, "path": f"assets/{name}", **info}

    @app.put("/api/guide-editor/docs/{doc_id}")
    async def guide_editor_save_doc(doc_id: str, request: Request):
        if not _is_local_request(request):
            return _fail("가이드 편집은 로컬 PC 에서만 됩니다.", 403, "LOCAL_ONLY")
        if not DOC_ID_RE.match(doc_id):
            return _fail("문서 이름이 올바르지 않습니다.")
        target = guides_dir / f"{doc_id}.html"
        if not target.is_file():
            return _fail("문서가 없습니다.", 404, "NOT_FOUND")
        try:
            payload = await request.json()
        except Exception:
            return _fail("JSON 이 아닙니다.")
        body = payload.get("html") if isinstance(payload, dict) else None
        if not isinstance(body, str) or not body.strip() or len(body) > MAX_HTML_CHARS:
            return _fail("본문이 비었거나 너무 큽니다.")
        if FORBIDDEN_HTML_RE.search(body):
            return _fail("본문에 script · javascript: · </main> 를 넣을 수 없습니다.")
        try:
            updated = replace_page_body(target.read_text(encoding="utf-8"), body)
        except ValueError as exc:
            return _fail(str(exc))
        _write_atomic(target, updated.encode("utf-8"))
        return {"ok": True, "id": doc_id, "bytes": len(updated.encode("utf-8"))}

    @app.post("/api/guide-editor/docs")
    async def guide_editor_create_doc(request: Request):
        if not _is_local_request(request):
            return _fail("가이드 편집은 로컬 PC 에서만 됩니다.", 403, "LOCAL_ONLY")
        try:
            payload = await request.json()
        except Exception:
            return _fail("JSON 이 아닙니다.")
        if not isinstance(payload, dict):
            return _fail("JSON 객체가 아닙니다.")
        doc_id = str(payload.get("id") or "")
        if not DOC_ID_RE.match(doc_id) or doc_id in RESERVED_IDS:
            return _fail("문서 이름은 영문 소문자 · 숫자 · - 만 씁니다(예: wildcard-basics).")
        target = guides_dir / f"{doc_id}.html"
        if target.exists():
            return _fail("같은 이름의 문서가 이미 있습니다.", 409, "EXISTS")
        title = _clean_text(payload.get("title"), 80)
        category = _clean_text(payload.get("category"), 40)
        if not title or not category:
            return _fail("제목과 분류를 적어 주세요.")
        catalog = _read_catalog(guides_dir)
        catalog["pages"].append({
            "id": doc_id, "category": category, "title": title,
            "summary": _clean_text(payload.get("summary"), 300), "keywords": "", "file": f"{doc_id}.html",
        })
        html_title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        _write_atomic(target, NEW_DOC_TEMPLATE.format(title=html_title).encode("utf-8"))
        try:
            clean = validate_catalog(catalog, guides_dir)
        except ValueError as exc:
            target.unlink(missing_ok=True)
            return _fail(str(exc))
        _write_atomic(guides_dir / "catalog.json", _catalog_bytes(clean))
        return {"ok": True, "id": doc_id, "catalog": clean}

    @app.put("/api/guide-editor/catalog")
    async def guide_editor_save_catalog(request: Request):
        if not _is_local_request(request):
            return _fail("가이드 편집은 로컬 PC 에서만 됩니다.", 403, "LOCAL_ONLY")
        try:
            payload = await request.json()
            clean = validate_catalog(payload, guides_dir)
        except ValueError as exc:
            return _fail(str(exc))
        except Exception:
            return _fail("JSON 이 아닙니다.")
        _write_atomic(guides_dir / "catalog.json", _catalog_bytes(clean))
        return {"ok": True, "catalog": clean}
