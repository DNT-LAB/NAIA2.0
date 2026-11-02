"""이벤트 맵 압축(사용자 지시 2026-11-02) - 조합에 붙는 상태 `selection.compress` + `compress_cut` + `compress_output`.

화면은 **기준 축**을 고른다(핀의 축은 늘 기준 - 끌 수 없다). 저장 값 `compress` = 기준이 아닌 축(지운 축) 목록 - 비면 압축 안 함.
기준 축의 태그(+ 핀 · 인원 태그 + 등급)가 같은 게시물끼리 **이벤트** 하나로 묶는다. 작품·고유명 · 미분류 태그는 축 밖이라 묶을 때 빠진다.
압축된 조합의 랜덤은 게시물이 아니라 이벤트를 **같은 확률로** 뽑는다(사용자 결정 2026-11-02) - 흔한 장면이 랜덤을 덮지 않게.
프롬프트 = [프롬프트 전체] 그 이벤트에 묶인 게시물 하나의 태그 전부(기본) | [선택한 축만] 기준 축 태그만(`compress_output`).
색상은 맵 정책대로 늘 빠진다(핀이면 남는다) - `EventMapIndex.sample` 과 같다.

슬라이더 둘(`compress_cut` - Quick Filter 이벤트 압축 창과 같은 뜻 · 사용자 결정 2026-11-02):
- 빈도 = 태그 하나가 나오는 이벤트 수. 범위 밖 태그는 이벤트를 거르지 않고 **태그 수에서만** 빠진다(프롬프트엔 남는다).
  핀 · 인원 태그는 늘 센다.
- 태그 수 = 이벤트에서 세는 태그 개수. 범위 밖 이벤트는 랜덤에서 빠진다.
후보 게시물이 50만을 넘으면 50만만 쓴다(나머지는 버림 · 사용자 지시 2026-11-02) - 조건마다 고정된 표본.

Search 의 이벤트 압축(`core/event_compress.py`)과 뜻은 같지만 출처가 다르다: 저쪽은 Search 풀 + PE '특징 제거',
여기는 이벤트 맵 색인 + 이벤트 맵 갈래(`kr_category_fold.json`).

계산: 게시물마다 남은 태그의 64비트 무작위 값을 더한 합(+ 등급 값)을 열쇠로 삼는다 - 게시물 안 태그는 겹치지 않으므로
합이 곧 집합의 지문이다(충돌 확률 ~ 이벤트 수² / 2^64). 파이썬 반복문 없이 본문을 한 번 긁는다(`_count_tags` 와 같은 수).
같은 조건이면 표(이벤트 · 이벤트별 태그 · 태그 빈도)를 캐시에서 쓴다 - 랜덤 단추와 슬라이더는 같은 조합을 거듭 부른다.
"""
from __future__ import annotations

import hashlib
import random
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field

import numpy as np

from core.event_map.service import MapQueryError

# 이벤트 맵 갈래 중 압축 대상 10개(사용자 지정 2026-11-02 - 작품·고유명 · 미분류는 뺀다). 차례 = 화면 차례.
COMPRESS_GROUPS = ("clothing", "body", "cast", "expression", "action", "adult", "scene", "object", "situation", "meta")
CUT_KEYS = ("min_tags", "max_tags", "min_freq", "max_freq")
ROW_LIMIT = 500_000
GATHER_BATCH = 250_000
CACHE_ITEMS = 16
CACHE_BYTES = 512 << 20
TOP_LIMIT = 50

_cache: OrderedDict = OrderedDict()
_cache_bytes = 0
_lock = threading.Lock()
_salt: dict = {}


def normalize_compress(value) -> list[str]:
    """`compress` 값 -> 갈래 id 목록(화면 차례 · 중복 없음). 비면 [] - 압축 안 함. 쉼표 글도 받는다(GET 쿼리)."""
    if value in (None, "", []):
        return []
    if isinstance(value, str):
        value = [v for v in value.split(",") if v.strip()]
    if not isinstance(value, (list, tuple)) or len(value) > len(COMPRESS_GROUPS):
        raise MapQueryError("bad_request", "압축 갈래 목록을 확인해주세요.")
    wanted = {str(v).strip() for v in value}
    unknown = wanted - set(COMPRESS_GROUPS)
    if unknown:
        raise MapQueryError("bad_request", "압축할 수 없는 갈래입니다: %s" % ", ".join(sorted(unknown)))
    return [g for g in COMPRESS_GROUPS if g in wanted]


