import os
import json
from typing import List, Dict, Set, Optional

class FilterDataManager:
    """
    data/ 디렉토리의 필터용 텍스트 파일들을 로드하고 관리하는 클래스.
    """
    def __init__(self, data_dir: str = 'data'):
        self.data_dir = data_dir

        # 각 텍스트 파일의 태그 목록을 저장할 리스트
        self.clothes_list: List[str] = []
        self.color_list: List[str] = []
        self.characteristic_list: List[str] = []

        # JSON 기반 태그 필터 (set으로 빠른 조회)
        self._location_set: Set[str] = set()
        self._expression_set: Set[str] = set()
        self._pose_action_set: Set[str] = set()
        self._meta_set: Set[str] = set()
        self._object_set: Set[str] = set()
        self._clothing_region_map: Dict[str, List[str]] = {}
        self._clothing_tag_to_region: Dict[str, str] = {}
        self._unassigned_region: str = "UNASSIGNED"

        # Noise 태그 필터링용 whitelist (빈도 > 24인 태그만 통과)
        self._valid_tag_whitelist: frozenset = frozenset()
        self._NOISE_THRESHOLD = 24

        # 클래스 생성 시 모든 파일을 로드
        self.load_all_filters()

    def _load_list_from_file(self, filename: str) -> List[str]:
        """지정된 파일에서 한 줄에 하나씩 있는 태그를 읽어 리스트로 반환합니다."""
        file_path = os.path.join(self.data_dir, filename)

        if not os.path.exists(file_path):
            print(f"⚠️ 필터 파일 없음: {file_path}")
            return []

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                # 비어있지 않은 라인만 읽어서 앞뒤 공백 제거 후 리스트에 추가
                tags = [line.strip() for line in f if line.strip()]
            print(f"✅ 필터 파일 로드 완료: {filename} ({len(tags)}개 태그)")
            return tags
        except Exception as e:
            print(f"❌ 필터 파일 로드 오류 ({filename}): {e}")
            return []

    def _load_json_tag_list(self, filename: str, subdirectory: str = 'taglist') -> dict:
        """JSON 태그 파일을 로드합니다."""
        file_path = os.path.join(self.data_dir, subdirectory, filename)

        if not os.path.exists(file_path):
            print(f"⚠️ JSON 필터 파일 없음: {file_path}")
            return {}

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            print(f"✅ JSON 필터 파일 로드 완료: {subdirectory}/{filename}")
            return data
        except Exception as e:
            print(f"❌ JSON 필터 파일 로드 오류 ({filename}): {e}")
            return {}

    def _load_json_filters(self):
        """JSON 기반 태그 필터 파일들을 로드합니다."""
        # expression_tags.json: modifiers + 모든 groups 값 flatten → set
        expr_data = self._load_json_tag_list('expression_tags.json')
        if expr_data:
            tags = set(expr_data.get('modifiers', []))
            for group_tags in expr_data.get('groups', {}).values():
                tags.update(group_tags)
            self._expression_set = tags
            print(f"  → 표정 태그: {len(self._expression_set)}개")

        # pose_action_tags.json: 모든 categories 값 flatten → set
        pose_data = self._load_json_tag_list('pose_action_tags.json')
        if pose_data:
            tags = set()
            for cat_tags in pose_data.get('categories', {}).values():
                tags.update(cat_tags)
            self._pose_action_set = tags
            print(f"  → 포즈/행동 태그: {len(self._pose_action_set)}개")

        # location_tags.json: tags → set
        loc_data = self._load_json_tag_list('location_tags.json')
        if loc_data:
            self._location_set = set(loc_data.get('tags', []))
            print(f"  → 장소 태그: {len(self._location_set)}개")

        # meta_tags.json: tags → set
        meta_data = self._load_json_tag_list('meta_tags.json')
        if meta_data:
            self._meta_set = set(meta_data.get('tags', []))
            print(f"  → 메타 태그: {len(self._meta_set)}개")

        # object_tags.json: tags → set
        obj_data = self._load_json_tag_list('object_tags.json')
        if obj_data:
            self._object_set = set(obj_data.get('tags', []))
            print(f"  → 사물 태그: {len(self._object_set)}개")

        # clothing_regions.json: regions dict 저장 + 역 매핑 생성
        region_data = self._load_json_tag_list('clothing_regions.json')
        if region_data:
            self._clothing_region_map = region_data.get('regions', {})
            self._unassigned_region = region_data.get('unassigned_region', 'UNASSIGNED')
            # 태그 → region 역 매핑 생성
            self._clothing_tag_to_region = {}
            for region, tags in self._clothing_region_map.items():
                for tag in tags:
                    self._clothing_tag_to_region[tag] = region
            print(f"  → 의류 Region: {len(self._clothing_region_map)}개 지역, "
                  f"{len(self._clothing_tag_to_region)}개 태그 매핑")

    def _load_tag_whitelist(self):
        """unique_tags.json 빈도 기반 + 분류 완료 태그를 합쳐 whitelist를 구성합니다."""
        file_path = os.path.join(self.data_dir, 'taglist', 'unique_tags.json')

        if not os.path.exists(file_path):
            print(f"⚠️ Whitelist 소스 파일 없음: {file_path}")
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                freq_data = json.load(f)
            freq_whitelist = {tag for tag, freq in freq_data.items() if freq > self._NOISE_THRESHOLD}

            # 분류 완료 태그는 빈도와 무관하게 whitelist 포함
            classified = set()
            classified.update(self.clothes_list)
            classified.update(self.characteristic_list)
            classified.update(self._location_set)
            classified.update(self._expression_set)
            classified.update(self._pose_action_set)
            classified.update(self._meta_set)
            classified.update(self._object_set)
            for region_tags in self._clothing_region_map.values():
                classified.update(region_tags)

            self._valid_tag_whitelist = frozenset(freq_whitelist | classified)
            exempt = len(classified - freq_whitelist)
            print(f"✅ 태그 Whitelist: {len(self._valid_tag_whitelist)}개 "
                  f"(빈도>{self._NOISE_THRESHOLD}: {len(freq_whitelist)} + 분류 예외: {exempt})")
        except Exception as e:
            print(f"❌ Whitelist 로드 오류: {e}")

    def filter_noise_tags(self, tags: List[str]) -> List[str]:
        """Whitelist에 있는 태그만 통과시킵니다. Whitelist 미로드 시 원본 반환."""
        if not self._valid_tag_whitelist:
            return tags
        return [tag for tag in tags if tag in self._valid_tag_whitelist]

    def load_all_filters(self):
        """정의된 모든 필터 파일을 로드합니다."""
        self.clothes_list = self._load_list_from_file('clothes_list.txt')
        self.color_list = self._load_list_from_file('color.txt')
        self.characteristic_list = self._load_list_from_file('characteristic_list.txt')
        self._load_json_filters()
        self._load_tag_whitelist()

    def get_clothing_region(self, tag: str) -> str:
        """의류 태그의 Region을 반환합니다. 매핑 없으면 UNASSIGNED."""
        return self._clothing_tag_to_region.get(tag, self._unassigned_region)
