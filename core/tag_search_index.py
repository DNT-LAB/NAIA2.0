from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from core.tag_axis_registry import TagAxisRegistry, normalize_tag


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KR_TAGS_PATH = PROJECT_ROOT / "data" / "KR_tags.parquet"


def _norm(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return " ".join(str(value).replace("_", " ").strip().lower().split())


def _split_keywords(value: Any) -> list[str]:
    text = str(value or "").replace("<", "").replace(">", "")
    return [part.strip() for part in text.split(",") if part.strip()]


@dataclass(frozen=True)
class TagSearchEntry:
    tag: str
    freq: int = 0
    axis: str = "uncategorized"
    source: str = ""
    is_event: bool = False
    is_expression: bool = False
    is_clothing: bool = False
    is_color: bool = False
    category: str = ""
    desc: str = ""
    keywords: tuple[str, ...] = ()
    search_blob: str = ""


@dataclass(frozen=True)
class TagSearchResult:
    tag: str
    score: float
    entry: TagSearchEntry


class TagSearchIndex:
    """Small shared lexical tag search index.

    MVP scope:
    - Exact, prefix, token, and substring ranking.
    - Korean lookup through KR_tags category/desc/keywords.
    - Event Preset metadata through tag_category + taxonomy search_blob.
    """

    def __init__(self, entries: Iterable[TagSearchEntry]):
        dedup: dict[str, TagSearchEntry] = {}
        for entry in entries:
            tag = normalize_tag(entry.tag)
            if not tag:
                continue
            previous = dedup.get(tag)
            if previous is None or entry.freq > previous.freq or (entry.is_event and not previous.is_event):
                dedup[tag] = TagSearchEntry(
                    tag=tag,
                    freq=int(entry.freq or 0),
                    axis=entry.axis,
                    source=entry.source,
                    is_event=entry.is_event,
                    is_expression=entry.is_expression,
                    is_clothing=entry.is_clothing,
                    is_color=entry.is_color,
                    category=entry.category,
                    desc=entry.desc,
                    keywords=tuple(entry.keywords),
                    search_blob=_norm(entry.search_blob),
                )

        self._entries = dedup
        self._blob_by_tag: dict[str, str] = {
            tag: self._make_blob(entry) for tag, entry in self._entries.items()
        }

    @classmethod
    def from_event_preset_assets(
        cls,
        assets: dict[str, Any],
        *,
        taxonomy: pd.DataFrame | None = None,
        kr_tags_path: str | Path | None = None,
    ) -> "TagSearchIndex":
        catalog = assets.get("tag_catalog.parquet", pd.DataFrame())
        category = assets.get("tag_category.parquet", pd.DataFrame())
        kr_rows = cls._load_kr_rows(kr_tags_path or DEFAULT_KR_TAGS_PATH)

        taxonomy_by_tag: dict[str, dict[str, Any]] = {}
        if taxonomy is not None and not taxonomy.empty and "event_tag" in taxonomy.columns:
            for item in taxonomy.to_dict(orient="records"):
                taxonomy_by_tag[normalize_tag(item.get("event_tag", ""))] = item

        base_lookup = cls._axis_lookup_from_category(category)
        registry = TagAxisRegistry(base_lookup)

        freq_by_tag = {}
        if not catalog.empty and {"tag_name", "freq"}.issubset(catalog.columns):
            freq_by_tag = {
                normalize_tag(tag): int(freq or 0)
                for tag, freq in zip(catalog["tag_name"], catalog["freq"])
            }

        entries: list[TagSearchEntry] = []
        if not category.empty and "tag_name" in category.columns:
            for item in category.to_dict(orient="records"):
                tag = normalize_tag(item.get("tag_name", ""))
                kr = kr_rows.get(tag, {})
                tax = taxonomy_by_tag.get(tag, {})

                keywords = tuple(
                    _split_keywords(kr.get("keywords", ""))
                    + _split_keywords(tax.get("kr_keywords", ""))
                    + _split_keywords(tax.get("interactive_keywords_kr", ""))
                )
                desc = " ".join(
                    part
                    for part in [
                        str(kr.get("desc", "") or ""),
                        str(tax.get("kr_desc", "") or ""),
                        str(tax.get("interactive_description", "") or ""),
                    ]
                    if part
                )
                category_text = " ".join(
                    part
                    for part in [
                        str(kr.get("category", "") or ""),
                        str(item.get("category", "") or ""),
                        str(tax.get("group", "") or ""),
                        str(tax.get("subgroup", "") or ""),
                        str(tax.get("subcategory", "") or ""),
                    ]
                    if part
                )
                search_blob = " ".join(
                    str(part)
                    for part in [
                        tag,
                        desc,
                        " ".join(keywords),
                        category_text,
                        tax.get("search_blob", ""),
                    ]
                    if part
                )

                entries.append(
                    TagSearchEntry(
                        tag=tag,
                        freq=freq_by_tag.get(tag, int(tax.get("post_count", 0) or 0)),
                        axis=registry.axis_for(tag),
                        source=str(item.get("source", "")),
                        is_event=bool(item.get("is_event", False)),
                        is_expression=bool(item.get("is_expression", False)),
                        is_clothing=bool(item.get("is_clothing", False)),
                        is_color=bool(item.get("is_color", False)),
                        category=category_text,
                        desc=desc,
                        keywords=keywords,
                        search_blob=search_blob,
                    )
                )

        # KR-only rows still matter for shared search outside Event Preset.
        existing_tags = {entry.tag for entry in entries}
        for tag, kr in kr_rows.items():
            if tag in existing_tags:
                continue
            entries.append(
                TagSearchEntry(
                    tag=tag,
                    freq=int(kr.get("count", 0) or 0),
                    axis=registry.axis_for(tag),
                    source="KR_tags",
                    category=str(kr.get("category", "") or ""),
                    desc=str(kr.get("desc", "") or ""),
                    keywords=tuple(_split_keywords(kr.get("keywords", ""))),
                    search_blob=" ".join(
                        str(part)
                        for part in [
                            tag,
                            kr.get("category", ""),
                            kr.get("desc", ""),
                            kr.get("keywords", ""),
                        ]
                        if part
                    ),
                )
            )

        return cls(entries)

    @staticmethod
    def _load_kr_rows(path: str | Path) -> dict[str, dict[str, Any]]:
        kr_path = Path(path)
        if not kr_path.exists():
            return {}
        df = pd.read_parquet(kr_path)
        rows: dict[str, dict[str, Any]] = {}
        for item in df.to_dict(orient="records"):
            tag = normalize_tag(item.get("tag", ""))
            if tag:
                rows[tag] = item
        return rows

    @staticmethod
    def _axis_lookup_from_category(category: pd.DataFrame) -> dict[str, str]:
        if category.empty or "tag_name" not in category.columns:
            return {}

        lookup: dict[str, str] = {}
        for item in category.to_dict(orient="records"):
            tag = normalize_tag(item.get("tag_name", ""))
            if not tag:
                continue
            raw_category = str(item.get("category", "") or "").lower()
            axis = "meta"
            if bool(item.get("is_event", False)) or raw_category == "event":
                axis = "pose_action"
            elif bool(item.get("is_expression", False)) or raw_category == "expression":
                axis = "expression"
            elif bool(item.get("is_clothing", False)) or raw_category == "clothing":
                axis = "clothing"
            elif raw_category in {"location", "background"}:
                axis = "location"
            elif raw_category in {"object", "food", "creature"}:
                axis = "object"
            lookup[tag] = axis
        return lookup

    def search(
        self,
        query: str,
        *,
        limit: int | None = 50,
        axes: set[str] | None = None,
        require_event: bool | None = None,
        sources: set[str] | None = None,
    ) -> list[TagSearchResult]:
        q = _norm(query)
        if not q:
            return []
        q_tokens = [tok for tok in q.split() if tok]

        results: list[TagSearchResult] = []
        for tag, entry in self._entries.items():
            if require_event is True and not entry.is_event:
                continue
            if require_event is False and entry.is_event:
                continue
            if axes is not None and entry.axis not in axes:
                continue
            if sources is not None and entry.source not in sources:
                continue

            blob = self._blob_by_tag[tag]
            score = self._score(q, q_tokens, tag, blob, entry)
            if score <= 0:
                continue
            results.append(TagSearchResult(tag=tag, score=score, entry=entry))

        results.sort(key=lambda r: (-r.score, -r.entry.freq, r.tag))
        if limit is not None:
            return results[:limit]
        return results

    def search_tags(self, query: str, **kwargs: Any) -> list[str]:
        return [result.tag for result in self.search(query, **kwargs)]

    def _make_blob(self, entry: TagSearchEntry) -> str:
        parts = [
            entry.tag,
            entry.category,
            entry.desc,
            " ".join(entry.keywords),
            entry.search_blob,
        ]
        return _norm(" ".join(part for part in parts if part))

    @staticmethod
    def _score(
        query: str,
        query_tokens: list[str],
        tag: str,
        blob: str,
        entry: TagSearchEntry,
    ) -> float:
        score = 0.0
        if tag == query:
            score += 1000
        elif tag.startswith(query):
            score += 850
        elif query in tag:
            score += 650

        if query in blob:
            score += 300
        elif query_tokens and all(token in blob for token in query_tokens):
            score += 220
        elif query_tokens and all(token in tag for token in query_tokens):
            score += 180

        if query_tokens:
            matched_tokens = sum(1 for token in query_tokens if token in blob)
            if matched_tokens:
                score += matched_tokens * 20

        if score <= 0:
            return 0.0

        if entry.is_event:
            score += 25
        if entry.source == "KR_tags":
            score += 5
        return score
