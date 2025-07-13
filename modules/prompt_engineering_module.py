from PyQt6.QtWidgets import QVBoxLayout, QLabel, QWidget, QTextEdit, QCheckBox
from interfaces.base_module import BaseMiddleModule
from core.prompt_context import PromptContext
from typing import Dict, Any
import os, json

class PromptEngineeringModule(BaseMiddleModule):
    """
    🔧 프롬프트 엔지니어링/자동화 모듈
    선행/후행 프롬프트 추가, 태그 제거 등 프롬프트 엔지니어링 로직을 담당합니다.
    '파이프라인 훅' 시스템을 통해 PromptProcessor의 처리 과정에 직접 개입합니다.
    """

    def __init__(self):
        super().__init__()
        """ 위젯들을 저장할 인스턴스 변수 초기화 -> create_widget 함수에서 QWidget과 QCheckBox를 할당합니다.  """
        self.pre_textedit = None
        self.post_textedit = None
        self.auto_hide_textedit = None
        self.preprocessing_checkboxes = {}

        """ 기능이 저장/불러오기 기능을 지원하는 경우 json 파일명을 정의해야 합니다. (save는 폴더 지시자이므로 놔두도록 함) 
        save_settings, load_settings 함수가 꼭 정의되어야 하고, on_initialize에서 load_settings을 한번 수행해야 합니다.
        """
        self.settings_file = os.path.join('save', 'PromptEngineeringModule.json')

        """ 파라미터 key로 사용할 영문명 매핑 """
        self.option_key_map = {
            "랜덤 프롬프트의 작가명을 제거": "remove_author",
            "랜덤 프롬프트의 작품명을 제거": "remove_work_title",
            "랜덤 프롬프트의 캐릭터명을 제거": "remove_character_name",
            "랜덤 프롬프트의 캐릭터 특징을 제거": "remove_character_features",
            "랜덤 프롬프트의 의류 태그를 제거": "remove_clothes",
            "랜덤 프롬프트의 색상포함 태그를 제거": "remove_color",
            "랜덤 프롬프트의 장소와 배경색을 제거": "remove_location_and_background_color"
        }

    def get_title(self) -> str:
        """ Middle UI에서 나타날 헤더입니다. (추가 기능 부여 불가) """
        return "🔧 프롬프트 엔지니어링/자동화"

    def get_order(self) -> int:
        """ 다른 모듈들보다 뒤에 위치하도록 높은 순서 부여 (UI 상에서만 반영됩니다)
         목적 -> UI 위젯의 시각적 정렬 순서, 값이 낮을수록 위로감  """
        return 900

    def create_widget(self, parent: QWidget) -> QWidget:
        """ 이 부분은 가급적 유지합니다. """
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(6)

        """ 선행 고정 프롬프트 체크박스 """
        pre_label = QLabel("선행 고정 프롬프트:")

        # --- setStyleSheet은 가급적 생성형 AI 서비스를 이용하여 새롭게 꾸며주세요. --
        PEM_textbox_style = """
            QTextEdit {
                background-color: #2B2B2B;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 8px;
                color: #FFFFFF;
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-size: 22px;
            }
        """
        # --- 여기까지 setStyleSheet 작성 예시입니다. -----------------------------
        # label 같은 경우에는 특별한 이유가 없으면 parent.get_dark_style('label_style') 유지해주세요

        if parent and hasattr(parent, 'get_dark_style'):
            pre_label.setStyleSheet(parent.get_dark_style('label_style'))
        layout.addWidget(pre_label)

        self.pre_textedit = QTextEdit() # 인스턴스 변수로 저장
        self.pre_textedit.setFixedHeight(160)
        self.pre_textedit.setStyleSheet(PEM_textbox_style)
        layout.addWidget(self.pre_textedit)

        # 후행 고정 프롬프트
        post_label = QLabel("후행 고정 프롬프트:")
        if parent and hasattr(parent, 'get_dark_style'):
            post_label.setStyleSheet(parent.get_dark_style('label_style'))
        layout.addWidget(post_label)

        self.post_textedit = QTextEdit() # 인스턴스 변수로 저장
        self.post_textedit.setFixedHeight(160)
        self.post_textedit.setStyleSheet(PEM_textbox_style)
        layout.addWidget(self.post_textedit)

        # 후행 고정 프롬프트
        auto_hide_label = QLabel("자동 숨김 프롬프트:")
        if parent and hasattr(parent, 'get_dark_style'):
            auto_hide_label.setStyleSheet(parent.get_dark_style('label_style'))
        layout.addWidget(auto_hide_label)

        self.auto_hide_textedit = QTextEdit() # 인스턴스 변수로 저장
        self.auto_hide_textedit.setFixedHeight(160)
        self.auto_hide_textedit.setStyleSheet(PEM_textbox_style)
        layout.addWidget(self.auto_hide_textedit)

        # 프롬프트 전처리 옵션들
        preprocessing_label = QLabel("프롬프트 전처리 옵션:")
        if parent and hasattr(parent, 'get_dark_style'):
            preprocessing_label.setStyleSheet(parent.get_dark_style('label_style'))
        layout.addWidget(preprocessing_label)

        for text in self.option_key_map.keys():
            cb = QCheckBox(text)
            layout.addWidget(cb)
            self.preprocessing_checkboxes[text] = cb # 딕셔너리에 저장

        return widget

    def get_pipeline_hook_info(self) -> Dict[str, Any]:
        """
        get_order 함수와 다른 기능입니다. (get_order->UI상 모듈 나열 순서, this->백엔드 로직의 실행 우선순위)
        이 모듈이 'PromptProcessor' 파이프라인에 참여하도록 메타데이터를 반환합니다.
        - target_pipeline: 어느 파이프라인에 개입할지 지정합니다.
        - hook_point: 파이프라인의 어느 지점에 개입할지 지정합니다. (post_processing: 내부 처리 후)
        - priority: 같은 지점의 다른 훅들 사이에서의 실행 순서입니다. (숫자가 낮을수록 먼저 실행)
        """
        return {
            'target_pipeline': 'PromptProcessor',
            'hook_point': 'post_processing',
            'priority': 10 
        }
    
    def execute_pipeline_hook(self, context: PromptContext) -> PromptContext:
        """
        [핵심 로직] PromptProcessor로부터 PromptContext를 받아 직접 수정합니다.
        """
        print("🔧 프롬프트 엔지니어링 훅 실행...")

        options = self.get_parameters()

        # 메인UI의 전역 데이터 파이프라인에 접근
        filter_manager = self.context.filter_data_manager

        # 1. 선행/후행 프롬프트 추가
        _prefix_tags = options["pre_prompt"]
        _postfix_tags = options["post_prompt"]
        
        # context의 태그 리스트 앞/뒤에 추가
        prefix_tags = _prefix_tags + context.prefix_tags
        postfix_tags = context.postfix_tags + _postfix_tags
        main_tags = context.main_tags
        removed_tags = context.removed_tags
        source_row = context.source_row #Pandas 시리즈 객체입니다. 접근시 주의
        
        # 2. 자동 태그 제거 옵션 처리
        # 체크박스 상태를 읽어 context의 settings에 반영합니다.
        # 이 settings 값은 PromptProcessor의 다른 단계(_step_4_inject_metadata 등)에서 사용됩니다.
        checkbox_options = options["preprocessing_options"]

        #"remove_work_title"
        if not checkbox_options.get("remove_work_title"):
            copyright = source_row.get("copyright")
            if copyright: prefix_tags.insert(0, copyright)

        #"remove_author"
        if not checkbox_options.get("remove_author"):
            artist = source_row.get("artist")
            if artist: prefix_tags.insert(0, artist)

        #"remove_character_name"
        if not checkbox_options.get("remove_character_name"):
            character = source_row.get("character")
            if character: prefix_tags.insert(0, character)

        # 자동숨김프롬프트 처리
        auto_hide = options["auto_hide"]
        temp_hide_prompt = []
        
        # ~ 로 시작하는 아이템 제거
        auto_hide = [item for item in auto_hide if not item.startswith('~')]
        
        # 직접 매칭되는 키워드 제거
        for keyword in main_tags:
            if keyword in auto_hide:
                temp_hide_prompt.append(keyword)
        for keyword in temp_hide_prompt:
            main_tags.remove(keyword)
            removed_tags.append(keyword)
            
        # 패턴 매칭 처리
        to_remove = []
        for item in auto_hide:
            modified_item = item
            if item.startswith("__") and item.endswith("__"):
                # 모든 _를 제거합니다.
                modified_item = modified_item.replace("_", "")
                to_remove += [keyword for keyword in main_tags if modified_item in keyword]
            elif item.startswith("_") and item.endswith("_"):
                # 모든 _를 공백으로 대체합니다.
                modified_item = modified_item.replace("_", " ")
                to_remove += [keyword for keyword in main_tags if modified_item in keyword]
            elif item.startswith("_"):
                # 시작하는 _를 공백으로 대체합니다.
                modified_item = modified_item.replace("_", " ", 1)
                to_remove += [keyword for keyword in main_tags if modified_item in keyword]
            elif item.endswith("_"):
                # 끝나는 _를 공백으로 대체합니다.
                modified_item = " " + modified_item.rstrip("_") + " "
                to_remove += [keyword for keyword in main_tags if modified_item.strip() in keyword]
                
        # 조건에 맞는 키워드를 main_tags에서 제거합니다.
        to_remove = list(set(to_remove))
        if to_remove:
            for keyword in to_remove:
                if keyword in main_tags:
                    main_tags.remove(keyword)
                    removed_tags.append(keyword)
                    
        print(f"Auto Hide로 제거된 태그: {', '.join(removed_tags) if removed_tags else '없음'}")

        #"remove_character_features" -> RFP의 rmc 구현 -> main_tags에 적용
        if checkbox_options.get("remove_character_features"):
            characteristics = filter_manager.characteristic_list
            temp = []
            for keyword in main_tags:
                if keyword in characteristics:
                    temp.append(keyword)
            for keyword in temp:
                main_tags.remove(keyword)
                removed_tags.append(keyword)
    
        #"remove_clothes" -> RFP의 rm_clothes 구현 -> main_tags에 적용 -> filter_manager.clothes_list
        if checkbox_options.get("remove_clothes"):
            clothes = filter_manager.clothes_list
            temp = []
            for keyword in main_tags:
                if keyword in clothes:
                    temp.append(keyword)
            for keyword in temp:
                main_tags.remove(keyword)
                removed_tags.append(keyword)

        #"remove_color" -> RFP의 rm_colors 구현 -> main_tags에 적용 -> filter_manager.color_list
        if checkbox_options.get("remove_color"):
            colors = filter_manager.color_list
            temp = []
            for keyword in main_tags:
                if any(color in keyword for color in colors):
                    temp.append(keyword)
            for keyword in temp:
                main_tags.remove(keyword)
                removed_tags.append(keyword)

        #"remove_location_and_background_color" -> RFP의 rm_loc 구현 -> main_tags에 적용
        if checkbox_options.get("remove_location_and_background_color"):
            locations = ['indoors', 'outdoors', 'airplane interior', 'airport', 'apartment', 'arena', 'armory', 'bar', 'barn', 'bathroom', 'bathtub', 'bedroom', 'bell tower', 'billiard room', 'book store', 'bowling alley', 'bunker', 'bus interior', 'butcher shop', 'cafe', 'cafeteria', 'car interior', 'casino', 'castle', 'catacomb', 'changing room', 'church', 'classroom', 'closet', 'construction site', 'convenience store', 'convention hall', 'court', 'dining room', 'drugstore', 'ferris wheel', 'flower shop', 'gym', 'hangar', 'hospital', 'hotel room', 'hotel', 'infirmary', 'izakaya', 'kitchen', 'laboratory', 'library', 'living room', 'locker room', 'mall', 'messy room', 'mosque', 'movie theater', 'museum', 'nightclub', 'office', 'onsen', 'ovservatory', 'phone booth', 'planetarium', 'pool', 'prison', 'refinery', 'restaurant', 'restroom', 'rural', 'salon', 'school', 'sex shop', 'shop', 'shower room', 'skating rink', 'snowboard shop', 'spacecraft interior', 'staff room', 'stage', 'supermarket', 'throne', 'train station', 'tunnel', 'airfield', 'alley', 'amphitheater', 'aqueduct', 'bamboo forest', 'beach', 'blizzard', 'bridge', 'bus stop', 'canal', 'canyon', 'carousel', 'cave', 'cliff', 'cockpit', 'conservatory', 'cross walk', 'desert', 'dust storm', 'flower field', 'forest', 'garden', 'gas staion', 'gazebo', 'geyser', 'glacier', 'graveyard', 'harbor', 'highway', 'hill', 'island', 'jungle', 'lake', 'market', 'meadow', 'nuclear powerplant', 'oasis', 'ocean bottom', 'ocean', 'pagoda', 'parking lot', 'playground', 'pond', 'poolside', 'railroad', 'rainforest', 'rice paddy', 'roller coster', 'rooftop', 'rope bridge', 'running track', 'savannah', 'shipyard', 'shirine', 'skyscraper', 'soccor field', 'space elevator', 'stair', 'starry sky', 'swamp', 'tidal flat', 'volcano', 'waterfall', 'waterpark', 'wheat field', 'zoo', 'white background', 'simple background', 'grey background', 'gradient background', 'blue background', 'black background', 'yellow background', 'pink background', 'red background', 'brown background', 'green background', 'purple background', 'orange background']
            temp = []
            for keyword in main_tags:
                if keyword in locations:
                    temp.append(keyword)
            for keyword in temp:
                main_tags.remove(keyword)
                removed_tags.append(keyword)
        
        # 수정된 context를 다음 훅 또는 파이프라인으로 전달
        context.prefix_tags = prefix_tags
        context.postfix_tags = postfix_tags
        context.main_tags = main_tags

        return context

    def get_parameters(self) -> Dict[str, Any]:
        """
        프롬프트 엔지니어링 모듈의 현재 파라미터를 수집하여 반환합니다.
        """
        # 각 체크박스의 상태를 수집
        options = {}
        for text, checkbox in self.preprocessing_checkboxes.items():
            key = self.option_key_map.get(text, text) # 매핑된 영문 key를 사용
            options[key] = checkbox.isChecked()

        # 최종 파라미터 딕셔너리 구성
        params = {
                "pre_prompt": [tag.strip() for tag in self.pre_textedit.toPlainText().split(',') if tag.strip()],
                "post_prompt": [tag.strip() for tag in self.post_textedit.toPlainText().split(',') if tag.strip()],
                "auto_hide": [tag.strip() for tag in self.auto_hide_textedit.toPlainText().split(',') if tag.strip()],
                "preprocessing_options": options
        }
        return params

    def on_initialize(self):
        super().on_initialize()
        self.load_settings()


    def save_settings(self):
        """현재 UI 상태를 JSON 파일에 저장합니다."""
        if not all([self.pre_textedit, self.post_textedit, self.auto_hide_textedit]):
            return # UI가 아직 완전히 생성되지 않았으면 저장하지 않음

        settings = {
            "pre_prompt": self.pre_textedit.toPlainText(),
            "post_prompt": self.post_textedit.toPlainText(),
            "auto_hide_prompt": self.auto_hide_textedit.toPlainText(),
            "preprocessing_options": {
                self.option_key_map.get(text): cb.isChecked()
                for text, cb in self.preprocessing_checkboxes.items()
            }
        }
        
        try:
            os.makedirs(os.path.dirname(self.settings_file), exist_ok=True)
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"❌ '{self.get_title()}' 설정 저장 실패: {e}")

    def load_settings(self):
        """JSON 파일에서 설정을 불러와 UI에 적용합니다."""
        try:
            if not os.path.exists(self.settings_file):
                return

            with open(self.settings_file, 'r', encoding='utf-8') as f:
                settings = json.load(f)

            # 불러온 값으로 UI 업데이트
            self.pre_textedit.setText(settings.get("pre_prompt", ""))
            self.post_textedit.setText(settings.get("post_prompt", ""))
            self.auto_hide_textedit.setText(settings.get("auto_hide_prompt", ""))
            
            options = settings.get("preprocessing_options", {})
            for text, cb in self.preprocessing_checkboxes.items():
                key = self.option_key_map.get(text)
                if key in options:
                    cb.setChecked(options[key])
            
            print(f"✅ '{self.get_title()}' 설정 로드 완료.")
        except Exception as e:
            print(f"❌ '{self.get_title()}' 설정 로드 실패: {e}")