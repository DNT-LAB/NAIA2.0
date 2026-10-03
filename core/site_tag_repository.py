"""Exact site-qualified identities and lossless legacy taxonomy adapters.

This module has no corpus I/O, global registries, aliases or tag normalization.
Display/search normalization must never change a stored identity.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator


@dataclass(frozen=True, slots=True)
class SiteTagKey:
    site: str
    exact_tag: str

    def __post_init__(self) -> None:
        if not isinstance(self.site, str) or not self.site or self.site.strip() != self.site:
            raise ValueError("site must be a nonempty exact identifier")
        if not isinstance(self.exact_tag, str) or not self.exact_tag:
            raise ValueError("exact_tag must be a nonempty string")

    def payload(self) -> dict[str, str]:
        return {"site": self.site, "exact_tag": self.exact_tag}


def walk_legacy_tags(node: Any, path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], dict[str, Any]]]:
    if isinstance(node, dict):
        if node.get("tag"):
            yield path, node
        else:
            for name, value in node.items():
                yield from walk_legacy_tags(value, (*path, name))
    elif isinstance(node, list):
        for value in node:
            yield from walk_legacy_tags(value, path)


def collect_legacy_tags(node: Any) -> list[dict[str, Any]]:
    """Collect rows without allocating taxonomy paths for every dictionary read."""
    rows: list[dict[str, Any]] = []
    if isinstance(node, list):
        for item in node:
            if isinstance(item, dict) and item.get("tag"):
                rows.append(item)
            elif isinstance(item, (list, dict)):
                rows.extend(collect_legacy_tags(item))
    elif isinstance(node, dict):
        if node.get("tag"):
            rows.append(node)
        else:
            for value in node.values():
                rows.extend(collect_legacy_tags(value))
    return rows


class LegacyTagRepository:
    """A per-site dictionary, independent of the shared autocomplete loader."""

    def __init__(self, site: str, tree: dict[str, Any]):
        SiteTagKey(site, "validation")
        if not isinstance(tree, dict):
            raise ValueError("legacy taxonomy must be an object")
        self.site = site
        self.legacy_tree = tree
        self._records: dict[str, dict[str, Any]] | None = None
        self.rows = collect_legacy_tags(tree)

    def _index(self) -> dict[str, dict[str, Any]]:
        if self._records is not None:
            return self._records
        records = {}
        for row in self.rows:
            tag = row.get("tag")
            if not isinstance(tag, str) or not tag:
                raise ValueError("invalid legacy exact tag")
            records.setdefault(tag, row)
        self._records = records
        return records

    def get(self, key: SiteTagKey) -> dict[str, Any] | None:
        if key.site != self.site:
            return None
        row = self._index().get(key.exact_tag)
        return dict(row) if row is not None else None

    def keys(self) -> Iterator[SiteTagKey]:
        return (SiteTagKey(self.site, tag) for tag in self._index())


class TagClassificationRepository:
    """Ordered memberships; multiple paths and empty folders remain intact."""

    def __init__(self, dictionary: LegacyTagRepository):
        self.dictionary = dictionary

    def paths(self, key: SiteTagKey) -> tuple[tuple[str, ...], ...]:
        if key.site != self.dictionary.site:
            return ()
        return tuple(path for path, row in walk_legacy_tags(self.dictionary.legacy_tree)
                     if row.get("tag") == key.exact_tag)

    def subtree(self, path: tuple[str, ...]) -> Any:
        node: Any = self.dictionary.legacy_tree
        for name in path:
            if not isinstance(node, dict) or name not in node:
                return None
            node = node[name]
        return node
