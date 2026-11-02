"""이벤트 맵 압축(사용자 지시 2026-11-02) - 조합에 붙는 상태 `selection.compress = [갈래 id …]`.

고른 갈래의 태그를 지우고, 남은 태그(+ 등급)가 같은 게시물끼리 **이벤트** 하나로 묶는다.
압축된 조합의 랜덤은 게시물이 아니라 이벤트를 **같은 확률로** 뽑는다(사용자 결정 2026-11-02) - 흔한 장면이 랜덤을 덮지 않게.
프롬프트 = 그 이벤트의 남은 태그. 핀 · 인원 태그는 지우는 갈래에 있어도 남는다(사용자 결정 2026-11-02).
색상은 맵 정책대로 늘 빠진다(핀이면 남는다) - `EventMapIndex.sample` 과 같다.

Search 의 이벤트 압축(`core/event_compress.py`)과 뜻은 같지만 출처가 다르다: 저쪽은 Search 풀 + PE '특징 제거',
여기는 이벤트 맵 색인 + 이벤트 맵 갈래(`kr_category_fold.json`).

계산: 게시물마다 남은 태그의 64비트 무작위 값을 더한 합(+ 등급 값)을 열쇠로 삼는다 - 게시물 안 태그는 겹치지 않으므로
합이 곧 집합의 지문이다(충돌 확률 ~ 이벤트 수² / 2^64). 파이썬 반복문 없이 본문을 한 번 긁는다(`_count_tags` 와 같은 수).
같은 조건이면 표를 캐시에서 쓴다 - 랜덤 단추는 같은 조합을 거듭 부른다.
"""
from __future__ import annotations

import random
import threading
import time
from collections import OrderedDict

import numpy as np

from core.event_map.service import MapQueryError

# 이벤트 맵 갈래 중 압축 대상 10개(사용자 지정 2026-11-02 - 작품·고유명 · 미분류는 뺀다). 차례 = 화면 차례.
COMPRESS_GROUPS = ("clothing", "body", "cast", "expression", "action", "adult", "scene", "object", "situation", "meta")
GATHER_BATCH = 250_000
CACHE_ITEMS = 16
CACHE_BYTES = 256 << 20
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


def drop_mask(service, idx, groups: list[str], wanted: list[int]) -> np.ndarray:
    """지울 태그(True) - 고른 갈래 + 색상. 핀 · 인원 태그는 남긴다."""
    drop = idx.color_arr.copy()
    mask = service.group_mask(groups)
    if mask is not None:
        drop |= mask
    drop &= ~idx.population_arr
    if wanted:
        drop[np.asarray(wanted, dtype=np.int64)] = False
    return drop


