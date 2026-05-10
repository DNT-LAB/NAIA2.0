from __future__ import annotations

import json
import math
import re
import threading
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
KR_METADATA_SEARCH_RULES_PATH = PROJECT_ROOT / "data" / "tag_index" / "kr_metadata_search_rules.json"
_WEIGHT_PREFIX_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)::\s*")
_WEIGHT_ONLY_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?::+)?$")
_TRAILING_WEIGHT_MARK_RE = re.compile(r"\s*::$")
_HANGUL_RE = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")
_METADATA_TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]+")
_KR_METADATA_STOPWORDS = {
    "것",
    "같은",
    "그",
    "및",
    "몸이",
    "건네줌",
    "녹아",
    "녹음",
    "사용",
    "정도",
    "있는",
    "있음",
    "하게",
    "하고",
    "하며",
    "한",
    "함",
}
_KR_METADATA_SINGLE_CHAR_TERMS = {
    "귀",
    "꽃",
    "꿀",
    "눈",
    "물",
    "발",
    "불",
    "손",
    "옷",
    "입",
    "잔",
    "컵",
    "코",
    "팔",
    "핀",
    "후",
}
_KR_METADATA_SUFFIXES = (
    "으로",
    "에서",
    "에게",
    "까지",
    "처럼",
    "보다",
    "부터",
    "하고",
    "하며",
    "하기",
    "하다",
    "하는",
    "하게",
    "되어",
    "된",
    "인",
    "임",
    "음",
    "기",
    "을",
    "를",
    "은",
    "는",
    "이",
    "가",
    "에",
    "의",
    "와",
    "과",
    "도",
    "나",
)
_KR_METADATA_ALIASES = {
    "바라보다": ("보기", "보고", "보다"),
    "바라보": ("보기", "보고", "보다"),
    "보고있음": ("보기", "보고", "보다"),
    "건네줌": ("offering", "handing"),
    "녹아": ("dissolving", "melting"),
    "녹음": ("dissolving", "melting"),
    "쥐고있음": ("들고", "잡고", "손"),
    "쥐고": ("들고", "잡고", "손"),
    "잡고있음": ("잡고", "들고"),
    "들고있음": ("들고", "잡고"),
    "드러냄": ("revealing", "exposing"),
    "드러내": ("revealing", "exposing"),
    "마시는": ("마시", "음료"),
    "마시": ("음료",),
    "따로": ("분리된", "분리"),
    "수인": ("anthro",),
    "요도": ("urethral", "urethra"),
    "입력": ("keyboard", "input"),
    "자판": ("keyboard",),
    "잡아당기기": ("잡아당기", "당기"),
    "잡아당김": ("잡아당기", "당기"),
    "당기기": ("당기",),
    "단지": ("jar", "pot", "honeypot"),
    "성기": ("penis", "genitalia", "genitals"),
    "슈타게": ("steins", "gate"),
    "장치": ("device",),
    "앉음": ("앉", "앉는", "앉아"),
    "이동": ("움직이", "움직이는", "매달려"),
    "타고": ("타는", "매달려"),
    "전구": ("bulb", "light"),
    "절정": ("orgasm", "climax"),
    "좀비": ("zombie", "zombification"),
    "좀비로": ("zombie", "zombification"),
    "카이니스": ("caenis",),
    "빨개짐": ("blush", "blushing"),
    "출렁": ("jiggling", "jiggle"),
    "출렁거림": ("jiggling", "jiggle"),
    "키보드": ("keyboard",),
    "투명함": ("invisible", "transparent"),
    "투명": ("invisible", "transparent"),
    "꿀": ("honey", "honeypot"),
    "후": ("after",),
}


