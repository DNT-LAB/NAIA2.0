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

    def __init__(self, service, *, kr_lookup=None):
        self.service = service
        self.kr_lookup = kr_lookup
        # 마지막 조건의 게시물 목록 하나(실측 2026-11-07: 큰 조건이면 ~280ms) - 자동완성 키마다 · 스냅숏마다 같은 조건을
        # 다시 센다. 열쇠 = 색인 · 영구 제외 객체 · 조건 글. 색인이 바뀌면(invalidate) 객체가 달라져 저절로 빗나간다.
        self._memo_key = None
        self._memo_rids = None
        # 그 게시물 목록의 비트 표(rid -> 있나) - 자동완성 후보 수를 교집합 대신 모아 읽기로 센다(실측 11-07:
        # 'w' 후보 1,677개 교집합 3.9초 -> 75ms). 열쇠 = 위 목록 객체 그대로(is).
        self._mask_for = None
        self._mask = None
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

    def _posts_mask(self, rids, idx):
        with self._memo_lock:
            if self._mask_for is rids:
                return self._mask
        mask = np.zeros(max(int(idx.offsets.size), int(rids[-1]) + 1 if rids.size else 0), dtype=bool)
        mask[rids] = True
        with self._memo_lock:
            self._mask_for, self._mask = rids, mask
        return mask

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

    def suggest(self, q, zone, *, state=None, counts=True):
        """후보 20개. `counts=False` 면 이름만(1ms 안쪽) - 화면이 먼저 띄우고 수는 `counts=True` 로 따로 받는다
        (사용자 지시 11-07: '자동완성은 미리 보여주고 수만 잠시 후에'). 차례는 두 번 모두 같다 = 무리(rating · 앞 · 가운데 ·
        한글) 안에서 **전체 출현 수** 순. 옛 차례(지금 조건 안의 수)는 후보 전부(앞부분 일치만 'w' 1,677개)를 세야 정해져
        키 하나에 4~9초였다. 이제 세는 것은 보여 줄 20개뿐이다."""
        state = state if state is not None else new_state()
        raw = str(q or "").strip().lower()
        exact = raw.startswith("*")
        raw = raw[1:].strip() if exact else raw
        if not raw:
            return {"ok": True, "items": []}
        if len(raw) > 160 or zone not in ("include", "exclude"):
            raise DraftError("too_many")
        idx = self._index()
        items = []
        for rating, name in RATINGS.items():
            if rating in state["ratings"] or not any(a.startswith(raw) for a, r in RATING_ALIASES.items() if r == rating):
                continue
            items.append({"tag": "rating:" + name, "kind": "rating", "rating": rating,
                          "label": "rating:" + name, "kr": None, "group": "rating",
                          "count_after": None, "slow": False, "blocked": zone == "exclude"})
        picked, _, groups = self.service.suggest_candidates(raw, 20, kr_lookup=self.kr_lookup)
        existing = {c["text"] for z in ("include", "exclude") for c in state[z]}
        block = self.service.permanent_block(idx)
        # 후보 수는 **그 태그 하나의 게시물 목록**으로 센다(실측 2026-11-07: 후보마다 텍스트 합집합을 만들면
        # 키 하나에 1~4초 · 64MB 캐시를 후보가 밀어낸다). 텍스트 칩의 실제 수는 합집합이라 이보다 작아질 수 없다 -
        # 포함 칸은 하한, 제외 칸은 남는 수의 상한이다. `bound` 로 알린다(화면 ≥ · ≤). 칩 추가는 늘 정확히 센다(check).
        bound = None if exact else ("min" if zone == "include" else "max")
        by_group = {g: [] for g in ("prefix", "infix", "korean")}
        for observed, name, tid in picked:
            if name in existing or name in RATING_ALIASES:
                continue
            by_group[groups[name]].append((observed, name, tid))
        tids = {}
        for group, rows in by_group.items():
            rows.sort(key=lambda r: -r[0])
            for _, name, tid in rows:
                tids[name] = tid
                items.append({"tag": name, "kind": "tag", "kr": None, "group": group,
                              "count_after": None, "bound": bound, "slow": False,
                              "blocked": block is not None and bool(block.tags[tid])})
        items = items[:20]
        if counts and items:
            current = self.posts(state, idx=idx)
            mask = self._posts_mask(current, idx)
            for item in items:
                if item["kind"] == "rating":
                    if item["blocked"]:
                        continue   # 제외 칸의 rating 은 칩이 될 수 없다 - 셀 것도 없다
                    # check() 는 posts() 한 칸 메모를 이 후보 조건으로 덮는다 - 다음 키에서 지금 조건을 다시 센다.
                    candidate = deepcopy(state)
                    candidate["ratings"].append(item["rating"])
                    item["count_after"] = int(self._posts(candidate, idx, block).size)
                    item["blocked"] = item["count_after"] == 0
                    continue
                posting = idx.posting(tids[item["tag"]])
                if posting.size and posting[-1] >= mask.size:
                    posting = posting[posting < mask.size]
                hits = int(np.count_nonzero(mask[posting])) if posting.size else 0
                count = hits if zone == "include" else int(current.size) - hits
                item["count_after"] = count
                item["blocked"] = item["blocked"] or (count == 0 and bound != "min")
        return {"ok": True, "items": items, "counted": bool(counts)}

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
