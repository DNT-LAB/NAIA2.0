from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, MutableMapping


_HANGUL_RE = re.compile(r"[가-힣]")


def has_hangul(text: Any) -> bool:
    return bool(_HANGUL_RE.search(str(text or "")))


def normalize_tag_key(tag: Any) -> str:
    return " ".join(
        str(tag)
        .replace("\\(", "(")
        .replace("\\)", ")")
        .replace("_", " ")
        .strip()
        .lower()
        .split()
    )


def normalize_display_tag(tag: Any) -> str:
    return " ".join(
        str(tag)
        .replace("\\(", "(")
        .replace("\\)", ")")
        .replace("_", " ")
        .strip()
        .split()
    )


@dataclass
class ParquetTagMergeStats:
    added: int = 0
    records_updated: int = 0
    description_filled: int = 0
    description_replaced: int = 0
    keywords_filled: int = 0
    keywords_replaced: int = 0
    missing_sources: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class TranslationOverrideStats:
    records_seen: int = 0
    added: int = 0
    updated: int = 0
    description_applied: int = 0
    keywords_applied: int = 0
    missing_path: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def applied(self) -> int:
        return self.added + self.updated


def _refresh_lookup_fields(record: MutableMapping[str, Any]) -> None:
    description = str(record.get("description", "") or "")
    keywords = str(record.get("keywords_kr", "") or "")
    record["_desc_lower"] = description.lower()
    record["_kw_lower"] = keywords.replace("<", "").replace(">", "").lower() if keywords else ""


def _merge_text_field(
    record: MutableMapping[str, Any],
    *,
    field_name: str,
    candidate: str,
    replace_non_korean: bool,
) -> str | None:
    candidate = str(candidate or "")
    if not candidate.strip():
        return None

    existing = str(record.get(field_name, "") or "")
    if not existing.strip():
        record[field_name] = candidate
        return "filled"
    if replace_non_korean and has_hangul(candidate) and not has_hangul(existing):
        record[field_name] = candidate
        return "replaced"
    return None


def merge_parquet_tag_records(
    raw: MutableMapping[str, MutableMapping[str, Any]],
    parquet_sources: Iterable[tuple[str | Path, int]],
) -> ParquetTagMergeStats:
    """Merge KR parquet tag metadata into interactive tag records.

    `interactive` remains the structural source for relations and UI grouping.
    Korean parquet metadata is allowed to fill empty fields and replace English
    descriptions/keywords, because those fields are user-facing in Web Remote.
    """

    stats = ParquetTagMergeStats()

    try:
        import pandas as pd
    except Exception as exc:  # pragma: no cover - environment failure
        stats.errors.append(f"pandas import failed: {exc}")
        return stats

    for pq_path, src_key in parquet_sources:
        path = Path(pq_path)
        if not path.exists():
            stats.missing_sources.append(str(path))
            continue
        try:
            df = pd.read_parquet(path, columns=["tag", "count", "category", "desc", "keywords"])
        except Exception as exc:
            stats.errors.append(f"{path}: {exc}")
            continue

        for _, row in df.iterrows():
            tag_raw = normalize_display_tag(row["tag"])
            tag_lower = normalize_tag_key(tag_raw)
            keywords = str(row.get("keywords", "") or "")
            description = str(row.get("desc", "") or "")

            if tag_lower in raw:
                existing = raw[tag_lower]
                updated = False

                desc_action = _merge_text_field(
                    existing,
                    field_name="description",
                    candidate=description,
                    replace_non_korean=True,
                )
                if desc_action == "filled":
                    stats.description_filled += 1
                    updated = True
                elif desc_action == "replaced":
                    stats.description_replaced += 1
                    updated = True

                kw_action = _merge_text_field(
                    existing,
                    field_name="keywords_kr",
                    candidate=keywords,
                    replace_non_korean=True,
                )
                if kw_action == "filled":
                    stats.keywords_filled += 1
                    updated = True
                elif kw_action == "replaced":
                    stats.keywords_replaced += 1
                    updated = True

                if updated:
                    existing["_translation_source"] = str(path)
                    existing["_kr_category"] = str(row.get("category", "") or "")
                    _refresh_lookup_fields(existing)
                    stats.records_updated += 1
                continue

            entry: dict[str, Any] = {
                "_tag": tag_raw,
                "_src": src_key,
                "freq": int(row.get("count", 0) or 0),
                "description": description,
                "group": str(row.get("category", "") or ""),
                "subgroup": "",
                "keywords_kr": keywords,
                "_translation_source": str(path),
                "_kr_category": str(row.get("category", "") or ""),
            }
            if src_key == 2:
                entry["_cat"] = "e621"
            _refresh_lookup_fields(entry)
            raw[tag_lower] = entry
            stats.added += 1

    return stats


def apply_translation_overrides(
    raw: MutableMapping[str, MutableMapping[str, Any]],
    overrides_path: str | Path,
) -> TranslationOverrideStats:
    stats = TranslationOverrideStats()
    path = Path(overrides_path)
    if not path.exists():
        stats.missing_path = True
        return stats

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        stats.errors.append(f"{path}: {exc}")
        return stats

    translations = payload.get("translations", {})
    if not isinstance(translations, dict):
        stats.errors.append(f"{path}: translations must be an object")
        return stats

    for raw_tag, value in translations.items():
        if not isinstance(value, dict):
            stats.errors.append(f"{path}: invalid override for {raw_tag!r}")
            continue
        stats.records_seen += 1

        tag = normalize_display_tag(raw_tag)
        tag_lower = normalize_tag_key(raw_tag)
        record = raw.get(tag_lower)
        added = False
        if record is None:
            record = {
                "_tag": tag,
                "_src": int(value.get("src", 20) or 20),
                "freq": int(value.get("freq", 0) or 0),
                "description": "",
                "group": str(value.get("group", "") or ""),
                "subgroup": str(value.get("subgroup", "") or ""),
                "keywords_kr": "",
            }
            raw[tag_lower] = record
            added = True

        description = str(value.get("description", "") or "")
        if description.strip():
            record["description"] = description
            stats.description_applied += 1
        keywords = str(value.get("keywords_kr", value.get("keywords", "")) or "")
        if keywords.strip():
            record["keywords_kr"] = keywords
            stats.keywords_applied += 1

        if value.get("group") and not record.get("group"):
            record["group"] = str(value.get("group") or "")
        if value.get("subgroup") and not record.get("subgroup"):
            record["subgroup"] = str(value.get("subgroup") or "")
        record["_translation_override_source"] = str(value.get("source", path.as_posix()))
        _refresh_lookup_fields(record)

        if added:
            stats.added += 1
        else:
            stats.updated += 1

    return stats
