"""
Event Index Manager

save/turbo_events 폴더의 생성된 이벤트를 JSON 인덱스로 관리
- 폴더 스캔 및 동기화
- 검색 필터링
- Parquet 쿼리 최소화
"""

import os
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Set
import pandas as pd


class EventIndexManager:
    """이벤트 인덱스 관리자

    save/turbo_events 폴더의 파일 목록을 JSON 인덱스로 관리하여
    Parquet 파일 쿼리를 최소화합니다.
    """

    INDEX_VERSION = "1.1"  # child_general 필드 추가
    INDEX_FILENAME = "generated_event_index.json"

    def __init__(self, data_dir: Path, events_dir: Path):
        """
        Args:
            data_dir: Parquet 파일이 있는 data 폴더 경로
            events_dir: 생성된 이벤트 이미지가 있는 save/turbo_events 폴더 경로
        """
        self.data_dir = Path(data_dir)
        self.events_dir = Path(events_dir)
        self.index_path = self.events_dir / self.INDEX_FILENAME

        # 인덱스 데이터
        self.index: Dict[int, Dict] = {}  # {parent_id: event_info}
        self.sorted_ids: List[int] = []  # 정렬된 ID 리스트 (생성일순)

        # EventSearcher (Lazy load)
        self._searcher = None
        self._searcher_loaded = False

    @property
    def searcher(self):
        """EventSearcher 인스턴스 (Lazy load)"""
        if not self._searcher_loaded:
            self._load_searcher()
        return self._searcher

    def _load_searcher(self):
        """EventSearcher 로드"""
        try:
            from ..event_search_utils import EventSearcher
            parquet_path = self.data_dir / 'NAIA_event_dataset_1girl.parquet'
            if parquet_path.exists():
                self._searcher = EventSearcher(str(parquet_path))
                print(f"[EventIndexManager] EventSearcher loaded: {parquet_path.name}")
            else:
                print(f"[EventIndexManager] Parquet not found: {parquet_path}")
                self._searcher = None
        except Exception as e:
            print(f"[EventIndexManager] Failed to load EventSearcher: {e}")
            self._searcher = None
        self._searcher_loaded = True

    def load_index(self) -> bool:
        """JSON 인덱스 로드

        Returns:
            bool: 로드 성공 여부
        """
        if not self.index_path.exists():
            print(f"[EventIndexManager] Index file not found, will create new one")
            return False

        try:
            with open(self.index_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 버전 체크
            if data.get('version') != self.INDEX_VERSION:
                print(f"[EventIndexManager] Index version mismatch, will rebuild")
                return False

            # 이벤트 로드
            events = data.get('events', [])
            self.index = {event['id']: event for event in events}
            self._rebuild_sorted_ids()

            print(f"[EventIndexManager] Loaded {len(self.index)} events from index")
            return True

        except Exception as e:
            print(f"[EventIndexManager] Failed to load index: {e}")
            return False

    def save_index(self) -> bool:
        """JSON 인덱스 저장

        Returns:
            bool: 저장 성공 여부
        """
        try:
            self.events_dir.mkdir(parents=True, exist_ok=True)

            # 정렬된 순서로 저장
            events = [self.index[id_] for id_ in self.sorted_ids if id_ in self.index]

            data = {
                'version': self.INDEX_VERSION,
                'last_updated': datetime.now().isoformat(),
                'total_count': len(events),
                'events': events
            }

            with open(self.index_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            print(f"[EventIndexManager] Saved {len(events)} events to index")
            return True

        except Exception as e:
            print(f"[EventIndexManager] Failed to save index: {e}")
            return False

    def sync_with_folder(self, progress_callback=None) -> Dict[str, int]:
        """폴더와 인덱스 동기화

        Args:
            progress_callback: 진행률 콜백 (current, total, message)

        Returns:
            Dict with 'added', 'removed', 'total' counts
        """
        if not self.events_dir.exists():
            return {'added': 0, 'removed': 0, 'total': 0}

        # 폴더 스캔 - 숫자로만 된 파일명(확장자 없음)만 대상
        folder_ids: Set[int] = set()
        for file_path in self.events_dir.iterdir():
            if file_path.is_file() and file_path.name != self.INDEX_FILENAME:
                try:
                    # 파일명이 숫자인지 확인
                    parent_id = int(file_path.name)
                    folder_ids.add(parent_id)
                except ValueError:
                    continue

        # 인덱스에 있는 ID
        index_ids = set(self.index.keys())

        # 새로 추가된 파일
        new_ids = folder_ids - index_ids
        # 삭제된 파일
        removed_ids = index_ids - folder_ids

        total_work = len(new_ids) + len(removed_ids)
        current_work = 0

        # 새 파일 추가
        for parent_id in new_ids:
            if progress_callback:
                current_work += 1
                progress_callback(current_work, total_work, f"Adding event {parent_id}...")

            event_info = self._get_event_info_from_parquet(parent_id)
            if event_info:
                self.index[parent_id] = event_info
            else:
                # Parquet에서 찾을 수 없으면 기본 정보만 저장
                file_path = self.events_dir / str(parent_id)
                created_at = datetime.fromtimestamp(file_path.stat().st_mtime).isoformat()
                self.index[parent_id] = {
                    'id': parent_id,
                    'general': '',
                    'ratings': [],
                    'pages': 0,
                    'created_at': created_at
                }

        # 삭제된 파일 제거
        for parent_id in removed_ids:
            if progress_callback:
                current_work += 1
                progress_callback(current_work, total_work, f"Removing event {parent_id}...")

            del self.index[parent_id]

        # 정렬된 ID 리스트 재구축
        self._rebuild_sorted_ids()

        # 변경이 있으면 저장
        if new_ids or removed_ids:
            self.save_index()

        result = {
            'added': len(new_ids),
            'removed': len(removed_ids),
            'total': len(self.index)
        }

        print(f"[EventIndexManager] Sync complete: +{result['added']} -{result['removed']} = {result['total']} total")
        return result

    def _get_event_info_from_parquet(self, parent_id: int) -> Optional[Dict]:
        """Parquet에서 이벤트 정보 조회

        Args:
            parent_id: 조회할 parent_id

        Returns:
            이벤트 정보 딕셔너리 또는 None
        """
        if self.searcher is None:
            return None

        try:
            sequence_df = self.searcher.get_sequence(parent_id)
            if sequence_df is None or len(sequence_df) == 0:
                return None

            # Parent 정보
            parent_rows = sequence_df[sequence_df['has_children'] == True]
            if len(parent_rows) == 0:
                return None

            parent = parent_rows.iloc[0]
            general = str(parent.get('general', ''))

            # 전체 rating 수집 및 child general 수집
            ratings = []
            ratings.append(str(parent.get('rating', '')).lower())
            children = sequence_df[sequence_df['has_children'] == False].sort_values('id')
            child_generals = []
            for _, child in children.iterrows():
                ratings.append(str(child.get('rating', '')).lower())
                child_general = str(child.get('general', ''))
                if child_general:
                    child_generals.append(child_general)

            # child_general: 모든 child의 general 태그를 합침 (검색용)
            child_general_combined = ' '.join(child_generals)

            # 파일 생성 시간
            file_path = self.events_dir / str(parent_id)
            if file_path.exists():
                created_at = datetime.fromtimestamp(file_path.stat().st_mtime).isoformat()
            else:
                created_at = datetime.now().isoformat()

            return {
                'id': parent_id,
                'general': general,
                'child_general': child_general_combined,
                'ratings': ratings,
                'pages': len(sequence_df),
                'created_at': created_at
            }

        except Exception as e:
            print(f"[EventIndexManager] Failed to get event info for {parent_id}: {e}")
            return None

    def _rebuild_sorted_ids(self):
        """정렬된 ID 리스트 재구축 (생성일 역순)"""
        # created_at 기준 내림차순 정렬 (최신순)
        sorted_events = sorted(
            self.index.values(),
            key=lambda x: x.get('created_at', ''),
            reverse=True
        )
        self.sorted_ids = [event['id'] for event in sorted_events]

    def add_event(self, parent_id: int) -> bool:
        """새 이벤트 추가 (생성 완료 시 호출)

        Args:
            parent_id: 추가할 이벤트의 parent_id

        Returns:
            bool: 추가 성공 여부
        """
        if parent_id in self.index:
            return False  # 이미 존재

        event_info = self._get_event_info_from_parquet(parent_id)
        if event_info:
            self.index[parent_id] = event_info
            self._rebuild_sorted_ids()
            self.save_index()
            print(f"[EventIndexManager] Added event: {parent_id}")
            return True

        return False

    def remove_event(self, parent_id: int) -> bool:
        """이벤트 제거

        Args:
            parent_id: 제거할 이벤트의 parent_id

        Returns:
            bool: 제거 성공 여부
        """
        if parent_id not in self.index:
            return False

        del self.index[parent_id]
        self._rebuild_sorted_ids()
        self.save_index()
        print(f"[EventIndexManager] Removed event: {parent_id}")
        return True

    def search(
        self,
        parent_include: str = None,
        parent_exclude: str = None,
        child_include: str = None,
        child_exclude: str = None,
        page_filters: Set[int] = None
    ) -> List[Dict]:
        """이벤트 검색 (인덱스 기반)

        Args:
            parent_include: Parent 태그 포함 (쉼표 구분)
            parent_exclude: Parent 태그 제외 (쉼표 구분)
            child_include: Child 태그 포함 (쉼표 구분)
            child_exclude: Child 태그 제외 (쉼표 구분)
            page_filters: 페이지 수 필터 (예: {2, 3, 4})

        Returns:
            필터링된 이벤트 리스트
        """
        results = []

        for parent_id in self.sorted_ids:
            event = self.index.get(parent_id)
            if event is None:
                continue

            # Pages 필터
            if page_filters:
                if event.get('pages', 0) not in page_filters:
                    continue

            # 태그 검색 (general 필드)
            general = event.get('general', '').lower()

            # Parent Include
            if parent_include:
                include_terms = [t.strip().lower() for t in parent_include.split(',') if t.strip()]
                if not all(term in general for term in include_terms):
                    continue

            # Parent Exclude
            if parent_exclude:
                exclude_terms = [t.strip().lower() for t in parent_exclude.split(',') if t.strip()]
                if any(term in general for term in exclude_terms):
                    continue

            # Child 태그 검색 (child_general 필드)
            child_general = event.get('child_general', '').lower()

            # Child Include
            if child_include:
                include_terms = [t.strip().lower() for t in child_include.split(',') if t.strip()]
                if not all(term in child_general for term in include_terms):
                    continue

            # Child Exclude
            if child_exclude:
                exclude_terms = [t.strip().lower() for t in child_exclude.split(',') if t.strip()]
                if any(term in child_general for term in exclude_terms):
                    continue

            results.append(event)

        return results

    def get_event(self, parent_id: int) -> Optional[Dict]:
        """특정 이벤트 조회

        Args:
            parent_id: 조회할 parent_id

        Returns:
            이벤트 정보 또는 None
        """
        return self.index.get(parent_id)

    def get_all_events(self) -> List[Dict]:
        """모든 이벤트 조회 (정렬된 순서)

        Returns:
            정렬된 이벤트 리스트
        """
        return [self.index[id_] for id_ in self.sorted_ids if id_ in self.index]

    def get_page_for_id(self, parent_id: int, items_per_page: int = 10) -> int:
        """특정 ID가 있는 페이지 번호 반환

        Args:
            parent_id: 찾을 parent_id
            items_per_page: 페이지당 항목 수

        Returns:
            페이지 번호 (0-indexed) 또는 -1 (없는 경우)
        """
        try:
            index = self.sorted_ids.index(parent_id)
            return index // items_per_page
        except ValueError:
            return -1

    def get_count(self) -> int:
        """전체 이벤트 수

        Returns:
            이벤트 수
        """
        return len(self.index)

    def get_sequence_df(self, parent_id: int) -> Optional[pd.DataFrame]:
        """특정 이벤트의 시퀀스 DataFrame 반환

        Args:
            parent_id: 조회할 parent_id

        Returns:
            시퀀스 DataFrame 또는 None
        """
        if self.searcher is None:
            return None

        try:
            return self.searcher.get_sequence(parent_id)
        except Exception as e:
            print(f"[EventIndexManager] Failed to get sequence for {parent_id}: {e}")
            return None
