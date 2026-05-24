import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd


def _has_prompt_text(value) -> bool:
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    text = str(value or "").strip()
    return bool(text) and text.lower() not in {"nan", "none", "null"}


def _normalize_rating(value) -> str:
    return str(value or "").strip().lower()


@dataclass
class _SearchResultBucket:
    bucket_id: int
    df: pd.DataFrame
    consumed_indices: set[int] = field(default_factory=set)
    valid_prompt_mask_cache: Optional[pd.Series] = None
    random_pools_by_rating: Optional[dict[Optional[str], list[int]]] = None
    rating_counts_cache: Optional[dict[str, int]] = None

    def __post_init__(self):
        self.df = self.df.reset_index(drop=True)

    def invalidate_caches(self):
        self.valid_prompt_mask_cache = None
        self.random_pools_by_rating = None
        self.rating_counts_cache = None

    def reset_consumed(self):
        self.consumed_indices.clear()

    def append_dataframe(self, new_df: pd.DataFrame):
        if new_df is None or new_df.empty:
            return
        base_df = self.remaining_dataframe()
        self.df = pd.concat([base_df, new_df.reset_index(drop=True)], ignore_index=True)
        self.reset_consumed()
        self.invalidate_caches()

    def has_rating_column(self) -> bool:
        return "rating" in self.df.columns

    def remaining_count(self) -> int:
        if not self.consumed_indices:
            return len(self.df)
        consumed_present = sum(1 for index in self.consumed_indices if index in self.df.index)
        return max(0, len(self.df) - consumed_present)

    def is_empty(self) -> bool:
        return self.remaining_count() <= 0

    def remaining_dataframe(self) -> pd.DataFrame:
        if not self.consumed_indices:
            return self.df
        return self.df.drop(index=list(self.consumed_indices), errors="ignore")

    def valid_prompt_mask(self) -> pd.Series:
        if self.valid_prompt_mask_cache is not None:
            return self.valid_prompt_mask_cache
        if "general" not in self.df.columns:
            self.valid_prompt_mask_cache = pd.Series(True, index=self.df.index)
            return self.valid_prompt_mask_cache
        general = self.df["general"]
        mask = general.notna()
        text = general.astype(str).str.strip()
        mask &= text.ne("")
        mask &= ~text.str.lower().isin({"nan", "none", "null"})
        self.valid_prompt_mask_cache = mask
        return mask

    def ensure_random_pools(self):
        if self.random_pools_by_rating is not None:
            return

        self.random_pools_by_rating = {}
        if self.df.empty:
            return

        mask = self.valid_prompt_mask()
        if self.consumed_indices:
            mask = mask & ~self.df.index.isin(self.consumed_indices)
        if not bool(mask.any()):
            return

        if "rating" not in self.df.columns:
            self.random_pools_by_rating[None] = list(self.df.index[mask])
            return

        ratings = self.df.loc[mask, "rating"].astype(str).str.strip().str.lower()
        for rating, indices in ratings.groupby(ratings, sort=False).groups.items():
            self.random_pools_by_rating[str(rating)] = list(indices)

    def row_matches_random_filter(self, index: int, active_rating_keys: Optional[set[str]]) -> bool:
        if index in self.consumed_indices:
            return False
        if index not in self.df.index:
            return False
        row = self.df.loc[index]
        if active_rating_keys is not None and _normalize_rating(row.get("rating")) not in active_rating_keys:
            return False
        if "general" in self.df.columns and not _has_prompt_text(row.get("general")):
            return False
        return True

    def candidate_bucket_keys(self, active_rating_keys: Optional[set[str]]) -> list[Optional[str]]:
        self.ensure_random_pools()
        if not self.random_pools_by_rating:
            return []
        if active_rating_keys is None:
            return list(self.random_pools_by_rating.keys())
        return [rating for rating in active_rating_keys if rating in self.random_pools_by_rating]

    def pop_candidate_index(self, bucket_keys: list[Optional[str]]) -> Optional[int]:
        if not self.random_pools_by_rating:
            return None

        while True:
            pools = [
                self.random_pools_by_rating[key]
                for key in bucket_keys
                if key in self.random_pools_by_rating and self.random_pools_by_rating[key]
            ]
            total = sum(len(pool) for pool in pools)
            if total <= 0:
                return None

            target = random.randrange(total)
            for pool in pools:
                if target >= len(pool):
                    target -= len(pool)
                    continue
                index = pool[target]
                pool[target] = pool[-1]
                pool.pop()
                return index

    def probe_random_index(self, active_rating_keys: Optional[set[str]], attempts: int = 64) -> Optional[int]:
        if self.df.empty:
            return None
        index_values = self.df.index
        for _ in range(min(attempts, len(index_values))):
            index = index_values[random.randrange(len(index_values))]
            if self.row_matches_random_filter(index, active_rating_keys):
                return index
        return None

    def get_count_by_rating(self) -> dict[str, int]:
        if self.is_empty() or "rating" not in self.df.columns:
            return {r: 0 for r in "gsqe"}
        if self.rating_counts_cache is not None:
            return dict(self.rating_counts_cache)
        ratings = self.remaining_dataframe()["rating"].astype(str).str.strip().str.lower()
        counts = ratings.value_counts()
        self.rating_counts_cache = {r: int(counts.get(r, 0)) for r in "gsqe"}
        return dict(self.rating_counts_cache)

    def get_filtered_count(self, active_rating_keys: Optional[set[str]]) -> int:
        if self.is_empty():
            return 0
        if active_rating_keys is None or "rating" not in self.df.columns:
            return self.remaining_count()
        counts = self.get_count_by_rating()
        return int(sum(counts.get(rating, 0) for rating in active_rating_keys))

    def pop_random_row(self, active_rating_keys: Optional[set[str]]) -> Optional[pd.Series]:
        if self.is_empty():
            return None

        random_index = self.probe_random_index(active_rating_keys)
        if random_index is None:
            bucket_keys = self.candidate_bucket_keys(active_rating_keys)
            while bucket_keys:
                candidate_index = self.pop_candidate_index(bucket_keys)
                if candidate_index is None:
                    break
                if self.row_matches_random_filter(candidate_index, active_rating_keys):
                    random_index = candidate_index
                    break

        if random_index is None:
            return None

        popped_row = self.df.loc[random_index].copy()
        self.consumed_indices.add(random_index)
        if self.rating_counts_cache is not None and "rating" in popped_row:
            rating = _normalize_rating(popped_row.get("rating"))
            if rating in self.rating_counts_cache:
                self.rating_counts_cache[rating] = max(0, self.rating_counts_cache[rating] - 1)
        return popped_row

    def pop_row_at_index(self, index: int) -> Optional[pd.Series]:
        if index in self.consumed_indices or index not in self.df.index:
            return None
        popped_row = self.df.loc[index].copy()
        self.consumed_indices.add(index)
        if self.rating_counts_cache is not None and "rating" in popped_row:
            rating = _normalize_rating(popped_row.get("rating"))
            if rating in self.rating_counts_cache:
                self.rating_counts_cache[rating] = max(0, self.rating_counts_cache[rating] - 1)
        return popped_row


