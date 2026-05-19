"""
이벤트 검색 유틸리티 (Event Search Utils)

NAIA_event_dataset에서 Parent/Child 이벤트를 검색하는 기능 제공

사용법:
    from event_search_utils import EventSearcher

    searcher = EventSearcher('continue_events/NAIA_event_dataset_v4.parquet')

    # Parent 검색
    parents = searcher.search_parents(include='1girl, smile', exclude='2girls')

    # Child 검색
    children = searcher.search_children(include='sex', exclude='group sex')

    # 특정 Parent의 Children 가져오기
    children = searcher.get_children(parent_id=12345)
"""

import os
import pandas as pd
from typing import List, Optional, Set, Union


class EventSearcher:
    """이벤트 데이터셋 검색 클래스"""

    def __init__(self, parquet_path: str = None, df: pd.DataFrame = None):
        """
        초기화

        Args:
            parquet_path: parquet 파일 경로 (df가 None인 경우 사용)
            df: 이미 로드된 DataFrame (parquet_path보다 우선)
        """
        if df is not None:
            self.df = df
        elif parquet_path is not None:
            if not os.path.exists(parquet_path):
                raise FileNotFoundError(f"File not found: {parquet_path}")
            self.df = pd.read_parquet(parquet_path)
        else:
            raise ValueError("Either parquet_path or df must be provided")

        # Parent/Children 분리 및 캐싱
        self._parent_df: Optional[pd.DataFrame] = None
        self._children_df: Optional[pd.DataFrame] = None
        self._children_counts: Optional[pd.Series] = None

    @property
    def parent_df(self) -> pd.DataFrame:
        """Parent 이벤트 DataFrame (캐싱)"""
        if self._parent_df is None:
            self._parent_df = self.df[self.df['has_children'] == True].copy()
        return self._parent_df

    @property
    def children_df(self) -> pd.DataFrame:
        """Children 이벤트 DataFrame (캐싱)"""
        if self._children_df is None:
            self._children_df = self.df[self.df['has_children'] == False].copy()
        return self._children_df

    @property
    def children_counts(self) -> pd.Series:
        """Parent별 Children 수 (캐싱)"""
        if self._children_counts is None:
            self._children_counts = self.children_df.groupby('parent_id').size()
        return self._children_counts

    def _parse_search_terms(self, search_text: str) -> List[str]:
        """검색어 문자열을 리스트로 파싱"""
        if not search_text or not search_text.strip():
            return []
        return [t.strip() for t in search_text.split(',') if t.strip()]

    def _filter_by_tags(
        self,
        df: pd.DataFrame,
        include: Union[str, List[str]] = None,
        exclude: Union[str, List[str]] = None,
        column: str = 'general'
    ) -> pd.DataFrame:
        """
        태그 기반 필터링

        Args:
            df: 필터링할 DataFrame
            include: 포함해야 할 태그 (쉼표 구분 문자열 또는 리스트)
            exclude: 제외해야 할 태그 (쉼표 구분 문자열 또는 리스트)
            column: 검색할 컬럼명 (기본: 'general')

        Returns:
            필터링된 DataFrame
        """
        result = df.copy()

        # Include 필터
        if include:
            if isinstance(include, str):
                include_terms = self._parse_search_terms(include)
            else:
                include_terms = include

            for term in include_terms:
                mask = result[column].str.contains(term, case=False, na=False)
                result = result[mask]

        # Exclude 필터
        if exclude:
            if isinstance(exclude, str):
                exclude_terms = self._parse_search_terms(exclude)
            else:
                exclude_terms = exclude

            for term in exclude_terms:
                mask = ~result[column].str.contains(term, case=False, na=False)
                result = result[mask]

        return result

    def search_parents(
        self,
        include: Union[str, List[str]] = None,
        exclude: Union[str, List[str]] = None,
        min_children: int = None,
        max_children: int = None,
        ratings: List[str] = None
    ) -> pd.DataFrame:
        """
        Parent 이벤트 검색

        Args:
            include: 포함해야 할 태그 (쉼표 구분 문자열 또는 리스트)
            exclude: 제외해야 할 태그 (쉼표 구분 문자열 또는 리스트)
            min_children: 최소 Children 수
            max_children: 최대 Children 수
            ratings: 허용할 rating 리스트 (예: ['q', 'e'])

        Returns:
            검색된 Parent DataFrame

        Example:
            # 1girl과 smile을 포함하고 2girls를 제외
            parents = searcher.search_parents(
                include='1girl, smile',
                exclude='2girls',
                min_children=2,
                ratings=['q', 'e']
            )
        """
        result = self.parent_df.copy()

        # 태그 필터링
        result = self._filter_by_tags(result, include, exclude)

        # Children 수 필터링
        if min_children is not None or max_children is not None:
            # Children 수 추가
            result['children_count'] = result['id'].map(self.children_counts).fillna(0).astype(int)

            if min_children is not None:
                result = result[result['children_count'] >= min_children]
            if max_children is not None:
                result = result[result['children_count'] <= max_children]

        # Rating 필터링
        if ratings:
            result = result[result['rating'].isin(ratings)]

        return result

    def search_children(
        self,
        include: Union[str, List[str]] = None,
        exclude: Union[str, List[str]] = None,
        parent_ids: List[int] = None,
        ratings: List[str] = None,
        min_score: int = None
    ) -> pd.DataFrame:
        """
        Children 이벤트 검색

        Args:
            include: 포함해야 할 태그 (쉼표 구분 문자열 또는 리스트)
            exclude: 제외해야 할 태그 (쉼표 구분 문자열 또는 리스트)
            parent_ids: 특정 Parent의 Children만 검색 (리스트)
            ratings: 허용할 rating 리스트 (예: ['q', 'e'])
            min_score: 최소 score

        Returns:
            검색된 Children DataFrame

        Example:
            # sex를 포함하고 group sex를 제외, e rating만
            children = searcher.search_children(
                include='sex',
                exclude='group sex',
                ratings=['e'],
                min_score=10
            )
        """
        result = self.children_df.copy()

        # Parent ID 필터링
        if parent_ids is not None:
            result = result[result['parent_id'].isin(parent_ids)]

        # 태그 필터링
        result = self._filter_by_tags(result, include, exclude)

        # Rating 필터링
        if ratings:
            result = result[result['rating'].isin(ratings)]

        # Score 필터링
        if min_score is not None:
            result = result[result['score'] >= min_score]

        return result

    def get_children(self, parent_id: int, sort_by_id: bool = True) -> pd.DataFrame:
        """
        특정 Parent의 모든 Children 가져오기

        Args:
            parent_id: Parent 이벤트 ID
            sort_by_id: ID 순으로 정렬할지 여부

        Returns:
            해당 Parent의 Children DataFrame
        """
        result = self.children_df[self.children_df['parent_id'] == parent_id]
        if sort_by_id:
            result = result.sort_values('id')
        return result

    def get_parent(self, parent_id: int) -> Optional[pd.Series]:
        """
        특정 Parent 이벤트 가져오기

        Args:
            parent_id: Parent 이벤트 ID

        Returns:
            Parent 이벤트 Series (없으면 None)
        """
        result = self.parent_df[self.parent_df['id'] == parent_id]
        if len(result) == 0:
            return None
        return result.iloc[0]

    def get_sequence(self, parent_id: int) -> pd.DataFrame:
        """
        Parent + Children 전체 시퀀스 가져오기

        Args:
            parent_id: Parent 이벤트 ID

        Returns:
            Parent와 Children을 포함한 DataFrame (ID 순 정렬)
        """
        parent = self.parent_df[self.parent_df['id'] == parent_id]
        children = self.get_children(parent_id)
        return pd.concat([parent, children]).sort_values('id')

    def search_parents_by_child_tags(
        self,
        child_include: Union[str, List[str]] = None,
        child_exclude: Union[str, List[str]] = None,
        parent_include: Union[str, List[str]] = None,
        parent_exclude: Union[str, List[str]] = None,
        child_ratings: List[str] = None,
        require_all_children: bool = False
    ) -> pd.DataFrame:
        """
        Child 태그 조건으로 Parent 검색

        Args:
            child_include: Children에 포함해야 할 태그
            child_exclude: Children에서 제외해야 할 태그
            parent_include: Parent에 포함해야 할 태그
            parent_exclude: Parent에서 제외해야 할 태그
            child_ratings: Children rating 필터
            require_all_children: True면 모든 Children이 조건 만족해야 함

        Returns:
            조건을 만족하는 Parent DataFrame

        Example:
            # Children 중 하나라도 'sex'를 포함하는 Parent 검색
            parents = searcher.search_parents_by_child_tags(
                child_include='sex',
                parent_include='1girl'
            )
        """
        # 먼저 조건에 맞는 Children 찾기
        matching_children = self.search_children(
            include=child_include,
            exclude=child_exclude,
            ratings=child_ratings
        )

        if require_all_children:
            # 모든 Children이 조건을 만족하는 Parent만
            # (각 Parent의 전체 Children 수와 매칭 Children 수 비교)
            matching_counts = matching_children.groupby('parent_id').size()
            total_counts = self.children_counts

            valid_parents = []
            for parent_id in matching_counts.index:
                if parent_id in total_counts.index:
                    if matching_counts[parent_id] == total_counts[parent_id]:
                        valid_parents.append(parent_id)

            parent_ids = valid_parents
        else:
            # 하나라도 조건을 만족하는 Children이 있는 Parent
            parent_ids = matching_children['parent_id'].unique().tolist()

        # Parent 필터링
        result = self.parent_df[self.parent_df['id'].isin(parent_ids)]

        # Parent 태그 추가 필터링
        result = self._filter_by_tags(result, parent_include, parent_exclude)

        return result

    def get_random_parents(self, n: int = 10, **search_kwargs) -> pd.DataFrame:
        """
        랜덤 Parent 샘플 가져오기

        Args:
            n: 샘플 수
            **search_kwargs: search_parents()에 전달할 인자

        Returns:
            랜덤 샘플 DataFrame
        """
        result = self.search_parents(**search_kwargs)
        return result.sample(min(n, len(result)))

    def get_stats(self) -> dict:
        """
        데이터셋 통계 반환

        Returns:
            통계 딕셔너리
        """
        return {
            'total_events': len(self.df),
            'total_parents': len(self.parent_df),
            'total_children': len(self.children_df),
            'rating_distribution': self.df['rating'].value_counts().to_dict(),
            'children_per_parent': {
                'mean': self.children_counts.mean(),
                'median': self.children_counts.median(),
                'min': self.children_counts.min(),
                'max': self.children_counts.max()
            }
        }