def normalize_cut(value) -> dict:
    """슬라이더 컷 -> {min_tags, max_tags, min_freq, max_freq} 중 정해진 것만(빈 dict = 끝까지).
    'a,b,c,d' 글(GET 쿼리 · 랜덤 연결 상태)도 받는다 - 빈 칸 = 끝까지."""
    if value in (None, "", {}, []):
        return {}
    if isinstance(value, str):
        parts = value.split(",")
        if len(parts) != len(CUT_KEYS):
            raise MapQueryError("bad_request", "압축 슬라이더 값을 확인해주세요.")
        value = dict(zip(CUT_KEYS, parts))
    if not isinstance(value, dict) or set(value) - set(CUT_KEYS):
        raise MapQueryError("bad_request", "압축 슬라이더 값을 확인해주세요.")
    out = {}
    for key in CUT_KEYS:
        raw = value.get(key)
        if raw in (None, ""):
            continue
        try:
            number = int(str(raw).strip())
        except ValueError as exc:
            raise MapQueryError("bad_request", "압축 슬라이더 값을 확인해주세요.") from exc
        if not 0 <= number <= 1_000_000_000:
            raise MapQueryError("bad_request", "압축 슬라이더 값을 확인해주세요.")
        out[key] = number
    for lo, hi in (("min_tags", "max_tags"), ("min_freq", "max_freq")):
        if lo in out and hi in out and out[lo] > out[hi]:
            raise MapQueryError("bad_request", "압축 슬라이더의 최소가 최대보다 큽니다.")
    return out


def cut_text(cut: dict) -> str:
    """normalize_cut 의 반대 - 'a,b,c,d'(빈 칸 = 끝까지). 비면 ''."""
    return ",".join("" if cut.get(k) is None else str(cut[k]) for k in CUT_KEYS) if cut else ""


def _tag_salt(idx) -> tuple[np.ndarray, np.ndarray]:
    """태그마다 · 분면마다 고정 64비트 값. 색인 하나에 한 번."""
    key = id(idx)
    hit = _salt.get(key)
    if hit is None or hit[0] is not idx:
        rng = np.random.default_rng(0x5EED_C0DE)
        hit = (idx, rng.integers(1, 2 ** 63, size=idx.n_tags, dtype=np.uint64),
               rng.integers(1, 2 ** 63, size=256, dtype=np.uint64))
        _salt.clear()
        _salt[key] = hit
    return hit[1], hit[2]


def normalize_output(value) -> str:
    """프롬프트 = 'full'(이벤트에 묶인 게시물 하나의 태그 전부 · 기본) | 'axes'(기준 축 태그만)."""
    if value in (None, "", "full"):
        return "full"
    if value == "axes":
        return "axes"
    raise MapQueryError("bad_request", "압축 출력은 full 또는 axes 입니다.")


def drop_mask(service, idx, groups: list[str], wanted: list[int]) -> np.ndarray:
    """이벤트를 가를 때 지울 태그(True) - 기준 축(10개 − groups) 밖의 태그 전부(작품·고유명 · 미분류 포함) + 색상.
    핀 · 인원 태그는 남긴다. 화면은 '기준 축' 을 고르고, 저장 값 `compress` 는 그 나머지(지운 축)다(사용자 지시 2026-11-02)."""
    axes = [g for g in COMPRESS_GROUPS if g not in groups]
    keep = service.group_mask(axes) if axes else np.zeros(idx.n_tags, dtype=bool)
    drop = idx.color_arr.copy() if keep is None else (~keep | idx.color_arr)   # 갈래 표가 없으면 옛 동작(색상만)
    drop &= ~idx.population_arr
    if wanted:
        drop[np.asarray(wanted, dtype=np.int64)] = False
    return drop


def _spans(idx, rids: np.ndarray):
    """rids 를 GATHER_BATCH 씩 - (구간 시작, 본문 자리, 구간 경계 누적) - 본문을 한 번에 다 펴지 않게."""
    starts_all = idx.offsets[rids].astype(np.int64)
    lengths_all = idx.offsets[rids + 1].astype(np.int64) - starts_all
    for at in range(0, rids.size, GATHER_BATCH):
        starts = starts_all[at:at + GATHER_BATCH]
        lengths = lengths_all[at:at + GATHER_BATCH]
        before = np.zeros(lengths.size + 1, dtype=np.int64)
        np.cumsum(lengths, out=before[1:])
        total = int(before[-1])
        picks = np.repeat(starts - before[:-1], lengths) + np.arange(total, dtype=np.int64)
        yield at, picks, before


