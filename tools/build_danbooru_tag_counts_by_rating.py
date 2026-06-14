"""Build data/danbooru_tag_counts_by_rating.json from tags_*.parquet.

Default scope is the user-facing autocomplete corpus plus the keys that already
exist in the current rating-count file. This closes visible count gaps without
shipping every obscure archive-only tag.
"""

from __future__ import annotations

import argparse
from collections import OrderedDict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

try:
    from tools.audit_tag_assets import (
        RATING_ORDER,
        SCRIPT_REPO_ROOT,
        _archive_counts,
        _coerce_int,
        _ensure_repo_import,
        _load_rating_counts,
        _normalize_display_tag,
        _normalize_tag_key,
    )
except ModuleNotFoundError:  # pragma: no cover - script execution fallback.
    from audit_tag_assets import (  # type: ignore
        RATING_ORDER,
        SCRIPT_REPO_ROOT,
        _archive_counts,
        _coerce_int,
        _ensure_repo_import,
        _load_rating_counts,
        _normalize_display_tag,
        _normalize_tag_key,
    )


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
) -> dict[str, Any]:
    _ensure_repo_import(repo_root)
    current_counts, current_display = _load_current_payload(out_path)
    current_count_totals, _, current_summary = _load_rating_counts(out_path)
    autocomplete_keys, autocomplete_display, autocomplete_rows = _load_autocomplete_keys(repo_root)

    archive_counts, _, archive_rating_counts, _, archive_summary = _archive_counts(
        archive_root,
        max_files=max_files,
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
        "source": f"{archive_root}\\tags_00~{archive_summary.get('file_count', 0) - 1:02d}.parquet",
        "scope": scope,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "archive_tags_root": str(archive_root.resolve()),
        "archive_file_count": archive_summary.get("file_count", 0),
        "archive_total_rows": archive_summary.get("total_rows", 0),
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
    )
    json.dump(summary, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
