class TagDataManager:
    def __init__(self):
        # 데이터 파일이 없으므로, 임시 더미 데이터로 초기화합니다.
        # 실제 파일이 있다면 아래 import 문을 활성화하세요.
        try:
            from result_dupl import generals
            from artist_dictionary import artist_dict
            from result_dict_copyright import copyright_dict
            from danbooru_character import character_dict_count
            print("✅ Tag data files loaded successfully.")
        except ImportError:
            print("⚠️ Tag data files not found. Using dummy data.")
            generals, artist_dict, copyright_dict, character_dict_count = {}, {}, {}, {}

        # find_top_matches 로직에 필요한 통합 딕셔너리 생성
        self.limited_generals = dict(list(generals.items())[:16000])
        self.limited_generals.update(dict(list(character_dict_count.items())[:15000]))
        self.limited_generals.update(artist_dict)
        self.limited_generals.update(copyright_dict)
        
        self.artist_dict = artist_dict
        self.character_dict_count = character_dict_count

    def find_top_matches(self, target_element, additional_wildcards=None):
        matching_items = []
        target_clean = target_element.strip()

        # 각 접두사에 따른 검색 로직
        if target_clean.startswith("artist:"):
            query = target_clean.replace("artist:", "")
            for key, value in self.artist_dict.items():
                if query in key:
                    matching_items.append((f"artist:{key}", value))
        elif target_clean.startswith("character:"):
            query = target_clean.replace("character:", "")
            for key, value in self.character_dict_count.items():
                if query in key:
                    matching_items.append((key, value)) # character: 접두어는 결과에 포함하지 않음
        elif (target_clean.startswith("wildcard:") or target_clean.startswith("from:")) and additional_wildcards:
            # 와일드카드 검색 로직 (기존 코드 참고)
            # 이 부분은 wildcard_dict_tree 구조에 따라 상세 구현이 필요
            query = target_clean.replace("wildcard:", "").replace("from:", "")
            for key in additional_wildcards.keys():
                if query in key:
                    matching_items.append((key, len(additional_wildcards[key])))
        else:
            # 일반 태그 검색
            for key, value in self.limited_generals.items():
                if target_clean in key:
                    matching_items.append((key, value))
        
        matching_items.sort(key=lambda x: x[1], reverse=True)
        return matching_items[:40]