def _build(idx, rids: np.ndarray, drop: np.ndarray):
    """rids -> (대표 게시물, 게시물 수, 이벤트 차례로 늘어놓은 게시물, 그 경계) - 큰 이벤트 먼저(같으면 rid 순)."""
    salt, part_salt = _tag_salt(idx)
    weights = np.where(drop, np.uint64(0), salt)
    keys = np.empty(rids.size, dtype=np.uint64)
    for at, picks, before in _spans(idx, rids):
        run = np.zeros(picks.size + 1, dtype=np.uint64)
        np.cumsum(weights[idx.body[picks]], out=run[1:])   # uint64 넘침은 2^64 를 법으로 돈다 - 차는 그대로 맞다
        part = run[before[1:]] - run[before[:-1]]
        n = before.size - 1
        keys[at:at + n] = part + part_salt[idx.part_arr[rids[at:at + n]]]
    _, first, inverse, counts = np.unique(keys, return_index=True, return_inverse=True, return_counts=True)
    order = np.lexsort((first, -counts))
    rank = np.empty(order.size, dtype=np.int64)
    rank[order] = np.arange(order.size)
    counts = counts[order].astype(np.int64)
    # 이벤트마다 묶인 게시물 - [프롬프트 전체] 는 그중 하나의 태그를 쓴다
    members = rids[np.argsort(rank[inverse.ravel()], kind="stable")].astype(np.int64)
    member_bounds = np.zeros(counts.size + 1, dtype=np.int64)
    np.cumsum(counts, out=member_bounds[1:])
    return rids[first[order]].astype(np.int64), counts, members, member_bounds


