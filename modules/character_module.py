import os
import json
import copy
import pandas as pd
from typing import List, Dict, Any
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QScrollArea, QGridLayout, QCheckBox, QTextEdit
)
from PyQt6.QtCore import Qt
from ui.modern_menu import setModernStyle
from interfaces.base_module import BaseMiddleModule
from interfaces.mode_aware_module import ModeAwareModule
from core.context import AppContext
from core.prompt_context import PromptContext
from core.wildcard_processor import WildcardProcessor
from ui.theme import DARK_STYLES

class NAID4CharacterInput(QWidget):
    """단일 캐릭터 입력을 위한 위젯 클래스"""
    def __init__(self, char_id: int, remove_callback, app_context=None, parent=None):
        super().__init__(parent)
        self.char_id = char_id
        self.remove_callback = remove_callback
        self.app_context = app_context
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
        setModernStyle(self.prompt_textbox)
        prompt_uc_layout.addWidget(self.prompt_textbox)

        self.uc_textbox = QTextEdit()
        self.uc_textbox.setPlaceholderText("부정 프롬프트 (UC)")
        self.uc_textbox.setStyleSheet(DARK_STYLES['compact_textedit'] + "color: #9E9E9E;")
        self.uc_textbox.setFixedHeight(50)
        setModernStyle(self.uc_textbox)
        prompt_uc_layout.addWidget(self.uc_textbox)
        
        layout.addLayout(prompt_uc_layout)

        remove_btn = QPushButton("❌")
        remove_btn.setFixedSize(30, 30)
        remove_btn.clicked.connect(lambda: self.remove_callback(self))
        layout.addWidget(remove_btn)
    

