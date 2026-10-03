"""Reviewable translation source; dictionary/taxonomy remain in e621_data.

LF-normalized hashes work with either Git checkout newline convention.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

CATALOG_SCHEMA = "naia.e621-translations.v2"
ASSET_NAMES = ("translations.json",)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key: " + key)
        result[key] = value
    return result


def text_digest(data: bytes) -> str:
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def rows_json(rows: list[dict[str, Any]]) -> str:
    return "[\n" + ",\n".join(" " + json.dumps(row, ensure_ascii=False) for row in rows) + "\n]\n"


def load_catalog(directory: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    manifest = json.loads((directory / "manifest.json").read_bytes(), object_pairs_hook=_unique_object)
    if not isinstance(manifest, dict) or manifest.get("schema") != CATALOG_SCHEMA or manifest.get("site") != "e621":
        raise ValueError("unsupported e621 translation manifest")
    assets = manifest.get("assets")
    if not isinstance(assets, dict) or set(assets) != set(ASSET_NAMES):
        raise ValueError("invalid translation asset list")
    entry = assets["translations.json"]
    if not isinstance(entry, dict) or not isinstance(entry.get("sha256_lf"), str):
        raise ValueError("invalid translation asset digest")
    blob = (directory / "translations.json").read_bytes()
    if text_digest(blob) != entry["sha256_lf"]:
        raise ValueError("translation asset digest mismatch")
    rows = json.loads(blob, object_pairs_hook=_unique_object)
    if not isinstance(rows, list) or not all(isinstance(row, dict) and isinstance(row.get("tag"), str) and row["tag"] for row in rows):
        raise ValueError("invalid translation records")
    if len({row["tag"] for row in rows}) != len(rows):
        raise ValueError("duplicate translation identity")
    if {"translations": len(rows)} != manifest.get("counts"):
        raise ValueError("translation counts do not match manifest")
    return rows, manifest
