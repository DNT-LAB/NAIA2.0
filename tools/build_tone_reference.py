"""Build bundled constants from read-only PNG folders; intermediates stay in docs.

--reuse-jsonl is an explicit assertion that measurements use the final inspector.
Its selected paths must exactly match the requested folders (0_first.png excluded).
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import pprint
import sys

for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_name] = "1"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.image_tone_reference import AXIS_SPECS, metric_value

CORPUS = Path(r"C:\VNR\artist_thumb_tool\data\artist_thumb\nai-diffusion-5-full")
DEFAULT_FOLDERS = [CORPUS / f"review_raw{i}" for i in range(50, 59)]


def select_paths(folders):
    paths = set()
    for folder in folders:
        if not folder.is_dir():
            raise ValueError(f"Missing sample folder: {folder}")
        paths.update(p.resolve() for p in folder.glob("*/*.png") if p.name.lower() != "0_first.png")
    if not paths:
        raise ValueError("No sample images")
    return sorted(paths)


def build_reference(rows, sample, built_at=None):
    rows = list(rows)
    n = len(rows)
    cut = round(n * 500 / 4002)
    if not n or n - 2*cut <= 0:
        raise ValueError("Empty trimmed sample")
    axes = []
    for axis_id, key, label, digits, cautions, primary in AXIS_SPECS:
        values = [metric_value(r["result"], key) for r in rows]
        if any(v is None for v in values):
            raise ValueError(f"Missing/nonfinite sample metric: {key}")
        values.sort()
        kept = values[cut:n-cut]
        axes.append({"id": axis_id, "key": key, "label": label, "zero": math.fsum(kept)/len(kept),
                     "low": kept[0], "high": kept[-1], "digits": digits,
                     "cautions": list(cautions), "primary": primary})
    return {"schema": "naia.tone-reference.v1", "sample": sample, "images": n,
            "rule": "cut = round(n * 500 / 4002); zero = trimmed mean; band = trimmed min/max",
            "built_at": built_at or datetime.now(timezone.utc).isoformat(), "axes": axes}


def measure(path):
    from core.image_tone_inspector import inspect_image
    return {"path": str(path), "file": path.name, "result": inspect_image(path)}


def write_reference(reference, module):
    source = module.read_text(encoding="utf-8")
    start, end = "# BEGIN GENERATED REFERENCE\n", "# END GENERATED REFERENCE"
    assert source.count(start) == source.count(end) == 1
    before, rest = source.split(start)
    _, after = rest.split(end)
    source = before + start + "REFERENCE = " + pprint.pformat(reference, sort_dicts=False, width=110) + "\n" + end + after
    module.write_text(source, encoding="utf-8", newline="\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folders", type=Path, nargs="*", default=DEFAULT_FOLDERS)
    parser.add_argument("--reuse-jsonl", type=Path)
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=4)
    parser.add_argument("--output", type=Path, default=ROOT/"docs/tone_eval_2026_10_03/round3/reference_measurements.jsonl")
    args = parser.parse_args()
    paths = select_paths(args.folders)
    output = args.output.resolve()
    for folder in args.folders:
        if output.is_relative_to(folder.resolve()):
            raise ValueError("Output must be outside sample folders")
    rows = []
    if args.reuse_jsonl:
        selected = set(paths)
        with args.reuse_jsonl.open(encoding="utf-8") as stream:
            rows = [r for line in stream if Path((r := json.loads(line))["path"]).resolve() in selected]
        if len(rows) != len(paths) or {Path(r["path"]).resolve() for r in rows} != selected:
            raise ValueError("JSONL must contain every selected path exactly once")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        with ProcessPoolExecutor(max_workers=args.workers) as pool, output.open("w",encoding="utf-8",newline="\n") as stream:
            for row in pool.map(measure, paths):
                rows.append(row)
                stream.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+"\n"); stream.flush()
                if len(rows)%100 == 0: print(f"reference {len(rows)}/{len(paths)}",flush=True)
    reference = build_reference(rows, "NAIA random prompts; " + ", ".join(p.name for p in args.folders) + "; <artist>/*.png excluding 0_first.png")
    write_reference(reference, ROOT/"core/image_tone_reference.py")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix(".manifest.json").write_text(json.dumps({
        "inspector_sha256": hashlib.sha256((ROOT/"core/image_tone_inspector.py").read_bytes()).hexdigest(),
        "reuse_jsonl": str(args.reuse_jsonl) if args.reuse_jsonl else None,
        "paths": [str(p) for p in paths], "reference": reference},ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"images":len(rows),"cut":round(len(rows)*500/4002),"axes":len(reference['axes'])}))


if __name__ == "__main__":
    main()
