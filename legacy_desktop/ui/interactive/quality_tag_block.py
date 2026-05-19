"""
Quality Tag Block - 퀄리티 태그 입력용 블록
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTextEdit, QSizePolicy
)

from legacy_desktop.ui.interactive.block_widget import BlockWidget
from legacy_desktop.ui.interactive.interactive_theme import (
    COMMON_STYLES, INTERACTIVE_FONTS, FONT_FAMILY
)
from legacy_desktop.ui.scaling_manager import get_scaled_size, get_scaled_font_size


class QualityTagBlock(BlockWidget):
    """
    퀄리티 태그 입력을 위한 블록 위젯
    """
    def __init__(self, parent=None):
        # 퀄리티 태그는 보라색 계열 (latent) 사용
        super().__init__("퀄리티 태그", parent, block_type='latent')
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self._init_content()

    def _init_content(self):
        layout = self.get_content_layout()

        # 라벨
        label = QLabel("퀄리티 태그를 입력합니다 :")
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
        # 기본 퀄리티 태그 예시
        initial_text = "0.25:: skindentation, watercolor (medium), realistic, no lineart ::, -0.6:: thick outlines ::, best quality, masterpiece, very absurdres, year 2024, year 2025"
        self.text_edit.setPlainText(initial_text)

        # 자동완성 데이터셋 지정 (quality 데이터셋 사용)
        self.text_edit.setProperty("autocomplete_dataset", "quality")
        self.text_edit.setProperty("autocomplete_ignore", True)
        
        # 높이 140 설정 (요청사항)
        self.text_edit.setFixedHeight(get_scaled_size(140)) 
        
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

    def get_quality_tags(self):
        """입력된 태그 반환"""
        return self.text_edit.toPlainText()

    def set_text(self, text):
        """텍스트 설정 (상태 복원용)"""
        self.text_edit.setPlainText(text)
