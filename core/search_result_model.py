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


class SearchResultModel:
    """검색 결과를 래핑하고 관리하는 데이터 모델 클래스"""

    def __init__(self, dataframe: Optional[pd.DataFrame] = None):
        if dataframe is None:
            self.df = pd.DataFrame()
        else:
            self.df = dataframe.reset_index(drop=True)

    def append_dataframe(self, new_df: pd.DataFrame):
        """기존 결과에 새로운 데이터프레임을 추가합니다."""
        if new_df is None or new_df.empty:
            return
        self.df = pd.concat([self.df, new_df], ignore_index=True)
    
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

    def get_dataframe(self) -> pd.DataFrame:
        """결과 데이터프레임을 반환합니다."""
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
        counts = self.df['rating'].value_counts()
        return {r: int(counts.get(r, 0)) for r in 'gsqe'}

    def get_filtered_count(self, active_ratings: set) -> int:
        """활성 rating에 해당하는 row 수."""
        if self.is_empty() or 'rating' not in self.df.columns:
            return 0
        return int(self.df['rating'].isin(active_ratings).sum())

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

        eligible = self.df
        if active_ratings and 'rating' in self.df.columns:
            mask = self.df['rating'].isin(active_ratings)
            eligible = eligible[mask]

        if 'general' in eligible.columns:
            eligible = eligible[eligible['general'].map(_has_prompt_text)]

        if eligible.empty:
            return None

        random_index = eligible.index.to_series().sample(n=1).iloc[0]

        # 해당 행 데이터 추출 및 원본에서 삭제
        popped_row = self.df.loc[random_index].copy()
        self.df.drop(random_index, inplace=True)

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
