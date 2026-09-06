"""Lazy, read-only search of bundled observed event combinations.

Ctrl+F and Chat share this lookup. It never opens the optional Event Preset
archive. Counts describe observed rows,
not a confidence score or a guarantee that a combination fits a user's intent.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from sys import intern
import threading


CATALOG_PATH = Path(__file__).with_suffix('.json')
DEEP_CATALOG_PATH = Path(__file__).with_name('fast_search_catalog_deep.json')
PERSON_IDS = ('1girl_solo', '1girl', '1girl_1boy', '1girl_multiple_boys',
              '2girls', 'multiple_girls', '1boy_solo', '1boy', '1boy_multiple_girls',
              '2boys', 'multiple_boys', 'multiple_girls_multiple_boys', 'other')
RATING_IDS = ('g', 's', 'q', 'e')
_catalog = None
_deep_catalog = None
_load_lock = threading.Lock()
_tag_indexes = {}


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


def load_catalog(detail: str = 'basic') -> tuple[Event, ...]:
    global _catalog, _deep_catalog
    if detail not in {'basic', 'deep'}:
        raise ValueError('Unknown event detail')
    cached = _catalog if detail == 'basic' else _deep_catalog
    if cached is None:
        with _load_lock:
            cached = _catalog if detail == 'basic' else _deep_catalog
            if cached is None:
                path = CATALOG_PATH if detail == 'basic' else DEEP_CATALOG_PATH
                payload = json.loads(path.read_text(encoding='utf-8'))
                if payload.get('version') != 1:
                    raise ValueError('Unsupported Fast Search event catalog')
                events = []
                for tag, row in payload['events'].items():
                    # The same bounded vocabulary appears in thousands of rows.
                    # Share strings instead of retaining each JSON occurrence.
                    variants = tuple(Variant(intern(v['partition']), tuple(intern(t) for t in v['tags']), int(v['count']))
                                     for v in row['variants'])
                    events.append(Event(tag, row['label'],
                                        tuple(dict.fromkeys(normalize(t) for t in
                                              [tag, row['label'], *row['aliases']] if t)), variants))
                # Publish only a complete immutable catalog; concurrent cold
                # searches share one read and an unsuccessful read can retry.
                cached = tuple(events)
                if detail == 'basic':
                    _catalog = cached
                else:
                    _deep_catalog = cached
    return cached


def _compound_candidates(events, terms, detail):
    """Intersect literal tag/declared-alias postings, only built for multi-tag input."""
    with _load_lock:
        existing = _tag_indexes.get(detail)
        if existing is None or existing[0] is not events:
            postings, aliases, rows = {}, {}, []
            for ei, event in enumerate(events):
                for term in event.terms:
                    aliases.setdefault(term, set()).add(normalize(event.tag))
                for variant in event.variants:
                    row_id = len(rows)
                    rows.append((ei, variant))
                    for tag in variant.tags:
                        # Reuse one integer per row in all of its tag postings.
                        postings.setdefault(normalize(tag), set()).add(row_id)
            existing = (events, postings, aliases, rows)
            _tag_indexes[detail] = existing
    _, postings, aliases, rows = existing
    candidates = None
    for term in terms:
        targets = {term} if term in postings else aliases.get(term, {term})
        hits = set().union(*(postings.get(tag, set()) for tag in targets))
        candidates = hits if candidates is None else candidates & hits
        if not candidates:
            return {}
    grouped = {}
    for row_id in sorted(candidates):
        ei, variant = rows[row_id]
        grouped.setdefault(ei, []).append(variant)
    return grouped


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


def search_catalog(query: str, limit: int, *, rating: str = '', person: str = '',
                   detail: str = 'basic') -> list[tuple[Event, Variant]]:
    # Comma-separated tags are a set of required conditions, never a prompt
    # assembled from independent observations. Order cannot alter selection.
    terms = tuple(sorted({normalize(t) for t in str(query).split(',') if normalize(t)}))
    if not terms or limit <= 0:
        return []
    if (rating and rating not in RATING_IDS) or (person and person not in PERSON_IDS):
        return []
    events = load_catalog(detail)
    compound = _compound_candidates(events, terms, detail) if len(terms) > 1 else None
    matches = []
    candidates = enumerate(events) if compound is None else ((ei, events[ei]) for ei in compound)
    for ei, event in candidates:
        if compound is None:
            rank = _match_rank(event, terms[0])
        else:
            ranks = (_match_rank(event, term) for term in terms)
            rank = min((r for r in ranks if r is not None), default=None)
        if compound is None and rank is None:
            continue
        variants = [v for v in (compound.get(ei, ()) if compound is not None else event.variants)
                    if (not rating or v.rating == rating) and (not person or v.person == person)]
        variants.sort(key=lambda v: (-v.count, v.partition, v.tags))
        if variants:
            # Offer distinct person contexts before another rating of the
            # same context. Do not synthesize or append population tags.
            first, rest, persons = [], [], set()
            for variant in variants:
                (rest if variant.person in persons else first).append(variant)
                persons.add(variant.person)
            matches.append((rank if rank is not None else 4, -variants[0].count, event, first + rest))
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
