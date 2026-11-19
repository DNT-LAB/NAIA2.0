"""프리셋 썸네일 팩(JSON 한 파일)을 굽는다 - 사양 docs/presets_remake/2026-11-18/PRESET_BENCH_SRS.md §6.

입력 = tools/preset_thumb_generate.py 의 출력 폴더(<key>.png + _targets.json).
출력 = 캐릭터 확장 팩과 같은 꼴의 JSON. 작은 메타가 **앞**, `thumbs` 가 **뒤**(키 정렬) - 서버는
core/character_preview_index.PreviewKeyIndex 로 thumbs 의 바이트 자리만 색인해 한 장씩 꺼낸다(팩을 통째로 읽지 않는다).

  {"note": [...], "schema": 1, "template_version": "...", "key_rule": "sha1(kind|head|sorted tags)[:16]",
   "format": "webp", "quality": 80, "sizes": {"outfit": [525, 768], ...}, "count": N, "kinds": {"outfit": n, ...},
   "thumbs": {"<key>": "<base64 webp>", ...}}

줄이기: 긴 변 768 · 비율 유지 · 자르지 않음(의상 832x1216 -> 525x768 · 나머지 1024² -> 768²) · LANCZOS · WebP method 6.
그림이 없는 대상 키는 건너뛴다(부분 팩 허용 - 끝에 수를 찍는다).

  python tools/build_preset_thumb_pack.py --src .experimental/preset_thumb_src/20261118 \
      --out <dir>/NAIA_preset_thumbs_YYMMDD.json [--quality 80] [--workers 8]

판이 바뀌면 파일 이름을 바꾼다(같은 이름 덮어쓰기 금지 - 받은 사람의 색인 캐시가 어긋난다). 같은 이름이 있으면 거절한다.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LONG_SIDE = 768
KEY_RULE = "sha1(kind|head|sorted tags)[:16]"
KINDS = ("outfit", "event", "expression", "scene", "link")


def target_size(width: int, height: int) -> tuple[int, int]:
    """긴 변을 LONG_SIDE 로 - 비율 유지(반올림)."""
    scale = LONG_SIDE / max(width, height)
    return round(width * scale), round(height * scale)


def encode(job: tuple[str, int]) -> bytes:
    path, quality = job
    with Image.open(path) as image:
        image = image.convert("RGB")
        size = target_size(*image.size)
        if image.size != size:
            image = image.resize(size, Image.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, "WEBP", quality=quality, method=6)
    return buffer.getvalue()


def collect(src: Path) -> tuple[dict, list[dict], list[str]]:
    doc = json.loads((src / "_targets.json").read_text(encoding="utf-8"))
    present, missing = [], []
    for target in doc["targets"]:
        (present if (src / f"{target['key']}.png").is_file() else missing).append(target)
    present.sort(key=lambda t: t["key"])
    return doc, present, [t["key"] for t in missing]


def build(src: Path, out: Path, *, quality: int = 80, workers: int = 8, log=print) -> dict:
    if out.exists():
        raise FileExistsError(f"{out} already exists - a new version needs a new file name")
    doc, present, missing = collect(src)
    if not present:
        raise ValueError(f"no thumbnails under {src}")
    keys = [t["key"] for t in present]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate keys in _targets.json")
    kinds = Counter(t["kind"] for t in present)
    unknown = set(kinds) - set(KINDS)
    if unknown:
        raise ValueError(f"unknown kinds {sorted(unknown)}")
    sizes = {}
    for target in present:  # 갈래마다 원본 크기가 하나여야 한다(틀 = 갈래별 해상도)
        size = target_size(target["width"], target["height"])
        if sizes.setdefault(target["kind"], size) != size:
            raise ValueError(f"mixed sizes in kind {target['kind']}")
    head = {
        "note": [
            "NAIA preset thumbnails (tools/build_preset_thumb_pack.py).",
            "thumbs = key -> base64 WebP. key = core/preset_thumb_key.preset_thumb_key(kind, head, tags).",
            "Read with core.character_preview_index.PreviewKeyIndex - do not json.load the whole pack at runtime.",
        ],
        "schema": 1,
        "template_version": doc["template_version"],
        "key_rule": KEY_RULE,
        "format": "webp",
        "quality": quality,
        "sizes": {kind: list(sizes[kind]) for kind in KINDS if kind in sizes},
        "count": len(present),
        "kinds": {kind: kinds[kind] for kind in KINDS if kinds[kind]},
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    raw_bytes = Counter()
    started = time.time()
    jobs = [(str(src / f"{key}.png"), quality) for key in keys]
    with ProcessPoolExecutor(max_workers=workers) as pool, open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(head, ensure_ascii=False)[:-1] + ', "thumbs": {')
        for n, (target, data) in enumerate(zip(present, pool.map(encode, jobs, chunksize=16)), 1):
            raw_bytes[target["kind"]] += len(data)
            fh.write(("" if n == 1 else ", ") + json.dumps(target["key"]) + ": "
                     + json.dumps(base64.b64encode(data).decode("ascii")))
            if n % 500 == 0:
                log(f"  {n}/{len(jobs)} {time.time() - started:.0f}s")
        fh.write("}}\n")
        fh.flush()
        os.fsync(fh.fileno())
    _verify(tmp, head, keys)
    os.replace(tmp, out)
    report = {
        "path": str(out), "bytes": out.stat().st_size, "count": len(present), "missing": len(missing),
        "kinds": {kind: {"count": kinds[kind], "avg_webp_kb": round(raw_bytes[kind] / kinds[kind] / 1024, 1)}
                  for kind in head["kinds"]},
        "seconds": round(time.time() - started, 1),
    }
    return report


def _verify(path: Path, head: dict, keys: list[str]) -> None:
    """올리기 전에: 메타가 그대로인지 · 색인기가 모든 키를 찾는지 · 앞뒤 그림이 WebP 로 풀리는지."""
    from core.character_preview_index import PreviewKeyIndex

    with path.open("rb") as fh:
        prefix = fh.read(64 * 1024)
    meta = json.loads(prefix[:prefix.index(b', "thumbs": {')] + b"}")
    if meta != head:
        raise ValueError("pack header mismatch")
    index = PreviewKeyIndex(path, cache_path=None)
    if list(index) != keys:
        raise ValueError(f"indexer found {len(index)} keys, expected {len(keys)}")
    for key in {keys[0], keys[len(keys) // 2], keys[-1]}:
        with Image.open(io.BytesIO(base64.b64decode(index[key]))) as image:
            if image.format != "WEBP":
                raise ValueError(f"{key} is not WebP")
            image.load()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--src", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--quality", type=int, default=80)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    if not 1 <= args.quality <= 100:
        parser.error("--quality must be 1..100")
    report = build(args.src, args.out, quality=args.quality, workers=args.workers)
    for kind, row in report["kinds"].items():
        print(f"{kind:<11} {row['count']:>5}  avg {row['avg_webp_kb']:.1f}KB")
    print(f"wrote {report['path']}  {report['bytes'] / 1e6:.1f}MB  count {report['count']}  "
          f"missing {report['missing']}  {report['seconds']}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
