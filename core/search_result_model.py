import pandas as pd
from typing import Dict, Any, Optional, List

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
    
    # [신규] 무작위 행을 추출하고 제거하는 메서드
    def pop_random_row(self) -> Optional[pd.Series]:
        """
        데이터프레임에서 무작위로 행 하나를 선택하여 반환하고, 원본에서는 제거합니다.
        """
        if self.is_empty():
            return None
        
        # 무작위 인덱스 선택
        random_index = self.df.index.to_series().sample(n=1).iloc[0]
        
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