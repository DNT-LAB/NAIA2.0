"""Helpers for Stable Diffusion WebUI generation info payloads."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any


_SEED_RE = re.compile(r"(?:^|[\n,])\s*Seed:\s*(-?\d+)\b", re.IGNORECASE)


def _coerce_seed(value: Any) -> int | None:
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, float) and not value.is_integer():
            return None
        seed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return seed if seed >= 0 else None


def _first_seed_from_sequence(value: Any) -> int | None:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        return None
    for item in value:
        seed = extract_webui_seed(item)
        if seed is not None:
            return seed
    return None


def extract_webui_seed(value: Any) -> int | None:
    """Return the actual non-negative WebUI seed from JSON, infotext, or metadata."""
    if value is None:
        return None

    seed = _coerce_seed(value)
    if seed is not None:
        return seed

    if isinstance(value, Mapping):
        for key in ("actual_seed", "webui_seed", "seed"):
            seed = _coerce_seed(value.get(key))
            if seed is not None:
                return seed
        for key in ("all_seeds", "seeds"):
            seed = _first_seed_from_sequence(value.get(key))
            if seed is not None:
                return seed
        for key in ("parameters", "generation_params", "api_metadata", "metadata"):
            nested = value.get(key)
            if nested is not value:
                seed = extract_webui_seed(nested)
                if seed is not None:
                    return seed
        for key in ("infotexts", "info_texts"):
            seed = _first_seed_from_sequence(value.get(key))
            if seed is not None:
                return seed
        for key in ("infotext", "info_text", "generation_info", "info", "parameters"):
            nested = value.get(key)
            if isinstance(nested, str):
                seed = extract_webui_seed(nested)
                if seed is not None:
                    return seed
        return None

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            decoded = json.loads(text)
        except (TypeError, ValueError):
            decoded = None
        if decoded is not None:
            seed = extract_webui_seed(decoded)
            if seed is not None:
                return seed
        match = _SEED_RE.search(text)
        if match:
            return _coerce_seed(match.group(1))
        return None

    return _first_seed_from_sequence(value)


def extract_webui_infotext(value: Any) -> str:
    """Return a human-readable WebUI infotext from API response info."""
    if value is None:
        return ""
    if isinstance(value, Mapping):
        for key in ("infotext", "info_text"):
            text = value.get(key)
            if isinstance(text, str) and text.strip():
                return text.strip()
        for key in ("infotexts", "info_texts"):
            items = value.get(key)
            if isinstance(items, Sequence) and not isinstance(items, (str, bytes, bytearray)):
                for item in items:
                    if isinstance(item, str) and item.strip():
                        return item.strip()
        for key in ("generation_info", "info", "parameters"):
            text = value.get(key)
            if isinstance(text, str) and text.strip():
                return extract_webui_infotext(text)
        return ""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ""
        try:
            decoded = json.loads(text)
        except (TypeError, ValueError):
            return text
        infotext = extract_webui_infotext(decoded)
        return infotext or text
    return ""


def embed_webui_parameters(raw_bytes: Any, info: Any) -> Any:
    """Bake the WebUI infotext into a PNG ``parameters`` text chunk when it is absent.

    forge/A1111 returns the infotext only in the API response's ``info`` field; the
    base64 image it sends back frequently carries NO ``parameters`` chunk (forge bakes
    that in only when *it* writes the file to disk). A NAIA-saved WEBUI image is the raw
    API bytes, so without this it has no metadata at all. We add the chunk so a
    NAIA-saved WEBUI PNG matches a forge-saved one (and the metadata viewer / re-import
    can read prompt, seed, ADetailer/ControlNet args, etc.). If the image already has a
    non-empty ``parameters`` chunk we return the original bytes untouched (forge baked it
    in). NAI/ComfyUI never reach here — only ``_call_webui_api`` sets ``generation_info``.
    Any failure returns the input bytes unchanged.
    """
    if not raw_bytes:
        return raw_bytes
    infotext = extract_webui_infotext(info)
    if not infotext:
        return raw_bytes
    try:
        import io

        from PIL import Image, PngImagePlugin

        data = bytes(raw_bytes)
        with Image.open(io.BytesIO(data)) as img:
            if (img.format or "").upper() != "PNG":
                return data
            existing = dict(img.info or {})
            current = existing.get("parameters")
            if isinstance(current, str) and current.strip():
                return data
            pnginfo = PngImagePlugin.PngInfo()
            for key, value in existing.items():
                if isinstance(key, str) and isinstance(value, str) and key != "parameters":
                    pnginfo.add_text(key, value)
            pnginfo.add_text("parameters", infotext)
            buffer = io.BytesIO()
            img.save(buffer, format="PNG", pnginfo=pnginfo)
            return buffer.getvalue()
    except Exception:
        return raw_bytes
