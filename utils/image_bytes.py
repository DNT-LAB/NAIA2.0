from __future__ import annotations

import io
from typing import Optional

from PIL import Image


def pil_image_from_png_bytes(png_bytes: bytes | None) -> Optional[Image.Image]:
    if not png_bytes:
        return None
    with Image.open(io.BytesIO(png_bytes)) as image:
        image.load()
        return image.copy()


def png_bytes_from_pil_image(image: Image.Image | None) -> bytes | None:
    if image is None:
        return None
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
