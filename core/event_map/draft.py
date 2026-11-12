"""Draft data operations and the UNIT 2 session/prompt ownership adapter.

Operations copy their input and advance rev only on change. UNIT 2 can rebuild
from that candidate, then persist/commit it, without rolling back this module.
The packed text cache has its own 64 MiB budget, independent of the index's
512 posting entries and 128 MiB sample-pool budget.
"""
from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import Future
from copy import deepcopy
import json
import os
from pathlib import Path
import random
import tempfile
import threading
import uuid
import weakref

import numpy as np

from .extra_prompt import MAX_TEXT
from .library import selection
from .service import MapQueryError, PERSON_LABELS
from core.tag_combo.person import PERSON_GROUPS

SCHEMA = "naia-event-map-draft-v1"
TEXT_CACHE_BYTES = 64 << 20
POOL_INLINE = 2_000
POOL_LIMIT = 50_000
RATINGS = dict(zip("gsqe", ("general", "sensitive", "questionable", "explicit")))
RATING_ALIASES = {alias: rating for rating, name in RATINGS.items()
                  for alias in (name, "rating:" + name, "rating:" + rating)}
_STORE_LOCK = threading.RLock()
_MESSAGES = {
    "zero_match": "조건에 맞는 게시물이 없습니다.",
    "stale": "조건이 바뀌었습니다. 최신 상태에서 다시 시도해주세요.",
    "duplicate": "이미 있는 칩입니다.",
    "rating_toggle": "등급은 위 G · S · Q · E 단추로 고릅니다",
    "rating_empty": "등급은 하나 이상 켜져 있어야 합니다.",
    "too_many": "칩 개수 또는 글자 수 상한을 넘었습니다.",
    "no_include": "포함 조건이 하나 이상 있어야 합니다.",
    "unavailable": "이벤트 맵 색인을 먼저 받아주세요.",
    "rebuild_failed": "드래프트 상태를 읽거나 저장하지 못했습니다. 원본은 보존됩니다.",
    "no_drawn": "먼저 게시물을 뽑아주세요.",
}


class DraftError(MapQueryError):
    """Stable wire error; malformed transport payloads belong to UNIT 2."""

    def __init__(self, code, message=None, *, status=None):
        super().__init__(code, message or _MESSAGES[code])
        self.status = status or (503 if code == "unavailable" else
                                 400 if code in ("too_many", "no_include") else 409)
        self.status_code = self.status

    def to_payload(self):
        return {"ok": False, "error": self.code, "message": self.message}


class TextPostCache:
    """Packed masks, byte-LRU, single-flight, and one active union globally.

    Epoch checks prevent late insertion after clear. Retiring an index also
    drains the current union before its mmap is closed, and rejects queued work.
    """

    def __init__(self, budget=TEXT_CACHE_BYTES):
        self.budget = budget
        self.entries = OrderedDict()
        self._counts = {}
        self.bytes = 0
        self._flights = {}
        self._lock = threading.Lock()
        self._compute = threading.Semaphore(1)
        self._epoch = 0
        self._retired = weakref.WeakSet()

    def clear(self):
        with self._lock:
            self._epoch += 1
            self.entries.clear()
            self._counts.clear()
            self.bytes = 0

    def retire(self, idx):
        with self._lock:
            self._retired.add(idx)
            self._epoch += 1
            for key in list(self.entries):
                if key[0] is idx:
                    self.bytes -= self.entries.pop(key).nbytes
                    self._counts.pop(key, None)
        with self._compute:
            pass

    def packed(self, idx, text):
        key = (idx, text.lower())
        with self._lock:
            if idx in self._retired:
                raise DraftError("unavailable")
            hit = self.entries.get(key)
            if hit is not None:
                self.entries.move_to_end(key)
                return hit
            epoch = self._epoch
            flight_key = (epoch, *key)
            future = self._flights.get(flight_key)
            leader = future is None
            if leader:
                future = self._flights[flight_key] = Future()
        if not leader:
            return future.result()
        try:
            with self._compute:
                with self._lock:
                    if idx in self._retired:
                        raise DraftError("unavailable")
                mask = np.zeros(idx.offsets.size - 1, dtype=bool)
                if key[1].startswith("*"):
                    tid = idx.resolve(key[1][1:])
                    tids = () if tid is None else (tid,)
                else:
                    tids = np.flatnonzero(idx.matching_tags(key[1]))
                for tid in tids:
                    mask[idx.posting(int(tid))] = True
                packed = np.packbits(mask)
                packed.flags.writeable = False
                count = int(np.bitwise_count(packed).sum(dtype=np.int64))
            with self._lock:
                if epoch == self._epoch and idx not in self._retired and packed.nbytes <= self.budget:
                    while self.entries and self.bytes + packed.nbytes > self.budget:
                        old_key, old = self.entries.popitem(last=False)
                        self.bytes -= old.nbytes
                        self._counts.pop(old_key, None)
                    self.entries[key] = packed
                    self._counts[key] = count
                    self.bytes += packed.nbytes
            future.set_result(packed)
            return packed
        except Exception as exc:
            future.set_exception(exc)
            raise
        finally:
            with self._lock:
                self._flights.pop(flight_key, None)

    def posts(self, idx, text):
        return np.flatnonzero(np.unpackbits(self.packed(idx, text))).astype(np.int64)

    def count(self, idx, text):
        packed = self.packed(idx, text)
        with self._lock:
            count = self._counts.get((idx, text.lower()))
        return count if count is not None else int(np.bitwise_count(packed).sum(dtype=np.int64))


TEXT_CACHE = TextPostCache()


