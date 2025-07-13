import pandas as pd
import re
from typing import Dict, List, Any, Optional

class SearchEngine:
    """Parquet 파일에서 태그를 검색하는 로직을 수행하는 핵심 엔진"""

    def _parse_query(self, query: str) -> Dict[str, List[Any]]:
        """검색 쿼리를 파싱하여 연산자별로 분리합니다."""
        query = query.strip().replace("_", " ")
        
        # OR 그룹 추출 ({...|...})
        or_groups_raw = re.findall(r'\{([^}]+)\}', query)
        query = re.sub(r'\{[^}]+\}', '', query) # OR 그룹 제거

        or_groups = []
        for group in or_groups_raw:
            or_parts = [part.strip().split(',') for part in group.split('|')]
            or_groups.append([p for p in or_parts if p])

        # 나머지 키워드를 쉼표로 분리
        keywords = [k.strip() for k in query.split(',') if k.strip()]

        # 연산자별로 분리
        parsed = {
            'normal': [k for k in keywords if not k.startswith(('*', '~'))],
            'exact': [k.lstrip('*') for k in keywords if k.startswith('*')],
            'not_exact': [k.lstrip('~') for k in keywords if k.startswith('~')],
        }
        if or_groups:
            parsed['or'] = or_groups
            
        return parsed

    def _apply_filters(self, df: pd.DataFrame, query: str, exclude_query: str) -> pd.DataFrame:
        """파싱된 쿼리에 따라 데이터프레임에 필터를 순차적으로 적용합니다."""
        if df.empty:
            return df
            
        # 긍정 쿼리 파싱 및 필터링
        search_params = self._parse_query(query)

        # [수정] 필터링 전에 'tags_string' 컬럼이 없으면 생성
        if 'tags_string' not in df.columns:
            df['tags_string'] = df[['copyright', 'character', 'artist', 'meta', 'general']].apply(
                lambda x: ','.join(x.dropna().astype(str)), axis=1
            )
            
        # 1. Normal (AND)
        if search_params['normal']:
            for keyword in search_params['normal']:
                # 정규식 특수문자 이스케이프
                safe_keyword = re.escape(keyword)
                mask = df['tags_string'].str.contains(safe_keyword, na=False, regex=True)
                df = df[mask]
                if df.empty: return df

        # 2. OR
        if 'or' in search_params and search_params['or']:
            final_or_mask = pd.Series(False, index=df.index)
            for group in search_params['or']:
                group_mask = pd.Series(True, index=df.index)
                for and_keywords in group:
                    part_mask = pd.Series(True, index=df.index)
                    for keyword in and_keywords:
                        safe_keyword = re.escape(keyword.strip())
                        part_mask &= df['tags_string'].str.contains(safe_keyword, na=False, regex=True)
                    group_mask &= part_mask
                final_or_mask |= group_mask
            df = df[final_or_mask]
            if df.empty: return df
        
        # 3. Exact (*)
        if search_params['exact']:
            for keyword in search_params['exact']:
                safe_keyword = re.escape(keyword)
                # 완전한 단어(태그)를 찾기 위한 정규식
                mask = df['tags_string'].str.contains(f'(?<![^, ]){safe_keyword}(?![^, ])', na=False, regex=True)
                df = df[mask]
                if df.empty: return df

        # 부정 쿼리 파싱 및 필터링
        exclude_params = self._parse_query(exclude_query)
        
        # 4. Normal Exclude
        if exclude_params['normal']:
            for keyword in exclude_params['normal']:
                safe_keyword = re.escape(keyword)
                mask = ~df['tags_string'].str.contains(safe_keyword, na=False, regex=True)
                df = df[mask]
                if df.empty: return df
                
        # 5. Exact Exclude (~)
        if exclude_params['not_exact']:
            for keyword in exclude_params['not_exact']:
                safe_keyword = re.escape(keyword)
                mask = ~df['tags_string'].str.contains(f'(?<![^, ]){safe_keyword}(?![^, ])', na=False, regex=True)
                df = df[mask]
                if df.empty: return df

        return df

    def search_in_file(self, file_path: str, search_params: Dict[str, Any]) -> Optional[pd.DataFrame]:
        """단일 Parquet 파일 내에서 검색을 수행합니다."""
        try:
            df = pd.read_parquet(file_path, engine="pyarrow")
        except Exception:
            return None # 파일 읽기 실패 시 건너뛰기

        # 등급 필터링
        enabled_ratings = set()
        if search_params.get('rating_e'): enabled_ratings.add('e')
        if search_params.get('rating_q'): enabled_ratings.add('q')
        if search_params.get('rating_s'): enabled_ratings.add('s')
        if search_params.get('rating_g'): enabled_ratings.add('g')
        
        df = df[df['rating'].isin(enabled_ratings)]
        if df.empty:
            return None

        # 성능 개선을 위해 모든 태그를 하나의 문자열 컬럼으로 결합
        df['tags_string'] = df[['copyright', 'character', 'artist', 'meta', 'general']].apply(
            lambda x: ','.join(x.dropna().astype(str)), axis=1
        )
        
        # 필터링 적용
        filtered_df = self._apply_filters(df, search_params['query'], search_params['exclude_query'])
        
        if filtered_df.empty:
            return None
            
        return filtered_df.drop(columns=['tags_string'])