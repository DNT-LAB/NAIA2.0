from __future__ import annotations

import importlib
import json
import sys
from collections.abc import MutableMapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from core.tag_knowledge import apply_translation_overrides, merge_parquet_tag_records


PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class KrTagLoadResult:
    raw: dict[str, dict[str, Any]]
    interactive_count: int = 0
    filter_count: int = 0
    dict_count: int = 0
    parquet_stats: Any | None = None
    override_stats: Any | None = None
    warnings: list[str] = field(default_factory=list)


def _normalize_tag_text(value: Any) -> str:
    return str(value or "").replace("\\(", "(").replace("\\)", ")")


def _warn(warnings: list[str], message: str, warn: Callable[[str], None] | None) -> None:
    warnings.append(message)
    if warn is not None:
        warn(message)


def _collect_filter_tags(path: Path) -> list[Any]:
    if path.suffix.lower() == ".json":
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return list(data or [])
        collected: list[Any] = []
        for key in ("tags", "modifiers", "uncategorized"):
            value = data.get(key, [])
            if isinstance(value, list):
                collected.extend(value)
        for key in ("groups", "categories"):
            value = data.get(key, {})
            if isinstance(value, dict):
                for sub_tags in value.values():
                    if isinstance(sub_tags, list):
                        collected.extend(sub_tags)
        return collected

    with path.open("r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def _unique_data_roots(repo_root: Path, data_roots: list[str | Path] | tuple[str | Path, ...] | None) -> list[Path]:
    roots: list[Path] = []
    for raw in [*(data_roots or []), repo_root / "data"]:
        path = Path(raw)
        if not path.is_absolute():
            path = repo_root / path
        resolved = path.resolve()
        if resolved not in roots:
            roots.append(resolved)
    return roots


def _first_existing(data_roots: list[Path], relative: str | Path) -> Path:
    for data_root in data_roots:
        path = data_root / relative
        if path.exists():
            return path
    return data_roots[0] / relative


def load_kr_tag_records(
    root: str | Path | None = None,
    *,
    data_roots: list[str | Path] | tuple[str | Path, ...] | None = None,
    allow_legacy_interactive_fallback: bool = False,
    warn: Callable[[str], None] | None = None,
) -> KrTagLoadResult:
    """Load the merged KR tag corpus without depending on RemoteBridge."""

    repo_root = Path(root) if root is not None else PROJECT_ROOT
    resolved_data_roots = _unique_data_roots(repo_root, data_roots)
    warnings: list[str] = []
    raw: dict[str, dict[str, Any]] = {}

    interactive_path = repo_root / "ui" / "interactive" / "interactive"
    if not interactive_path.exists() and allow_legacy_interactive_fallback:
        legacy_path = repo_root / "legacy_desktop" / "ui" / "interactive" / "interactive"
        if legacy_path.exists():
            interactive_path = legacy_path
    if interactive_path.exists():
        with interactive_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        for tag, info in data.items():
            if not isinstance(info, MutableMapping):
                continue
            keywords = str(info.get("keywords_kr", "") or "")
            tag_norm = _normalize_tag_text(tag)
            raw[tag_norm.lower()] = {
                **info,
                "_tag": tag_norm,
                "_src": 0,
                "_kw_lower": keywords.replace("<", "").replace(">", "").lower() if keywords else "",
                "_desc_lower": str(info.get("description", "") or "").lower(),
            }
    else:
        _warn(warnings, f"tag data not found at {interactive_path}; using parquet/filter bootstrap only", warn)
    interactive_count = len(raw)

    parquet_stats = merge_parquet_tag_records(
        raw,
        [
            (_first_existing(resolved_data_roots, "KR_tags.parquet"), 1),
            (_first_existing(resolved_data_roots, "e621_KR_tags.parquet"), 2),
        ],
    )
    override_stats = apply_translation_overrides(
        raw,
        _first_existing(resolved_data_roots, Path("tag_index") / "tag_translation_overrides.json"),
    )
    for error in parquet_stats.errors + override_stats.errors:
        _warn(warnings, f"tag metadata merge warning - {error}", warn)

    filter_sources = [
        ("data/characteristic_list.txt", 3, "\ud2b9\uc9d5"),
        ("data/clothes_list.txt", 4, "\uc758\uc0c1"),
        ("data/taglist/expression_tags.json", 5, "\ud45c\uc815"),
        ("data/taglist/pose_action_tags.json", 6, "\uc790\uc138/\ud589\ub3d9"),
        ("data/taglist/location_tags.json", 7, "\uc7a5\uc18c"),
        ("data/taglist/meta_tags.json", 8, "\uba54\ud0c0"),
        ("data/taglist/object_tags.json", 9, "\ubb3c\uccb4"),
        ("data/color.txt", 10, "\uc0c9\uc0c1"),
    ]
    filter_count = 0
    for relative_path, source_key, group_name in filter_sources:
        clean_relative = str(relative_path)
        if clean_relative.startswith("data/"):
            clean_relative = clean_relative[len("data/"):]
        path = _first_existing(resolved_data_roots, clean_relative)
        if not path.exists():
            continue
        try:
            tags = _collect_filter_tags(path)
            for tag_raw in tags:
                tag_norm = _normalize_tag_text(str(tag_raw).replace("_", " "))
                tag_lower = tag_norm.lower()
                if tag_lower in raw:
                    continue
                raw[tag_lower] = {
                    "_tag": tag_norm,
                    "_src": source_key,
                    "freq": 0,
                    "description": "",
                    "group": group_name,
                    "subgroup": "",
                    "keywords_kr": "",
                    "_kw_lower": "",
                    "_desc_lower": "",
                }
                filter_count += 1
        except Exception as exc:
            _warn(warnings, f"filter {path} load failed - {exc}", warn)

    root_str = str(repo_root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    dict_sources = [
        ("artist_dictionary", "artist_dict", 11, "artist"),
        ("danbooru_character", "character_dict_count", 12, "character"),
        ("result_dict_copyright", "copyright_dict", 13, "copyright"),
    ]
    dict_count = 0
    for module_name, variable_name, source_key, category in dict_sources:
        try:
            module = importlib.import_module(module_name)
            records = getattr(module, variable_name, {})
            for tag_raw, freq in records.items():
                tag_norm = _normalize_tag_text(tag_raw)
                tag_lower = tag_norm.lower()
                if tag_lower in raw:
                    raw[tag_lower].setdefault("_cat", category)
                    continue
                raw[tag_lower] = {
                    "_tag": tag_norm,
                    "_src": source_key,
                    "_cat": category,
                    "freq": int(freq) if isinstance(freq, (int, float)) else 0,
                    "description": "",
                    "group": category,
                    "subgroup": "",
                    "keywords_kr": "",
                    "_kw_lower": "",
                    "_desc_lower": "",
                }
                dict_count += 1
        except Exception as exc:
            _warn(warnings, f"dict {module_name} load failed - {exc}", warn)

    return KrTagLoadResult(
        raw=raw,
        interactive_count=interactive_count,
        filter_count=filter_count,
        dict_count=dict_count,
        parquet_stats=parquet_stats,
        override_stats=override_stats,
        warnings=warnings,
    )


def format_kr_tag_load_summary(result: KrTagLoadResult) -> str:
    parquet = result.parquet_stats
    overrides = result.override_stats
    return (
        f"{result.interactive_count} interactive + {getattr(parquet, 'added', 0)} parquet "
        f"+ {getattr(parquet, 'records_updated', 0)} KR merges "
        f"(desc fill {getattr(parquet, 'description_filled', 0)}, "
        f"desc replace {getattr(parquet, 'description_replaced', 0)}, "
        f"kw fill {getattr(parquet, 'keywords_filled', 0)}, "
        f"kw replace {getattr(parquet, 'keywords_replaced', 0)}) "
        f"+ {getattr(overrides, 'applied', 0)} overrides "
        f"+ {result.filter_count} filter + {result.dict_count} dict = {len(result.raw)} total"
    )
