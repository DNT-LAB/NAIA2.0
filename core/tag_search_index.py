from __future__ import annotations

import re
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from core.tag_axis_registry import TagAxisRegistry, normalize_tag
from core.tag_knowledge import has_hangul


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KR_TAGS_PATH = PROJECT_ROOT / "data" / "KR_tags.parquet"
_WEIGHT_PREFIX_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)::\s*")
_WEIGHT_ONLY_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?::+)?$")
_TRAILING_WEIGHT_MARK_RE = re.compile(r"\s*::$")
_HANGUL_RE = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")


def _norm(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return " ".join(str(value).replace("_", " ").strip().lower().split())


def _compact_hangul(value: Any) -> str:
    text = _norm(value)
    if not text or not _HANGUL_RE.search(text):
        return ""
    return "".join(text.split())


def _split_keywords(value: Any) -> list[str]:
    text = str(value or "").replace("<", "").replace(">", "")
    return [part.strip() for part in text.split(",") if part.strip()]


def normalize_search_query(value: Any) -> str:
    """Normalize user tag search text and discard prompt weight fragments."""
    query = _norm(value)
    if not query:
        return ""

    while True:
        stripped = _WEIGHT_PREFIX_RE.sub("", query, count=1).strip()
        if stripped == query:
            break
        query = stripped

    query = _TRAILING_WEIGHT_MARK_RE.sub("", query).strip()
    if not query or _WEIGHT_ONLY_RE.fullmatch(query):
        return ""
    if not any(ch.isalnum() for ch in query):
        return ""
    return query


@dataclass(frozen=True)
class TagSearchEntry:
    tag: str
    freq: int = 0
    axis: str = "uncategorized"
    source: str = ""
    cat: str = ""
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


def _entry_has_hangul(entry: TagSearchEntry) -> bool:
    return (
        has_hangul(entry.category)
        or has_hangul(entry.desc)
        or any(has_hangul(keyword) for keyword in entry.keywords)
    )


def _should_replace_duplicate(entry: TagSearchEntry, previous: TagSearchEntry) -> bool:
    if entry.is_event != previous.is_event:
        return entry.is_event

    entry_has_hangul = _entry_has_hangul(entry)
    previous_has_hangul = _entry_has_hangul(previous)
    if entry_has_hangul != previous_has_hangul:
        return entry_has_hangul

    if entry.freq != previous.freq:
        return entry.freq > previous.freq

    if entry.desc and not previous.desc:
        return True
    return bool(entry.keywords and not previous.keywords)


def _deduped_entry(
    tag: str,
    preferred: TagSearchEntry,
    other: TagSearchEntry | None = None,
) -> TagSearchEntry:
    other = other or preferred
    keywords = tuple(dict.fromkeys(tuple(preferred.keywords) + tuple(other.keywords)))
    search_blob = " ".join(
        part for part in (preferred.search_blob, other.search_blob) if part
    )

    return TagSearchEntry(
        tag=tag,
        freq=max(int(preferred.freq or 0), int(other.freq or 0)),
        axis=preferred.axis if preferred.axis != "uncategorized" else other.axis,
        source=preferred.source or other.source,
        cat=preferred.cat or other.cat,
        is_event=preferred.is_event or other.is_event,
        is_expression=preferred.is_expression or other.is_expression,
        is_clothing=preferred.is_clothing or other.is_clothing,
        is_color=preferred.is_color or other.is_color,
        category=preferred.category or other.category,
        desc=preferred.desc or other.desc,
        keywords=keywords,
        search_blob=_norm(search_blob),
    )


class TagSearchIndex:
    """Small shared lexical tag search index.

    MVP scope:
    - Exact, prefix, token, and substring ranking.
    - Korean lookup through KR_tags category/desc/keywords.
    - Event Preset metadata through tag_category + taxonomy search_blob.

    Public entrypoints intentionally map to product use-cases. Web autocomplete
    should stay fast and literal-heavy, while event/state semantic search should
    preserve recall from descriptions and Korean keywords.
    """

    def __init__(self, entries: Iterable[TagSearchEntry]):
        dedup: dict[str, TagSearchEntry] = {}
        for entry in entries:
            tag = normalize_tag(entry.tag)
            if not tag:
                continue
            previous = dedup.get(tag)
            if previous is None:
                dedup[tag] = _deduped_entry(tag, entry)
                continue
            if _should_replace_duplicate(entry, previous):
                dedup[tag] = _deduped_entry(tag, entry, previous)
            else:
                dedup[tag] = _deduped_entry(tag, previous, entry)

        self._entries = dedup
        self._blob_by_tag: dict[str, str] = {
            tag: self._make_blob(entry) for tag, entry in self._entries.items()
        }
        self._sorted_tags = tuple(sorted(self._entries))
        self._term_to_tags = self._build_candidate_index()

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
                        cat="",
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
                    cat="",
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

    @classmethod
    def from_raw_tag_records(
        cls,
        records: Mapping[str, Mapping[str, Any]],
    ) -> "TagSearchIndex":
        """Build an index from Remote/Web tag records.

        The remote server already merges `ui/interactive/interactive`, KR_tags,
        e621, and artist/character dictionaries into `_kr_tags_raw`. This helper
        lets Web Remote use the same search scorer as Event Preset without
        requiring Event Preset assets.
        """
        registry = TagAxisRegistry()
        entries: list[TagSearchEntry] = []

        for raw_info in records.values():
            tag = normalize_tag(str(raw_info.get("_tag", "") or raw_info.get("tag", "")))
            if not tag:
                continue

            group = str(raw_info.get("group", "") or "")
            subgroup = str(raw_info.get("subgroup", "") or "")
            cat = str(raw_info.get("_cat", "") or "")
            desc = str(raw_info.get("description", "") or raw_info.get("desc", "") or "")
            keywords = tuple(
                _split_keywords(raw_info.get("keywords_kr", ""))
                + _split_keywords(raw_info.get("keywords", ""))
            )

            entries.append(
                TagSearchEntry(
                    tag=tag,
                    freq=int(raw_info.get("freq", raw_info.get("count", 0)) or 0),
                    axis=registry.axis_for(tag),
                    source=str(raw_info.get("_src", "") or raw_info.get("source", "")),
                    cat=cat,
                    category=group,
                    desc=desc,
                    keywords=keywords,
                    search_blob=" ".join(
                        str(part)
                        for part in [
                            tag,
                            group,
                            subgroup,
                            cat,
                            desc,
                            " ".join(keywords),
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
        cats: set[str] | None = None,
    ) -> list[TagSearchResult]:
        """Compatibility entrypoint for existing fast autocomplete callers."""
        return self.search_autocomplete(
            query,
            limit=limit,
            axes=axes,
            require_event=require_event,
            sources=sources,
            cats=cats,
        )

    def search_autocomplete(
        self,
        query: str,
        *,
        limit: int | None = 50,
        axes: set[str] | None = None,
        require_event: bool | None = None,
        sources: set[str] | None = None,
        cats: set[str] | None = None,
    ) -> list[TagSearchResult]:
        """Fast, literal-heavy lookup for Web Remote autocomplete/search chips."""
        return self._search(
            query,
            limit=limit,
            axes=axes,
            require_event=require_event,
            sources=sources,
            cats=cats,
            force_term_scan=False,
            scan_substrings=False,
        )

    def search_tag_filter(
        self,
        query: str,
        *,
        limit: int | None = 50,
        axes: set[str] | None = None,
        require_event: bool | None = None,
        sources: set[str] | None = None,
        cats: set[str] | None = None,
    ) -> list[TagSearchResult]:
        """Fast lookup for tag filter assignment UI."""
        return self._search(
            query,
            limit=limit,
            axes=axes,
            require_event=require_event,
            sources=sources,
            cats=cats,
            force_term_scan=False,
            scan_substrings=False,
        )

    def search_semantic(
        self,
        query: str,
        *,
        limit: int | None = 50,
        axes: set[str] | None = None,
        require_event: bool | None = None,
        sources: set[str] | None = None,
        cats: set[str] | None = None,
    ) -> list[TagSearchResult]:
        """Recall-oriented search for Korean descriptions/keywords."""
        return self._search(
            query,
            limit=limit,
            axes=axes,
            require_event=require_event,
            sources=sources,
            cats=cats,
            force_term_scan=True,
            scan_substrings=True,
        )

    def search_event_semantic(
        self,
        query: str,
        *,
        limit: int | None = 50,
        axes: set[str] | None = None,
        require_event: bool | None = True,
        sources: set[str] | None = None,
        cats: set[str] | None = None,
    ) -> list[TagSearchResult]:
        """Recall-oriented event/state lookup with event filtering by default."""
        return self._search(
            query,
            limit=limit,
            axes=axes,
            require_event=require_event,
            sources=sources,
            cats=cats,
            force_term_scan=True,
            scan_substrings=True,
        )

    def _search(
        self,
        query: str,
        *,
        limit: int | None,
        axes: set[str] | None,
        require_event: bool | None,
        sources: set[str] | None,
        cats: set[str] | None,
        force_term_scan: bool,
        scan_substrings: bool,
    ) -> list[TagSearchResult]:
        q = normalize_search_query(query)
        if not q:
            return []
        q_tokens = [tok for tok in q.split() if tok]

        results: list[TagSearchResult] = []
        candidate_tags = self._candidate_tags(
            q,
            q_tokens,
            limit=limit,
            force_term_scan=force_term_scan,
            scan_substrings=scan_substrings,
        )

        for tag in candidate_tags:
            entry = self._entries[tag]
            if require_event is True and not entry.is_event:
                continue
            if require_event is False and entry.is_event:
                continue
            if axes is not None and entry.axis not in axes:
                continue
            if sources is not None and entry.source not in sources:
                continue
            if cats is not None and entry.cat not in cats:
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

    def _build_candidate_index(self) -> dict[str, frozenset[str]]:
        term_to_tags: dict[str, set[str]] = defaultdict(set)

        for tag, entry in self._entries.items():
            blob = self._make_candidate_blob(entry)
            for token in set(blob.split()):
                if not token:
                    continue
                term_to_tags[token].add(tag)

            for keyword in entry.keywords:
                term = _norm(keyword)
                if not term:
                    continue
                term_to_tags[term].add(tag)
                compact_term = _compact_hangul(term)
                if compact_term and compact_term != term:
                    term_to_tags[compact_term].add(tag)

        return {term: frozenset(tags) for term, tags in term_to_tags.items()}

    def _candidate_tags(
        self,
        query: str,
        query_tokens: list[str],
        *,
        limit: int | None,
        force_term_scan: bool = False,
        scan_substrings: bool = False,
    ) -> set[str]:
        candidates: set[str] = set()
        compact_query = _compact_hangul(query)

        if query in self._entries:
            candidates.add(query)

        start = bisect_left(self._sorted_tags, query)
        for tag in self._sorted_tags[start:]:
            if not tag.startswith(query):
                break
            candidates.add(tag)

        if scan_substrings and self._should_scan_tag_substrings(query):
            candidates.update(tag for tag in self._sorted_tags if query in tag)

        token_sets = [self._term_to_tags.get(token) for token in query_tokens]
        if token_sets and all(token_sets):
            ordered_sets = sorted(token_sets, key=len)
            token_candidates = set(ordered_sets[0])
            for tags in ordered_sets[1:]:
                token_candidates.intersection_update(tags)
                if not token_candidates:
                    break
            candidates.update(token_candidates)

        term_matches = self._term_to_tags.get(query)
        if term_matches:
            candidates.update(term_matches)
        if compact_query and compact_query != query:
            compact_matches = self._term_to_tags.get(compact_query)
            if compact_matches:
                candidates.update(compact_matches)

        should_scan_terms = force_term_scan or (
            scan_substrings and not self._has_enough_candidates(candidates, limit)
        )
        if self._should_scan_terms(query) and should_scan_terms:
            for term, tags in self._term_to_tags.items():
                if term != query and query in term:
                    candidates.update(tags)

        if force_term_scan:
            candidates.update(tag for tag, blob in self._blob_by_tag.items() if query in blob)

        return candidates

    @staticmethod
    def _has_enough_candidates(candidates: set[str], limit: int | None) -> bool:
        if limit is None:
            return False
        return len(candidates) >= max(limit * 3, 32)

    @staticmethod
    def _should_scan_terms(query: str) -> bool:
        if len(query) < 2:
            return False
        if any(ord(ch) > 127 for ch in query):
            return True
        return len(query) >= 3

    @staticmethod
    def _should_scan_tag_substrings(query: str) -> bool:
        if any(ord(ch) > 127 for ch in query):
            return len(query) >= 2
        return len(query) >= 3

    def _make_candidate_blob(self, entry: TagSearchEntry) -> str:
        parts = [
            entry.tag,
            entry.desc,
            " ".join(entry.keywords),
        ]
        return _norm(" ".join(part for part in parts if part))

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

        keyword_terms = [_norm(keyword) for keyword in entry.keywords if _norm(keyword)]
        keyword_blob = _norm(" ".join(keyword_terms))
        compact_query = _compact_hangul(query)
        compact_keywords = {
            compact
            for compact in (_compact_hangul(keyword) for keyword in keyword_terms)
            if compact
        }
        desc = _norm(entry.desc)
        category = _norm(entry.category)
        search_blob = _norm(entry.search_blob)

        if query in keyword_terms:
            score += 760
        elif compact_query and compact_query in compact_keywords:
            score += 600
        elif any(term.startswith(query) for term in keyword_terms):
            score += 560
        elif keyword_blob and query in keyword_blob:
            score += 500
        elif query_tokens and keyword_blob and all(token in keyword_blob for token in query_tokens):
            score += 430
        elif desc and query in desc:
            score += 220
        elif query_tokens and desc and all(token in desc for token in query_tokens):
            score += 160
        elif query_tokens and all(token in tag for token in query_tokens):
            score += 180
        elif search_blob and query in search_blob:
            score += 140
        elif category and query in category:
            score += 100

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
