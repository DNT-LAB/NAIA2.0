"""
EZ Mode STEP 2: Person Count Selection

Solo 모드와 Multiple 모드로 나뉘어 인물 수를 선택
"""

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                              QLabel, QComboBox, QButtonGroup, QStackedWidget)
from PyQt6.QtCore import Qt, pyqtSignal
from legacy_desktop.ui.scaling_manager import get_scaled_font_size, get_scaled_size
from legacy_desktop.ui.theme import DARK_COLORS, DARK_STYLES


class NoScrollComboBox(QComboBox):
    """마우스 휠 스크롤을 무시하는 QComboBox"""

    def wheelEvent(self, event):
        """마우스 휠 이벤트 무시"""
        event.ignore()


class EZModeStep2(QWidget):
    """STEP 2: Person Count 선택 위젯"""

    person_count_selected = pyqtSignal(str, dict)  # person_type, person_count_dict

    def __init__(self, data_manager, parent=None):
        super().__init__(parent)
        self.data_manager = data_manager
        self.current_rating = None
        self.current_person_type = None  # 'solo' or 'multiple'
        self.current_person_count = {}

        self.init_ui()
        self.setEnabled(False)  # STEP 1 완료 전까지 비활성화

    def init_ui(self):
        """UI 초기화"""
        # 고정 높이 설정
        self.setFixedHeight(get_scaled_size(280))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            get_scaled_size(8),
            get_scaled_size(6),
            get_scaled_size(8),
            get_scaled_size(6)
        )
        layout.setSpacing(get_scaled_size(4))

        # 제목
        title_label = QLabel("STEP 2: 인물 수 선택")
        title_label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(20)}px;
                font-weight: bold;
                color: {DARK_COLORS['text_primary']};
            }}
        """)
        layout.addWidget(title_label)

        # 모드 선택 버튼 (Solo / Multiple)
        mode_layout = QHBoxLayout()
        mode_layout.setSpacing(get_scaled_size(8))

        self.mode_button_group = QButtonGroup(self)
        self.mode_button_group.setExclusive(True)

        self.solo_button = QPushButton("Solo (단일 인물)")
        self.solo_button.setCheckable(True)
        self.solo_button.setMinimumHeight(get_scaled_size(40))
        self.solo_button.clicked.connect(self._on_solo_clicked)
        self.mode_button_group.addButton(self.solo_button)

        self.multiple_button = QPushButton("Multiple (다중 인물)")
        self.multiple_button.setCheckable(True)
        self.multiple_button.setMinimumHeight(get_scaled_size(40))
        self.multiple_button.clicked.connect(self._on_multiple_clicked)
        self.mode_button_group.addButton(self.multiple_button)

        # 모드 버튼 스타일
        mode_button_style = f"""
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
                border-color: {DARK_COLORS['accent_blue']};
            }}
            QPushButton:checked {{
                background-color: {DARK_COLORS['accent_blue']};
                color: white;
                border-color: {DARK_COLORS['accent_blue']};
                font-weight: bold;
            }}
        """
        self.solo_button.setStyleSheet(mode_button_style)
        self.multiple_button.setStyleSheet(mode_button_style)

        mode_layout.addWidget(self.solo_button)
        mode_layout.addWidget(self.multiple_button)
        layout.addLayout(mode_layout)

        # 스택 위젯 (Solo / Multiple 화면 전환)
        self.stack_widget = QStackedWidget()
        layout.addWidget(self.stack_widget)

        # Solo 모드 위젯
        self.solo_widget = self._create_solo_widget()
        self.stack_widget.addWidget(self.solo_widget)

        # Multiple 모드 위젯
        self.multiple_widget = self._create_multiple_widget()
        self.stack_widget.addWidget(self.multiple_widget)

        layout.addStretch()

    def _create_solo_widget(self) -> QWidget:
        """Solo 모드 위젯 생성"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, get_scaled_size(8), 0, 0)
        layout.setSpacing(get_scaled_size(8))

        # 안내문
        info_label = QLabel("단일 인물 선택:")
        info_label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(16)}px;
                color: {DARK_COLORS['text_primary']};
            }}
        """)
        layout.addWidget(info_label)

        # 콤보박스 (휠 스크롤 비활성화)
        self.solo_combo = NoScrollComboBox()
        self.solo_combo.setMinimumHeight(get_scaled_size(40))
        self.solo_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
        self.solo_combo.currentIndexChanged.connect(self._on_solo_combo_changed)
        layout.addWidget(self.solo_combo)

        layout.addStretch()
        return widget

    def _create_multiple_widget(self) -> QWidget:
        """Multiple 모드 위젯 생성"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, get_scaled_size(8), 0, 0)
        layout.setSpacing(get_scaled_size(8))

        # 안내문
        info_label = QLabel("다중 인물 구성:")
        info_label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(16)}px;
                color: {DARK_COLORS['text_primary']};
            }}
        """)
        layout.addWidget(info_label)

        # 라벨 행 (여성 / 남성 / 기타)
        labels_layout = QHBoxLayout()
        labels_layout.setSpacing(get_scaled_size(8))

        female_label = QLabel("여성")
        female_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        female_label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(16)}px;
                color: #F0E68C;
                font-weight: bold;
            }}
        """)

        male_label = QLabel("남성")
        male_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        male_label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(16)}px;
                color: #F0E68C;
                font-weight: bold;
            }}
        """)

        other_label = QLabel("기타")
        other_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        other_label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(16)}px;
                color: #F0E68C;
                font-weight: bold;
            }}
        """)

        labels_layout.addWidget(female_label)
        labels_layout.addWidget(male_label)
        labels_layout.addWidget(other_label)
        layout.addLayout(labels_layout)

        # 콤보박스 행 (휠 스크롤 비활성화)
        combos_layout = QHBoxLayout()
        combos_layout.setSpacing(get_scaled_size(8))

        self.female_combo = NoScrollComboBox()
        self.female_combo.setMinimumHeight(get_scaled_size(40))
        self.female_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
        self.female_combo.addItems(['0', '1', '2', '3', '4', '5', '6+'])

        self.male_combo = NoScrollComboBox()
        self.male_combo.setMinimumHeight(get_scaled_size(40))
        self.male_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
        self.male_combo.addItems(['0', '1', '2', '3', '4', '5', '6+'])

        self.other_combo = NoScrollComboBox()
        self.other_combo.setMinimumHeight(get_scaled_size(40))
        self.other_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
        self.other_combo.addItems(['0', '1', '2', '3', '4', '5', '6+'])

        combos_layout.addWidget(self.female_combo)
        combos_layout.addWidget(self.male_combo)
        combos_layout.addWidget(self.other_combo)
        layout.addLayout(combos_layout)

        # 적용 버튼
        self.apply_button = QPushButton("적용")
        self.apply_button.setMinimumHeight(get_scaled_size(40))
        self.apply_button.setStyleSheet(DARK_STYLES['primary_button'])
        self.apply_button.clicked.connect(self._on_apply_multiple)
        layout.addWidget(self.apply_button)

        layout.addStretch()
        return widget

    def set_rating(self, rating: str):
        """Rating 설정 (STEP 1에서 호출)"""
        self.current_rating = rating
        self.setEnabled(True)

        # Solo 콤보박스 업데이트
        self._update_solo_combo()

    def _update_solo_combo(self):
        """Solo 콤보박스 업데이트"""
        self.solo_combo.clear()

        if not self.current_rating:
            return

        # Solo person types 조회
        available_types = self.data_manager.get_available_person_types()

        # Solo 타입만 필터링
        solo_options = []
        for person_type in available_types:
            if person_type == 'solo':
                # Solo의 person counts 조회
                counts = self.data_manager.get_available_person_counts(
                    self.current_rating, 'solo'
                )
                for count_key in counts:
                    # count_key: '1girl', '1boy', '1other'
                    display_name = count_key.replace('1', '').capitalize()
                    solo_options.append((display_name, count_key))

        # 콤보박스에 추가
        for display_name, count_key in solo_options:
            self.solo_combo.addItem(display_name, count_key)

        if self.solo_combo.count() > 0:
            self.solo_combo.setCurrentIndex(0)

    def _on_solo_clicked(self):
        """Solo 모드 선택"""
        if self.solo_button.isChecked():
            self.stack_widget.setCurrentIndex(0)
            self.current_person_type = 'solo'
            # 즉시 적용
            self._on_solo_combo_changed()

    def _on_multiple_clicked(self):
        """Multiple 모드 선택"""
        if self.multiple_button.isChecked():
            self.stack_widget.setCurrentIndex(1)
            self.current_person_type = 'multiple'

    def _on_solo_combo_changed(self):
        """Solo 콤보박스 변경 이벤트"""
        if not self.solo_button.isChecked():
            return

        current_data = self.solo_combo.currentData()
        if current_data:
            # person_count 딕셔너리 생성
            self.current_person_count = {current_data: 1}

            # 시그널 발행
            self.person_count_selected.emit('solo', self.current_person_count)

            print(f"[OK] Solo person count selected: {self.current_person_count}")

    def _on_apply_multiple(self):
        """Multiple 모드 적용 버튼 클릭"""
        # 여성/남성/기타 수 가져오기
        female_count = self.female_combo.currentText()
        male_count = self.male_combo.currentText()
        other_count = self.other_combo.currentText()

        # person_count 딕셔너리 생성
        person_count = {}

        # 6+는 6으로 처리
        def parse_count(text):
            if text == '6+':
                return 6
            return int(text)

        female = parse_count(female_count)
        male = parse_count(male_count)
        other = parse_count(other_count)

        if female > 0:
            person_count[f'{female}girls' if female > 1 else '1girl'] = female
        if male > 0:
            person_count[f'{male}boys' if male > 1 else '1boy'] = male
        if other > 0:
            person_count[f'{other}others' if other > 1 else '1other'] = other

        if not person_count:
            print("[WARN] No person count selected (all 0)")
            return

        self.current_person_count = person_count

        # 시그널 발행
        self.person_count_selected.emit('multiple', self.current_person_count)

        print(f"[OK] Multiple person count selected: {self.current_person_count}")

    def get_person_type(self) -> str:
        """현재 선택된 Person Type 반환"""
        return self.current_person_type

    def get_person_count(self) -> dict:
        """현재 선택된 Person Count 반환"""
        return self.current_person_count

    def reset(self):
        """선택 초기화"""
        self.mode_button_group.setExclusive(False)
        self.solo_button.setChecked(False)
        self.multiple_button.setChecked(False)
        self.mode_button_group.setExclusive(True)

        self.solo_combo.setCurrentIndex(0)
        self.female_combo.setCurrentIndex(0)
        self.male_combo.setCurrentIndex(0)
        self.other_combo.setCurrentIndex(0)

        self.current_person_type = None
        self.current_person_count = {}
        self.current_rating = None

        self.setEnabled(False)
