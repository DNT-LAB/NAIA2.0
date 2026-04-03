# ui/virtual_prompt_engineering_tab.py
"""
가상 프롬프트 엔지니어링 탭 (Virtual Prompt Engineering Tab)

임시 생성 창 전용 프롬프트 엔지니어링 모듈 복제본입니다.
메인 UI의 PromptEngineeringModule 상태를 복사하여 독립적으로 작동합니다.
"""

from typing import Dict, Any
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QCheckBox,
    QScrollArea, QPushButton, QGridLayout
)
from PyQt6.QtCore import Qt
from ui.modern_menu import setModernStyle
from core.context import AppContext
from core.prompt_context import PromptContext
from core.tag_filter_helpers import apply_tag_filters
from ui.theme import DARK_STYLES, DARK_COLORS
from ui.scaling_manager import get_scaled_font_size, get_scaled_size


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
        self.auto_hide_toggle_btn = None
        self.auto_hide_collapsed = False
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
            "랜덤 프롬프트의 장소와 배경색을 제거": "remove_location_and_background_color",
            "랜덤 프롬프트의 표정 태그를 제거": "remove_expression",
            "랜덤 프롬프트의 포즈/행동 태그를 제거": "remove_pose_action",
            "랜덤 프롬프트의 메타 태그를 제거": "remove_meta_tags",
            "랜덤 프롬프트의 사물 태그를 제거": "remove_object_tags",
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

        # 자동 숨김 프롬프트 (접기/펼치기)
        auto_hide_header = QHBoxLayout()
        auto_hide_header.setSpacing(4)
        auto_hide_label = QLabel("자동 숨김 프롬프트:")
        auto_hide_label.setStyleSheet(dynamic_styles['label_style'])
        auto_hide_header.addWidget(auto_hide_label)
        auto_hide_header.addStretch()
        self.auto_hide_toggle_btn = QPushButton("접기")
        self.auto_hide_toggle_btn.setFixedSize(get_scaled_size(50), get_scaled_size(20))
        self.auto_hide_toggle_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 3px;
                font-size: {get_scaled_font_size(11)}px;
                padding: 0px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
        """)
        self.auto_hide_toggle_btn.clicked.connect(self._toggle_auto_hide)
        auto_hide_header.addWidget(self.auto_hide_toggle_btn)
        layout.addLayout(auto_hide_header)

        self.auto_hide_textedit = QTextEdit()
        self.auto_hide_textedit.setAcceptRichText(False)  # 서식 차단
        self.auto_hide_textedit.setFixedHeight(get_scaled_size(160))
        self.auto_hide_textedit.setStyleSheet(dynamic_styles['compact_textedit'])
        setModernStyle(self.auto_hide_textedit)
        layout.addWidget(self.auto_hide_textedit)

        # 프롬프트 전처리 옵션들 (2단 그리드)
        preprocessing_label = QLabel("프롬프트 전처리 옵션:")
        preprocessing_label.setStyleSheet(dynamic_styles['label_style'])
        layout.addWidget(preprocessing_label)

        # 연노랑색 체크박스 스타일 (작가명/작품명/캐릭터명용)
        yellow_checkbox_style = f"""
            QCheckBox {{
                background-color: transparent;
                spacing: {get_scaled_size(6)}px;
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-size: {get_scaled_font_size(14)}px;
                color: #FFFACD;
            }}
            QCheckBox::indicator {{
                width: {get_scaled_size(18)}px;
                height: {get_scaled_size(18)}px;
                border: 1px solid {DARK_COLORS['border_light']};
                border-radius: 3px;
                background-color: {DARK_COLORS['bg_secondary']};
            }}
            QCheckBox::indicator:checked {{
                background-color: {DARK_COLORS['accent_blue']};
                border-color: {DARK_COLORS['accent_blue']};
            }}
        """

        checkbox_grid = QGridLayout()
        checkbox_grid.setSpacing(get_scaled_size(4))
        checkbox_grid.setContentsMargins(0, 0, 0, 0)
        yellow_keys = {"remove_author", "remove_work_title", "remove_character_name"}
        for i, text in enumerate(self.option_key_map.keys()):
            cb = QCheckBox(text)
            key = self.option_key_map[text]
            if key in yellow_keys:
                cb.setStyleSheet(yellow_checkbox_style)
            else:
                cb.setStyleSheet(dynamic_styles['dark_checkbox'])
            row = i // 2
            col = i % 2
            checkbox_grid.addWidget(cb, row, col)
            self.preprocessing_checkboxes[text] = cb
        layout.addLayout(checkbox_grid)

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

            # 자동 숨김 프롬프트 접기 상태 복사
            if hasattr(main_module, 'auto_hide_collapsed'):
                self._set_auto_hide_collapsed(main_module.auto_hide_collapsed)
                print(f"  - 자동 숨김 접기 상태: {main_module.auto_hide_collapsed}")

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

    def _toggle_auto_hide(self):
        """자동 숨김 프롬프트 접기/펼치기 토글"""
        self._set_auto_hide_collapsed(not self.auto_hide_collapsed)

    def _set_auto_hide_collapsed(self, collapsed: bool):
        """자동 숨김 프롬프트 접기 상태 설정"""
        self.auto_hide_collapsed = collapsed
        if self.auto_hide_textedit:
            self.auto_hide_textedit.setVisible(not collapsed)
        if self.auto_hide_toggle_btn:
            self.auto_hide_toggle_btn.setText("펼치기" if collapsed else "접기")

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

            # Auto Hide + 필터 체크박스 통합 처리 (공유 헬퍼)
            auto_hide = options["auto_hide"]
            filter_result = apply_tag_filters(
                main_tags, removed_tags, checkbox_options, auto_hide,
                filter_manager, track_clothing_regions=True,
            )

            # 의류 Region 추적 결과를 metadata에 기록
            if filter_result.get('removed_clothes_by_region'):
                context.metadata['removed_clothes_by_region'] = filter_result['removed_clothes_by_region']

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
