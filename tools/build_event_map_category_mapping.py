"""Build a reviewable category sidecar; never modify the index or runtime sources.

Run with explicit --index, --parquet, --csv and --output paths. The CSV has no
header; its fourth column starts with [category > subcategory] when classified.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.event_map.categories import FOLD_PATH, fold_category, groups, split_category
from core.event_map.index import EventMapIndex

UNCLASSIFIED = {"", "일반", "기타", "미분류", "[미분류]", "분류 불가", "분류불가", "복합"}


def meaningful(category: str) -> bool:
    return category.strip() not in UNCLASSIFIED


def category_key(category: str) -> tuple[str, ...]:
    return tuple(" ".join(part.split()).casefold() for part in category.split(">"))


def source_info(path: Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": str(path.resolve()), "bytes": path.stat().st_size,
            "sha256": digest.hexdigest()}


def entry(current: str | None, proposed: str | None) -> dict:
    old, new = current or "", proposed or ""
    changed = bool(old and new and category_key(old) != category_key(new))
    flags = ["category_changed"] if changed else []
    if old and proposed is not None and not new:
        flags.append("csv_category_missing")
    if meaningful(old):
        category, source = old, "parquet"
        if changed:
            status = "conflict"
        elif current is not None and proposed is not None and meaningful(new):
            status = "unchanged"
        else:
            status = "existing_only"
    elif meaningful(new):
        category, source, status = new, "csv", "filled_from_csv"
    else:
        category, source, status = "", None, "unclassified"

    top, sub = split_category(category)
    group = fold_category(category)[0] if category else "unsorted"
    pending = status == "conflict"
    if pending:
        flags.append("subcategory_review_required")
    if category and group == "unsorted":
        flags.append("group_unmapped")
    if not category:
        flags.append("unclassified")
    elif not sub and not pending:
        flags.append("subcategory_missing")
    return {
        "status": status,
        "flags": flags,
        "category_changed": changed,
        "current_category": current,
        "csv_category": proposed,
        "category": category or None,
        "source": source,
        "group": group,
        "top_category": top or None,
        # A changed category retains its old group but awaits subcategory review.
        "subcategory": None if pending else (sub or None),
        "subcategory_status": "pending_review" if pending else ("mapped" if sub else "missing"),
    }


def build(index_path: Path, parquet_path: Path, csv_path: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError(f"Refusing to replace an existing mapping: {output}")
    index = EventMapIndex(index_path)
    try:
        current: dict[str, str] = {}
        proposed: dict[str, str] = {}

        def put(target: dict, raw_tag: str, category: str) -> None:
            tid = index.resolve(raw_tag)
            if tid is None:
                return
            tag = index.by_id[tid]
            if tag in target and category_key(target[tag]) != category_key(category):
                raise ValueError(f"Conflicting source rows for {tag!r}")
            target[tag] = category

        frame = pd.read_parquet(parquet_path, columns=["tag", "category"]).fillna("")
        for tag, category in frame.itertuples(index=False, name=None):
            put(current, str(tag), str(category).strip())
        csv_rows = csv_classified = 0
        with csv_path.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.reader(stream):
                csv_rows += 1
                if len(row) != 4:
                    raise ValueError(f"CSV record {csv_rows}: expected four columns")
                match = re.match(r"^\s*\[([^\]]+)\]", row[3])
                category = match.group(1).strip() if match else ""
                csv_classified += bool(category)
                put(proposed, row[0], category)

        tags = {tag: entry(current.get(tag), proposed.get(tag))
                for tag in sorted(index.by_name)}
        summary = {
            "tags": len(tags),
            "parquet_rows": len(frame), "csv_rows": csv_rows,
            "csv_rows_with_category": csv_classified,
            "parquet_matched_tags": len(current), "csv_matched_tags": len(proposed),
            "status_counts": dict(Counter(row["status"] for row in tags.values())),
            "flag_counts": dict(Counter(flag for row in tags.values() for flag in row["flags"])),
            "subcategory_status_counts": dict(Counter(row["subcategory_status"] for row in tags.values())),
        }
        document = {
            "schema": "naia-event-map-category-mapping-v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "runtime_enabled": False,
            "scope": "All canonical tags in the specified naiamap; keyed by tag, not tag ID.",
            "policy": {
                "conflict": "Flag differing nonempty categories; retain existing category/group and defer subcategory assignment.",
                "fill": "Use a meaningful CSV category only when the existing category is absent or an explicit unclassified label.",
                "unclassified_labels": sorted(UNCLASSIFIED),
                "unmapped_group": "Retain meaningful source categories even when the existing 12-group fold cannot map them.",
                "subcategory": "Preserve the entire source path after the first >; never infer a missing subcategory.",
                "comparison": "Ignore whitespace around >, repeated whitespace, and case only.",
                "missing_source": "null means the tag is absent from that source; an empty string means a source row without a category.",
            },
            "sources": {"index": source_info(index_path), "parquet": source_info(parquet_path),
                        "csv": source_info(csv_path), "group_fold": source_info(FOLD_PATH)},
            "groups": groups(), "summary": summary, "tags": tags,
        }
        assert len(tags) == index.n_tags
        assert sum(summary["status_counts"].values()) == index.n_tags
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(document, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        return summary
    finally:
        index.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("index", "parquet", "csv", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.index, args.parquet, args.csv, args.output), ensure_ascii=False, indent=2))