class _Cond:
    """One immutable condition, with thread-safe lazy views and body counts."""

    def __init__(self, packed, size):
        packed.flags.writeable = False
        self.packed = packed
        self.size = size
        self.count = int(np.bitwise_count(packed).sum(dtype=np.int64))
        self._lock = threading.RLock()
        self._rids = self._mask = self._cumulative = None
        self._tag_counts = self._gathered = self._reduce_at = self._present = None

    def rids(self):
        with self._lock:
            if self._rids is None:
                self._rids = np.flatnonzero(np.unpackbits(self.packed)[:self.size]).astype(np.int64)
                self._rids.flags.writeable = False
            return self._rids

    def mask(self):
        with self._lock:
            if self._mask is None:
                self._mask = np.unpackbits(self.packed)[:self.size].view(bool)
                self._mask.flags.writeable = False
            return self._mask

    def has(self, rid):
        return 0 <= rid < self.size and bool(self.packed[rid >> 3] & (0x80 >> (rid & 7)))

    def nth(self, k):
        if k < 0:
            k += self.count
        if not 0 <= k < self.count:
            raise IndexError(k)
        with self._lock:
            if self._cumulative is None:
                self._cumulative = np.cumsum(np.bitwise_count(self.packed), dtype=np.int64)
            byte = int(np.searchsorted(self._cumulative, k, side="right"))
            before = int(self._cumulative[byte - 1]) if byte else 0
        bit = np.flatnonzero(np.unpackbits(self.packed[byte:byte + 1]))[k - before]
        return byte * 8 + int(bit)

    def __len__(self):
        return self.count

    def __getitem__(self, k):
        return self.nth(k)

    def has_tag_counts(self):
        with self._lock:
            return self._tag_counts is not None

    def tag_counts(self, idx):
        if self.count > POOL_LIMIT:
            return None
        with self._lock:
            if self._tag_counts is None:
                rids = np.flatnonzero(self.mask())
                starts = idx.offsets[rids].astype(np.int64)
                lengths = idx.offsets[rids + 1].astype(np.int64) - starts
                before = np.zeros(rids.size, dtype=np.int64)
                np.cumsum(lengths[:-1], out=before[1:])
                picks = np.repeat(starts - before, lengths) + np.arange(int(lengths.sum()), dtype=np.int64)
                self._gathered = idx.body[picks]
                self._reduce_at = before[lengths > 0]
                self._tag_counts = np.bincount(self._gathered, minlength=idx.n_tags)[:idx.n_tags]
                self._tag_counts.flags.writeable = False
            return self._tag_counts

    def present(self, idx):
        """조건 안에 있는 태그의 (소문자 이름, tid) 목록. 후보 이름이 든 태그는 어휘 전체가 아니라 여기서만 찾는다."""
        counts = self.tag_counts(idx)
        with self._lock:
            if self._present is None:
                self._present = [(idx.by_id[int(tid)].lower(), int(tid)) for tid in np.flatnonzero(counts)]
            return self._present

    def text_hits(self, idx, text, scope=None):
        """`text` 가 이름에 든 태그가 하나라도 달린 조건 안 게시물 수 = 텍스트 칩으로 넣었을 때의 합집합 수.

        `scope` 는 찾아볼 (소문자 이름, tid) 목록이고 없으면 조건 안 태그 전부다. `idx.matching_tags()` 로 어휘 전체를
        훑지 않는다 - 후보 20개마다 5.8만 이름을 돌아 키 하나에 40~150ms 가 들었고(실측 2026-11-11, 이름 응답이 그만큼
        늦었다) 칩이 쓰는 이름표 캐시(256칸)도 후보가 밀어냈다. 조건 밖 태그는 어차피 수에 보태지 않는다.
        """
        counts = self.tag_counts(idx)
        matching = [tid for name, tid in (self.present(idx) if scope is None else scope) if text in name]
        if len(matching) < 2:
            return int(counts[matching[0]]) if matching else 0
        tidmask = np.zeros(idx.n_tags, dtype=bool)
        tidmask[matching] = True
        return int(np.count_nonzero(np.logical_or.reduceat(tidmask[self._gathered], self._reduce_at)))


def new_state():
    return {"schema": SCHEMA, "gen": uuid.uuid4().hex, "rev": 0,
            "active": False, "saved_prompt": "", "include": [], "exclude": [],
            "ratings": [], "tags": {"persons": [], "groups": []}, "extra": "", "drawn": None}


def _limits(state):
    if (len(state["include"]) > 16 or len(state["exclude"]) > 32
            or len(state["tags"]["groups"]) > 7 or len(state["extra"]) > MAX_TEXT
            or any(len(c["text"]) > 160 for z in ("include", "exclude") for c in state[z])):
        raise DraftError("too_many")


def _base(state, base_rev):
    if base_rev is not None and base_rev < state["rev"]:
        raise DraftError("stale")
    return deepcopy(state)


def _finish(old, candidate):
    _limits(candidate)
    if candidate != old:
        candidate["rev"] = old["rev"] + 1
    return candidate


def _next_id(state, prefix="c"):
    rows = state["include"] + state["exclude"] if prefix == "c" else state["tags"]["groups"]
    used = {r["id"] for r in rows}
    n = 1
    while prefix + str(n) in used:
        n += 1
    return prefix + str(n)


def _chip(state, zone, text, exact):
    state[zone].append({"id": _next_id(state), "text": text, "exact": exact})


class DraftStore:
    """Atomic persistence with explicit corrupt-file recovery, like staging."""

    def __init__(self, path):
        self.path = Path(path)

    @classmethod
    def from_context(cls, context):
        return cls(context._save_path("event_map", "draft.json"))

    def load(self):
        with _STORE_LOCK:
            if not self.path.exists():
                return new_state()
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                _validate_state(data)
                return data
            except (OSError, ValueError, KeyError, TypeError, AttributeError, DraftError) as exc:
                raise DraftError("rebuild_failed") from exc

    def _write(self, state):
        try:
            encoded = json.dumps(state, ensure_ascii=False, indent=2)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=".event-map-draft-", suffix=".tmp", delete=False) as file:
                file.write(encoded)
                file.flush()
                os.fsync(file.fileno())
                temporary = file.name
            os.replace(temporary, self.path)
        except OSError as exc:
            raise DraftError("rebuild_failed") from exc

    def save(self, state, *, base_rev=None, force_revision=False):
        with _STORE_LOCK:
            current = self.load()
            if self.path.exists() and state["gen"] != current["gen"]:
                raise DraftError("stale")
            if state["rev"] < current["rev"]:
                raise DraftError("stale")
            _base(current, base_rev)
            candidate = deepcopy(state)
            comparable = {**candidate, "rev": current["rev"]}
            if comparable == current and not force_revision:
                return current
            candidate["rev"] = current["rev"] + 1
            _validate_state(candidate)
            self._write(candidate)
            return candidate

    def clear(self):
        with _STORE_LOCK:
            try:
                old = self.load()
            except DraftError:
                old = new_state()
            state = new_state()
            state.update(gen=old["gen"], rev=old["rev"] + 1)
            self._write(state)
            return state


def _validate_state(s):
    if s["schema"] != SCHEMA or not isinstance(s["active"], bool):
        raise ValueError("schema")
    uuid.UUID(s["gen"])
    if type(s["rev"]) is not int or s["rev"] < 0:
        raise ValueError("rev")
    if not isinstance(s["saved_prompt"], str) or not isinstance(s["extra"], str):
        raise ValueError("text")
    ids = set()
    for zone in ("include", "exclude"):
        if not isinstance(s[zone], list):
            raise ValueError("chips")
        for c in s[zone]:
            if (not c["id"].startswith("c") or not c["id"][1:].isdigit() or c["id"] in ids
                    or not isinstance(c["text"], str) or not c["text"] or type(c["exact"]) is not bool):
                raise ValueError("chip")
            ids.add(c["id"])
    if (not isinstance(s["ratings"], list) or len(set(s["ratings"])) != len(s["ratings"])
            or set(s["ratings"]) - set(RATINGS)):
        raise ValueError("ratings")
    if not isinstance(s["tags"]["persons"], list) or set(s["tags"]["persons"]) - set(PERSON_GROUPS):
        raise ValueError("persons")
    if not isinstance(s["tags"]["groups"], list):
        raise ValueError("groups")
    for g in s["tags"]["groups"]:
        if (not g["id"].startswith("t") or not g["id"][1:].isdigit() or g["id"] in ids
                or g["invert"] is not True or not isinstance(g["terms"], list)
                or not 2 <= len(g["terms"]) <= 16
                or any(not isinstance(t, str) or not t or len(t) > 160 for t in g["terms"])):
            raise ValueError("group")
        ids.add(g["id"])
    d = s["drawn"]
    if d is not None and (type(d["rid"]) is not int or d["rid"] < 0
                          or not isinstance(d["partition"], str)
                          or any(not isinstance(d[k], list) or any(not isinstance(t, str) for t in d[k])
                                 for k in ("post_tags", "dropped"))):
        raise ValueError("drawn")
    _limits(s)


