"""Small image helpers shared by headless Remote Web feature services."""

from __future__ import annotations

import base64
import hashlib
import io


def image_hash(image_bytes: bytes) -> str:
    return hashlib.sha256(image_bytes).hexdigest()[:16]


def data_url_payload(value: str) -> str:
    text = str(value or "").strip()
    if "," in text and text.lower().startswith("data:"):
        return text.split(",", 1)[1]
    return text


def image_to_png_bytes(image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()


def thumbnail_b64(image, max_side: int = 128) -> str:
    from PIL import Image

    thumb = image.copy()
    thumb.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    if thumb.mode == "RGBA":
        thumb = thumb.convert("RGB")
    buffer = io.BytesIO()
    thumb.save(buffer, format="JPEG", quality=70)
    return base64.b64encode(buffer.getvalue()).decode("ascii")
