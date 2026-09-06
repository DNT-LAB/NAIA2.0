"""Lazy, read-only search of bundled observed event combinations.

This catalog belongs to Ctrl+F only. It neither opens the optional Event Preset
archive nor changes the composer/Chat services. Counts describe observed rows,
not a confidence score or a guarantee that a combination fits a user's intent.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import threading


CATALOG_PATH = Path(__file__).with_suffix('.json')
_catalog = None
_load_lock = threading.Lock()


def normalize(text: str) -> str:
    return ' '.join(str(text or '').replace('_', ' ').casefold().split())


@dataclass(frozen=True, slots=True)
class Variant:
    partition: str
    tags: tuple[str, ...]
    count: int

    @property
    def rating(self) -> str:
        return self.partition.split('_', 1)[0]

    @property
    def person(self) -> str:
        return self.partition.split('_', 1)[1]

    @property
    def copy_tags(self) -> tuple[str, ...]:
        # Only the observed combination itself is a joint observation.
        # Do not append retained/inferred context to a bundled example.
        return self.tags


@dataclass(frozen=True, slots=True)
class Event:
    tag: str
    label: str
    terms: tuple[str, ...]
    variants: tuple[Variant, ...]


def load_catalog() -> tuple[Event, ...]:
    global _catalog
    if _catalog is None:
        with _load_lock:
            if _catalog is None:
                payload = json.loads(CATALOG_PATH.read_text(encoding='utf-8'))
                if payload.get('version') != 1:
                    raise ValueError('Unsupported Fast Search event catalog')
                events = []
                for tag, row in payload['events'].items():
                    variants = tuple(Variant(v['partition'], tuple(v['tags']), int(v['count']))
                                     for v in row['variants'])
                    events.append(Event(tag, row['label'],
                                        tuple(dict.fromkeys(normalize(t) for t in
                                              [tag, row['label'], *row['aliases']] if t)), variants))
                # Publish only a complete immutable catalog; concurrent cold
                # searches share one read and an unsuccessful read can retry.
                _catalog = tuple(events)
    return _catalog


def _match_rank(event: Event, query: str) -> int | None:
    if query == normalize(event.tag):
        return 0
    if query in event.terms:
        return 1
    if any(term.startswith(query) for term in event.terms):
        return 2
    if any(query in term for term in event.terms):
        return 3
    return None


def search_catalog(query: str, limit: int, *, rating: str = '', person: str = '') -> list[tuple[Event, Variant]]:
    query = normalize(query)
    if not query or limit <= 0:
        return []
    matches = []
    for event in load_catalog():
        rank = _match_rank(event, query)
        if rank is None:
            continue
        variants = [v for v in event.variants
                    if (not rating or v.rating == rating) and (not person or v.person == person)]
        variants.sort(key=lambda v: (-v.count, v.partition, v.tags))
        if variants:
            # Offer distinct person contexts before another rating of the
            # same context. Do not synthesize or append population tags.
            first, rest, persons = [], [], set()
            for variant in variants:
                (rest if variant.person in persons else first).append(variant)
                persons.add(variant.person)
            matches.append((rank, -variants[0].count, event, first + rest))
    matches.sort(key=lambda m: (m[0], m[1], m[2].tag))
    selected, seen = [], set()
    # Exact anchors win over loose matches. Within each rank, show different
    # anchors before filling remaining slots with further observed variants.
    for rank in sorted({m[0] for m in matches}):
        buckets = [(event, iter(variants)) for r, _, event, variants in matches if r == rank]
        while buckets and len(selected) < limit:
            remaining = []
            for event, variants in buckets:
                for variant in variants:
                    key = tuple(sorted(variant.copy_tags))
                    if key in seen:
                        continue
                    selected.append((event, variant))
                    seen.add(key)
                    remaining.append((event, variants))
                    break
                if len(selected) == limit:
                    break
            buckets = remaining
    return selected
