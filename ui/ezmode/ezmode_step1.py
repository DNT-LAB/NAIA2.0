"""
EZ Mode STEP 1: Rating Selection

사용자가 콘텐츠 등급을 선택하는 위젯
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QButtonGroup
from PyQt6.QtCore import Qt, pyqtSignal
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from ui.theme import DARK_COLORS


class EZModeStep1(QWidget):
    """STEP 1: Rating 선택 위젯"""

    rating_selected = pyqtSignal(str)  # rating: 'g', 's', 'q', 'e'

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_rating = None
        self.init_ui()

    def init_ui(self):
        """UI 초기화"""
        # 고정 높이 설정
        self.setFixedHeight(get_scaled_size(230))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            get_scaled_size(8),
            get_scaled_size(6),
            get_scaled_size(8),
            get_scaled_size(6)
        )
        layout.setSpacing(get_scaled_size(4))

        # 제목
        title_label = QLabel("STEP 1: Rating 선택")
        title_label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(20)}px;
                font-weight: bold;
                color: {DARK_COLORS['text_primary']};
            }}
        """)
        layout.addWidget(title_label)

        # 안내문
        info_label = QLabel("콘텐츠 등급을 선택하세요:")
        info_label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(16)}px;
                color: {DARK_COLORS['text_primary']};
            }}
        """)
        layout.addWidget(info_label)

        # 버튼 그룹 (배타적 선택)
        self.button_group = QButtonGroup(self)
        self.button_group.setExclusive(True)

        # 버튼 컨테이너
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(get_scaled_size(8))

        # Rating 버튼 정의
        self.rating_buttons = {}
        rating_info = [
            ('g', 'General', '#4CAF50'),      # 녹색
            ('s', 'Sensitive', '#2196F3'),    # 파란색
            ('q', 'Questionable', '#FF9800'), # 주황색
            ('e', 'Explicit', '#F44336')      # 빨간색
        ]

        for rating_key, rating_label, color in rating_info:
            button = QPushButton(rating_label)
            button.setCheckable(True)
            button.setProperty('rating', rating_key)
            button.setMinimumHeight(get_scaled_size(40))

            # 버튼 스타일
            button.setStyleSheet(f"""
                QPushButton {{
                    font-size: {get_scaled_font_size(18)}px;
                    background-color: {DARK_COLORS['bg_secondary']};
                    color: {DARK_COLORS['text_primary']};
                    border: 2px solid {DARK_COLORS['border']};
                    border-radius: {get_scaled_size(4)}px;
                    padding: {get_scaled_size(8)}px;
                }}
                QPushButton:hover {{
                    background-color: {DARK_COLORS['bg_hover']};
                    border-color: {color};
                }}
                QPushButton:checked {{
                    background-color: {color};
                    color: white;
                    border-color: {color};
                    font-weight: bold;
                }}
            """)

            button.clicked.connect(self._on_rating_clicked)
            self.button_group.addButton(button)
            buttons_layout.addWidget(button)

            self.rating_buttons[rating_key] = button

        layout.addLayout(buttons_layout)

        # 설명 레이블
        self.description_label = QLabel("")
        self.description_label.setWordWrap(True)
        self.description_label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(14)}px;
                color: #F0E68C;
                padding: {get_scaled_size(8)}px;
                background-color: {DARK_COLORS['bg_tertiary']};
                border-radius: {get_scaled_size(4)}px;
            }}
        """)
        layout.addWidget(self.description_label)

        layout.addStretch()

    def _on_rating_clicked(self):
        """Rating 버튼 클릭 이벤트"""
        button = self.sender()
        if button and button.isChecked():
            rating = button.property('rating')
            self.current_rating = rating

            # 설명 업데이트
            descriptions = {
                'g': "General: 전체 이용가 콘텐츠",
                's': "Sensitive: 민감할 수 있는 콘텐츠",
                'q': "Questionable: 부적절할 수 있는 콘텐츠",
                'e': "Explicit: 성인 전용 콘텐츠"
            }
            self.description_label.setText(descriptions.get(rating, ""))

            # 시그널 발행
            self.rating_selected.emit(rating)

            print(f"[OK] Rating selected: {rating}")

    def set_rating(self, rating: str):
        """프로그래밍 방식으로 Rating 설정"""
        if rating in self.rating_buttons:
            button = self.rating_buttons[rating]
            button.setChecked(True)
            self.current_rating = rating

            # 설명 업데이트
            descriptions = {
                'g': "General: 전체 이용가 콘텐츠",
                's': "Sensitive: 민감할 수 있는 콘텐츠",
                'q': "Questionable: 부적절할 수 있는 콘텐츠",
                'e': "Explicit: 성인 전용 콘텐츠"
            }
            self.description_label.setText(descriptions.get(rating, ""))

    def get_rating(self) -> str:
        """현재 선택된 Rating 반환"""
        return self.current_rating

    def reset(self):
        """선택 초기화"""
        self.button_group.setExclusive(False)
        for button in self.rating_buttons.values():
            button.setChecked(False)
        self.button_group.setExclusive(True)

        self.current_rating = None
        self.description_label.setText("")
