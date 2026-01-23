"""
Main Prompt Block - 메인 프롬프트 입력용 블록
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTextEdit, QSizePolicy
)

from ui.interactive.block_widget import BlockWidget
from ui.interactive.interactive_theme import (
    COMMON_STYLES, INTERACTIVE_FONTS, FONT_FAMILY
)
from ui.scaling_manager import get_scaled_size, get_scaled_font_size


class AdditionalNegativePromptBlock(BlockWidget):
    """
    추가적으로 네거티브 처리할 태그(프롬프트) 입력을 위한 블록 위젯
    """
    def __init__(self, parent=None):
        # block_type='default' (회색 계열)
        super().__init__("추가 네거티브", parent, block_type='default')
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self._init_content()

    def _init_content(self):
        layout = self.get_content_layout()

        # 라벨
        label = QLabel("추가적으로 네거티브 처리할 태그를 입력합니다 :")
        label.setStyleSheet(f"""
            color: {COMMON_STYLES['text_primary']};
            font-family: {FONT_FAMILY};
            font-size: {get_scaled_font_size(INTERACTIVE_FONTS['label'])}px;
            font-weight: bold;
            margin-bottom: {get_scaled_size(4)}px;
        """)
        layout.addWidget(label)

        # 텍스트 에디터 (수정 가능)
        self.text_edit = QTextEdit()
        # 초기값은 비워둠 (요청 없음)
        self.text_edit.setPlaceholderText("프롬프트를 입력하세요...")
        
        # 필터 속성 설정 (general)
        # self.text_edit.setProperty("autocomplete_filter", "general")
        
        # 높이 300 설정
        self.text_edit.setMinimumHeight(get_scaled_size(300)) 
        
        # 스타일 적용 (Editable)
        self.text_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COMMON_STYLES['input_bg']};
                color: {COMMON_STYLES['text_primary']};
                border: 1px solid {COMMON_STYLES['input_border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(8)}px;
                font-family: {FONT_FAMILY};
                font-size: {get_scaled_font_size(INTERACTIVE_FONTS['content'])}px;
            }}
            QTextEdit:focus {{
                border: 1px solid {COMMON_STYLES['input_focus']};
            }}
        """)
        
        layout.addWidget(self.text_edit)

        # 상하 늘어짐 방지
        layout.addStretch()

    def get_prompt(self):
        """입력된 프롬프트 반환"""
        return self.text_edit.toPlainText()
