"""Build an immutable, uncompressed extension ZIP from generation manifests.

Development-only. Example: python tools/build_character_preview_ext_pack.py --src DIR
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import zipfile

try:
    from tools.build_character_preview_pack import encode_preview
except ModuleNotFoundError:  # direct invocation from tools/
    from build_character_preview_pack import encode_preview


def source_images(sources):
    images = {}
    for source in sources:
        root = Path(source).resolve()
        targets = json.loads((root / "_targets.json").read_text(encoding="utf-8"))
        rows = targets["targets"] if isinstance(targets, dict) else targets
        # Targets also cover PNGs written just before the manifest was appended.
        local = {row["key"]: row.get("file") or f"{row['rank']:05d}.png" for row in rows}
        for manifest in sorted(root.glob("manifest_*.jsonl")):
            for line in manifest.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:  # generator may be writing the final line
                    continue
                if row.get("key") and row.get("file"):
                    local[row["key"]] = row["file"]
        for key, filename in local.items():
            path = (root / filename).resolve()
            if path.is_relative_to(root) and path.suffix.lower() == ".png" and path.is_file():
                images[key] = path  # later source wins, missing PNG never erases an earlier one
    return images


def build_pack(sources, output: Path, bundled: Path) -> dict:
    from PIL import Image

    excluded = json.loads(Path(bundled).read_text(encoding="utf-8"))["thumbs"]
    images = source_images(sources)
    manifest = {"format": 1, "built": datetime.now(timezone.utc).isoformat(), "count": 0, "keys": {}}
    # Exclusive creation is also race safe; never overwrite an existing release name.
    members = set()
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_STORED) as archive:
        for key, path in images.items():
            if key in excluded:
                continue
            member = f"thumbs/{hashlib.sha1(key.encode('utf-8')).hexdigest()[:16]}.webp"
            if member in members:
                raise ValueError(f"Thumbnail hash collision: {key}")
            with Image.open(path) as image:
                archive.writestr(member, encode_preview(image))
            manifest["keys"][key] = member
            members.add(member)
        manifest["count"] = len(manifest["keys"])
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False).encode("utf-8"))
    print(f"Saved: {output} ({manifest['count']} items, {output.stat().st_size / 1024**2:.1f} MB)")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", action="append", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=Path(f"NAIA_character_pack_{datetime.now():%y%m%d}.zip"))
    parser.add_argument("--bundled", type=Path,
                        default=Path(__file__).resolve().parents[1] / "data/character_preview_thumbs.json")
    args = parser.parse_args()
    build_pack(args.src, args.out, args.bundled)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
