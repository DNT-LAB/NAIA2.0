"""JSON-backed Expression Preset service for Remote Web."""

from __future__ import annotations

import json
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any


CATALOG_RELATIVE_PATH = Path("ui") / "expression_preset" / "expression_catalog.json"

_EXPR_MODIFIERS: set[str] = {
    "blush",
    "light blush",
    "blush stickers",
    "nose blush",
    "open mouth",
    "closed mouth",
    "closed eyes",
    "one eye closed",
    "half-closed eyes",
    "raised eyebrows",
}

# Ported from ui/clothes_preset/engines.py. Keep order aligned with Desktop.
EXPRESSION_GROUPS: list[tuple[str, str, set[str]]] = [
    ("tears", "tears", {"tears", "crying", "crying with eyes open", "tearing up"}),
    ("angry", "angry", {"angry", "frown", "light frown", "annoyed", "defeat"}),
    ("shy", "shy", {"embarrassed", "shy", "nervous", "sweatdrop"}),
    ("emoticon", "emoticon", {":d", ":3", ":p", ":q", ";d", ";)", ";p", ":>", "^^^", ";o"}),
    ("surprise", "surprise", {":o", ";o", "surprised"}),
    ("displeased", "displeased", {":<", ":/"}),
    ("grin", "grin", {"grin", "smirk", "smug", "evil smile", "evil grin", "seductive smile"}),
    ("smile", "smile", {"smile", "light smile", "happy"}),
    (
        "stoic",
        "stoic",
        {"expressionless", "serious", "sleepy", "wavy mouth", "dot mouth", "sideways mouth"},
    ),
    (
        "physical",
        "physical",
        {"blood on face", "blood from mouth", "nosebleed", "snot", "saliva", "heavy breathing", "drunk"},
    ),
    ("special", "special", {"facepaint", "reverse trap", "food on face", "averting eyes"}),
]


def norm_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().lower().replace("_", " ").split())


def parse_csv_tags(value: Any) -> list[str]:
    if not isinstance(value, str) or not value.strip():
        return []
    return [tag for tag in (norm_text(part) for part in value.split(",")) if tag]


