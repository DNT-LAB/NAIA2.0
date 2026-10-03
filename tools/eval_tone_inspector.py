"""Offline, resumable tone evaluation. Inputs are read-only; outputs must be elsewhere.

Example: python tools/eval_tone_inspector.py measure RAW --output docs/tone/run.jsonl
         python tools/eval_tone_inspector.py summarize docs/tone/run.jsonl --output docs/tone/summary.json
Sampling is balanced by bucket epoch, NOT a population-weighted estimate.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import time

# Bound native numerical threads as well as Python workers (before numpy import).
for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_name] = "1"
import numpy as np
from PIL import Image, ImageDraw
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DEFAULT_MODULE = ROOT / "core/image_tone_inspector.py"
PERCENTILES = [1, 5, 25, 50, 75, 95, 99]
TAIL_METRICS = ["lightness.mean", "chroma.mean", "tint.highlights.b", "texture.grain",
                "texture.sharpness", "lines.width", "lines.steepness", "lines.floor",
                "lines.depth", "lines.flank", "hue.effective_hues", "hue.warm_share"]


def load_module(path):
    spec = importlib.util.spec_from_file_location("tone_eval_impl", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def flatten(value, prefix=""):
    result = {}
    if isinstance(value, dict):
        for key, child in value.items():
            result.update(flatten(child, f"{prefix}.{key}" if prefix else key))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            result.update(flatten(child, f"{prefix}.{i}"))
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        result[prefix] = value
    return result


def bucket_of(path):
    match = re.search(r"bucket_(\d+)", str(path))
    return int(match[1]) if match else None


def epoch_of(bucket):
    return "unknown" if bucket is None else "1-10" if bucket <= 10 else "11-33" if bucket <= 33 else "34+"


def select_paths(root, limit=4002, seed=20261003):
    groups = {}
    for path in sorted(root.rglob("*.png")):
        groups.setdefault(epoch_of(bucket_of(path)), []).append(path)
    if not limit:
        return sorted(p for group in groups.values() for p in group)
    rng = np.random.default_rng(seed)
    selected = []
    # Round robin avoids silently underfilling when one stratum is small.
    queues = [list(rng.permutation(len(group))) for group in groups.values()]
    values = list(groups.values())
    while len(selected) < limit and any(queues):
        for group, queue in zip(values, queues):
            if queue and len(selected) < limit:
                selected.append(group[queue.pop()])
    return selected


def metadata(path):
    with Image.open(path) as im:
        try:
            comment = json.loads(im.info.get("Comment", "{}"))
        except (ValueError, TypeError):
            comment = {}
        if not isinstance(comment, dict):
            comment = {}
        prompt = comment.get("prompt") or im.info.get("Description", "")
        artist = re.search(r"artist:(.*?)(?=::|,|$)", prompt)
        template = re.sub(r"artist:.*?(?=::|,|$)", "artist:X", prompt)
        bucket = bucket_of(path)
        return {"artist": artist[1].strip() if artist else None, "bucket": bucket,
                "seed": comment.get("seed"), "prompt_epoch": epoch_of(bucket),
                "prompt_template": template, "prompt": prompt,
                "prompt_form": "weighted" if re.search(r"[\d.]::artist:", prompt) else
                               "hand_up" if "hand up" in prompt else "original"}


_MODULE = None


def init_worker(module):
    global _MODULE
    _MODULE = load_module(module)


def measure_one(task):
    path, max_side = task
    try:
        meta = metadata(path)
        start = time.perf_counter()
        result = _MODULE.inspect_image(path, max_side=max_side)
        return {"path": str(path), **meta, "elapsed_ms": (time.perf_counter() - start) * 1000,
                "result": result}
    except Exception as exc:
        return {"path": str(path), "error": f"{type(exc).__name__}: {exc}"}


def read_rows(path):
    rows = []
    if path.exists():
        with path.open(encoding="utf-8") as stream:
            for number, line in enumerate(stream, 1):
                try:
                    rows.append(json.loads(line))
                except ValueError as exc:
                    raise ValueError(f"Invalid JSONL line {number}; preserve file and repair trailing line before resume") from exc
    return rows


def outside_input(output, root):
    if output.resolve().is_relative_to(root.resolve()):
        raise ValueError("Output must be outside the read-only input tree")


def measure(args):
    root, output = args.root.resolve(), args.output.resolve()
    outside_input(output, root)
    paths = select_paths(root, args.limit, args.seed)
    if not paths:
        raise ValueError("No PNG inputs")
    manifest_path = output.with_suffix(output.suffix + ".manifest.json")
    manifest = {"root": str(root), "limit": args.limit, "seed": args.seed, "max_side": args.max_side,
                "module_sha256": hashlib.sha256(args.module.read_bytes()).hexdigest(),
                "paths": [str(p) for p in paths], "numpy": np.__version__}
    output.parent.mkdir(parents=True, exist_ok=True)
    if manifest_path.exists():
        if json.loads(manifest_path.read_text(encoding="utf-8")) != manifest:
            raise ValueError("Resume configuration/source/input selection changed; use a new output")
    else:
        if output.exists():
            raise ValueError("Existing output has no manifest")
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    previous = read_rows(output)
    if output.exists() and output.stat().st_size:
        with output.open("rb") as stream:
            stream.seek(-1, 2)
            if stream.read(1) != b"\n":
                raise ValueError("JSONL must end with a newline before resume")
    done = {row["path"] for row in previous if "result" in row}
    tasks = [(p, args.max_side) for p in paths if str(p) not in done]
    with ProcessPoolExecutor(max_workers=args.workers, initializer=init_worker,
                             initargs=(str(args.module),)) as pool, output.open("a", encoding="utf-8", newline="\n") as stream:
        for index, row in enumerate(pool.map(measure_one, tasks, chunksize=1), 1):
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
            stream.flush()
            if index % 100 == 0:
                print(f"{len(done)+index}/{len(paths)}", flush=True)
    print(json.dumps({"output": str(output), "selected": len(paths), "resumed": len(done)}))


def summarize(args):
    # A retry supersedes an earlier error, without counting the image twice.
    rows = list({r["path"]: r for r in read_rows(args.input)}.values())
    errors = [r for r in rows if "result" not in r]
    rows = [r for r in rows if "result" in r]
    if not rows:
        raise ValueError("No successful measurements")
    flat = [flatten(row["result"]) for row in rows]
    keys = sorted(set.intersection(*(set(r) for r in flat)))
    # Fixed descriptors and positional palette/hue ranks are inappropriate correlations.
    metrics = [key for key in keys if not key.startswith(("image.", "palette.", "hue.bins.", "hue.dominant.", "regions.box."))]
    groups = {"all_balanced_sample": list(range(len(rows)))}
    for i, row in enumerate(rows):
        # Bucket boundaries are only an approximation. PNG prompt content wins.
        groups.setdefault(row["prompt_form"], []).append(i)
    report = {"count": len(rows), "errors": errors, "groups": {}, "correlations": {}, "tails": {},
              "no_line_samples": sum(r["result"]["lines"]["samples"] == 0 for r in rows),
              "bucket_prompt_mismatches": [r["path"] for r in rows
                  if {"1-10": "original", "11-33": "hand_up", "34+": "weighted"}.get(r["prompt_epoch"])
                  not in (None, r["prompt_form"])],
              "prompt_templates": sorted({r["prompt_template"] for r in rows})}
    for group, indices in groups.items():
        matrix = np.array([[flat[i][key] for key in metrics] for i in indices])
        report["groups"][group] = {"n": len(indices), "percentiles": {
            key: dict(zip(map(str, PERCENTILES), np.percentile(matrix[:, j], PERCENTILES).tolist()))
            for j, key in enumerate(metrics)}}
        pairs = []
        for j, first in enumerate(metrics):
            for k in range(j + 1, len(metrics)):
                if np.ptp(matrix[:, j]) == 0 or np.ptp(matrix[:, k]) == 0:
                    continue
                corr = float(spearmanr(matrix[:, j], matrix[:, k]).statistic)
                pairs.append({"a": first, "b": metrics[k], "rho": corr})
        report["correlations"][group] = sorted(pairs, key=lambda p: -abs(p["rho"]))
    for key in metrics:
        order = sorted(range(len(rows)), key=lambda i: flat[i][key])
        report["tails"][key] = {}
        for side, indices in (("low", order[:30]), ("high", order[-30:][::-1])):
            entries = [{"path": rows[i]["path"], "artist": rows[i]["artist"],
                        "epoch": rows[i]["prompt_epoch"], "value": flat[i][key],
                        "review": "unreviewed"} for i in indices]
            report["tails"][key][side] = entries
            if args.galleries and key in TAIL_METRICS:
                args.galleries.mkdir(parents=True, exist_ok=True)
                canvas = Image.new("RGB", (6 * 176, 5 * 224), "white")
                draw = ImageDraw.Draw(canvas)
                for n, entry in enumerate(entries):
                    x, y = (n % 6) * 176, (n // 6) * 224
                    with Image.open(entry["path"]) as im:
                        thumb = im.convert("RGB")
                        thumb.thumbnail((172, 190))
                        canvas.paste(thumb, (x, y))
                    draw.text((x + 2, y + 192), f"{n+1} {entry['value']:.3f} e{entry['epoch']}", fill="black")
                    label = (entry["artist"] or "unknown").encode("ascii", "replace").decode()[:25]
                    draw.text((x + 2, y + 207), label, fill="black")
                canvas.save(args.galleries / f"{key}_{side}.jpg")
    report["elapsed_ms"] = dict(zip(("p50", "p95"), np.percentile([r["elapsed_ms"] for r in rows], [50, 95]).tolist()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"count": len(rows), "errors": len(errors), "output": str(args.output)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("measure")
    p.add_argument("root", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--module", type=Path, default=DEFAULT_MODULE)
    p.add_argument("--limit", type=int, default=4002, help="0 = all (explicit opt-in)")
    p.add_argument("--seed", type=int, default=20261003)
    p.add_argument("--workers", type=int, choices=range(1, 5), default=2)
    p.add_argument("--max-side", type=int, default=1280)
    p.set_defaults(run=measure)
    p = sub.add_parser("summarize")
    p.add_argument("input", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--galleries", type=Path)
    p.set_defaults(run=summarize)
    args = parser.parse_args()
    if getattr(args, "limit", 0) < 0 or getattr(args, "max_side", 0) < 0:
        parser.error("limit/max-side must be nonnegative")
    args.run(args)


if __name__ == "__main__":
    main()