def _rating_out(state):
    drawn = state["drawn"]
    rating = drawn["partition"][:1] if drawn else (state["ratings"][0] if len(state["ratings"]) == 1 else None)
    return "rating:" + RATINGS[rating] if rating in RATINGS else None


def _outputs(state):
    """User output and gray remainder in the canonical post_tags order."""
    drawn = state["drawn"]
    tags = drawn["post_tags"] if drawn else []
    hits = {c["id"]: [t for t in tags if c["text"].lower() in t.lower()] if not c["exact"] else []
            for c in state["include"]}
    own = []
    for c in state["include"]:
        own.extend([c["text"]] if c["exact"] or not drawn else hits[c["id"]])
    own = list(dict.fromkeys(own))
    if drawn:
        own = [t for t in tags if t in own] + [t for t in own if t not in tags]
    rating = _rating_out(state)
    if rating:
        own.append(rating)
    gray = [{"tag": t, "pe_hidden": False, "dropped": t in drawn.get("dropped", [])}
            for t in tags if t not in own] if drawn else []
    return own, gray, hits


def build_row(state):
    own, gray, _ = _outputs(state)
    if state["drawn"]:
        kept = set(own) | {g["tag"] for g in gray if not g["dropped"]}
        tags = [t for t in state["drawn"]["post_tags"] if t in kept]
        tags += [t for t in own if t not in tags]
    else:
        tags = own
    rating = _rating_out(state)
    row = {"general": ", ".join(tags), "event_map_combo": True,
           "draft_protected": own, "draft_extra": state["extra"]}
    if rating:
        row["rating"] = RATING_ALIASES[rating]
    # With no unambiguous rating, omit it so the pipeline's default applies.
    return row