def _build(idx, rids: np.ndarray, drop: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """rids -> (대표 게시물, 게시물 수) - 큰 이벤트 먼저(같으면 rid 순)."""
    salt, part_salt = _tag_salt(idx)
    weights = np.where(drop, np.uint64(0), salt)
    keys = np.empty(rids.size, dtype=np.uint64)
    starts_all = idx.offsets[rids].astype(np.int64)
    lengths_all = idx.offsets[rids + 1].astype(np.int64) - starts_all
    for at in range(0, rids.size, GATHER_BATCH):
        starts = starts_all[at:at + GATHER_BATCH]
        lengths = lengths_all[at:at + GATHER_BATCH]
        total = int(lengths.sum())
        before = np.zeros(lengths.size + 1, dtype=np.int64)
        np.cumsum(lengths, out=before[1:])
        if total:
            picks = np.repeat(starts - before[:-1], lengths) + np.arange(total, dtype=np.int64)
            run = np.zeros(total + 1, dtype=np.uint64)
            np.cumsum(weights[idx.body[picks]], out=run[1:])   # uint64 넘침은 2^64 를 법으로 돈다 - 차는 그대로 맞다
            part = run[before[1:]] - run[before[:-1]]
        else:
            part = np.zeros(lengths.size, dtype=np.uint64)
        keys[at:at + lengths.size] = part + part_salt[idx.part_arr[rids[at:at + GATHER_BATCH]]]
    _, first, counts = np.unique(keys, return_index=True, return_counts=True)
    order = np.lexsort((first, -counts))
    return rids[first[order]].astype(np.int64), counts[order].astype(np.int64)


def event_table(service, idx, rids: np.ndarray, *, cache_key, groups: list[str], wanted: list[int]):
    """(대표 rid, 게시물 수, 지울 태그) - 같은 열쇠면 캐시."""
    global _cache_bytes
    key = (id(idx), cache_key, tuple(groups))
    with _lock:
        hit = _cache.get(key)
        if hit is not None and hit[0] is idx:
            _cache.move_to_end(key)
            return hit[1], hit[2], hit[3]
    drop = drop_mask(service, idx, groups, wanted)
    reps, counts = _build(idx, rids, drop) if rids.size else (np.empty(0, np.int64), np.empty(0, np.int64))
    size = reps.nbytes + counts.nbytes + drop.nbytes
    if size <= CACHE_BYTES:
        with _lock:
            if key not in _cache:
                _cache[key] = (idx, reps, counts, drop)
                _cache_bytes += size
            while _cache and (_cache_bytes > CACHE_BYTES or len(_cache) > CACHE_ITEMS):
                _, old = _cache.popitem(last=False)
                _cache_bytes -= old[1].nbytes + old[2].nbytes + old[3].nbytes
    return reps, counts, drop


def clear_cache() -> None:
    global _cache_bytes
    with _lock:
        _cache.clear()
        _cache_bytes = 0


def event_tags(idx, rid: int, drop: np.ndarray, wanted: list[int]) -> list[str]:
    """이벤트 대표 게시물의 남은 태그 - 인원 -> 핀 -> 나머지(`EventMapIndex.sample` 과 같은 차례)."""
    tids = [t for t in idx.body[idx.offsets[rid]:idx.offsets[rid + 1]].tolist() if not drop[t]]
    population = [t for t in tids if idx.population_arr[t]]
    head = population + [t for t in wanted if t in tids and t not in population]
    seen = set(head)
    return [idx.by_id[t] for t in head + [t for t in tids if t not in seen]]


def candidate_rids(idx, wanted, excluded, ratings, persons, block, filters) -> np.ndarray:
    """`EventMapIndex.sample` 과 같은 후보 풀(핀 ∩ 분면 − 제외 − 영구 제외 → 찾기 조건)."""
    parts = idx._partition_filter(ratings, persons)
    pool = idx._matching_posts(wanted, parts) if wanted else idx._live_posts(parts)
    return idx.filter_posts(idx._unblocked(idx._without(pool, excluded), block), filters)


def compressed(service, idx, *, pins, exclude, ratings, persons, block, filters, groups,
               n=0, top=0, seed=None) -> dict:
    """압축된 조합 - 뽑기(n) 와 큰 이벤트 목록(top). `EventMapIndex.sample` 과 같은 모양 + events · compress."""
    started = time.perf_counter()
    wanted, unknown = idx._resolve_many(pins)
    excluded, unknown_ex = idx._resolve_many(exclude)
    excluded = [t for t in excluded if t not in wanted]
    out = {"pins": [idx.by_id[t] for t in wanted], "unknown_pins": unknown,
           "exclude": [idx.by_id[t] for t in excluded], "unknown_exclude": unknown_ex,
           "ratings": sorted(ratings or []), "persons": sorted(persons or []), "compress": list(groups),
           "observed_posts": 0, "events": 0, "samples": [], "top": [], "kind": "compressed_event"}
    if unknown:
        out["status"] = "unknown_tag"
        return out
    rids = candidate_rids(idx, wanted, excluded, ratings, persons, block, filters)
    cache_key = (tuple(sorted(set(wanted))), tuple(sorted(set(excluded))), tuple(sorted(ratings or [])),
                 tuple(sorted(persons or [])), getattr(block, "text", None) if block is not None else None,
                 repr(filters or []))
    if block is not None and not isinstance(getattr(block, "text", None), str):
        cache_key = None   # 글로 가릴 수 없는 막을 것 - 캐시하지 않는다
    if cache_key is None:
        drop = drop_mask(service, idx, groups, wanted)
        reps, counts = _build(idx, rids, drop) if rids.size else (np.empty(0, np.int64), np.empty(0, np.int64))
    else:
        reps, counts, drop = event_table(service, idx, rids, cache_key=cache_key, groups=groups, wanted=wanted)
    out["observed_posts"] = int(rids.size)
    out["events"] = int(reps.size)
    rng = random.Random(seed)
    for i in rng.sample(range(int(reps.size)), min(int(n), int(reps.size))):
        rid = int(reps[i])
        tags = event_tags(idx, rid, drop, wanted)
        out["samples"].append({"tags": tags, "prompt": ", ".join(tags), "event_posts": int(counts[i]),
                               "partition": idx.partitions[idx.part_arr[rid]] if rid < idx.part_arr.size else None})
    for i in range(min(int(top), int(reps.size), TOP_LIMIT)):
        out["top"].append({"tags": event_tags(idx, int(reps[i]), drop, wanted), "posts": int(counts[i])})
    out["status"] = "matched" if reps.size else "no_match"
    out["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return out
