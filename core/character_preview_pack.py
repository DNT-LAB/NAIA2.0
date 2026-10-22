"""Small shared manifest contract for the downloaded character preview ZIP."""
from __future__ import annotations

import json
import re
from zipfile import ZipFile


def read_manifest(archive: ZipFile) -> dict:
    # Read metadata only, never thumbnail bodies while indexing/validating readiness.
    info = archive.getinfo("manifest.json")
    if info.file_size > 16 * 1024 * 1024:
        raise ValueError("Character pack manifest is too large")
    doc = json.loads(archive.read(info))
    if not isinstance(doc, dict) or doc.get("format") != 1:
        raise ValueError("Unsupported character pack format")
    keys = doc.get("keys")
    if not isinstance(keys, dict) or doc.get("count") != len(keys):
        raise ValueError("Invalid character pack count/keys")
    for key, member in keys.items():
        if not isinstance(key, str) or not isinstance(member, str) or not re.fullmatch(
                r"thumbs/[0-9a-f]{16}\.webp", member):
            raise ValueError("Invalid character pack member")
        archive.getinfo(member)
    return doc
