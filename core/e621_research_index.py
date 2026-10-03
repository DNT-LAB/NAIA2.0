"""In-memory research-only index, built on the first E621 module request.

No shared autocomplete imports, persistence, provider state or corpus I/O.
Exact identities are retained; normalization is only a search projection.
"""
from __future__ import annotations

import re
import heapq
from typing import Any

from core.site_tag_repository import collect_legacy_tags

TAG_NAME, KOREAN_NAME, KOREAN_KEYWORDS, KOREAN_DESCRIPTION, STORED_BODY = 1, 2, 4, 8, 16
MATCH_FIELDS = ((TAG_NAME, "tag_name"), (KOREAN_NAME, "korean_name"),
                (KOREAN_KEYWORDS, "korean_keywords"), (KOREAN_DESCRIPTION, "korean_description"),
                (STORED_BODY, "stored_body"))
HANGUL = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")


def search_key(value: Any) -> str:
    return " ".join(str(value or "").replace("_", " ").lower().split())


class E621ResearchIndex:
    def __init__(self, tree: dict, metadata: Any):
        self.metadata = metadata
        self.categories = []
        self.category_rows = {}
        self.folder_rows = {}
        for section in ("General", "Species"):
            section_data = tree.get(section, {})
            if not isinstance(section_data, dict):
                continue
            # Traversal order preserves the first native occurrence on dedup.
            for name, node in section_data.items():
                self.categories.append((section, name, len(node) if isinstance(node, dict) else 0))
                if isinstance(node, dict):
                    rows = []
                    for folder, child in node.items():
                        values = collect_legacy_tags(child)
                        self.folder_rows[(section, name, folder)] = values
                        rows.extend(values)
                else:
                    rows = collect_legacy_tags(node)
                self.category_rows[(section, name)] = rows
        # Metadata already owns the first native row for each exact identity.
        self.by_tag = metadata._native
        if set(tree) <= {"General", "Species"}:
            self.all_rows = list(self.by_tag.values())
        else:
            visible = {}
            for rows in self.category_rows.values():
                for row in rows:
                    visible.setdefault(row["tag"], row)
            self.all_rows = list(visible.values())
        # The first response needs 300 ranks, not a full sorted copy of 172k
        # rows. Later pages use the identical total ordering over this snapshot.
        self.first_page = heapq.nsmallest(300, self.all_rows, key=self.sort_key)
        # The exact-key dictionary is also the name index. Query the retained
        # names directly instead of allocating 172k normalized name copies.
        # Keep references to bodies, not another normalized corpus in memory.
        # Korean fields are small and prepared below; body case conversion is
        # done during a query so opening the module need not copy every wiki.
        self.bodies = {tag: str(self.by_tag[tag].get("wiki_body") or self.by_tag[tag].get("wiki_preview"))
                       for tag in metadata._body_tags if tag in self.by_tag}
        self.korean = {}
        for tag in metadata.search_field_tags:
            if tag in self.by_tag:
                normal = tuple(search_key(value) for value in metadata.search_fields(tag))
                self.korean[tag] = (*normal, *(value.replace(" ", "") for value in normal))
        self._query_key = None
        self._matches = None

    def matches(self, query: str, disable_wiki: bool) -> dict[str, tuple[int, int, int]] | None:
        """Return (field bits, compact-only bits, grade); cache one query only."""
        key = (query, disable_wiki)
        if key == self._query_key:
            return self._matches
        if not query:
            self._query_key, self._matches = key, None
            return None
        needle = search_key(query)
        compact = needle.replace(" ", "") if HANGUL.search(needle) else None
        pattern = re.compile(re.escape(needle).replace(r"\ ", r"[\s_]+")) if " " in needle else None
        matches = {tag: (TAG_NAME, 0, 0 if needle and needle == search_key(tag) else 1)
                   for tag in self.by_tag if (pattern.search(tag.lower()) if pattern else needle in tag.lower())}
        for tag, fields in self.korean.items():
            bits, compact_bits, direct_bits = 0, 0, 0
            for position, bit in ((0, KOREAN_NAME), (1, KOREAN_NAME), (2, KOREAN_DESCRIPTION), (3, KOREAN_KEYWORDS)):
                if fields[position] and needle in fields[position]:
                    bits |= bit
                    direct_bits |= bit
                elif compact is not None and fields[position + 4] and compact in fields[position + 4]:
                    bits |= bit
                    compact_bits |= bit
            if bits:
                previous = matches.get(tag, (0, 0, 1))
                matches[tag] = (previous[0] | bits, compact_bits & ~direct_bits, previous[2])
        if not disable_wiki:
            # Query whitespace matches runs of native whitespace/underscores.
            # This is equivalent to search_key(body) substring matching, without
            # copying/splitting every long body during module initialization.
            for tag, body in self.bodies.items():
                body = body.lower()
                if (pattern.search(body) if pattern else needle in body):
                    previous = matches.get(tag, (0, 0, 1))
                    matches[tag] = (previous[0] | STORED_BODY, previous[1], previous[2])
        self._query_key, self._matches = key, matches
        return matches

    def filter_rows(self, rows, *, content_filter, hidden, starred, starred_only, matches):
        allowed = self.metadata.content_tags(content_filter)
        without = content_filter == "without_description"
        body, described = self.metadata._body_tags, self.metadata._described
        return [row for row in rows
                if row["tag"] not in hidden
                and (not starred_only or row["tag"] in starred)
                and (allowed is None or row["tag"] in allowed)
                and (not without or (row["tag"] not in body and row["tag"] not in described))
                and (matches is None or row["tag"] in matches)]

    def visible(self, *, category, folder, content_filter, hidden, starred, starred_only, matches):
        if category:
            section = next((section for section in ("General", "Species") if (section, category) in self.category_rows), None)
            rows = (self.folder_rows.get((section, category, folder), []) if folder
                    else self.category_rows.get((section, category), []))
            # Dedup precedes pagination; preserve the first native membership.
            rows = list({row["tag"]: row for row in reversed(rows)}.values())
        else:
            rows = self.all_rows
        if matches is None and not category and content_filter == "all" and not hidden and not starred_only:
            return rows
        rows = self.filter_rows(rows, content_filter=content_filter, hidden=hidden,
                                starred=starred, starred_only=starred_only, matches=matches)
        rows.sort(key=lambda row: ((matches[row["tag"]][2] if matches is not None else 1),
                                  -int(row.get("count") or 0), row["tag"]))
        return rows

    @staticmethod
    def sort_key(row):
        return -int(row.get("count") or 0), row["tag"]

    def page(self, rows, offset, limit=300):
        if rows is self.all_rows:
            if offset == 0 and limit == 300:
                return self.first_page
            return sorted(rows, key=self.sort_key)[offset:offset + limit]
        return rows[offset:offset + limit]

    @staticmethod
    def match_payload(match):
        bits, compact, grade = match or (0, 0, None)
        korean = bits & (KOREAN_NAME | KOREAN_KEYWORDS | KOREAN_DESCRIPTION)
        return {"match_grade": grade,
                "match_fields": [name for bit, name in MATCH_FIELDS if bits & bit],
                "match_compact_fields": [name for bit, name in MATCH_FIELDS if compact & bit],
                "matched_in_korean": bool(not bits & TAG_NAME and korean),
                "matched_in_wiki": bool(not bits & TAG_NAME and not korean and bits & STORED_BODY)}
