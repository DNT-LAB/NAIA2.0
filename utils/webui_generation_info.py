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
