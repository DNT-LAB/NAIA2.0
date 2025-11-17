# ui/virtual_character_tab.py
"""
가상 캐릭터 탭 (Virtual Character Tab)

임시 생성 창 전용 캐릭터 모듈 복제본입니다.
메인 UI의 CharacterModule 상태를 복사하여 독립적으로 작동합니다.
"""

import copy
import pandas as pd
from typing import List, Dict, Any
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QScrollArea, QGridLayout, QCheckBox, QTextEdit,
    QSizePolicy
)
from PyQt6.QtCore import Qt
from ui.modern_menu import setModernStyle
from core.context import AppContext
from core.prompt_context import PromptContext
from core.wildcard_processor import WildcardProcessor
from ui.theme import DARK_STYLES, DARK_COLORS
from ui.scaling_manager import get_scaled_font_size, get_scaled_size


class VirtualCharacterInput(QWidget):
    """단일 캐릭터 입력 위젯 (검색 버튼 없음)"""

    def __init__(self, char_id: int, remove_callback, parent=None):
        super().__init__(parent)
        self.char_id = char_id
        self.remove_callback = remove_callback
        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(get_scaled_size(6))

        # 활성화 체크박스
        self.active_checkbox = QCheckBox(f"C{self.char_id}")
        self.active_checkbox.setChecked(True)
        self.active_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        layout.addWidget(self.active_checkbox)

        # 프롬프트/UC 레이아웃
        prompt_uc_layout = QVBoxLayout()

        # 캐릭터 프롬프트
        self.prompt_textbox = QTextEdit()
        self.prompt_textbox.setAcceptRichText(False)
        self.prompt_textbox.setPlaceholderText("캐릭터 프롬프트 (예: 1girl, ...)")
        self.prompt_textbox.setStyleSheet(DARK_STYLES['compact_textedit'])
        self.prompt_textbox.setMinimumHeight(get_scaled_size(110))
        setModernStyle(self.prompt_textbox)
        prompt_uc_layout.addWidget(self.prompt_textbox)

        # 부정 프롬프트 (UC)
        self.uc_textbox = QTextEdit()
        self.uc_textbox.setAcceptRichText(False)
        self.uc_textbox.setPlaceholderText("부정 프롬프트 (UC)")
        self.uc_textbox.setStyleSheet(
            DARK_STYLES['compact_textedit'] +
            f"color: {DARK_COLORS['text_secondary']};"
        )
        self.uc_textbox.setMinimumHeight(get_scaled_size(55))
        self.uc_textbox.setMaximumHeight(get_scaled_size(110))
        setModernStyle(self.uc_textbox)
        prompt_uc_layout.addWidget(self.uc_textbox)

        layout.addLayout(prompt_uc_layout)

        # 제거 버튼
        button_layout = QVBoxLayout()
        button_layout.setSpacing(get_scaled_size(4))

        remove_btn = QPushButton("❌")
        remove_btn.setFixedSize(get_scaled_size(30), get_scaled_size(30))
        remove_btn.setToolTip("캐릭터 제거")
        remove_btn.clicked.connect(lambda: self.remove_callback(self))
        button_layout.addWidget(remove_btn)

        button_layout.addStretch()
        layout.addLayout(button_layout)