def _kept_tags(idx, reps: np.ndarray, drop: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """이벤트(대표 게시물)마다 남은 태그 - (경계 E+1, 태그 id 이어 붙임)."""
    kept = np.zeros(reps.size, dtype=np.int64)
    parts = []
    for at, picks, before in _spans(idx, reps):
        tids = idx.body[picks]
        keep = ~drop[tids]
        run = np.zeros(picks.size + 1, dtype=np.int64)
        np.cumsum(keep, out=run[1:])
        kept[at:at + before.size - 1] = run[before[1:]] - run[before[:-1]]
        parts.append(tids[keep].astype(np.int32))
    bounds = np.zeros(reps.size + 1, dtype=np.int64)
    np.cumsum(kept, out=bounds[1:])
    return bounds, (np.concatenate(parts) if parts else np.empty(0, dtype=np.int32))


@dataclass
class Table:
    """압축 표 - 이벤트(큰 것 먼저) · 이벤트별 남은 태그 · 태그 빈도(그 태그가 나오는 이벤트 수)."""
    reps: np.ndarray
    counts: np.ndarray
    members: np.ndarray        # 이벤트 차례로 늘어놓은 게시물(member_bounds 로 자른다)
    member_bounds: np.ndarray
    drop: np.ndarray
    bounds: np.ndarray
    tags: np.ndarray
    freq: np.ndarray
    rows: int        # 후보 게시물(표본 전)
    used: int        # 실제로 센 게시물(50만 상한)
    # 컷마다 태그 출현 수(pool_freq · 나중에 붙인다) - nbytes 에 넣지 않는다(캐시 회계는 넣을 때의 크기로 뺀다 · 하나 470KB · 4개까지)
    pool: dict = field(default_factory=dict)

    @property
    def nbytes(self) -> int:
        return sum(a.nbytes for a in (self.reps, self.counts, self.members, self.member_bounds, self.drop,
                                      self.bounds, self.tags, self.freq))


def _make_table(service, idx, rids: np.ndarray, groups, wanted, sample_key) -> Table:
    rows = int(rids.size)
    if rows > ROW_LIMIT:
        # 50만만 센다(사용자 지시 2026-11-02 - 나머지는 버림). 같은 조건이면 같은 표본(Quick Filter 와 같다).
        seed = int.from_bytes(hashlib.sha256(repr(sample_key).encode("utf-8")).digest()[:8], "big")
        rids = rids[np.sort(np.random.default_rng(seed).choice(rows, size=ROW_LIMIT, replace=False))]
    drop = drop_mask(service, idx, groups, wanted)
    if rids.size:
        reps, counts, members, member_bounds = _build(idx, rids, drop)
    else:
        reps = counts = members = np.empty(0, np.int64)
        member_bounds = np.zeros(1, np.int64)
    bounds, tags = _kept_tags(idx, reps, drop)
    freq = np.bincount(tags, minlength=idx.n_tags).astype(np.int64)
    return Table(reps, counts, members, member_bounds, drop, bounds, tags, freq, rows, int(rids.size))


def event_table(service, idx, rids_fn, *, cache_key, groups: list[str], wanted: list[int]) -> Table:
    """압축 표 - 같은 열쇠면 캐시(후보 게시물도 다시 안 센다). cache_key None = 캐시 안 함."""
    global _cache_bytes
    key = (id(idx), cache_key, tuple(groups))
    if cache_key is not None:
        with _lock:
            hit = _cache.get(key)
            if hit is not None and hit[0] is idx:
                _cache.move_to_end(key)
                return hit[1]
    table = _make_table(service, idx, rids_fn(), groups, wanted, (cache_key, tuple(groups)))
    if cache_key is not None and table.nbytes <= CACHE_BYTES:
        with _lock:
            if key not in _cache:
                _cache[key] = (idx, table)
                _cache_bytes += table.nbytes
            while _cache and (_cache_bytes > CACHE_BYTES or len(_cache) > CACHE_ITEMS):
                _, old = _cache.popitem(last=False)
                _cache_bytes -= old[1].nbytes
    return table


def clear_cache() -> None:
    global _cache_bytes
    with _lock:
        _cache.clear()
        _cache_bytes = 0


def counted_tags(idx, table: Table, wanted: list[int], cut: dict) -> np.ndarray | None:
    """태그 수에 세는 태그(True) - 빈도 범위 안 + 핀 · 인원 태그. 빈도 컷이 없으면 None(남은 태그 전부)."""
    if "min_freq" not in cut and "max_freq" not in cut:
        return None
    counted = table.freq > 0
    if "min_freq" in cut:
        counted &= table.freq >= cut["min_freq"]
    if "max_freq" in cut:
        counted &= table.freq <= cut["max_freq"]
    counted |= idx.population_arr
    if wanted:
        counted[np.asarray(wanted, dtype=np.int64)] = True
    return counted


def tag_counts(table: Table, counted: np.ndarray | None) -> np.ndarray:
    """이벤트마다 세는 태그 개수."""
    if counted is None:
        return np.diff(table.bounds)
    run = np.zeros(table.tags.size + 1, dtype=np.int64)
    np.cumsum(counted[table.tags], out=run[1:])
    return run[table.bounds[1:]] - run[table.bounds[:-1]]


def event_tags(idx, rid: int, drop: np.ndarray, wanted: list[int]) -> list[int]:
    """이벤트 대표 게시물의 남은 태그 id - 인원 -> 핀 -> 나머지(`EventMapIndex.sample` 과 같은 차례)."""
    return _ordered(idx, [t for t in idx.body[idx.offsets[rid]:idx.offsets[rid + 1]].tolist() if not drop[t]], wanted)


def post_tags(idx, rid: int, wanted: list[int]) -> list[int]:
    """게시물 하나의 태그 전부 - 색상만 뺀다(핀이면 남김) · `EventMapIndex.sample` 과 같은 규칙 · 같은 차례."""
    pinned = set(wanted)
    return _ordered(idx, [t for t in idx.body[idx.offsets[rid]:idx.offsets[rid + 1]].tolist()
                          if t in pinned or not idx.color_arr[t]], wanted)


def include_mask(idx, filters) -> np.ndarray | None:
    """찾기 조건의 '포함' 낱말에 맞는 태그 - 압축한 이벤트 안 찾기의 포함 칩은 [선택한 축만] 출력에도 핀처럼 남긴다
    (사용자 결정 2026-11-02). 뒤집은 묶음 · '-' 낱말은 뺀다 · 맞추는 법은 `EventMapIndex.filter_posts` 와 같다
    (부분 일치 · `*` = 정확히). 출력에만 쓴다 - 이벤트 묶음(drop_mask)은 그대로. 포함 낱말이 없으면 None."""
    mask = None
    for group in filters or []:
        if group.get("invert", False):
            continue
        for token in group.get("terms") or []:
            if token.startswith("-"):
                continue
            exact = token.startswith("*")
            clean = token[1:] if exact else token
            if mask is None:
                mask = np.zeros(idx.n_tags, dtype=bool)
            hit = idx._filter_masks.get((clean, exact))
            if hit is not None:
                mask |= hit
            elif exact:
                tid = idx.resolve(clean)
                if tid is not None:
                    mask[tid] = True
            else:
                if idx._filter_names is None:
                    idx._filter_names = [idx.by_id[t].lower() for t in range(idx.n_tags)]
                mask |= np.fromiter((clean in name for name in idx._filter_names), dtype=bool, count=idx.n_tags)
    return mask


def _ordered(idx, tids: list[int], wanted: list[int]) -> list[int]:
    population = [t for t in tids if idx.population_arr[t]]
    head = population + [t for t in wanted if t in tids and t not in population]
    seen = set(head)
    return head + [t for t in tids if t not in seen]


def candidate_rids(idx, wanted, excluded, ratings, persons, block, filters) -> np.ndarray:
    """`EventMapIndex.sample` 과 같은 후보 풀(핀 ∩ 분면 − 제외 − 영구 제외 → 찾기 조건)."""
    parts = idx._partition_filter(ratings, persons)
    pool = idx._matching_posts(wanted, parts) if wanted else idx._live_posts(parts)
    return idx.filter_posts(idx._unblocked(idx._without(pool, excluded), block), filters)


def _table_for(service, idx, wanted, excluded, ratings, persons, block, filters, groups) -> Table:
    """조건의 압축 표 - compressed() · pool_freq() 가 같은 열쇠로 같은 캐시를 쓴다."""
    cache_key = (tuple(sorted(set(wanted))), tuple(sorted(set(excluded))), tuple(sorted(ratings or [])),
                 tuple(sorted(persons or [])), getattr(block, "text", None) if block is not None else None,
                 repr(filters or []))
    if block is not None and not isinstance(getattr(block, "text", None), str):
        cache_key = None   # 글로 가릴 수 없는 막을 것 - 캐시하지 않는다
    return event_table(service, idx, lambda: candidate_rids(idx, wanted, excluded, ratings, persons, block, filters),
                       cache_key=cache_key, groups=groups, wanted=wanted)


def pool_freq(service, idx, *, pins, exclude, ratings, persons, block, filters, groups, cut=None) -> np.ndarray | None:
    """압축한 조합의 게시물(태그 수 슬라이더 안 이벤트에 묶인 것 · 50만 상한 표본)에 태그마다 몇 번 나오나.
    막의 '이벤트 안에서 찾기' 자동완성이 이 조합에 없는 태그를 거르고 이 안의 게시물 수를 보인다(사용자 결정 2026-11-02).
    기준 축 밖 태그도 센다(표의 freq 는 남은 태그만). 실측 2만 12ms · 7.6만 43ms · 50만 257ms - 표에 붙여 둔다."""
    cut = normalize_cut(cut)
    wanted, unknown = idx._resolve_many(pins)
    if unknown:
        return None
    excluded, _ = idx._resolve_many(exclude)
    excluded = [t for t in excluded if t not in wanted]
    table = _table_for(service, idx, wanted, excluded, ratings, persons, block, filters, groups)
    key = repr(sorted(cut.items()))
    hit = table.pool.get(key)
    if hit is not None:
        return hit
    rids = table.members
    if "min_tags" in cut or "max_tags" in cut:   # 빈도 컷은 이벤트를 빼지 않는다(태그 수만 바꾼다)
        sizes = tag_counts(table, counted_tags(idx, table, wanted, cut))
        inside = np.ones(sizes.size, dtype=bool)
        if "min_tags" in cut:
            inside &= sizes >= cut["min_tags"]
        if "max_tags" in cut:
            inside &= sizes <= cut["max_tags"]
        rids = table.members[np.repeat(inside, table.counts)]
    freq = np.zeros(idx.n_tags, dtype=np.int64)
    for _at, picks, _before in _spans(idx, np.sort(rids)):
        freq += np.bincount(idx.body[picks], minlength=idx.n_tags)
    if len(table.pool) >= 4:
        table.pool.clear()
    table.pool[key] = freq
    return freq


def _hist(values: np.ndarray) -> dict:
    keys, counts = np.unique(values, return_counts=True)
    return {str(int(k)): int(c) for k, c in zip(keys, counts)}


def compressed(service, idx, *, pins, exclude, ratings, persons, block, filters, groups,
               cut=None, output=None, n=0, top=0, seed=None, hist=False) -> dict:
    """압축된 조합 - 뽑기(n) · 큰 이벤트 목록(top) · 슬라이더 분포(hist).
    `EventMapIndex.sample` 과 같은 모양 + events(전체) · events_in(슬라이더 안) · sampled(50만 상한).
    뽑기 = 이벤트를 같은 확률로 고른 뒤 output='full' 이면 그 이벤트에 묶인 게시물 하나의 태그 전부,
    'axes' 면 기준 축 태그만(사용자 지시 2026-11-02 - [프롬프트 전체] [선택한 축만]).
    `uncounted` = 태그 수에 안 세는 태그(기준 축 밖 + 빈도 범위 밖) - 화면은 회색."""
    started = time.perf_counter()
    cut = normalize_cut(cut)
    output = normalize_output(output)
    wanted, unknown = idx._resolve_many(pins)
    excluded, unknown_ex = idx._resolve_many(exclude)
    excluded = [t for t in excluded if t not in wanted]
    out = {"pins": [idx.by_id[t] for t in wanted], "unknown_pins": unknown,
           "exclude": [idx.by_id[t] for t in excluded], "unknown_exclude": unknown_ex,
           "ratings": sorted(ratings or []), "persons": sorted(persons or []), "compress": list(groups),
           "compress_cut": cut, "compress_output": output, "observed_posts": 0, "events": 0, "events_in": 0, "sampled": None,
           "samples": [], "top": [], "kind": "compressed_event"}
    if unknown:
        out["status"] = "unknown_tag"
        return out
    table = _table_for(service, idx, wanted, excluded, ratings, persons, block, filters, groups)
    counted = counted_tags(idx, table, wanted, cut)
    sizes = tag_counts(table, counted)
    inside = np.ones(sizes.size, dtype=bool)
    if "min_tags" in cut:
        inside &= sizes >= cut["min_tags"]
    if "max_tags" in cut:
        inside &= sizes <= cut["max_tags"]
    eligible = np.flatnonzero(inside)    # 큰 이벤트 먼저(표 차례)
    out["observed_posts"] = table.rows
    if table.used < table.rows:
        out["sampled"] = {"rows": table.rows, "used": table.used}
    out["events"] = int(table.reps.size)
    out["events_in"] = int(eligible.size)
    if hist:
        always = idx.population_arr.copy()
        if wanted:
            always[np.asarray(wanted, dtype=np.int64)] = True
        out["hist"] = _hist(sizes)   # {세는 태그 수: 이벤트 수} - 빈도 컷은 걸고 태그 수 컷은 안 건 전체
        out["freq_hist"] = _hist(table.freq[(table.freq > 0) & ~always])   # {빈도: 그 빈도의 태그 수} - 늘 세는 태그 빼고

    keep = include_mask(idx, filters) if output == "axes" else None
    shown = table.drop if keep is None else (table.drop & ~keep)   # 포함 칩에 맞는 태그는 축 밖이어도 남긴다(회색)

    def row(i, rid=None):
        tids = event_tags(idx, int(table.reps[i]), shown, wanted) if rid is None else post_tags(idx, rid, wanted)
        item = {"tags": [idx.by_id[t] for t in tids], "posts": int(table.counts[i])}
        item["uncounted"] = [idx.by_id[t] for t in tids if table.drop[t] or (counted is not None and not counted[t])]
        return item

    rng = random.Random(seed)
    for j in rng.sample(range(int(eligible.size)), min(int(n), int(eligible.size))):
        i = int(eligible[j])
        if output == "full":
            lo, hi = int(table.member_bounds[i]), int(table.member_bounds[i + 1])
            rid = int(table.members[rng.randrange(lo, hi)])
            item = row(i, rid)
        else:
            rid = int(table.reps[i])
            item = row(i)
        item["event_posts"] = item.pop("posts")
        item["prompt"] = ", ".join(item["tags"])
        item["partition"] = idx.partitions[idx.part_arr[rid]] if rid < idx.part_arr.size else None
        out["samples"].append(item)
    for i in eligible[:min(int(top), TOP_LIMIT)].tolist():
        out["top"].append(row(i))
    out["status"] = "matched" if eligible.size else "no_match"
    out["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return out