# 편의 함수
def load_event_dataset(version: str = 'v4') -> EventSearcher:
    """
    이벤트 데이터셋 로드 편의 함수

    Args:
        version: 데이터셋 버전 ('v4', 'v4_heavy', 'v3', 'v2')

    Returns:
        EventSearcher 인스턴스
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))

    version_map = {
        'v4': 'NAIA_event_dataset_v4.parquet',
        'v4_heavy': 'NAIA_event_dataset_v4_heavy.parquet',
        'v3': 'NAIA_event_dataset_v3.parquet',
        'v2': 'NAIA_event_dataset_v2.parquet',
    }

    if version not in version_map:
        raise ValueError(f"Unknown version: {version}. Available: {list(version_map.keys())}")

    path = os.path.join(script_dir, 'continue_events', version_map[version])
    return EventSearcher(path)


# 테스트 코드
if __name__ == "__main__":
    print("=== Event Search Utils Test ===\n")

    # 로드
    searcher = load_event_dataset('v4')

    # 통계
    stats = searcher.get_stats()
    print(f"Dataset Stats:")
    print(f"  Total events: {stats['total_events']:,}")
    print(f"  Parents: {stats['total_parents']:,}")
    print(f"  Children: {stats['total_children']:,}")
    print(f"  Avg children per parent: {stats['children_per_parent']['mean']:.2f}")

    # Parent 검색 테스트
    print("\n--- Parent Search Test ---")
    parents = searcher.search_parents(
        include='1girl, solo',
        exclude='2girls',
        min_children=3,
        ratings=['q', 'e']
    )
    print(f"Found {len(parents):,} parents with '1girl, solo', excluding '2girls', min 3 children, q/e rating")

    # Children 검색 테스트
    print("\n--- Children Search Test ---")
    children = searcher.search_children(
        include='sex',
        ratings=['e']
    )
    print(f"Found {len(children):,} children with 'sex' tag and 'e' rating")

    # Child 태그로 Parent 검색
    print("\n--- Search Parents by Child Tags ---")
    parents = searcher.search_parents_by_child_tags(
        child_include='sex',
        parent_include='1girl'
    )
    print(f"Found {len(parents):,} parents where at least one child has 'sex' tag")

    # 시퀀스 가져오기
    print("\n--- Get Sequence Example ---")
    if len(parents) > 0:
        sample_parent_id = parents.iloc[0]['id']
        sequence = searcher.get_sequence(sample_parent_id)
        print(f"Sequence for parent {sample_parent_id}: {len(sequence)} events")

    print("\n=== Test Complete ===")
