"""Event Corpus (.tgp) 접근의 단일 소유자.

``data/quick_search/`` 아래의 파티션 파일과 ``metadata.tgpm`` 을 읽는 유일한 계층이다.
파티션 파일 포맷 자체는 ``core/event_preset/quick_search_data.py`` (Dev0714 원본과 동일 blob)
가 다루고, 이 모듈은 그 위에서 경로 해석 · 검증 · 캐시 · 화이트리스트를 책임진다.

설계 근거는 ``INTERACTIVE_QUICKFILTER_PLAN.md`` 참조. 요점만:

- 경로는 ``runtime_paths.data_dir`` -> ``repo_root/data`` 순으로 찾되, **quick_search 디렉터리와
  유효한 metadata 를 함께 가진 첫 루트**를 택한다. 빈 runtime 디렉터리가 정상 repo 데이터를
  가리는 것을 막는다.
- 파티션명은 ``{rating}_{person}`` 화이트리스트 조립만 허용한다. 사용자 문자열이 경로에
  들어가지 않는다.
- 캐시는 엔트리 수가 아니라 **보유 배열의 바이트 합**으로 제한한다. 파티션 하나가 수십~수백 MB다.
- 로드 시 CSR 불변식을 검증한다. 중단된 다운로드/손상 파일은 ``corrupt`` 로 분류하고 예외를
  밖으로 던지지 않는다.
"""

from __future__ import annotations

import lzma
import pickle
import struct
import threading
from pathlib import Path
from typing import Any, Iterable, Sequence

try:  # pragma: no cover - numpy 는 quick_search_data 와 동일한 필수 의존성
    import numpy as np
    HAS_NUMPY = True
except ImportError:  # pragma: no cover
    np = None  # type: ignore[assignment]
    HAS_NUMPY = False

try:
    from core.event_preset.engines import PERSON_PARTITION_ORDER, PERSON_TAG_MAP
except Exception:  # pragma: no cover - engines 는 pandas 를 끌어온다. 테스트 격리용 폴백.
    PERSON_PARTITION_ORDER = [
        "1girl_solo", "1girl", "1girl_1boy", "1girl_multiple_boys",
        "2girls", "multiple_girls", "1boy_solo", "1boy",
        "1boy_multiple_girls", "2boys", "multiple_boys",
        "multiple_girls_multiple_boys", "other",
    ]
    PERSON_TAG_MAP = {
        "1girl_solo": ["1girl", "solo"],
        "1boy_solo": ["1boy", "solo"],
        "1girl_1boy": ["1girl", "1boy"],
        "2girls": ["2girls"],
        "2boys": ["2boys"],
        "1girl_multiple_boys": ["1girl", "multiple boys"],
        "1boy_multiple_girls": ["1boy", "multiple girls"],
        "multiple_girls": ["multiple girls"],
        "multiple_boys": ["multiple boys"],
        "multiple_girls_multiple_boys": ["multiple girls", "multiple boys"],
        "1girl": ["1girl"],
        "1boy": ["1boy"],
        "other": [],
    }


RATING_IDS = ("g", "s", "q", "e")
PERSON_IDS = tuple(PERSON_PARTITION_ORDER)

_TGPS_MAGIC = b"TGPS"
_TGP_MAGIC = b"TGP1"

# 구버전 판정. Dev0714 quick_search_block.py 및 engines.py 와 동일한 임계값.
MIN_TAG_COUNT = 13053

# 손상/악의적 파일 방어용 상한. 실제 자산은 이보다 한참 작다.
MAX_METADATA_BYTES = 64 * 1024 * 1024
MAX_PARTITION_BYTES = 768 * 1024 * 1024

