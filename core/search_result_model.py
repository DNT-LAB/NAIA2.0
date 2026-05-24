import random
import pandas as pd
from typing import Dict, Any, Optional, List


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


class SearchResultModel:
    """검색 결과를 래핑하고 관리하는 데이터 모델 클래스"""

    def __init__(self, dataframe: Optional[pd.DataFrame] = None):
        if dataframe is None:
            self.df = pd.DataFrame()
        else:
            self.df = dataframe.reset_index(drop=True)
        self._consumed_indices: set[int] = set()
        self._valid_prompt_mask_cache: Optional[pd.Series] = None
        self._random_pools_by_rating: Optional[dict[Optional[str], list[int]]] = None
        self._rating_counts_cache: Optional[dict[str, int]] = None

    def _invalidate_caches(self):
        self._valid_prompt_mask_cache = None
        self._random_pools_by_rating = None
        self._rating_counts_cache = None

    def _reset_consumed(self):
        self._consumed_indices.clear()

    def _remaining_count(self) -> int:
        if not self._consumed_indices:
            return len(self.df)
        consumed_present = sum(1 for index in self._consumed_indices if index in self.df.index)
        return max(0, len(self.df) - consumed_present)

    def _remaining_dataframe(self) -> pd.DataFrame:
        if not self._consumed_indices:
            return self.df
        return self.df.drop(index=list(self._consumed_indices), errors='ignore')

    def _valid_prompt_mask(self) -> pd.Series:
        if self._valid_prompt_mask_cache is not None:
            return self._valid_prompt_mask_cache
        if 'general' not in self.df.columns:
            self._valid_prompt_mask_cache = pd.Series(True, index=self.df.index)
            return self._valid_prompt_mask_cache
        general = self.df['general']
        mask = general.notna()
        text = general.astype(str).str.strip()
        mask &= text.ne("")
        mask &= ~text.str.lower().isin({"nan", "none", "null"})
        self._valid_prompt_mask_cache = mask
        return mask

    def _ensure_random_pools(self):
        if self._random_pools_by_rating is not None:
            return

        self._random_pools_by_rating = {}
        if self.df.empty:
            return

        mask = self._valid_prompt_mask()
        if self._consumed_indices:
            mask = mask & ~self.df.index.isin(self._consumed_indices)
        if not bool(mask.any()):
            return

        if 'rating' not in self.df.columns:
            self._random_pools_by_rating[None] = list(self.df.index[mask])
            return

        ratings = self.df.loc[mask, 'rating'].astype(str).str.strip().str.lower()
        for rating, indices in ratings.groupby(ratings, sort=False).groups.items():
            self._random_pools_by_rating[str(rating)] = list(indices)

    def _active_rating_keys(self, active_ratings: set = None) -> Optional[set[str]]:
        if not active_ratings or 'rating' not in self.df.columns:
            return None
        return {
            rating for rating in (_normalize_rating(value) for value in active_ratings)
            if rating
        }

    def _row_matches_random_filter(self, index: int, active_rating_keys: Optional[set[str]]) -> bool:
        if index in self._consumed_indices:
            return False
        if index not in self.df.index:
            return False
        row = self.df.loc[index]
        if active_rating_keys is not None and _normalize_rating(row.get('rating')) not in active_rating_keys:
            return False
        if 'general' in self.df.columns and not _has_prompt_text(row.get('general')):
            return False
        return True

    def _candidate_bucket_keys(self, active_rating_keys: Optional[set[str]]) -> list[Optional[str]]:
        self._ensure_random_pools()
        if not self._random_pools_by_rating:
            return []
        if active_rating_keys is None:
            return list(self._random_pools_by_rating.keys())
        return [rating for rating in active_rating_keys if rating in self._random_pools_by_rating]

    def _pop_candidate_index(self, bucket_keys: list[Optional[str]]) -> Optional[int]:
        if not self._random_pools_by_rating:
            return None

        while True:
            pools = [
                self._random_pools_by_rating[key]
                for key in bucket_keys
                if key in self._random_pools_by_rating and self._random_pools_by_rating[key]
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

    def _probe_random_index(self, active_rating_keys: Optional[set[str]], attempts: int = 64) -> Optional[int]:
        if self.df.empty:
            return None
        index_values = self.df.index
        for _ in range(min(attempts, len(index_values))):
            index = index_values[random.randrange(len(index_values))]
            if self._row_matches_random_filter(index, active_rating_keys):
                return index
        return None

    def prime_random_cache(self) -> None:
        """랜덤 프롬프트에 자주 함께 표시되는 카운트 캐시만 준비합니다."""
        if self.is_empty():
            return
        self.get_count_by_rating()

    def append_dataframe(self, new_df: pd.DataFrame):
        """기존 결과에 새로운 데이터프레임을 추가합니다."""
        if new_df is None or new_df.empty:
            return
        base_df = self._remaining_dataframe()
        self.df = pd.concat([base_df, new_df], ignore_index=True)
        self._reset_consumed()
        self._invalidate_caches()
    
    def set_dataframe(self, new_df: pd.DataFrame):
        """기존 데이터프레임을 안전하게 제거하고 새로운 데이터프레임으로 교체합니다."""
        import gc
        
        # 기존 데이터프레임 메모리 해제
        if hasattr(self, 'df') and self.df is not None:
            # 기존 데이터프레임을 명시적으로 비우기
            self.df.drop(self.df.index, inplace=True)
            del self.df
            gc.collect()  # 가비지 컬렉션 강제 실행
        
        # 새로운 데이터프레임 설정
        if new_df is None:
            self.df = pd.DataFrame()
        else:
            self.df = new_df.reset_index(drop=True)
        self._reset_consumed()
        self._invalidate_caches()

    def get_dataframe(self) -> pd.DataFrame:
        """결과 데이터프레임을 반환합니다."""
        # 호출자가 반환된 DataFrame을 직접 수정하는 기존 경로가 있어 캐시를 보수적으로 폐기합니다.
        self._invalidate_caches()
        return self._remaining_dataframe()

    def get_count(self) -> int:
        """결과의 총 개수를 반환합니다."""
        return self._remaining_count()

    def is_empty(self) -> bool:
        """결과가 비어있는지 확인합니다."""
        return self.get_count() <= 0

    def get_prompt_at(self, index: int) -> Optional[Dict[str, Any]]:
        """특정 인덱스의 프롬프트 데이터를 딕셔너리 형태로 반환합니다."""
        if not self.is_empty() and 0 <= index < self.get_count():
            return self._remaining_dataframe().iloc[index].to_dict()
        return None
    
    def get_count_by_rating(self) -> dict:
        """Rating별 row 수 반환. {'g': N, 's': N, 'q': N, 'e': N}"""
        if self.is_empty() or 'rating' not in self.df.columns:
            return {r: 0 for r in 'gsqe'}
        if self._rating_counts_cache is not None:
            return dict(self._rating_counts_cache)
        counts = self._remaining_dataframe()['rating'].value_counts()
        self._rating_counts_cache = {r: int(counts.get(r, 0)) for r in 'gsqe'}
        return dict(self._rating_counts_cache)

    def get_filtered_count(self, active_ratings: set) -> int:
        """활성 rating에 해당하는 row 수."""
        if self.is_empty() or 'rating' not in self.df.columns:
            return 0
        if self._rating_counts_cache is not None:
            return int(sum(
                self._rating_counts_cache.get(_normalize_rating(rating), 0)
                for rating in active_ratings
            ))
        return int(self._remaining_dataframe()['rating'].isin(active_ratings).sum())

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
        random_index = self._probe_random_index(active_rating_keys)
        if random_index is None:
            bucket_keys = self._candidate_bucket_keys(active_rating_keys)
            while bucket_keys:
                candidate_index = self._pop_candidate_index(bucket_keys)
                if candidate_index is None:
                    break
                if self._row_matches_random_filter(candidate_index, active_rating_keys):
                    random_index = candidate_index
                    break

        if random_index is None:
            return None

        # 해당 행 데이터 추출 및 소비 처리. 대형 DataFrame에서 drop은 매번 전체 블록을 재구성하므로 지연이 큽니다.
        popped_row = self.df.loc[random_index].copy()
        self._consumed_indices.add(random_index)
        if self._rating_counts_cache is not None and 'rating' in popped_row:
            rating = _normalize_rating(popped_row.get('rating'))
            if rating in self._rating_counts_cache:
                self._rating_counts_cache[rating] = max(0, self._rating_counts_cache[rating] - 1)

        return popped_row

    def deduplicate(self, subset: Optional[List[str]] = None):
        """데이터프레임의 중복된 행을 제거합니다."""
        if self.is_empty():
            return
        
        # 기본적으로 'general' 컬럼을 기준으로 중복 제거
        if subset is None:
            subset = ['general']
            
        self.df = self._remaining_dataframe()
        self.df.drop_duplicates(subset=subset, keep='first', inplace=True)
        self.df.reset_index(drop=True, inplace=True)
        self._reset_consumed()
        self._invalidate_caches()
