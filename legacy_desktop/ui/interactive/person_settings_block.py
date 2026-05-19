"""
Person Settings Block - 인원수 및 이미지 목적 설정 위젯
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QButtonGroup, QRadioButton, QTextEdit, QFrame,
    QSizePolicy, QCheckBox
)
from PyQt6.QtCore import Qt, pyqtSignal

from legacy_desktop.ui.interactive.block_widget import BlockWidget
from legacy_desktop.ui.interactive.interactive_theme import (
    COMMON_STYLES, INTERACTIVE_FONTS, FONT_FAMILY,
    get_readonly_text_style
)
from legacy_desktop.ui.scaling_manager import get_scaled_size, get_scaled_font_size


class CountControl(QWidget):
    """
    [Label] [MinBtn] [Value] [PlusBtn] 형태의 인원수 조절 위젯 (컴팩트 스타일)
    """
    valueChanged = pyqtSignal(int)

    def __init__(self, label_text, max_value=6, initial_value=0, parent=None):
        super().__init__(parent)
        self.label_text = label_text
        self.max_value = max_value
        self.value = initial_value
        self._init_ui()

    def _init_ui(self):
        # 수직 정렬로 레이블을 위로 올리거나, 수평으로 두되 컴팩트하게
        # 여기서는 "Label [-] 0 [+]" 형태의 수평 배치를 최대한 타이트하게 구성
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(get_scaled_size(4))

        # 라벨 (Bold)
        self.label = QLabel(self.label_text)
        self.label.setStyleSheet(f"""
            color: {COMMON_STYLES['text_primary']};
            font-family: {FONT_FAMILY};
            font-size: {get_scaled_font_size(INTERACTIVE_FONTS['label'])}px;
            font-weight: bold;
        """)
        
        # 컨트롤 버튼 스타일 (좁고 명확한 테두리)
        btn_style = f"""
            QPushButton {{
                background-color: #4A4A4A;
                color: #FFFFFF;
                border: 1px solid #666666;
                border-radius: {get_scaled_size(3)}px;
                font-family: {FONT_FAMILY};
                font-size: {get_scaled_font_size(INTERACTIVE_FONTS['tiny'])}px;
                font-weight: bold;
                min-width: {get_scaled_size(20)}px;
                min-height: {get_scaled_size(20)}px;
                padding: {get_scaled_size(2)}px;
            }}
            QPushButton:hover {{
                border: 1px solid #888888;
                background-color: #5A5A5A; 
            }}
            QPushButton:pressed {{
                background-color: #333333;
            }}
        """

        # 감소 버튼
        self.btn_minus = QPushButton("◀")
        self.btn_minus.setStyleSheet(btn_style)
        self.btn_minus.setFixedSize(get_scaled_size(20), get_scaled_size(24))
        self.btn_minus.clicked.connect(self._decrease)

        # 값 표시 (흰 배경, 검은 글씨)
        self.value_label = QLabel(str(self.value))
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value_label.setFixedWidth(get_scaled_size(32)) # 너비 줄임
        self.value_label.setFixedHeight(get_scaled_size(24))
        self.value_label.setStyleSheet(f"""
            color: #000000;
            font-family: {FONT_FAMILY};
            font-size: {get_scaled_font_size(INTERACTIVE_FONTS['content'])}px;
            font-weight: bold;
            background-color: #FFFFFF;
            border: 1px solid #CCCCCC;
            border-radius: {get_scaled_size(4)}px;
        """)

        # 증가 버튼
        self.btn_plus = QPushButton("▶")
        self.btn_plus.setStyleSheet(btn_style)
        self.btn_plus.setFixedSize(get_scaled_size(20), get_scaled_size(24))
        self.btn_plus.clicked.connect(self._increase)

        layout.addWidget(self.label)
        layout.addWidget(self.btn_minus)
        layout.addWidget(self.value_label)
        layout.addWidget(self.btn_plus)

    def _decrease(self):
        if self.value > 0:
            self.value -= 1
            self._update_display()
            self.valueChanged.emit(self.value)

    def _increase(self):
        if self.value < self.max_value:
            self.value += 1
            self._update_display()
            self.valueChanged.emit(self.value)

    def _update_display(self):
        self.value_label.setText(str(self.value))
    
    def get_value(self):
        return self.value


class ImageRatingButton(QPushButton):
    """스타일 적용된 토글 버튼 (라디오 버튼 대체)"""
    def __init__(self, text, value, parent=None):
        super().__init__(text, parent)
        self.value = value
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(get_scaled_size(32))
        self.setObjectName("rating_btn")  # 스타일 충돌 방지용 ID
        
        # 스타일 정의
        self.setStyleSheet(f"""
            QPushButton#rating_btn {{
                background-color: {COMMON_STYLES['input_bg']};
                color: {COMMON_STYLES['text_secondary']};
                border: 1px solid {COMMON_STYLES['input_border']};
                border-radius: {get_scaled_size(4)}px;
                font-family: {FONT_FAMILY};
                font-size: {get_scaled_font_size(INTERACTIVE_FONTS['tiny'])}px;
                font-weight: 500;
                padding: 0px; 
            }}
            QPushButton#rating_btn:hover {{
                border: 1px solid {COMMON_STYLES['text_secondary']};
                background-color: {COMMON_STYLES['input_focus']};
            }}
            QPushButton#rating_btn:checked {{
                background-color: {COMMON_STYLES['input_focus']};
                border: 1px solid {COMMON_STYLES['input_focus']};
                color: #FFFFFF;
                font-weight: bold;
            }}
        """)


class PersonSettingsBlock(BlockWidget):
    """
    인원 수 / 이미지 목적 설정 블록
    """
    settingsChanged = pyqtSignal(str, dict) # rating, person_info

    def __init__(self, parent=None):
        super().__init__("인원 수 / 이미지 목적", parent, block_type='control')
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self._init_content()

    def _init_content(self):
        layout = self.get_content_layout()

        # === 인원수 설정 섹션 (자동 조정) ===
        # GridLayout을 사용하여 라벨과 컨트롤의 정렬을 맞춤
        counts_layout = QHBoxLayout()
        counts_layout.setContentsMargins(0, 0, 0, 0)
        counts_layout.setSpacing(get_scaled_size(8))

        self.control_girls = CountControl("여성", max_value=6, initial_value=1)
        self.control_boys = CountControl("남성", max_value=6)
        self.control_others = CountControl("인외", max_value=6)

        # 각 컨트롤이 균등하게 공간을 차지하거나, 내용물에 맞게 조정되도록 설정
        # 여기서는 stretch를 주어 너비를 균등 분배
        counts_layout.addWidget(self.control_girls, 1)
        counts_layout.addWidget(self.control_boys, 1)
        counts_layout.addWidget(self.control_others, 1)

        layout.addLayout(counts_layout)

        # 구분선 (간격 유지를 위한 투명 라인)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        line.setStyleSheet(f"background-color: transparent; max-height: 1px; border: none; margin: {get_scaled_size(4)}px 0;")
        layout.addWidget(line)

        # === 이미지 목적 섹션 (버튼식) ===
        rating_layout = QHBoxLayout()
        rating_layout.setSpacing(get_scaled_size(8))
        
        self.rating_group = QButtonGroup(self)
        self.rating_group.setExclusive(True)
        
        # 옵션 정의 (Text, Value)
        ratings = [
            ("General", "general"),
            ("Sensitive", "sensitive"),
            ("Question", "questionable"),
            ("Explicit", "explicit")
        ]

        for text, val in ratings:
            btn = ImageRatingButton(text, val)
            self.rating_group.addButton(btn)
            # stretch=1을 주어 4개의 버튼이 꽉 차게 배치됨
            rating_layout.addWidget(btn, 1)
            
            if val == "sensitive": # Default
                btn.setChecked(True)
        
        layout.addLayout(rating_layout)

        # Solo 체크박스 (조건부 표시)
        self.solo_checkbox = QCheckBox("Solo 이미지입니다.")
        self.solo_checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self.solo_checkbox.setChecked(True)
        self.solo_checkbox.setStyleSheet(f"""
            QCheckBox {{
                color: {COMMON_STYLES['text_primary']};
                font-family: {FONT_FAMILY};
                font-size: {get_scaled_font_size(13)}px;
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
            }}
        """)
        # 체크박스 토글 시에도 프리뷰 업데이트
        self.solo_checkbox.toggled.connect(self._update_preview)
        layout.addWidget(self.solo_checkbox)

        # 구분선 2 (간격 유지를 위한 투명 라인)
        line2 = QFrame()
        line2.setFrameShape(QFrame.Shape.HLine)
        line2.setFrameShadow(QFrame.Shadow.Sunken)
        line2.setStyleSheet(f"background-color: transparent; max-height: 1px; border: none; margin: {get_scaled_size(4)}px 0;")
        layout.addWidget(line2)

        # === 미리보기 섹션 ===
        preview_label = QLabel("미리보기:")
        preview_label.setStyleSheet(f"""
            color: {COMMON_STYLES['text_primary']};
            font-family: {FONT_FAMILY};
            font-size: {get_scaled_font_size(INTERACTIVE_FONTS['label'])}px;
            font-weight: bold;
        """)
        layout.addWidget(preview_label)

        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setFixedHeight(get_scaled_size(60))
        self.preview_text.setStyleSheet(get_readonly_text_style())
        layout.addWidget(self.preview_text)

        # 이벤트 연결
        self.control_girls.valueChanged.connect(self._update_preview)
        self.control_boys.valueChanged.connect(self._update_preview)
        self.control_others.valueChanged.connect(self._update_preview)
        self.rating_group.buttonClicked.connect(self._update_preview)

        # 상단 정렬 및 남는 공간 채움 (아이템들이 상하로 늘어나는 것 방지)
        layout.addStretch()

        # 초기 업데이트
        self._update_preview()

    def _update_preview(self):
        """태그 생성 및 미리보기 업데이트"""
        c_girls = self.control_girls.get_value()
        c_boys = self.control_boys.get_value()
        c_others = self.control_others.get_value()
        total_count = c_girls + c_boys + c_others
        
        # Solo 조건 검사: (여1, 나머지0) 또는 (남1, 나머지0)
        is_solo_condition = (c_girls == 1 and c_boys == 0 and c_others == 0) or \
                            (c_girls == 0 and c_boys == 1 and c_others == 0)
        
        # 상태 업데이트 (시그널 차단하여 불필요한 호출 방지)
        self.solo_checkbox.blockSignals(True)
        if is_solo_condition:
            if not self.solo_checkbox.isVisible():
                self.solo_checkbox.setVisible(True)
                self.solo_checkbox.setChecked(True) # 다시 나타날 때 자동 체크
        else:
            if self.solo_checkbox.isVisible():
                self.solo_checkbox.setVisible(False)
                self.solo_checkbox.setChecked(False) # 조건 불만족 시 해제
        self.solo_checkbox.blockSignals(False)

        # 1. 태그 생성
        tags = []
        
        # 인원 정보 구성 (Quick Search용)
        person_info = {
            'girls': c_girls,
            'boys': c_boys,
            'others': c_others,
            'total': total_count,
            'is_solo': self.solo_checkbox.isChecked()
        }

        if total_count == 0:
            tags.append("no humans")
        else:
            # 여성
            if c_girls > 0:
                if c_girls >= 6:
                    tags.append("6+girls")
                elif c_girls == 1:
                    tags.append("1girl")
                else:
                    tags.append(f"{c_girls}girls")
            
            # 남성
            if c_boys > 0:
                if c_boys >= 6:
                    tags.append("6+boys")
                elif c_boys == 1:
                    tags.append("1boy")
                else:
                    tags.append(f"{c_boys}boys")
 
            # 인외
            if c_others > 0:
                if c_others >= 6:
                    tags.append("6+others")
                elif c_others == 1:
                    tags.append("1other")
                else:
                    tags.append(f"{c_others}others")

        # 2. Rating 태그 생성
        selected_rating = "sensitive" # Default
        checked_btn = self.rating_group.checkedButton()
        if checked_btn:
            if hasattr(checked_btn, 'value'):
                selected_rating = checked_btn.value

        if selected_rating == "general":
            tags.append("rating:general")
        elif selected_rating == 'sensitive':
            tags.append("rating:sensitive")
        elif selected_rating == 'questionable':
            tags.append("rating:questionable")
        elif selected_rating == 'explicit':
            tags.append("nsfw")
            tags.append("rating:explicit")
            
        # Solo 태그 추가 (프리뷰용)
        if person_info['is_solo']:
            tags.append("solo")

        # 결과 조합
        result_text = ", ".join(tags)
        self.preview_text.setText(result_text)
        
        # 변경 사항 알림
        self.settingsChanged.emit(selected_rating, person_info)

    def get_tags(self):
        """
        현재 설정에 따른 태그 리스트 반환 (이미지 생성용)

        Returns:
            list: 태그 리스트 (예: ["1girl", "rating:sensitive", "solo"])
        """
        c_girls = self.control_girls.get_value()
        c_boys = self.control_boys.get_value()
        c_others = self.control_others.get_value()
        total_count = c_girls + c_boys + c_others

        tags = []

        # 1. 인원수 태그
        if total_count == 0:
            tags.append("no humans")
        else:
            # 여성
            if c_girls > 0:
                if c_girls >= 6:
                    tags.append("6+girls")
                elif c_girls == 1:
                    tags.append("1girl")
                else:
                    tags.append(f"{c_girls}girls")

            # 남성
            if c_boys > 0:
                if c_boys >= 6:
                    tags.append("6+boys")
                elif c_boys == 1:
                    tags.append("1boy")
                else:
                    tags.append(f"{c_boys}boys")

            # 인외
            if c_others > 0:
                if c_others >= 6:
                    tags.append("6+others")
                elif c_others == 1:
                    tags.append("1other")
                else:
                    tags.append(f"{c_others}others")

        # 2. Rating 태그
        selected_rating = "sensitive"  # Default
        checked_btn = self.rating_group.checkedButton()
        if checked_btn:
            if hasattr(checked_btn, 'value'):
                selected_rating = checked_btn.value

        if selected_rating == "general":
            tags.append("rating:general")
        elif selected_rating == 'sensitive':
            tags.append("rating:sensitive")
        elif selected_rating == 'questionable':
            tags.append("rating:questionable")
        elif selected_rating == 'explicit':
            tags.append("nsfw")
            tags.append("rating:explicit")

        # 3. Solo 태그 (체크박스가 visible하고 checked인 경우만)
        if self.solo_checkbox.isVisible() and self.solo_checkbox.isChecked():
            tags.append("solo")

        return tags