class SearchResultModel:
    """검색 결과를 래핑하고 관리하는 데이터 모델 클래스"""

    _bucket_starts_cache: Optional[list[int]] = None
    _bucket_starts_array_cache: Optional[np.ndarray] = None

    def __init__(self, dataframe: Optional[pd.DataFrame] = None):
        self._buckets: dict[int, _SearchResultBucket] = {}
        self._bucket_order: list[int] = []
        self._rating_counts_cache: Optional[dict[str, int]] = None
        self._materialized_current = False
        self.df = pd.DataFrame()
        if dataframe is not None:
            self.set_dataframe(dataframe)

    @classmethod
    def _load_bucket_starts(cls) -> list[int]:
        if cls._bucket_starts_cache is not None:
            return cls._bucket_starts_cache

        tags_dir = Path("data") / "tags"
        ranges: list[tuple[int, int]] = []
        try:
            import pyarrow.parquet as pq

            for path in tags_dir.glob("tags_*.parquet"):
                match = re.match(r"tags_(\d+)\.parquet$", path.name)
                if not match:
                    continue
                bucket_id = int(match.group(1))
                parquet_file = pq.ParquetFile(path)
                id_column = parquet_file.schema_arrow.get_field_index("id")
                if id_column < 0:
                    continue
                minima = []
                for row_group_index in range(parquet_file.metadata.num_row_groups):
                    stats = parquet_file.metadata.row_group(row_group_index).column(id_column).statistics
                    if stats is not None and stats.min is not None:
                        minima.append(int(stats.min))
                if minima:
                    ranges.append((bucket_id, min(minima)))
        except Exception:
            ranges = []

        ranges.sort()
        cls._bucket_starts_cache = [start for _, start in ranges]
        cls._bucket_starts_array_cache = (
            np.asarray(cls._bucket_starts_cache, dtype=np.int64)
            if cls._bucket_starts_cache
            else None
        )
        return cls._bucket_starts_cache

    @classmethod
    def _bucket_starts_array(cls) -> Optional[np.ndarray]:
        if cls._bucket_starts_array_cache is None:
            cls._load_bucket_starts()
        return cls._bucket_starts_array_cache

    @classmethod
    def _bucket_id_for_int(cls, value: int) -> int:
        starts = cls._bucket_starts_array()
        if starts is None or len(starts) == 0:
            return 0
        bucket_id = int(np.searchsorted(starts, value, side="right") - 1)
        return max(0, min(bucket_id, len(starts) - 1))

    @classmethod
    def _bucket_ids_for_frame(cls, dataframe: pd.DataFrame) -> Optional[np.ndarray]:
        if "id" not in dataframe.columns or dataframe.empty:
            return None

        starts = cls._bucket_starts_array()
        if starts is None or len(starts) == 0:
            return None

        ids = pd.to_numeric(dataframe["id"], errors="coerce")
        valid_mask = ids.notna().to_numpy()
        bucket_ids = np.zeros(len(dataframe), dtype=np.int16)
        if valid_mask.any():
            values = ids[valid_mask].to_numpy(dtype=np.int64, copy=False)
            bucket_ids[valid_mask] = np.searchsorted(starts, values, side="right") - 1
            np.clip(bucket_ids, 0, len(starts) - 1, out=bucket_ids)
        return bucket_ids

    @classmethod
    def _iter_bucketed_frames(cls, dataframe: pd.DataFrame):
        frame = dataframe.reset_index(drop=True)
        bucket_ids = cls._bucket_ids_for_frame(frame)
        if bucket_ids is None:
            yield 0, frame
            return

        if len(bucket_ids) == 0:
            return

        first_bucket = int(bucket_ids[0])
        if bool(np.all(bucket_ids == first_bucket)):
            yield first_bucket, frame
            return

        bucket_series = pd.Series(bucket_ids, index=frame.index)
        for bucket_id in pd.unique(bucket_ids):
            chunk = frame.loc[bucket_series == bucket_id].reset_index(drop=True)
            if not chunk.empty:
                yield int(bucket_id), chunk

    def _invalidate_caches(self):
        self._rating_counts_cache = None
        for bucket in self._buckets.values():
            bucket.invalidate_caches()

    def _mark_bucket_data_changed(self):
        self._rating_counts_cache = None
        self._materialized_current = False
        if len(self._buckets) != 1:
            self.df = pd.DataFrame()

    def _refresh_legacy_df_pointer(self):
        if len(self._buckets) == 1:
            bucket = self._buckets[self._bucket_order[0]]
            if not bucket.consumed_indices:
                self.df = bucket.df
                self._materialized_current = True
                return
        self.df = pd.DataFrame()
        self._materialized_current = False

    def _remaining_count(self) -> int:
        return sum(bucket.remaining_count() for bucket in self._buckets.values())

    def _remaining_dataframe(self) -> pd.DataFrame:
        if not self._buckets:
            return pd.DataFrame()

        frames = [
            self._buckets[bucket_id].remaining_dataframe()
            for bucket_id in self._bucket_order
            if bucket_id in self._buckets and not self._buckets[bucket_id].is_empty()
        ]
        if not frames:
            return pd.DataFrame()
        if len(frames) == 1:
            return frames[0]
        return pd.concat(frames, ignore_index=True)

    def _has_rating_column(self) -> bool:
        return any(bucket.has_rating_column() for bucket in self._buckets.values())

    def _active_rating_keys(self, active_ratings: set = None) -> Optional[set[str]]:
        if not active_ratings or not self._has_rating_column():
            return None
        return {
            rating for rating in (_normalize_rating(value) for value in active_ratings)
            if rating
        }

    def prime_random_cache(self) -> None:
        """랜덤 프롬프트에 자주 함께 표시되는 카운트 캐시만 준비합니다."""
        if self.is_empty():
            return
        self.get_count_by_rating()

    def append_dataframe(self, new_df: pd.DataFrame):
        """기존 결과에 새로운 데이터프레임을 추가합니다."""
        if new_df is None or new_df.empty:
            return
        for bucket_id, bucket_df in self._iter_bucketed_frames(new_df):
            bucket = self._buckets.get(bucket_id)
            if bucket is None:
                self._buckets[bucket_id] = _SearchResultBucket(bucket_id, bucket_df)
                self._bucket_order.append(bucket_id)
            else:
                bucket.append_dataframe(bucket_df)
        self._rating_counts_cache = None
        self._refresh_legacy_df_pointer()

    def set_dataframe(self, new_df: pd.DataFrame):
        """기존 데이터프레임을 안전하게 제거하고 새로운 데이터프레임으로 교체합니다."""
        import gc

        if hasattr(self, "df") and self.df is not None:
            try:
                self.df.drop(self.df.index, inplace=True)
            except Exception:
                pass
            del self.df
            gc.collect()

        self._buckets = {}
        self._bucket_order = []
        self._rating_counts_cache = None
        self._materialized_current = False
        self.df = pd.DataFrame()
        if new_df is not None and not new_df.empty:
            self.append_dataframe(new_df)

    def get_dataframe(self) -> pd.DataFrame:
        """결과 데이터프레임을 반환합니다."""
        # 호출자가 반환된 DataFrame을 직접 수정하는 기존 경로가 있어 캐시를 보수적으로 폐기합니다.
        self._invalidate_caches()
        result = self._remaining_dataframe()
        if len(self._buckets) == 1:
            self.df = result
            self._materialized_current = True
        else:
            self.df = pd.DataFrame()
            self._materialized_current = False
        return result

    def get_count(self) -> int:
        """결과의 총 개수를 반환합니다."""
        return self._remaining_count()

    def is_empty(self) -> bool:
        """결과가 비어있는지 확인합니다."""
        return self.get_count() <= 0

    def get_prompt_at(self, index: int) -> Optional[Dict[str, Any]]:
        """특정 인덱스의 프롬프트 데이터를 딕셔너리 형태로 반환합니다."""
        if self.is_empty() or index < 0:
            return None
        offset = index
        for bucket_id in self._bucket_order:
            bucket = self._buckets.get(bucket_id)
            if bucket is None:
                continue
            count = bucket.remaining_count()
            if offset < count:
                return bucket.remaining_dataframe().iloc[offset].to_dict()
            offset -= count
        return None

    def get_count_by_rating(self) -> dict:
        """Rating별 row 수 반환. {'g': N, 's': N, 'q': N, 'e': N}"""
        if self.is_empty() or not self._has_rating_column():
            return {r: 0 for r in "gsqe"}
        if self._rating_counts_cache is not None:
            return dict(self._rating_counts_cache)
        counts = {r: 0 for r in "gsqe"}
        for bucket in self._buckets.values():
            bucket_counts = bucket.get_count_by_rating()
            for rating in counts:
                counts[rating] += int(bucket_counts.get(rating, 0))
        self._rating_counts_cache = counts
        return dict(counts)

    def get_filtered_count(self, active_ratings: set) -> int:
        """활성 rating에 해당하는 row 수."""
        if self.is_empty() or not self._has_rating_column():
            return 0
        if not active_ratings:
            return 0
        active_rating_keys = self._active_rating_keys(active_ratings)
        if self._rating_counts_cache is not None and active_rating_keys is not None:
            return int(sum(self._rating_counts_cache.get(rating, 0) for rating in active_rating_keys))
        return int(sum(bucket.get_filtered_count(active_rating_keys) for bucket in self._buckets.values()))

    # [신규] 무작위 행을 추출하고 제거하는 메서드
    def pop_random_row(self, active_ratings: set = None) -> Optional[pd.Series]:
        """
        데이터프레임에서 무작위로 행 하나를 선택하여 반환하고, 원본에서는 제거합니다.
        active_ratings가 주어지면 해당 rating만 대상으로 추출합니다.
        비활성 rating row는 삭제하지 않고 보존합니다.
        general 컬럼이 있으면 빈 프롬프트 row는 랜덤 생성 후보에서 제외합니다.
        """
        if self.is_empty():
            return None

        active_rating_keys = self._active_rating_keys(active_ratings)
        remaining_bucket_ids = [
            bucket_id
            for bucket_id in self._bucket_order
            if bucket_id in self._buckets and not self._buckets[bucket_id].is_empty()
        ]
        attempted: set[int] = set()

        while len(attempted) < len(remaining_bucket_ids):
            weighted_buckets = []
            total_weight = 0
            for bucket_id in remaining_bucket_ids:
                if bucket_id in attempted:
                    continue
                bucket = self._buckets[bucket_id]
                weight = bucket.get_filtered_count(active_rating_keys)
                if weight <= 0:
                    attempted.add(bucket_id)
                    continue
                total_weight += weight
                weighted_buckets.append((bucket_id, bucket, total_weight))

            if total_weight <= 0:
                return None

            target = random.randrange(total_weight)
            selected_id = None
            selected_bucket = None
            for bucket_id, bucket, cumulative_weight in weighted_buckets:
                if target < cumulative_weight:
                    selected_id = bucket_id
                    selected_bucket = bucket
                    break
            if selected_bucket is None:
                return None

            popped_row = selected_bucket.pop_random_row(active_rating_keys)
            if popped_row is not None:
                if self._rating_counts_cache is not None and "rating" in popped_row:
                    rating = _normalize_rating(popped_row.get("rating"))
                    if rating in self._rating_counts_cache:
                        self._rating_counts_cache[rating] = max(0, self._rating_counts_cache[rating] - 1)
                self._mark_bucket_data_changed()
                return popped_row

            attempted.add(selected_id)

        return None

    def pop_random_row_matching(
        self,
        active_ratings: set = None,
        row_predicate: Optional[Callable[[pd.Series], bool]] = None,
    ) -> Optional[pd.Series]:
        """임의 predicate까지 반영해 무작위 행을 선택하고 소비 처리합니다."""
        if self.is_empty():
            return None
        if row_predicate is None:
            return self.pop_random_row(active_ratings)

        active_rating_keys = self._active_rating_keys(active_ratings)
        weighted_buckets = []
        eligible_indices_by_bucket: dict[int, list[int]] = {}
        total_weight = 0

        for bucket_id in self._bucket_order:
            bucket = self._buckets.get(bucket_id)
            if bucket is None or bucket.is_empty():
                continue
            frame = bucket.remaining_dataframe()
            if frame.empty:
                continue

            filtered = frame
            if active_rating_keys is not None and "rating" in filtered.columns:
                ratings = filtered["rating"].astype(str).str.strip().str.lower()
                filtered = filtered[ratings.isin(active_rating_keys)]
            if filtered.empty:
                continue

            predicate_mask = filtered.apply(row_predicate, axis=1)
            eligible = filtered[predicate_mask]
            if eligible.empty:
                continue

            indices = list(eligible.index)
            eligible_indices_by_bucket[bucket_id] = indices
            total_weight += len(indices)
            weighted_buckets.append((bucket_id, total_weight))

        if total_weight <= 0:
            return None

        target = random.randrange(total_weight)
        selected_bucket_id = None
        previous_weight = 0
        for bucket_id, cumulative_weight in weighted_buckets:
            if target < cumulative_weight:
                selected_bucket_id = bucket_id
                target -= previous_weight
                break
            previous_weight = cumulative_weight

        if selected_bucket_id is None:
            return None

        bucket = self._buckets[selected_bucket_id]
        selected_index = eligible_indices_by_bucket[selected_bucket_id][target]
        popped_row = bucket.pop_row_at_index(selected_index)
        if popped_row is None:
            return None

        if self._rating_counts_cache is not None and "rating" in popped_row:
            rating = _normalize_rating(popped_row.get("rating"))
            if rating in self._rating_counts_cache:
                self._rating_counts_cache[rating] = max(0, self._rating_counts_cache[rating] - 1)
        self._mark_bucket_data_changed()
        return popped_row

    def deduplicate(self, subset: Optional[List[str]] = None):
        """데이터프레임의 중복된 행을 제거합니다."""
        if self.is_empty():
            return

        if subset is None:
            subset = ["general"]

        df = self.get_dataframe()
        df = df.drop_duplicates(subset=subset, keep="first").reset_index(drop=True)
        self.set_dataframe(df)
