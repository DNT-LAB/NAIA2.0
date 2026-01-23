
import pickle
import struct
import lzma
from collections import Counter
from typing import Dict, List, Set, Optional
from pathlib import Path

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    np = None
    HAS_NUMPY = False

class SinglePartitionStore:
    """단일 파티션 데이터 스토어 (메모리 효율적)"""
    MAGIC = b'TGP1'

    def __init__(self):
        self.num_events: int = 0
        self._event_tag_indices = None
        self._event_tag_indptr = None
        self._event_counts = None
        self._tag_to_events: Dict[int, object] = {}
        self._loaded: bool = False

    @classmethod
    def load(cls, input_path: Path) -> 'SinglePartitionStore':
        """파티션 파일 로드"""
        if not HAS_NUMPY:
            print("QuickSearch: NumPy is required to load partition data.")
            return cls()

        store = cls()
        
        try:
            with open(input_path, 'rb') as f:
                magic = f.read(4)
                if magic != cls.MAGIC:
                    print(f"QuickSearch: Invalid format magic {magic}")
                    return store

                _ = struct.unpack('<H', f.read(2))[0]  # version
                compressed_len = struct.unpack('<I', f.read(4))[0]
                compressed = f.read(compressed_len)

            serialized = lzma.decompress(compressed)
            data = pickle.loads(serialized)

            store.num_events = data['num_events']
            # .copy() for safety if data is read-only
            store._event_tag_indices = np.frombuffer(data['event_tag_indices'], dtype=np.uint16).copy()
            store._event_tag_indptr = np.frombuffer(data['event_tag_indptr'], dtype=np.int32).copy()
            store._event_counts = np.frombuffer(data['event_counts'], dtype=np.int32).copy()

            store._tag_to_events = {
                int(k): np.frombuffer(v, dtype=np.int32).copy()
                for k, v in data['tag_to_events'].items()
            }

            store._loaded = True
            # print(f"QuickSearch: Partition loaded successfully ({store.num_events} events)")
            return store
            
        except Exception as e:
            print(f"QuickSearch: Failed to load partition: {e}")
            return cls()

    def filter_events(self, required_tags: List[str] = None, excluded_tags: List[str] = None, tag_to_id: Dict[str, int] = None) -> object:
        """조건에 맞는 이벤트 인덱스(ndarray) 반환"""
        if not self._loaded or not HAS_NUMPY:
            return np.array([], dtype=np.int32) if HAS_NUMPY else []

        candidates = None

        # Required 태그 처리 (교집합)
        if required_tags and tag_to_id:
            sorted_req = []
            for tag in required_tags:
                if tag in tag_to_id:
                    tag_id = tag_to_id[tag]
                    if tag_id in self._tag_to_events:
                        sorted_req.append((len(self._tag_to_events[tag_id]), tag_id))
                    else:
                        # 필수 태그가 존재하지 않는 이벤트 -> 결과 0개
                        return np.array([], dtype=np.int32)
                # tag가 id 매핑에 없으면 해당 태그를 가진 이벤트도 없음 -> 결과 0개
                # (단, 사용자가 오타를 냈거나 없는 태그를 입력했을 경우 무시할지 엄격하게 할지 결정 필요.
                #  여기서는 엄격하게 처리)
                elif tag not in tag_to_id: 
                     return np.array([], dtype=np.int32)
            
            # 빈도 적은 순 정렬 (최적화)
            sorted_req.sort()
            
            # 첫 번째 태그로 후보 초기화
            if sorted_req:
                first_tag_id = sorted_req[0][1]
                candidates = set(self._tag_to_events[first_tag_id])
                
                # 나머지 태그들과 교집합
                for _, tag_id in sorted_req[1:]:
                    candidates &= set(self._tag_to_events[tag_id])
                    if not candidates:
                        return np.array([], dtype=np.int32)

        if candidates is None:
             # required 태그가 없으면 전체 이벤트가 후보
             candidates = set(range(self.num_events))

        # Excluded 태그 처리 (차집합)
        if excluded_tags and tag_to_id:
            for tag in excluded_tags:
                if tag in tag_to_id:
                    tag_id = tag_to_id[tag]
                    if tag_id in self._tag_to_events:
                        candidates -= set(self._tag_to_events[tag_id])
                        if not candidates:
                             return np.array([], dtype=np.int32)

        return np.array(sorted(list(candidates)), dtype=np.int32)

    def get_tag_counts(self, event_indices, id_to_tag: Dict[int, str]) -> Counter:
        """
        선택된 이벤트들에 대한 태그 빈도수 계산
        event_indices: np.array (sorted int32)
        """
        if not self._loaded or not HAS_NUMPY or id_to_tag is None:
            return Counter()

        if len(event_indices) == 0:
            return Counter()
        
        # 1. 대상 이벤트들의 모든 태그 ID 수집
        # 루프 최적화를 위해 단순 리스트 확장 사용
        all_tags = []
        
        # event_indices가 numpy array임
        for evt_idx in event_indices:
            start = self._event_tag_indptr[evt_idx]
            end = self._event_tag_indptr[evt_idx+1]
            # 슬라이싱으로 numpy array 부분 추출
            tags = self._event_tag_indices[start:end]
            all_tags.extend(tags)
            
        counter = Counter(all_tags)
        
        # 2. 태그 ID를 이름으로 변환
        result = Counter()
        for tag_id, count in counter.items():
            if tag_id in id_to_tag:
                result[id_to_tag[tag_id]] += count
                
        return result
    
    def get_random_prompt(self, event_indices, id_to_tag: Dict[int, str]) -> str:
        """이벤트 중 하나를 랜덤 선택하여 프롬프트 생성"""
        if not self._loaded or len(event_indices) == 0:
            return ""
        
        import random
        evt_idx = random.choice(event_indices)
        
        start = self._event_tag_indptr[evt_idx]
        end = self._event_tag_indptr[evt_idx+1]
        tag_ids = self._event_tag_indices[start:end]
        
        tags = [id_to_tag[tid] for tid in tag_ids if tid in id_to_tag]
        
        # 태그 셔플링 옵션이 필요할 수도 있지만 일단 순서대로
        return ", ".join(tags)