class VirtualCharacterTab(QWidget):
    """
    임시 생성 창용 가상 캐릭터 탭

    CharacterModule의 UI를 복제하되, 검색 다이얼로그는 제외합니다.
    메인 UI의 CharacterModule 상태를 복사하여 초기화됩니다.
    """

    def __init__(self, app_context: AppContext, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.wildcard_processor = None
        self.character_widgets: List[VirtualCharacterInput] = []

        # UI 위젯 인스턴스 변수
        self.activate_checkbox: QCheckBox = None
        self.reroll_on_generate_checkbox: QCheckBox = None
        self.processed_prompt_display: QTextEdit = None
        self.scroll_layout: QVBoxLayout = None

        # 처리된 데이터 저장
        self.last_processed_data: dict = {'characters': [], 'uc': []}
        self.modifiable_clone: dict = {'characters': [], 'uc': []}

        self.init_ui()

    def init_ui(self):
        """UI 초기화"""
        # 🆕 전체 탭을 스크롤 가능하게 만들기
        # 메인 레이아웃 (self에 직접 설정)
        wrapper_layout = QVBoxLayout(self)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.setSpacing(0)

        # 스크롤 영역 생성
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setStyleSheet(f"""
            QScrollArea {{
                background-color: {DARK_COLORS['bg_primary']};
                border: none;
            }}
        """)

        # 스크롤 가능한 콘텐츠 컨테이너
        content_widget = QWidget()
        content_widget.setStyleSheet(f"""
            QWidget {{
                background-color: {DARK_COLORS['bg_primary']};
            }}
        """)
        content_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

        # 콘텐츠 레이아웃
        content_layout = QVBoxLayout(content_widget)
        content_layout.setSpacing(get_scaled_size(10))
        content_layout.setContentsMargins(
            get_scaled_size(12),
            get_scaled_size(12),
            get_scaled_size(12),
            get_scaled_size(12)
        )

        # --- 상단 옵션 영역 ---
        options_frame = QFrame()
        options_frame.setStyleSheet(f"background-color: {DARK_COLORS['bg_primary']};")
        options_layout = QGridLayout(options_frame)
        options_layout.setContentsMargins(0, 0, 0, 0)

        # 활성화 체크박스
        self.activate_checkbox = QCheckBox("캐릭터 프롬프트 옵션을 활성화 합니다. (NAID4 이상) - 생성큐 호환X ")
        self.activate_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])

        # Reroll 체크박스
        self.reroll_on_generate_checkbox = QCheckBox("[랜덤]대신 [생성]시에 와일드카드를 개봉합니다.")
        self.reroll_on_generate_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])

        # 미리보기 갱신 버튼
        self.reroll_button = QPushButton("🔄️ 미리보기 갱신")
        self.reroll_button.setStyleSheet(DARK_STYLES['secondary_button'])
        self.reroll_button.setFixedWidth(get_scaled_size(200))
        self.reroll_button.clicked.connect(self.process_and_update_view)

        options_layout.addWidget(self.activate_checkbox, 0, 0, 1, 2)
        options_layout.addWidget(self.reroll_on_generate_checkbox, 1, 0)
        options_layout.addWidget(self.reroll_button, 1, 1)

        content_layout.addWidget(options_frame)

        # --- 캐릭터 위젯 컨테이너 ---
        char_widgets_container = QWidget()
        char_widgets_container.setStyleSheet(f"background-color: {DARK_COLORS['bg_primary']};")
        self.scroll_layout = QVBoxLayout(char_widgets_container)
        self.scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_layout.setContentsMargins(0, get_scaled_size(5), 0, get_scaled_size(5))

        # 캐릭터 추가 버튼
        add_button = QPushButton("+ 캐릭터 추가")
        add_button.setStyleSheet(DARK_STYLES['secondary_button'])
        add_button.clicked.connect(lambda: self.add_character_widget())
        self.scroll_layout.addWidget(add_button)

        content_layout.addWidget(char_widgets_container)

        # --- 처리된 프롬프트 표시 ---
        processed_label = QLabel("최종 적용될 캐릭터 프롬프트 (와일드카드/Hook 처리 후)")
        processed_label.setStyleSheet(DARK_STYLES['label_style'])
        content_layout.addWidget(processed_label)

        self.processed_prompt_display = QTextEdit()
        self.processed_prompt_display.setAcceptRichText(False)
        self.processed_prompt_display.setReadOnly(True)
        self.processed_prompt_display.setStyleSheet(DARK_STYLES['compact_textedit'])
        self.processed_prompt_display.setFixedHeight(get_scaled_size(240))
        setModernStyle(self.processed_prompt_display)
        content_layout.addWidget(self.processed_prompt_display)

        # 콘텐츠 위젯을 스크롤 영역에 설정
        scroll_area.setWidget(content_widget)

        # 스크롤 영역을 메인 레이아웃에 추가
        wrapper_layout.addWidget(scroll_area)

        # WildcardProcessor 초기화
        if self.app_context and hasattr(self.app_context, 'main_window'):
            self.wildcard_processor = WildcardProcessor(self.app_context.main_window.wildcard_manager)

        # 기본 캐릭터 위젯 추가
        self.add_character_widget()

    def add_character_widget(self, prompt_text: str = "", uc_text: str = "", is_enabled: bool = True):
        """캐릭터 위젯 추가"""
        char_id = len(self.character_widgets) + 1
        char_widget = VirtualCharacterInput(char_id, self.remove_character_widget, self.scroll_layout.parentWidget())
        char_widget.prompt_textbox.setText(prompt_text)
        char_widget.uc_textbox.setText(uc_text)
        char_widget.active_checkbox.setChecked(is_enabled)

        self.scroll_layout.insertWidget(self.scroll_layout.count() - 1, char_widget)
        self.character_widgets.append(char_widget)
        self.update_widget_ids()

    def remove_character_widget(self, widget_to_remove):
        """캐릭터 위젯 제거 (최소 1개 유지)"""
        if len(self.character_widgets) > 1:
            self.character_widgets.remove(widget_to_remove)
            widget_to_remove.deleteLater()
            self.update_widget_ids()

    def update_widget_ids(self):
        """위젯 ID 업데이트"""
        for i, widget in enumerate(self.character_widgets):
            widget.char_id = i + 1
            widget.active_checkbox.setText(f"C{widget.char_id}")

    def get_or_create_context(self) -> PromptContext:
        """PromptContext 가져오기 또는 생성"""
        if hasattr(self, 'app_context') and self.app_context and self.app_context.current_prompt_context:
            return self.app_context.current_prompt_context
        else:
            if not hasattr(self, '_module_context') or self._module_context is None:
                self._module_context = PromptContext(source_row=pd.Series(), settings={})
            return self._module_context

    def process_and_update_view(self) -> PromptContext:
        """와일드카드를 처리하고 UI를 업데이트"""
        # 🐛 디버깅
        print(f"\n[VirtualCharacterTab] process_and_update_view() 호출됨")
        print(f"[VirtualCharacterTab] activate_checkbox.isChecked(): {self.activate_checkbox.isChecked()}")
        print(f"[VirtualCharacterTab] character_widgets 개수: {len(self.character_widgets)}")

        if not self.activate_checkbox or not self.activate_checkbox.isChecked():
            print(f"[VirtualCharacterTab] ⚠️ 체크박스 비활성화 → 빈 데이터 설정")
            self.processed_prompt_display.setPlainText("(캐릭터 옵션 비활성화)")
            self.last_processed_data = {'characters': [], 'uc': []}
            self.modifiable_clone = {'characters': [], 'uc': []}
            return self.get_or_create_context()

        context = self.get_or_create_context()
        processed_prompts = []
        processed_ucs = []

        print(f"[VirtualCharacterTab] character_widgets 처리 시작...")
        for i, widget in enumerate(self.character_widgets):
            print(f"[VirtualCharacterTab] Widget {i+1}: active={widget.active_checkbox.isChecked()}")
            if not widget.active_checkbox.isChecked():
                continue

            raw_prompt = widget.prompt_textbox.toPlainText().strip()
            raw_uc = widget.uc_textbox.toPlainText().strip()
            print(f"[VirtualCharacterTab] Widget {i+1} raw_prompt: {raw_prompt[:50] if raw_prompt else '(empty)'}")
            print(f"[VirtualCharacterTab] Widget {i+1} raw_uc: {raw_uc[:50] if raw_uc else '(empty)'}")

            # 와일드카드 처리
            if self.wildcard_processor and raw_prompt:
                # 문자열을 태그 리스트로 변환
                tag_list = [tag.strip() for tag in raw_prompt.split(',') if tag.strip()]
                # expand_tags 메서드 사용
                expanded_tags = self.wildcard_processor.expand_tags(tag_list, context)
                # 다시 문자열로 합치기
                expanded_prompt = ', '.join(expanded_tags)
            else:
                expanded_prompt = raw_prompt

            if self.wildcard_processor and raw_uc:
                # UC도 동일하게 처리
                uc_tag_list = [tag.strip() for tag in raw_uc.split(',') if tag.strip()]
                expanded_uc_tags = self.wildcard_processor.expand_tags(uc_tag_list, context)
                expanded_uc = ', '.join(expanded_uc_tags)
            else:
                expanded_uc = raw_uc

            processed_prompts.append(expanded_prompt)
            processed_ucs.append(expanded_uc)

        # 데이터 저장
        print(f"[VirtualCharacterTab] 처리 완료. processed_prompts 개수: {len(processed_prompts)}")
        print(f"[VirtualCharacterTab] processed_prompts: {processed_prompts}")
        print(f"[VirtualCharacterTab] processed_ucs: {processed_ucs}")

        self.last_processed_data = {
            'characters': processed_prompts,
            'uc': processed_ucs
        }
        self.modifiable_clone = copy.deepcopy(self.last_processed_data)

        print(f"[VirtualCharacterTab] ✅ modifiable_clone 업데이트됨: {self.modifiable_clone}")
        self.update_processed_display(processed_prompts, processed_ucs)

        return context

    def update_processed_display(self, prompts: List[str], ucs: List[str]):
        """처리된 프롬프트 표시 업데이트"""
        display_text = ""
        for i, (prompt, uc) in enumerate(zip(prompts, ucs)):
            display_text += f"C{i+1} 프롬프트: {prompt}\n"
            if uc:
                display_text += f"C{i+1} UC: {uc}\n"
            display_text += "\n"

        self.processed_prompt_display.setPlainText(display_text.strip())

    def get_parameters(self) -> dict:
        """
        생성 API 호출 시 사용할 파라미터 반환

        Returns:
            {"characters": [...], "uc": [...]} 또는 {"characters": None}

        참고: reroll_on_generate가 True인 경우, process_and_update_view()는
        TempGenerationWindow.on_generate_clicked()에서 UI 스레드에서 먼저 호출됩니다.
        """
        # 🐛 디버깅: modifiable_clone 내용 확인
        print(f"[VirtualCharacterTab] get_parameters() 호출됨")
        print(f"[VirtualCharacterTab] activate_checkbox.isChecked(): {self.activate_checkbox.isChecked()}")
        print(f"[VirtualCharacterTab] modifiable_clone: {self.modifiable_clone}")
        print(f"[VirtualCharacterTab] character_widgets 개수: {len(self.character_widgets)}")

        if not self.activate_checkbox or not self.activate_checkbox.isChecked():
            print(f"[VirtualCharacterTab] ⚠️ 체크박스 비활성화 → None 반환")
            return {"characters": None}

        print(f"[VirtualCharacterTab] ✅ modifiable_clone 반환: {self.modifiable_clone}")
        return self.modifiable_clone

    def get_display_text(self) -> str:
        """
        현재 표시 중인 캐릭터 텍스트를 하나의 문자열로 반환 (메인 UI 적용용)

        Returns:
            모든 활성화된 캐릭터의 프롬프트를 결합한 문자열
        """
        if not self.activate_checkbox or not self.activate_checkbox.isChecked():
            return ""

        combined_text = []

        for widget in self.character_widgets:
            if widget.active_checkbox.isChecked():
                prompt_text = widget.prompt_textbox.toPlainText().strip()
                if prompt_text:
                    combined_text.append(prompt_text)

        result = ', '.join(combined_text)
        print(f"[VirtualCharacterTab] get_display_text(): {len(result)} 문자 반환")
        return result

    def initialize_from_main(self, main_character_module):
        """
        메인 UI의 CharacterModule 상태를 복사

        Args:
            main_character_module: CharacterModule 인스턴스
        """
        # 🐛 디버깅
        print(f"\n[VirtualCharacterTab] initialize_from_main() 호출됨")
        if not main_character_module:
            print("⚠️ VirtualCharacterTab: CharacterModule이 제공되지 않음")
            return

        print(f"📋 VirtualCharacterTab: CharacterModule 상태 복사 중...")
        print(f"[VirtualCharacterTab] 메인 CharacterModule 타입: {type(main_character_module).__name__}")

        # 메인 모듈의 데이터 확인
        if hasattr(main_character_module, 'modifiable_clone'):
            print(f"[VirtualCharacterTab] 메인 modifiable_clone: {main_character_module.modifiable_clone}")
        if hasattr(main_character_module, 'last_processed_data'):
            print(f"[VirtualCharacterTab] 메인 last_processed_data: {main_character_module.last_processed_data}")
        if hasattr(main_character_module, 'character_widgets'):
            print(f"[VirtualCharacterTab] 메인 character_widgets 개수: {len(main_character_module.character_widgets)}")

        # 기존 위젯 제거
        for widget in self.character_widgets[:]:
            widget.deleteLater()
        self.character_widgets.clear()

        # 활성화 체크박스 상태 복사
        if hasattr(main_character_module, 'activate_checkbox') and main_character_module.activate_checkbox:
            self.activate_checkbox.setChecked(main_character_module.activate_checkbox.isChecked())

        # Reroll 체크박스 상태 복사
        if hasattr(main_character_module, 'reroll_on_generate_checkbox') and main_character_module.reroll_on_generate_checkbox:
            self.reroll_on_generate_checkbox.setChecked(
                main_character_module.reroll_on_generate_checkbox.isChecked()
            )

        # 캐릭터 위젯 복사
        if hasattr(main_character_module, 'character_widgets'):
            for main_widget in main_character_module.character_widgets:
                prompt_text = main_widget.prompt_textbox.toPlainText()
                uc_text = main_widget.uc_textbox.toPlainText()
                is_enabled = main_widget.active_checkbox.isChecked()

                self.add_character_widget(prompt_text, uc_text, is_enabled)

        # 데이터 복사
        if hasattr(main_character_module, 'last_processed_data'):
            self.last_processed_data = copy.deepcopy(main_character_module.last_processed_data)
            self.modifiable_clone = copy.deepcopy(main_character_module.modifiable_clone)
            print(f"[VirtualCharacterTab] ✅ 데이터 복사 완료")
            print(f"[VirtualCharacterTab] 복사된 last_processed_data: {self.last_processed_data}")
            print(f"[VirtualCharacterTab] 복사된 modifiable_clone: {self.modifiable_clone}")

        # 처리된 프롬프트 표시 업데이트
        if hasattr(main_character_module, 'processed_prompt_display'):
            display_text = main_character_module.processed_prompt_display.toPlainText()
            self.processed_prompt_display.setPlainText(display_text)

        print(f"✅ VirtualCharacterTab: {len(self.character_widgets)}개 캐릭터 위젯 복사 완료")
