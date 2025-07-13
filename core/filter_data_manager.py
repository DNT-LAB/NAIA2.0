import os
from typing import List

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

    def load_all_filters(self):
        """정의된 모든 필터 파일을 로드합니다."""
        self.clothes_list = self._load_list_from_file('clothes_list.txt')
        self.color_list = self._load_list_from_file('color.txt')
        self.characteristic_list = self._load_list_from_file('characteristic_list.txt')