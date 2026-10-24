"""Live-pool event compression. No generated-prompt rules are duplicated here.

The worker owns expensive tokenization/grouping. The context pool lock owns
publication; generation, assignment revision, PE signature and request sequence
must all match before a result can change the live pool. Read-only analysis may
be published across consumption, but never across an assignment/settings change.
"""
from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
from itertools import chain, islice
from bisect import bisect_left, bisect_right
from collections import Counter

import numpy as np

from core.event_map.pe_filter import _pe_options, _category_overrides, _filter_manager
from core.tag_filter_helpers import apply_tag_filters, compile_hide_pattern
from core.wildcard_processor import split_tags_smart

EVENT_COMPRESS_ROW_LIMIT = 500_000

OPTIONS = (
    "remove_character_features", "remove_clothes", "remove_clothing_event",
    "remove_color", "remove_location_and_background_color", "remove_expression",
    "remove_pose_action", "remove_meta_tags", "remove_object_tags", "remove_noise_tags",
)
ROUNDS = ("auto_hide", "category_hide", *OPTIONS)
PEOPLE_COUNT_TAGS = frozenset({
    "solo", "solo focus", "1girl", "2girls", "3girls", "4girls", "5girls", "6+girls",
    "multiple girls", "1boy", "2boys", "3boys", "4boys", "5boys", "6+boys",
    "multiple boys", "1other", "2others", "3others", "4others", "5others", "6+others",
    "multiple others", "no humans",
})
_CREATE_LOCK = threading.Lock()


class _AnalysisCancelled(Exception):
    """An obsolete/deferred analysis must never publish partial results."""


def _cooperative(rows, checkpoint=None):
    """C-level iteration within each batch avoids a Python yield per row."""
    def batches():
        iterator = iter(rows)
        while True:
            if checkpoint is not None:
                checkpoint()
            time.sleep(0)
            if checkpoint is not None:
                checkpoint()
            batch = tuple(islice(iterator, 2000))
            if not batch:
                return
            yield batch
    return chain.from_iterable(batches())


def _is_people_tag(tag):
    return tag.lower().replace("_", " ") in PEOPLE_COUNT_TAGS


def _frequency_metadata(groups, tag_index, checkpoint=None):
    """Build immutable request inputs once, before publishing an analysis."""
    frequencies = {tag: len(keys) for tag, keys in _cooperative(tag_index.items(), checkpoint)}
    non_people = {tag: freq for tag, freq in _cooperative(frequencies.items(), checkpoint) if not _is_people_tag(tag)}
    group_frequencies = {}
    for key, group in _cooperative(groups.items(), checkpoint):
        values = sorted(non_people[tag] for tag in group["tag_set"] if tag in non_people)
        group_frequencies[key] = (group["tag_count"] - len(values), values)
    histogram = Counter(non_people.values())
    return (frequencies, group_frequencies,
            {str(n): histogram[n] for n in sorted(histogram)},
            min(histogram, default=0), max(histogram, default=0))


def pe_settings(context):
    raw = _pe_options(context)
    options = {key: bool((raw.get("preprocessing_options") or {}).get(
        key, key == "remove_meta_tags")) for key in OPTIONS}
    auto_hide = list(raw.get("auto_hide") or [])
    overrides = copy.deepcopy(_category_overrides(context))
    signature = hashlib.sha256(json.dumps(
        [options, auto_hide, overrides], sort_keys=True, ensure_ascii=True,
    ).encode()).hexdigest()
    return signature, options, auto_hide, overrides


def filter_rows(rows, options, auto_hide, manager, overrides, checkpoint=None):
    """Union-once fast path; replay ONLY context-sensitive rounds when needed.

    Auto Hide patterns remove one occurrence, not all duplicates. Round includes
    deduplicate by lower-case name, so multiplicity/case aliases are contextual.
    Dictionary, color exceptions, category hide and noise whitelist are unary.
    """
    union = list(dict.fromkeys(tag for row in _cooperative(rows, checkpoint) for tag in row))
    aliases = len({t.strip().lower() for t in union}) != len(union)
    duplicates = any(len(set(row)) != len(row) for row in _cooperative(rows, checkpoint))
    special = set()
    if duplicates and any(compile_hide_pattern(t) for t in auto_hide if not t.startswith("~")):
        special.add("auto_hide")
    if aliases or duplicates:
        special.update(key for key in OPTIONS[:-1] if options[key]
                       and (overrides.get(key) or {}).get("include"))

    def run(tags, rounds=None):
        tags = list(tags)
        apply_tag_filters(tags, [], options, auto_hide, manager,
                          category_overrides=overrides, only_rounds=rounds, quiet=True)
        return tags

    if not special:
        kept = set(run(union))
        return [tuple(t for t in row if t in kept) for row in _cooperative(rows, checkpoint)], special
    # Keep round order. A prior contextual round can leave a tag in only some
    # rows; each later unary segment therefore uses the union of CURRENT rows.
    current = rows
    pending = []
    for key in (*ROUNDS, None):
        if key is not None and key not in special:
            pending.append(key)
            continue
        if pending:
            union = list(dict.fromkeys(t for row in _cooperative(current, checkpoint) for t in row))
            kept = set(run(union, set(pending)))
            current = [tuple(t for t in row if t in kept) for row in _cooperative(current, checkpoint)]
            pending = []
        if key is not None:
            current = [tuple(run(row, {key})) for row in _cooperative(current, checkpoint)]
    return current, special