def _load_kr_metadata_search_rules() -> dict[str, Any]:
    try:
        with KR_METADATA_SEARCH_RULES_PATH.open("r", encoding="utf-8") as f:
            loaded = json.load(f)
        return loaded if isinstance(loaded, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def _extend_rule_set(target: set[str], rules: Mapping[str, Any], key: str) -> None:
    value = rules.get(key)
    if not isinstance(value, list):
        return
    target.update(_norm(item) for item in value if _norm(item))


def _extend_aliases(target: dict[str, tuple[str, ...]], rules: Mapping[str, Any]) -> None:
    value = rules.get("aliases")
    if not isinstance(value, dict):
        return
    for raw_key, raw_items in value.items():
        key = _norm(raw_key)
        if not key:
            continue
        if isinstance(raw_items, str):
            items = [_norm(raw_items)]
        elif isinstance(raw_items, list):
            items = [_norm(item) for item in raw_items]
        else:
            continue
        clean_items = tuple(item for item in items if item)
        if clean_items:
            target[key] = tuple(dict.fromkeys(target.get(key, ()) + clean_items))


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


_KR_METADATA_WEAK_QUERY_TERMS = {
    "고있",
    "고있음",
    "달린",
    "단",
    "따로",
    "당기",
    "들고",
    "드러냄",
    "드러내",
    "마시",
    "마시는",
    "매달려",
    "몸이",
    "보고",
    "보기",
    "보다",
    "바라보",
    "바라보다",
    "쥐고",
    "쥐고있",
    "쥐고있음",
    "잡고",
    "잡아당기",
    "잡아당기기",
    "성기",
    "성기를",
    "상태",
    "좀비",
    "좀비로",
    "타고",
    "움직이",
    "움직이는",
    "음료",
    "이동",
    "앉",
    "앉는",
    "앉아",
    "앉음",
    "출렁",
    "출렁거림",
    "후",
    "빨개짐",
}
_KR_METADATA_SCORELESS_QUERY_TERMS = {
    "몸이",
    "성기",
    "성기를",
}
_KR_METADATA_SEARCH_RULES = _load_kr_metadata_search_rules()
_extend_rule_set(_KR_METADATA_STOPWORDS, _KR_METADATA_SEARCH_RULES, "stopwords")
_extend_rule_set(_KR_METADATA_SINGLE_CHAR_TERMS, _KR_METADATA_SEARCH_RULES, "single_char_terms")
_extend_rule_set(_KR_METADATA_WEAK_QUERY_TERMS, _KR_METADATA_SEARCH_RULES, "weak_query_terms")
_extend_rule_set(_KR_METADATA_SCORELESS_QUERY_TERMS, _KR_METADATA_SEARCH_RULES, "scoreless_query_terms")
_extend_aliases(_KR_METADATA_ALIASES, _KR_METADATA_SEARCH_RULES)


def _metadata_token_variants(
    value: Any,
    *,
    expand_substrings: bool = False,
    expand_aliases: bool = True,
) -> set[str]:
    token = _norm(value)
    if not token or " " in token or token in _KR_METADATA_STOPWORDS:
        return set()

    variants = {token}
    if token.endswith(("고있음", "고있다", "고있는")) and len(token) > 4:
        variants.add(token[:-2])
        variants.add(token.replace("있음", "").replace("있다", "").replace("있는", ""))

    for suffix in _KR_METADATA_SUFFIXES:
        if token.endswith(suffix) and len(token) >= len(suffix) + 1:
            variants.add(token[: -len(suffix)])

    if expand_substrings and _HANGUL_RE.search(token) and 3 <= len(token) <= 8:
        for size in range(2, min(4, len(token)) + 1):
            for index in range(0, len(token) - size + 1):
                variants.add(token[index:index + size])

    expanded = set(variants)
    if expand_aliases:
        for variant in tuple(variants):
            expanded.update(_KR_METADATA_ALIASES.get(variant, ()))

    return {
        variant
        for variant in expanded
        if (len(variant) >= 2 or variant in _KR_METADATA_SINGLE_CHAR_TERMS)
        and variant not in _KR_METADATA_STOPWORDS
    }


def _metadata_terms(
    value: Any,
    *,
    include_compact: bool = True,
    expand_substrings: bool = False,
    expand_aliases: bool = True,
) -> frozenset[str]:
    text = _norm(value)
    if not text:
        return frozenset()

    terms: set[str] = set()
    for raw_token in _METADATA_TOKEN_RE.findall(text):
        terms.update(
            _metadata_token_variants(
                raw_token,
                expand_substrings=expand_substrings,
                expand_aliases=expand_aliases,
            )
        )

    if include_compact:
        compact = _compact_hangul(text)
        if compact and compact != text:
            terms.update(
                _metadata_token_variants(
                    compact,
                    expand_substrings=expand_substrings,
                    expand_aliases=expand_aliases,
                )
            )

    return frozenset(terms)


def _metadata_anchor_terms(value: Any) -> frozenset[str]:
    return frozenset(
        term
        for term in _metadata_terms(
            value,
            include_compact=False,
            expand_substrings=False,
            expand_aliases=False,
        )
        if term not in _KR_METADATA_WEAK_QUERY_TERMS
    )


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
        self._metadata_term_to_tags: dict[str, frozenset[str]] | None = None
        self._metadata_terms_by_tag: dict[str, dict[str, frozenset[str]]] | None = None
        self._metadata_text_by_tag: dict[str, dict[str, str]] | None = None
        self._metadata_index_lock = threading.Lock()

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

    def search_metadata_fallback(
        self,
        query: str,
        *,
        limit: int | None = 50,
        axes: set[str] | None = None,
        require_event: bool | None = None,
        sources: set[str] | None = None,
        cats: set[str] | None = None,
    ) -> list[TagSearchResult]:
        """Evidence-ranked fallback for natural Korean metadata queries.

        Unlike `search_semantic`, this never scans every tag blob at query time.
        It unions a field-aware metadata inverted index, then reranks candidates
        by phrase evidence and query term coverage.
        """
        q = normalize_search_query(query)
        if not q:
            return []
        query_terms = frozenset(
            term
            for term in _metadata_terms(q, include_compact=False)
            if term not in _KR_METADATA_SCORELESS_QUERY_TERMS
        )
        if not query_terms:
            return []
        anchor_terms = _metadata_anchor_terms(q)
        self._ensure_metadata_candidate_index()
        term_to_tags = self._metadata_term_to_tags or {}

        candidate_tags: set[str] = set()
        for term in query_terms:
            candidate_tags.update(term_to_tags.get(term, ()))
        if not candidate_tags:
            return []

        results: list[TagSearchResult] = []
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

            score = self._metadata_score(q, query_terms, anchor_terms, tag, entry)
            if score <= 0:
                continue
            results.append(TagSearchResult(tag=tag, score=score, entry=entry))

        results.sort(key=lambda r: (-r.score, -r.entry.freq, r.tag))
        if limit is not None:
            return results[:limit]
        return results

    def metadata_fallback_index_ready(self) -> bool:
        return self._metadata_term_to_tags is not None

    def warm_metadata_fallback_index(self) -> None:
        self._ensure_metadata_candidate_index()

    def _ensure_metadata_candidate_index(self) -> None:
        if self._metadata_term_to_tags is not None:
            return
        with self._metadata_index_lock:
            if self._metadata_term_to_tags is not None:
                return
            (
                self._metadata_term_to_tags,
                self._metadata_terms_by_tag,
                self._metadata_text_by_tag,
            ) = self._build_metadata_candidate_index()

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

    def _build_metadata_candidate_index(
        self,
    ) -> tuple[
        dict[str, frozenset[str]],
        dict[str, dict[str, frozenset[str]]],
        dict[str, dict[str, str]],
    ]:
        term_to_tags: dict[str, set[str]] = defaultdict(set)
        terms_by_tag: dict[str, dict[str, frozenset[str]]] = {}
        text_by_tag: dict[str, dict[str, str]] = {}

        for tag, entry in self._entries.items():
            field_text = {
                "tag": _norm(entry.tag),
                "keywords": _norm(" ".join(entry.keywords)),
                "desc": _norm(entry.desc),
                "category": _norm(entry.category),
            }
            field_terms = {
                field: _metadata_terms(
                    text,
                    expand_substrings=True,
                    expand_aliases=False,
                )
                for field, text in field_text.items()
                if text
            }
            terms_by_tag[tag] = field_terms
            text_by_tag[tag] = field_text

            for terms in field_terms.values():
                for term in terms:
                    term_to_tags[term].add(tag)

        return (
            {term: frozenset(tags) for term, tags in term_to_tags.items()},
            terms_by_tag,
            text_by_tag,
        )

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

    def _metadata_score(
        self,
        query: str,
        query_terms: frozenset[str],
        anchor_terms: frozenset[str],
        tag: str,
        entry: TagSearchEntry,
    ) -> float:
        field_terms = (self._metadata_terms_by_tag or {}).get(tag, {})
        field_text = (self._metadata_text_by_tag or {}).get(tag, {})
        if not field_terms:
            return 0.0

        matched_terms: set[str] = set()
        score = 0.0
        field_weights = {
            "tag": 95.0,
            "keywords": 140.0,
            "desc": 42.0,
            "category": 24.0,
        }
        for term in query_terms:
            for field, weight in field_weights.items():
                if term in field_terms.get(field, ()):
                    matched_terms.add(term)
                    score += weight
                    break

        compact_query = _compact_hangul(query)
        keyword_text = field_text.get("keywords", "")
        desc_text = field_text.get("desc", "")
        tag_text = field_text.get("tag", "")
        category_text = field_text.get("category", "")
        compact_keywords = _compact_hangul(keyword_text)
        compact_desc = _compact_hangul(desc_text)

        strong_phrase = False
        if query == tag_text:
            score += 1000
            strong_phrase = True
        elif tag_text.startswith(query):
            score += 780
            strong_phrase = True
        elif keyword_text and query in keyword_text:
            score += 720
            strong_phrase = True
        elif compact_query and compact_keywords and compact_query in compact_keywords:
            score += 680
            strong_phrase = True
        elif desc_text and query in desc_text:
            score += 420
            strong_phrase = True
        elif compact_query and compact_desc and compact_query in compact_desc:
            score += 360
            strong_phrase = True
        elif category_text and query in category_text:
            score += 120

        if not matched_terms and not strong_phrase:
            return 0.0

        if anchor_terms:
            matched_anchor_terms = {
                term
                for term in anchor_terms
                if any(term in field_terms.get(field, ()) for field in field_weights)
            }
            required_anchor_count = 1
            if len(matched_anchor_terms) < required_anchor_count and not strong_phrase:
                return 0.0
            score += len(matched_anchor_terms) * 36.0
            score += (len(matched_anchor_terms) / len(anchor_terms)) * 180.0

        query_size = min(len(query_terms), 4)
        coverage = len(matched_terms) / query_size if query_size else 0.0
        if len(query_terms) >= 2 and not strong_phrase:
            if len(matched_terms) < 2:
                tag_terms = field_terms.get("tag", ())
                keyword_terms = field_terms.get("keywords", ())
                if anchor_terms or not any(
                    term in tag_terms or term in keyword_terms for term in matched_terms
                ):
                    return 0.0

        score += coverage * 180.0
        score += len(matched_terms) * 18.0

        if entry.is_event:
            score += 28.0
        if entry.source == "KR_tags":
            score += 8.0
        category_text = field_text.get("category", "")
        if entry.cat in {"artist", "character", "copyright"}:
            score -= 220.0
        elif any(marker in category_text for marker in ("character", "copyright", "캐릭터", "등장인물")):
            score -= 180.0
        if entry.freq:
            score += min(math.log10(max(entry.freq, 0) + 1) * 3.0, 18.0)
        return score
