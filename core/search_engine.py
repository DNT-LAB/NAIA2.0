import pandas as pd
import re
from typing import Dict, List, Any, Optional


class SearchEngine:
    """Parquet 파일에서 태그를 검색하는 로직을 수행하는 핵심 엔진"""
    TAG_COLUMNS = ['copyright', 'character', 'artist', 'meta', 'general']

    def _build_tags_string(self, df: pd.DataFrame) -> pd.Series:
        """태그 컬럼들을 쉼표로 결합한 tags_string 을 행 단위로 생성(벡터화).

        ``Series.str.cat`` 한 번으로 5개 태그 컬럼을 결합한다. 기존 melt/groupby
        구현 대비 ~수배 빠르며(읽기+빌드 150파일 51.7s→13.9s), 검색 결과는 동치
        (동일 ``.str.contains`` 매칭; NaN→'' 치환이라 빈 필드는 어떤 키워드와도
        매칭되지 않음). groupby('index') 를 쓰지 않으므로 비유니크 인덱스에서
        서로 다른 행의 태그가 병합되던 결함도 구조적으로 발생하지 않는다.
        """
        if df.empty:
            return pd.Series(index=df.index, dtype='object')

        first = df[self.TAG_COLUMNS[0]].astype(object)
        rest = [df[col].astype(object) for col in self.TAG_COLUMNS[1:]]
        return first.str.cat(rest, sep=',', na_rep='')

    def _parse_query(self, query: str) -> Dict[str, List[Any]]:
        query = query.strip().replace("_", " ")
        
        # OR 그룹 추출 ({tag1|tag2|tag3} 형태)
        or_groups_raw = re.findall(r'\{([^}]+)\}', query)
        query = re.sub(r'\{[^}]+\}', '', query)

        or_groups = []
        for group in or_groups_raw:
            # | 로 분리된 태그들을 개별 키워드로 처리 (수정됨)
            or_parts = [part.strip() for part in group.split('|') if part.strip()]
            if or_parts:
                or_groups.append(or_parts)

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

        # 필터링 전에 'tags_string' 컬럼이 없으면 생성
        if 'tags_string' not in df.columns:
            df['tags_string'] = self._build_tags_string(df)
            
        # 1. Normal (AND) - 각 키워드가 모두 포함되어야 함
        if search_params['normal']:
            for keyword in search_params['normal']:
                safe_keyword = re.escape(keyword)
                mask = df['tags_string'].str.contains(safe_keyword, na=False, regex=True)
                df = df[mask]
                if df.empty: 
                    return df

        # 2. OR - 수정된 로직
        if 'or' in search_params and search_params['or']:
            final_or_mask = pd.Series(False, index=df.index)
            
            for or_group in search_params['or']:
                # 각 OR 그룹 내에서는 하나의 태그만 일치하면 됨
                group_or_mask = pd.Series(False, index=df.index)
                
                for keyword in or_group:
                    safe_keyword = re.escape(keyword.strip())
                    keyword_mask = df['tags_string'].str.contains(safe_keyword, na=False, regex=True)
                    group_or_mask |= keyword_mask
                
                # 각 OR 그룹의 결과를 AND로 결합
                # 예: {tag1|tag2}, {tag3|tag4} → (tag1 OR tag2) AND (tag3 OR tag4)
                if final_or_mask.any():
                    final_or_mask &= group_or_mask
                else:
                    final_or_mask = group_or_mask
            
            df = df[final_or_mask]
            if df.empty: 
                return df
        
        # 3. Exact (*) - 정확한 태그 매칭
        if search_params['exact']:
            for keyword in search_params['exact']:
                safe_keyword = re.escape(keyword)
                # 완전한 단어(태그)를 찾기 위한 정규식
                mask = df['tags_string'].str.contains(f'(?<![^, ]){safe_keyword}(?![^, ])', na=False, regex=True)
                df = df[mask]
                if df.empty: 
                    return df

        # 부정 쿼리 파싱 및 필터링
        exclude_params = self._parse_query(exclude_query)
        
        # 4. Normal Exclude - 해당 키워드를 포함하지 않아야 함
        if exclude_params['normal']:
            for keyword in exclude_params['normal']:
                safe_keyword = re.escape(keyword)
                mask = ~df['tags_string'].str.contains(safe_keyword, na=False, regex=True)
                df = df[mask]
                if df.empty: 
                    return df
                
        # 5. Exact Exclude (~) - 정확한 태그를 포함하지 않아야 함
        if exclude_params['not_exact']:
            for keyword in exclude_params['not_exact']:
                safe_keyword = re.escape(keyword)
                mask = ~df['tags_string'].str.contains(f'(?<![^, ]){safe_keyword}(?![^, ])', na=False, regex=True)
                df = df[mask]
                if df.empty: 
                    return df

        return df

    def search_in_file(self, file_path: str, search_params: Dict[str, Any]) -> Optional[pd.DataFrame]:
        """단일 Parquet 파일 내에서 검색을 수행합니다."""
        try:
            df = pd.read_parquet(file_path, engine="pyarrow")
        except Exception:
            return None # 파일 읽기 실패 시 건너뛰기

        # 로드 시 인덱스 정규화: 원격 태그 아카이브 parquet 일부는 뒤섞인(때로 비유니크)
        # int64 인덱스를 갖는다(실제 식별자는 'id' 컬럼). parquet 자체는 수정 불가(원격
        # 로드)이므로 로드 단계에서 0..N-1 RangeIndex 로 리셋해 tags_string 이 행 단위로만
        # 만들어지게 한다 — 비유니크 인덱스에서 서로 다른 행의 태그가 병합되던 결함
        # (예: '2girls' 행이 '1girl' 검색에 매칭)을 로드 단계에서 차단.
        if not isinstance(df.index, pd.RangeIndex):
            df = df.reset_index(drop=True)

        # 등급 필터링 - 최적화: 모든 등급이 선택된 경우 건너뛰기
        enabled_ratings = set()
        if search_params.get('rating_e'): enabled_ratings.add('e')
        if search_params.get('rating_q'): enabled_ratings.add('q')
        if search_params.get('rating_s'): enabled_ratings.add('s')
        if search_params.get('rating_g'): enabled_ratings.add('g')

        # 모든 등급이 선택되지 않은 경우만 필터링
        if len(enabled_ratings) < 4:
            df = df[df['rating'].isin(enabled_ratings)]
            if df.empty:
                return None

        # 검색어가 있을 때만 tags_string 생성 (성능 최적화)
        if search_params.get('query') or search_params.get('exclude_query'):
            # 벡터화된 _build_tags_string 으로 매 검색마다 즉석 빌드(캐시 없음 -> 추가
            # 메모리 0). df 는 등급 필터로 boolean mask 된 뷰일 수 있어 copy 후 부착.
            df = df.copy()
            df['tags_string'] = self._build_tags_string(df)

            # 필터링 적용
            filtered_df = self._apply_filters(df, search_params['query'], search_params['exclude_query'])

            if filtered_df.empty:
                return None

            return filtered_df.drop(columns=['tags_string'])
        else:
            # 검색어가 없으면 필터링 없이 반환
            return df
