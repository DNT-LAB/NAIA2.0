from PyQt6.QtWidgets import QVBoxLayout, QLabel, QWidget, QTextEdit, QCheckBox
from PyQt6.QtCore import Qt
from interfaces.base_module import BaseMiddleModule
from core.prompt_context import PromptContext
from interfaces.mode_aware_module import ModeAwareModule
from ui.theme import get_dynamic_styles
from ui.scaling_manager import get_scaled_font_size
from ui.modern_menu import setModernStyle
from typing import Dict, Any
import os, json

class PromptEngineeringModule(BaseMiddleModule, ModeAwareModule):
    """
    🔧 프롬프트 엔지니어링/자동화 모듈
    선행/후행 프롬프트 추가, 태그 제거 등 프롬프트 엔지니어링 로직을 담당합니다.
    '파이프라인 훅' 시스템을 통해 PromptProcessor의 처리 과정에 직접 개입합니다.
    """

    def __init__(self):
        BaseMiddleModule.__init__(self)
        ModeAwareModule.__init__(self)

        # 🆕 ModeAwareModule 필수 속성들
        self.settings_base_filename = "PromptEngineeringModule"
        self.current_mode = "NAI"
        
        # 🆕 필수 호환성 플래그 추가
        self.NAI_compatibility = True
        self.WEBUI_compatibility = True
        
        # UI 위젯들을 저장할 인스턴스 변수 초기화
        self.pre_textedit = None
        self.post_textedit = None
        self.auto_hide_textedit = None
        self.preprocessing_checkboxes = {}

        # 기존 설정 파일 경로 유지
        self.settings_file = os.path.join('save', 'PromptEngineeringModule.json')

        # 파라미터 key로 사용할 영문명 매핑
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
        return "🔧 프롬프트 엔지니어링/자동화"

    def get_order(self) -> int:
        return 900
    
    def get_module_name(self) -> str:
        """ModeAwareModule 인터페이스 구현"""
        return self.get_title()
    
    def collect_current_settings(self) -> Dict[str, Any]:
        """현재 UI 상태에서 설정 수집"""
        if not all([self.pre_textedit, self.post_textedit, self.auto_hide_textedit]):
            return {}

        settings = {
            "pre_prompt": self.pre_textedit.toPlainText(),
            "post_prompt": self.post_textedit.toPlainText(),
            "auto_hide_prompt": self.auto_hide_textedit.toPlainText(),
            "preprocessing_options": {
                self.option_key_map.get(text): cb.isChecked()
                for text, cb in self.preprocessing_checkboxes.items()
            }
        }
        return settings
    
    def apply_settings(self, settings: Dict[str, Any]):
        """설정을 UI에 적용"""
        if not all([self.pre_textedit, self.post_textedit, self.auto_hide_textedit]):
            return

        # 텍스트 설정 적용
        self.pre_textedit.setText(settings.get("pre_prompt", ""))
        self.post_textedit.setText(settings.get("post_prompt", ""))
        self.auto_hide_textedit.setText(settings.get("auto_hide_prompt", ""))
        
        # 체크박스 설정 적용
        options = settings.get("preprocessing_options", {})
        for text, cb in self.preprocessing_checkboxes.items():
            key = self.option_key_map.get(text)
            if key in options:
                cb.setChecked(options[key])
    
    # 🆕 누락된 메서드 추가
    def initialize_with_context(self, context):
        """AppContext와 연결"""
        self.context = context  # 기존 코드에서 사용하는 self.context 유지
        self.app_context = context  # 새로운 모드 시스템용
    
    def create_widget(self, parent: QWidget) -> QWidget:
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)
        layout.setSpacing(6)

        # 동적 스타일 가져오기
        dynamic_styles = get_dynamic_styles()
        
        # 선행 고정 프롬프트
        pre_label = QLabel("선행 고정 프롬프트:")
        pre_label.setStyleSheet(dynamic_styles['label_style'])
        layout.addWidget(pre_label)

        self.pre_textedit = QTextEdit()
        self.pre_textedit.setFixedHeight(160)
        self.pre_textedit.setStyleSheet(dynamic_styles['compact_textedit'])
        setModernStyle(self.pre_textedit)
        layout.addWidget(self.pre_textedit)

        # 후행 고정 프롬프트
        post_label = QLabel("후행 고정 프롬프트:")
        post_label.setStyleSheet(dynamic_styles['label_style'])
        layout.addWidget(post_label)

        self.post_textedit = QTextEdit()
        self.post_textedit.setFixedHeight(160)
        self.post_textedit.setStyleSheet(dynamic_styles['compact_textedit'])
        setModernStyle(self.post_textedit)
        layout.addWidget(self.post_textedit)

        # 자동 숨김 프롬프트
        auto_hide_label = QLabel("자동 숨김 프롬프트:")
        auto_hide_label.setStyleSheet(dynamic_styles['label_style'])
        layout.addWidget(auto_hide_label)

        self.auto_hide_textedit = QTextEdit()
        self.auto_hide_textedit.setFixedHeight(160)
        self.auto_hide_textedit.setStyleSheet(dynamic_styles['compact_textedit'])
        setModernStyle(self.auto_hide_textedit)
        layout.addWidget(self.auto_hide_textedit)

        # 프롬프트 전처리 옵션들
        preprocessing_label = QLabel("프롬프트 전처리 옵션:")
        preprocessing_label.setStyleSheet(dynamic_styles['label_style'])
        layout.addWidget(preprocessing_label)

        for text in self.option_key_map.keys():
            cb = QCheckBox(text)
            cb.setStyleSheet(dynamic_styles['dark_checkbox'])
            layout.addWidget(cb)
            self.preprocessing_checkboxes[text] = cb

        # 🆕 생성된 위젯 저장 (가시성 제어용)
        self.widget = widget
        
        # 🆕 현재 모드에 따른 가시성 설정
        if hasattr(self, 'app_context') and self.app_context:
            current_mode = self.app_context.get_api_mode()
            should_be_visible = (
                (current_mode == "NAI" and self.NAI_compatibility) or
                (current_mode == "WEBUI" and self.WEBUI_compatibility)
            )
            widget.setVisible(should_be_visible)

        return widget

    def get_pipeline_hook_info(self) -> Dict[str, Any]:
        return {
            'target_pipeline': 'PromptProcessor',
            'hook_point': 'post_processing',
            'priority': 10 
        }
    
    def execute_pipeline_hook(self, context: PromptContext) -> PromptContext:
        """기존 파이프라인 훅 로직 유지"""
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
        source_row = context.source_row
        
        # 2. 자동 태그 제거 옵션 처리
        checkbox_options = options["preprocessing_options"]

        # "remove_work_title"
        if not checkbox_options.get("remove_work_title"):
            copyright = source_row.get("copyright")
            if copyright: prefix_tags.insert(0, copyright)

        # "remove_author"
        if not checkbox_options.get("remove_author"):
            artist = source_row.get("artist")
            if artist: prefix_tags.insert(0, artist)

        # "remove_character_name"
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
                modified_item = modified_item.replace("_", "")
                to_remove += [keyword for keyword in main_tags if modified_item in keyword]
            elif item.startswith("_") and item.endswith("_"):
                modified_item = modified_item.replace("_", " ")
                to_remove += [keyword for keyword in main_tags if modified_item in keyword]
            elif item.startswith("_"):
                modified_item = modified_item.replace("_", " ", 1)
                to_remove += [keyword for keyword in main_tags if modified_item in keyword]
            elif item.endswith("_"):
                modified_item = " " + modified_item.rstrip("_") + " "
                to_remove += [keyword for keyword in main_tags if modified_item.strip() in keyword]
                
        # 조건에 맞는 키워드를 main_tags에서 제거
        to_remove = list(set(to_remove))
        if to_remove:
            for keyword in to_remove:
                if keyword in main_tags:
                    main_tags.remove(keyword)
                    removed_tags.append(keyword)
                    
        print(f"Auto Hide로 제거된 태그: {', '.join(removed_tags) if removed_tags else '없음'}")

        # "remove_character_features"
        if checkbox_options.get("remove_character_features"):
            characteristics = filter_manager.characteristic_list
            temp = []
            for keyword in main_tags:
                if keyword in characteristics:
                    temp.append(keyword)
            for keyword in temp:
                main_tags.remove(keyword)
                removed_tags.append(keyword)
    
        # "remove_clothes"
        if checkbox_options.get("remove_clothes"):
            clothes = filter_manager.clothes_list
            temp = []
            for keyword in main_tags:
                if keyword in clothes:
                    temp.append(keyword)
            for keyword in temp:
                main_tags.remove(keyword)
                removed_tags.append(keyword)

        # "remove_color"
        if checkbox_options.get("remove_color"):
            colors = filter_manager.color_list
            temp = []
            for keyword in main_tags:
                if any(color in keyword for color in colors):
                    temp.append(keyword)
            for keyword in temp:
                main_tags.remove(keyword)
                removed_tags.append(keyword)

        # "remove_location_and_background_color"
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
        """프롬프트 엔지니어링 모듈의 현재 파라미터를 수집하여 반환합니다."""
        # 각 체크박스의 상태를 수집
        options = {}
        for text, checkbox in self.preprocessing_checkboxes.items():
            key = self.option_key_map.get(text, text)
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
        if hasattr(self, 'app_context') and self.app_context:
            print(f"✅ {self.get_title()}: AppContext 연결 완료")
            
            # 초기 가시성 설정
            current_mode = self.app_context.get_api_mode()
            if self.widget:
                self.update_visibility_for_mode(current_mode)
        self.load_mode_settings()
