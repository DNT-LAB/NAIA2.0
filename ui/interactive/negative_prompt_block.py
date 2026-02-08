"""
Negative Prompt Block - 네거티브 프롬프트 입력용 블록
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTextEdit, QSizePolicy
)

from ui.interactive.block_widget import BlockWidget
from ui.interactive.interactive_theme import (
    COMMON_STYLES, INTERACTIVE_FONTS, FONT_FAMILY
)
from ui.scaling_manager import get_scaled_size, get_scaled_font_size


class NegativePromptBlock(BlockWidget):
    """
    네거티브 프롬프트 입력을 위한 블록 위젯
    """
    def __init__(self, parent=None):
        # 네거티브는 회색 (default) 사용
        super().__init__("네거티브 프롬프트", parent, block_type='default')
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self._init_content()

    def _init_content(self):
        layout = self.get_content_layout()

        # 라벨
        label = QLabel("네거티브 태그를 입력합니다 :")
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
        self.text_edit.setAcceptRichText(False)
        # 기본 네거티브 태그 예시
        initial_text = "lowres, bad, error, fewer, extra, missing, worst quality, jpeg artifacts, bad quality, watermark, unfinished, displeasing, chromatic aberration, signature, extra digits, artistic error, username, scan, abstract"
        self.text_edit.setPlainText(initial_text)
        
        # 필터 속성
        # self.text_edit.setProperty("autocomplete_filter", "negative") # 'negative' 필터 사용 가능하면 사용
        
        # 높이 400 설정 (요청사항)
        self.text_edit.setFixedHeight(get_scaled_size(400)) 
        
        # 스타일 적용
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

    def get_negative_prompt(self):
        """입력된 네거티브 프롬프트 반환"""
        return self.text_edit.toPlainText()

    def set_text(self, text):
        """텍스트 설정 (상태 복원용)"""
        self.text_edit.setPlainText(text)
