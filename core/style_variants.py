"""Shared paths and bounded metadata validation for the optional Thumb A|B pack."""
from __future__ import annotations

import base64
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import io
import json
import math
import os
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


def is_webp(image: bytes) -> bool:
    return len(image) >= 12 and image[:4] == b"RIFF" and image[8:12] == b"WEBP"


def _decode_check(key: str, encoded: str) -> None:
    from PIL import Image

    try:
        image = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise ValueError(f"Style variant image is not valid base64: {key}") from exc
    if not is_webp(image):
        raise ValueError(f"Style variant image is not WebP: {key}")
    try:
        with Image.open(io.BytesIO(image)) as decoded:
            decoded.load()
    except Exception as exc:  # noqa: BLE001 - PIL 은 여러 종류를 던진다
        raise ValueError(f"Style variant image is unreadable: {key}") from exc


def validate_variant_images(index: PreviewKeyIndex, keys) -> None:
    """설치 때만: 모든 그림이 base64 로 풀리고 WebP 로 **실제로 디코딩되는지**(Codex 리뷰 2026-10-26 #2 - 그림 하나가
    깨져도 설치를 통과하고 '준비됨' 으로 남아 다시 받을 길이 막혔다). verify() 는 WebP 머리만 보고 픽셀은 안 읽어서
    머리는 멀쩡하고 몸통이 깨진 그림을 통과시켰다(재리뷰 R1) - load() 로 끝까지 푼다.
    2,184장을 한 줄로 풀면 30초 - 디코딩만 스레드 여럿에 나눈다(6초). 색인 읽기는 이 스레드에서만,
    한 번에 떠 있는 그림은 몇십 장뿐이라 메모리는 그대로다."""
    workers = max(1, min(8, os.cpu_count() or 1))
    with ThreadPoolExecutor(workers, thread_name_prefix="style-variants-check") as pool:
        pending = deque()
        for key in sorted(keys):
            try:
                encoded = index[key]
            except KeyError as exc:
                raise ValueError(f"Style variant image is missing: {key}") from exc
            pending.append(pool.submit(_decode_check, key, encoded))
            if len(pending) >= workers * 4:
                pending.popleft().result()
        while pending:
            pending.popleft().result()


def open_variants(path: Path, *, cache_write: bool = True,
                  cache_path: Path | None = None, validate_images: bool = False) -> tuple[dict, PreviewKeyIndex]:
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
    if validate_images:
        validate_variant_images(index, keys)
    return metadata, index
