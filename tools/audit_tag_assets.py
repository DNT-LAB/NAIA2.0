"""Audit NAIA tag assets against the local Danbooru tag archive.

This tool is intentionally read-only. It inventories the tag-related assets
used by autocomplete/search and compares them with the post tag archive under
``data/tags`` or another archive directory.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import gzip
import importlib
import json
from pathlib import Path
import sys
from typing import Any, Iterable

import pandas as pd


SCRIPT_REPO_ROOT = Path(__file__).resolve().parents[1]
TAG_COLUMNS = ("general", "meta", "character", "copyright", "artist")
RATING_ORDER = ("g", "s", "q", "e")
RATING_INDEX = {rating: idx for idx, rating in enumerate(RATING_ORDER)}
TOP_LIMIT = 100

SOURCE_NAMES = {
    0: "interactive",
    1: "KR_tags.parquet",
    2: "e621_KR_tags.parquet",
    3: "characteristic_list.txt",
    4: "clothes_list.txt",
    5: "taglist/expression_tags.json",
    6: "taglist/pose_action_tags.json",
    7: "taglist/location_tags.json",
    8: "taglist/meta_tags.json",
    9: "taglist/object_tags.json",
    10: "color.txt",
    11: "artist_dictionary.py",
    12: "danbooru_character.py",
    13: "result_dict_copyright.py",
    20: "tag_translation_overrides.json",
}


def _ensure_repo_import(repo_root: Path) -> None:
    repo = str(repo_root)
    if repo not in sys.path:
        sys.path.insert(0, repo)


def _sort_key(path: Path) -> tuple[int, str]:
    try:
        return (int(path.stem.split("_", 1)[1]), path.name)
    except (IndexError, ValueError):
        return (10**9, path.name)


def _utc_mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _file_info(path: Path, root: Path, kind: str) -> dict[str, Any]:
    return {
        "path": _relative(path, root),
        "kind": kind,
        "bytes": path.stat().st_size,
        "modified_utc": _utc_mtime(path),
    }


def _parquet_info(path: Path, root: Path, kind: str) -> dict[str, Any]:
    info = _file_info(path, root, kind)
    try:
        import pyarrow.parquet as pq

        metadata = pq.ParquetFile(path)
        info.update(
            {
                "rows": metadata.metadata.num_rows,
                "row_groups": metadata.metadata.num_row_groups,
                "columns": list(metadata.schema.names),
            }
        )
    except Exception as exc:
        info["error"] = str(exc)
    return info


def _load_json(path: Path) -> Any:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _json_info(path: Path, root: Path, kind: str) -> dict[str, Any]:
    info = _file_info(path, root, kind)
    try:
        payload = _load_json(path)
        if isinstance(payload, dict):
            info["top_level_type"] = "object"
            info["top_level_count"] = len(payload)
            info["top_level_keys_sample"] = list(payload)[:12]
        elif isinstance(payload, list):
            info["top_level_type"] = "array"
            info["top_level_count"] = len(payload)
        else:
            info["top_level_type"] = type(payload).__name__
    except Exception as exc:
        info["error"] = str(exc)
    return info


def _line_count_info(path: Path, root: Path, kind: str) -> dict[str, Any]:
    info = _file_info(path, root, kind)
    try:
        with path.open("r", encoding="utf-8") as handle:
            info["line_count"] = sum(1 for line in handle if line.strip())
    except Exception as exc:
        info["error"] = str(exc)
    return info


def _normalize_tag_key(tag: Any) -> str:
    from core.tag_knowledge import normalize_tag_key

    return normalize_tag_key(tag)


def _normalize_display_tag(tag: Any) -> str:
    from core.tag_knowledge import normalize_display_tag

    return normalize_display_tag(tag)


def _coerce_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _sum_rating_value(value: Any) -> int:
    if isinstance(value, list):
        return sum(_coerce_int(item) for item in value)
    if isinstance(value, dict):
        return sum(_coerce_int(item) for item in value.values())
    return _coerce_int(value)


def _source_name(source_id: Any) -> str:
    try:
        return SOURCE_NAMES.get(int(source_id), str(source_id))
    except (TypeError, ValueError):
        return str(source_id)


def _split_tags(value: Any) -> list[str]:
    if value is None:
        return []
    text = str(value)
    if not text or text.lower() == "nan":
        return []
    return [_normalize_tag_key(part) for part in text.split(",") if part.strip()]


def _count_tokens(series: pd.Series) -> Counter[str]:
    if series.empty:
        return Counter()
    tokens = series.dropna().astype(str).str.split(",").explode().str.strip()
    tokens = tokens[tokens != ""]
    if tokens.empty:
        return Counter()
    normalized = tokens.map(_normalize_tag_key)
    return Counter({str(tag): int(count) for tag, count in normalized.value_counts().items()})


def _count_tokens_by_rating(series: pd.Series, ratings: pd.Series) -> tuple[Counter[str], dict[str, Counter[str]]]:
    if series.empty:
        return Counter(), {}
    frame = pd.DataFrame({"tag": series, "rating": ratings}).dropna(subset=["tag"])
    if frame.empty:
        return Counter(), {}
    frame["tag"] = frame["tag"].astype(str).str.split(",")
    frame = frame.explode("tag")
    frame["tag"] = frame["tag"].astype(str).str.strip()
    frame = frame[frame["tag"] != ""]
    if frame.empty:
        return Counter(), {}
    frame["tag"] = frame["tag"].map(_normalize_tag_key)

    total = Counter({str(tag): int(count) for tag, count in frame["tag"].value_counts().items()})
    by_rating: dict[str, Counter[str]] = {}
    grouped = frame.groupby(["rating", "tag"]).size()
    for (rating, tag), count in grouped.items():
        by_rating.setdefault(str(rating), Counter())[str(tag)] = int(count)
    return total, by_rating


def _top(counter: Counter[str], limit: int = TOP_LIMIT) -> list[dict[str, Any]]:
    return [{"tag": tag, "count": int(count)} for tag, count in counter.most_common(limit)]


def _inventory_assets(repo_root: Path, archive_root: Path | None) -> dict[str, Any]:
    data_root = repo_root / "data"
    inventory: dict[str, Any] = {
        "autocomplete_sources": [],
        "taglist": [],
        "tag_index": [],
        "archive": {},
        "event_and_search_assets": [],
        "dictionary_modules": [],
    }

    for relative, kind in [
        ("data/KR_tags.parquet", "autocomplete_parquet"),
        ("data/e621_KR_tags.parquet", "autocomplete_parquet"),
        ("data/danbooru_tag_counts_by_rating.json", "rating_count_json"),
        ("data/characteristic_list.txt", "filter_text"),
        ("data/clothes_list.txt", "filter_text"),
        ("data/color.txt", "filter_text"),
        ("data/character_analysis.json", "character_json"),
        ("data/copyright_groups.json", "copyright_json"),
        ("data/tag_bucket_dates.json", "archive_bucket_dates"),
        ("data/e621_data", "e621_data"),
        ("data/e621_boost_static.py", "e621_python"),
    ]:
        path = repo_root / relative
        if not path.exists():
            continue
        if path.suffix == ".parquet":
            inventory["autocomplete_sources"].append(_parquet_info(path, repo_root, kind))
        elif path.suffix in {".json", ".gz"}:
            inventory["autocomplete_sources"].append(_json_info(path, repo_root, kind))
        elif path.suffix == ".txt":
            inventory["autocomplete_sources"].append(_line_count_info(path, repo_root, kind))
        else:
            inventory["autocomplete_sources"].append(_file_info(path, repo_root, kind))

    for path in sorted((data_root / "taglist").glob("*")):
        if path.suffix == ".json":
            inventory["taglist"].append(_json_info(path, repo_root, "taglist_json"))
        elif path.is_file():
            inventory["taglist"].append(_file_info(path, repo_root, "taglist_asset"))

    for path in sorted((data_root / "tag_index").glob("*")):
        if path.suffix in {".json", ".gz"}:
            inventory["tag_index"].append(_json_info(path, repo_root, "tag_index_json"))
        elif path.is_file():
            inventory["tag_index"].append(_file_info(path, repo_root, "tag_index_asset"))

    for relative, kind in [
        ("data/NAIA_event_dataset_1girl_story.parquet", "event_dataset_parquet"),
        ("data/sequence_preset/naia_sequence_events_v1.parquet", "sequence_event_parquet"),
        ("data/ezmode/category_tags_index.json", "ezmode_json"),
        ("data/ezmode/category_tags_merged.json", "ezmode_json"),
        ("data/character_thumbnails/index.json", "character_thumbnail_index"),
    ]:
        path = repo_root / relative
        if not path.exists():
            continue
        if path.suffix == ".parquet":
            inventory["event_and_search_assets"].append(_parquet_info(path, repo_root, kind))
        elif path.suffix == ".json":
            inventory["event_and_search_assets"].append(_json_info(path, repo_root, kind))
        else:
            inventory["event_and_search_assets"].append(_file_info(path, repo_root, kind))

    for module_name in ("artist_dictionary.py", "danbooru_character.py", "result_dict_copyright.py"):
        path = repo_root / module_name
        if path.exists():
            inventory["dictionary_modules"].append(_file_info(path, repo_root, "python_tag_dictionary"))

    if archive_root and archive_root.exists():
        files = sorted(archive_root.glob("tags_*.parquet"), key=_sort_key)
        inventory["archive"] = {
            "root": str(archive_root.resolve()),
            "file_count": len(files),
            "bytes": sum(path.stat().st_size for path in files),
            "first_file": files[0].name if files else None,
            "last_file": files[-1].name if files else None,
            "schema_sample": _parquet_info(files[0], archive_root, "post_tag_archive") if files else None,
        }
    elif archive_root:
        inventory["archive"] = {"root": str(archive_root.resolve()), "missing": True}

    return inventory


def _load_rating_counts(path: Path) -> tuple[dict[str, int], dict[str, list[int]], dict[str, Any]]:
    if not path.exists():
        return {}, {}, {"missing": True, "path": str(path)}
    payload = _load_json(path)
    if not isinstance(payload, dict):
        return {}, {}, {"error": "expected object", "path": str(path)}

    counts: dict[str, int] = {}
    partitions: dict[str, list[int]] = {}
    for raw_tag, value in payload.items():
        if raw_tag == "_meta":
            continue
        tag = _normalize_tag_key(raw_tag)
        counts[tag] = _sum_rating_value(value)
        if isinstance(value, list):
            partitions[tag] = [_coerce_int(item) for item in value[: len(RATING_ORDER)]]

    return counts, partitions, {"path": str(path), "records": len(counts), "meta": payload.get("_meta", {})}


def _load_parquet_counts(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    df = pd.read_parquet(path, columns=["tag", "count", "category"], engine="pyarrow")
    records: dict[str, dict[str, Any]] = {}
    for row in df.itertuples(index=False):
        tag = _normalize_tag_key(getattr(row, "tag"))
        records[tag] = {
            "tag": _normalize_display_tag(getattr(row, "tag")),
            "count": _coerce_int(getattr(row, "count")),
            "category": str(getattr(row, "category") or ""),
        }
    return records


def _load_taglist_tags(repo_root: Path) -> dict[str, dict[str, Any]]:
    def collect_values(data: Any) -> list[str]:
        out: list[str] = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, str):
                    out.append(item)
                elif isinstance(item, dict):
                    tag = item.get("tag")
                    if isinstance(tag, str) and tag.strip():
                        out.append(tag)
                    else:
                        out.extend(collect_values(item))
                elif isinstance(item, list):
                    out.extend(collect_values(item))
        elif isinstance(data, dict):
            tag = data.get("tag")
            if isinstance(tag, str) and tag.strip():
                out.append(tag)
            for key, value in data.items():
                if key in {"version", "description", "tag", "garment_noun", "region", "unassigned_region"}:
                    continue
                if key == "style_thumbnails":
                    continue
                if isinstance(value, (list, dict)):
                    out.extend(collect_values(value))
        return out

    tags: dict[str, dict[str, Any]] = {}
    for path in sorted((repo_root / "data" / "taglist").glob("*.json")):
        try:
            for raw_tag in collect_values(_load_json(path)):
                tag = _normalize_display_tag(str(raw_tag).replace("_", " "))
                tags.setdefault(
                    _normalize_tag_key(tag),
                    {"tag": tag, "files": [], "count": 0},
                )
                tags[_normalize_tag_key(tag)]["files"].append(path.name)
                tags[_normalize_tag_key(tag)]["count"] += 1
        except Exception:
            continue
    for path in [
        repo_root / "data" / "characteristic_list.txt",
        repo_root / "data" / "clothes_list.txt",
        repo_root / "data" / "color.txt",
    ]:
        if not path.exists():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            tag = _normalize_display_tag(raw.replace("_", " "))
            tags.setdefault(_normalize_tag_key(tag), {"tag": tag, "files": [], "count": 0})
            tags[_normalize_tag_key(tag)]["files"].append(path.name)
            tags[_normalize_tag_key(tag)]["count"] += 1
    return tags


def _load_interactive(path: Path | None) -> dict[str, dict[str, Any]]:
    if not path or not path.exists():
        return {}
    payload = _load_json(path)
    if not isinstance(payload, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for raw_tag, info in payload.items():
        if not isinstance(info, dict):
            continue
        tag = _normalize_display_tag(raw_tag)
        out[_normalize_tag_key(tag)] = {
            "tag": tag,
            "freq": _coerce_int(info.get("freq", 0)),
            "group": str(info.get("group", "") or ""),
            "subgroup": str(info.get("subgroup", "") or ""),
        }
    return out


def _load_dictionary_counts(repo_root: Path) -> dict[str, int]:
    _ensure_repo_import(repo_root)
    total: dict[str, int] = {}
    for module_name, variable_name in [
        ("artist_dictionary", "artist_dict"),
        ("danbooru_character", "character_dict_count"),
        ("result_dict_copyright", "copyright_dict"),
    ]:
        try:
            module = importlib.import_module(module_name)
            records = getattr(module, variable_name, {})
        except Exception:
            continue
        if not isinstance(records, dict):
            continue
        for raw_tag, count in records.items():
            total[_normalize_tag_key(raw_tag)] = _coerce_int(count)
    return total


def _load_autocomplete(repo_root: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    _ensure_repo_import(repo_root)
    from core.kr_tag_loader import format_kr_tag_load_summary, load_kr_tag_records

    result = load_kr_tag_records(repo_root, data_roots=[repo_root / "data"])
    raw = result.raw
    source_counts = Counter(_source_name(record.get("_src")) for record in raw.values())
    zero_by_source = Counter(
        _source_name(record.get("_src"))
        for record in raw.values()
        if _coerce_int(record.get("freq", record.get("count", 0))) <= 0
    )
    summary = {
        "summary": format_kr_tag_load_summary(result),
        "total": len(raw),
        "zero_count_rows": sum(
            1 for record in raw.values() if _coerce_int(record.get("freq", record.get("count", 0))) <= 0
        ),
        "source_counts": dict(sorted(source_counts.items())),
        "zero_count_by_source": dict(sorted(zero_by_source.items())),
        "warnings": result.warnings,
    }
    return raw, summary


def _archive_counts(
    archive_root: Path,
    *,
    max_files: int | None,
) -> tuple[Counter[str], dict[str, Counter[str]], dict[str, list[int]], dict[str, str], dict[str, Any]]:
    files = sorted(archive_root.glob("tags_*.parquet"), key=_sort_key)
    if max_files is not None:
        files = files[:max_files]

    all_counts: Counter[str] = Counter()
    category_counts = {column: Counter() for column in TAG_COLUMNS}
    rating_counts: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    first_category: dict[str, str] = {}
    post_rating_counts: Counter[str] = Counter()
    total_rows = 0
    id_min: int | None = None
    id_max: int | None = None
    created_min: str | None = None
    created_max: str | None = None
    missing_columns: Counter[str] = Counter()

    for idx, path in enumerate(files, start=1):
        df = pd.read_parquet(
            path,
            columns=["id", "created_at", "rating", *TAG_COLUMNS],
            engine="pyarrow",
        )
        total_rows += int(len(df))
        if "id" in df:
            ids = df["id"].dropna()
            if not ids.empty:
                low = int(ids.min())
                high = int(ids.max())
                id_min = low if id_min is None else min(id_min, low)
                id_max = high if id_max is None else max(id_max, high)
        if "created_at" in df:
            dates = df["created_at"].dropna().astype(str)
            if not dates.empty:
                low_s = str(dates.min())
                high_s = str(dates.max())
                created_min = low_s if created_min is None else min(created_min, low_s)
                created_max = high_s if created_max is None else max(created_max, high_s)
        if "rating" in df:
            post_rating_counts.update(str(value) for value in df["rating"].dropna())

        for column in TAG_COLUMNS:
            if column not in df:
                missing_columns[column] += 1
                continue
            column_counts, rating_column_counts = _count_tokens_by_rating(df[column], df["rating"])
            category_counts[column].update(column_counts)
            all_counts.update(column_counts)
            for tag in column_counts:
                first_category.setdefault(tag, column)

            for rating, per_rating in rating_column_counts.items():
                if rating not in RATING_INDEX:
                    continue
                rating_index = RATING_INDEX[rating]
                for tag, count in per_rating.items():
                    rating_counts[tag][rating_index] += int(count)

        if idx % 10 == 0:
            print(f"processed {idx}/{len(files)} tag parquet files", file=sys.stderr)

    summary = {
        "root": str(archive_root.resolve()),
        "file_count": len(files),
        "total_rows": total_rows,
        "min_id": id_min,
        "max_id": id_max,
        "created_at_min": created_min,
        "created_at_max": created_max,
        "post_rating_counts": dict(sorted(post_rating_counts.items())),
        "unique_tags_total": len(all_counts),
        "unique_tags_by_column": {column: len(counter) for column, counter in category_counts.items()},
        "tag_assignments_by_column": {column: int(sum(counter.values())) for column, counter in category_counts.items()},
        "top_tags_by_column": {column: _top(counter, 30) for column, counter in category_counts.items()},
        "missing_columns": dict(missing_columns),
        "sampled": max_files is not None,
    }
    return all_counts, category_counts, dict(rating_counts), first_category, summary


def _record_count(record: dict[str, Any]) -> int:
    return _coerce_int(record.get("freq", record.get("count", 0)))


def _display_record_tag(key: str, record: dict[str, Any] | None = None) -> str:
    if record:
        return str(record.get("_tag") or record.get("tag") or key)
    return key


def _zero_rows_with_archive(
    raw: dict[str, dict[str, Any]],
    archive_counts: Counter[str],
    first_category: dict[str, str],
    limit: int = TOP_LIMIT,
) -> list[dict[str, Any]]:
    rows = []
    for key, record in raw.items():
        if _record_count(record) > 0:
            continue
        archive_count = int(archive_counts.get(key, 0))
        if archive_count <= 0:
            continue
        rows.append(
            {
                "tag": _display_record_tag(key, record),
                "autocomplete_source": _source_name(record.get("_src")),
                "group": str(record.get("group", "") or ""),
                "archive_category": first_category.get(key, ""),
                "archive_count": archive_count,
            }
        )
    rows.sort(key=lambda item: item["archive_count"], reverse=True)
    return rows[:limit]


def _top_missing_from_left(
    left_counts: Counter[str],
    right_keys: set[str],
    first_category: dict[str, str],
    limit: int = TOP_LIMIT,
) -> list[dict[str, Any]]:
    rows = [
        {"tag": tag, "archive_category": first_category.get(tag, ""), "archive_count": int(count)}
        for tag, count in left_counts.items()
        if count > 0 and tag not in right_keys
    ]
    rows.sort(key=lambda item: item["archive_count"], reverse=True)
    return rows[:limit]


def _rating_source_missing_archive_available(
    archive_counts: Counter[str],
    rating_counts: dict[str, int],
    first_category: dict[str, str],
    limit: int = TOP_LIMIT,
) -> list[dict[str, Any]]:
    rows = [
        {"tag": tag, "archive_category": first_category.get(tag, ""), "archive_count": int(count)}
        for tag, count in archive_counts.items()
        if count > 0 and tag not in rating_counts
    ]
    rows.sort(key=lambda item: item["archive_count"], reverse=True)
    return rows[:limit]


def _kr_zero_with_archive(
    kr_records: dict[str, dict[str, Any]],
    archive_counts: Counter[str],
    first_category: dict[str, str],
    limit: int = TOP_LIMIT,
) -> list[dict[str, Any]]:
    rows = []
    for key, record in kr_records.items():
        if _coerce_int(record.get("count", 0)) > 0:
            continue
        archive_count = int(archive_counts.get(key, 0))
        if archive_count <= 0:
            continue
        rows.append(
            {
                "tag": record.get("tag", key),
                "kr_category": record.get("category", ""),
                "archive_category": first_category.get(key, ""),
                "archive_count": archive_count,
            }
        )
    rows.sort(key=lambda item: item["archive_count"], reverse=True)
    return rows[:limit]


def _kr_count_deltas(
    kr_records: dict[str, dict[str, Any]],
    archive_counts: Counter[str],
    limit: int = TOP_LIMIT,
) -> list[dict[str, Any]]:
    rows = []
    for key, record in kr_records.items():
        kr_count = _coerce_int(record.get("count", 0))
        archive_count = int(archive_counts.get(key, 0))
        if kr_count <= 0 or archive_count <= 0:
            continue
        delta = archive_count - kr_count
        ratio = archive_count / kr_count if kr_count else None
        if abs(delta) < max(1000, kr_count * 0.25):
            continue
        rows.append(
            {
                "tag": record.get("tag", key),
                "kr_count": kr_count,
                "archive_count": archive_count,
                "delta": delta,
                "archive_to_kr_ratio": round(ratio, 3) if ratio is not None else None,
                "kr_category": record.get("category", ""),
            }
        )
    rows.sort(key=lambda item: abs(item["delta"]), reverse=True)
    return rows[:limit]


def _taglist_archive_gaps(
    taglist: dict[str, dict[str, Any]],
    archive_counts: Counter[str],
    first_category: dict[str, str],
    *,
    present: bool,
    limit: int = TOP_LIMIT,
) -> list[dict[str, Any]]:
    rows = []
    for key, record in taglist.items():
        archive_count = int(archive_counts.get(key, 0))
        if present and archive_count <= 0:
            continue
        if not present and archive_count > 0:
            continue
        rows.append(
            {
                "tag": record["tag"],
                "files": sorted(set(record["files"])),
                "archive_category": first_category.get(key, ""),
                "archive_count": archive_count,
            }
        )
    rows.sort(key=lambda item: item["archive_count"], reverse=True)
    return rows[:limit]


def _interactive_gaps(
    interactive: dict[str, dict[str, Any]],
    raw: dict[str, dict[str, Any]],
    archive_counts: Counter[str],
    limit: int = TOP_LIMIT,
) -> dict[str, Any]:
    missing = []
    positive_zero = []
    for key, record in interactive.items():
        raw_record = raw.get(key)
        if raw_record is None:
            missing.append(
                {
                    "tag": record["tag"],
                    "interactive_freq": int(record["freq"]),
                    "archive_count": int(archive_counts.get(key, 0)),
                    "group": record["group"],
                    "subgroup": record["subgroup"],
                }
            )
            continue
        if _record_count(raw_record) <= 0 and record["freq"] > 0:
            positive_zero.append(
                {
                    "tag": record["tag"],
                    "interactive_freq": int(record["freq"]),
                    "archive_count": int(archive_counts.get(key, 0)),
                    "autocomplete_source": _source_name(raw_record.get("_src")),
                    "group": record["group"],
                    "subgroup": record["subgroup"],
                }
            )
    missing.sort(key=lambda item: item["interactive_freq"], reverse=True)
    positive_zero.sort(key=lambda item: item["interactive_freq"], reverse=True)
    return {
        "interactive_records": len(interactive),
        "missing_from_autocomplete": len(missing),
        "positive_interactive_freq_but_autocomplete_zero": len(positive_zero),
        "top_missing_from_autocomplete": missing[:limit],
        "top_positive_freq_but_autocomplete_zero": positive_zero[:limit],
    }


def _build_report(
    repo_root: Path,
    archive_root: Path,
    interactive_path: Path | None,
    *,
    max_files: int | None,
) -> dict[str, Any]:
    _ensure_repo_import(repo_root)

    raw, autocomplete_summary = _load_autocomplete(repo_root)
    kr_records = _load_parquet_counts(repo_root / "data" / "KR_tags.parquet")
    e621_records = _load_parquet_counts(repo_root / "data" / "e621_KR_tags.parquet")
    rating_counts, rating_partitions, rating_summary = _load_rating_counts(
        repo_root / "data" / "danbooru_tag_counts_by_rating.json"
    )
    taglist = _load_taglist_tags(repo_root)
    interactive = _load_interactive(interactive_path)
    dictionary_counts = _load_dictionary_counts(repo_root)
    archive_counts, category_counts, archive_rating_counts, first_category, archive_summary = _archive_counts(
        archive_root,
        max_files=max_files,
    )

    raw_keys = set(raw)
    rating_keys = set(rating_counts)
    kr_keys = set(kr_records)
    taglist_keys = set(taglist)
    dictionary_keys = set(dictionary_counts)

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(repo_root.resolve()),
        "archive_root": str(archive_root.resolve()),
        "interactive_path": str(interactive_path.resolve()) if interactive_path and interactive_path.exists() else None,
        "asset_inventory": _inventory_assets(repo_root, archive_root),
        "autocomplete": autocomplete_summary,
        "kr_tags": {
            "records": len(kr_records),
            "zero_count_rows": sum(1 for record in kr_records.values() if _coerce_int(record.get("count", 0)) <= 0),
        },
        "e621_kr_tags": {
            "records": len(e621_records),
            "zero_count_rows": sum(1 for record in e621_records.values() if _coerce_int(record.get("count", 0)) <= 0),
        },
        "rating_count_source": rating_summary,
        "taglist": {"unique_tags": len(taglist), "files": sorted({file for row in taglist.values() for file in row["files"]})},
        "dictionary_modules": {"unique_tags": len(dictionary_counts)},
        "archive": archive_summary,
        "gaps": {
            "autocomplete_zero_with_archive_count": _zero_rows_with_archive(raw, archive_counts, first_category),
            "archive_top_missing_from_autocomplete": _top_missing_from_left(archive_counts, raw_keys, first_category),
            "archive_top_missing_from_rating_count_source": _rating_source_missing_archive_available(
                archive_counts,
                rating_counts,
                first_category,
            ),
            "kr_zero_with_archive_count": _kr_zero_with_archive(kr_records, archive_counts, first_category),
            "kr_count_delta_top": _kr_count_deltas(kr_records, archive_counts),
            "taglist_with_archive_count": _taglist_archive_gaps(taglist, archive_counts, first_category, present=True),
            "taglist_absent_from_archive": _taglist_archive_gaps(taglist, archive_counts, first_category, present=False),
            "archive_top_missing_from_kr_tags": _top_missing_from_left(archive_counts, kr_keys, first_category),
            "archive_top_missing_from_taglist": _top_missing_from_left(archive_counts, taglist_keys, first_category),
            "archive_top_missing_from_dictionary_modules": _top_missing_from_left(
                archive_counts,
                dictionary_keys,
                first_category,
            ),
        },
        "interactive": _interactive_gaps(interactive, raw, archive_counts) if interactive else {"records": 0},
        "derived_counts": {
            "archive_rating_count_records": len(archive_rating_counts),
            "current_rating_count_records": len(rating_counts),
            "rating_count_records_missing_archive_tags": len(set(archive_counts) - rating_keys),
            "autocomplete_zero_rows_recoverable_from_archive": sum(
                1 for key, record in raw.items() if _record_count(record) <= 0 and archive_counts.get(key, 0) > 0
            ),
            "taglist_rows_recoverable_from_archive": sum(1 for key in taglist_keys if archive_counts.get(key, 0) > 0),
        },
        "recommended_next_assets": [
            {
                "asset": "data/danbooru_tag_counts_by_rating.json",
                "reason": "Current rating-count source is smaller than the archive-derived count map; regenerate it from data/tags before filling autocomplete zero-count rows.",
            },
            {
                "asset": "data/KR_tags.parquet",
                "reason": "KR metadata rows with count 0 can be patched from archive counts while preserving Korean description/keywords.",
            },
            {
                "asset": "data/tag_bucket_dates.json",
                "reason": "Rebuild after the post tag archive changes so date cutoff buckets stay aligned.",
            },
            {
                "asset": "tag wiki serving index",
                "reason": "Use the autocomplete corpus as the visible index, with archive/rating counts as coverage metadata and Danbooru wiki text as a separate detail payload.",
            },
        ],
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit NAIA tag assets and dataset gaps.")
    parser.add_argument("--repo-root", default=str(SCRIPT_REPO_ROOT), help="NAIA checkout root.")
    parser.add_argument(
        "--archive-tags",
        default=r"C:\VNR\NAIA2.0\data\tags",
        help="Directory containing tags_*.parquet post tag archive files.",
    )
    parser.add_argument(
        "--interactive",
        default=r"C:\VNR\DEV\interactive.json",
        help="Optional legacy interactive.json to compare against autocomplete.",
    )
    parser.add_argument(
        "--output",
        default=str(SCRIPT_REPO_ROOT / "docs" / "tag_asset_audit_2026-06-14.json"),
        help="JSON report output path.",
    )
    parser.add_argument("--max-files", type=int, default=None, help="Limit archive parquet files for a faster sample audit.")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    archive_root = Path(args.archive_tags).resolve()
    interactive_path = Path(args.interactive).resolve() if args.interactive else None
    output_path = Path(args.output).resolve()

    if not archive_root.exists():
        raise SystemExit(f"archive tag directory not found: {archive_root}")

    report = _build_report(
        repo_root,
        archive_root,
        interactive_path,
        max_files=args.max_files,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"wrote {output_path}")
    print(f"autocomplete rows: {report['autocomplete']['total']:,}")
    print(f"autocomplete zero-count rows: {report['autocomplete']['zero_count_rows']:,}")
    print(f"archive unique tags: {report['archive']['unique_tags_total']:,}")
    print(
        "zero-count rows recoverable from archive: "
        f"{report['derived_counts']['autocomplete_zero_rows_recoverable_from_archive']:,}"
    )
    print(
        "archive tags missing from rating-count source: "
        f"{report['derived_counts']['rating_count_records_missing_archive_tags']:,}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
