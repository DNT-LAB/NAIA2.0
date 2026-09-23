"""작가 x 태그 친화도 — "이 태그를 자주 그리는 작가".

`data/artist_tag_affinity.naiapack`(tools/build_artist_affinity_pack.py 산출물)을
읽어 copyright / character 축의 친화도를 **60~150ms** 에 낸다. 같은 답을 전수 주사로
내면 태그 하나에 49초(참조 구현) 또는 23초(NAIA 검색)가 든다.

⚠️ `share == 0` 은 **"그 태그를 안 그린다" 가 아니라 "모른다"** 다.
   이 자료로 "이 태그를 자주 그리는 사람 찾기" 는 되지만 **"안 그리는 사람만 남기기" 는
   안 된다.** 표에 없는 이유가 (a) 정말 안 그려서인지 (b) 표본이 없어서인지 구분이
   안 되기 때문이다. 이 프로젝트에서 한 번 뒤집어 구현했다가 되돌린 적이 있다.

⚠️ 문턱을 데이터에 걸지 않았다. 표본이 얇은 작가(`1/1 = 100%`)가 위를 덮는 것은
   **Wilson 하한**(기본 정렬)이 막는다 - 문턱은 화면 슬라이더로 남긴다. 실측으로
   `feet` 를 비중순으로 세우면 `xhb 63/63` 이, Wilson 으로 세우면 `wd (1106592840)
   299/300` 이 1위다. 뒤쪽이 사람들이 기대하는 순서다.

⚠️ general 축은 이 팩에 없다. `event_map` 의 `.naiamap` 이 갖고 있고 그쪽 행 번호는
   **1-based** 다 - 이 팩의 `rid_artist` 와 이을 때는 반드시 1을 빼라
   (`meta.rid_note`). 섞으면 건수는 그럴듯한데 작가만 통째로 어긋난다.

팩이 없는 것은 고장이 아니다. `state()` 가 `missing` 을 돌려주고 호출자는 기존 검색
경로로 내려가면 된다 - 기능만 꺼지고 앱은 산다.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import heapq
import threading
import zlib
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from core.event_map.index import decode_postings
from core.event_map.pack import PackReader

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PACK_NAME = "artist_tag_affinity.naiapack"
# general 축은 **옆 파일**이다(사용자 결정 2026-09-19, 방안 B). 역색인 대신
# (작가, 횟수) 집계만 담아 약 12MB - postings 로 담으면 +256MB 라 배포판이 배가 된다.
# 없으면 general 갈래만 잠기고 나머지는 그대로 돈다.
GENERAL_PACK_NAME = "artist_tag_general.naiapack"
GENERAL_SCHEMA = "naia-artist-general-v1"
GENERAL_AXIS = "general"
SCHEMA = "naia-artist-affinity-v1"
RATING_CODE = {"g": 0, "s": 1, "q": 2, "e": 3}
ALL_RATINGS = frozenset(RATING_CODE)
# 95% Wilson 하한. 비율만 높고 근거가 얇은 이름이 위로 오는 것을 막는다.
WILSON_Z = 1.96


def _clean_ratings(ratings: Iterable[str] | None) -> frozenset:
    """모르는 등급 글자는 버리고, 비면 전체로 본다."""
    wanted = frozenset(r for r in (ratings or ALL_RATINGS) if r in RATING_CODE)
    return wanted or ALL_RATINGS


def wilson_lower_bound(hit: np.ndarray, total: np.ndarray, z: float = WILSON_Z
                       ) -> np.ndarray:
    """이항 비율의 Wilson 하한(벡터). total 0 은 0 으로 둔다."""
    total = np.maximum(total, 1).astype(np.float64)
    p = hit.astype(np.float64) / total
    z2 = z * z
    denom = 1.0 + z2 / total
    center = (p + z2 / (2.0 * total)) / denom
    margin = (z / denom) * np.sqrt(p * (1.0 - p) / total + z2 / (4.0 * total * total))
    return np.clip(center - margin, 0.0, 1.0)


class ArtistAffinityPack:
    """팩 하나의 단일 소유자. 지연 로딩이고 스레드 안전하다."""

    def __init__(self, path: str | Path | None = None,
                 data_dir: str | Path | None = None):
        if path is not None:
            self._candidates = [Path(path)]
            # 옆 파일은 **같은 폴더**에서 찾는다 - 짝이므로 따로 다니면 안 된다.
            self._general_candidates = [Path(path).with_name(GENERAL_PACK_NAME)]
        else:
            root = Path(data_dir) if data_dir is not None else PROJECT_ROOT / "data"
            self._candidates = [Path(root) / DEFAULT_PACK_NAME]
            self._general_candidates = [Path(root) / GENERAL_PACK_NAME]
        self._lock = threading.Lock()
        self._loaded = False
        self._error: str | None = None
        self._reader: PackReader | None = None
        self._meta: dict[str, Any] = {}
        self._names: dict[str, list[str]] = {}
        self._lookup: dict[str, dict[str, int]] = {}
        self._index: dict[str, np.ndarray] = {}
        self._span: dict[str, int] = {}
        self._artists: list[str] = []
        self._rid_artist: np.ndarray | None = None
        self._rid_rating: np.ndarray | None = None
        self._denominators: dict[frozenset, np.ndarray] = {}
        self._general: dict[str, Any] | None = None
        self._general_loaded = False
        self._general_error: str | None = None

    # ------------------------------------------------------------- 열기
    def _path(self) -> Path | None:
        for candidate in self._candidates:
            if candidate.is_file():
                return candidate
        return None

    def _load(self) -> bool:
        if self._loaded:
            return self._reader is not None
        with self._lock:
            if self._loaded:
                return self._reader is not None
            self._loaded = True
            path = self._path()
            if path is None:
                self._error = "pack not found"
                return False
            try:
                reader = PackReader(path)
                meta = reader.json_of("meta")
                if meta.get("schema") != SCHEMA:
                    reader.close()
                    self._error = f"unknown schema: {meta.get('schema')!r}"
                    return False
                for axis in meta.get("axes", ()):
                    names = json.loads(zlib.decompress(reader.bytes_of(f"names_{axis}")))
                    self._names[axis] = names
                    # 조회는 소문자로. 코퍼스 태그는 소문자지만 질의는 아무거나 온다.
                    self._lookup[axis] = {name.lower(): tid
                                          for tid, name in enumerate(names)}
                    self._index[axis] = np.frombuffer(
                        reader.bytes_of(f"post_index_{axis}"), dtype=np.uint64)
                    # postings 구역의 시작 위치만 들고 있다가 mmap 을 직접 자른다.
                    # `bytes_of` 를 쓰면 질의마다 구역 **전체**(13~27MB)를 복사한다.
                    self._span[axis] = reader.span(f"postings_{axis}")[0]
                self._artists = json.loads(
                    zlib.decompress(reader.bytes_of("artist_names")))
                self._rid_artist = np.frombuffer(
                    zlib.decompress(reader.bytes_of("rid_artist")), dtype=np.uint32)
                self._rid_rating = np.frombuffer(
                    zlib.decompress(reader.bytes_of("rid_rating")), dtype=np.uint8)
            except Exception as exc:  # 망가진 팩이 앱을 죽이면 안 된다
                self._error = f"{type(exc).__name__}: {exc}"
                return False
            rows = int(meta.get("rows", 0))
            if self._rid_artist.size != rows or self._rid_rating.size != rows:
                reader.close()
                self._error = "side arrays do not match meta.rows"
                self._rid_artist = self._rid_rating = None
                return False
            self._reader = reader
            self._meta = meta
            return True

    def close(self) -> None:
        general = self._general
        self._general = None
        self._general_loaded = False
        if general is not None:
            try:
                general["reader"].close()
            except Exception:
                pass
        with self._lock:
            if self._reader is not None:
                self._reader.close()
                self._reader = None

    # ------------------------------------------------------------- 상태
    def state(self) -> dict[str, Any]:
        """팩이 없는 것은 고장이 아니다 - 찾아본 자리를 같이 돌려준다."""
        if not self._load():
            return {"state": "missing", "reason": self._error,
                    "searched": [str(p) for p in self._candidates]}
        meta = self._meta
        return {
            "state": "ready",
            "path": str(self._path()),
            "rows": meta.get("rows"),
            "artists": meta.get("artists"),
            "axes": self._axes_state(),
            "built_at": meta.get("built_at"),
            "source_sha256": (meta.get("source") or {}).get("sha256"),
            "ratings": sorted(RATING_CODE),
            # 화면이 상수를 중복해 갖지 않도록 여기서 말해 준다.
            "min_posts": meta.get("min_posts"),
            "general_axis": (
                {"state": "ready", "path": str(self._general_path()),
                 "tags": len(self._general["names"]),
                 "min_count": self._general["min_count"],
                 "built_at": self._general["meta"].get("built_at"),
                 "pairs": (self._general["meta"].get("stats") or {}).get("pairs")}
                if self._load_general()
                else {"state": "missing", "reason": self._general_error,
                      "searched": [str(p) for p in self._general_candidates]}),
        }

    def _axes_state(self) -> dict[str, Any]:
        """화면이 **갈래를 여닫는 근거**. 여기 없는 축은 화면에서 잠긴다."""
        out: dict[str, Any] = {axis: {"tags": len(self._names[axis])}
                               for axis in self._names}
        if self._load_general():
            out[GENERAL_AXIS] = {
                "tags": len(self._general["names"]),
                # ⚠️ 이 축만 **문턱이 있다**(집계표라서). 화면이 이 값으로 입력을
                #    잡아 주지 않으면 사용자가 5를 넣고 조용히 10의 답을 본다.
                "min_count": self._general["min_count"],
                "aggregate": True,
            }
        return out

    def _general_path(self) -> Path | None:
        for candidate in self._general_candidates:
            if candidate.is_file():
                return candidate
        return None

    def _load_general(self) -> bool:
        """옆의 general 집계표. **없는 것은 고장이 아니다** - 그 갈래만 잠긴다.

        ⚠️ 작가 색인은 본 팩의 것을 그대로 쓰는 표다. 다른 코퍼스 빌드로 구운 것이
           섞이면 **건수는 그럴듯하고 작가만 통째로 틀린다** - 그래서 작가 이름표의
           지문을 맞대 보고 다르면 아예 안 연다.
        """
        if self._general_loaded:
            return self._general is not None
        if not self._load():
            return False
        with self._lock:
            if self._general_loaded:
                return self._general is not None
            self._general_loaded = True
            path = self._general_path()
            if path is None:
                self._general_error = "general pack not found"
                return False
            try:
                reader = PackReader(path)
                meta = reader.json_of("meta")
                if meta.get("schema") != GENERAL_SCHEMA:
                    reader.close()
                    self._general_error = f"unknown schema: {meta.get('schema')!r}"
                    return False
                mine = hashlib.sha256(
                    json.dumps(self._artists, ensure_ascii=False).encode("utf-8")
                ).hexdigest()
                if str(meta.get("artist_table_sha256") or "") != mine:
                    reader.close()
                    self._general_error = (
                        "artist table does not match the affinity pack "
                        "(두 파일은 같은 코퍼스로 구운 짝이어야 한다)")
                    return False
                names = json.loads(zlib.decompress(reader.bytes_of("names_general")))
                self._general = {
                    "reader": reader,
                    "meta": meta,
                    "names": names,
                    "lookup": {name.lower(): tid for tid, name in enumerate(names)},
                    "posts": np.frombuffer(reader.bytes_of("posts_general"),
                                           dtype=np.uint32),
                    "id_index": np.frombuffer(reader.bytes_of("id_index"),
                                              dtype=np.uint64),
                    "cnt_index": np.frombuffer(reader.bytes_of("cnt_index"),
                                               dtype=np.uint64),
                    "ids_base": reader.span("ids_general")[0],
                    "cnt_base": reader.span("counts_general")[0],
                    "min_count": int(meta.get("min_count") or 1),
                }
            except Exception as exc:      # 망가진 옆 파일이 앱을 죽이면 안 된다
                self._general_error = f"{type(exc).__name__}: {exc}"
                self._general = None
                return False
            return True

    def general_min_count(self) -> int:
        """이 표가 **셀 수 있는 가장 낮은 횟수**. 그 아래는 자료가 없다."""
        return int(self._general["min_count"]) if self._load_general() else 0

    def _general_pair(self, tid: int) -> tuple[np.ndarray, np.ndarray]:
        g = self._general
        reader = g["reader"]
        a = g["ids_base"] + int(g["id_index"][tid])
        b = g["ids_base"] + int(g["id_index"][tid + 1])
        c = g["cnt_base"] + int(g["cnt_index"][tid])
        d = g["cnt_base"] + int(g["cnt_index"][tid + 1])
        ids = decode_postings(zlib.decompress(reader.map[a:b]))
        counts = np.frombuffer(zlib.decompress(reader.map[c:d]), dtype=np.uint32)
        return ids, counts

    def available(self) -> bool:
        return self._load()

    def axes(self) -> list[str]:
        out = list(self._names) if self._load() else []
        if out and self._load_general():
            out.append(GENERAL_AXIS)
        return out

    # ------------------------------------------------------------- 조회
    def resolve(self, tag: str, axis: str | None = None) -> tuple[str, int] | None:
        """태그가 어느 축에 있나. 두 축에 다 있으면 **게시물이 많은 쪽**을 고른다."""
        if not self._load():
            return None
        key = (tag or "").strip().lower().replace("_", " ")
        if not key:
            return None
        found = []
        for name in ([axis] if axis else list(self._names)):
            tid = self._lookup.get(name, {}).get(key)
            if tid is not None:
                found.append((name, tid))
        # general 은 옆 파일이라 목록이 따로다. 축을 안 주면 마지막에 본다 -
        # 어휘가 제일 크고(10만) 흔한 낱말이 많아 먼저 보면 고유명을 가린다.
        if (axis in (None, GENERAL_AXIS)) and self._load_general():
            tid = self._general["lookup"].get(key)
            if tid is not None:
                found.append((GENERAL_AXIS, tid))
        if not found:
            return None
        if len(found) == 1:
            return found[0]
        return max(found, key=lambda pair: self._axis_posts(*pair))

    def posts(self, tag: str, axis: str | None = None) -> int:
        """태그의 게시물 수(팩에 없으면 0). Assist 가 캐릭터 후보를 줄 세울 때 쓴다(카나데 -> yoisaki 2,940 …)."""
        try:
            hit = self.resolve(tag, axis)
            return int(self._axis_posts(*hit)) if hit else 0
        except Exception:
            return 0

    def _axis_posts(self, axis: str, tid: int) -> int:
        """그 태그의 게시물 수. general 은 굽는 쪽이 적어 둔 값을 그냥 읽는다."""
        if axis == GENERAL_AXIS:
            return int(self._general["posts"][tid])
        return int(self._posting(axis, tid).size)

    def _posting(self, axis: str, tid: int) -> np.ndarray:
        index = self._index[axis]
        base = self._span[axis]
        start, end = base + int(index[tid]), base + int(index[tid + 1])
        # 이 팩의 postings 는 **0-based** 다(meta.rid_base). 자리 옮김이 없다.
        return decode_postings(zlib.decompress(self._reader.map[start:end]))

    def _denominator(self, ratings: frozenset) -> np.ndarray:
        """작가별 **분모**를 분자와 같은 필터로 센다.

        이걸 미리 구워 둔 표(`artist_dictionary.py` 등)로 대신하면 안 된다 - 그 표는
        164명이 공식 수치로 덮여 있어 분모가 최대 12배 부풀어 있고, 등급을 좁히면
        분자만 줄어 순위가 통째로 거짓이 된다.
        """
        cached = self._denominators.get(ratings)
        if cached is not None:
            return cached
        codes = self._rid_artist
        if ratings == ALL_RATINGS:
            picked = codes[codes != 0]
        else:
            wanted = np.asarray(sorted(RATING_CODE[r] for r in ratings), dtype=np.uint8)
            mask = np.isin(self._rid_rating, wanted)
            picked = codes[mask & (codes != 0)]
        counts = np.bincount(picked, minlength=len(self._artists))
        self._denominators[ratings] = counts
        return counts

    # ── 공개 문 ────────────────────────────────────────────────────────
    #  깊이 검색(`core/artist_search.py`)이 밑단을 직접 만지지 않게 낸 창구다.
    @property
    def artist_names(self) -> list[str]:
        """작가 이름표. 색인 0 은 '작가 없음/합작' 자리다."""
        self._load()
        return self._artists

    def denominator(self, ratings: Iterable[str] | None = None) -> np.ndarray | None:
        """작가별 게시물 수(등급 필터 반영). 없으면 None."""
        if not self._load():
            return None
        return self._denominator(_clean_ratings(ratings))

    def tally(self, tag: str, *, axis: str | None = None,
              ratings: Iterable[str] | None = None) -> dict[str, Any]:
        """한 태그의 **작가별 분자**. 순위표를 만들지 않는다.

        ⚠️ 이것이 `affinity()` 와 깊이 검색의 공통 밑단이다. 분자를 내주는 것만으로도
           깊이마다 행을 91,529개씩 만들고 버리는 일이 사라진다.
        """
        if not self._load():
            return {"state": "missing", "reason": self._error}
        target = self.resolve(tag, axis)
        if target is None:
            return {"state": "unknown_tag", "tag": tag, "axes": list(self._names)}
        found_axis, tid = target
        wanted = _clean_ratings(ratings)

        if found_axis == GENERAL_AXIS:
            # ⚠️ 집계표는 **등급을 미리 합쳐** 담는다. 등급으로 좁혀 달라는 요청을
            #    조용히 무시하면 답이 거짓이 된다 - 못 한다고 말한다.
            if wanted != ALL_RATINGS:
                return {"state": "rating_unsupported", "tag": tag,
                        "axis": GENERAL_AXIS,
                        "reason": "general 축은 집계표라 등급으로 좁힐 수 없다"}
            ids, counts = self._general_pair(tid)
            numerator = np.zeros(len(self._artists), dtype=np.int64)
            numerator[ids] = counts
            return {
                "state": "ready",
                "axis": GENERAL_AXIS,
                "tag": self._general["names"][tid],
                "ratings": sorted(ALL_RATINGS),
                "posts": int(self._general["posts"][tid]),
                # ⚠️ 문턱 아래를 안 담았으니 **합이 posts 보다 작다**. 빠진 것이
                #    아니라 안 센 것이다 - 화면이 이 둘을 같은 줄에 놓으면 안 된다.
                "matched": int(counts.sum()),
                "min_count": self._general["min_count"],
                "aggregate": True,
                "numerator": numerator,
            }

        rids = self._posting(found_axis, tid)
        posts = int(rids.size)
        if wanted != ALL_RATINGS:
            keep = np.asarray(sorted(RATING_CODE[r] for r in wanted), dtype=np.uint8)
            rids = rids[np.isin(self._rid_rating[rids], keep)]
        picked = self._rid_artist[rids]
        # ⚠️ 0 은 '작가 없음' 이다. 빼지 않으면 합작·무명 행이 한 작가로 뭉친다.
        picked = picked[picked != 0]
        return {
            "state": "ready",
            "axis": found_axis,
            "tag": self._names[found_axis][tid],
            "ratings": sorted(wanted),
            "posts": posts,
            "matched": int(rids.size),
            "numerator": np.bincount(picked, minlength=len(self._artists)),
        }

    def affinity(self, tag: str, *, axis: str | None = None,
                 ratings: Iterable[str] | None = None, min_posts: int = 0,
                 limit: int | None = 300, order: str = "wilson") -> dict[str, Any]:
        """한 태그의 작가 친화도.

        `min_posts` 와 `limit` 은 **화면 조건**이다 - 팩에는 문턱이 없으므로 0 으로
        불러도 비용이 같다(큰 태그에서 응답만 커진다: twintails 문턱 0 이면 139,751명).
        """
        counted = self.tally(tag, axis=axis, ratings=ratings)
        if counted["state"] != "ready":
            return {**counted, "rows": []}
        found_axis = counted["axis"]
        wanted = frozenset(counted["ratings"])
        posts = counted["posts"]
        numerator = counted["numerator"]
        seen = np.flatnonzero(numerator)

        denominator = self._denominator(wanted)
        eligible = seen[denominator[seen] >= max(int(min_posts), 1)]
        hit = numerator[eligible]
        total = denominator[eligible]
        share = hit / np.maximum(total, 1)
        wilson = wilson_lower_bound(hit, total)
        rank = np.argsort(-(wilson if order == "wilson" else share), kind="stable")
        if limit is not None and limit > 0:
            rank = rank[:limit]

        rows = [{"artist": self._artists[int(eligible[i])],
                 "hit": int(hit[i]), "total": int(total[i]),
                 "share": round(float(share[i]), 4),
                 "wilson": round(float(wilson[i]), 4)} for i in rank]
        return {
            "state": "ready",
            "tag": counted["tag"],
            "axis": found_axis,
            "ratings": sorted(wanted),
            "posts": posts,                 # 등급 거르기 **전** 게시물 수
            "matched": counted["matched"],  # 거른 뒤
            "hits": int(numerator.sum()),   # 그중 단일 작가 행
            "artists": int(seen.size),
            "eligible": int(eligible.size),
            "min_posts": int(min_posts),
            "order": order,
            "rows": rows,
        }

    #: 실제로 풀어서 **정확히** 세는 개수. 화면에 보일 것보다 넉넉하게.
    SUGGEST_COUNT_CAP = 60

    def _span_of(self, axis: str, tid: int) -> int:
        """postings 구역의 **바이트 길이**. 풀지 않고 얻는 크기의 대리값이다."""
        index = self._index[axis]
        return int(index[tid + 1]) - int(index[tid])

    @staticmethod
    def _suggest_ranker(key: str):
        # Preserve punctuation in the query: (nte and nte) are useful fragments.
        boundary = re.compile(r"(?<!\w)" + re.escape(key) + r"(?!\w)")
        return lambda tag: 2 if tag == key else int(bool(boundary.search(tag)))

    def suggest(self, prefix: str, axis: str | None = None, limit: int = 20
                ) -> list[dict[str, Any]]:
        """Substring suggestions, with exact names/words before interior matches.

        Scan the whole vocabulary; stopping at the first 600 matches loses later
        names. Only the best compressed spans are decoded to obtain post counts.
        Counts are exact; selection within a match tier remains approximate.
        """
        if not self._load():
            return []
        key = (prefix or "").strip().lower().replace("_", " ")
        if not key:
            return []
        want = max(int(limit or 20), 1)
        if axis == GENERAL_AXIS:
            return self._suggest_general(key, want)
        axes = [axis] if axis else list(self._names)
        rank = self._suggest_ranker(key)
        candidates = (
            (rank(tag), self._span_of(name, tid), name, tag, tid)
            for name in axes for tag, tid in self._lookup.get(name, {}).items()
            if key in tag
        )
        rough = heapq.nlargest(max(want, self.SUGGEST_COUNT_CAP), candidates)
        out = [(tier, {"tag": self._names[name][tid], "axis": name,
                       "posts": int(self._posting(name, tid).size)})
               for tier, _span, name, tag, tid in rough]
        out.sort(key=lambda row: (-row[0], -row[1]["posts"], row[1]["tag"]))
        return [row for _tier, row in out[:want]]

    def _suggest_general(self, key: str, want: int) -> list[dict[str, Any]]:
        """General uses stored counts; suggestions never decode postings."""
        if not self._load_general():
            return []
        g = self._general
        rank = self._suggest_ranker(key)
        candidates = (
            (-rank(tag), -int(g["posts"][tid]), g["names"][tid])
            for tag, tid in g["lookup"].items() if key in tag
        )
        return [{"tag": name, "axis": GENERAL_AXIS, "posts": -count}
                for _tier, count, name in heapq.nsmallest(want, candidates)]


_default: ArtistAffinityPack | None = None
_default_lock = threading.Lock()


def default_pack() -> ArtistAffinityPack:
    """앱 전체가 공유하는 팩 하나. 열기는 첫 질의까지 미룬다."""
    global _default
    if _default is None:
        with _default_lock:
            if _default is None:
                _default = ArtistAffinityPack()
    return _default
