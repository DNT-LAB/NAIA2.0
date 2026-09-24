"""Build data/danbooru_tag_counts_by_rating.json from tags_*.parquet.

Default scope is the user-facing autocomplete corpus plus the keys that already
exist in the current rating-count file. This closes visible count gaps without
shipping every obscure archive-only tag.

Counting (2026-09-24): files are read with pyarrow in parallel threads - each file's
tag columns are split on "," and paired with the row's rating, counted per file, then
merged; tag keys go through the same normalize_tag_key as before. 175 files: about
7 minutes (pandas, one file at a time) -> tens of seconds. A post id that appears in
more than one file is counted once (the later file wins, like search's _dedup_by_id);
--keep-duplicates restores the old behaviour.

    python tools/build_danbooru_tag_counts_by_rating.py --archive-tags "%APPDATA%/NAIA/data/tags" \
        --archive-label "runtime tag archive (data/tags)"
"""

from __future__ import annotations

import argparse
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any

try:
    from tools.audit_tag_assets import (
        RATING_ORDER,
        SCRIPT_REPO_ROOT,
        TAG_COLUMNS,
        _coerce_int,
        _ensure_repo_import,
        _load_rating_counts,
        _normalize_display_tag,
        _normalize_tag_key,
        _sort_key,
    )
except ModuleNotFoundError:  # pragma: no cover - script execution fallback.
    from audit_tag_assets import (  # type: ignore
        RATING_ORDER,
        SCRIPT_REPO_ROOT,
        TAG_COLUMNS,
        _coerce_int,
        _ensure_repo_import,
        _load_rating_counts,
        _normalize_display_tag,
        _normalize_tag_key,
        _sort_key,
    )


def _keep_masks(files: list[Path], workers: int) -> tuple[list[Any], int]:
    """Per-file row masks keeping each post id once (the latest file wins). None = keep all."""
    import numpy as np
    import pyarrow.parquet as pq

    with ThreadPoolExecutor(workers) as ex:
        ids = list(ex.map(lambda p: pq.read_table(p, columns=["id"])["id"].to_numpy(zero_copy_only=False), files))
    if not ids:
        return [], 0
    all_ids = np.concatenate(ids)
    _, first_from_end = np.unique(all_ids[::-1], return_index=True)
    keep = np.zeros(len(all_ids), dtype=bool)
    keep[len(all_ids) - 1 - first_from_end] = True
    masks: list[Any] = []
    offset = 0
    for arr in ids:
        part = keep[offset:offset + len(arr)]
        masks.append(None if part.all() else part)
        offset += len(arr)
    return masks, int(len(all_ids) - keep.sum())


def _count_file(path: Path, mask: Any):
    """(rows, rating_counts, raw (tag, rating) counts) for one file - tags as written, trimmed."""
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    names = set(pq.ParquetFile(path).schema_arrow.names)
    columns = [c for c in TAG_COLUMNS if c in names]
    table = pq.read_table(path, columns=[*columns, "rating"])
    if mask is not None:
        table = table.filter(pa.array(mask))
    rating = pc.cast(table["rating"], pa.string())
    parts = []
    for column in columns:
        lists = pc.split_pattern(pc.fill_null(pc.cast(table[column], pa.string()), ""), ",")
        parts.append(pa.table({
            "tag": pc.utf8_trim_whitespace(pc.list_flatten(lists)),
            "rating": pc.take(rating, pc.list_parent_indices(lists)),
        }))
    flat = pa.concat_tables(parts) if parts else pa.table({"tag": pa.array([], pa.string()), "rating": pa.array([], pa.string())})
    flat = flat.filter(pc.and_(pc.not_equal(flat["tag"], ""), pc.not_equal(pc.utf8_lower(flat["tag"]), "nan")))
    grouped = flat.group_by(["tag", "rating"]).aggregate([([], "count_all")])
    posts = {str(k): int(v) for k, v in zip(*pc.value_counts(rating.drop_null()).flatten())} \
        if table.num_rows else {}
    return table.num_rows, posts, grouped


