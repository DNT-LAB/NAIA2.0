"""Draft's pure data layer. No session, HTTP, or prompt-pipeline ownership.

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
from .index import _intersect_sorted
from .library import selection
from .service import MapQueryError, PERSON_LABELS
from core.tag_combo.person import PERSON_GROUPS

SCHEMA = "naia-event-map-draft-v1"
TEXT_CACHE_BYTES = 64 << 20
RATINGS = dict(zip("gsqe", ("general", "sensitive", "questionable", "explicit")))
RATING_ALIASES = {alias: rating for rating, name in RATINGS.items()
                  for alias in (name, "rating:" + name, "rating:" + rating)}
_STORE_LOCK = threading.RLock()
_MESSAGES = {
    "zero_match": "조건에 맞는 게시물이 없습니다.",
    "stale": "조건이 바뀌었습니다. 최신 상태에서 다시 시도해주세요.",
    "duplicate": "이미 있는 칩입니다.",
    "rating_in_exclude": "등급은 포함 칸에서 고르세요",
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
            self.bytes = 0

    def retire(self, idx):
        with self._lock:
            self._retired.add(idx)
            self._epoch += 1
            for key in list(self.entries):
                if key[0] is idx:
                    self.bytes -= self.entries.pop(key).nbytes
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
                for tid in np.flatnonzero(idx.matching_tags(key[1])):
                    mask[idx.posting(int(tid))] = True
                packed = np.packbits(mask)
                packed.flags.writeable = False
            with self._lock:
                if epoch == self._epoch and idx not in self._retired and packed.nbytes <= self.budget:
                    while self.entries and self.bytes + packed.nbytes > self.budget:
                        self.bytes -= self.entries.popitem(last=False)[1].nbytes
                    self.entries[key] = packed
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


TEXT_CACHE = TextPostCache()


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

    def save(self, state, *, base_rev=None):
        with _STORE_LOCK:
            current = self.load()
            if self.path.exists() and state["gen"] != current["gen"]:
                raise DraftError("stale")
            if state["rev"] < current["rev"]:
                raise DraftError("stale")
            _base(current, base_rev)
            candidate = deepcopy(state)
            comparable = {**candidate, "rev": current["rev"]}
            if comparable == current:
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

    def __init__(self, service, *, kr_lookup=None):
        self.service = service
        self.kr_lookup = kr_lookup
        # 마지막 조건의 게시물 목록 하나(실측 2026-11-07: 큰 조건이면 ~280ms) - 자동완성 키마다 · 스냅숏마다 같은 조건을
        # 다시 센다. 열쇠 = 색인 · 영구 제외 객체 · 조건 글. 색인이 바뀌면(invalidate) 객체가 달라져 저절로 빗나간다.
        self._memo_key = None
        self._memo_rids = None
        self._memo_lock = threading.Lock()

    def _index(self):
        try:
            return self.service.index()
        except MapQueryError as exc:
            raise DraftError("unavailable") from exc

    @staticmethod
    def _set(idx, chip):
        if chip["exact"]:
            tid = idx.resolve(chip["text"])
            return idx.posting(tid) if tid is not None else np.empty(0, dtype=np.int64)
        return TEXT_CACHE.posts(idx, chip["text"])

    def posts(self, state, *, idx=None):
        idx = idx or self._index()
        block = self.service.permanent_block(idx)
        key = (id(idx), id(block), json.dumps([state["include"], state["exclude"], state["ratings"],
                                                state["tags"]], sort_keys=True))
        with self._memo_lock:
            if self._memo_key == key:
                return self._memo_rids
        rids = self._posts(state, idx, block)
        rids.flags.writeable = False
        with self._memo_lock:
            self._memo_key, self._memo_rids = key, rids
        return rids

    def _posts(self, state, idx, block):
        parts = idx._partition_filter(state["ratings"], state["tags"]["persons"])
        sets = sorted((self._set(idx, c) for c in state["include"]), key=len)
        if sets:
            rids = sets[0]
            for other in sets[1:]:
                rids = _intersect_sorted(rids, other)
            if parts is not None:
                rids, owners = idx._partition_of(rids)
                rids = rids[idx._part_lut(parts)[owners]]
        else:
            rids = idx._live_posts(parts)
        for chip in state["exclude"]:
            rids = rids[~np.isin(rids, self._set(idx, chip), assume_unique=True)]
        rids = idx.filter_posts(rids, state["tags"]["groups"])
        return np.array(idx._unblocked(rids, block), copy=True)

    def count(self, state):
        return int(self.posts(state).size)

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
            out.update(kind="rating", rating=rating)
            if zone == "exclude":
                return blocked("rating_in_exclude")
            if rating in state["ratings"]:
                return blocked("duplicate")
            candidate["ratings"].append(rating)
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
        out["count_after"] = int(self.posts(candidate, idx=idx).size)
        return blocked("zero_match") if not out["count_after"] else out

    def _recheck(self, state):
        drawn = state["drawn"]
        if drawn is None:
            return
        idx = self._index()
        rids = self.posts(state, idx=idx)
        at = np.searchsorted(rids, drawn["rid"])
        if at == rids.size or rids[at] != drawn["rid"]:
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
            if result["kind"] == "rating":
                candidate["ratings"].append(result["rating"])
            else:
                _chip(candidate, zone, result["text"], result["exact"])
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
        if idx is not None:
            result["remaining"] = int(self.posts(state, idx=idx).size)
        for zone in ("include", "exclude"):
            for c in state[zone]:
                row = {"id": c["id"], "count": int(self._set(idx, c).size) if idx else 0,
                       "hits": int(np.count_nonzero(idx.matching_tags(c["text"], c["exact"]))) if idx else 0}
                if zone == "include":
                    row["chip_hits"] = chip_hits[c["id"]]
                result[zone].append(row)
        return result

    def pick(self, state, *, rng=None):
        idx = self._index()
        rids = self.posts(state, idx=idx)
        if not rids.size:
            raise MapQueryError("no_match", _MESSAGES["zero_match"])
        rid = int((rng or random).choice(rids))
        pinned = [idx.resolve(c["text"]) for c in state["include"] if c["exact"]]
        post = idx.post_tags(rid, pinned=pinned, include_color=True)
        return {"rid": rid, "partition": post["partition"], "post_tags": post["tags"]}

    build_row = staticmethod(build_row)

    def suggest(self, q, zone, *, state=None):
        state = state if state is not None else new_state()
        raw = str(q or "").strip().lower()
        exact = raw.startswith("*")
        raw = raw[1:].strip() if exact else raw
        if not raw:
            return {"ok": True, "items": []}
        if len(raw) > 160 or zone not in ("include", "exclude"):
            raise DraftError("too_many")
        idx = self._index()
        buckets = {g: [] for g in ("rating", "prefix", "infix", "korean")}
        for rating, name in RATINGS.items():
            if rating in state["ratings"] or not any(a.startswith(raw) for a, r in RATING_ALIASES.items() if r == rating):
                continue
            check = self.check(zone, name, state=state)
            buckets["rating"].append({"tag": "rating:" + name, "kind": "rating", "rating": rating,
                                      "label": "rating:" + name, "kr": None, "group": "rating",
                                      "count_after": check["count_after"], "slow": False,
                                      "blocked": check["kind"] == "blocked"})
        picked, _, groups = self.service.suggest_candidates(raw, 20, kr_lookup=self.kr_lookup)
        existing = {c["text"] for z in ("include", "exclude") for c in state[z]}
        block = self.service.permanent_block(idx)
        current = self.posts(state, idx=idx)
        for _, name, tid in picked:
            if name in existing or name in RATING_ALIASES:
                continue
            slow = False   # 늘 센다(아래) - 옛 '걸린 태그 > 200 은 수 생략' 은 합집합을 만들 때의 규칙이었다
            blocked = block is not None and bool(block.tags[tid])
            # 후보 수는 **그 태그 하나의 게시물 목록**으로 센다(실측 2026-11-07: 후보마다 텍스트 합집합을 만들면
            # 키 하나에 1~4초 · 64MB 캐시를 후보가 밀어낸다). 텍스트 칩의 실제 수는 합집합이라 이보다 작아질 수 없다 -
            # 포함 칸은 하한, 제외 칸은 남는 수의 상한이다. `bound` 로 알린다(화면 ≥ · ≤). 칩 추가는 늘 정확히 센다(check).
            hits_in_current = _intersect_sorted(current, idx.posting(tid)).size
            count = int(hits_in_current if zone == "include" else current.size - hits_in_current)
            bound = None if exact else ("min" if zone == "include" else "max")
            buckets[groups[name]].append({"tag": name, "kind": "tag", "kr": None,
                                         "group": groups[name], "count_after": count, "bound": bound,
                                         "slow": slow, "blocked": blocked or (count == 0 and bound != "min")})
        items = []
        for rows in buckets.values():
            rows.sort(key=lambda r: -(r["count_after"] if r["count_after"] is not None else -1))
            items.extend(rows)
        return {"ok": True, "items": items[:20]}

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
