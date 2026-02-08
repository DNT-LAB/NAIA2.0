# ui/virtual_prompt_engineering_tab.py
"""
가상 프롬프트 엔지니어링 탭 (Virtual Prompt Engineering Tab)

임시 생성 창 전용 프롬프트 엔지니어링 모듈 복제본입니다.
메인 UI의 PromptEngineeringModule 상태를 복사하여 독립적으로 작동합니다.
"""

from typing import Dict, Any
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTextEdit, QCheckBox, QScrollArea
)
from PyQt6.QtCore import Qt
from ui.modern_menu import setModernStyle
from core.context import AppContext
from core.prompt_context import PromptContext
from ui.theme import DARK_STYLES, DARK_COLORS
from ui.scaling_manager import get_scaled_font_size, get_scaled_size

# 색상 필터링 예외 함수 import
from modules.prompt_engineering_module import _is_color_exception


class VirtualPromptEngineeringTab(QWidget):
    """
    임시 생성 창용 가상 프롬프트 엔지니어링 탭

    PromptEngineeringModule의 UI를 복제하되, 프리셋 시스템은 제외합니다.
    메인 UI의 PromptEngineeringModule 상태를 복사하여 초기화됩니다.
    """

    def __init__(self, app_context: AppContext, parent=None):
        super().__init__(parent)
        self.app_context = app_context

        # UI 위젯 참조
        self.pre_textedit = None
        self.post_textedit = None
        self.auto_hide_textedit = None
        self.preprocessing_checkboxes = {}

        # 메인 모듈 참조 (초기화 후 설정됨)
        self.main_module = None

        # 파라미터 key 매핑 (메인 모듈과 동일)
        self.option_key_map = {
            "랜덤 프롬프트의 작가명을 제거": "remove_author",
            "랜덤 프롬프트의 작품명을 제거": "remove_work_title",
            "랜덤 프롬프트의 캐릭터명을 제거": "remove_character_name",
            "랜덤 프롬프트의 캐릭터 특징을 제거": "remove_character_features",
            "랜덤 프롬프트의 의류 태그를 제거": "remove_clothes",
            "랜덤 프롬프트의 색상포함 태그를 제거": "remove_color",
            "랜덤 프롬프트의 장소와 배경색을 제거": "remove_location_and_background_color"
        }

        self.init_ui()

    def init_ui(self):
        """UI 초기화 (VirtualCharacterTab 패턴 적용)"""
        # 🆕 전체 탭을 스크롤 가능하게 만들기
        wrapper_layout = QVBoxLayout(self)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet(f"""
            QScrollArea {{
                background-color: {DARK_COLORS['bg_primary']};
                border: none;
            }}
        """)

        content_widget = QWidget()
        content_widget.setStyleSheet(f"""
            QWidget {{
                background-color: {DARK_COLORS['bg_primary']};
            }}
        """)

        layout = QVBoxLayout(content_widget)
        layout.setSpacing(get_scaled_size(6))
        layout.setContentsMargins(
            get_scaled_size(12),
            get_scaled_size(12),
            get_scaled_size(12),
            get_scaled_size(12)
        )

        # 동적 스타일
        dynamic_styles = DARK_STYLES

        # 선행 고정 프롬프트
        pre_label = QLabel("선행 고정 프롬프트:")
        pre_label.setStyleSheet(dynamic_styles['label_style'])
        layout.addWidget(pre_label)

        self.pre_textedit = QTextEdit()
        self.pre_textedit.setAcceptRichText(False)  # ✅ 서식 차단
        self.pre_textedit.setFixedHeight(get_scaled_size(160))
        self.pre_textedit.setStyleSheet(dynamic_styles['compact_textedit'])
        setModernStyle(self.pre_textedit)
        layout.addWidget(self.pre_textedit)

        # 후행 고정 프롬프트
        post_label = QLabel("후행 고정 프롬프트:")
        post_label.setStyleSheet(dynamic_styles['label_style'])
        layout.addWidget(post_label)

        self.post_textedit = QTextEdit()
        self.post_textedit.setAcceptRichText(False)  # ✅ 서식 차단
        self.post_textedit.setFixedHeight(get_scaled_size(160))
        self.post_textedit.setStyleSheet(dynamic_styles['compact_textedit'])
        setModernStyle(self.post_textedit)
        layout.addWidget(self.post_textedit)

        # 자동 숨김 프롬프트
        auto_hide_label = QLabel("자동 숨김 프롬프트:")
        auto_hide_label.setStyleSheet(dynamic_styles['label_style'])
        layout.addWidget(auto_hide_label)

        self.auto_hide_textedit = QTextEdit()
        self.auto_hide_textedit.setAcceptRichText(False)  # ✅ 서식 차단
        self.auto_hide_textedit.setFixedHeight(get_scaled_size(160))
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

        # 하단 여백
        layout.addStretch()

        # 스크롤 영역 설정
        scroll_area.setWidget(content_widget)
        wrapper_layout.addWidget(scroll_area)

    def initialize_from_main(self, main_module):
        """
        메인 PromptEngineeringModule에서 현재 상태 복사

        Args:
            main_module: PromptEngineeringModule 인스턴스
        """
        if not main_module:
            print("[VirtualPromptEngineeringTab] ⚠️ main_module이 None입니다.")
            return

        self.main_module = main_module

        print(f"[VirtualPromptEngineeringTab] 메인 모듈에서 상태 복사 중...")

        try:
            # 텍스트 필드 복사
            if hasattr(main_module, 'pre_textedit') and main_module.pre_textedit:
                pre_text = main_module.pre_textedit.toPlainText()
                self.pre_textedit.setPlainText(pre_text)
                print(f"  - 선행 프롬프트 복사 (길이: {len(pre_text)})")

            if hasattr(main_module, 'post_textedit') and main_module.post_textedit:
                post_text = main_module.post_textedit.toPlainText()
                self.post_textedit.setPlainText(post_text)
                print(f"  - 후행 프롬프트 복사 (길이: {len(post_text)})")

            if hasattr(main_module, 'auto_hide_textedit') and main_module.auto_hide_textedit:
                auto_hide_text = main_module.auto_hide_textedit.toPlainText()
                self.auto_hide_textedit.setPlainText(auto_hide_text)
                print(f"  - 자동 숨김 프롬프트 복사 (길이: {len(auto_hide_text)})")

            # 체크박스 상태 복사
            if hasattr(main_module, 'preprocessing_checkboxes'):
                for text, main_cb in main_module.preprocessing_checkboxes.items():
                    if text in self.preprocessing_checkboxes:
                        is_checked = main_cb.isChecked()
                        self.preprocessing_checkboxes[text].setChecked(is_checked)
                        print(f"  - 체크박스 '{text}' = {is_checked}")

            print("[VirtualPromptEngineeringTab] ✅ 초기화 완료")
        except Exception as e:
            import traceback
            print(f"[VirtualPromptEngineeringTab] ❌ 초기화 실패: {e}")
            traceback.print_exc()

    def execute_manual_hook(self, context: PromptContext) -> PromptContext:
        """
        파이프라인 훅 수동 실행 (메인 모듈과 동일한 로직)

        임시 창은 AppContext 파이프라인을 우회하므로,
        on_generate_clicked()에서 UI 스레드에서 직접 호출합니다.

        Args:
            context: PromptContext

        Returns:
            수정된 PromptContext
        """
        print("🔧 [VirtualPromptEngineeringTab] 프롬프트 엔지니어링 훅 수동 실행...")

        try:
            # 현재 UI에서 파라미터 수집
            options = self._get_current_parameters()

            # 메인 UI의 전역 데이터 파이프라인 접근
            filter_manager = self.app_context.filter_data_manager

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
                copyright = source_row.get("copyright") if source_row is not None else None
                if copyright:
                    prefix_tags.insert(0, copyright)

            # "remove_author"
            if not checkbox_options.get("remove_author"):
                artist = source_row.get("artist") if source_row is not None else None
                if artist:
                    prefix_tags.insert(0, artist)

            # "remove_character_name"
            if not checkbox_options.get("remove_character_name"):
                character = source_row.get("character") if source_row is not None else None
                if character:
                    prefix_tags.insert(0, character)

            # 자동숨김프롬프트 처리
            auto_hide = options["auto_hide"]
            temp_hide_prompt = []

            # ~ 로 시작하는 아이템을 분리 (보호할 키워드들)
            protected_keywords = []
            for item in auto_hide:
                if item.startswith('~'):
                    # ~ 제거하고 보호 리스트에 추가
                    protected_keywords.append(item[1:].strip())

            # ~ 로 시작하는 아이템 제거 (auto_hide에서는 제외)
            auto_hide = [item for item in auto_hide if not item.startswith('~')]

            # 원본 tag_conversion_map (key와 value를 바꿔서 사용할 것임)
            original_tag_conversion_map = {
                'v': 'peace sign', 'double v': 'double peace', '|_|': 'bar eyes',
                '\\||/': 'open \\m/', ':|': 'neutral face', ';|': 'neutral face',
                'eyepatch bikini': 'square bikini', 'tachi-e': 'character image'
            }

            # key와 value를 바꾼 reversed map
            tag_conversion_map = {v: k for k, v in original_tag_conversion_map.items()}

            # auto_hide에 있는 항목이 reversed map의 key와 매칭되면, 해당 value도 auto_hide에 추가
            additional_auto_hide = []
            for item in auto_hide:
                if item in tag_conversion_map:
                    additional_auto_hide.append(tag_conversion_map[item])

            # 추가된 항목을 auto_hide에 병합 (중복 제거)
            auto_hide = list(set(auto_hide + additional_auto_hide))

            # 직접 매칭되는 키워드 제거 (보호된 키워드는 제외)
            for keyword in main_tags[:]:  # 복사본으로 순회
                if keyword in auto_hide:
                    # 보호된 키워드인지 확인
                    is_protected = False
                    for protected in protected_keywords:
                        if protected in keyword or keyword == protected:
                            is_protected = True
                            break

                    if not is_protected:
                        temp_hide_prompt.append(keyword)

            for keyword in temp_hide_prompt:
                if keyword in main_tags:
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

            # 보호된 키워드를 to_remove에서 제외
            to_remove = list(set(to_remove))
            if protected_keywords:
                # 보호된 키워드와 매칭되는 항목을 to_remove에서 제거
                protected_to_keep = []
                for protected in protected_keywords:
                    for keyword in to_remove[:]:  # 복사본으로 순회
                        if protected in keyword or keyword == protected:
                            protected_to_keep.append(keyword)

                # to_remove에서 보호된 키워드 제거
                for protected_item in protected_to_keep:
                    if protected_item in to_remove:
                        to_remove.remove(protected_item)

                print(f"보호된 키워드: {', '.join(protected_to_keep) if protected_to_keep else '없음'}")

            # 조건에 맞는 키워드를 main_tags에서 제거
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
                    if keyword in main_tags:
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
                    if keyword in main_tags:
                        main_tags.remove(keyword)
                        removed_tags.append(keyword)

            # "remove_color"
            if checkbox_options.get("remove_color"):
                colors = filter_manager.color_list
                temp = []
                for keyword in main_tags:
                    # 🔥 예외 패턴 체크: 색상과 무관한 태그는 필터링하지 않음
                    if _is_color_exception(keyword):
                        continue
                    if any(color in keyword for color in colors):
                        temp.append(keyword)
                for keyword in temp:
                    if keyword in main_tags:
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
                    if keyword in main_tags:
                        main_tags.remove(keyword)
                        removed_tags.append(keyword)

            # 수정된 context를 다음 훅 또는 파이프라인으로 전달
            context.prefix_tags = prefix_tags
            context.postfix_tags = postfix_tags
            context.main_tags = main_tags

            print(f"✅ [VirtualPromptEngineeringTab] 훅 실행 완료")
            print(f"  - prefix_tags: {len(prefix_tags)}개")
            print(f"  - main_tags: {len(main_tags)}개")
            print(f"  - postfix_tags: {len(postfix_tags)}개")
            print(f"  - removed_tags: {len(removed_tags)}개")

            return context
        except Exception as e:
            import traceback
            print(f"❌ [VirtualPromptEngineeringTab] 훅 실행 실패: {e}")
            traceback.print_exc()
            return context

    def _get_current_parameters(self) -> Dict[str, Any]:
        """현재 UI 상태에서 파라미터 수집"""
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
