"""Read-only reader for the event map index.

Contract, inherited from the observed corpus and kept deliberately narrow:

* A count is the number of **distinct posts carrying every pinned tag at once**.
  It is never a union of pairwise edges, and never a confidence score.
* A tag missing from a result does not prove it cannot happen -- only that it
  was not observed often enough under these pins.
* Nothing here infers who acts on whom, or any negation.

Ranking is `lift = P(tag | pins) / P(tag)`, not raw frequency. Frequency alone
returns `1girl`, `solo` and `looking at viewer` for every pin in the corpus
(measured 2026-09-11); lift is what makes the map navigable.
"""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import mmap
import random
import sqlite3
import time
import zlib

import numpy as np

from .pack import PackReader, is_pack
from .policy import POLICY_VERSION, color_exclusion_reason, normalize

SCHEMA = "naia-event-map-v1"
MAX_PINS = 16
MAX_EXCLUDE = 32
MAX_SAMPLES = 50
NOTE = ("관측 수는 같은 게시물에 함께 달린 횟수다. 의도의 정확도도, 행위의 주체/대상도,"
        " 없는 태그가 '일어나지 않는다' 는 뜻도 아니다.")

# 후보 순위를 낼 때 실제로 펴 보는 게시물 수의 상한.
#
# ⚠️ 이게 없으면 `1girl`(610만건)을 핀으로 꽂는 순간 서버가 **13초** 멈춘다(실측
#    2026-09-11. 대부분이 SQLite 가 610만 행을 꺼내는 9초다 - 세는 값이 아니다).
#    상한을 넘으면 교집합 전체에서 **고르게 건너뛰며** 표본을 뜬다.
#
# **교집합 건수(`observed_posts`)는 표본과 무관하게 언제나 정확하다** - 그건 게시물을
# 펴지 않고 목록 교집합만으로 나오기 때문이다. 표본이 흔드는 것은 후보 순위뿐이고,
# 그럴 때는 `sampled` 로 밝힌다.
#
# ⚠️ 이 상한을 **더 내리지 마라.** 표본은 교집합이 작을수록 빨리 깨진다(실측 2026-09-11:
#    1/8 표본이 핀 1개에서는 상위 8개 중 7개를 지켰지만 핀 3개에서는 1개만 남았다).
#    상한은 교집합이 **클 때만** 걸리므로 안전하다 - 작은 교집합은 애초에 상한 밑이다.
SCAN_CAP = 120_000

# 순위를 낼 때 기댓값에 얹는 **사전 무게**.
#
# ⚠️ 날 lift(P(t|핀)/P(t))로 줄을 세우면 **전역에서 희귀한 태그가 몇 건으로 1등을 한다.**
#    실측 2026-09-11: `armpits + armpit crease`(2,583건)의 1위가 `heart ring bottom`
#    이었다 - 겨우 **8건**이다. 그 8건이 통계적으로 우연은 아니지만, 전체에 100건뿐인
#    태그는 사용자가 **타고 갈 만한 자리가 아니다**.
#
#    그래서 lift 대신 `관측 / (기댓값 + PRIOR)` 로 세운다. 기댓값이 1보다 한참 작은
#    희귀 태그는 분모가 사실상 PRIOR 로 고정돼 몇 건으로는 못 올라오고, 기댓값이 큰
#    태그는 PRIOR 가 묻혀 원래 lift 그대로다.
#    ⚠️ 화면에 보여 주는 `lift` 는 **날 lift 그대로**다 - 그게 사용자가 읽는 값이고,
#       줄 세우기에만 눌린 점수를 쓴다. 둘을 같은 이름으로 합치지 말 것.
RANK_PRIOR = 3.0


BODY_MAGIC = b"NAIAMAPR"
BODY_HEADER = 24         # magic 8 + 게시물 수 8 + 오프셋 표 위치 8
GATHER_BATCH = 250_000   # 한 번에 긁는 게시물 수. 색인 배열이 메모리를 먹지 않게 끊는다.


