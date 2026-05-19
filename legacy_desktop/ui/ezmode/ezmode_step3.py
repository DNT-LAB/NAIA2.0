"""
EZ Mode STEP 3: Special Tags Selection

카테고리에 따라 사용 가능한 Special Tags를 선택
"""

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                              QScrollArea, QPushButton, QGridLayout)
from PyQt6.QtCore import Qt, pyqtSignal
from legacy_desktop.ui.scaling_manager import get_scaled_font_size, get_scaled_size
from legacy_desktop.ui.theme import DARK_COLORS


class EZModeStep3(QWidget):
    """STEP 3: Special Tags 선택 위젯"""

    special_tags_selected = pyqtSignal(list)  # special_tags: List[str]

    def __init__(self, data_manager, parent=None):
        super().__init__(parent)
        self.data_manager = data_manager
        self.current_rating = None
        self.current_person_type = None
        self.current_person_count = {}
        self.current_special_tags = []
        self.tag_buttons = {}  # tag -> QPushButton

        self.init_ui()
        self.setEnabled(False)  # STEP 2 완료 전까지 비활성화

    def init_ui(self):
        """UI 초기화"""
        # 고정 높이 설정
        self.setFixedHeight(get_scaled_size(310))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            get_scaled_size(8),
            get_scaled_size(6),
            get_scaled_size(8),
            get_scaled_size(6)
        )
        layout.setSpacing(get_scaled_size(4))

        # 제목
        title_label = QLabel("STEP 3: Special Tags 선택 (선택사항)")
        title_label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(20)}px;
                font-weight: bold;
                color: {DARK_COLORS['text_primary']};
            }}
        """)
        layout.addWidget(title_label)

        # 안내문
        self.info_label = QLabel("특수 태그를 선택하세요 (선택사항):")
        self.info_label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(16)}px;
                color: {DARK_COLORS['text_primary']};
            }}
        """)
        layout.addWidget(self.info_label)

        # 스크롤 영역 (고정 높이)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFixedHeight(get_scaled_size(180))  # 3x3 그리드 고정 높이 (40px * 3 + spacing)
        scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
        """)

        # 스크롤 컨텐츠
        scroll_content = QWidget()
        self.tags_layout = QGridLayout(scroll_content)
        self.tags_layout.setSpacing(get_scaled_size(8))
        self.tags_layout.setContentsMargins(0, 0, 0, 0)

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        # 건너뛰기 버튼
        skip_layout = QHBoxLayout()
        skip_layout.setSpacing(get_scaled_size(8))

        self.clear_btn = QPushButton("선택 초기화")
        self.clear_btn.setMinimumHeight(get_scaled_size(35))
        self.clear_btn.clicked.connect(self._on_clear_clicked)
        self.clear_btn.setStyleSheet(f"""
            QPushButton {{
                font-size: {get_scaled_font_size(16)}px;
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 2px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(6)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
        """)

        self.skip_btn = QPushButton("건너뛰기 →")
        self.skip_btn.setMinimumHeight(get_scaled_size(35))
        self.skip_btn.clicked.connect(self._on_skip_clicked)
        self.skip_btn.setStyleSheet(f"""
            QPushButton {{
                font-size: {get_scaled_font_size(16)}px;
                background-color: {DARK_COLORS['accent_blue']};
                color: white;
                border: none;
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(6)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['accent_blue_hover']};
            }}
        """)

        skip_layout.addWidget(self.clear_btn)
        skip_layout.addWidget(self.skip_btn)
        layout.addLayout(skip_layout)

    def set_context(self, rating: str, person_type: str, person_count: dict):
        """STEP 2에서 호출: 컨텍스트 설정 및 Special Tags 옵션 로드"""
        self.current_rating = rating
        self.current_person_type = person_type
        self.current_person_count = person_count
        self.current_special_tags = []

        # UI 활성화
        self.setEnabled(True)

        # 기존 버튼 제거
        self._clear_tags_layout()

        # Special Tags 옵션 로드
        self._load_special_tags()

        print(f"[OK] STEP 3 context set: {rating}, {person_type}, {person_count}")

    def _clear_tags_layout(self):
        """태그 레이아웃 초기화"""
        while self.tags_layout.count():
            item = self.tags_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.tag_buttons.clear()

    def _load_special_tags(self):
        """Special Tags 옵션 로드 (3x4 그리드, 최대 12개)"""
        # person_count_key 생성 (예: '1girl', '2girls')
        person_count_keys = list(self.current_person_count.keys())
        if not person_count_keys:
            self.info_label.setText("사용 가능한 Special Tags가 없습니다.")
            return

        # 첫 번째 person_count_key 사용 (예: '1girl')
        person_count_key = person_count_keys[0]

        # data_manager에서 옵션 가져오기
        options = self.data_manager.get_available_options(
            self.current_rating,
            self.current_person_type,
            person_count_key
        )

        if not options:
            self.info_label.setText("사용 가능한 Special Tags가 없습니다.")
            return

        # special_tags가 있는 옵션만 필터링
        valid_options = [opt for opt in options if opt.get('special_tags')]

        if not valid_options:
            self.info_label.setText("사용 가능한 Special Tags가 없습니다.")
            return

        # 3x4 그리드 레이아웃으로 버튼 생성 (최대 12개)
        row = 0
        col = 0
        max_cols = 3  # 3열
        max_rows = 4  # 4행 (3→4로 증가)
        max_buttons = max_cols * max_rows  # 12개

        for i, option in enumerate(valid_options[:max_buttons]):
            # option 구조: {'category_id': ..., 'special_tags': [...], 'special_key': ..., 'label': ...}
            special_tags_list = option.get('special_tags', [])
            label = option.get('label', 'Unknown')
            special_key = option.get('special_key', '')

            button = QPushButton(label)
            button.setCheckable(True)
            button.setProperty('special_tags', special_tags_list)  # 리스트 저장
            button.setProperty('special_key', special_key)
            button.setMinimumHeight(get_scaled_size(40))  # 높이 증가

            # 버튼 스타일
            button.setStyleSheet(f"""
                QPushButton {{
                    font-size: {get_scaled_font_size(16)}px;
                    background-color: {DARK_COLORS['bg_secondary']};
                    color: {DARK_COLORS['text_primary']};
                    border: 2px solid {DARK_COLORS['border']};
                    border-radius: {get_scaled_size(4)}px;
                    padding: {get_scaled_size(6)}px;
                    text-align: center;
                }}
                QPushButton:hover {{
                    background-color: {DARK_COLORS['bg_hover']};
                    border-color: {DARK_COLORS['accent_blue']};
                }}
                QPushButton:checked {{
                    background-color: {DARK_COLORS['accent_blue']};
                    color: white;
                    border-color: {DARK_COLORS['accent_blue']};
                    font-weight: bold;
                }}
                QPushButton:disabled {{
                    background-color: {DARK_COLORS['bg_tertiary']};
                    color: {DARK_COLORS['text_disabled']};
                    border-color: {DARK_COLORS['border']};
                }}
            """)

            button.clicked.connect(self._on_tag_button_clicked)
            self.tags_layout.addWidget(button, row, col)
            self.tag_buttons[special_key] = button  # special_key를 키로 사용

            col += 1
            if col >= max_cols:
                col = 0
                row += 1

        # 안내문 업데이트
        if len(valid_options) > 0:
            self.info_label.setText(f"사용 가능한 Special Tags: {len(valid_options)}개 (단일 선택)")
        else:
            self.info_label.setText("사용 가능한 Special Tags가 없습니다.")

    def _on_tag_button_clicked(self):
        """태그 버튼 클릭 이벤트 (단일 카테고리 선택)"""
        # 클릭된 버튼 찾기
        clicked_button = self.sender()
        if not clicked_button:
            return

        # 다른 모든 버튼 체크 해제 (단일 선택)
        for button in self.tag_buttons.values():
            if button != clicked_button:
                button.setChecked(False)

        # 선택된 태그 수집
        self.current_special_tags = []

        if clicked_button.isChecked():
            # 체크된 버튼의 special_tags 가져오기
            # 이 리스트는 해당 카테고리의 모든 special tags를 포함
            # 예: ['large_breasts'], ['furry'], 또는 ['furry', 'loli'] 등
            special_tags_list = clicked_button.property('special_tags')
            if special_tags_list:
                self.current_special_tags = special_tags_list

        # 시그널 발행
        self.special_tags_selected.emit(self.current_special_tags)

        print(f"[OK] Special tags selected: {self.current_special_tags}")

    def _on_clear_clicked(self):
        """선택 초기화 버튼 클릭"""
        for button in self.tag_buttons.values():
            button.setChecked(False)

        self.current_special_tags = []
        self.special_tags_selected.emit(self.current_special_tags)

        print("[OK] Special tags cleared")

    def _on_skip_clicked(self):
        """건너뛰기 버튼 클릭"""
        # 선택 초기화
        self._on_clear_clicked()

        # STEP 4로 진행 시그널 발행 (빈 리스트)
        self.special_tags_selected.emit([])

        print("[OK] STEP 3 skipped")

    def get_special_tags(self) -> list:
        """현재 선택된 Special Tags 반환"""
        return self.current_special_tags

    def reset(self):
        """선택 초기화"""
        self._clear_tags_layout()
        self.current_rating = None
        self.current_person_type = None
        self.current_person_count = {}
        self.current_special_tags = []
        self.setEnabled(False)
        self.info_label.setText("특수 태그를 선택하세요 (선택사항):")
