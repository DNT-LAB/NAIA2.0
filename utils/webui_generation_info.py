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


def _alwayson_summary(alwayson: Any) -> list[str]:
    """Infotext fragments summarising the requested alwayson scripts (ADetailer/ControlNet)."""
    out: list[str] = []
    if not isinstance(alwayson, Mapping):
        return out
    adetailer = alwayson.get("ADetailer")
    if isinstance(adetailer, Mapping):
        args = adetailer.get("args") or []
        # forge ADetailer args: [enabled, skip_img2img, unit1{...}, unit2{...}, ...]
        if isinstance(args, Sequence) and not isinstance(args, (str, bytes)) and args and args[0]:
            for unit in args:
                if not isinstance(unit, Mapping):
                    continue
                model = str(unit.get("ad_model") or "").strip()
                if not model or model.lower() == "none":
                    continue
                out.append(f"ADetailer model: {model}")
                if unit.get("ad_confidence") is not None:
                    out.append(f"ADetailer confidence: {unit.get('ad_confidence')}")
                if unit.get("ad_denoising_strength") is not None:
                    out.append(f"ADetailer denoising strength: {unit.get('ad_denoising_strength')}")
                break  # first active unit is enough to confirm ADetailer was requested
    controlnet = alwayson.get("ControlNet")
    if isinstance(controlnet, Mapping):
        args = controlnet.get("args") or []
        if isinstance(args, Sequence) and not isinstance(args, (str, bytes)):
            active = sum(1 for u in args if isinstance(u, Mapping) and u.get("enabled"))
            if active:
                out.append(f"ControlNet units active: {active}")
    return out


def build_webui_infotext_from_payload(payload: Any, actual_seed: Any = None) -> str:
    """Reconstruct an A1111-style ``parameters`` infotext from the request payload.

    Some forge forks (forge-neo/reForge) return an empty or unreadable ``info`` field
    from ``/sdapi/v1/txt2img``, so a NAIA-saved image would have no metadata at all. When
    that happens we rebuild the infotext from exactly what NAIA sent (prompt, core params,
    and a summary of the requested alwayson scripts such as ADetailer), so the saved PNG
    is never metadata-less and the user can see ADetailer/ControlNet were dispatched.
    """
    if not isinstance(payload, Mapping):
        return ""
    pos = str(payload.get("prompt") or "").strip()
    neg = str(payload.get("negative_prompt") or "").strip()
    seed = actual_seed if actual_seed is not None else payload.get("seed")
    parts: list[str] = []
    if payload.get("steps") is not None:
        parts.append(f"Steps: {payload.get('steps')}")
    sampler = payload.get("sampler_name") or payload.get("sampler")
    if sampler:
        parts.append(f"Sampler: {sampler}")
    if payload.get("scheduler"):
        parts.append(f"Schedule type: {payload.get('scheduler')}")
    if payload.get("cfg_scale") is not None:
        parts.append(f"CFG scale: {payload.get('cfg_scale')}")
    if seed is not None:
        parts.append(f"Seed: {seed}")
    width, height = payload.get("width"), payload.get("height")
    if width and height:
        parts.append(f"Size: {width}x{height}")
    override = payload.get("override_settings")
    model = str(override.get("sd_model_checkpoint") or "").strip() if isinstance(override, Mapping) else ""
    if model:
        parts.append(f"Model: {model}")
    parts.extend(_alwayson_summary(payload.get("alwayson_scripts")))
    lines = [pos]
    if neg:
        lines.append(f"Negative prompt: {neg}")
    if parts:
        lines.append(", ".join(str(part) for part in parts))
    return "\n".join(lines)


def embed_webui_parameters(raw_bytes: Any, info: Any) -> Any:
    """Bake the WebUI infotext into a PNG ``parameters`` text chunk when it is absent.

    forge/A1111 returns the infotext only in the API response's ``info`` field; the
    image bytes it sends back carry NO ``parameters`` chunk. Crucially forge-neo returns
    the image as **WEBP** (which can't hold A1111 text metadata at all), and NAIA re-saves
    WEBUI results as PNG anyway — that re-encode previously dropped everything. So here we
    re-encode the image to PNG and bake the infotext into a ``parameters`` text chunk,
    regardless of the inbound format (WEBP/JPEG/PNG). The result is a PNG whose metadata a
    forge "PNG Info" tab / the NAIA viewer can read (prompt, seed, ADetailer/ControlNet).
    A PNG that already carries a non-empty ``parameters`` chunk is returned untouched
    (forge baked it in). NAI/ComfyUI never reach here — only ``_call_webui_api`` sets
    ``generation_info``. Any failure returns the input bytes unchanged.
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
            fmt = (img.format or "").upper()
            existing = dict(img.info or {})
            current = existing.get("parameters")
            # A PNG forge already stamped with a parameters chunk — keep its bytes verbatim.
            if fmt == "PNG" and isinstance(current, str) and current.strip():
                return data
            pnginfo = PngImagePlugin.PngInfo()
            for key, value in existing.items():
                if isinstance(key, str) and isinstance(value, str) and key != "parameters":
                    pnginfo.add_text(key, value)
            pnginfo.add_text("parameters", infotext)
            # forge-neo sends WEBP; re-encode to PNG with the chunk (NAIA saves WEBUI as PNG
            # anyway, so this is the same single re-encode, just metadata-preserving now).
            out = img if img.mode in ("RGB", "RGBA", "L", "P") else img.convert("RGB")
            buffer = io.BytesIO()
            out.save(buffer, format="PNG", pnginfo=pnginfo)
            return buffer.getvalue()
    except Exception:
        return raw_bytes
