"""
Artist Tag Block - 작가 태그 입력용 블록
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTextEdit, QSizePolicy
)

from legacy_desktop.ui.interactive.block_widget import BlockWidget
from legacy_desktop.ui.interactive.interactive_theme import (
    COMMON_STYLES, INTERACTIVE_FONTS, FONT_FAMILY
)
from legacy_desktop.ui.scaling_manager import get_scaled_size, get_scaled_font_size


class ArtistTagBlock(BlockWidget):
    """
    작가 태그 입력을 위한 블록 위젯
    """
    def __init__(self, parent=None):
        # block_type='conditioning' (보통 프롬프트/태그 관련에 사용되는 초록색 계열, 없으면 default)
        super().__init__("아티스트 태그", parent, block_type='conditioning')
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self._init_content()

    def _init_content(self):
        layout = self.get_content_layout()

        # 라벨
        label = QLabel("작가 태그만을 기입합니다 :")
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
        initial_text = "0.33::artist:qiandaiyiyu ::, 0.13::artist:cutesexyrobutts ::, 0.47::artist:dishwasher1910 ::, 0.47::artist:bm94199, artist:nixeu ::, 0.3::artist:torino aqua ::, 0.45::artist:ixy ::, 0.48::artist:quasarcake ::, 0.3::artist:kim eb ::, 0.27::artist:wanke ::, -1::artist collaboration ::"
        self.text_edit.setPlainText(initial_text)
        self.text_edit.setProperty("autocomplete_filter", "artist")
        self.text_edit.setFixedHeight(get_scaled_size(140)) # 적절한 높이 설정
        
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

    def get_tags(self):
        """입력된 태그 반환"""
        return self.text_edit.toPlainText()

    def set_text(self, text):
        """텍스트 설정 (상태 복원용)"""
        self.text_edit.setPlainText(text)