def _runtime():
    # Lazy import avoids the search runtime / context import cycle.
    from app.backend.server import search_runtime
    return search_runtime


def enabled(context):
    return bool((getattr(context, "search_filter_state", None) or {}).get("event_compress", False))


def ensure_event_compress(context):
    with _CREATE_LOCK:
        service = getattr(context, "_event_compress", None)
        if service is None:
            service = EventCompress(context)
            context._event_compress = service
        return service


def request_event_compress(context):
    """No work or messages on the legacy disabled path."""
    if enabled(context):
        ensure_event_compress(context).request()


def check_event_compress(context):
    """Cheap signature/identity check before Random, including Quick Presets."""
    if enabled(context):
        service = ensure_event_compress(context)
        if service.is_stale() and not service.computing:
            service.request()


class CommitError(ValueError):
    def __init__(self, code, message, status):
        super().__init__(message)
        self.code, self.status = code, status


class EventCompress:
    def __init__(self, context):
        self.context = context
        self.sequence = 0
        self.computing = False
        self._worker_running = False
        self.done = threading.Event()
        self.done.set()
        self.identity = None
        self.signature = None
        self.groups = {}
        self._page_cache = None
        # Bumped on every published analysis - the window relists on it even when the counts match.
        self.analysis = 0
        self.sorted_groups = {"asc": [], "desc": []}
        self.tag_index = {}
        self.group_tag_counts = {}
        self.tag_count_hist = {}
        self.tag_count_min = 0
        self.tag_count_max = 0
        self.tag_frequencies = {}
        self.group_frequencies = {}
        self.tag_freq_hist = {}
        self.tag_freq_min = 0
        self.tag_freq_max = 0
        self._effective_cache = None
        self.size_hist = {}
        self.size_min = 0
        self.size_max = 0
        self.dropped = set()
        self.token_cache = {}
        self.cache_generation = None
        self.error = None
        self.sample = None
        self.per_row_rounds = set()

    def guard(self):
        return _runtime().search_pool_state_guard(self.context)

    def _identity(self):
        ctx = self.context
        model = getattr(ctx, "search_results", None)
        if model is not None:
            model._event_compress_guard = self.guard()
            model._event_compress_in_flight = lambda: self.computing
            model._event_compress_on_change = lambda: request_event_compress(ctx)
        active = getattr(ctx, "active_tag_filter", None)
        ids = getattr(ctx, "active_tag_filter_ids", None)
        if not isinstance(active, dict) and ids is not None:
            active = {"ids": set(ids), "count": len(ids), "tags": [], "rating_counts": {}}
            ctx.active_tag_filter = active
        scope = "tag_filter" if isinstance(active, dict) or ids is not None else "search_pool"
        return (_runtime().current_search_pool_generation(ctx), scope,
                id(active) if isinstance(active, dict) else id(ids) if ids is not None else id(model),
                0 if scope == "tag_filter" else getattr(model, "_event_compress_version", 0))

    def is_stale(self):
        with self.guard():
            return self.identity != self._identity() or self.signature != pe_settings(self.context)[0]

    def request(self):
        with self.guard():
            self.sequence += 1
            self.computing = True
            self.error = None
            self.done.clear()
            if not self._worker_running and not _runtime().is_pool_busy(self.context):
                self._worker_running = True
                self._notify()
                threading.Thread(target=self._worker, name="naia-event-compress", daemon=True).start()
            elif _runtime().is_pool_busy(self.context):
                self._notify()

    def pool_busy_changed(self):
        # Called under the same pool guard as worker start/publication.
        if _runtime().is_pool_busy(self.context):
            if self.computing or self.is_stale():
                self.request()
        elif self.computing or self.is_stale():
            running = self._worker_running
            self.request()
            if running:
                self._notify()

    def _checkpoint(self, stamp):
        if _runtime().is_pool_busy(self.context):
            raise _AnalysisCancelled()
        with self.guard():
            current = (self._identity(), self._revision(), stamp[2], self.sequence)
            if _runtime().is_pool_busy(self.context) or not self._can_publish(stamp, current):
                raise _AnalysisCancelled()

    def refresh(self):
        if self.is_stale():
            self.request()
        self.done.wait()
        if self.error:
            raise RuntimeError(self.error)
        return self.state()

    def toggle(self, value):
        with self.guard():
            self.context.save_search_filter_state(event_compress=value)
            self.sequence += 1
            if not value:
                self._restore()
                self._clear_token_cache()
                self._notify(pool_changed=True)
        if value:
            self.request()
        return self.state()

    def _clear_token_cache(self):
        self.token_cache = {}
        self.cache_generation = None

    def _live_ids(self):
        active = getattr(self.context, "active_tag_filter", None)
        return set(active.get("ids") or ()) if isinstance(active, dict) else set(
            getattr(self.context, "active_tag_filter_ids", None) or ())

    def _set_ids(self, ids, ratings):
        ctx = self.context
        active = getattr(ctx, "active_tag_filter", None)
        if not isinstance(active, dict):
            active = {"tags": [], "branches": []}
            ctx.active_tag_filter = active
        active.update(ids=set(ids), count=len(ids),
                      rating_counts={r: int(ratings.get(r, 0)) for r in "gsqe"})
        ctx.active_tag_filter_ids = set(ids)
        # The frame cache must never claim to be sliced for these new ids.
        ctx.active_tag_filter_frame_for = None
        _runtime().mark_tag_filter_changed(ctx)

    def _restore(self):
        # Plain masks belong to the model, including after an append changed its
        # version while recomputation was pending. They are always reversible.
        if self._identity()[1] == "search_pool":
            model = getattr(self.context, "search_results", None)
            if model is not None:
                model.set_event_compress_dropped(set())
            self.dropped.clear()
            return
        if self.identity != self._identity():
            self.dropped.clear()
            return
        if self.identity[1] == "tag_filter":
            live = self._live_ids()
            ids = live | self.dropped
            restored = self.dropped - live
            # Preserve contributions from live ids that have no group/frame row.
            ratings = Counter((self.context.active_tag_filter or {}).get("rating_counts") or {})
            for group in self.groups.values():
                ratings[group["rating"]] += len(restored.intersection(group["members"]))
            self._set_ids(ids, ratings)
            # The model is a fast path; rebuild only when restoring dropped ids.
            if self.dropped:
                _runtime().apply_search_runtime_filters(self.context)
        self.dropped.clear()

    def _revision(self):
        model = getattr(self.context, "search_results", None)
        return (_runtime().current_tag_filter_revision(self.context), id(model),
                getattr(model, "_event_compress_version", 0),
                getattr(model, "_event_compress_consumption", 0),
                int(getattr(self.context, "_tag_filter_consumption", 0) or 0))

    def _can_publish(self, stamp, current):
        if enabled(self.context):
            # Compression writes kept ids back, so consumption must also match.
            return current == stamp

        def without_consumption(value):
            identity, revision, signature, sequence = value
            tag_revision, model_id, version, _, tag_consumption = revision
            if identity[1] == "tag_filter":
                tag_revision -= tag_consumption
            return identity, (tag_revision, model_id, version), signature, sequence

        return without_consumption(current) == without_consumption(stamp)

    def _capture(self):
        with self.guard():
            identity = self._identity()
            settings = pe_settings(self.context)
            stamp = (identity, self._revision(), settings[0], self.sequence)
            if identity != self.identity:
                self.dropped = set()
            if identity[1] == "tag_filter":
                frame = getattr(self.context, "search_results_snapshot", None)
                live = self._live_ids()
                ids = live | self.dropped
                restored = self.dropped - live
                model = getattr(self.context, "search_results", None)
                ratings = Counter((self.context.active_tag_filter or {}).get("rating_counts") or {})
                for group in self.groups.values():
                    ratings[group["rating"]] += len(restored.intersection(group["members"]))
                data = (frame, ids, model.event_compress_snapshot() if model is not None else [], ratings)
            else:
                model = getattr(self.context, "search_results", None)
                data = model.event_compress_snapshot() if model is not None else []
            return stamp, settings, data

    def _sample_candidates(self, stamp, data):
        """Select integer positions only; never exclude rows from the live pool."""
        identity = stamp[0]
        tag_filter = identity[1] == "tag_filter"
        rows = (len(data[1]) if tag_filter else
                sum(len(frame) - len(consumed) for _, frame, consumed, _ in data))
        limit = EVENT_COMPRESS_ROW_LIMIT
        if rows <= limit:
            return data, None, None
        # Identity includes generation, scope, assignment/model identity and version.
        # Neither request sequence, PE settings nor global RNG state affects the seed.
        seed = int.from_bytes(hashlib.sha256(
            json.dumps(identity, ensure_ascii=True).encode()).digest()[:8], "big")
        selected = np.sort(np.random.default_rng(seed).choice(rows, size=limit, replace=False))
        sample = {"rows": rows, "used": limit, "limit": limit}
        if tag_filter:
            candidates = np.fromiter(data[1], dtype=np.int64, count=rows)
            candidates.sort()
            return (data[0], set(candidates[selected].tolist()), data[2], data[3]), {}, sample
        positions, offset = {}, 0
        for bucket, frame, consumed, _ in data:
            count = len(frame) - len(consumed)
            lo, hi = np.searchsorted(selected, [offset, offset + count])
            local = selected[lo:hi] - offset
            if len(local) and consumed:
                available = np.ones(len(frame), dtype=bool)
                available[np.fromiter(consumed, dtype=np.intp, count=len(consumed))] = False
                local = np.flatnonzero(available)[local]
            positions[bucket] = local
            offset += count
        return data, positions, sample

    def _compute(self, stamp, settings, data, sampled_positions=None):
        checkpoint = lambda: self._checkpoint(stamp)
        checkpoint()
        identity = stamp[0]
        # Frame references are immutable until replacement. Cache integer tag
        # arrays across PE edits, consumption and assignment within a generation.
        generation = (identity[0], identity[1],
                      id(data[0]) if identity[1] == "tag_filter" else identity[2:])
        if self.cache_generation != generation:
            self.token_cache = {}
            self.cache_generation = generation
        records = []
        frames = [(None, data[0], set())] if identity[1] == "tag_filter" else [
            (key, frame, consumed) for key, frame, consumed, dropped in data]
        for bucket, frame, consumed in frames:
            if frame is None:
                continue
            if bucket is None:
                positions = frame["id"].isin(data[1]).to_numpy().nonzero()[0] if "id" in frame else []
            elif sampled_positions is not None:
                positions = sampled_positions[bucket]
            else:
                available = np.ones(len(frame), dtype=bool)
                if consumed:
                    available[np.fromiter(consumed, dtype=np.intp, count=len(consumed))] = False
                positions = np.flatnonzero(available)
            if not len(positions):
                continue
            cache_key = (id(frame), len(frame))
            cached = self.token_cache.get(cache_key)
            if cached is None or cached[0] is not frame:
                cached = (frame, [], {}, {}, {})
                self.token_cache[cache_key] = cached
            _, vocabulary, arrays, ratings, ids = cached
            # Payload reads and Python row objects are restricted to selected rows.
            unseen = [i for i in _cooperative(positions, checkpoint) if i not in arrays]
            mapping = {t: i for i, t in enumerate(vocabulary)}
            generals = frame["general"].iloc[unseen].tolist() if "general" in frame else [None] * len(unseen)
            selected_ratings = frame["rating"].iloc[unseen].astype(str).str.strip().str.lower().tolist() if "rating" in frame else [""] * len(unseen)
            selected_ids = frame["id"].iloc[unseen].tolist() if bucket is None and "id" in frame else unseen
            for i, general, rating, row_id in _cooperative(zip(unseen, generals, selected_ratings, selected_ids), checkpoint):
                valid_text = isinstance(general, str) and (bucket is not None or general.strip().lower() not in {"", "nan", "none", "null"})
                tokens = tuple(split_tags_smart(general)) if valid_text else ()
                for tag in tokens:
                    if tag not in mapping:
                        mapping[tag] = len(vocabulary)
                        vocabulary.append(tag)
                arrays[i] = tuple(mapping[t] for t in tokens)
                ratings[i], ids[i] = rating, row_id
            for i in _cooperative(positions, checkpoint):
                # Missing Tag Filter text is not an event and must never cause a drop.
                if bucket is not None or arrays[i]:
                    ref = ids[i] if bucket is None else (bucket, int(i))
                    records.append((ref, tuple(vocabulary[t] for t in arrays[i]), ratings[i], frame, i))
        filtered, special = filter_rows([r[1] for r in _cooperative(records, checkpoint)], settings[1], settings[2],
                                        _filter_manager(self.context), settings[3], checkpoint)
        groups = {}
        for record, tags in _cooperative(zip(records, filtered), checkpoint):
            ref, _, rating, frame, index = record
            key = (rating, frozenset(tags))
            group = groups.get(key)
            if group is None:
                opaque = hashlib.sha256(json.dumps([rating, sorted(key[1])], ensure_ascii=True).encode()).hexdigest()
                group = groups[key] = {"key": opaque, "rating": rating,
                                      "tags": ", ".join(sorted(key[1])), "tag_set": key[1],
                                      "tag_count": len(key[1]), "members": [],
                                      "frame": frame, "index": index}
            group["members"].append(ref)
        result = {g["key"]: g for g in _cooperative(groups.values(), checkpoint)}
        for group in _cooperative(result.values(), checkpoint):
            group["size"] = len(group["members"])
        def ordered_groups(direction):
            count = 0
            def sort_key(group):
                nonlocal count
                if count % 2000 == 0:
                    checkpoint()
                    time.sleep(0)
                    checkpoint()
                count += 1
                return direction * group["size"], group["tags"]
            return sorted(result.values(), key=sort_key)

        ordered = {"asc": ordered_groups(1), "desc": ordered_groups(-1)}
        kept, dropped, ratings = set(), set(), Counter()
        for group in _cooperative(result.values(), checkpoint):
            kept.add(group["members"][0])
            dropped.update(_cooperative(islice(group["members"], 1, None), checkpoint)
                           if len(group["members"]) > 2000 else group["members"][1:])
            ratings[group["rating"]] += 1
        mask = dropped
        if identity[1] == "tag_filter" and sampled_positions is None:
            # Only grouped duplicates may leave the pool. Delta accounting keeps
            # the previous per-rating contribution of every ungrouped live id.
            kept = data[1] - dropped
            ratings = data[3].copy()
            for group in _cooperative(result.values(), checkpoint):
                ratings[group["rating"]] -= len(group["members"]) - 1
            mask = set()
            for bucket, frame, consumed, _ in data[2]:
                if "id" in frame:
                    positions = frame["id"].isin(dropped).to_numpy().nonzero()[0]
                    mask.update((bucket, i) for i in _cooperative(positions, checkpoint) if i not in consumed)
        checkpoint()
        return result, special, ordered, kept, dropped, ratings, mask

    def _worker(self):
        while True:
            try:
                self._analyze()
                return
            except _AnalysisCancelled:
                with self.guard():
                    self._clear_token_cache()
                    if _runtime().is_pool_busy(self.context):
                        self._worker_running = False
                        return
                    # A short busy block can finish before the worker observes it.
                    # Its sequence change still cancels the old pass, then retries here.
                    self._notify()

    def _analyze(self):
        try:
            while True:
                with self.guard():
                    if _runtime().is_pool_busy(self.context):
                        raise _AnalysisCancelled()
                    stamp, settings, data = self._capture()
                checkpoint = lambda: self._checkpoint(stamp)
                data, sampled_positions, sample = self._sample_candidates(stamp, data)
                if sample:
                    # Do not retain full-pool tokens from an earlier legacy analysis.
                    self._clear_token_cache()
                groups, special, ordered, kept, dropped, ratings, mask = self._compute(
                    stamp, settings, data, sampled_positions)
                # Build once outside the pool lock; publish with the same groups.
                tag_index = {}
                group_tag_counts = {}
                for key, group in _cooperative(groups.items(), checkpoint):
                    group_tag_counts[key] = group["tag_count"]
                    for tag in group["tag_set"]:
                        tag_index.setdefault(tag, []).append(key)
                frequency_metadata = _frequency_metadata(groups, tag_index, checkpoint)
                histogram = Counter(group_tag_counts.values())
                tag_count_hist = {str(n): histogram[n] for n in sorted(histogram)}
                tag_count_min = min(histogram, default=0)
                tag_count_max = max(histogram, default=0)
                size_histogram = Counter(group["size"] for group in _cooperative(groups.values(), checkpoint))
                size_hist = {str(n): size_histogram[n] for n in sorted(size_histogram)}
                size_min = min(size_histogram, default=0)
                size_max = max(size_histogram, default=0)
                with self.guard():
                    checkpoint()
                    current = (self._identity(), self._revision(),
                               pe_settings(self.context)[0], self.sequence)
                    if not self._can_publish(stamp, current):
                        if current[0] != stamp[0] or not enabled(self.context):
                            self._clear_token_cache()
                        continue
                    before = self._remaining()
                    self.groups = groups
                    self.analysis += 1
                    self.sorted_groups = ordered
                    self.tag_index = tag_index
                    self.group_tag_counts = group_tag_counts
                    (self.tag_frequencies, self.group_frequencies, self.tag_freq_hist,
                     self.tag_freq_min, self.tag_freq_max) = frequency_metadata
                    self._effective_cache = None
                    self.tag_count_hist = tag_count_hist
                    self.tag_count_min = tag_count_min
                    self.tag_count_max = tag_count_max
                    self.size_hist = size_hist
                    self.size_min = size_min
                    self.size_max = size_max
                    self.identity, self.signature = stamp[0], settings[0]
                    self.per_row_rounds = special
                    self.sample = sample
                    if enabled(self.context) and sample is None:
                        self.dropped = dropped
                        if self.identity[1] == "tag_filter":
                            self._set_ids(kept, ratings)
                        model = getattr(self.context, "search_results", None)
                        if model is not None:
                            model.set_event_compress_dropped(mask)
                    if sample or not enabled(self.context):
                        self._clear_token_cache()
                    self.computing = False
                    self._worker_running = False
                    self.error = None
                    self._notify(pool_changed=before != self._remaining())
                    self.done.set()
                    return
        except _AnalysisCancelled:
            raise
        except Exception as exc:
            with self.guard():
                self.error = str(exc)
                self.signature = None
                self.computing = False
                self._worker_running = False
                try:
                    self._notify()
                except Exception:
                    pass
                self.done.set()

    def _remaining(self):
        if self._identity()[1] == "tag_filter":
            return len(self._live_ids())
        model = getattr(self.context, "search_results", None)
        return model.get_count() if model is not None else 0

    def state(self):
        with self.guard():
            signature, options, auto_hide, overrides = pe_settings(self.context)
            identity = self._identity()
            valid = identity == self.identity
            remaining = self._remaining()
            dropped = len(self.dropped) if valid and enabled(self.context) else 0
            payload = {"ok": True, "enabled": enabled(self.context), "computing": self.computing,
                       "stale": not valid or signature != self.signature,
                       "paused": _runtime().is_pool_busy(self.context) and (
                           self.computing or not valid or signature != self.signature),
                       "row_limit": EVENT_COMPRESS_ROW_LIMIT,
                       "sample": dict(self.sample) if self.sample else None,
                       "scope": identity[1] if remaining or dropped else "empty",
                       "pool_rows": remaining + dropped, "events": len(self.groups) if valid else 0,
                       "dropped": dropped, "remaining": remaining,
                       # Rows of the event commit the live Tag Filter came from (0 = not a commit).
                       # A plain re-apply replaces the snapshot, so it never reads as committed.
                       "committed_rows": self._committed_rows(),
                       "analysis": self.analysis,
                       "pe": {"options": options, "auto_hide_count": len(auto_hide),
                              "hide_count": sum(len(v.get("hide") or []) for v in overrides.values() if isinstance(v, dict))}}
            if self.error:
                payload.update(ok=False, error=self.error)
            return payload

    @staticmethod
    def _passes_tag_cut(count, min_tags, max_tags):
        return (min_tags is None or count >= min_tags) and (max_tags is None or count <= max_tags)

    def _effective_counts(self, min_freq, max_freq):
        # Called under the pool guard. Cache only the last frequency selection;
        # paging, search and the other cuts do not affect these global counts.
        bounds = (min_freq, max_freq)
        if self._effective_cache is not None and self._effective_cache[0] == bounds:
            return self._effective_cache[1]
        if bounds == (None, None):
            result = (self.group_tag_counts, self.tag_count_hist,
                      self.tag_count_min, self.tag_count_max)
        else:
            counts, histogram = {}, {}
            for key, (people_count, frequencies) in self.group_frequencies.items():
                lower = 0 if min_freq is None else bisect_left(frequencies, min_freq)
                upper = len(frequencies) if max_freq is None else bisect_right(frequencies, max_freq)
                count = people_count + upper - lower
                counts[key] = count
                histogram[count] = histogram.get(count, 0) + 1
            result = (counts, {str(n): histogram[n] for n in sorted(histogram)},
                      min(histogram, default=0), max(histogram, default=0))
        self._effective_cache = (bounds, result)
        return result

    def _passes_cuts(self, group, min_tags, max_tags, min_size, max_size, counts):
        return (self._passes_tag_cut(counts[group["key"]], min_tags, max_tags)
                and (min_size is None or group["size"] >= min_size)
                and (max_size is None or group["size"] <= max_size))

    def _events_signature(self):
        # Pool identity (generation/assignment), PE signature and the toggle - NOT consumption.
        # Random using rows (Auto Gen) must not make every commit stale: commit only ever takes
        # rows that are still live at commit time (_commit_ids), so a consumed row simply drops out.
        return hashlib.sha256(json.dumps([
            self._identity(), self.signature, enabled(self.context),
        ], ensure_ascii=True).encode()).hexdigest()

    def _matching_groups(self, sort, q, min_tags, max_tags, min_size, max_size, counts):
        words = q.lower().split()
        return [g for g in self.sorted_groups[sort]
                if self._passes_cuts(g, min_tags, max_tags, min_size, max_size, counts)
                and all(word in g["tags"].lower() for word in words)]

    def _page_groups(self, sort, q, min_tags, max_tags, min_size, max_size, counts):
        # Scrolling asks for the same selection page after page. Keep the last one, tied
        # to the published ordering and counts objects themselves (not their ids).
        key = (sort, q, min_tags, max_tags, min_size, max_size)
        cached = self._page_cache
        if cached is not None and cached[0] is self.sorted_groups and cached[1] is counts and cached[2] == key:
            return cached[3], cached[4]
        groups = self._matching_groups(sort, q, min_tags, max_tags, min_size, max_size, counts)
        # Largest event of the whole selection - the window scales its bars by this, so rows
        # drawn on earlier pages never need redrawing when a later page brings a bigger one.
        top = max((g["size"] for g in groups), default=0)
        self._page_cache = (self.sorted_groups, counts, key, groups, top)
        return groups, top

    def _live_predicate(self):
        # Liveness of a few listed members only - building the whole live set (every
        # member of every event) cost ~1 s per page on a 500k-row sample.
        if self.identity[1] == "tag_filter":
            active = getattr(self.context, "active_tag_filter", None)
            ids = active.get("ids") if isinstance(active, dict) else getattr(
                self.context, "active_tag_filter_ids", None)
            ids = ids or ()
            return lambda ref: ref in ids
        model = getattr(self.context, "search_results", None)
        if model is None:
            return lambda ref: False
        masks = {key: (consumed, dropped) for key, _, consumed, dropped in model.event_compress_snapshot()}

        def live(ref):
            mask = masks.get(ref[0])
            return mask is not None and ref[1] not in mask[0] and ref[1] not in mask[1]
        return live

    def _committed_rows(self):
        # Called under the pool guard.
        snapshot = getattr(self.context, "active_tag_filter_snapshot", None)
        if (self._identity()[1] != "tag_filter" or not isinstance(snapshot, dict)
                or not snapshot.get("_event_compress_commit")):
            return 0
        return len(snapshot.get("ids") or ())

    def pool(self):
        """[↑↑풀링] - make the committed rows the session search result, exactly like saving them as
        a parquet and loading it back (user 2026-10-24: every committed row, consumed ones included)."""
        # Check, export and install under ONE hold of the (reentrant) pool guard: otherwise another tab
        # can re-apply Tag Filter between the commit check and the export, and an uncommitted selection
        # would be installed (Codex review 2026-10-24).
        with self.guard():
            if not self._committed_rows():
                raise CommitError("not_committed", "Commit the event selection first", 409)
            # Same frame as [이 결과 저장]: the applied (immutable) commit set x active ratings.
            frame, recipe = _runtime().export_condition_frame(self.context)
            if frame is None or frame.empty:
                raise CommitError("empty", "No committed rows to pool", 400)
            recipe["event_compress"] = {"rows": int(len(frame))}
            _runtime().install_custom_parquet_frame(self.context, frame, provenance=recipe)
            return int(len(frame))

    def _commit_ids(self, groups):
        if not groups or self._identity()[1] != "tag_filter":
            return set()
        live = self._live_ids()
        ids = set()
        for group in groups:
            # Always ONE row per event (user 2026-10-23: commit count == event count; the live
            # "compress on" mode was removed from the window). The first member is the
            # representative; if it was consumed, fall back to another currently live member.
            for member in group["members"]:
                if member in live:
                    ids.add(member)
                    break
        return ids

    def commit(self, events_signature, min_tags=None, max_tags=None, q="",
               min_size=None, max_size=None, min_freq=None, max_freq=None):
        from core.tag_filter_remaining import save_committed

        with self.guard():
            if self._identity()[1] != "tag_filter" or not self._live_ids():
                raise CommitError("no_tag_filter", "An active non-empty Tag Filter is required", 409)
            if self.computing or self.is_stale() or events_signature != self._events_signature():
                raise CommitError("stale", "Event analysis changed; reload the event list", 409)
            counts, _, _, _ = self._effective_counts(min_freq, max_freq)
            groups = self._matching_groups("desc", q, min_tags, max_tags, min_size, max_size, counts)
            ids = self._commit_ids(groups)
            if not ids:
                raise CommitError("empty", "No live rows match the event selection", 400)
            ratings = Counter()
            for group in groups:
                ratings[group["rating"]] += len(ids.intersection(group["members"]))
            ctx = self.context
            # Persist before publishing the new assignment. A failure leaves the
            # live pool untouched. Repeated commits keep the original full pair.
            record = save_committed(ctx, ids)
            self.sequence += 1
            self.dropped.clear()
            self._set_ids(ids, ratings)
            ctx.active_tag_filter_snapshot = copy.deepcopy(ctx.active_tag_filter)
            ctx.active_tag_filter_snapshot["_event_compress_commit"] = record
            # Refill rebinds frame_for to the restored ids. Discard the old
            # pre-commit slice so it cannot then masquerade as the committed set.
            ctx.active_tag_filter_frame = None
            ctx.active_tag_filter_frame_snapshot = None
            self.identity = None
            _runtime().apply_search_runtime_filters(ctx)
            self.request()
            self._notify(pool_changed=True)
            return {"ok": True, "committed": len(ids), "state": self.state()}

    def _list_pending(self):
        if self.computing or self.is_stale() or _runtime().is_pool_busy(self.context):
            if not self.computing:
                self.request()
            return True
        return False

    def _pending_flags(self):
        return {"computing": True, "paused": _runtime().is_pool_busy(self.context),
                "row_limit": EVENT_COMPRESS_ROW_LIMIT,
                "sample": dict(self.sample) if self.sample else None}

    def _pending_events(self, offset):
        return {"ok": True, **self._pending_flags(), "total": 0, "offset": offset,
                "items": [], "commit_rows": 0, "events_signature": None,
                "tag_count_hist": {}, "tag_count_min": 0, "tag_count_max": 0,
                "tag_freq_hist": {}, "tag_freq_min": 0, "tag_freq_max": 0,
                "size_hist": {}, "size_min": 0, "size_max": 0}

    def events(self, sort="desc", q="", offset=0, limit=60, min_tags=None, max_tags=None,
               min_size=None, max_size=None, min_freq=None, max_freq=None):
        with self.guard():
            if self._list_pending():
                return self._pending_events(offset)
            live = self._live_predicate()
            counts, histogram, count_min, count_max = self._effective_counts(min_freq, max_freq)
            groups, size_top = self._page_groups(sort, q, min_tags, max_tags, min_size, max_size, counts)
            items = [{**{k: g[k] for k in ("key", "rating", "tags", "size")},
                      "tag_count": counts[g["key"]],
                      "uncounted": sorted(tag for tag in g["tag_set"]
                                          if not _is_people_tag(tag) and not self._passes_tag_cut(
                                              self.tag_frequencies[tag], min_freq, max_freq)),
                      "remaining": sum(1 for ref in g["members"] if live(ref))}
                     for g in groups[offset:offset + limit]]
            return {"ok": True, "total": len(groups), "offset": offset, "items": items, "size_top": size_top,
                    "row_limit": EVENT_COMPRESS_ROW_LIMIT,
                    "sample": dict(self.sample) if self.sample else None,
                    "commit_rows": len(self._commit_ids(groups)),
                    "events_signature": self._events_signature(),
                    "tag_count_hist": dict(histogram),
                    "tag_count_min": count_min, "tag_count_max": count_max,
                    "tag_freq_hist": dict(self.tag_freq_hist),
                    "tag_freq_min": self.tag_freq_min, "tag_freq_max": self.tag_freq_max,
                    "size_hist": dict(self.size_hist),
                    "size_min": self.size_min, "size_max": self.size_max}

    def tags(self, q="", min_tags=None, max_tags=None, limit=20, min_size=None, max_size=None,
             min_freq=None, max_freq=None):
        query = q.lower().replace("_", " ")
        with self.guard():
            if self._list_pending():
                return {"ok": True, "items": [], **self._pending_flags()}
            counts, _, _, _ = self._effective_counts(min_freq, max_freq)
            items = []
            for tag, keys in self.tag_index.items():
                normalized = tag.lower().replace("_", " ")
                if query not in normalized:
                    continue
                unbounded = min_tags is None and max_tags is None and min_size is None and max_size is None
                count = len(keys) if unbounded else sum(
                    self._passes_cuts(self.groups[key], min_tags, max_tags, min_size, max_size, counts)
                    for key in keys)
                if count:
                    items.append({"tag": tag, "events": count})
            items.sort(key=lambda item: (
                not item["tag"].lower().replace("_", " ").startswith(query),
                -item["events"], item["tag"]))
            return {"ok": True, "items": items[:limit]}

    def source_row(self, key):
        with self.guard():
            self._list_pending()
            group = self.groups.get(key) if self.identity == self._identity() else None
            if group is None:
                raise KeyError(key)
            return group["frame"].iloc[group["index"]].to_dict()

    def persisted_dropped(self):
        with self.guard():
            if self.identity == self._identity() and self.identity[1] == "tag_filter":
                return set(self.dropped)
            return set()

    def _notify(self, pool_changed=False):
        publish = getattr(self.context, "publish", None)
        if callable(publish):
            publish("search_pool_broadcast", {"type": "event_compress_state", **self.state()})
            if pool_changed:
                if self._identity()[1] == "tag_filter":
                    from core.headless_random_prompt_service import HeadlessRandomPromptService
                    payload = HeadlessRandomPromptService(self.context)._tag_filter_update_payload(
                        self.context.active_tag_filter)
                else:
                    payload = self.context.search_state_payload()
                publish("search_pool_broadcast", payload)