class EventMapDraft:
    """Read-only queries and copy-on-write operations over explicit states."""

    def __init__(self, service, *, kr_lookup=None, describe=None):
        self.service = service
        self.kr_lookup = kr_lookup
        self.describe = describe
        self._conditions = []
        self._memo_lock = threading.Lock()
        self._cache_idx = None
        self._part_cache = OrderedDict()
        self._live = None
        self._block_for = None
        self._blocked = None

    def _index(self):
        try:
            return self.service.index()
        except MapQueryError as exc:
            raise DraftError("unavailable") from exc

    @staticmethod
    def _chip_count(idx, chip):
        if chip["exact"]:
            tid = idx.resolve(chip["text"])
            return int(idx.posting(tid).size) if tid is not None else 0
        return TEXT_CACHE.count(idx, chip["text"])

    def posts(self, state, *, idx=None):
        idx = idx or self._index()
        return self._condition(state, idx, self.service.permanent_block(idx)).rids()

    def _condition_key(self, state):
        return json.dumps([state["include"], state["exclude"], state["ratings"], state["tags"]], sort_keys=True)

    def _cached_condition(self, key, idx, block):
        with self._memo_lock:
            for at, (old_idx, old_block, old_key, cond) in enumerate(self._conditions):
                if old_idx is idx and old_block is block and old_key == key:
                    self._conditions.append(self._conditions.pop(at))
                    return cond
        return None

    def _condition(self, state, idx, block, *, memo=True):
        key = self._condition_key(state)
        if memo:
            hit = self._cached_condition(key, idx, block)
            if hit is not None:
                return hit
        cond = self._build_condition(state, idx, block)
        if memo:
            with self._memo_lock:
                for old_idx, old_block, old_key, old in self._conditions:
                    if old_idx is idx and old_block is block and old_key == key:
                        return old
                self._conditions.append((idx, block, key, cond))
                self._conditions = self._conditions[-2:]
        return cond

    def _auxiliary(self, state, idx, block):
        size = idx.offsets.size - 1
        parts = idx._partition_filter(state["ratings"], state["tags"]["persons"])
        key = (frozenset(state["ratings"]), frozenset(state["tags"]["persons"]))
        with self._memo_lock:
            if self._cache_idx is not idx:
                self._cache_idx = idx
                self._part_cache.clear()
                self._live = self._blocked = self._block_for = None
                self._conditions.clear()
            partition = None
            if parts is not None:
                partition = self._part_cache.get(key)
                if partition is None:
                    mask = np.zeros(size, dtype=bool)
                    owners = idx.part_arr[:size]
                    mask[:owners.size] = idx._part_lut(parts)[owners]
                    partition = np.packbits(mask)
                    partition.flags.writeable = False
                    self._part_cache[key] = partition
                    if len(self._part_cache) > 16:
                        self._part_cache.popitem(last=False)
                self._part_cache.move_to_end(key)
            if not state["include"] and self._live is None:
                self._live = np.packbits(idx.offsets[1:] > idx.offsets[:-1])
                self._live.flags.writeable = False
            if self._block_for is not block:
                self._block_for = block
                self._blocked = np.packbits(block.posts) if block is not None else None
                if self._blocked is not None:
                    self._blocked.flags.writeable = False
            return partition, self._live, self._blocked

    def _build_condition(self, state, idx, block):
        partition, live, blocked = self._auxiliary(state, idx, block)
        packed = None
        for chip in state["include"]:
            other = TEXT_CACHE.packed(idx, ("*" if chip["exact"] else "") + chip["text"])
            if packed is None:
                packed = other.copy()
            else:
                packed &= other
        if packed is None:
            packed = live.copy()
        if partition is not None:
            packed &= partition
        for chip in state["exclude"]:
            packed &= ~TEXT_CACHE.packed(idx, ("*" if chip["exact"] else "") + chip["text"])
        size = idx.offsets.size - 1
        if state["tags"]["groups"]:
            rids = np.flatnonzero(np.unpackbits(packed)[:size])
            mask = np.zeros(size, dtype=bool)
            mask[idx.filter_posts(rids, state["tags"]["groups"])] = True
            packed = np.packbits(mask)
        if blocked is not None:
            packed &= ~blocked
        return _Cond(packed, size)

    def count(self, state):
        idx = self._index()
        return self._condition(state, idx, self.service.permanent_block(idx)).count

    def condition_id(self, state):
        """조건(포함 · 제외 · 등급 · 분면)의 짧은 지문. 뽑기 · Extra · PE 재조립은 rev 만 올리고 이것은 그대로다 -
        '남은 태그' 창이 받은 목록이 지금 조건의 것인지 rev 대신 이것으로 가린다(Codex 리뷰 2026-11-12 3차 #5)."""
        import hashlib
        return hashlib.sha1(self._condition_key(state).encode("utf-8")).hexdigest()[:16]

    def rating_counts(self, state, *, idx=None):
        """등급별 남는 게시물 수 - 등급 조건만 뺀 나머지 조건 안에서. 0 인 축은 켤 수 없다."""
        idx = idx or self._index()
        block = self.service.permanent_block(idx)
        base = self._condition(dict(state, ratings=[]), idx, block)
        out = {}
        for rating in RATINGS:
            partition, _, _ = self._auxiliary(dict(state, ratings=[rating]), idx, block)
            out[rating] = int(np.bitwise_count(base.packed & partition).sum(dtype=np.int64))
        return out

    def _parse(self, text):
        raw = str(text or "").strip()
        exact = raw.startswith("*")
        clean = (raw[1:] if exact else raw).strip().lower()
        rating = RATING_ALIASES.get(clean)
        if not rating:
            idx = self._index()
            tid = idx.resolve(clean)
            clean = idx.by_id[tid] if tid is not None else clean
        return clean, exact, rating

    def check(self, zone, text, *, state=None):
        state = state if state is not None else new_state()
        idx = self._index()
        clean, exact, rating = self._parse(text)
        out = {"ok": True, "kind": "chip", "text": clean, "exact": exact,
               "count_after": None, "hits": 0, "reason": None}

        def blocked(reason):
            out.update(kind="blocked", reason=reason)
            out.pop("rating", None)
            return out

        if zone not in ("include", "exclude") or not clean or len(clean) > 160:
            return blocked("too_many")
        candidate = deepcopy(state)
        if rating:
            # 등급은 칩이 아니다 - 판의 G · S · Q · E 단추(`chips` op "ratings")로만 고른다(사용자 결정 2026-11-12).
            return blocked("rating_toggle")
        else:
            mask = idx.matching_tags(clean, exact)
            out["hits"] = int(np.count_nonzero(mask))
            if not out["hits"]:
                out["kind"] = "extra"
                if len(state["extra"]) + len(clean) + (2 if state["extra"] else 0) > MAX_TEXT:
                    return blocked("too_many")
                return out
            if any(c["text"] == clean and c["exact"] == exact
                   for z in ("include", "exclude") for c in state[z]):
                return blocked("duplicate")
            if len(state[zone]) >= (16 if zone == "include" else 32):
                return blocked("too_many")
            block = self.service.permanent_block(idx)
            if block is not None and np.all(block.tags[mask]):
                out["count_after"] = 0
                return blocked("permanent_excluded")
            _chip(candidate, zone, clean, exact)
        out["count_after"] = self._condition(candidate, idx, self.service.permanent_block(idx)).count
        return blocked("zero_match") if not out["count_after"] else out

    def _recheck(self, state):
        drawn = state["drawn"]
        if drawn is None:
            return
        idx = self._index()
        cond = self._condition(state, idx, self.service.permanent_block(idx))
        if not cond.has(drawn["rid"]):
            state["drawn"] = None
        else:
            pinned = [idx.resolve(c["text"]) for c in state["include"] if c["exact"]]
            post = idx.post_tags(drawn["rid"], pinned=pinned, include_color=True)
            drawn.update(partition=post["partition"], post_tags=post["tags"])

    def chips(self, state, op, *, base_rev=None, id=None, zone=None, text=None, exact=None):
        candidate = _base(state, base_rev)
        self._index()
        if op == "add":
            result = self.check(zone, text, state=state)
            if result["kind"] == "blocked":
                reason = result["reason"]
                # The wire error list has no permanent_excluded error (only a check reason).
                raise DraftError("zero_match" if reason == "permanent_excluded" else reason)
            if result["kind"] == "extra":
                candidate["extra"] += (", " if candidate["extra"] else "") + result["text"]
                return _finish(state, candidate)
            _chip(candidate, zone, result["text"], result["exact"])
        elif op == "ratings":
            # text = 켜 둘 등급 글자들("sq"). 빈 state["ratings"] = 넷 다 켬(등급 조건 없음).
            want = set(text) if isinstance(text, str) else None
            if want is None or want - set(RATINGS) or len(text) != len(want):
                raise DraftError("too_many", "등급을 확인해주세요.")
            if not want:
                raise DraftError("rating_empty")
            was = set(state["ratings"] or RATINGS)
            if want - was:
                counts = self.rating_counts(state)
                if any(not counts[r] for r in want - was):
                    raise DraftError("zero_match")       # 남는 게시물이 없는 축은 켤 수 없다
            candidate["ratings"] = [] if want == set(RATINGS) else [r for r in RATINGS if r in want]
            if candidate["ratings"] != state["ratings"] and not self.count(candidate):
                raise DraftError("zero_match")
        elif op == "clear" and zone in ("include", "exclude"):
            # 그 칸을 통째로 비운다(사용자 지시 2026-11-12). 포함 = 칩 + 인원 분면 · 제외 = 칩 + 묶음 제외. 등급 단추는 그대로.
            candidate[zone] = []
            if zone == "include":
                candidate["tags"]["persons"] = []
            else:
                candidate["tags"]["groups"] = []
        elif op == "remove" and id == "persons":
            candidate["tags"]["persons"] = []
        elif op == "remove" and id in ["r:" + r for r in candidate["ratings"]]:
            candidate["ratings"].remove(id[2:])
            if candidate["ratings"] and not self.count(candidate):
                raise DraftError("zero_match")
        elif op == "remove" and any(g["id"] == id for g in candidate["tags"]["groups"]):
            candidate["tags"]["groups"] = [g for g in candidate["tags"]["groups"] if g["id"] != id]
        else:
            found = next(((z, c) for z in ("include", "exclude") for c in candidate[z] if c["id"] == id), None)
            if found is None:
                raise DraftError("stale")
            source, chip = found
            if op == "remove":
                candidate[source].remove(chip)
            elif op == "mode":
                if type(exact) is not bool:
                    raise DraftError("too_many", "매칭 방식을 확인해주세요.")
                chip["exact"] = exact
            elif op == "move" and zone in ("include", "exclude"):
                candidate[source].remove(chip)
                candidate[zone].append(chip)
            else:
                raise DraftError("too_many", "칩 작업을 확인해주세요.")
            _limits(candidate)
            keys = [(c["text"], c["exact"]) for z in ("include", "exclude") for c in candidate[z]]
            if len(set(keys)) != len(keys):
                raise DraftError("duplicate")
            if op != "remove" and candidate != state and not self.count(candidate):
                raise DraftError("zero_match")
        self._recheck(candidate)
        return _finish(state, candidate)

    def extra(self, state, text, *, base_rev=None):
        candidate = _base(state, base_rev)
        if not isinstance(text, str) or len(text) > MAX_TEXT:
            raise DraftError("too_many")
        candidate["extra"] = text  # One original block, never split or expanded.
        return _finish(state, candidate)

    def drawn(self, state, op, tag, *, base_rev=None):
        candidate = _base(state, base_rev)
        d = candidate["drawn"]
        if d is None or tag not in {g["tag"] for g in _outputs(candidate)[1]}:
            raise DraftError("no_drawn")
        if op in ("keep", "exclude"):
            return self.chips(state, "add", zone="include" if op == "keep" else "exclude",
                              text="*" + tag, base_rev=base_rev)
        if op == "drop":
            if tag not in d["dropped"]:
                d["dropped"].append(tag)
        elif op == "undrop":
            d["dropped"] = [t for t in d["dropped"] if t != tag]
        else:
            raise DraftError("too_many", "회색 칩 작업을 확인해주세요.")
        return _finish(state, candidate)

    def derive(self, state):
        _, gray, chip_hits = _outputs(state)
        result = {"remaining": None, "include": [], "exclude": [], "gray": gray,
                  "rating_out": _rating_out(state),
                  "persons_label": " · ".join(PERSON_LABELS.get(p, p) for p in state["tags"]["persons"]) or None}
        try:
            idx = self._index()
        except DraftError:
            idx = None
        result["cond"] = self.condition_id(state)
        result["ratings_on"] = [r for r in RATINGS if r in (state["ratings"] or RATINGS)]
        result["rating_counts"] = None
        if idx is not None:
            result["remaining"] = self._condition(state, idx, self.service.permanent_block(idx)).count
            result["rating_counts"] = self.rating_counts(state, idx=idx)
        for zone in ("include", "exclude"):
            for c in state[zone]:
                row = {"id": c["id"], "count": self._chip_count(idx, c) if idx else 0,
                       "hits": int(np.count_nonzero(idx.matching_tags(c["text"], c["exact"]))) if idx else 0}
                if zone == "include":
                    row["chip_hits"] = chip_hits[c["id"]]
                result[zone].append(row)
        return result

    def pick(self, state, *, rng=None):
        idx = self._index()
        cond = self._condition(state, idx, self.service.permanent_block(idx))
        if not cond.count:
            raise MapQueryError("no_match", _MESSAGES["zero_match"])
        chooser = rng or random
        current = (state.get("drawn") or {}).get("rid")
        if cond.count > 1 and current is not None and cond.has(current):
            # 지금 뽑혀 있는 게시물은 다시 뽑지 않는다 - 조건이 좁으면(남은 10건 = 열 번에 한 번) 같은 글이 또 나와
            # Random 이 '씹힌' 것처럼 보였다(사용자 제보 2026-11-12). 나머지에서 고르게: 끝 자리를 제 자리로 돌려 쓴다.
            rid = int(cond.nth(chooser.choice(range(cond.count - 1))))
            if rid == current:
                rid = int(cond.nth(cond.count - 1))
        else:
            rid = int(chooser.choice(cond))
        pinned = [idx.resolve(c["text"]) for c in state["include"] if c["exact"]]
        post = idx.post_tags(rid, pinned=pinned, include_color=True)
        return {"rid": rid, "partition": post["partition"], "post_tags": post["tags"]}

    build_row = staticmethod(build_row)

    def remaining_tags(self, state, *, group="", sort="mix", q="", limit=60, offset=0):
        """지금 조건에 남은 게시물들이 가진 태그 - 이벤트 맵 후보 목록의 Draft 판(사용자 지시 2026-11-12).

        줄 세우기 · 갈래 탭은 이벤트 맵의 것을 그대로 쓴다(`EventMapIndex._rank` · `service._attach_groups`).
        다른 점: 조건이 핀 교집합이 아니라 칩 비트표라서 텍스트 칩 · 묶음 제외 · 등급 단추가 그대로 먹고,
        색상 · 인원 태그도 후보다(Draft 는 둘 다 보통 칩으로 센다). 3단 지도는 쓰지 않는다.
        """
        from core.event_map.index import RANK_PRIOR, SCAN_CAP, SORT_MODES
        if sort not in SORT_MODES:
            raise DraftError("too_many", "정렬을 확인해주세요.")
        if not isinstance(q, str) or len(q) > 160 or not isinstance(group, str):
            raise DraftError("too_many", "요청 형식을 확인해주세요.")
        try:
            limit, offset = max(1, min(200, int(limit))), max(0, int(offset))
        except (TypeError, ValueError):
            raise DraftError("too_many", "요청 형식을 확인해주세요.")
        idx = self._index()
        block = self.service.permanent_block(idx)
        cond = self._condition(state, idx, block)
        out = {"ok": True, "total": cond.count, "sampled": False, "scanned": cond.count, "sort": sort,
               "group": group, "items": [], "group_counts": [], "pool": 0, "rev": state.get("rev"),
               "cond": self.condition_id(state)}
        if not cond.count:
            return out
        counts = cond.tag_counts(idx)                 # 작은 조건(POOL_LIMIT 이하)은 정확히 센다 · 자동완성과 같은 표
        base = cond.count
        if counts is None:
            # 큰 조건은 이벤트 맵처럼 고르게 건너뛰며 뜬 표본에서 센다(앞에서 자르면 한 분면만 본다). 조건마다 한 번.
            with cond._lock:
                sample = getattr(cond, "_remaining_sample", None)
                if sample is None:
                    rids = np.flatnonzero(np.unpackbits(cond.packed)[:cond.size]).astype(np.int64)
                    if rids.size > SCAN_CAP:
                        rids = rids[np.linspace(0, rids.size - 1, SCAN_CAP).astype(np.int64)]
                    sample = cond._remaining_sample = (idx._count_tags(rids), int(rids.size))
            counts, base = sample
            out.update(sampled=base < cond.count, scanned=base)
        keep = (counts >= (2 if out["sampled"] else 1)) & idx.usable_arr & (idx.obs_arr > 0)
        if block is not None:
            keep &= ~block.tags
        own = [idx.resolve(c["text"]) for z in ("include", "exclude") for c in state[z] if c["exact"]]
        keep[[t for t in own if t is not None]] = False       # 이미 퍼펙트 칩으로 넣은 태그는 내지 않는다
        needle = q.strip().lower()
        if needle:
            named = np.zeros(idx.n_tags, dtype=bool)
            for tid in np.flatnonzero(keep):
                if needle in idx.by_id[int(tid)].lower():
                    named[tid] = True
            if self.kr_lookup is not None and not needle.isascii():
                for tag in self.kr_lookup(needle, 60) or []:
                    tid = idx.resolve(tag)
                    if tid is not None:
                        named[tid] = True
            keep &= named
        out["_pool"] = keep.copy()                      # 갈래 필터 전의 풀 - 탭의 개수용. _attach_groups 가 지운다
        out["pool"] = int(keep.sum())
        if group:
            mask = self.service.group_mask([group])
            if mask is None:
                raise DraftError("too_many", "갈래를 확인해주세요.")
            keep &= mask
        rows = idx._rank(counts, keep, base, cond.count, out["sampled"], limit, RANK_PRIOR, sort=sort, offset=offset)
        self.service._attach_groups(rows, out)
        out.pop("_pool", None)
        try:
            descriptions = self.describe([r["tag"] for r in rows]) if self.describe is not None and rows else {}
        except Exception:
            descriptions = {}
        out["items"] = [{"tag": r["tag"], "count": r["observed_estimate"], "seen": r["observed"],
                         "share": r["share"], "lift": r["lift"], "group": r.get("group"),
                         "all": (not out["sampled"]) and r["observed"] >= base,
                         "desc": descriptions.get(r["tag"])} for r in rows]
        out["more"] = offset + len(rows) < int(keep.sum())
        return out

    def suggest(self, q, zone, *, state=None, counts=True):
        """Global names/counts, or exact pool suggestions on a small condition."""
        state = state if state is not None else new_state()
        raw = str(q or "").strip().lower()
        exact = raw.startswith("*")
        raw = raw[1:].strip() if exact else raw
        if not raw:
            return {"ok": True, "items": []}
        if len(raw) > 160 or zone not in ("include", "exclude"):
            raise DraftError("too_many")
        idx = self._index()
        block = self.service.permanent_block(idx)
        current = self._cached_condition(self._condition_key(state), idx, block)
        # Snapshots/checks already memoize the current condition. A names-only
        # request must not build an unknown large condition just to select a lane.
        if current is None and not counts and idx.offsets.size - 1 <= min(POOL_INLINE, POOL_LIMIT):
            current = self._condition(state, idx, block)
        pool = (not counts and current is not None and current.count <= POOL_LIMIT
                and (current.count <= POOL_INLINE or current.has_tag_counts()))
        vector = current.tag_counts(idx) if pool else None
        items = []      # 등급 줄은 없다 - 등급은 판의 단추로 고른다(2026-11-12)
        picked, _, groups = self.service.suggest_candidates(raw, 20, kr_lookup=self.kr_lookup)
        existing = {c["text"] for z in ("include", "exclude") for c in state[z]}
        bound = None if pool or exact else ("min" if zone == "include" else "max")
        by_group = {g: [] for g in ("prefix", "infix", "korean")}
        for observed, name, tid in picked:
            if name in existing or name in RATING_ALIASES:
                continue
            by_group[groups[name]].append((observed, name, tid))
        rows = []
        scope = None
        if pool:
            # 조건 안에 있는 태그 중 이름에 입력이 든 것. 줄의 후보이자, 후보의 합집합 수를 셀 때 찾아볼 범위다 -
            # 후보 이름에 입력이 들어 있으면 그 이름이 든 태그는 전부 이 안에 있다(이미 칩인 태그도 수에는 보탠다).
            scope = [(lower, tid) for lower, tid in current.present(idx) if raw in lower]
            present = [(int(vector[tid]), int(idx.observed[tid]), idx.by_id[tid], tid) for _, tid in scope
                       if idx.by_id[tid] not in existing and idx.by_id[tid] not in RATING_ALIASES]
            present.sort(key=lambda r: (-r[0], -r[1]))
            rows.extend((name, tid, "prefix" if name.lower().startswith(raw) else "infix")
                        for _, _, name, tid in present)
        seen = {name for name, _, _ in rows}
        for group, candidates in by_group.items():
            if not pool or group != "korean":
                candidates.sort(key=lambda r: -r[0])
            for _, name, tid in candidates:
                if name not in seen:
                    rows.append((name, tid, group))
                    seen.add(name)
        tids = {}
        for name, tid, group in rows[:max(0, 20 - len(items))]:
            tids[name] = tid
            try:
                facets = self.service.tag_facets(idx, tid)
            except Exception:
                facets = {"major": None, "minor": None, "path": None}
            items.append({"tag": name, "kind": "tag", "kr": None, "group": group,
                          "count_after": None, "bound": bound, "slow": False,
                          "blocked": block is not None and bool(block.tags[tid]),
                          "hits": None, "observed": int(idx.observed[tid]),
                          "major": facets.get("major"), "minor": facets.get("minor"),
                          "path": facets.get("path"), "desc": None})
        try:
            descriptions = self.describe(list(tids)) if self.describe is not None and tids else {}
            for item in items:
                if item["kind"] == "tag":
                    item["desc"] = descriptions.get(item["tag"])
        except Exception:
            pass
        if (counts or pool) and items:
            if current is None:
                current = self._condition(state, idx, block)
            tag_items = [i for i in items if i["kind"] == "tag"]
            if tag_items and current.count <= POOL_LIMIT:
                vector = current.tag_counts(idx)
            mask = current.mask() if tag_items and vector is None else None
            for item in items:
                if item["kind"] == "rating":
                    if item["blocked"]:
                        continue
                    candidate = deepcopy(state)
                    candidate["ratings"].append(item["rating"])
                    item["count_after"] = self._condition(candidate, idx, block, memo=False).count
                    item["blocked"] = item["count_after"] == 0
                    continue
                tid = tids[item["tag"]]
                if pool and not exact:
                    lower = item["tag"].lower()
                    hits = current.text_hits(idx, lower, scope if raw in lower else None)
                elif vector is not None:
                    hits = int(vector[tid])
                else:
                    posting = idx.posting(tid)
                    if posting.size and posting[-1] >= mask.size:
                        posting = posting[posting < mask.size]
                    hits = int(np.count_nonzero(mask[posting])) if posting.size else 0
                count = hits if zone == "include" else current.count - hits
                item.update(hits=hits, count_after=count)
                item["blocked"] = item["blocked"] or (count == 0 and bound != "min")
            if pool:
                ratings = [i for i in items if i["kind"] == "rating"]
                positive = [i for i in tag_items if i["hits"] > 0 and i["group"] != "korean"]
                positive.sort(key=lambda i: -i["hits"])
                korean = [i for i in tag_items if i["hits"] > 0 and i["group"] == "korean"]
                items = ratings + positive + korean + [i for i in tag_items if i["hits"] == 0]
        return {"ok": True, "items": items, "counted": bool(counts or pool), "order": "pool" if pool else "global"}

    def to_staging(self, state):
        _limits(state)
        if not state["include"]:
            raise DraftError("no_include")
        terms = [c["text"] for c in state["include"] if not c["exact"]]
        terms += ["-" + c["text"] for c in state["exclude"] if not c["exact"]]
        groups = [{"terms": terms[i:i + 16], "invert": False} for i in range(0, len(terms), 16)]
        groups += [{k: deepcopy(v) for k, v in g.items() if k != "id"} for g in state["tags"]["groups"]]
        selected = {"pins": [c["text"] for c in state["include"] if c["exact"]],
                    "exclude": [c["text"] for c in state["exclude"] if c["exact"]],
                    "ratings": state["ratings"] or list(RATINGS),
                    "persons": state["tags"]["persons"] or list(PERSON_GROUPS)}
        if groups:
            selected["filters"] = groups
        try:
            selected = selection(selected)
        except MapQueryError as exc:
            raise DraftError("too_many", "스테이징에 담기엔 칩이 많습니다.") from exc
        return {"selection": selected, "extra": {"on": bool(state["extra"]), "text": state["extra"]}}

    def from_staging(self, state, item, *, base_rev=None):
        """Only individual rows. Caller can report discarded(item) alongside state."""
        candidate = _base(state, base_rev)
        if not isinstance(item, dict) or item.get("kind") in ("bundle", "group") or "selection" not in item:
            raise DraftError("no_include", "개별 스테이징 줄만 불러올 수 있습니다.")
        try:
            selected = selection(item["selection"])
        except MapQueryError as exc:
            raise DraftError("too_many", "불러올 조건의 상한을 확인해주세요.") from exc
        candidate.update(include=[], exclude=[], ratings=[], tags={"persons": [], "groups": []}, drawn=None)
        for zone, key in (("include", "pins"), ("exclude", "exclude")):
            for text in selected[key]:
                _chip(candidate, zone, self._parse("*" + text)[0], True)
        for group in selected.get("filters", []):
            if group["invert"] and len(group["terms"]) > 1:
                candidate["tags"]["groups"].append({"id": _next_id(candidate, "t"), **deepcopy(group)})
                continue
            for term in group["terms"]:
                negative = term.startswith("-")
                clean = term[1:] if negative else term
                exact = clean.startswith("*")
                clean = clean[1:] if exact else clean
                zone = "exclude" if negative != group["invert"] else "include"
                _chip(candidate, zone, clean, exact)
        candidate["ratings"] = [] if set(selected["ratings"]) == set(RATINGS) else selected["ratings"]
        candidate["tags"]["persons"] = [] if set(selected["persons"]) == set(PERSON_GROUPS) else selected["persons"]
        own = item.get("extra") or {}
        candidate["extra"] = own.get("text", "") if own.get("on") is True else ""
        return _finish(state, candidate)

    @staticmethod
    def discarded(item):
        return ["compress"] if any(k.startswith("compress") for k in item.get("selection", {})) else []

    def from_staging_id(self, state, staging, item_id, *, base_rev=None):
        item = next((r for r in staging.list()["items"] if r["id"] == item_id), None)
        return self.from_staging(state, item, base_rev=base_rev)


