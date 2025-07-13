import os
import json
import pandas as pd
from typing import List, Dict, Any
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QScrollArea, QGridLayout, QCheckBox, QTextEdit
)
from PyQt6.QtCore import Qt
from interfaces.base_module import BaseMiddleModule
from core.context import AppContext
from core.prompt_context import PromptContext
from core.wildcard_processor import WildcardProcessor
from ui.theme import DARK_STYLES

class NAID4CharacterInput(QWidget):
    """단일 캐릭터 입력을 위한 위젯 클래스"""
    def __init__(self, char_id: int, remove_callback, parent=None):
        super().__init__(parent)
        self.char_id = char_id
        self.remove_callback = remove_callback
        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.active_checkbox = QCheckBox(f"C{self.char_id}")
        self.active_checkbox.setChecked(True)
        self.active_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        layout.addWidget(self.active_checkbox)

        prompt_uc_layout = QVBoxLayout()
        self.prompt_textbox = QTextEdit()
        self.prompt_textbox.setPlaceholderText("캐릭터 프롬프트 (예: 1girl, ...)")
        self.prompt_textbox.setStyleSheet(DARK_STYLES['compact_textedit'])
        self.prompt_textbox.setFixedHeight(110)
        prompt_uc_layout.addWidget(self.prompt_textbox)

        self.uc_textbox = QTextEdit()
        self.uc_textbox.setPlaceholderText("부정 프롬프트 (UC)")
        self.uc_textbox.setStyleSheet(DARK_STYLES['compact_textedit'] + "color: #9E9E9E;")
        self.uc_textbox.setFixedHeight(50)
        prompt_uc_layout.addWidget(self.uc_textbox)
        
        layout.addLayout(prompt_uc_layout)

        remove_btn = QPushButton("❌")
        remove_btn.setFixedSize(30, 30)
        remove_btn.clicked.connect(lambda: self.remove_callback(self))
        layout.addWidget(remove_btn)

