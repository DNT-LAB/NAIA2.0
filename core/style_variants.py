"""Shared paths and bounded metadata validation for the optional Thumb A|B pack."""
from __future__ import annotations

import json
import math
from pathlib import Path
import re

from core.character_preview_index import PreviewKeyIndex


STYLE_VARIANTS_NAME = "style_variants.json"
# 311,249,091 bytes; the install manager reports MB in units of 1024**2.
STYLE_VARIANTS_APPROX_MB = 297
STYLE_VARIANTS_INDEX_NAME = "variants-key-index.json"


def style_variants_path(runtime_paths) -> Path:
    return runtime_paths.data_dir / "style_variants" / STYLE_VARIANTS_NAME


def read_variants_metadata(path: Path) -> dict:
    """Parse only the prefix before the top-level thumbs member (never its body)."""
    prefix = bytearray()
    marker = re.compile(rb',\s*"thumbs"\s*:\s*\{')
    with path.open("rb") as handle:
        # Bound malformed inputs too; the current 430-tag header is under 256 KiB.
        while len(prefix) < 16 * 1024 * 1024:
            chunk = handle.read(64 * 1024)
            if not chunk:
                break
            prefix.extend(chunk)
            for match in marker.finditer(prefix):
                try:
                    metadata = json.loads(prefix[:match.start()] + b"}")
                except (ValueError, UnicodeError):
                    # A tag may itself be named 'thumbs'; only a complete root
                    # object before this member identifies the real boundary.
                    continue
                return metadata
    raise ValueError("Invalid style variants metadata header")


def open_variants(path: Path, *, cache_write: bool = True,
                  cache_path: Path | None = None) -> tuple[dict, PreviewKeyIndex]:
    metadata = read_variants_metadata(path)
    if type(metadata.get("version")) is not int or metadata["version"] != 1:
        raise ValueError("Unsupported style variants version")
    bases, tags = metadata.get("bases"), metadata.get("index")
    if not isinstance(bases, dict) or not isinstance(tags, dict) or not tags:
        raise ValueError("Invalid style variants index/bases")
    keys = set()
    for base, info in bases.items():
        if base not in {"preset", "bare"} or not isinstance(info, dict) or not isinstance(info.get("gt"), str):
            raise ValueError("Invalid style variants base")
        keys.add(info["gt"])
    for tag, info in tags.items():
        if (not isinstance(info, dict) or info.get("base") not in bases
                or not isinstance(info.get("variants"), list) or not info["variants"]):
            raise ValueError("Invalid style variants tag")
        columns = set()
        for variant in info["variants"]:
            if (not isinstance(variant, dict)
                    or not isinstance(variant.get("col"), str) or not variant["col"]
                    or variant["col"] in columns
                    or variant.get("place") not in {"uc", "pos", "front"}
                    or type(variant.get("weight")) not in (int, float)
                    or not math.isfinite(variant["weight"])
                    or not isinstance(variant.get("key"), str)):
                raise ValueError("Invalid style variant entry")
            columns.add(variant["col"])
            keys.add(variant["key"])
    index = PreviewKeyIndex(path, cache_path or path.parent / STYLE_VARIANTS_INDEX_NAME,
                            extension=False, cache_write=cache_write)
    if not keys.issubset(index):
        raise ValueError("Style variants thumbnail keys are missing")
    return metadata, index