def _fast_archive_counts(
    archive_root: Path,
    *,
    max_files: int | None,
    workers: int | None = None,
    dedupe: bool = True,
) -> tuple[set[str], dict[str, list[int]], dict[str, Any]]:
    """Archive tag x rating counts. Returns (all tag keys, {key: [g, s, q, e]}, summary)."""
    import pyarrow as pa

    files = sorted(archive_root.glob("tags_*.parquet"), key=_sort_key)
    if max_files is not None:
        files = files[:max_files]
    workers = workers or os.cpu_count() or 4
    masks, duplicates = _keep_masks(files, workers) if dedupe else ([None] * len(files), 0)
    with ThreadPoolExecutor(workers) as ex:
        results = list(ex.map(lambda fm: _count_file(*fm), zip(files, masks)))

    merged = pa.concat_tables([r[2] for r in results]).group_by(["tag", "rating"]).aggregate(
        [("count_all", "sum")]) if results else None
    rating_index = {rating: idx for idx, rating in enumerate(RATING_ORDER)}
    key_cache: dict[str, str] = {}
    all_keys: set[str] = set()
    rating_counts: dict[str, list[int]] = {}
    if merged is not None:
        for tag, rating, count in zip(merged["tag"].to_pylist(), merged["rating"].to_pylist(),
                                      merged["count_all_sum"].to_pylist()):
            key = key_cache.get(tag)
            if key is None:
                key = key_cache[tag] = _normalize_tag_key(tag)
            if not key:
                continue
            all_keys.add(key)
            idx = rating_index.get(rating)
            if idx is None:
                continue
            rating_counts.setdefault(key, [0, 0, 0, 0])[idx] += int(count)

    post_rating_counts: dict[str, int] = {}
    for _, posts, _ in results:
        for rating, n in posts.items():
            post_rating_counts[rating] = post_rating_counts.get(rating, 0) + n
    summary = {
        "file_count": len(files),
        "total_rows": sum(r[0] for r in results),
        "duplicate_rows_skipped": duplicates,
        "post_rating_counts": dict(sorted(post_rating_counts.items())),
        "unique_tags_total": len(all_keys),
    }
    return all_keys, rating_counts, summary


def _load_current_payload(path: Path) -> tuple[dict[str, list[int]], dict[str, str]]:
    if not path.exists():
        return {}, {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}, {}
    counts: dict[str, list[int]] = {}
    display: dict[str, str] = {}
    for raw_tag, value in payload.items():
        if raw_tag == "_meta":
            continue
        key = _normalize_tag_key(raw_tag)
        if isinstance(value, list):
            counts[key] = [_coerce_int(item) for item in value[: len(RATING_ORDER)]]
            display[key] = str(raw_tag)
    return counts, display


def _load_autocomplete_keys(repo_root: Path) -> tuple[set[str], dict[str, str], int]:
    _ensure_repo_import(repo_root)
    from core.kr_tag_loader import load_kr_tag_records

    result = load_kr_tag_records(repo_root, data_roots=[repo_root / "data"])
    keys: set[str] = set()
    display: dict[str, str] = {}
    for key, record in result.raw.items():
        tag = str(record.get("_tag") or key)
        normalized = _normalize_tag_key(tag)
        keys.add(normalized)
        display.setdefault(normalized, _normalize_display_tag(tag))
    return keys, display, len(result.raw)


def _rating_totals(post_rating_counts: dict[str, int]) -> list[int]:
    return [_coerce_int(post_rating_counts.get(rating, 0)) for rating in RATING_ORDER]


