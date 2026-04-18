from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().lower().replace("_", " ").split())


def has_hangul(text: str) -> bool:
    return any("\uac00" <= char <= "\ud7a3" for char in str(text or ""))


def tokenize(text: str) -> list[str]:
    return [token for token in normalize_text(text).split(" ") if token]


def score_match(candidate: str, query: str) -> tuple[int, list[str]]:
    candidate_norm = normalize_text(candidate)
    query_norm = normalize_text(query)
    if not candidate_norm or not query_norm:
        return 0, []

    score = 0
    reasons: list[str] = []

    if candidate_norm == query_norm:
        score += 200
        reasons.append("exact")
    elif candidate_norm.startswith(query_norm):
        score += 120
        reasons.append("prefix")
    elif query_norm in candidate_norm:
        score += 85
        reasons.append("contains")
    elif candidate_norm in query_norm:
        score += 35
        reasons.append("query_contains_candidate")

    query_tokens = tokenize(query_norm)
    candidate_tokens = set(tokenize(candidate_norm))
    overlap = [token for token in query_tokens if token in candidate_tokens]
    if overlap:
        score += len(overlap) * 18
        reasons.append(f"token_overlap:{len(overlap)}")

    return score, reasons


@dataclass(frozen=True)
class ResolverHit:
    source: str
    path: str
    tag: str
    normalized_tag: str
    score: int
    reason: list[str] = field(default_factory=list)
    match_blob: str = ""
    count: int | None = None
    category: str | None = None
    description: str | None = None
    keywords: str | None = None
    group: str | None = None
    subgroup: str | None = None
    source_type: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reason"] = list(self.reason)
        return payload


