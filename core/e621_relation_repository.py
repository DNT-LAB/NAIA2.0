"""Lazy, app-owned E621 relation data; this repository never rewrites prompts itself.

The small bundle contains exact pair observations, not multi-tag intersections.
This boundary has no UI and no dependency on the large index. E621EventService reads it
for the relation rows and for the visible, user-toggled auto-related assembly.
"""
from __future__ import annotations

from array import array
from copy import deepcopy
import json
import math
from pathlib import Path
import sys
from threading import Lock
from typing import Any
import zipfile

SCHEMA = "naia.e621-relations.v1"
PACK_NAME = "e621_relations.pack"
RATINGS = ("s", "q", "e")
MAX_PACK_BYTES = 10_000_000
MAX_UNPACKED_BYTES = 48_000_000


def _numpy():
    """Optional accelerator for bundle validation; the app already ships numpy, a bare checkout may not."""
    try:
        import numpy
    except Exception:
        return None
    return numpy


def _uint32(blob: bytes) -> array:
    values = array("I")
    if values.itemsize != 4 or len(blob) % 4:
        raise ValueError("invalid uint32 section")
    values.frombytes(blob)
    if sys.byteorder != "little":
        values.byteswap()
    return values


class E621RelationRepository:
    """Construction performs no reads. First query loads one complete revision.

    A present but invalid app-owned bundle fails closed; runtime copies cannot
    silently replace that revision. Missing/invalid results remain queryable.
    """

    def __init__(self, repo_root: Path, *, data_roots: list[Path] | None = None):
        self.repo_root = Path(repo_root)
        self.data_roots = list(dict.fromkeys([self.repo_root / "data", *[
            root if root.is_absolute() else self.repo_root / root
            for root in map(Path, data_roots or [])]]))
        self.loaded = False
        self.last_error: str | None = None
        self.source_path: Path | None = None
        self._attempted = False
        self._lock = Lock()
        self._meta: dict[str, Any] = {}
        self._names: list[str] = []
        self._ids: dict[str, int] = {}
        self._counts = array("I")
        self._offsets = array("I")
        self._edges = array("I")
        self._relations: dict[int, list[list[Any]]] = {}
        self._crosswalk: dict[str, list[dict[str, Any]]] = {}

    def load(self) -> bool:
        with self._lock:
            if self._attempted:
                return self.loaded
            self._attempted = True
            for root in self.data_roots:
                source = root / PACK_NAME
                if not source.exists():
                    continue
                self.source_path = source
                try:
                    if source.stat().st_size > MAX_PACK_BYTES:
                        raise ValueError("relation bundle exceeds size budget")
                    with zipfile.ZipFile(source) as pack:
                        if sum(member.file_size for member in pack.infolist()) > MAX_UNPACKED_BYTES:
                            raise ValueError("relation bundle expanded size exceeds budget")
                        meta = json.loads(pack.read("meta.json"))
                        names = json.loads(pack.read("tags.json"))
                        counts = _uint32(pack.read("tag_counts.u32"))
                        offsets = _uint32(pack.read("offsets.u32"))
                        edges = _uint32(pack.read("cooccurrence.u32"))
                        relations = json.loads(pack.read("relations.json"))
                        crosswalk = json.loads(pack.read("crosswalk.json"))
                    self._validate(meta, names, counts, offsets, edges, relations, crosswalk)
                    by_tag: dict[int, list[list[Any]]] = {}
                    for row in relations:
                        by_tag.setdefault(row[1], []).append(row)
                        if row[2] != row[1]:
                            by_tag.setdefault(row[2], []).append(row)
                    by_cross: dict[str, list[dict[str, Any]]] = {}
                    for row in crosswalk:
                        by_cross.setdefault(row["e621"], []).append(row)
                    self._meta, self._names = meta, names
                    self._ids = {tag: index for index, tag in enumerate(names)}
                    self._counts, self._offsets, self._edges = counts, offsets, edges
                    self._relations, self._crosswalk = by_tag, by_cross
                    self.loaded = True
                    return True
                except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError,
                        OverflowError, zipfile.BadZipFile, RuntimeError) as exc:
                    self.last_error = type(exc).__name__ + ": " + str(exc)
                    return False
            return False

    @staticmethod
    def _validate(meta, names, counts, offsets, edges, relations, crosswalk):
        if meta.get("schema") != SCHEMA or meta.get("site") != "e621":
            raise ValueError("unknown relation schema/site")
        if (not isinstance(names, list) or any(not isinstance(n, str) or not n for n in names)
                or names != sorted(set(names)) or len(names) != meta["vocabulary_count"]):
            raise ValueError("invalid exact product vocabulary")
        if (meta["rating_values"] != list(RATINGS)
                or set(meta["denominators"]) != set(RATINGS)
                or any(type(v) is not int or v < 0 for v in meta["denominators"].values())
                or sum(meta["denominators"].values()) != meta["total_posts"]
                or meta["total_posts"] <= 0):
            raise ValueError("invalid E621 denominators")
        if (len(counts) != len(names) * 3 or len(offsets) != len(names) + 1
                or len(edges) % 4 or offsets[0] != 0 or offsets[-1] != len(edges) // 4
                or any(a > b or b - a > meta["k"] for a, b in zip(offsets, offsets[1:]))):
            raise ValueError("invalid relation array shape or top K")
        denominators = [meta["denominators"][rating] for rating in RATINGS]
        np = _numpy()
        if np is not None:
            # Same checks as the loop below, on whole arrays: the per-edge loop cost ~0.5s of the
            # first relation query (240k edges). Every product stays below 2**53, so the float
            # lift equals the integer arithmetic of the loop.
            count_rows = np.frombuffer(counts, dtype=np.uint32).reshape(-1, 3)
            if (count_rows > np.array(denominators, dtype=np.uint64)).any():
                raise ValueError("tag count exceeds E621 rating denominator")
            edge_rows = np.frombuffer(edges, dtype=np.uint32).reshape(-1, 4)
            source = np.repeat(np.arange(len(names), dtype=np.int64), np.diff(np.frombuffer(offsets, dtype=np.uint32).astype(np.int64)))
            target = edge_rows[:, 0].astype(np.int64)
            if (target >= len(names)).any() or (target == source).any() or len(
                    np.unique(source * len(names) + target)) != len(target):
                raise ValueError("invalid or duplicate cooccurrence target")
            pairs = edge_rows[:, 1:]
            support = pairs.sum(axis=1, dtype=np.int64)
            if (support < meta["min_support"]).any() or (pairs > np.minimum(count_rows[source], count_rows[target])).any():
                raise ValueError("invalid cooccurrence count")
            totals = count_rows.sum(axis=1, dtype=np.int64)
            denominator = (totals[source] * totals[target]).astype(np.float64)
            if (denominator == 0).any() or (support * meta["total_posts"] / denominator < meta["min_lift"]).any():
                raise ValueError("cooccurrence does not meet lift floor")
        else:
            if any(count > denominators[index % 3] for index, count in enumerate(counts)):
                raise ValueError("tag count exceeds E621 rating denominator")
            for source in range(len(names)):
                seen = set()
                for record in range(offsets[source], offsets[source + 1]):
                    target, s, q, e = edges[record * 4:record * 4 + 4]
                    if target >= len(names) or target == source or target in seen:
                        raise ValueError("invalid or duplicate cooccurrence target")
                    seen.add(target)
                    support = s + q + e
                    if (support < meta["min_support"] or any(
                            value > min(counts[source * 3 + rating], counts[target * 3 + rating])
                            for rating, value in enumerate((s, q, e)))):
                        raise ValueError("invalid cooccurrence count")
                    denominator = sum(counts[source * 3:source * 3 + 3]) * sum(counts[target * 3:target * 3 + 3])
                    if not denominator or support * meta["total_posts"] / denominator < meta["min_lift"]:
                        raise ValueError("cooccurrence does not meet lift floor")
        for kind, source, target, source_id in relations:
            if kind not in ("alias", "implication") or not (0 <= source < len(names) and 0 <= target < len(names)):
                raise ValueError("invalid active relation")
        valid_names = set(names)
        for row in crosswalk:
            if (row["e621"] not in valid_names or row.get("review_status") != "root_definition_passage_review"
                    or row.get("source_site") != "e621" or row.get("target_site") != "danbooru"
                    or not isinstance(row.get("danbooru"), str) or not row["danbooru"]):
                raise ValueError("unreviewed or invalid crosswalk")

    def _base(self):
        self.load()
        return {
            "site": "e621", "available": self.loaded,
            "status": "available" if self.loaded else "invalid" if self.last_error else "missing",
            "schema": SCHEMA, "sources": deepcopy(self._meta.get("sources", {})),
            "automatic_rewrite_allowed": False, "edit_permission": False,
        }

    def _tag_counts(self, tag_id):
        return dict(zip(RATINGS, self._counts[tag_id * 3:tag_id * 3 + 3]))

    def _observations(self, tag_id):
        source_count = sum(self._counts[tag_id * 3:tag_id * 3 + 3])
        result = []
        for record in range(self._offsets[tag_id], self._offsets[tag_id + 1]):
            target, s, q, e = self._edges[record * 4:record * 4 + 4]
            target_count = sum(self._counts[target * 3:target * 3 + 3])
            result.append({
                "kind": "cooccurrence", "source": {"site": "e621", "exact_tag": self._names[tag_id]},
                "target": {"site": "e621", "exact_tag": self._names[target]},
                "pair_count": s + q + e, "pair_counts_by_rating": dict(zip(RATINGS, (s, q, e))),
                "source_counts_by_rating": self._tag_counts(tag_id),
                "target_counts_by_rating": self._tag_counts(target),
                "lift": (s + q + e) * self._meta["total_posts"] / (source_count * target_count),
                "count_exact": True, "semantic_approval": False,
            })
        return result

    def cooccurring(self, exact_tag: str) -> list[tuple[str, int, float, float, int]]:
        """Stored pair rows in pack rank order: (target, pair_count, share, lift, target_count).

        `share` = pair_count / source_count: how much of this tag's posts also carry the target.
        A lean read for ranking - `related()` builds a full evidence dict per row.
        """
        self.load()
        tag_id = self._ids.get(exact_tag) if self.loaded and isinstance(exact_tag, str) else None
        if tag_id is None:
            return []
        source_count = sum(self._counts[tag_id * 3:tag_id * 3 + 3])
        rows = []
        for record in range(self._offsets[tag_id], self._offsets[tag_id + 1]):
            target, s, q, e = self._edges[record * 4:record * 4 + 4]
            pair, target_count = s + q + e, sum(self._counts[target * 3:target * 3 + 3])
            rows.append((self._names[target], pair, pair / source_count,
                         pair * self._meta["total_posts"] / (source_count * target_count), target_count))
        return rows

    def implied(self, exact_tag: str) -> set[str]:
        """Every tag this tag implies, transitively (active implications inside the product vocabulary)."""
        self.load()
        start = self._ids.get(exact_tag) if self.loaded and isinstance(exact_tag, str) else None
        if start is None:
            return set()
        seen: set[int] = set()
        stack = [start]
        while stack:
            node = stack.pop()
            for kind, source, target, _ in self._relations.get(node, []):
                if kind == "implication" and source == node and target != start and target not in seen:
                    seen.add(target)
                    stack.append(target)
        return {self._names[index] for index in seen}

    def related(self, exact_tag: str) -> dict[str, Any]:
        if not isinstance(exact_tag, str) or not exact_tag:
            raise ValueError("exact_tag must be a nonempty exact string")
        result = {**self._base(), "exact_tag": exact_tag, "known_tag": exact_tag in self._ids,
                  "groups": {"aliases": [], "implications": [], "cooccurrences": [], "cross_site": []}}
        tag_id = self._ids.get(exact_tag)
        if tag_id is None:
            return result
        result["observations"] = {
            "site": "e621", "snapshot": self._meta["sources"]["observations"]["snapshot"],
            "denominators_by_rating": dict(self._meta["denominators"]),
            "total_posts": self._meta["total_posts"], "tag_counts_by_rating": self._tag_counts(tag_id),
            "rating_filter": None, "k": self._meta["k"], "min_support": self._meta["min_support"],
            "min_lift": self._meta["min_lift"], "rank": self._meta["rank"],
        }
        for kind, source, target, source_id in self._relations.get(tag_id, []):
            result["groups"]["aliases" if kind == "alias" else "implications"].append({
                "kind": "input_normalization_suggestion" if kind == "alias" else "implication",
                "upstream_relation": kind, "upstream_status": "active", "source_id": source_id,
                "source": {"site": "e621", "exact_tag": self._names[source]},
                "target": {"site": "e621", "exact_tag": self._names[target]},
                "direction": "outgoing" if source == tag_id else "incoming",
                "automatic_rewrite_allowed": False,
            })
        result["groups"]["cooccurrences"] = self._observations(tag_id)
        for row in self._crosswalk.get(exact_tag, []):
            result["groups"]["cross_site"].append({**deepcopy(row), "kind": "cross_site_review",
                "automatic_rewrite_allowed": False, "translation_transfer_allowed": False,
                "edit_permission": False})
        return result

    def suggest(self, selected_tags: list[str], *, limit: int = 30) -> dict[str, Any]:
        if (not isinstance(selected_tags, (list, tuple)) or len(selected_tags) > 64
                or any(not isinstance(tag, str) or not tag for tag in selected_tags)):
            raise ValueError("selected_tags must contain at most 64 exact tag strings")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer between 1 and 100")
        selected = list(dict.fromkeys(selected_tags))
        result = {**self._base(), "selected_tags": selected, "approximate": True,
                  "method": "stored_pair_union", "joint_count": None,
                  "missing_tags": [tag for tag in selected if tag not in self._ids],
                  "candidates": []}
        if not selected or not self.loaded:
            return result
        by_candidate: dict[str, list[dict[str, Any]]] = {}
        for source in selected:
            tag_id = self._ids.get(source)
            if tag_id is None:
                continue
            for evidence in self._observations(tag_id):
                candidate = evidence["target"]["exact_tag"]
                if candidate not in selected:
                    by_candidate.setdefault(candidate, []).append(evidence)
        candidates = []
        for tag, evidence in by_candidate.items():
            candidates.append({"site": "e621", "exact_tag": tag, "approximate": True,
                "matched_anchor_count": len(evidence), "selected_anchor_count": len(selected),
                "pair_lift_score": sum(math.log2(row["lift"]) for row in evidence) / len(selected),
                "pair_evidence": evidence, "joint_count": None, "semantic_approval": False})
        candidates.sort(key=lambda row: (-row["matched_anchor_count"], -row["pair_lift_score"], row["exact_tag"]))
        result["candidates"] = candidates[:limit]
        result["observations"] = {"site": "e621", "denominators_by_rating": dict(self._meta["denominators"]),
                                  "total_posts": self._meta["total_posts"], "rating_filter": None}
        return result