def decode_postings(buf: bytes) -> np.ndarray:
    """`개수 + 차분 varint` 를 오름차순 절대값 배열로 편다. **postings 전용**이다.

    바이트를 배열로 눕혀서 한 번에 푼다 - 파이썬으로 한 바이트씩 돌면 `1girl`
    (610만건) 하나에 1.4초가 든다(실측 2026-09-11). 게시물 본문은 아예 varint 가
    아니라 날 uint16 이므로 이 경로를 안 탄다.

    풀이: varint 는 **마지막 바이트만 최상위 비트가 0** 이다. 그 자리를 끝으로 보고
    묶음마다 `(byte & 0x7F) << (7 * 묶음_내_위치)` 를 더하면 값이 나온다.
    """
    if not buf:
        return np.empty(0, dtype=np.int64)
    raw = np.frombuffer(buf, dtype=np.uint8)
    ends = np.flatnonzero(raw < 0x80)
    if ends.size == 0:
        raise ValueError("postings 바이트가 varint 로 끝나지 않는다")
    starts = np.empty(ends.size, dtype=np.int64)
    starts[0] = 0
    starts[1:] = ends[:-1] + 1
    within = np.arange(raw.size, dtype=np.int64) - np.repeat(starts, ends - starts + 1)
    contrib = (raw & 0x7F).astype(np.int64) << (7 * within)
    values = np.add.reduceat(contrib, starts)
    # 첫 값은 개수, 나머지가 차분이다. 차분은 '앞 값 다음부터 몇 칸' 이라 +1 한다.
    count = int(values[0])
    deltas = values[1:1 + count]
    if deltas.size != count:
        raise ValueError("postings 개수와 실제 값이 안 맞는다")
    return np.cumsum(deltas + 1) - 1


def _decode_deltas(buf: bytes, pos: int = 0) -> tuple[list[int], int]:
    """느린 참조 구현. `decode_postings` 가 맞는지 시험에서 맞대는 용도로만 둔다."""
    count = 0
    shift = 0
    while True:
        byte = buf[pos]
        pos += 1
        count |= (byte & 0x7F) << shift
        if byte < 0x80:
            break
        shift += 7
    out = []
    prev = -1
    for _ in range(count):
        value = 0
        shift = 0
        while True:
            byte = buf[pos]
            pos += 1
            value |= (byte & 0x7F) << shift
            if byte < 0x80:
                break
            shift += 7
        prev += value + 1
        out.append(prev)
    return out, pos