# 나머지 CharacterModule 클래스는 동일하게 유지
class CharacterModule(BaseMiddleModule):
    """👤 NAID4 캐릭터 관리 모듈"""
    
    def __init__(self):
        super().__init__()
        self.settings_file = os.path.join('save', 'CharacterModule.json')
        self.character_widgets: List[NAID4CharacterInput] = []
        self.scroll_layout: QVBoxLayout = None
        self.wildcard_processor: WildcardProcessor = None
        
        # UI 위젯 인스턴스 변수
        self.activate_checkbox: QCheckBox = None
        self.reroll_on_generate_checkbox: QCheckBox = None
        self.processed_prompt_display: QTextEdit = None
        self.last_processed_data: dict = {'characters': [], 'uc': []}

    def get_title(self) -> str:
        return "👤 NAID4 캐릭터"

    def get_order(self) -> int:
        return 3
    
    def initialize_with_context(self, context: AppContext):
        super().initialize_with_context(context)
        self.wildcard_processor = WildcardProcessor(self.context.main_window.wildcard_manager)
        self.context.subscribe("random_prompt_triggered", self.on_random_prompt_triggered)
    
    def on_initialize(self):
        super().on_initialize()
        # [수정] 위젯이 생성된 후에 load_settings 호출되도록 변경 (create_widget 마지막으로 이동)

    def create_widget(self, parent: QWidget) -> QWidget:
        widget = QWidget()
        main_layout = QVBoxLayout(widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # --- 상단 옵션 영역 ---
        options_frame = QFrame()
        # [수정] QHBoxLayout 대신 QGridLayout 사용
        options_layout = QGridLayout(options_frame)
        options_layout.setContentsMargins(0, 0, 0, 0)

        # 체크박스 및 버튼 위젯 생성 (기존과 동일)
        self.activate_checkbox = QCheckBox("캐릭터 프롬프트 옵션을 활성화 합니다. (NAID4 이상)")
        self.activate_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        
        # [수정] 체크박스 텍스트를 더 명확하게 변경
        self.reroll_on_generate_checkbox = QCheckBox("[랜덤]대신 [생성]시에 와일드카드를 개봉합니다.")
        self.reroll_on_generate_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        
        self.reroll_button = QPushButton("🔄️ 미리보기 갱신") 
        self.reroll_button.setStyleSheet(DARK_STYLES['secondary_button'])
        self.reroll_button.setFixedWidth(200) # [수정] 버튼 너비 고정
        self.reroll_button.clicked.connect(self.process_and_update_view)

        options_layout.addWidget(self.activate_checkbox, 0, 0, 1, 2)
        options_layout.addWidget(self.reroll_on_generate_checkbox, 1, 0)
        options_layout.addWidget(self.reroll_button, 1, 1)

        main_layout.addWidget(options_frame)

        # [수정] QScrollArea 제거 -> 위젯들이 담길 컨테이너와 레이아웃만 생성
        char_widgets_container = QWidget()
        self.scroll_layout = QVBoxLayout(char_widgets_container)
        self.scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_layout.setContentsMargins(0, 5, 0, 5) # 상하 여백 추가
        
        add_button = QPushButton("+ 캐릭터 추가")
        add_button.setStyleSheet(DARK_STYLES['secondary_button'])
        add_button.clicked.connect(lambda: self.add_character_widget())
        self.scroll_layout.addWidget(add_button)
        
        main_layout.addWidget(char_widgets_container)

        processed_label = QLabel("최종 적용될 캐릭터 프롬프트 (와일드카드 처리 후)")
        processed_label.setStyleSheet(DARK_STYLES['label_style'])
        main_layout.addWidget(processed_label)

        self.processed_prompt_display = QTextEdit()
        self.processed_prompt_display.setReadOnly(True)
        self.processed_prompt_display.setStyleSheet(DARK_STYLES['compact_textedit'])
        self.processed_prompt_display.setFixedHeight(240)
        main_layout.addWidget(self.processed_prompt_display)

        self.load_settings()
        if not self.character_widgets:
            self.add_character_widget()

        return widget

    def process_and_update_view(self) -> PromptContext:
        """[신규] 와일드카드를 처리하고 UI를 업데이트하는 핵심 메소드"""
        if not self.activate_checkbox or not self.activate_checkbox.isChecked():
            self.processed_prompt_display.clear()
            self.last_processed_data = {'characters': [], 'uc': []}
            return None

        temp_context = PromptContext(source_row=pd.Series(), settings={})
        processed_prompts, processed_ucs = [], []

        for widget in self.character_widgets:
            if widget.active_checkbox.isChecked():
                prompt_tags = [t.strip() for t in widget.prompt_textbox.toPlainText().split(',')]
                uc_tags = [t.strip() for t in widget.uc_textbox.toPlainText().split(',')]
                
                processed_prompts.append(', '.join(self.wildcard_processor.expand_tags(prompt_tags, temp_context)))
                processed_ucs.append(', '.join(self.wildcard_processor.expand_tags(uc_tags, temp_context)))
        
        self.last_processed_data = {'characters': processed_prompts, 'uc': processed_ucs}
        self.update_processed_display(processed_prompts, processed_ucs)
        return temp_context

    def on_random_prompt_triggered(self):
        """[신규] '랜덤 프롬프트' 버튼 클릭 시 호출되는 이벤트 핸들러"""
        # "생성 시 Reroll"이 체크되어 있지 *않을* 경우에만 와일드카드를 갱신합니다.
        if self.activate_checkbox.isChecked() and not self.reroll_on_generate_checkbox.isChecked():
            print("🔄️ 랜덤 프롬프트 요청으로 캐릭터 와일드카드를 갱신합니다.")
            self.process_and_update_view()

    def get_parameters(self) -> dict:
        """[수정] 모듈의 파라미터를 반환합니다."""
        if not self.activate_checkbox or not self.activate_checkbox.isChecked():
            return {"characters": None}

        # "생성 시 Reroll"이 체크된 경우에만 와일드카드 재처리
        if self.reroll_on_generate_checkbox.isChecked():
            temp_context = self.process_and_update_view()
        else:
            # 체크되지 않은 경우, 캐시된 마지막 결과 사용
            temp_context = None

        # 메인 컨텍스트에 와일드카드 처리 결과 병합
        if temp_context and self.context.current_prompt_context:
            self.context.current_prompt_context.wildcard_history.update(temp_context.wildcard_history)
            self.context.current_prompt_context.wildcard_state.update(temp_context.wildcard_state)

        return self.last_processed_data

    def update_processed_display(self, prompts: List[str], ucs: List[str]):
        """처리된 프롬프트를 하단 텍스트 박스에 표시합니다."""
        display_text = []
        for i, (prompt, uc) in enumerate(zip(prompts, ucs)):
            display_text.append(f"C{i+1}: {prompt}")
            display_text.append(f"UC{i+1}: {uc}\n")
        self.processed_prompt_display.setText("\n".join(display_text))

    def add_character_widget(self, prompt_text: str = "", uc_text: str = "", is_enabled: bool = True):
        char_id = len(self.character_widgets) + 1
        # [수정] 부모 위젯을 self.scroll_layout.parentWidget()으로 올바르게 참조
        char_widget = NAID4CharacterInput(char_id, self.remove_character_widget, self.scroll_layout.parentWidget())
        char_widget.prompt_textbox.setText(prompt_text)
        char_widget.uc_textbox.setText(uc_text)
        char_widget.active_checkbox.setChecked(is_enabled)
        
        self.scroll_layout.insertWidget(self.scroll_layout.count() - 1, char_widget)
        self.character_widgets.append(char_widget)
        self.update_widget_ids()

    def remove_character_widget(self, widget_to_remove):
        if len(self.character_widgets) > 1:
            self.character_widgets.remove(widget_to_remove)
            widget_to_remove.deleteLater()
            self.update_widget_ids()

    def update_widget_ids(self):
        for i, widget in enumerate(self.character_widgets):
            widget.char_id = i + 1
            widget.active_checkbox.setText(f"C{widget.char_id}")

    def save_settings(self):
        """[수정] UI 위젯이 생성되었는지 확인 후 저장"""
        if not self.activate_checkbox: return

        char_data = []
        for widget in self.character_widgets:
            char_data.append({
                "prompt": widget.prompt_textbox.toPlainText(),
                "uc": widget.uc_textbox.toPlainText(),
                "is_enabled": widget.active_checkbox.isChecked()
            })

        settings = {
            "is_active": self.activate_checkbox.isChecked(),
            "reroll_on_generate": self.reroll_on_generate_checkbox.isChecked(),
            "character_frames": char_data
        }

        try:
            os.makedirs(os.path.dirname(self.settings_file), exist_ok=True)
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"❌ '{self.get_title()}' 설정 저장 실패: {e}")

    def load_settings(self):
        """[수정] JSON 파일에서 설정을 불러올 때, 키워드 인자를 명시하여 add_character_widget을 호출합니다."""
        if not os.path.exists(self.settings_file) or not self.activate_checkbox:
            return

        try:
            with open(self.settings_file, 'r', encoding='utf-8') as f:
                settings = json.load(f)
            
            self.activate_checkbox.setChecked(settings.get("is_active", False))
            self.reroll_on_generate_checkbox.setChecked(settings.get("reroll_on_generate", False))
            
            for widget in self.character_widgets[:]:
                self.remove_character_widget(widget)
            
            char_frames = settings.get("character_frames", [])
            if not char_frames:
                self.add_character_widget() # 인자 없이 호출 -> 기본값 사용
            else:
                for frame_data in char_frames:
                    # ✅ 키워드 인자를 명시하여 각 인자에 올바른 값을 전달합니다.
                    self.add_character_widget(
                        prompt_text=frame_data.get("prompt", ""),
                        uc_text=frame_data.get("uc", ""),
                        is_enabled=frame_data.get("is_enabled", True)
                    )
            
            print(f"✅ '{self.get_title()}' 설정 로드 완료.")
        except Exception as e:
            print(f"❌ '{self.get_title()}' 설정 로드 실패: {e}")