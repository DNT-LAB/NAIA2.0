"""생성 매니페스트로 캐릭터 썸네일 확장 JSON 을 만든다(개발 전용).

Development-only. Example: python tools/build_character_preview_ext_pack.py --src DIR
"""
from __future__ import annotations

import argparse
from datetime import datetime
import base64
import json
from pathlib import Path
import os

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
            if path.is_relative_to(root) and path.suffix.lower() in {".png", ".webp"} and path.is_file():
                images[key] = path  # later source wins, missing PNG never erases an earlier one
    return images


def build_pack(sources, output: Path, bundled: Path, exclude_bundled: bool = False) -> dict:
    from PIL import Image

    # 번들 키도 담는다(사용자 결정 2026-10-22: 번들 3,000 도 V5 로 통일 - 서비스는 확장 팩을 번들보다 먼저 본다).
    # 옛 동작(번들에 있는 키는 빼기)은 --exclude-bundled.
    excluded = json.loads(Path(bundled).read_text(encoding="utf-8"))["thumbs"] if exclude_bundled else {}
    images = source_images(sources)
    keys = sorted(key for key in images if key not in excluded)
    metadata = {
        "note": [
            "캐릭터 썸네일 확장 팩 · 생성 사양 V5.",
            "우선순위: 1) 사용자 썸네일 2) 확장 팩 3) 번들 팩.",
            "384px / webp q72 · WebP 원본은 재인코딩하지 않는다.",
            "tools/build_character_preview_ext_pack.py 가 만든다.",
        ],
        "size": 384, "quality": 72, "count": len(keys),
    }
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    # ⚠️ 같은 출력의 동시 빌드도 막는다. 완성 전에는 최종 이름으로 노출하지 않는다.
    temporary = output.with_name(output.name + ".tmp")
    handle = temporary.open("x", encoding="utf-8", newline="")
    try:
        with handle:
            handle.write(json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))[:-1])
            handle.write(',"thumbs":{')
            for position, key in enumerate(keys):
                path = images[key]
                if path.suffix.lower() == ".webp":
                    raw = path.read_bytes()
                else:
                    # PNG 입력은 기존 번들과 같은 자르기 · 크기 · 화질로 한 번만 변환한다.
                    with Image.open(path) as image:
                        raw = encode_preview(image)
                if position:
                    handle.write(",")
                handle.write(json.dumps(key, ensure_ascii=False, separators=(",", ":")))
                handle.write(":")
                handle.write(json.dumps(base64.b64encode(raw).decode("ascii")))
            handle.write("}}")
            handle.flush()
            os.fsync(handle.fileno())
        if output.exists():
            raise FileExistsError(output)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Saved: {output} ({metadata['count']} items, {output.stat().st_size / 1024**2:.1f} MB)")
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", action="append", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=Path(f"NAIA_character_pack_{datetime.now():%y%m%d}.json"))
    parser.add_argument("--bundled", type=Path,
                        default=Path(__file__).resolve().parents[1] / "data/character_preview_thumbs.json")
    parser.add_argument("--exclude-bundled", action="store_true", help="번들 팩에 있는 키는 빼기(옛 동작)")
    args = parser.parse_args()
    build_pack(args.src, args.out, args.bundled, exclude_bundled=args.exclude_bundled)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