def build(
    *,
    repo_root: Path,
    archive_root: Path,
    out_path: Path,
    scope: str,
    include_current_missing: bool,
    dry_run: bool,
    max_files: int | None,
    archive_label: str | None = None,
    workers: int | None = None,
    dedupe: bool = True,
) -> dict[str, Any]:
    _ensure_repo_import(repo_root)
    current_counts, current_display = _load_current_payload(out_path)
    current_count_totals, _, current_summary = _load_rating_counts(out_path)
    autocomplete_keys, autocomplete_display, autocomplete_rows = _load_autocomplete_keys(repo_root)

    archive_counts, archive_rating_counts, archive_summary = _fast_archive_counts(
        archive_root,
        max_files=max_files,
        workers=workers,
        dedupe=dedupe,
    )

    if scope == "all":
        target_keys = set(archive_rating_counts)
    elif scope == "current":
        target_keys = set(current_counts)
    else:
        target_keys = set(autocomplete_keys)
        target_keys.update(current_counts)

    output_records: dict[str, list[int]] = {}
    archive_records = 0
    preserved_current_records = 0
    skipped_without_counts = 0
    for key in sorted(target_keys):
        counts = archive_rating_counts.get(key)
        if counts and sum(counts) > 0:
            output_records[key] = [_coerce_int(item) for item in counts[: len(RATING_ORDER)]]
            archive_records += 1
            continue
        if include_current_missing and key in current_counts and sum(current_counts[key]) > 0:
            output_records[key] = current_counts[key]
            preserved_current_records += 1
            continue
        skipped_without_counts += 1

    output_payload: OrderedDict[str, Any] = OrderedDict()
    output_payload["_meta"] = {
        "partition_order": list(RATING_ORDER),
        "total_posts": _rating_totals(archive_summary.get("post_rating_counts", {})),
        "num_tags": len(output_records),
        "source": f"{archive_label or archive_root}\\tags_00~{archive_summary.get('file_count', 0) - 1:02d}.parquet",
        "scope": scope,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "archive_tags_root": archive_label or str(archive_root.resolve()),
        "archive_file_count": archive_summary.get("file_count", 0),
        "archive_total_rows": archive_summary.get("total_rows", 0),
        "archive_duplicate_rows_skipped": archive_summary.get("duplicate_rows_skipped", 0),
        "archive_unique_tags": archive_summary.get("unique_tags_total", 0),
        "sampled": max_files is not None,
        "autocomplete_rows": autocomplete_rows,
        "current_source_records": current_summary.get("records", len(current_count_totals)),
        "archive_records": archive_records,
        "preserved_current_records": preserved_current_records,
        "skipped_without_counts": skipped_without_counts,
    }

    for key, counts in output_records.items():
        display = autocomplete_display.get(key) or current_display.get(key) or key
        output_payload[display] = counts

    if not dry_run:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(output_payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    recoverable_autocomplete = sum(1 for key in autocomplete_keys if key in archive_counts)
    return {
        "out_path": str(out_path),
        "dry_run": dry_run,
        "scope": scope,
        "records": len(output_records),
        "archive_records": archive_records,
        "preserved_current_records": preserved_current_records,
        "skipped_without_counts": skipped_without_counts,
        "archive_unique_tags": archive_summary.get("unique_tags_total", 0),
        "autocomplete_rows": autocomplete_rows,
        "autocomplete_keys_with_archive_counts": recoverable_autocomplete,
        "current_records": current_summary.get("records", len(current_count_totals)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Danbooru rating-count tag distribution JSON.")
    parser.add_argument("--repo-root", default=str(SCRIPT_REPO_ROOT), help="NAIA checkout root.")
    parser.add_argument(
        "--archive-tags",
        default=r"C:\VNR\NAIA2.0\data\tags",
        help="Directory containing tags_*.parquet post tag archive files.",
    )
    parser.add_argument(
        "--out",
        default=str(SCRIPT_REPO_ROOT / "data" / "danbooru_tag_counts_by_rating.json"),
        help="Output JSON path.",
    )
    parser.add_argument(
        "--scope",
        choices=("autocomplete", "current", "all"),
        default="autocomplete",
        help="Which tags to write. Default keeps autocomplete-visible tags plus existing keys.",
    )
    parser.add_argument(
        "--drop-current-missing",
        action="store_true",
        help="Do not preserve existing count records missing from the archive.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Compute counts and print summary without writing.")
    parser.add_argument("--max-files", type=int, default=None, help="Limit archive parquet files for validation runs.")
    # 배포 파일(_meta)에 사용자 PC 경로(계정 이름이 든 %APPDATA%)를 적지 않으려고 쓴다.
    parser.add_argument("--workers", type=int, default=None, help="Parallel reader threads (default: CPU count).")
    parser.add_argument("--keep-duplicates", action="store_true",
                        help="Count a post id every time it appears (old behaviour) instead of once.")
    parser.add_argument("--archive-label", default=None,
                        help="Label written to _meta instead of the absolute archive path.")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    archive_root = Path(args.archive_tags).resolve()
    out_path = Path(args.out).resolve()
    if not archive_root.exists():
        raise SystemExit(f"archive tag directory not found: {archive_root}")

    summary = build(
        repo_root=repo_root,
        archive_root=archive_root,
        out_path=out_path,
        scope=args.scope,
        include_current_missing=not args.drop_current_missing,
        dry_run=args.dry_run,
        max_files=args.max_files,
        archive_label=args.archive_label,
        workers=args.workers,
        dedupe=not args.keep_duplicates,
    )
    json.dump(summary, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
