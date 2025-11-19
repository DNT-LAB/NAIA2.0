"""
EZ Mode Data Manager

데이터 로딩, 캐싱, 매트릭스 관리를 담당하는 중앙 데이터 관리자
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import pandas as pd
from scipy.sparse import load_npz
from PyQt6.QtCore import QObject, pyqtSignal


class EZModeDataManager(QObject):
    """EZ Mode 데이터 로딩 및 관리"""

    data_loaded = pyqtSignal()
    load_error = pyqtSignal(str)

    def __init__(self, data_dir='data/ezmode'):
        super().__init__()
        self.data_dir = Path(data_dir)  # JSON 파일 경로 (GitHub)
        self.matrices_dir = Path('data/.ezmode/matrices')  # Matrices 경로 (Hugging Face)

        # 데이터
        self.category_index: Optional[Dict] = None
        self.tag_index: Optional[Dict[str, int]] = None
        self.index_tag: Optional[Dict[int, str]] = None
        self.kr_tags_df: Optional[pd.DataFrame] = None

        # 매트릭스 캐시 (최대 3개)
        self.matrix_cache: Dict[str, Dict] = {}
        self.cache_order: List[str] = []

    def load_initial_data(self) -> bool:
        """초기 데이터 로드 (category_index, tag_index)"""
        try:
            # category_index.json
            category_path = self.data_dir / 'category_index.json'
            if not category_path.exists():
                raise FileNotFoundError(f"category_index.json을 찾을 수 없습니다: {category_path}")

            with open(category_path, 'r', encoding='utf-8') as f:
                self.category_index = json.load(f)

            print(f"[OK] category_index.json loaded: {self.category_index['metadata']['total_categories']} categories")

            # output.json (태그 인덱스)
            output_path = self.data_dir / 'output.json'
            if not output_path.exists():
                raise FileNotFoundError(f"output.json not found: {output_path}")

            with open(output_path, 'r', encoding='utf-8') as f:
                tag_totals = json.load(f)

            tags = sorted(tag_totals.keys())
            self.tag_index = {tag: idx for idx, tag in enumerate(tags)}
            self.index_tag = {idx: tag for tag, idx in self.tag_index.items()}

            print(f"[OK] output.json loaded: {len(self.tag_index)} tags")

            self.data_loaded.emit()
            return True

        except Exception as e:
            error_msg = f"Data load failed: {e}"
            print(f"[ERROR] {error_msg}")
            self.load_error.emit(error_msg)
            return False

    def load_kr_tags(self) -> bool:
        """KR_tags.parquet 로드 (Tooltip용)"""
        try:
            kr_tags_path = Path('data/KR_tags.parquet')
            if kr_tags_path.exists():
                self.kr_tags_df = pd.read_parquet(kr_tags_path)
                print(f"[OK] KR_tags.parquet loaded: {len(self.kr_tags_df)} entries")
                return True
            else:
                print("[WARN] KR_tags.parquet not found. Tooltip functionality limited.")
                return False
        except Exception as e:
            print(f"[WARN] KR_tags load failed: {e}")
            return False

    def get_tooltip_for_tag(self, tag: str) -> Optional[str]:
        """태그의 Tooltip 가져오기 (KR_tags.parquet의 keywords 컬럼)"""
        if self.kr_tags_df is None:
            return None

        try:
            result = self.kr_tags_df[self.kr_tags_df['tags'] == tag]
            if not result.empty and 'keywords' in result.columns:
                keyword = result.iloc[0]['keywords']
                # NaN 체크
                if pd.notna(keyword):
                    return str(keyword)
        except Exception as e:
            print(f"Tooltip 조회 실패 ({tag}): {e}")

        return None

    def load_matrices(self, category_id: str) -> Optional[Dict]:
        """매트릭스 로드 (캐싱)"""
        # 캐시 확인
        if category_id in self.matrix_cache:
            print(f"[CACHE] Matrix loaded from cache: {category_id}")
            return self.matrix_cache[category_id]

        # 디스크에서 로드
        try:
            base_path = self.matrices_dir / category_id  # data/.ezmode/matrices/{category_id}

            print(f"[LOADING] Loading matrices: {category_id}")

            # 파일 존재 확인
            required_files = [
                f"{base_path}_cooccur.npz",
                f"{base_path}_pmi.npz",
                f"{base_path}_condprob.npz",
                f"{base_path}_metadata.json"
            ]

            for file_path in required_files:
                if not Path(file_path).exists():
                    raise FileNotFoundError(f"필수 파일 없음: {file_path}")

            matrices = {
                'cooccur': load_npz(f"{base_path}_cooccur.npz"),
                'pmi': load_npz(f"{base_path}_pmi.npz"),
                'condprob': load_npz(f"{base_path}_condprob.npz")
            }

            with open(f"{base_path}_metadata.json", 'r', encoding='utf-8') as f:
                matrices['metadata'] = json.load(f)

            print(f"[OK] Matrices loaded: {category_id} (shape: {matrices['pmi'].shape})")

            # 캐시 저장 (LRU)
            self._add_to_cache(category_id, matrices)

            return matrices

        except Exception as e:
            print(f"[ERROR] Matrix load failed ({category_id}): {e}")
            return None

    def _add_to_cache(self, category_id: str, matrices: Dict):
        """LRU 캐시에 추가"""
        # 이미 있으면 제거 후 재추가
        if category_id in self.cache_order:
            self.cache_order.remove(category_id)

        self.cache_order.append(category_id)
        self.matrix_cache[category_id] = matrices

        # 캐시 크기 제한 (최대 3개)
        while len(self.cache_order) > 3:
            oldest = self.cache_order.pop(0)
            del self.matrix_cache[oldest]
            print(f"[CACHE] Removed from cache: {oldest}")

    def get_available_ratings(self) -> List[str]:
        """사용 가능한 Rating 목록"""
        if not self.category_index:
            return []
        return self.category_index['available_options']['ratings']

    def get_available_person_types(self) -> List[str]:
        """사용 가능한 Person Type 목록"""
        if not self.category_index:
            return []
        return self.category_index['available_options']['person_types']

    def get_available_person_counts(self, rating: str, person_type: str) -> List[str]:
        """특정 Rating과 Person Type에서 가용한 Person Count 목록"""
        if not self.category_index:
            return []

        try:
            return list(self.category_index['ui_tree'][rating][person_type].keys())
        except KeyError:
            print(f"[WARN] Person count not found: rating={rating}, person_type={person_type}")
            return []

    def get_available_options(self, rating: str, person_type: str, person_count_key: str) -> List[Dict]:
        """사용 가능한 Special Tag 옵션 목록"""
        if not self.category_index:
            return []

        try:
            return self.category_index['ui_tree'][rating][person_type][person_count_key]
        except KeyError:
            print(f"[WARN] Special tag options not found: rating={rating}, person_type={person_type}, person_count={person_count_key}")
            return []

    def build_category_id(self, rating: str, person_type: str,
                         person_count: Dict[str, int], special_tags: List[str]) -> str:
        """카테고리 ID 생성

        예시:
        - rating='g', person_type='solo', person_count={'1girl': 1}, special_tags=[]
          → "g_solo_1girl"
        - rating='g', person_type='solo', person_count={'1girl': 1}, special_tags=['small_breasts']
          → "g_solo_1girl_small_breasts"
        """
        person_count_str = '_'.join(sorted(person_count.keys()))
        special_tags_str = '_'.join(sorted(special_tags)) if special_tags else ''

        category_id = f"{rating}_{person_type}_{person_count_str}"
        if special_tags_str:
            category_id += f"_{special_tags_str}"

        return category_id

    def validate_category_exists(self, category_id: str) -> bool:
        """카테고리가 존재하는지 확인"""
        if not self.category_index:
            return False

        return category_id in self.category_index.get('categories', {})

    def get_category_info(self, category_id: str) -> Optional[Dict]:
        """카테고리 상세 정보 조회"""
        if not self.category_index:
            return None

        return self.category_index.get('categories', {}).get(category_id)

    def clear_cache(self):
        """매트릭스 캐시 초기화"""
        self.matrix_cache.clear()
        self.cache_order.clear()
        print("[CACHE] Matrix cache cleared")
