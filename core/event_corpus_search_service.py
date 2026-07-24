"""Event Corpus Search — "태그 N개 누적 -> 매칭 이벤트 -> 공기 빈도순 추천 태그" 질의.

Dev0714 Interactive Mode 의 QuickSearchBlock 탐색 루프를 헤드리스로 옮긴 것이다.
Event Preset(카테고리->이벤트->콤보, 하향)과 질의 방향이 반대이고 데이터 저장소도 다르다
(Event Preset 은 naia_prompt_preset ZIP 의 parquet 를 읽는다).

성능이 이 모듈의 존재 이유다. 원본 ``SinglePartitionStore.filter_events`` /
``get_tag_counts`` 를 그대로 쓰면 두 지점에서 터진다:

1. 선택 단계 — required 태그가 없으면 ``set(range(num_events))`` 를 만들고 ``sorted(list(...))``
   까지 돈다(quick_search_data.py:110,122). 첫 질의(필터 0개)가 가장 흔한데 가장 비싸다.
2. 집계 단계 — 이벤트마다 파이썬 리스트를 확장한 뒤 Counter 를 돌린다(:135-155).

이 프로젝트에는 같은 성격의 사고 전례가 있다(Pool Quick Filter 재적용 시 청크 없는 int-set
처리로 15분 먹통). 그래서 여기서는 원본 메서드를 호출하지 않고, 포스팅 리스트와 CSR 버퍼를
numpy 로 직접 다룬다. ``quick_search_data.py`` 자체는 수정하지 않는다(Dev0714 와 동일 blob 유지).
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any, Callable, Iterable, Sequence

try:  # pragma: no cover
    import numpy as np
    HAS_NUMPY = True
except ImportError:  # pragma: no cover
    np = None  # type: ignore[assignment]
    HAS_NUMPY = False

from core.event_corpus_index import (
    CorpusUnavailable,
    EventCorpusIndex,
    normalize_tag,
    partition_name,
    seed_tags,
)

# 집계 청크. 피크 메모리가 이 값에 비례해 상한이 생긴다.
CHUNK = 50_000

# 결과 캐시: (partition, include, exclude) -> counts 벡터. 검색어 타이핑/페이지 이동마다
# 전 코퍼스를 재집계하지 않기 위한 것이다.
DEFAULT_RESULT_CACHE_ENTRIES = 24

MAX_LIMIT = 200
MAX_TAGS_PER_SIDE = 64
MAX_TAG_LENGTH = 128


class QueryError(Exception):
    """검증 실패. code 는 프론트가 분기할 수 있는 안정 문자열."""

    def __init__(self, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra

    def to_payload(self) -> dict[str, Any]:
        return {"ok": False, "code": self.code, "message": self.message, **self.extra}


class EventCorpusSearchService:
    def __init__(
        self,
        index: EventCorpusIndex,
        *,
        cache_entries: int = DEFAULT_RESULT_CACHE_ENTRIES,
    ) -> None:
        self._index = index
        self._cache: "OrderedDict[tuple, tuple[Any, int]]" = OrderedDict()
        self._cache_entries = int(cache_entries)
        self._cache_lock = threading.RLock()

    # ------------------------------------------------------------------
    # 상태 / 시드
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        payload = self._index.status()
        payload["ok"] = True
        return payload

    def seed_tags(self, person: Any) -> list[str]:
        return seed_tags(person)

    def invalidate(self) -> None:
        self._index.invalidate()
        with self._cache_lock:
            self._cache.clear()

    # ------------------------------------------------------------------
    # 입력 검증
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_tag_list(values: Any, field: str) -> list[Any]:
        if values is None:
            return []
        if not isinstance(values, (list, tuple)):
            raise QueryError("invalid_request", f"{field} must be a list")
        if len(values) > MAX_TAGS_PER_SIDE:
            raise QueryError(
                "invalid_request",
                f"{field} exceeds {MAX_TAGS_PER_SIDE} entries",
            )
        for item in values:
            if not isinstance(item, str):
                raise QueryError("invalid_request", f"{field} must contain strings")
            if len(item) > MAX_TAG_LENGTH:
                raise QueryError("invalid_request", f"{field} entry too long")
        return list(values)

    # ------------------------------------------------------------------
    # 선택 단계 (BLOCKER 대응)
    # ------------------------------------------------------------------

    def _select(self, store: Any, inc_ids: Sequence[int], exc_ids: Sequence[int]) -> Any:
        """매칭 이벤트 인덱스. ``None`` 은 '전체 이벤트' sentinel.

        파이썬 set 을 만들지 않는다. 포스팅 리스트는 이미 정렬된 int32 ndarray 라
        intersect1d / setdiff1d 를 assume_unique 로 쓸 수 있다.
        """
        index = self._index
        if not inc_ids and not exc_ids:
            return None  # 전체 선택 fast path — 배열조차 만들지 않는다.

        empty = np.array([], dtype=np.int32)
        if inc_ids:
            posts = []
            for tag_id in inc_ids:
                arr = index.postings(store, tag_id)
                if arr is None or len(arr) == 0:
                    return empty
                posts.append(arr)
            posts.sort(key=len)  # 빈도 적은 순 교집합 (Dev0714 최적화 유지)
            sel = posts[0]
            for arr in posts[1:]:
                sel = np.intersect1d(sel, arr, assume_unique=True)
                if sel.size == 0:
                    return sel
        else:
            num_events = int(getattr(store, "num_events", 0) or 0)
            sel = np.arange(num_events, dtype=np.int32)

        for tag_id in exc_ids:
            arr = index.postings(store, tag_id)
            if arr is None or len(arr) == 0:
                continue
            sel = np.setdiff1d(sel, arr, assume_unique=True)
            if sel.size == 0:
                break
        return sel

    # ------------------------------------------------------------------
    # 집계
    # ------------------------------------------------------------------

    def _tag_counts(
        self,
        store: Any,
        sel: Any,
        num_tags: int,
        should_abort: Callable[[], bool] | None = None,
    ) -> Any:
        indptr, indices, _ = self._index.csr_arrays(store)

        # np.bincount(x, minlength=n) 은 max(n, x.max()+1) 길이를 반환한다.
        # tag id 가 조밀하지 않으면 결과가 num_tags 보다 길어지므로 슬라이스가 필수다.
        if sel is None:
            # 전체 선택은 단일 C 호출이라 중간에 끊을 수 없다. 시작 전에 한 번은 확인해서
            # 이미 superseded 된 질의가 전 코퍼스를 훑는 일은 막는다.
            if should_abort is not None and should_abort():
                raise _Aborted()
            return np.bincount(indices, minlength=num_tags)[:num_tags].astype(np.int64)

        total = np.zeros(num_tags, dtype=np.int64)
        for beg in range(0, int(sel.size), CHUNK):
            if should_abort is not None and should_abort():
                # 협조적 조기 종료. asyncio.to_thread 취소는 이미 시작된 스레드를 멈추지 못한다.
                raise _Aborted()
            part = sel[beg:beg + CHUNK]
            starts = indptr[part]
            lens = (indptr[part + 1] - starts).astype(np.int64)
            n = int(lens.sum())
            if n == 0:
                continue
            offsets = np.repeat(
                starts - np.concatenate(([0], np.cumsum(lens)[:-1])),
                lens,
            )
            gathered = indices[offsets + np.arange(n)]
            total += np.bincount(gathered, minlength=num_tags)[:num_tags]
        return total

    # ------------------------------------------------------------------
    # 질의
    # ------------------------------------------------------------------

    def query(
        self,
        payload: dict[str, Any] | None = None,
        *,
        should_abort: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        payload = payload if isinstance(payload, dict) else {}
        if not HAS_NUMPY:
            raise QueryError("numpy_unavailable", "numpy is required for corpus search")

        try:
            name = partition_name(payload.get("rating"), payload.get("person"))
        except ValueError as exc:
            raise QueryError("invalid_request", str(exc)) from exc

        raw_include = self._validate_tag_list(payload.get("include"), "include")
        raw_exclude = self._validate_tag_list(payload.get("exclude"), "exclude")

        # 범위 위반은 조용히 보정하지 않는다 — 잘못된 클라이언트 요청을 숨기면
        # 프론트 버그가 "결과가 이상한데 ok:true" 로 나타난다.
        raw_offset = payload.get("offset")
        raw_limit = payload.get("limit")
        if raw_offset in (None, ""):
            raw_offset = 0
        if raw_limit in (None, ""):
            raw_limit = 60
        if isinstance(raw_offset, bool) or isinstance(raw_limit, bool):
            raise QueryError("invalid_request", "offset/limit must be integers")
        if not isinstance(raw_offset, int) or not isinstance(raw_limit, int):
            raise QueryError("invalid_request", "offset/limit must be integers")
        offset, limit = int(raw_offset), int(raw_limit)
        if offset < 0:
            raise QueryError("invalid_request", "offset must be >= 0")
        if limit < 1 or limit > MAX_LIMIT:
            raise QueryError("invalid_request", f"limit must be 1..{MAX_LIMIT}")
        search = normalize_tag(payload.get("search"))

        index = self._index
        status = index.status()
        if status["state"] != "ready":
            raise QueryError(
                "corpus_unavailable",
                status.get("message") or "event corpus data is not installed",
                state=status["state"],
            )
        if status["partitions"].get(name) != "ready":
            # 폴백하지 않는다. 다른 파티션으로 조용히 넘어가면 사용자가 고른 rating/person 과
            # 실제 집계 대상이 달라진다.
            raise QueryError(
                "partition_unavailable",
                f"partition not available: {name}",
                partition=name,
            )

        include, unknown_include = index.resolve_tags(raw_include)
        exclude, unknown_exclude = index.resolve_tags(raw_exclude)

        # include 는 fail-closed. 오타를 조용히 무시하면 필터가 거짓말을 한다.
        if unknown_include:
            raise QueryError(
                "unknown_include_tags",
                "unknown tags in include filter",
                tags=unknown_include,
            )
        conflict = sorted(set(include) & set(exclude))
        if conflict:
            raise QueryError("conflicting_tags", "tag is both included and excluded", tags=conflict)

        try:
            store = index.store(name)
        except CorpusUnavailable as exc:
            raise QueryError("partition_unavailable", str(exc), partition=name) from exc

        num_tags = index.num_tags
        table = index.tag_to_id
        inc_ids = [table[t] for t in include]
        exc_ids = [table[t] for t in exclude]

        # 캐시 키에 epoch 를 넣는다. 계산 중 invalidate() 가 지나가면 구 코퍼스 결과가
        # 새 캐시에 되살아나 새 store 의 totalEvents 와 섞이거나, 태그 ID 매핑이 바뀐 뒤
        # 엉뚱한 태그에 counts 가 붙는다.
        epoch = index.epoch
        cache_key = (epoch, name, tuple(sorted(include)), tuple(sorted(exclude)))
        cached = self._cache_get(cache_key)
        if cached is None:
            sel = self._select(store, inc_ids, exc_ids)
            num_events = int(getattr(store, "num_events", 0) or 0)
            match_count = num_events if sel is None else int(sel.size)
            try:
                counts = self._tag_counts(store, sel, num_tags, should_abort=should_abort)
            except _Aborted:
                raise QueryError("aborted", "superseded by a newer query")
            if index.epoch == epoch:
                self._cache_put(cache_key, (counts, match_count))
        else:
            counts, match_count = cached
            num_events = int(getattr(store, "num_events", 0) or 0)

        rows = self._rank(counts, include, exclude, search)
        total = len(rows)
        page = rows[offset:offset + limit]

        return {
            "ok": True,
            "partition": name,
            "matchCount": match_count,
            "totalEvents": num_events,
            "tags": page,
            "tagTotal": total,
            "hasMore": offset + len(page) < total,
            "warnings": (
                {"unknownExclude": unknown_exclude} if unknown_exclude else {}
            ),
        }

    def _rank(
        self,
        counts: Any,
        include: Iterable[str],
        exclude: Iterable[str],
        search: str,
    ) -> list[dict[str, Any]]:
        """빈도 내림차순 + 태그 오름차순.

        tie-break 가 계약에 없으면 페이지네이션 순서가 비결정적이 된다.
        """
        id_to_tag = self._index.id_to_tag
        skip = set(include) | set(exclude)
        nonzero = np.nonzero(counts)[0]
        rows: list[tuple[int, str]] = []
        for tag_id in nonzero.tolist():
            tag = id_to_tag.get(tag_id)
            if not tag or tag in skip:
                continue
            if search and search not in tag:
                continue
            rows.append((int(counts[tag_id]), tag))
        rows.sort(key=lambda item: (-item[0], item[1]))
        return [{"tag": tag, "count": count} for count, tag in rows]

    # ------------------------------------------------------------------
    # 결과 캐시
    # ------------------------------------------------------------------

    def _cache_get(self, key: tuple) -> tuple[Any, int] | None:
        with self._cache_lock:
            value = self._cache.get(key)
            if value is not None:
                self._cache.move_to_end(key)
            return value

    def _cache_put(self, key: tuple, value: tuple[Any, int]) -> None:
        with self._cache_lock:
            self._cache[key] = value
            self._cache.move_to_end(key)
            while len(self._cache) > self._cache_entries:
                self._cache.popitem(last=False)


class _Aborted(Exception):
    """내부 신호: 더 새로운 질의가 들어와 중단."""