class EventMapIndex:
    """Opens the index read-only. One instance is shared per process.

    두 형식을 연다:
      - `.naiamap` 한 파일 (core/event_map/pack.py) - 지금 빌더가 만드는 것
      - 예전 두 파일 `event_map.sqlite3` + `event_map.records.bin` - 옮겨 가는 동안만
    어느 쪽이든 아래 속성은 같다: by_id/by_name/observed/role/lane · offsets/body(numpy 뷰)
    · part_arr(게시물 -> 분면) · posting(tid).
    """

    def __init__(self, path: str | Path):
        path = Path(path).resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        self.path = path
        self.body_path = path
        self.db = None
        self._pack = None
        self._body_file = self._body_map = None
        if is_pack(path):
            self._load_pack(path)
        else:
            self._load_legacy(path)
        self.partitions: list[str] = list(self.meta.get("partitions") or [])
        self.total_posts: int = int(self.meta.get("records") or 0)
        # 오프셋은 **rid 로 색인**된다. rid 가 1부터라 표는 게시물 수보다 길다.
        if self.offsets.size <= self.total_posts:
            n = self.offsets.size
            self.close()
            raise ValueError("오프셋 표가 게시물 수보다 짧다 (%d <= %d)" % (n, self.total_posts))

    # -- 여는 법 두 가지 ---------------------------------------------------------
    def _load_pack(self, path: Path) -> None:
        pk = PackReader(path)
        self._pack = pk
        self.meta = pk.json_of("meta")
        if self.meta.get("schema") != SCHEMA or self.meta.get("state") != "ready":
            self.close()
            raise ValueError("이벤트 맵 색인이 호환되지 않거나 미완성이다")
        self._set_tags(pk.json_of("tags"))
        start, length = pk.span("post_index")
        self._post_index = np.frombuffer(pk.map, dtype="<u8", count=length // 8, offset=start)
        self._post_base = pk.span("postings")[0]
        start, length = pk.span("partitions")
        self.part_arr = np.frombuffer(pk.map, dtype=np.uint8, count=length, offset=start)
        start, length = pk.span("offsets")
        self.offsets = np.frombuffer(pk.map, dtype="<u4", count=length // 4, offset=start)
        start, length = pk.span("body")
        dtype = self._record_dtype()
        self.body = np.frombuffer(pk.map, dtype=dtype,
                                  count=length // self.record_width, offset=start)

    def _load_legacy(self, path: Path) -> None:
        self.db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, check_same_thread=False)
        self.meta = {k: json.loads(v) for k, v in self.db.execute("SELECT key,value FROM meta")}
        if self.meta.get("schema") != SCHEMA or self.meta.get("state") != "ready":
            self.close()
            raise ValueError("이벤트 맵 색인이 호환되지 않거나 미완성이다")
        rows = []
        for tid, name, observed, role, details in self.db.execute(
                "SELECT id,name,observed,role,details FROM tags ORDER BY id"):
            info = json.loads(details)
            # 빌더가 붙인 갈래(general/adult). 성인 갈래는 원본 preset_eligible 이 False 라
            # 그것만 보면 전부 떨어진다 - E/Q 배선이 빠졌던 바로 그 자리다.
            lane = info.get("map_lane") or ("general" if info.get("preset_eligible") else None)
            if tid != len(rows):
                self.close()
                raise ValueError("태그 id 가 0부터 빈틈없이 이어지지 않는다")
            rows.append([name, observed, role or info.get("role") or "unreviewed", lane])
        self._set_tags(rows)
        row = self.db.execute("SELECT data FROM post_partitions").fetchone()
        self.part_arr = np.frombuffer(zlib.decompress(row[0]) if row else b"", dtype=np.uint8)
        # 게시물 본문은 sqlite 옆의 평면 파일이다.
        name = self.meta.get("record_body") or (path.stem + ".records.bin")
        body_path = path.with_name(str(name))
        if not body_path.is_file():
            self.close()
            raise FileNotFoundError("게시물 본문 파일이 없다: %s" % body_path)
        self.body_path = body_path
        self._body_file = open(body_path, "rb")
        self._body_map = mmap.mmap(self._body_file.fileno(), 0, access=mmap.ACCESS_READ)
        if self._body_map[:8] != BODY_MAGIC:
            self.close()
            raise ValueError("게시물 본문 파일 형식이 다르다: %s" % body_path)
        n_offsets = int.from_bytes(self._body_map[8:16], "little")
        off_at = int.from_bytes(self._body_map[16:24], "little")
        self.offsets = np.frombuffer(self._body_map, dtype="<u4", count=n_offsets, offset=off_at)
        dtype = self._record_dtype()
        self.body = np.frombuffer(self._body_map, dtype=dtype,
                                  count=(off_at - BODY_HEADER) // self.record_width,
                                  offset=BODY_HEADER)

    def _record_dtype(self) -> str:
        """본문 한 칸의 폭. 정렬된 날 정수다.

        어휘가 65,535개를 넘으면 빌더가 uint32 로 쓰고 meta["record_width"] 에 적는다
        (Full 코퍼스로 지은 판이 어휘 10만이라 그렇다). 옛 색인에는 안 적혀 있어 2로 본다.
        ⚠️ 폭을 상수로 박지 마라. uint32 본문을 uint16 으로 읽으면 길이가 두 배인 쓰레기가
           나오는데 **빌더의 자가 검증은 통과한다** - 엔트리 수는 맞으니까.
        """
        width = int(self.meta.get("record_width") or 2)
        if width not in (2, 4):
            raise ValueError("모르는 본문 폭이다: %r" % width)
        self.record_width = width
        return "<u2" if width == 2 else "<u4"

    def _set_tags(self, rows) -> None:
        """[[이름, 관측 수, 갈래, lane], ...] (id = 순서) 로 태그표를 세운다."""
        self.by_id = {}
        self.by_name = {}
        self.observed = {}
        self.role = {}
        self.eligible = {}
        self.lane = {}
        self.color = {}
        # 색상은 **정책과 무관하게 항상** 후보에서 뺀다(사용자 지정 2026-09-12). 색상은 이벤트로
        # 이어지지 않는다는 것이 정책이 아니라 맵의 전제라서다. meta 의 color_policy 는 기록으로만
        # 남고 여기서는 읽지 않는다 - `--policy none` 판(full-20260912)에서 `black bikini`·
        # `yellow shirt` 가 후보로 올라오던 것이 그 값을 읽던 흔적이다.
        self.policy_mode = self.meta.get("policy_mode", "full")
        color_on = True
        for tid, (name, observed, role, lane) in enumerate(rows):
            self.by_id[tid] = name
            self.by_name[name] = tid
            self.observed[tid] = int(observed)
            self.role[tid] = role or "unreviewed"
            self.lane[tid] = lane
            self.eligible[tid] = lane is not None
            self.color[tid] = color_on and color_exclusion_reason(name) is not None
        # 점수 계산은 태그 수만큼 한 번에 돈다 - 파이썬 반복문 대신 배열로 든다.
        size = len(rows)
        self.n_tags = size
        self.obs_arr = np.array([self.observed[t] for t in range(size)], dtype=np.int64)
        self.usable_arr = np.array([self.eligible[t] for t in range(size)], dtype=bool)
        self.color_arr = np.array([self.color[t] for t in range(size)], dtype=bool)

    def tag_rows(self) -> list:
        """태그표를 `.naiamap` 의 tags 구역 모양으로 돌려준다(변환 도구가 쓴다)."""
        return [[self.by_id[t], self.observed[t], self.role[t], self.lane[t]]
                for t in range(self.n_tags)]

    def posting_blob(self, tid: int) -> bytes:
        """태그의 게시물 목록을 **압축된 채로** 준다(`zlib(개수 + 차분 varint)`)."""
        if self._pack is not None:
            a, b = int(self._post_index[tid]), int(self._post_index[tid + 1])
            return bytes(self._pack.map[self._post_base + a:self._post_base + b])
        row = self.db.execute("SELECT data FROM postings WHERE tag=?", (tid,)).fetchone()
        return row[0] if row else b""

    def close(self) -> None:
        self.posting.cache_clear()
        # numpy 뷰가 mmap 을 붙들고 있으면 닫히지 않는다 - 먼저 놓는다.
        self.offsets = self.body = self.part_arr = self._post_index = None
        if self._pack is not None:
            self._pack.close()
            self._pack = None
        if self._body_map is not None:
            self._body_map.close()
            self._body_map = None
        if self._body_file is not None:
            self._body_file.close()
            self._body_file = None
        if self.db is not None:
            self.db.close()
            self.db = None

    # -- 태그 ---------------------------------------------------------------
    def resolve(self, tag: str) -> int | None:
        # ⚠️ 원래 이름을 먼저 찾는다. 색인 이름은 원본 규칙대로 **이모티콘의 밑줄을
        #    남겨 뒀다**(`>_<`·`^_^`·`o_o` 등 16개). 곧장 normalize 하면 `> <` 가 돼서
        #    핀으로 꽂을 수도, 뽑은 조합에서 되찾을 수도 없었다(실측 2026-09-11).
        # ⚠️ `a or b or c` 로 쓰지 마라 - id 0 은 가장 흔한 태그(`1girl`)라 거짓으로 읽힌다.
        text = str(tag or "").strip()
        for key in (text, text.lower(), normalize(text)):
            tid = self.by_name.get(key)
            if tid is not None:
                return tid
        return None

    def describe(self, tag: str) -> dict | None:
        tid = self.resolve(tag)
        if tid is None:
            return None
        return {"tag": self.by_id[tid], "observed": self.observed[tid],
                "role": self.role[tid], "lane": self.lane.get(tid),
                "color_only": self.color[tid],
                "map_eligible": self.eligible[tid] and not self.color[tid]}

    @lru_cache(maxsize=512)
    def posting(self, tid: int) -> np.ndarray:
        """태그의 게시물 목록(오름차순). 태그마다 한 번만 풀고 캐시에 남는다."""
        blob = self.posting_blob(tid)
        if not blob:
            return np.empty(0, dtype=np.int64)
        return decode_postings(zlib.decompress(blob))

    def _partition_of(self, rids: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """게시물 -> 분면. 파이썬 반복문으로 돌면 610만 번이라 배열로 민다."""
        keep = rids[rids < self.part_arr.size]
        return keep, self.part_arr[keep]

    # -- 탐색 ---------------------------------------------------------------
    def _matching_posts(self, tids: list[int], parts: set[int] | None) -> np.ndarray:
        lists = sorted((self.posting(t) for t in tids), key=len)
        if not lists or lists[0].size == 0:
            return np.empty(0, dtype=np.int64)
        acc = lists[0]
        for arr in lists[1:]:
            # 양쪽 다 오름차순 · 중복 없음이라 assume_unique 를 켤 수 있다.
            acc = np.intersect1d(acc, arr, assume_unique=True)
            if acc.size == 0:
                return acc
        if parts is not None:
            acc, owner = self._partition_of(acc)
            acc = acc[np.isin(owner, np.fromiter(parts, dtype=np.uint8, count=len(parts)))]
        return acc

    def _count_tags(self, rids: np.ndarray) -> np.ndarray:
        """주어진 게시물들에 달린 태그를 센다. 평면 본문에서 한 번에 긁는다.

        게시물마다 길이가 달라도 색인 배열 하나로 모아 뜰 수 있다:
        각 게시물의 시작 위치를 길이만큼 늘어놓고, 거기에 '누적 길이를 뺀 일련번호'를
        더하면 원하는 자리들이 그대로 나온다. 파이썬 반복문이 하나도 없다.
        """
        counts = np.zeros(self.n_tags, dtype=np.int64)
        starts_all = self.offsets[rids].astype(np.int64)
        lengths_all = (self.offsets[rids + 1].astype(np.int64) - starts_all)
        for at in range(0, rids.size, GATHER_BATCH):
            starts = starts_all[at:at + GATHER_BATCH]
            lengths = lengths_all[at:at + GATHER_BATCH]
            total = int(lengths.sum())
            if not total:
                continue
            before = np.zeros(lengths.size, dtype=np.int64)
            np.cumsum(lengths[:-1], out=before[1:])
            picks = np.repeat(starts - before, lengths) + np.arange(total, dtype=np.int64)
            counts += np.bincount(self.body[picks], minlength=self.n_tags)[:self.n_tags]
        return counts

    def _resolve_many(self, tags) -> tuple[list[int], list[str]]:
        """이름 목록 -> (색인 id 목록, 색인에 없는 이름). 순서를 지키고 중복은 한 번만."""
        found: list[int] = []
        missing: list[str] = []
        for raw in tags or ():
            tid = self.resolve(raw)
            if tid is None:
                missing.append(normalize(raw))
            elif tid not in found:
                found.append(tid)
        return found, missing

    def _without(self, rids: np.ndarray, excluded: list[int]) -> np.ndarray:
        """제외 태그가 **하나라도** 달린 게시물을 뺀다(Dev0714 Quick Search 우클릭과 같다).

        ⚠️ 정확히 그 태그만 뺀다 - `sex` 를 빼도 `group sex` 는 남는다.
        """
        for tid in excluded:
            if rids.size == 0:
                break
            rids = rids[~np.isin(rids, self.posting(tid), assume_unique=True)]
        return rids

    def _partition_filter(self, ratings, persons) -> set[int] | None:
        if not ratings and not persons:
            return None
        ratings = {str(r).lower() for r in (ratings or [])}
        persons = {str(p) for p in (persons or [])}
        keep = set()
        for pid, name in enumerate(self.partitions):
            rating, _, person = name.partition("_")
            if ratings and rating not in ratings:
                continue
            if persons and person not in persons:
                continue
            keep.add(pid)
        return keep

    def _live_posts(self, parts: set[int] | None) -> np.ndarray:
        """본문이 비지 않은 게시물 전부(분면을 주면 그 분면만). rid 오름차순."""
        lengths = np.diff(self.offsets.astype(np.int64))
        live = lengths > 0
        if parts is not None:
            owner = self.part_arr[:lengths.size]
            live &= np.isin(owner, np.fromiter(parts, dtype=np.uint8, count=len(parts)))
        return np.flatnonzero(live).astype(np.int64)

    def browse(self, *, ratings=None, persons=None, allowed=None, limit=40, min_posts=5,
               include_color=False, scan_cap=SCAN_CAP, prior=RANK_PRIOR) -> dict:
        """핀 **없이** 고른 분면(인원·등급)에서 특징적인 태그를 낸다 - 첫 화면(대분류 → 태그)용.

        기준선은 코퍼스 전체다: 그 분면에서의 비율 ÷ 전체에서의 비율. `allowed` (태그 불리언
        마스크)로 대분류 하나에 가둔다. 분면의 게시물이 많으면 explore 와 같이 고르게 표본을 뜬다
        - 여기서 세는 것은 흔한 태그들이라 표본으로 충분하다.
        """
        started = time.perf_counter()
        parts = self._partition_filter(ratings, persons)
        rids = self._live_posts(parts)
        out = {"schema": SCHEMA, "ratings": sorted(ratings or []), "persons": sorted(persons or []),
               "observed_posts": int(rids.size), "candidates": [], "corpus_posts": self.total_posts,
               "count_meaning": "고른 분면의 게시물 수", "note": NOTE}
        if rids.size == 0:
            out["status"] = "no_match"
            return out
        scanned = rids
        sampled = rids.size > scan_cap > 0
        if sampled:
            scanned = rids[np.linspace(0, rids.size - 1, scan_cap).astype(np.int64)]
        out["scanned_posts"] = int(scanned.size)
        out["sampled"] = sampled
        counts = self._count_tags(scanned)
        keep = (counts >= min_posts) & self.usable_arr & (self.obs_arr > 0)
        if not include_color:
            keep &= ~self.color_arr
        out["_pool"] = keep.copy()      # 갈래 필터 전의 풀(카테고리 탭의 개수용). 서비스가 지운다.
        if allowed is not None:
            keep &= allowed
        # ⚠️ 첫 화면은 explore 의 눌린 점수로 세우면 안 된다. `1girl_solo` 는 코퍼스의 절반이라
        #    어떤 태그도 그 분면에 크게 치우치지 않고, 표본에서 5건 겨우 넘긴 희귀 태그가 lift 2 로
        #    맨 위에 온다(실측: `shirt in mouth`·`double fox shadow puppet`). 여기서는
        #    **지지도 × lift** 로 세운다 - 많이 나오면서 이 분면에 치우친 것이 위다.
        out["candidates"] = self._rank(counts, keep, int(scanned.size), rids.size, sampled, limit, prior,
                                       support_weighted=True)
        out["candidate_pool"] = int(keep.sum())
        out["status"] = "matched" if out["candidates"] else "no_match"
        out["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
        return out

    def _rank(self, counts, keep, base, matched, sampled, limit, prior,
              support_weighted: bool = False) -> list[dict]:
        """explore/browse 공통 줄 세우기. lift 는 언제나 날 값으로 보인다.

        explore : `관측/(기댓값+PRIOR)` - 핀 교집합 안에서 **치우친** 것.
        browse  : `관측 × lift` - 분면 안에서 **많이 나오면서** 치우친 것(첫 화면용).
        """
        total = self.total_posts or 1
        picked = np.flatnonzero(keep)
        seen_arr = counts[picked].astype(np.float64)
        global_arr = self.obs_arr[picked].astype(np.float64)
        share_arr = seen_arr / base
        expected_arr = base * global_arr / total
        lift_arr = share_arr / (global_arr / total)
        score_arr = seen_arr * lift_arr if support_weighted else seen_arr / (expected_arr + prior)
        rows = sorted(zip(score_arr.tolist(), lift_arr.tolist(), share_arr.tolist(),
                          counts[picked].tolist(), picked.tolist()), reverse=True)
        factor = (matched / base) if base else 1.0
        return [
            {"tag": self.by_id[tid], "observed": seen,
             "observed_estimate": seen if not sampled else int(round(seen * factor)),
             "share": round(share, 6), "lift": round(lift, 2), "score": round(score, 3),
             "role": self.role.get(tid), "lane": self.lane.get(tid),
             "observed_total": self.observed.get(tid)}
            for score, lift, share, seen, tid in rows[:limit]
        ]

    def explore(self, pins, *, exclude=None, ratings=None, persons=None, limit=24,
                min_posts=5, include_color=False, roles=None, allowed=None,
                scan_cap=SCAN_CAP, prior=RANK_PRIOR) -> dict:
        """핀 전체를 동시에 만족하는(그리고 제외 태그가 없는) 게시물에서 다음 후보를 센다."""
        started = time.perf_counter()
        if not isinstance(pins, (list, tuple)) or not 1 <= len(pins) <= MAX_PINS:
            raise ValueError("핀은 1~%d개여야 한다" % MAX_PINS)
        if exclude is not None and (not isinstance(exclude, (list, tuple))
                                    or len(exclude) > MAX_EXCLUDE):
            raise ValueError("제외 태그는 %d개까지다" % MAX_EXCLUDE)
        wanted, unknown = self._resolve_many(pins)
        excluded, unknown_ex = self._resolve_many(exclude)
        excluded = [t for t in excluded if t not in wanted]
        out = {
            "schema": SCHEMA, "policy": POLICY_VERSION,
            "pins": [self.by_id[t] for t in wanted],
            "unknown_pins": unknown,
            "exclude": [self.by_id[t] for t in excluded],
            # 색인에 없는 제외 태그는 거를 게시물도 없다 - 조용히 무시하되 알려 준다.
            "unknown_exclude": unknown_ex,
            "ratings": sorted(ratings or []), "persons": sorted(persons or []),
            "observed_posts": 0, "counts_by_partition": [], "candidates": [],
            "corpus_posts": self.total_posts,
            "count_meaning": "핀 전부가 같은 게시물에 함께 달린 수",
            "proves_actor_direction": False, "proves_negation": False,
            "note": NOTE,
        }
        if unknown or not wanted:
            out["status"] = "unknown_tag" if unknown else "no_pins"
            return out

        parts = self._partition_filter(ratings, persons)
        rids = self._without(self._matching_posts(wanted, parts), excluded)
        out["observed_posts"] = int(rids.size)
        if rids.size == 0:
            out["status"] = "no_match"
            out["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
            return out

        # 상한을 넘으면 앞쪽만 자르지 않고 **고르게 건너뛰며** 뜬다. rid 는 대체로
        # 분면 순서라, 앞에서 자르면 한 등급/인원만 보게 된다.
        scanned = rids
        sampled = rids.size > scan_cap > 0
        if sampled:
            scanned = rids[np.linspace(0, rids.size - 1, scan_cap).astype(np.int64)]
        out["scanned_posts"] = int(scanned.size)
        out["sampled"] = sampled
        if sampled:
            out["sample_note"] = ("교집합이 커서 후보 순위는 %s건을 고르게 뽑아 셌다."
                                  " 관측 수 자체는 정확하다." % format(len(scanned), ","))

        # 분면별 내역은 **교집합 전체**에서 센다. 게시물을 펴지 않고 바이트 하나만 보면
        # 되므로 표본과 상관없이 정확하다.
        _, owner = self._partition_of(rids)
        per_part = np.bincount(owner, minlength=len(self.partitions))
        out["counts_by_partition"] = [
            {"partition": self.partitions[p], "posts": int(per_part[p])}
            for p in np.argsort(-per_part) if per_part[p]
        ]

        counts = self._count_tags(scanned)
        base = int(scanned.size)
        total = self.total_posts or 1
        keep = (counts >= min_posts) & self.usable_arr & (self.obs_arr > 0)
        if not include_color:
            keep &= ~self.color_arr
        keep[[t for t in wanted + excluded]] = False
        if roles:
            roles = set(roles)
            by_role = np.zeros(self.n_tags, dtype=bool)
            for tid, role in self.role.items():
                if role in roles:
                    by_role[tid] = True
            keep &= by_role
        out["_pool"] = keep.copy()      # 갈래 필터 전의 풀(카테고리 탭의 개수용). 서비스가 지운다.
        if allowed is not None:
            keep &= allowed

        # 표본을 떴으면 `observed` 는 **표본 안에서 센 수**다. 화면이 곱셈을 잘못하는 일이
        # 없도록 교집합 전체로 환산한 추정치를 따로 실어 보낸다(표본이 아니면 같은 값).
        out["candidates"] = self._rank(counts, keep, base, rids.size, sampled, limit, prior)
        out["candidate_pool"] = int(keep.sum())
        out["status"] = "matched"
        out["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
        return out

    def sample(self, pins, *, exclude=None, ratings=None, persons=None, n=5,
               include_color=False, seed=None) -> dict:
        """핀 전부를 포함하는 **실제 게시물**을 무작위로 골라 그 게시물의 태그 전체를 준다.

        Dev0714 Interactive 창 Quick Search 의 랜덤 프롬프트와 같은 동작이다. 돌려주는
        조합은 이어 붙인 것이 아니라 **게시물 하나에 실제로 함께 달린 태그**다.

        알아 둘 것
          - 색인 어휘(일반 + 성인 갈래) 안의 태그만 담긴다. 원본이 분류하지 못한 태그
            (`brown eyes` 등)와 메타(`monochrome` 등)는 원래 게시물에 있었어도 빠진다.
          - 색상은 기본으로 뺀다(맵 정책). 단 **핀으로 꽂은 태그는 색상이어도 남긴다.**
          - 교집합 전체에서 고르게 뽑는다 - 표본 상한(SCAN_CAP)과 무관하다.
          - 핀이 없으면 분면(인원·등급) 전체에서 뽑는다 - [랜덤 프롬프트 할당](사용자 지정 2026-09-12 밤).
        """
        started = time.perf_counter()
        if not isinstance(pins, (list, tuple)) or len(pins) > MAX_PINS:
            raise ValueError("핀은 %d개까지다" % MAX_PINS)
        if exclude is not None and (not isinstance(exclude, (list, tuple))
                                    or len(exclude) > MAX_EXCLUDE):
            raise ValueError("제외 태그는 %d개까지다" % MAX_EXCLUDE)
        n = max(1, min(int(n), MAX_SAMPLES))
        wanted, unknown = self._resolve_many(pins)
        excluded, unknown_ex = self._resolve_many(exclude)
        excluded = [t for t in excluded if t not in wanted]
        out = {
            "schema": SCHEMA, "policy": POLICY_VERSION,
            "pins": [self.by_id[t] for t in wanted],
            "unknown_pins": unknown,
            "exclude": [self.by_id[t] for t in excluded],
            "unknown_exclude": unknown_ex,
            "ratings": sorted(ratings or []), "persons": sorted(persons or []),
            "observed_posts": 0, "samples": [],
            "kind": "observed_post_tag_set",
            "note": "게시물 하나에 실제로 함께 달린 태그다(색인 어휘 안에서). 합성하지 않았다.",
        }
        if unknown:
            out["status"] = "unknown_tag"
            return out
        parts = self._partition_filter(ratings, persons)
        pool = self._matching_posts(wanted, parts) if wanted else self._live_posts(parts)
        rids = self._without(pool, excluded)
        out["observed_posts"] = int(rids.size)
        if rids.size == 0:
            out["status"] = "no_match"
            out["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
            return out

        rng = random.Random(seed)
        pinned = set(wanted)
        table = self.part_arr
        for i in rng.sample(range(int(rids.size)), min(n, int(rids.size))):
            rid = int(rids[i])
            tids = self.body[self.offsets[rid]:self.offsets[rid + 1]].tolist()
            kept = [t for t in tids if include_color or t in pinned or not self.color_arr[t]]
            # 인원 태그 -> 핀 -> 나머지(id 순 = 흔한 태그 먼저). 프롬프트로 바로 쓸 수 있게.
            population = [t for t in kept if self.role.get(t) == "population"]
            head = population + [t for t in wanted if t in kept and t not in population]
            rest = [t for t in kept if t not in set(head)]
            tags = [self.by_id[t] for t in head + rest]
            out["samples"].append({
                "tags": tags, "prompt": ", ".join(tags),
                "partition": self.partitions[table[rid]] if rid < table.size else None,
                "dropped_color": len(tids) - len(kept),
            })
        out["status"] = "matched"
        out["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
        return out


_INDEX: EventMapIndex | None = None


def load_index(path: str | Path) -> EventMapIndex:
    """Process-wide singleton; the index is read-only and safe to share."""
    global _INDEX
    if _INDEX is None or _INDEX.path != Path(path).resolve():
        if _INDEX is not None:
            _INDEX.close()
        _INDEX = EventMapIndex(path)
    return _INDEX
