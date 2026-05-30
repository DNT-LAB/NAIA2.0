"""Build data/tag_bucket_dates.json — the per-bucket (id range -> YYYY/MM date)
map that powers the search date-cutoff slider.

For each tags_NN.parquet in data/tags, record its id range, then resolve those
ids to created_at dates using the fuller Danbooru dump in .experimental/
output_part_*.parquet (dev-only, NOT shipped). Only the resulting small JSON is
committed/bundled.

Usage:
    python tools/build_tag_bucket_dates.py [--tags DIR] [--dates DIR] [--out FILE]

Re-run whenever the tag archive (data/tags) is updated.
"""
from __future__ import annotations

import argparse
import bisect
import json
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent


def _sort_key(path: Path):
    try:
        return (int(path.stem.split("_", 1)[1]), path.name)
    except (IndexError, ValueError):
        return (10**9, path.name)


def build(tags_dir: Path, dates_dir: Path, out_path: Path) -> None:
    tag_files = sorted(tags_dir.glob("tags_*.parquet"), key=_sort_key)
    if not tag_files:
        raise SystemExit(f"no tags_*.parquet found under {tags_dir}")
    print(f"tag buckets: {len(tag_files)}")

    buckets = []
    for i, fp in enumerate(tag_files):
        ids = pd.read_parquet(fp, columns=["id"], engine="pyarrow")["id"]
        buckets.append({
            "bucket": i,
            "file": fp.name,
            "min_id": int(ids.min()),
            "max_id": int(ids.max()),
            "rows": int(len(ids)),
        })

    parts = sorted(dates_dir.glob("output_part_*.parquet"), key=_sort_key)
    if not parts:
        raise SystemExit(f"no output_part_*.parquet found under {dates_dir}")
    print(f"date-source parts: {len(parts)}")
    frames = [pd.read_parquet(p, columns=["id", "created_at"], engine="pyarrow") for p in parts]
    alld = pd.concat(frames, ignore_index=True).dropna(subset=["id", "created_at"])
    alld = alld.drop_duplicates(subset=["id"])
    alld["id"] = alld["id"].astype("int64")
    alld = alld.sort_values("id").reset_index(drop=True)
    ids_sorted = alld["id"].to_numpy()
    dates_sorted = alld["created_at"].astype(str).to_numpy()
    print(f"date lookup rows: {len(ids_sorted):,}")

    def ym_for(target_id: int) -> str:
        j = bisect.bisect_right(ids_sorted, target_id) - 1
        if j < 0:
            j = 0
        return str(dates_sorted[j])[:7].replace("-", "/")  # 'YYYY-MM-..' -> 'YYYY/MM'

    for b in buckets:
        b["start_ym"] = ym_for(b["min_id"])
        b["end_ym"] = ym_for(b["max_id"])

    payload = {
        "version": 1,
        "bucket_count": len(buckets),
        "buckets": buckets,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"wrote {out_path}  ({buckets[0]['start_ym']} -> {buckets[-1]['end_ym']})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tags", default=str(REPO / "data" / "tags"))
    ap.add_argument("--dates", default=r"C:\VNR\NAIA2.0\.experimental")
    ap.add_argument("--out", default=str(REPO / "data" / "tag_bucket_dates.json"))
    args = ap.parse_args()
    build(Path(args.tags), Path(args.dates), Path(args.out))


if __name__ == "__main__":
    main()
