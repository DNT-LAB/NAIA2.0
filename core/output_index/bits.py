"""Packed live/flag masks and a hybrid (dense bits / sparse positions) tag index."""
from collections import defaultdict
from collections.abc import Iterable
from heapq import nsmallest
from typing import Literal

import numpy as np

from .store import DECODED, EXIST, META_HEAD, NEEDS_DECODE, NO_META, READ_ERROR
from .tags import normalize_tag


_FLAGS = (EXIST, META_HEAD, NEEDS_DECODE, NO_META, DECODED, READ_ERROR)
_POP = np.array([i.bit_count() for i in range(256)], dtype=np.uint8)


def _pop(mask: np.ndarray) -> int:
    return int(_POP[mask].sum())


def _grow(column: np.ndarray, size: int) -> np.ndarray:
    # A reader may still hold a slice of the old allocation (e.g. exist).
    # Never invalidate such views with ndarray.resize(refcheck=False).
    result = np.zeros(size, column.dtype)
    result[:column.size] = column
    return result


def _set(mask: np.ndarray, positions: np.ndarray) -> None:
    # Several positions can share a byte. Fancy-index |= alone loses writes.
    np.bitwise_or.at(mask, positions >> 3, (1 << (positions & 7)).astype(np.uint8))


class IndexBits:
    """Consume ordered IndexStore.iter_rows(); append accepts the same row shape."""
    def __init__(self, rows: Iterable[dict] = ()):
        self.n_rows = 0
        self._mtime = np.empty(0, np.int64)
        self._source = np.empty(0, np.uint8)
        self._root = np.empty(0, np.int64)
        self._dir = np.empty(0, np.int64)
        self._flags = {flag: np.empty(0, np.uint8) for flag in _FLAGS}
        self.dense: dict[str, np.ndarray] = {}
        self.sparse: dict[str, np.ndarray] = {}
        self._extend(rows, building=True)

    @property
    def mtime(self) -> np.ndarray:
        return self._mtime[:self.n_rows]

    @property
    def source(self) -> np.ndarray:
        return self._source[:self.n_rows]

    @property
    def root(self) -> np.ndarray:
        return self._root[:self.n_rows]

    @property
    def dir(self) -> np.ndarray:
        return self._dir[:self.n_rows]

    @property
    def exist(self) -> np.ndarray:
        return self._flags[EXIST][:(self.n_rows + 7) // 8]

    def _reserve(self, needed: int) -> None:
        if needed <= self._mtime.size:
            return
        capacity = max(needed, 2 * self._mtime.size, 8)
        self._mtime = _grow(self._mtime, capacity)
        self._source = _grow(self._source, capacity)
        self._root = _grow(self._root, capacity)
        self._dir = _grow(self._dir, capacity)
        self._flags = {f: _grow(bits, (capacity + 7) // 8) for f, bits in self._flags.items()}

    def _extend(self, rows: Iterable[dict], building: bool) -> None:
        postings = defaultdict(list)
        for item in rows:
            i = self.n_rows
            if item["row"] != i:
                raise ValueError("expected consecutive row numbers")
            self._reserve(i + 1)
            self._mtime[i], self._source[i], self._root[i] = item["mtime_ns"], item["source"], item["root_id"] or 0
            self._dir[i] = item.get("dir_id") or 0
            for flag in _FLAGS:
                if item["flags"] & flag:
                    self._flags[flag][i >> 3] |= 1 << (i & 7)
            for tag in set(item["tags"]):
                postings[tag].append(i)
            self.n_rows += 1
        for tag, positions in postings.items():
            pos = np.asarray(positions, dtype=np.uint32)
            if building and len(pos) * 32 > self.n_rows:
                self.dense[tag] = np.zeros(len(self.exist), dtype=np.uint8)
            if tag in self.dense:
                bits = self.dense[tag]
                if bits.size <= positions[-1] >> 3:
                    self.dense[tag] = bits = _grow(bits, self._flags[EXIST].size)
                _set(bits, pos)
            elif tag in self.sparse:
                self.sparse[tag] = np.concatenate((self.sparse[tag], pos))
            else:
                self.sparse[tag] = pos

    def append(self, rows: Iterable[dict]) -> None:
        self._extend(rows, building=False)

    def set_dead(self, row: int) -> None:
        if not 0 <= row < self.n_rows:
            raise IndexError(row)
        self._flags[EXIST][row >> 3] &= 255 ^ (1 << (row & 7))

    def _names(self, chip: str) -> list[str]:
        if chip.startswith("*"):
            tag = normalize_tag(chip[1:])
            return [tag] if tag in self.dense or tag in self.sparse else []
        text = normalize_tag(chip)
        return [tag for table in (self.dense, self.sparse) for tag in table if text in tag]

    def _union(self, names: Iterable[str]) -> np.ndarray:
        sparse, dense = [], []
        for tag in names:
            if tag in self.sparse:
                sparse.append(self.sparse[tag])
            else:
                dense.append(self.dense[tag])
        if sparse:
            acc = np.zeros(self.n_rows, dtype=bool)
            acc[np.concatenate(sparse)] = True
            mask = np.packbits(acc, bitorder="little")
        else:
            mask = np.zeros_like(self.exist)
        for bits in dense:
            bits = bits[:mask.size]
            mask[:bits.size] |= bits
        return mask

    def _counts(self, names, mask):
        counts = {}
        keys, postings = [], []
        for name in names:
            if name in self.sparse:
                keys.append(name)
                postings.append(self.sparse[name])
            else:
                bits = self.dense[name][:mask.size]
                counts[name] = _pop(bits & mask[:bits.size])
        if postings:
            pos = np.concatenate(postings)
            starts = np.cumsum([0] + [p.size for p in postings[:-1]])
            live = np.unpackbits(mask, bitorder="little")[pos]
            counts.update(zip(keys, np.add.reduceat(live, starts, dtype=np.int64).tolist()))
        return counts

    def _condition(self, include, exclude, live):
        mask = live.copy()
        matched = set()
        for chips, negative in ((include, False), (exclude, True)):
            for chip in chips:
                names = self._names(chip)
                if not chip.startswith("*"):
                    matched.update(names)
                bits = self._union(names)
                mask &= ~bits if negative else bits
        return mask, matched

    def _visible(self, hidden_roots):
        if not hidden_roots:
            return self.exist
        keep = np.isin(self.root, list(hidden_roots), invert=True)
        return self.exist & np.packbits(keep, bitorder="little")

    def _page(self, mask: np.ndarray, desc: bool, offset: int, limit: int) -> list[int]:
        if not limit:
            return []
        rows = np.flatnonzero(np.unpackbits(mask, count=self.n_rows, bitorder="little"))
        end = min(offset + limit, rows.size)
        if offset >= end:
            return []
        # Complement rather than negate: also works for the minimum int64.
        keys = ~self.mtime[rows] if desc else self.mtime[rows]
        partition = np.argpartition(keys, (offset, end - 1))
        lo, hi = keys[partition[offset]], keys[partition[end - 1]]
        # Resolve boundary ties by original row number. Only the page (not
        # the offset+limit prefix) then needs sorting, even for deep pages.
        skip = offset - np.count_nonzero(keys < lo)
        first = np.flatnonzero(keys == lo)[skip:]
        length = end - offset
        if lo == hi:
            return rows[first[:length]].tolist()
        mid = partition[offset:end]
        mid = mid[(keys[mid] > lo) & (keys[mid] < hi)]
        last = np.flatnonzero(keys == hi)[:length - first.size - mid.size]
        selected = np.concatenate((first, mid, last))
        order = np.lexsort((rows[selected], keys[selected]))
        return rows[selected[order]].tolist()

    def select(self, include: Iterable[str] = (), exclude: Iterable[str] = (),
               sources: list[int] | None = None, roots: list[int] | None = None,
               hidden_roots: set[int] | None = None, dirs: list[int] | None = None) -> tuple:
        """(mask, top matched tags, matched tag total) - query and folders share one condition."""
        live = self._visible(hidden_roots)
        mask, names = self._condition(include, exclude, live)
        counts = self._counts(names, live)
        matched = [t for t in names if counts[t]]
        top = nsmallest(100, matched, key=lambda t: (-counts[t], t))
        for values, allowed in ((self.source, sources), (self.root, roots), (self.dir, dirs)):
            if allowed is not None:
                keep = np.isin(values, allowed)
                mask &= np.packbits(keep, bitorder="little")
        return mask, top, len(matched)

    def rows_of(self, mask: np.ndarray) -> np.ndarray:
        return np.flatnonzero(np.unpackbits(mask, count=self.n_rows, bitorder="little"))

    def query(self, include: Iterable[str] = (), exclude: Iterable[str] = (),
              sources: list[int] | None = None, roots: list[int] | None = None,
              hidden_roots: set[int] | None = None, sort: Literal["mtime_desc", "mtime_asc"] = "mtime_desc",
              offset: int = 0, limit: int = 100, dirs: list[int] | None = None) -> dict:
        if sort not in ("mtime_asc", "mtime_desc") or offset < 0 or limit < 0:
            raise ValueError("invalid sort or page")
        mask, top, total = self.select(include, exclude, sources, roots, hidden_roots, dirs)
        return {"count": _pop(mask), "rows": self._page(mask, sort == "mtime_desc", offset, limit),
                "matched": top, "matched_total": total}

    def group(self, rows, desc: bool = True, offset: int = 0, limit: int = 40,
              samples: int = 3) -> tuple[int, list[tuple[int, int, list[int]]]]:
        """Group rows by folder: (folder count, [(dir_id, rows in folder, first `samples` rows)]).

        Folders are ordered by their best row in the sort direction (newest first for desc),
        and so are the samples inside a folder - the same order the flat list would show.
        """
        if offset < 0 or limit < 0 or samples < 0:
            raise ValueError("invalid page")
        rows = np.asarray(rows, dtype=np.int64)
        if not rows.size:
            return 0, []
        dirs = self.dir[rows]
        # Complement rather than negate: also works for the minimum int64.
        keys = ~self.mtime[rows] if desc else self.mtime[rows]
        order = np.lexsort((rows, keys, dirs))
        rows, dirs, keys = rows[order], dirs[order], keys[order]
        starts = np.flatnonzero(np.r_[True, dirs[1:] != dirs[:-1]])
        sizes = np.diff(np.r_[starts, rows.size])
        folders = np.lexsort((dirs[starts], keys[starts]))[offset:offset + limit]
        return int(starts.size), [(int(dirs[starts[g]]), int(sizes[g]),
                                   rows[starts[g]:starts[g] + min(samples, int(sizes[g]))].tolist()) for g in folders]

    def suggest(self, q: str, limit: int = 20, include: Iterable[str] = (),
                exclude: Iterable[str] = (), hidden_roots: set[int] | None = None) -> list[tuple[str, int, int]]:
        if limit <= 0:
            return []
        live = self._visible(hidden_roots)
        condition, _ = self._condition(include, exclude, live)
        needle = normalize_tag(q)
        totals = self._counts(self._names(q), live)
        names = sorted((t for t in totals if totals[t]),
                       key=lambda t: (t != needle, not t.startswith(needle), -totals[t], t))[:limit]
        filtered = self._counts(names, condition)
        return [(t, totals[t], filtered[t]) for t in names]
