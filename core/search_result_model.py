import random
import pandas as pd
from typing import Dict, Any, Iterable, Optional, List


def _has_prompt_text(value) -> bool:
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    text = str(value or "").strip()
    return bool(text) and text.lower() not in {"nan", "none", "null"}


class SearchResultModel:
    """검색 결과를 래핑하고 관리하는 데이터 모델 클래스"""

    def __init__(self, dataframe: Optional[pd.DataFrame] = None):
        if dataframe is None:
            self.df = pd.DataFrame()
        else:
            self.df = dataframe.reset_index(drop=True)
        self._candidate_indices_cache: dict[tuple[str, ...] | None, list[int]] = {}
        self._valid_prompt_mask_cache: pd.Series | None = None
        self._rating_counts_cache: dict[str, int] | None = None

    def _invalidate_caches(self):
        self._candidate_indices_cache.clear()
        self._valid_prompt_mask_cache = None
        self._rating_counts_cache = None

    def append_dataframe(self, new_df: pd.DataFrame):
        """기존 결과에 새로운 데이터프레임을 추가합니다."""
        if new_df is None or new_df.empty:
            return
        self.df = pd.concat([self.df, new_df], ignore_index=True)
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
        self._invalidate_caches()

    def get_dataframe(self) -> pd.DataFrame:
        """결과 데이터프레임을 반환합니다."""
        # Callers may mutate the returned frame directly, so cached random-pick
        # state cannot be trusted after exposing the internal dataframe.
        self._invalidate_caches()
        return self.df

    def get_count(self) -> int:
        """결과의 총 개수를 반환합니다."""
        return len(self.df)

    def is_empty(self) -> bool:
        """결과가 비어있는지 확인합니다."""
        return self.df.empty

    def get_prompt_at(self, index: int) -> Optional[Dict[str, Any]]:
        """특정 인덱스의 프롬프트 데이터를 딕셔너리 형태로 반환합니다."""
        if not self.is_empty() and 0 <= index < self.get_count():
            return self.df.iloc[index].to_dict()
        return None
    
    def get_count_by_rating(self) -> dict:
        """Rating별 row 수 반환. {'g': N, 's': N, 'q': N, 'e': N}"""
        if self.is_empty() or 'rating' not in self.df.columns:
            return {r: 0 for r in 'gsqe'}
        if self._rating_counts_cache is not None:
            return dict(self._rating_counts_cache)
        counts = self.df['rating'].value_counts()
        self._rating_counts_cache = {r: int(counts.get(r, 0)) for r in 'gsqe'}
        return dict(self._rating_counts_cache)

    def get_filtered_count(self, active_ratings: set) -> int:
        """활성 rating에 해당하는 row 수."""
        if self.is_empty() or 'rating' not in self.df.columns:
            return 0
        if self._rating_counts_cache is not None:
            return int(sum(self._rating_counts_cache.get(str(r).strip().lower(), 0) for r in active_ratings))
        return int(self.df['rating'].isin(active_ratings).sum())

    def _rating_key(self, active_ratings: set | None) -> tuple[str, ...] | None:
        if not active_ratings or 'rating' not in self.df.columns:
            return None
        return tuple(sorted({str(rating).strip().lower() for rating in active_ratings if str(rating).strip()}))

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

    def _candidate_indices(self, active_ratings: set | None) -> list[int]:
        key = self._rating_key(active_ratings)
        cached = self._candidate_indices_cache.get(key)
        if cached is not None:
            return cached

        mask = self._valid_prompt_mask()
        if key and 'rating' in self.df.columns:
            mask = mask & self.df['rating'].isin(set(key))
        indices = list(self.df.index[mask])
        self._candidate_indices_cache[key] = indices
        return indices

    def prime_random_cache(self, rating_sets: Iterable[set | tuple | list | None] = (None,)) -> None:
        """Build random-pick candidate caches before the first UI click."""
        if self.is_empty():
            return
        self.get_count_by_rating()
        for ratings in rating_sets:
            rating_set = set(ratings) if ratings else None
            self._candidate_indices(rating_set)

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

        indices = self._candidate_indices(active_ratings)
        random_index = None
        while indices:
            candidate_position = random.randrange(len(indices))
            candidate_index = indices.pop(candidate_position)
            if candidate_index in self.df.index:
                random_index = candidate_index
                break

        if random_index is None:
            return None

        # 해당 행 데이터 추출 및 원본에서 삭제
        popped_row = self.df.loc[random_index].copy()
        self.df.drop(random_index, inplace=True)
        if self._rating_counts_cache is not None and 'rating' in popped_row:
            rating = str(popped_row.get('rating') or '').strip().lower()
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
            
        self.df.drop_duplicates(subset=subset, keep='first', inplace=True)
        self.df.reset_index(drop=True, inplace=True)
        self._invalidate_caches()