# UNIT 2: session wiring. The data operations above remain copy-on-write.
def active(context):
    holder = getattr(context, "event_map_draft", None)
    return bool(holder and holder.state["active"])


def saved_prompt(context):
    return (context.event_map_draft.state["saved_prompt"] if active(context)
            else str(getattr(context, "prompt_text", "") or ""))


def exit_for_owner(context, owner):
    if not active(context):
        return
    holder = context.event_map_draft
    _, messages = holder.mutate("exit", {})
    messages.append({"type": "toast", "level": "info", "message": f"{owner} 사용으로 Draft를 종료했습니다."})
    if holder.broadcast:
        for message in messages:
            holder.broadcast(message)


def session(context):
    from core.headless_random_prompt_service import pipeline_swap_lock
    holder = getattr(context, "event_map_draft", None)
    if holder is not None:
        return holder   # 이미 있으면 잠금 없이 - 자동완성이 생성 조립을 기다리지 않게(11-07)
    with pipeline_swap_lock(context):
        holder = getattr(context, "event_map_draft", None)
        if holder is None:
            holder = DraftSession(context)
            context.event_map_draft = holder
        return holder


class DraftSession:
    def __init__(self, context):
        from core.event_map.random_link import ensure_event_map_service
        self.context = context
        self.store = DraftStore.from_context(context)
        self.state = self.store.load()
        self.engine = EventMapDraft(ensure_event_map_service(context))
        self.lock = threading.RLock()
        self.broadcast = None
        # 실행할 때는 늘 꺼진 채로(사용자 지시 11-07). 켜진 채 저장돼 있었으면 끈 것으로 적는다 - 칩 · Extra 는 남겨
        # 다시 켜면 그대로 쓴다. 메인 글은 건드리지 않는다: Draft 중에도 저장되는 글은 saved_prompt(원문)이다.
        if self.state["active"]:
            candidate = deepcopy(self.state)
            candidate["active"] = False
            try:
                self.state = self.store.save(candidate)
            except DraftError:
                self.state = candidate   # 못 적어도 이번 실행은 꺼진 채 - 다음 저장이 덮는다

    def snapshot(self):
        from core.headless_random_prompt_service import pipeline_swap_lock
        from core.prompt_processor import _protected_key
        with pipeline_swap_lock(self.context), self.lock:
            derived = self.engine.derive(self.state)
            metadata = getattr(getattr(self.context, "current_prompt_context", None), "metadata", {})
            after = metadata.get("draft_after_pe")
            if after is not None:
                for gray in derived["gray"]:
                    gray["pe_hidden"] = _protected_key(gray["tag"]) not in after
            return {"ok": True, "gen": self.state["gen"], "rev": self.state["rev"],
                    "available": derived["remaining"] is not None,
                    "state": {k: deepcopy(v) for k, v in self.state.items() if k not in ("schema", "gen", "rev")},
                    "derived": derived, "prompt": str(getattr(self.context, "prompt_text", "") or "")}

    def _backup(self):
        ctx = self.context
        fields = {k: getattr(ctx, k, None) for k in
                  ("current_source_row", "current_prompt_context", "prompt_text", "negative_prompt_text")}
        metadata = getattr(fields["current_prompt_context"], "metadata", {})
        keys = ("conditional_character_overrides", "_conditional_character_slots", "conditional_character_skips")
        conditional = {k: deepcopy(metadata[k]) for k in keys if k in metadata}
        mode = ctx.get_api_mode()
        rolls = getattr(ctx, "_character_roll_snapshot", {}) or {}
        return fields, keys, conditional, mode, mode in rolls, deepcopy(rolls.get(mode))

    def _restore(self, backup):
        fields, keys, conditional, mode, existed, roll = backup
        for key, value in fields.items():
            setattr(self.context, key, value)
        metadata = getattr(fields["current_prompt_context"], "metadata", None)
        if isinstance(metadata, dict):
            for key in keys:
                metadata.pop(key, None)
            metadata.update(conditional)
        rolls = getattr(self.context, "_character_roll_snapshot", None)
        if isinstance(rolls, dict):
            if existed:
                rolls[mode] = roll
            else:
                rolls.pop(mode, None)

    def commit(self, candidate, *, roll_characters=False, request_id="", overrides=None):
        """Caller holds pipeline + draft locks; failure never installs a candidate."""
        from app.backend.server.generation_commands import random_service
        old = self.state
        backup = self._backup()
        result = None
        try:
            # Persistence in the pipeline must see the candidate's saved_prompt.
            self.state = candidate
            if candidate["active"]:
                result = random_service(self.context).generate_from_source_row(
                    build_row(candidate), source="event_map_draft", update_context=True,
                    roll_characters=roll_characters, random_request_id=request_id,
                    overrides={**(overrides or {}), "wildcard_standalone": False})
                if not result.success:
                    raise DraftError("rebuild_failed")
            self.state = self.store.save(candidate, force_revision=candidate["rev"] > old["rev"])
        except Exception as exc:
            self.state = old
            self._restore(backup)
            if isinstance(exc, DraftError):
                raise
            raise DraftError("rebuild_failed") from exc
        return result

    def rebuild(self, *, saved=None, notify=True):
        from core.headless_random_prompt_service import pipeline_swap_lock
        with pipeline_swap_lock(self.context), self.lock:
            if not self.state["active"]:
                return self.snapshot()
            candidate = deepcopy(self.state)
            if saved is not None:
                candidate["saved_prompt"] = saved
            candidate["rev"] += 1
            result = self.commit(candidate)
            snap = self.snapshot()
            if notify and self.broadcast:
                if result is not None:
                    self.broadcast(result.websocket_payload())
                self.broadcast({"type": "event_map_draft", **snap})
            return snap

    def mutate(self, action, body):
        from core.headless_random_prompt_service import pipeline_swap_lock
        from core.event_map.random_link import link_state, staging_store
        ctx = self.context
        if action == "remaining":
            # 읽기만 한다(자동완성과 같은 길) - 잠금을 기다리지 않는다
            return self.engine.remaining_tags(
                self.state, group=body.get("group") or "", sort=body.get("sort") or "mix",
                q=body.get("q") or "", limit=body.get("limit", 60), offset=body.get("offset", 0)), []
        if action in ("suggest", "check"):
            # 읽기만 한다 - 생성 조립 · 랜덤 파이프라인(pipeline_swap_lock) · 칩 편집의 재조립(self.lock)을 기다리지 않는다
            # (사용자 지적 11-07: 자동완성이 느리다). 상태는 통째로 갈아 끼우기만 하므로(제자리 수정 없음) 참조 하나를 읽는다.
            state = self.state
            self.engine._index()
            for key in ("zone", "text"):
                if key in body and not isinstance(body[key], str):
                    raise DraftError("too_many", "요청 형식을 확인해주세요.")
            if action == "check":
                if not isinstance(body.get("zone"), str) or not isinstance(body.get("text"), str):
                    raise DraftError("too_many", "요청 형식을 확인해주세요.")
                return self.engine.check(body.get("zone"), body.get("text"), state=state), []
            suggestions = self.engine.suggest(body.get("q"), body.get("zone", "include"), state=state,
                                              counts=body.get("counts", True) is not False)
            for item in suggestions["items"]:
                item.setdefault("bound", None)
            return suggestions, []
        with pipeline_swap_lock(ctx), self.lock:
            if action != "exit":
                self.engine._index()
            state = self.state
            required_text = {"check": ("zone", "text"), "extra": ("text",), "drawn": ("op", "tag"),
                             "chips": ("op",), "from-staging": ("item_id",)}
            if any(not isinstance(body.get(k), str) for k in required_text.get(action, ())):
                raise DraftError("too_many", "요청 형식을 확인해주세요.")
            for key in ("id", "zone", "text"):
                if key in body and not isinstance(body[key], str):
                    raise DraftError("too_many", "요청 형식을 확인해주세요.")
            result = None
            extras = {}
            messages = []
            if action in ("enter", "exit"):
                entering = action == "enter"
                if state["active"] == entering:
                    return self.snapshot(), messages
                if entering and (getattr(ctx, "img2img_session", {}) or {}).get("active"):
                    raise DraftError("owned_by", "인페인트 세션을 먼저 닫아주세요.")
                candidate = deepcopy(state)
                old_link = link_state(ctx)
                old_prompt = getattr(ctx, "prompt_text", "")
                if entering:
                    if "prompt" in body:
                        if not isinstance(body["prompt"], str):
                            raise DraftError("too_many")
                        ctx.prompt_text = body["prompt"]
                    candidate["saved_prompt"] = ctx.prompt_text
                    if ctx.get_options().get("wildcard_standalone"):
                        ctx.set_option("wildcard_standalone", False)
                        messages.extend([{"type": "options", **ctx.get_options()},
                                         {"type": "toast", "level": "info", "message": "Draft를 위해 WC Solo를 해제했습니다."}])
                    story = getattr(ctx, "_storyteller_service", None)
                    if callable(story):
                        story = story()
                        stream = getattr(ctx, "event_stream_runtime", None)
                        if story.is_running() or getattr(stream, "is_active", False):
                            stopped = story.stop() if story.is_running() else story.disarm_manual()
                            messages.extend(stopped.get("_headless_extra_messages", []))
                            messages.append({"type": "toast", "level": "info", "message": "Draft를 위해 Story를 종료했습니다."})
                    ctx.event_map_random_link = {"enabled": True, "mode": "draft", "revision": old_link["revision"] + 1}
                elif body.get("keep") is True:
                    # [이 결과를 메인 프롬프트로](사용자 지시 11-07) - 원문으로 되돌리지 않고 지금 조립된 글을 메인에 남긴다.
                    # 화면이 보던 게시물(rid)이 지금 것이 아니면 거절한다 - 다른 뽑기의 글을 남기지 않게.
                    drawn = state["drawn"]
                    if drawn is None or type(body.get("rid")) is not int or body["rid"] != drawn["rid"]:
                        raise DraftError("stale")
                    if old_link.get("mode") == "draft":
                        ctx.event_map_random_link = {"enabled": False, "revision": old_link["revision"] + 1}
                else:
                    ctx.prompt_text = state["saved_prompt"]
                    if old_link.get("mode") == "draft":
                        ctx.event_map_random_link = {"enabled": False, "revision": old_link["revision"] + 1}
                candidate.update(active=entering, rev=state["rev"] + 1)
                ctx.prompt_owner_gen = getattr(ctx, "prompt_owner_gen", 0) + 1
                try:
                    result = self.commit(candidate)
                except Exception:
                    ctx.event_map_random_link = old_link
                    ctx.prompt_text = old_prompt
                    raise
                from app.backend.server.generation_commands import invalidate_auto_gen_prefetch
                invalidate_auto_gen_prefetch(ctx)
                ctx.save_remote_ui_state()
                messages.append({"type": "event_map_random_link", **link_state(ctx)})
            elif action == "to-staging":
                value = self.engine.to_staging(state)
                from core.event_map.library import EventMapLibrary
                data = staging_store(ctx).add_many([value["selection"]], extras=[value["extra"]])
                identity = EventMapLibrary._identity(value["selection"])
                item_id = next(r["id"] for r in data["items"]
                               if EventMapLibrary._identity(r["selection"]) == identity)
                messages.append({"type": "event_map_staging", "count": sum(r.get("enabled", True) for r in data["items"]),
                                 "total": len(data["items"])})
                return {"ok": True, "item_id": item_id, "snapshot": self.snapshot()}, messages
            else:
                base = body.get("base_rev")
                if base is not None and type(base) is not int:
                    raise DraftError("too_many")
                _base(state, base)
                if action == "chips":
                    candidate = self.engine.chips(state, body.get("op"), base_rev=base,
                        **{k: body.get(k) for k in ("id", "zone", "text", "exact")})
                    if candidate["extra"] != state["extra"]:
                        extras["routed"] = "extra"
                elif action == "extra":
                    candidate = self.engine.extra(state, body.get("text"), base_rev=base)
                elif action == "drawn":
                    candidate = self.engine.drawn(state, body.get("op"), body.get("tag"), base_rev=base)
                elif action == "from-staging":
                    item = next((r for r in staging_store(ctx).list()["items"] if r["id"] == body.get("item_id")), None)
                    candidate = self.engine.from_staging(state, item)
                    dropped = self.engine.discarded(item)
                    if dropped:
                        extras["dropped"] = dropped
                elif action == "rebuild":
                    if not state["active"]:
                        return self.snapshot(), messages
                    candidate = deepcopy(state)
                    candidate["rev"] += 1
                else:
                    raise DraftError("too_many")
                if candidate != state:
                    result = self.commit(candidate)
            if result is not None:
                messages.append(result.websocket_payload())
                messages.extend(result.extra_messages)
            snap = self.snapshot()
            messages.append({"type": "event_map_draft", **snap})
            return {**snap, **extras}, messages

    def random(self, request_id="", *, overrides=None):
        from core.headless_random_prompt_service import HeadlessRandomPromptResult, pipeline_swap_lock
        from core.event_map.random_link import link_state
        ctx = self.context
        for attempt in range(2):
            with pipeline_swap_lock(ctx), self.lock:
                state = deepcopy(self.state)
                revision = link_state(ctx)["revision"]
                if not state["active"]:
                    break
            try:
                picked = self.engine.pick(state)  # expensive selection stays outside the commit lock
            except MapQueryError as exc:
                return HeadlessRandomPromptResult(False, error=str(exc), random_request_id=request_id,
                                                 event_map_revision=revision, draft_rev=state["rev"])
            with pipeline_swap_lock(ctx), self.lock:
                if (state["gen"], state["rev"], revision) != (self.state["gen"], self.state["rev"], link_state(ctx)["revision"]):
                    continue
                if not self.state["active"]:
                    break
                state["drawn"] = {**picked, "dropped": []}
                state["rev"] += 1
                try:
                    result = self.commit(state, roll_characters=True, request_id=request_id, overrides=overrides)
                except DraftError as exc:
                    return HeadlessRandomPromptResult(False, error=exc.message, random_request_id=request_id,
                                                     event_map_revision=revision, draft_rev=self.state["rev"])
                result.source = "random"
                result.event_map_revision = revision
                result.draft_rev = self.state["rev"]
                result.extra_messages.append({"type": "event_map_draft", **self.snapshot()})
                return result
        return HeadlessRandomPromptResult(False, error="cancelled", random_request_id=request_id,
                                         event_map_revision=revision, draft_rev=self.state["rev"])