class CharacterModule(BaseMiddleModule, ModeAwareModule):
    def __init__(self):
        BaseMiddleModule.__init__(self)
        ModeAwareModule.__init__(self)
        
        # 🆕 ModeAwareModule 필수 속성들
        self.settings_base_filename = "CharacterModule"
        self.current_mode = "NAI"  # 기본값
        
        # 🆕 호환성 설정 (NAI만 호환, WEBUI 비호환)
        self.NAI_compatibility = True
        self.WEBUI_compatibility = False
        self.COMFYUI_compatibility = False
        
        # 기존 속성들
        self.scroll_layout: QVBoxLayout = None
        self.wildcard_processor: WildcardProcessor = None
        self.character_widgets: List[NAID4CharacterInput] = []  # 🆕 누락된 속성 추가
        
        # UI 위젯 인스턴스 변수
        self.activate_checkbox: QCheckBox = None
        self.reroll_on_generate_checkbox: QCheckBox = None
        self.processed_prompt_display: QTextEdit = None
        self.last_processed_data: dict = {'characters': [], 'uc': []}
        self.modifiable_clone: dict = {'characters': [], 'uc': []}

    def get_title(self) -> str:
        return "👤 NAID4 캐릭터"

    def get_order(self) -> int:
        return 3
    
    def get_module_name(self) -> str:
        """ModeAwareModule 인터페이스 구현"""
        return self.get_title()
    
    def initialize_with_context(self, context: AppContext):
        """기존 메서드 유지"""
        self.app_context = context  # 🆕 app_context 설정
        self.wildcard_processor = WildcardProcessor(context.main_window.wildcard_manager)
        context.subscribe("random_prompt_triggered", self.on_random_prompt_triggered)
    
    def on_initialize(self):
        if hasattr(self, 'app_context') and self.app_context:
            # 모드 변경 이벤트는 이미 ModeAwareModuleManager에서 자동 구독됨
            print(f"✅ {self.get_title()}: AppContext 연결 완료")
            
            # 초기 가시성 설정
            current_mode = self.app_context.get_api_mode()
            if self.widget:
                self.update_visibility_for_mode(current_mode)

    def collect_current_settings(self) -> Dict[str, Any]:
        """현재 UI 상태에서 설정 수집"""
        if not self.activate_checkbox:
            return {}
        
        char_data = []
        for widget in self.character_widgets:
            char_data.append({
                "prompt": widget.prompt_textbox.toPlainText(),
                "uc": widget.uc_textbox.toPlainText(),
                "is_enabled": widget.active_checkbox.isChecked()
            })
        
        return {
            "is_active": self.activate_checkbox.isChecked(),
            "reroll_on_generate": self.reroll_on_generate_checkbox.isChecked() if self.reroll_on_generate_checkbox else False,
            "character_frames": char_data
        }
    
    def apply_settings(self, settings: Dict[str, Any]):
        """설정을 UI에 적용"""
        if not self.activate_checkbox:
            return
            
        self.activate_checkbox.setChecked(settings.get("is_active", False))
        
        if self.reroll_on_generate_checkbox:
            self.reroll_on_generate_checkbox.setChecked(settings.get("reroll_on_generate", False))
        
        # 기존 캐릭터 위젯들 제거
        for widget in self.character_widgets[:]:
            self._remove_character_widget_internal(widget)
        
        # 캐릭터 프레임 복원
        character_frames_data = settings.get("character_frames", [])
        if not character_frames_data:
            self.add_character_widget()  # 기본 위젯 하나 추가
        else:
            for frame_data in character_frames_data:
                self.add_character_widget(
                    prompt_text=frame_data.get("prompt", ""),
                    uc_text=frame_data.get("uc", ""),
                    is_enabled=frame_data.get("is_enabled", True)
                )

    def create_widget(self, parent: QWidget) -> QWidget:
        widget = QWidget(parent)
        main_layout = QVBoxLayout(widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # --- 상단 옵션 영역 ---
        options_frame = QFrame(widget)
        options_layout = QGridLayout(options_frame)
        options_layout.setContentsMargins(0, 0, 0, 0)

        # 체크박스 및 버튼 위젯 생성
        self.activate_checkbox = QCheckBox("캐릭터 프롬프트 옵션을 활성화 합니다. (NAID4 이상)")
        self.activate_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        
        self.reroll_on_generate_checkbox = QCheckBox("[랜덤]대신 [생성]시에 와일드카드를 개봉합니다.")
        self.reroll_on_generate_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])
        
        self.reroll_button = QPushButton("🔄️ 미리보기 갱신") 
        self.reroll_button.setStyleSheet(DARK_STYLES['secondary_button'])
        self.reroll_button.setFixedWidth(200)
        self.reroll_button.clicked.connect(self.process_and_update_view)

        options_layout.addWidget(self.activate_checkbox, 0, 0, 1, 2)
        options_layout.addWidget(self.reroll_on_generate_checkbox, 1, 0)
        options_layout.addWidget(self.reroll_button, 1, 1)

        main_layout.addWidget(options_frame)

        # 캐릭터 위젯 컨테이너
        char_widgets_container = QWidget(widget)
        self.scroll_layout = QVBoxLayout(char_widgets_container)
        self.scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_layout.setContentsMargins(0, 5, 0, 5)
        
        add_button = QPushButton("+ 캐릭터 추가")
        add_button.setStyleSheet(DARK_STYLES['secondary_button'])
        add_button.clicked.connect(lambda: self.add_character_widget())
        self.scroll_layout.addWidget(add_button)
        
        main_layout.addWidget(char_widgets_container)

        processed_label = QLabel("최종 적용될 캐릭터 프롬프트 (와일드카드/Hook 처리 후)")
        processed_label.setStyleSheet(DARK_STYLES['label_style'])
        main_layout.addWidget(processed_label)

        self.processed_prompt_display = QTextEdit()
        self.processed_prompt_display.setReadOnly(True)
        self.processed_prompt_display.setStyleSheet(DARK_STYLES['compact_textedit'])
        self.processed_prompt_display.setFixedHeight(240)
        setModernStyle(self.processed_prompt_display)
        main_layout.addWidget(self.processed_prompt_display)

        # 🆕 생성된 위젯 저장 (가시성 제어용)
        self.widget = widget
        
        # 🆕 UI 생성 완료 후 즉시 가시성 설정
        if hasattr(self, 'app_context') and self.app_context:
            current_mode = self.app_context.get_api_mode()
            should_be_visible = self.is_compatible_with_mode(current_mode)
            widget.setVisible(should_be_visible)
            print(f"🔍 CharacterModule 초기 가시성: {should_be_visible} (모드: {current_mode})")
        
        # 모드별 설정 로드
        self.load_mode_settings()
        
        # 기본 캐릭터 위젯 추가
        if not self.character_widgets:
            self.add_character_widget()

        return widget

    def get_or_create_context(self) -> PromptContext:
        """순차 와일드카드 상태를 유지하기 위해 공유 컨텍스트를 가져오거나 생성합니다."""
        if hasattr(self, 'app_context') and self.app_context and self.app_context.current_prompt_context:
            # 메인 애플리케이션의 공유 컨텍스트가 있으면 사용
            return self.app_context.current_prompt_context
        else:
            # 없으면 모듈 전용 컨텍스트를 생성/재사용 (순차 카운터 보존)
            if not hasattr(self, '_module_context') or self._module_context is None:
                self._module_context = PromptContext(source_row=pd.Series(), settings={})
            return self._module_context

    def process_and_update_view(self) -> PromptContext:
        """와일드카드를 처리하고 UI를 업데이트하는 핵심 메소드"""
        if not self.activate_checkbox or not self.activate_checkbox.isChecked():
            self.processed_prompt_display.clear()
            self.last_processed_data = {'characters': [], 'uc': []}
            self.modifiable_clone = {'characters': [], 'uc': []} # ⬅️ 비활성화 시 복제본도 초기화
            return None

        # 🔧 [수정] 공유 컨텍스트 사용으로 순차 와일드카드 상태 보존
        context = self.get_or_create_context()
        processed_prompts, processed_ucs = [], []

        for widget in self.character_widgets:
            if widget.active_checkbox.isChecked():
                prompt_tags = [t.strip() for t in widget.prompt_textbox.toPlainText().split(',')]
                uc_tags = [t.strip() for t in widget.uc_textbox.toPlainText().split(',')]
                
                processed_prompts.append(', '.join(self.wildcard_processor.expand_tags(prompt_tags, context)))
                processed_ucs.append(', '.join(self.wildcard_processor.expand_tags(uc_tags, context)))
        
        self.last_processed_data = {'characters': processed_prompts, 'uc': processed_ucs}
        self.modifiable_clone = copy.deepcopy(self.last_processed_data)
        self.update_processed_display(processed_prompts, processed_ucs)
        return context

    def on_random_prompt_triggered(self):
        """'랜덤 프롬프트' 버튼 클릭 시 호출되는 이벤트 핸들러"""
        if self.activate_checkbox.isChecked() and not self.reroll_on_generate_checkbox.isChecked():
            print("🔄️ 랜덤 프롬프트 요청으로 캐릭터 와일드카드를 갱신합니다.")
            self.process_and_update_view()

    def get_parameters(self) -> dict:
        """모듈의 파라미터를 반환합니다."""
        if not self.activate_checkbox or not self.activate_checkbox.isChecked():
            return {"characters": None}

        return self.modifiable_clone
    
    def hooker_update_prompt(self):
        # ⬇️ Hooker에 의해 수정된 최종 결과를 UI에 업데이트하는 로직 추가
        if self.modifiable_clone:
            final_prompts = self.modifiable_clone.get('characters', [])
            final_ucs = self.modifiable_clone.get('uc', [])
            self.update_processed_display(final_prompts, final_ucs)

    def update_processed_display(self, prompts: List[str], ucs: List[str]):
        """처리된 프롬프트를 하단 텍스트 박스에 표시합니다."""
        display_text = []
        for i, (prompt, uc) in enumerate(zip(prompts, ucs)):
            display_text.append(f"C{i+1}: {prompt}")
            display_text.append(f"UC{i+1}: {uc}\n")
        self.processed_prompt_display.setText("\n".join(display_text))

    def add_character_widget(self, prompt_text: str = "", uc_text: str = "", is_enabled: bool = True):
        char_id = len(self.character_widgets) + 1
        char_widget = NAID4CharacterInput(char_id, self.remove_character_widget, self.app_context, self.scroll_layout.parentWidget())
        char_widget.prompt_textbox.setText(prompt_text)
        char_widget.uc_textbox.setText(uc_text)
        char_widget.active_checkbox.setChecked(is_enabled)
        
        self.scroll_layout.insertWidget(self.scroll_layout.count() - 1, char_widget)
        self.character_widgets.append(char_widget)
        self.update_widget_ids()

    def _remove_character_widget_internal(self, widget_to_remove):
        """내부용 위젯 제거 메서드 (최소 개수 제한 없음)"""
        if widget_to_remove in self.character_widgets:
            self.character_widgets.remove(widget_to_remove)
            widget_to_remove.deleteLater()
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