# CSR 의 태그 인덱스는 uint16 이다(quick_search_data.py:52). 따라서 파티션이 참조할 수 있는
# 태그 ID 는 구조적으로 0..65535 다. metadata 가 그보다 큰 ID 를 담고 있으면 그 태그는 어떤
# 파티션에서도 등장할 수 없고, num_tags = max(id)+1 로 잡으면 집계 배열이 폭발한다
# (예: id 1e9 하나로 np.zeros(int64) 8GB). 그래서 범위를 벗어난 metadata 는 corrupt 로 본다.
MAX_TAG_ID = 65535

# 파티션 캐시 예산(바이트). 파티션 하나가 CSR + inverted index 를 동시에 보유한다.
DEFAULT_CACHE_BUDGET = 640 * 1024 * 1024


def normalize_tag(tag: Any) -> str:
    """태그 정규화. tag_to_id 키와 동일한 형태로 맞춘다."""
    return " ".join(str(tag or "").replace("_", " ").strip().lower().split())


def partition_name(rating: Any, person: Any) -> str:
    """화이트리스트 조립. 허용되지 않은 값이면 ValueError.

    사용자 입력이 경로 조각으로 흘러들어가지 않도록 여기서만 파티션명을 만든다.
    """
    r = str(rating or "").strip().lower()
    p = str(person or "").strip().lower()
    if r not in RATING_IDS:
        raise ValueError(f"unknown rating: {rating!r}")
    if p not in PERSON_IDS:
        raise ValueError(f"unknown person: {person!r}")
    return f"{r}_{p}"


_VALID_PARTITION_NAMES = frozenset(
    f"{r}_{p}" for r in RATING_IDS for p in PERSON_IDS
)


def seed_tags(person: Any) -> list[str]:
    """인원 카테고리의 기본 포함 태그.

    SSOT 는 PERSON_TAG_MAP(future02) 이다. Dev0714 의 PERSON_AUTO_TAGS 로 되돌리지 않는다 —
    preset_composer_service 가 이미 이 값으로 프롬프트를 조립하므로, 갈라지면 같은 인원
    설정에서 프리셋과 Interactive 의 결과가 달라진다.
    """
    p = str(person or "").strip().lower()
    return [normalize_tag(t) for t in PERSON_TAG_MAP.get(p, [])]


class CorpusUnavailable(RuntimeError):
    """데이터가 없거나 손상되어 질의할 수 없음."""


class _CacheEntry:
    __slots__ = ("store", "nbytes")

    def __init__(self, store: Any, nbytes: int) -> None:
        self.store = store
        self.nbytes = nbytes


