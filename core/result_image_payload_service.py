"""Pure image payload helpers for Remote Web result endpoints."""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def result_png_filename(source_name: str = "") -> str:
    raw_name = Path(str(source_name or "")).name
    raw_name = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", raw_name).strip()
    stem = Path(raw_name).stem if raw_name else ""
    return f"{stem or 'naia-result'}.png"


def download_content_disposition(filename: str) -> str:
    ascii_name = re.sub(r"[^A-Za-z0-9._ -]+", "_", filename).strip(" ._")
    ascii_name = ascii_name or "naia-result.png"
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(filename)}'


def image_media_type_for_path(image_path: str | Path) -> str:
    ext = Path(image_path).suffix.lower()
    return {
        ".webp": "image/webp",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
    }.get(ext, "image/png")


def _coerce_bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, memoryview):
        return value.tobytes()
    return b""


def image_media_type_for_bytes(image_bytes: bytes | bytearray | memoryview) -> str:
    image_bytes = _coerce_bytes(image_bytes)
    if image_bytes.startswith(PNG_SIGNATURE):
        return "image/png"
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_bytes.startswith(b"RIFF") and len(image_bytes) >= 12 and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    if image_bytes.startswith(b"GIF87a") or image_bytes.startswith(b"GIF89a"):
        return "image/gif"
    return "application/octet-stream"


def is_png_bytes(image_bytes: bytes | bytearray | memoryview) -> bool:
    image_bytes = _coerce_bytes(image_bytes)
    if not image_bytes or not image_bytes.startswith(PNG_SIGNATURE):
        return False
    try:
        from PIL import Image

        with Image.open(io.BytesIO(image_bytes)) as opened:
            return (opened.format or "").upper() == "PNG"
    except Exception:
        return False


def pil_image_to_png_bytes(image) -> bytes:
    from utils.comfyui_png_metadata import build_pnginfo, image_to_png_bytes

    pnginfo = build_pnginfo(dict(getattr(image, "info", {}) or {}))
    return image_to_png_bytes(image, pnginfo=pnginfo)


def image_file_to_png_payload(image_path: str | Path) -> tuple[bytes, str]:
    from PIL import Image

    target = Path(image_path)
    if target.suffix.lower() == ".png":
        return target.read_bytes(), result_png_filename(target.name)
    with Image.open(str(target)) as opened:
        opened.load()
        image = opened.convert("RGBA").copy()
    return pil_image_to_png_bytes(image), result_png_filename(target.name)


def image_bytes_to_png_payload(
    image_bytes: bytes | bytearray | memoryview,
    filename: str = "naia-result.png",
) -> tuple[bytes, str]:
    from PIL import Image

    image_bytes = _coerce_bytes(image_bytes)
    with Image.open(io.BytesIO(image_bytes)) as opened:
        opened.load()
        image = opened.convert("RGBA").copy()
    return pil_image_to_png_bytes(image), result_png_filename(filename)


def history_item_png_payload(item, label: str = "") -> tuple[bytes, str]:
    filepath = str(getattr(item, "filepath", "") or "")
    label = str(label or filepath or "naia-result.png")

    raw_bytes = _coerce_bytes(getattr(item, "raw_bytes", None))
    if raw_bytes and is_png_bytes(raw_bytes):
        return raw_bytes, result_png_filename(label)

    if filepath:
        path = Path(filepath)
        if path.is_file() and path.suffix.lower() == ".png":
            return path.read_bytes(), result_png_filename(filepath)

    image = getattr(item, "image", None)
    if image is None:
        raise FileNotFoundError("History image is unavailable")
    return pil_image_to_png_bytes(image), result_png_filename(label)


def history_item_image_payload(item) -> tuple[bytes, str]:
    raw_bytes = _coerce_bytes(getattr(item, "raw_bytes", None))
    if raw_bytes:
        return raw_bytes, image_media_type_for_bytes(raw_bytes)

    image = getattr(item, "image", None)
    if image is None:
        raise FileNotFoundError("History image is unavailable")
    return pil_image_to_png_bytes(image), "image/png"


def memory_history_thumbnail_payload(
    item,
    max_side: int = 0,
    on_error: Callable[[Exception], None] | None = None,
) -> bytes:
    image = getattr(item, "image", None)
    if image is None:
        return b""
    try:
        from PIL import Image

        thumb = image.copy()
        if max_side <= 0:
            max_side = 256
        max_side = min(max(max_side, 50), 1024)
        thumb.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        thumb.save(buf, format="WEBP", quality=85, method=4)
        return buf.getvalue()
    except Exception as exc:
        if on_error:
            on_error(exc)
        return b""


def history_item_meta_payload(
    item,
    *,
    include_full: bool = False,
    metadata_json_safe: Callable[[Any], Any] | None = None,
) -> dict:
    gen_params = getattr(item, "generation_params", {}) or {}
    prompt_context = getattr(item, "prompt_context", {}) or {}
    raw = {
        "generation_params": gen_params,
        "prompt_context": prompt_context,
        "api_metadata": getattr(item, "api_metadata", {}) or {},
    }
    prompt = ""
    negative = ""
    if isinstance(prompt_context, dict):
        prompt = str(prompt_context.get("main_prompt") or prompt_context.get("final_prompt") or "")
    if isinstance(gen_params, dict):
        prompt = prompt or str(gen_params.get("input") or gen_params.get("prompt") or "")
        negative = str(gen_params.get("negative_prompt") or gen_params.get("uc") or "")
    characters = prompt_context.get("characters") if isinstance(prompt_context, dict) else None

    extra_summary: dict = {}
    # External images (e.g. imported into history) carry no naia_* params; their
    # prompt/params live only in the embedded PNG metadata (NAI Comment/stealth,
    # WebUI parameters, ComfyUI workflow). Extract whenever the in-app prompt is
    # missing so BOTH the summary (the Generation Info panel and floating prompt
    # fetch /api/history/meta WITHOUT full=1) and the full detail view surface it —
    # otherwise external images show "No metadata" in the result view even though
    # the Metadata tab (full=1) reads them. This endpoint is only called per
    # displayed item (the bulk history list uses a different summary), and generated
    # results have a prompt so they skip the stealth-PNG scan.
    if not prompt:
        from utils.image_info import extract_embedded_metadata

        extracted = extract_embedded_metadata(getattr(item, "raw_bytes", None))
        if extracted:
            raw["extracted_metadata"] = extracted
            prompt = prompt or str(extracted.get("prompt") or "")
            negative = negative or str(extracted.get("negative") or extracted.get("uc") or "")
            if not characters and extracted.get("characters"):
                characters = extracted.get("characters")
            ext_params = extracted.get("parameters") if isinstance(extracted.get("parameters"), dict) else {}
            for key in ("seed", "steps", "sampler", "cfg_scale", "scale", "model"):
                value = extracted.get(key)
                if value in ("", None):
                    value = ext_params.get(key)
                if value not in ("", None):
                    extra_summary[key] = value

    result = {}
    if prompt:
        result["prompt"] = prompt
    if negative:
        result["negative"] = negative
    if characters:
        result["characters"] = characters
    if include_full:
        summary = dict(result)
        image = getattr(item, "image", None)
        if image is not None and getattr(image, "width", None) and getattr(image, "height", None):
            summary.setdefault("width", image.width)
            summary.setdefault("height", image.height)
        summary.update(extra_summary)
        result["summary"] = summary
        result["raw"] = metadata_json_safe(raw) if metadata_json_safe else raw
    return result
