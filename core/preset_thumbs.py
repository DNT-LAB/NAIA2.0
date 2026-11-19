"""Bounded reader for the optional preset bench WebP pack."""
from __future__ import annotations

import json
from pathlib import Path
import re

from core.character_preview_index import PreviewKeyIndex, character_pack_fingerprint
from core.style_variants import validate_variant_images


PRESET_THUMBS_NAME = "preset_thumbs.json"
PRESET_THUMBS_INDEX_NAME = "preset-thumbs-key-index.json"
PRESET_THUMBS_APPROX_MB = 414
KINDS = {"outfit", "event", "expression", "scene", "link"}
_THUMBS = re.compile(rb',\s*"thumbs"\s*:\s*\{')


def preset_thumbs_path(runtime_paths) -> Path:
    return runtime_paths.data_dir / "preset_thumbs" / PRESET_THUMBS_NAME


def installed_signature(path: Path):
    fingerprint = character_pack_fingerprint(path)
    if not fingerprint:
        return None
    try:
        stat = path.stat()
        signature = (fingerprint, stat.st_size, stat.st_mtime_ns)
        marker = path.with_suffix(".corrupt")
        if marker.is_file() and marker.read_text(encoding="ascii") == _marker_text(signature):
            return None
        return signature
    except (OSError, UnicodeError):
        return None


def _marker_text(signature) -> str:
    digest, size, mtime = signature
    return f"{digest} {size} {mtime}\n"


def mark_corrupt(path, signature):
    # Bind a rejection to these bytes. A replacement becomes visible even if
    # another process could not remove the old marker.
    try:
        path.with_suffix(".corrupt").write_text(_marker_text(signature), encoding="ascii", newline="\n")
    except OSError:
        pass


def read_metadata(path: Path) -> dict:
    prefix = bytearray()
    with path.open("rb") as stream:
        for _ in range(16):
            chunk = stream.read(64 * 1024)
            if not chunk:
                break
            prefix.extend(chunk)
            for match in _THUMBS.finditer(prefix):
                try:
                    header = json.loads(prefix[:match.start()] + b"}")
                except ValueError:
                    continue  # Only a complete root object ends the header.
                if not isinstance(header, dict):
                    raise ValueError("Invalid preset thumbnail header")
                count, kinds = header.get("count"), header.get("kinds")
                if (type(header.get("schema")) is not int or header["schema"] != 1
                        or header.get("format") != "webp" or type(count) is not int or count <= 0
                        or not isinstance(kinds, dict) or not kinds.keys() <= KINDS
                        or any(type(n) is not int or n < 0 for n in kinds.values())
                        or sum(kinds.values()) != count):
                    raise ValueError("Invalid preset thumbnail metadata")
                return header
    raise ValueError("Missing preset thumbnail metadata header")


def open_preset_thumbs(path: Path, *, cache_write: bool = True, cache_path: Path | None = None,
                      validate_images: bool = False) -> tuple[dict, PreviewKeyIndex]:
    metadata = read_metadata(path)
    index = PreviewKeyIndex(path, cache_path or path.parent / PRESET_THUMBS_INDEX_NAME,
                            extension=False, cache_write=cache_write)
    if len(index) != metadata["count"]:
        raise ValueError("Preset thumbnail index count mismatch")
    # The generic index stops at the end of the thumbs map. Require the
    # enclosing object to end as well, including on interrupted downloads.
    with path.open("rb") as stream:
        stream.seek(next(reversed(index.offsets.values()))[1])
        closing = b""
        for chunk in iter(lambda: stream.read(4096), b""):
            closing += chunk.translate(None, b" \r\t\n")
            if not b"}}".startswith(closing):
                raise ValueError("Invalid preset thumbnail pack terminator")
        if closing != b"}}":
            raise ValueError("Truncated preset thumbnail pack")
    if validate_images:
        validate_variant_images(index, index)
    return metadata, index