class EventCorpusIndex:
    """.tgp 파티션 + metadata 접근자."""

    def __init__(
        self,
        data_roots: Sequence[Path | str],
        *,
        cache_budget: int = DEFAULT_CACHE_BUDGET,
    ) -> None:
        self._data_roots = [Path(r) for r in data_roots if r]
        self._cache_budget = int(cache_budget)
        self._lock = threading.RLock()
        self._load_locks: dict[str, threading.Lock] = {}
        self._cache: dict[str, _CacheEntry] = {}
        self._lru: list[str] = []
        self._root: Path | None = None
        self._tag_to_id: dict[str, int] = {}
        self._id_to_tag: dict[int, str] = {}
        self._num_tags = 0
        self._meta_error = ""
        self._meta_loaded = False
        # invalidate() 마다 증가. 진행 중이던 질의가 자기 epoch 를 들고 있다가 결과를 캐시할 때
        # 대조한다. 없으면 다운로드/마이그레이션 직후 구 코퍼스의 counts 가 새 캐시에 되살아나
        # 새 store 의 totalEvents 와 섞이거나, 태그 ID 매핑이 바뀐 뒤 엉뚱한 태그에 붙는다.
        self._epoch = 0
        # store() 로드에 실패한 파티션. status() 가 파일 크기만 보고 ready 라 우기지 않도록.
        self._corrupt: set[str] = set()

    @property
    def epoch(self) -> int:
        with self._lock:
            return self._epoch

    # ------------------------------------------------------------------
    # 경로
    # ------------------------------------------------------------------

    @property
    def root(self) -> Path | None:
        """metadata 가 실제로 **로드되는** 첫 data root.

        파일 존재/크기만 보면 안 된다 — runtime 루트에 bad-magic/truncated/stale metadata 가
        있고 repo 루트에 정상 코퍼스가 있을 때, 앞의 것으로 고정돼 기능 전체가 죽는다.
        """
        self._ensure_metadata()
        with self._lock:
            return self._root

    def _candidate_roots(self) -> list[Path]:
        out: list[Path] = []
        for base in self._data_roots:
            candidate = Path(base) / "quick_search"
            if candidate.is_dir():
                out.append(candidate)
        return out

    # ------------------------------------------------------------------
    # 메타데이터
    # ------------------------------------------------------------------

    def _ensure_metadata(self) -> bool:
        with self._lock:
            if self._meta_loaded:
                return bool(self._tag_to_id)
            self._meta_loaded = True
            candidates = self._candidate_roots()
            if not candidates:
                self._root = None
                self._meta_error = "quick_search directory not found"
                return False
            # status 보고용 폴백: 유효한 루트가 없으면 존재하는 첫 디렉터리를 가리킨다.
            self._root = candidates[0]
            last_error = ""
            for candidate in candidates:
                if self._load_metadata_from(candidate / "metadata.tgpm"):
                    self._root = candidate
                    return True
                last_error = self._meta_error
            self._meta_error = last_error or "metadata.tgpm not found"
            return False

    def _load_metadata_from(self, path: Path) -> bool:
        """단일 metadata 파일 시도. 성공 시 태그 매핑을 채운다."""
        if not path.is_file():
            self._meta_error = "metadata.tgpm not found"
            return False
        try:
            size = path.stat().st_size
            if size > MAX_METADATA_BYTES:
                self._meta_error = f"metadata.tgpm too large ({size} bytes)"
                return False
            with open(path, "rb") as handle:
                if handle.read(4) != _TGPS_MAGIC:
                    self._meta_error = "metadata.tgpm magic mismatch"
                    return False
                _version = struct.unpack("<H", handle.read(2))[0]
                clen = struct.unpack("<I", handle.read(4))[0]
                if clen <= 0 or clen > MAX_METADATA_BYTES:
                    self._meta_error = "metadata.tgpm declares invalid payload length"
                    return False
                payload = handle.read(clen)
            if len(payload) != clen:
                self._meta_error = "metadata.tgpm truncated"
                return False
            data = pickle.loads(lzma.decompress(payload))
        except Exception as exc:
            self._meta_error = f"metadata.tgpm load failed: {exc}"
            return False

        raw_t2i = data.get("tag_to_id") if isinstance(data, dict) else None
        raw_i2t = data.get("id_to_tag") if isinstance(data, dict) else None
        if not isinstance(raw_t2i, dict) or not raw_t2i:
            self._meta_error = "metadata.tgpm has no tag_to_id"
            return False
        if len(raw_t2i) <= MIN_TAG_COUNT:
            self._meta_error = (
                f"stale corpus: {len(raw_t2i)} tags (needs > {MIN_TAG_COUNT})"
            )
            return False

        tag_to_id = {normalize_tag(k): int(v) for k, v in raw_t2i.items()}
        if isinstance(raw_i2t, dict) and raw_i2t:
            id_to_tag = {int(k): normalize_tag(v) for k, v in raw_i2t.items()}
        else:
            id_to_tag = {v: k for k, v in tag_to_id.items()}

        # ID 범위 검증. 음수이거나 uint16 밖이면 CSR 이 참조할 수 없는 값이므로 corrupt.
        all_ids = list(tag_to_id.values()) + list(id_to_tag.keys())
        if all_ids:
            lo, hi = min(all_ids), max(all_ids)
            if lo < 0 or hi > MAX_TAG_ID:
                self._meta_error = (
                    f"metadata tag id out of range: [{lo}, {hi}] "
                    f"(allowed 0..{MAX_TAG_ID})"
                )
                return False

        self._tag_to_id = tag_to_id
        self._id_to_tag = id_to_tag
        # num_tags 는 사전 길이가 아니라 **최대 ID + 1** 이다.
        # tag id 가 조밀하지 않으면 np.bincount(minlength=len(map)) 결과가 더 길어져
        # 누산이 깨진다(설계안 2.4 의 v1 버그). 위 범위 검증 덕에 상한은 65536 이다.
        self._num_tags = (max(self._id_to_tag) + 1) if self._id_to_tag else 0
        self._meta_error = ""
        return True

    @property
    def tag_to_id(self) -> dict[str, int]:
        self._ensure_metadata()
        return self._tag_to_id

    @property
    def id_to_tag(self) -> dict[int, str]:
        self._ensure_metadata()
        return self._id_to_tag

    @property
    def num_tags(self) -> int:
        self._ensure_metadata()
        return self._num_tags

    def has_tag(self, tag: Any) -> bool:
        return normalize_tag(tag) in self.tag_to_id

    def resolve_tags(self, tags: Iterable[Any]) -> tuple[list[str], list[str]]:
        """(known, unknown) 정규화된 태그로 분리. 순서·중복 제거 유지."""
        known: list[str] = []
        unknown: list[str] = []
        seen: set[str] = set()
        table = self.tag_to_id
        for raw in tags or []:
            tag = normalize_tag(raw)
            if not tag or tag in seen:
                continue
            seen.add(tag)
            (known if tag in table else unknown).append(tag)
        return known, unknown

    # ------------------------------------------------------------------
    # 상태
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """파티션별 상태. 전역 ready/임의 임계값(.tgp >= 10개) 을 쓰지 않는다."""
        root = self.root
        meta_ok = self._ensure_metadata()
        partitions: dict[str, str] = {}
        available = 0
        if root is not None:
            for rating in RATING_IDS:
                for person in PERSON_IDS:
                    name = f"{rating}_{person}"
                    path = root / f"{name}.tgp"
                    if not path.is_file():
                        partitions[name] = "missing"
                        continue
                    if name in self._corrupt:
                        # 이전 store() 로드가 실패한 파티션은 기억한다. 기억하지 않으면 질의는
                        # 계속 실패하는데 status 는 매번 ready 라고 우긴다.
                        partitions[name] = "corrupt"
                        continue
                    try:
                        size = path.stat().st_size
                    except OSError:
                        partitions[name] = "corrupt"
                        continue
                    if size <= 16 or size > MAX_PARTITION_BYTES:
                        partitions[name] = "corrupt"
                        continue
                    # 크기만 보지 않고 매직도 확인한다(헤더 10바이트만 읽으므로 저렴).
                    try:
                        with open(path, "rb") as handle:
                            if handle.read(4) != _TGP_MAGIC:
                                partitions[name] = "corrupt"
                                continue
                    except OSError:
                        partitions[name] = "corrupt"
                        continue
                    partitions[name] = "ready"
                    available += 1

        if root is None:
            state = "missing"
        elif not meta_ok:
            state = "stale" if "stale corpus" in self._meta_error else "missing"
        elif available == 0:
            state = "missing"
        else:
            state = "ready"

        return {
            "state": state,
            "message": self._meta_error or "",
            "root": str(root) if root is not None else "",
            "tagCount": len(self._tag_to_id),
            "availablePartitions": available,
            "partitions": partitions,
            "ratings": list(RATING_IDS),
            "persons": list(PERSON_IDS),
        }

    # ------------------------------------------------------------------
    # 파티션 스토어
    # ------------------------------------------------------------------

    @staticmethod
    def _store_nbytes(store: Any) -> int:
        total = 0
        for name in ("_event_tag_indices", "_event_tag_indptr", "_event_counts"):
            arr = getattr(store, name, None)
            if arr is not None and hasattr(arr, "nbytes"):
                total += int(arr.nbytes)
        posting = getattr(store, "_tag_to_events", None)
        if isinstance(posting, dict):
            for arr in posting.values():
                if hasattr(arr, "nbytes"):
                    total += int(arr.nbytes)
        return total

    @staticmethod
    def _validate_csr(store: Any, num_tags: int) -> str:
        """CSR 불변식 검증. 문제가 없으면 빈 문자열."""
        if not HAS_NUMPY:
            return "numpy unavailable"
        indptr = getattr(store, "_event_tag_indptr", None)
        indices = getattr(store, "_event_tag_indices", None)
        num_events = int(getattr(store, "num_events", 0) or 0)
        if indptr is None or indices is None:
            return "missing CSR arrays"
        if indptr.size != num_events + 1:
            return f"indptr size {indptr.size} != num_events+1 {num_events + 1}"
        if indptr.size and int(indptr[0]) != 0:
            return "indptr does not start at 0"
        if indptr.size and int(indptr[-1]) != int(indices.size):
            return f"indptr tail {int(indptr[-1])} != indices size {int(indices.size)}"
        if indptr.size > 1 and bool(np.any(np.diff(indptr) < 0)):
            return "indptr is not monotonic"
        if indices.size and num_tags and int(indices.max()) >= num_tags:
            return f"tag id {int(indices.max())} out of range (num_tags={num_tags})"

        # 포스팅 리스트 검증. _select 가 intersect1d/setdiff1d 에 assume_unique=True 를 쓰므로
        # 정렬·유일이 깨지면 **예외 없이 거짓 결과**가 나온다. 실측:
        #   np.intersect1d([0,0,1], [2,3], assume_unique=True) -> [0]   (실제 교집합은 공집합)
        # quick_search_data.py 의 로더는 파일 바이트를 그대로 frombuffer 할 뿐 아무것도 보장하지
        # 않는다. 그래서 여기서 한 번 검사한다. 비용은 O(nnz) 로 CSR 자체와 같은 차수이고,
        # 방금 압축 해제한 직후라 캐시에 올라와 있다.
        postings = getattr(store, "_tag_to_events", None)
        if not isinstance(postings, dict):
            return "missing postings index"
        for tag_id, arr in postings.items():
            if arr is None or getattr(arr, "size", 0) == 0:
                continue
            if arr.dtype != np.int32:
                return f"postings dtype {arr.dtype} for tag {tag_id}"
            if arr.size > 1 and bool(np.any(np.diff(arr) <= 0)):
                return f"postings not sorted-unique for tag {tag_id}"
            if int(arr[0]) < 0 or int(arr[-1]) >= num_events:
                return f"postings event id out of range for tag {tag_id}"
        return ""

    def _evict_locked(self) -> None:
        # 최소 1개는 항상 상주시킨다. 예산이 파티션 하나보다 작으면(설정 오류/거대 파티션)
        # 방금 로드한 엔트리까지 방출돼 질의마다 압축 해제를 반복하게 된다.
        #
        # 주의: 방출은 캐시에서 빼는 것일 뿐, 진행 중인 질의가 잡고 있는 store 는 지역 참조로
        # 살아 있다. 따라서 예산은 "상주 하한"이 아니라 "캐시 상한"이다. 활성 질의가 여러
        # 파티션을 동시에 쥐면 순간 사용량은 예산을 넘을 수 있다(refcount 를 도입하지 않는 한
        # 피할 수 없고, 도입하면 호출자가 release 해야 하는 API 가 된다).
        while len(self._cache) > 1 and self._cached_bytes_locked() > self._cache_budget:
            name = self._lru.pop(0)
            self._cache.pop(name, None)

    def _cached_bytes_locked(self) -> int:
        return sum(entry.nbytes for entry in self._cache.values())

    def store(self, name: str) -> Any:
        """파티션 스토어. 없거나 손상이면 CorpusUnavailable.

        ``name`` 은 반드시 ``partition_name()`` 이 만든 값이어야 한다. 계층 계약을 Index 가
        스스로 지키도록 여기서도 형식을 확인한다(서비스만 믿지 않는다 — 경로 조립의 단일
        소유자라고 문서에 써 놓았으므로).
        """
        if name not in _VALID_PARTITION_NAMES:
            raise CorpusUnavailable(f"invalid partition name: {name!r}")
        with self._lock:
            entry = self._cache.get(name)
            if entry is not None:
                self._touch_locked(name)
                return entry.store
            load_lock = self._load_locks.setdefault(name, threading.Lock())

        # single-flight: 같은 파티션을 동시에 두 번 압축 해제하지 않는다.
        with load_lock:
            with self._lock:
                entry = self._cache.get(name)
                if entry is not None:
                    self._touch_locked(name)
                    return entry.store
                epoch_at_start = self._epoch

            root = self.root
            if root is None:
                raise CorpusUnavailable("event corpus data is not installed")
            path = root / f"{name}.tgp"
            if not path.is_file():
                raise CorpusUnavailable(f"partition not available: {name}")
            try:
                if path.stat().st_size > MAX_PARTITION_BYTES:
                    raise CorpusUnavailable(f"partition too large: {name}")
            except OSError as exc:
                raise CorpusUnavailable(f"partition unreadable: {name} ({exc})") from exc

            from core.event_preset.quick_search_data import SinglePartitionStore

            store = SinglePartitionStore.load(path)
            if not getattr(store, "_loaded", False):
                with self._lock:
                    self._corrupt.add(name)
                raise CorpusUnavailable(f"partition failed to load: {name}")
            problem = self._validate_csr(store, self.num_tags)
            if problem:
                with self._lock:
                    self._corrupt.add(name)
                raise CorpusUnavailable(f"partition corrupt: {name} ({problem})")

            nbytes = self._store_nbytes(store)
            with self._lock:
                # 로드 중 invalidate() 가 지나갔으면 이 store 는 구 코퍼스의 것이다. 캐시에
                # 넣지 않는다(호출자에게는 반환하되, 서비스가 epoch 로 결과를 버린다).
                if epoch_at_start == self._epoch:
                    self._cache[name] = _CacheEntry(store, nbytes)
                    self._lru.append(name)
                    self._evict_locked()
            return store

    def _touch_locked(self, name: str) -> None:
        try:
            self._lru.remove(name)
        except ValueError:
            pass
        self._lru.append(name)

    def csr_arrays(self, store: Any) -> tuple[Any, Any, int]:
        """CSR 배열 접근의 유일한 지점.

        SinglePartitionStore 는 밑줄 접두 속성만 노출한다. 밑줄 접근을 이 메서드 하나로
        모아, 나중에 포맷이 바뀌어도 수정 지점이 하나가 되게 한다.
        """
        return (
            store._event_tag_indptr,
            store._event_tag_indices,
            int(getattr(store, "num_events", 0) or 0),
        )

    def postings(self, store: Any, tag_id: int) -> Any:
        """태그 하나의 이벤트 포스팅 리스트(정렬된 int32 ndarray)."""
        return store._tag_to_events.get(int(tag_id))

    def invalidate(self) -> None:
        """마이그레이션/다운로드 이후 호출. 경로·메타데이터·캐시를 모두 버린다."""
        with self._lock:
            self._epoch += 1
            self._cache.clear()
            self._lru.clear()
            # _load_locks 는 지우지 않는다. 진행 중인 로더가 들고 있는 Lock 객체를 버리면
            # 새 로더가 다른 Lock 을 만들어 single-flight 가 깨진다(같은 파티션 동시 해제).
            # 파티션 이름은 화이트리스트라 최대 52개, 누적해도 무해하다.
            self._root = None
            self._corrupt.clear()
            self._tag_to_id = {}
            self._id_to_tag = {}
            self._num_tags = 0
            self._meta_error = ""
            self._meta_loaded = False