def unique_preserve(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def classify_expression_combo(expr_combo: str) -> str:
    tags = {tag.strip() for tag in str(expr_combo or "").split(",") if tag.strip()}
    core = tags - _EXPR_MODIFIERS
    if not core:
        return "base"
    for group_key, _label, anchors in EXPRESSION_GROUPS:
        if core & anchors:
            return group_key
    return "other"


def expression_sort_key(row: dict[str, Any]) -> tuple[int, float, int, str]:
    single_bottom = 1 if int(row.get("expr_tags", 0)) <= 1 else 0
    return (
        single_bottom,
        -float(row.get("confidence", 0.0)),
        -int(row.get("count", 0)),
        str(row.get("expression_combo", "")),
    )


def format_count(value: int) -> str:
    n = int(value or 0)
    if n < 1000:
        return str(n)
    k = n / 1000.0
    if k >= 100:
        return f"{k:,.0f}k"
    return f"{k:,.1f}k"


class ExpressionPresetService:
    """Read-only Expression Preset facade backed by a pre-exported JSON catalog."""

    def __init__(self, repo_root: Path | str):
        self.repo_root = Path(repo_root)
        self.catalog_path = self.repo_root / CATALOG_RELATIVE_PATH
        self._lock = threading.RLock()
        self._catalog: dict[str, Any] | None = None
        self._catalog_error = ""

    def status(self) -> dict[str, Any]:
        state = "missing"
        message = "Expression Preset JSON catalog is not installed."
        counts: dict[str, int] = self._empty_counts()
        if self.catalog_path.exists():
            try:
                catalog = self._load_catalog()
                state = "ready"
                message = "Expression Preset JSON catalog is ready."
                counts.update(self._catalog_counts(catalog.get("counts")))
            except Exception as exc:
                state = "error"
                message = f"Expression Preset JSON catalog load failed: {exc}"

        return {
            "ok": True,
            "dataMode": "real" if state == "ready" else state,
            "dataReady": state == "ready",
            "dataAvailability": {
                "main": state,
                "message": message,
            },
            "paths": {
                "catalog": str(CATALOG_RELATIVE_PATH),
            },
            "counts": counts,
            "coverage": self._coverage_summary(self._catalog.get("coverage") if self._catalog else None),
            "semanticCoverage": self._semantic_coverage_summary(
                self._catalog.get("semanticCoverage") if self._catalog else None
            ),
            "capabilities": {
                "bootstrap": state == "ready",
            },
        }

    def bootstrap(self, payload: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        request = self._coerce_payload(payload, kwargs)
        selected = {
            "ratingId": str(request.get("ratingId") or "s"),
            "personId": str(request.get("personId") or "1girl_solo"),
            "limit": self._normalize_limit(request.get("limit")),
        }
        status = self.status()
        if status["dataAvailability"]["main"] != "ready":
            return {
                "ok": True,
                "dataMode": status["dataMode"],
                "dataReady": False,
                "dataAvailability": status["dataAvailability"],
                "counts": status["counts"],
                "coverage": status.get("coverage") or {},
                "semanticCoverage": status.get("semanticCoverage") or {},
                "selected": selected,
                "categories": [],
            }

        catalog = self._load_catalog()
        return {
            "ok": True,
            "dataMode": "real",
            "dataReady": True,
            "dataAvailability": status["dataAvailability"],
            "counts": status["counts"],
            "coverage": status.get("coverage") or {},
            "semanticCoverage": status.get("semanticCoverage") or {},
            "selected": selected,
            "categories": self._limited_categories(catalog.get("categories") or [], selected["limit"]),
        }

    def _load_catalog(self) -> dict[str, Any]:
        with self._lock:
            if self._catalog is not None:
                return self._catalog
            if self._catalog_error:
                raise RuntimeError(self._catalog_error)
            try:
                with self.catalog_path.open("r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                if not isinstance(payload, dict):
                    raise ValueError("catalog root must be an object")
                if not isinstance(payload.get("categories"), list):
                    raise ValueError("catalog categories must be a list")
            except Exception as exc:
                self._catalog_error = str(exc)
                raise
            self._catalog = payload
            return payload

    def _limited_categories(self, categories: list[Any], limit: int) -> list[dict[str, Any]]:
        remaining = limit
        output: list[dict[str, Any]] = []
        for category in categories:
            if remaining <= 0:
                break
            if not isinstance(category, dict):
                continue
            category_copy = deepcopy(category)
            subcategories: list[dict[str, Any]] = []
            item_total = 0
            for subcategory in category_copy.get("subcategories") or []:
                if remaining <= 0:
                    break
                if not isinstance(subcategory, dict):
                    continue
                primary_items = [item for item in (subcategory.get("items") or []) if isinstance(item, dict)]
                overflow_items = [item for item in (subcategory.get("moreItems") or []) if isinstance(item, dict)]
                all_items = [*primary_items, *overflow_items]
                selected_items = deepcopy(all_items[:remaining])
                if not selected_items:
                    continue
                remaining -= len(selected_items)
                is_truncated = len(selected_items) < len(all_items)
                selected_primary = selected_items[:len(primary_items)]
                selected_overflow = selected_items[len(primary_items):]
                subcategory_count = len(selected_items) if is_truncated else int(subcategory.get("count") or len(all_items))
                item_total += subcategory_count
                sub_copy = deepcopy(subcategory)
                sub_copy["items"] = selected_primary
                if selected_overflow:
                    sub_copy["moreItems"] = selected_overflow
                    sub_copy["moreCount"] = len(selected_overflow)
                else:
                    sub_copy.pop("moreItems", None)
                    sub_copy.pop("moreCount", None)
                sub_copy["count"] = subcategory_count
                subcategories.append(sub_copy)
            if not subcategories:
                continue
            category_copy["subcategories"] = subcategories
            category_copy["count"] = item_total
            output.append(category_copy)
        return output

    def _coerce_payload(self, payload: dict[str, Any] | None, kwargs: dict[str, Any]) -> dict[str, Any]:
        request: dict[str, Any] = {}
        if isinstance(payload, dict):
            request.update(payload)
        request.update(kwargs)
        return request

    def _coverage_summary(self, coverage: Any) -> dict[str, Any]:
        if not isinstance(coverage, dict):
            return {}
        summary_keys = (
            "taxonomyTags",
            "catalogTags",
            "coveredTags",
            "missingTags",
            "noiseTags",
            "sourceSeenTags",
            "extraTags",
            "coverageRatio",
            "minTagCount",
        )
        summary = {key: coverage.get(key) for key in summary_keys if key in coverage}
        by_group = []
        for row in coverage.get("byGroup") or []:
            if not isinstance(row, dict):
                continue
            by_group.append({
                "id": row.get("id"),
                "total": row.get("total"),
                "covered": row.get("covered"),
                "missing": row.get("missing"),
                "coverageRatio": row.get("coverageRatio"),
            })
        summary["byGroup"] = by_group
        return summary

    def _semantic_coverage_summary(self, semantic_coverage: Any) -> dict[str, Any]:
        if not isinstance(semantic_coverage, dict):
            return {}
        return {
            "totalTags": semantic_coverage.get("totalTags"),
            "totalComboItems": semantic_coverage.get("totalComboItems"),
            "byCategory": [
                {
                    "id": row.get("id"),
                    "label": row.get("label"),
                    "tags": row.get("tags"),
                    "occurrences": row.get("occurrences"),
                    "comboItems": row.get("comboItems"),
                    "byFocus": [
                        {
                            "id": focus.get("id"),
                            "label": focus.get("label"),
                            "tags": focus.get("tags"),
                            "occurrences": focus.get("occurrences"),
                            "comboItems": focus.get("comboItems"),
                        }
                        for focus in row.get("byFocus") or []
                        if isinstance(focus, dict)
                    ],
                }
                for row in semantic_coverage.get("byCategory") or []
                if isinstance(row, dict)
            ],
        }

    def _normalize_limit(self, value: Any, default: int = 20000) -> int:
        try:
            limit = int(value)
        except (TypeError, ValueError):
            limit = default
        if limit <= 0:
            return default
        return min(limit, 50000)

    def _empty_counts(self) -> dict[str, int]:
        return {
            "sourceRows": 0,
            "rowsWithTaxonomyTags": 0,
            "rowsWithExpressionTags": 0,
            "rawExpressionTags": 0,
            "rawExpressionCombos": 0,
            "expressionCombos": 0,
            "expressionTags": 0,
            "staticTags": 0,
            "noiseTagsRemoved": 0,
            "noiseTagOccurrences": 0,
            "flattenedRows": 0,
            "deduplicatedRows": 0,
            "decoratedRows": 0,
            "semanticDuplicateCombos": 0,
            "lowSignalComboTags": 0,
        }

    def _catalog_counts(self, raw_counts: Any) -> dict[str, int]:
        counts: dict[str, int] = {}
        if not isinstance(raw_counts, dict):
            return counts
        for key, value in raw_counts.items():
            try:
                counts[str(key)] = int(value or 0)
            except (TypeError, ValueError):
                continue
        return counts