class TagResolver:
    """Resolve Korean/English tag queries against local NAIA2.0 assets."""

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = Path(base_dir or Path(__file__).resolve().parents[1])
        self.data_dir = self.base_dir / "data"
        self.ui_dir = self.base_dir / "ui"
        self._kr_cache: dict[str, pd.DataFrame] = {}
        self._interactive_cache: dict[str, dict[str, Any]] | None = None
        self._taglist_cache: dict[str, list[dict[str, Any]]] | None = None
        self._line_cache: dict[str, list[str]] = {}

    def resolve(
        self,
        query: str,
        *,
        limit: int = 20,
        sources: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        query = str(query or "").strip()
        if not query:
            return {
                "status": "error",
                "error": "query is required",
                "message": "query is required",
            }

        enabled_sources = set(sources or {"kr", "e621_kr", "interactive", "taglists", "clothes", "characteristic"})
        hits: list[ResolverHit] = []

        if "kr" in enabled_sources:
            hits.extend(self._search_kr_dataset("kr", self.data_dir / "KR_tags.parquet", query, limit))
        if "e621_kr" in enabled_sources:
            hits.extend(self._search_kr_dataset("e621_kr", self.data_dir / "e621_KR_tags.parquet", query, limit))
        if "interactive" in enabled_sources:
            hits.extend(self._search_interactive(query, limit))
        if "taglists" in enabled_sources:
            hits.extend(self._search_taglists(query, limit))
        if "clothes" in enabled_sources:
            hits.extend(self._search_line_file("clothes", self.data_dir / "clothes_list.txt", query, limit))
        if "characteristic" in enabled_sources:
            hits.extend(self._search_line_file("characteristic", self.data_dir / "characteristic_list.txt", query, limit))

        deduped = self._dedupe_hits(hits)
        deduped.sort(key=lambda item: (-item.score, -(item.count or 0), item.tag))
        top_hits = deduped[:limit]

        return {
            "status": "success",
            "query": query,
            "normalized_query": normalize_text(query),
            "language_hint": "ko" if has_hangul(query) else "en",
            "base_dir": str(self.base_dir),
            "source_paths": {
                "kr": str(self.data_dir / "KR_tags.parquet"),
                "e621_kr": str(self.data_dir / "e621_KR_tags.parquet"),
                "interactive": str(self.ui_dir / "interactive" / "interactive"),
                "clothes": str(self.data_dir / "clothes_list.txt"),
                "characteristic": str(self.data_dir / "characteristic_list.txt"),
                "taglists": str(self.data_dir / "taglist"),
            },
            "hit_count": len(top_hits),
            "hits": [hit.to_payload() for hit in top_hits],
            "summary": self._summarize_hits(top_hits),
        }

    def trace_tag(self, query: str, *, limit: int = 20) -> dict[str, Any]:
        return self.resolve(query, limit=limit)

    def _search_kr_dataset(self, source: str, path: Path, query: str, limit: int) -> list[ResolverHit]:
        if not path.exists():
            return []

        df = self._kr_cache.get(source)
        if df is None:
            df = pd.read_parquet(path).copy()
            for column in ("tag", "category", "desc", "keywords"):
                if column not in df.columns:
                    df[column] = ""
            df["_tag_norm"] = df["tag"].map(normalize_text)
            df["_blob"] = (
                df["tag"].map(normalize_text)
                + " "
                + df["category"].map(normalize_text)
                + " "
                + df["desc"].map(normalize_text)
                + " "
                + df["keywords"].map(normalize_text)
            )
            self._kr_cache[source] = df

        query_norm = normalize_text(query)
        mask = df["_blob"].str.contains(query_norm, na=False, regex=False)
        rows = df.loc[mask].head(max(limit * 6, 60))
        hits: list[ResolverHit] = []

        for _, row in rows.iterrows():
            tag_score, tag_reason = score_match(row["_tag_norm"], query_norm)
            blob_score, blob_reason = score_match(row["_blob"], query_norm)
            score = max(tag_score, 0) + max(blob_score // 2, 0)
            if score <= 0:
                continue
            if row["_tag_norm"] == query_norm:
                score += 25

            hits.append(
                ResolverHit(
                    source=source,
                    path=str(path),
                    tag=str(row["tag"]),
                    normalized_tag=str(row["_tag_norm"]),
                    score=score,
                    reason=tag_reason + blob_reason,
                    match_blob=str(row["_blob"]),
                    count=int(row["count"]) if pd.notna(row["count"]) else None,
                    category=str(row["category"] or ""),
                    description=str(row["desc"] or ""),
                    keywords=str(row["keywords"] or ""),
                )
            )

        return hits

    def _search_interactive(self, query: str, limit: int) -> list[ResolverHit]:
        path = self.ui_dir / "interactive" / "interactive"
        if not path.exists():
            return []

        catalog = self._load_interactive_catalog()
        query_norm = normalize_text(query)
        hits: list[ResolverHit] = []

        for tag, item in catalog.items():
            tag_norm = normalize_text(tag)
            blob = " ".join(
                filter(
                    None,
                    [
                        tag_norm,
                        normalize_text(item.get("group")),
                        normalize_text(item.get("subgroup")),
                        normalize_text(item.get("description")),
                        normalize_text(item.get("keywords_kr")),
                    ],
                )
            )
            if query_norm not in blob:
                continue
            tag_score, tag_reason = score_match(tag_norm, query_norm)
            blob_score, blob_reason = score_match(blob, query_norm)
            score = tag_score + blob_score // 2 + 12
            if score <= 0:
                continue
            hits.append(
                ResolverHit(
                    source="interactive",
                    path=str(path),
                    tag=tag,
                    normalized_tag=tag_norm,
                    score=score,
                    reason=tag_reason + blob_reason,
                    match_blob=blob,
                    count=int(item.get("freq", 0) or 0),
                    description=str(item.get("description") or ""),
                    keywords=str(item.get("keywords_kr") or ""),
                    group=str(item.get("group") or ""),
                    subgroup=str(item.get("subgroup") or ""),
                    source_type=str(item.get("source") or ""),
                )
            )

        return hits[: max(limit * 4, 40)]

    def _search_taglists(self, query: str, limit: int) -> list[ResolverHit]:
        hits: list[ResolverHit] = []
        query_norm = normalize_text(query)

        for entry in self._load_taglists():
            tag_score, tag_reason = score_match(entry["tag_norm"], query_norm)
            blob_score, blob_reason = score_match(entry["blob"], query_norm)
            if tag_score <= 0 and blob_score <= 0:
                continue
            score = tag_score + blob_score // 2 + 8
            hits.append(
                ResolverHit(
                    source="taglists",
                    path=entry["path"],
                    tag=entry["tag"],
                    normalized_tag=entry["tag_norm"],
                    score=score,
                    reason=tag_reason + blob_reason,
                    match_blob=entry["blob"],
                    category=entry.get("category"),
                    group=entry.get("group"),
                    extra={"taglist_kind": entry.get("kind")},
                )
            )

        return hits[: max(limit * 4, 40)]

    def _search_line_file(self, source: str, path: Path, query: str, limit: int) -> list[ResolverHit]:
        if not path.exists():
            return []
        lines = self._line_cache.get(source)
        if lines is None:
            lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self._line_cache[source] = lines

        query_norm = normalize_text(query)
        hits: list[ResolverHit] = []
        for tag in lines:
            tag_norm = normalize_text(tag)
            if query_norm not in tag_norm:
                continue
            score, reasons = score_match(tag_norm, query_norm)
            if score <= 0:
                continue
            hits.append(
                ResolverHit(
                    source=source,
                    path=str(path),
                    tag=tag,
                    normalized_tag=tag_norm,
                    score=score + 6,
                    reason=reasons,
                    match_blob=tag_norm,
                )
            )

        return hits[: max(limit * 4, 40)]

    def _load_interactive_catalog(self) -> dict[str, Any]:
        if self._interactive_cache is None:
            path = self.ui_dir / "interactive" / "interactive"
            self._interactive_cache = json.loads(path.read_text(encoding="utf-8"))
        return self._interactive_cache

    def _load_taglists(self) -> list[dict[str, Any]]:
        if self._taglist_cache is not None:
            return self._taglist_cache["entries"]

        taglist_dir = self.data_dir / "taglist"
        entries: list[dict[str, Any]] = []
        specs = [
            ("expression_tags.json", self._parse_expression_tags),
            ("pose_action_tags.json", self._parse_pose_action_tags),
            ("location_tags.json", self._parse_flat_tags),
            ("object_tags.json", self._parse_flat_tags),
            ("meta_tags.json", self._parse_flat_tags),
            ("unique_tags.json", self._parse_flat_tags),
        ]

        for filename, parser in specs:
            path = taglist_dir / filename
            if not path.exists():
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            entries.extend(parser(path, payload))

        self._taglist_cache = {"entries": entries}
        return entries

    def _parse_expression_tags(self, path: Path, payload: dict[str, Any]) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for group, tags in payload.get("groups", {}).items():
            for tag in tags:
                tag_norm = normalize_text(tag)
                entries.append(
                    {
                        "path": str(path),
                        "kind": "expression_group",
                        "tag": str(tag),
                        "tag_norm": tag_norm,
                        "blob": f"{tag_norm} {normalize_text(group)} expression",
                        "group": str(group),
                    }
                )
        for tag in payload.get("modifiers", []):
            tag_norm = normalize_text(tag)
            entries.append(
                {
                    "path": str(path),
                    "kind": "expression_modifier",
                    "tag": str(tag),
                    "tag_norm": tag_norm,
                    "blob": f"{tag_norm} modifier expression",
                    "group": "modifier",
                }
            )
        return entries

    def _parse_pose_action_tags(self, path: Path, payload: dict[str, Any]) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for category, tags in payload.get("categories", {}).items():
            for tag in tags:
                tag_norm = normalize_text(tag)
                entries.append(
                    {
                        "path": str(path),
                        "kind": "pose_action",
                        "tag": str(tag),
                        "tag_norm": tag_norm,
                        "blob": f"{tag_norm} {normalize_text(category)} pose action",
                        "category": str(category),
                    }
                )
        for tag in payload.get("uncategorized", []):
            tag_norm = normalize_text(tag)
            entries.append(
                {
                    "path": str(path),
                    "kind": "pose_action_uncategorized",
                    "tag": str(tag),
                    "tag_norm": tag_norm,
                    "blob": f"{tag_norm} pose action",
                    "category": "uncategorized",
                }
            )
        return entries

    def _parse_flat_tags(self, path: Path, payload: dict[str, Any]) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for tag in payload.get("tags", []):
            tag_norm = normalize_text(tag)
            entries.append(
                {
                    "path": str(path),
                    "kind": path.stem,
                    "tag": str(tag),
                    "tag_norm": tag_norm,
                    "blob": f"{tag_norm} {normalize_text(path.stem)}",
                    "category": path.stem,
                }
            )
        return entries

    def _dedupe_hits(self, hits: list[ResolverHit]) -> list[ResolverHit]:
        by_key: dict[tuple[str, str], ResolverHit] = {}
        for hit in hits:
            key = (hit.source, hit.tag)
            prev = by_key.get(key)
            if prev is None or hit.score > prev.score:
                by_key[key] = hit
        return list(by_key.values())

    def _summarize_hits(self, hits: list[ResolverHit]) -> dict[str, Any]:
        source_counts: dict[str, int] = {}
        top_tags: list[str] = []
        for hit in hits:
            source_counts[hit.source] = source_counts.get(hit.source, 0) + 1
            if len(top_tags) < 8:
                top_tags.append(hit.tag)
        return {
            "source_counts": source_counts,
            "top_tags": top_tags,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve Korean/English tags against local NAIA2.0 assets.")
    parser.add_argument("query", help="Tag or natural-language tag-like query.")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--base-dir", default=None)
    args = parser.parse_args()

    resolver = TagResolver(base_dir=Path(args.base_dir) if args.base_dir else None)
    payload = resolver.resolve(args.query, limit=args.limit)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
