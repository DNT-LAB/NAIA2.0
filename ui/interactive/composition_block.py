"""
Composition Block - X/Y/Z 축 및 구도 설정 위젯
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QComboBox, QCheckBox, QGridLayout, QFrame, QSizePolicy, QTextEdit
)

from ui.interactive.block_widget import BlockWidget
from ui.interactive.interactive_theme import (
    COMMON_STYLES, INTERACTIVE_FONTS, FONT_FAMILY,
    get_label_style, get_combobox_style, get_checkbox_style,
    get_readonly_text_style
)
from ui.scaling_manager import get_scaled_size, get_scaled_font_size


class CompositionBlock(BlockWidget):
    """
    X/Y/Z 축과 특수 프레이밍 태그를 설정하는 블록
    """
    def __init__(self, parent=None):
        # block_type='utility' (설정/도구 느낌의 청록/회색 계열)
        super().__init__("X / Y / Z 축(구도)", parent, block_type='utility')
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self._init_content()

    def disable_wheel_event(self, widget):
        """위젯의 마우스 휠 이벤트를 비활성화"""
        def wheelEvent(event):
            event.ignore()
        widget.wheelEvent = wheelEvent
        return widget

    def _init_content(self):
        layout = self.get_content_layout()

        # 공통 스타일 적용을 위한 QSS
        self.setStyleSheet(f"""
            {get_label_style()}
            {get_combobox_style()}
            {get_checkbox_style()}
        """)

        # === 1. X축 (수평 시점) ===
        x_label = QLabel("이미지의 X축(수평 시점)을 설정합니다")
        layout.addWidget(x_label)
        
        # POV 체크박스
        self.chk_pov = QCheckBox("POV")
        self.chk_pov.stateChanged.connect(self._update_preview)
        layout.addWidget(self.chk_pov)

        # X축 콤보박스
        self.combo_x = QComboBox()
        self.disable_wheel_event(self.combo_x)
        self.combo_x.addItems([
            "정의하지 않음",
            "정면",
            "강한 정면",
            "측면(옆모습)",
            "3/4(반측면)",
            "후면(등)"
        ])
        # 데이터 매핑 (인덱스 순서대로)
        self.tags_x = [
            "",
            "front view",
            "front view, 0.5::straight-on ::",
            "side view, 0.5::from side ::",
            "three-quarter view",
            "rear view, 0.5::from behind ::"
        ]
        self.combo_x.currentIndexChanged.connect(self._update_preview)
        layout.addWidget(self.combo_x)

        self._add_separator(layout)

        # === 2. Y축 (상하 시점) ===
        y_label = QLabel("이미지의 Y축(상하 시점)을 설정합니다")
        layout.addWidget(y_label)

        # Y축 콤보박스
        self.combo_y = QComboBox()
        self.disable_wheel_event(self.combo_y)
        self.combo_y.addItems([
            "정의하지 않음(중앙)",
            "정확히 위에서 내려다보기(탑다운)",
            "약간 위에서 내려다보기",
            "약간 아래에서 올려다보기",
            "정확히 아래에서 올려다보기(바닥시점)"
        ])
        self.tags_y = [
            "",
            "bird's-eye view, 0.5::from above ::",
            "high-angle view, 0.5::from above ::",
            "low-angle view, 0.5::from below ::",
            "worm's-eye view, 0.5::from below ::"
        ]
        self.combo_y.currentIndexChanged.connect(self._update_preview)
        layout.addWidget(self.combo_y)

        self._add_separator(layout)

        # === 3. Z축 (거리/샷 크기) ===
        z_label = QLabel("이미지의 Z축(거리/샷 크기)을 설정합니다")
        layout.addWidget(z_label)

        # Z축 콤보박스
        self.combo_z = QComboBox()
        self.disable_wheel_event(self.combo_z)
        self.combo_z.addItems([
            "정의하지 않음",
            "초근접(얼굴 위주)",
            "상반신(가슴~머리)",
            "반신(허리 위)",
            "카우보이 샷(허벅지/무릎 위)",
            "전신",
            "원거리(배경 많이)"
        ])
        self.tags_z = [
            "",
            "close-up",
            "upper body",
            "half body",
            "cowboy shot",
            "full body",
            "wide shot"
        ]
        self.combo_z.currentIndexChanged.connect(self._update_preview)
        layout.addWidget(self.combo_z)

        self._add_separator(layout)

        # === 4. 스페셜 태그 (2x2 체크박스) ===
        special_label = QLabel("스페셜 태그")
        layout.addWidget(special_label)

        special_grid = QGridLayout()
        special_grid.setContentsMargins(0, 0, 0, 0)
        special_grid.setSpacing(get_scaled_size(8))

        # 데이터 정의 (Label, Tag)
        specials = [
            ("뒤집기", "upside-down"),
            ("90도", "sideways"),
            ("원근감", "perspective"),
            ("기울임", "dutch angle"),
            ("역동감", "foreshortening")
        ]

        # 2열 그리드 배치
        self.special_checks = []
        for i, (text, tag) in enumerate(specials):
            chk = QCheckBox(text)
            chk.setProperty("tag", tag)
            chk.stateChanged.connect(self._update_preview)
            special_grid.addWidget(chk, i // 2, i % 2)
            self.special_checks.append(chk)

        layout.addLayout(special_grid)

        self._add_separator(layout)

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
        self.preview_text.setFixedHeight(get_scaled_size(80))
        self.preview_text.setStyleSheet(get_readonly_text_style())
        layout.addWidget(self.preview_text)

        # 상하 늘어짐 방지
        layout.addStretch()

        # 초기 업데이트
        self._update_preview()

    def _add_separator(self, layout):
        """투명 구분선 추가"""
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        line.setStyleSheet(f"background-color: transparent; max-height: 1px; border: none; margin: {get_scaled_size(4)}px 0;")
        layout.addWidget(line)

    def _update_preview(self):
        """미리보기 업데이트"""
        self.preview_text.setText(self._calculate_prompt_text())

    def _calculate_prompt_text(self) -> str:
        """
        선택된 태그들을 조합하여 프롬프트 문자열 계산
        가중치 태그(0.x::...::)는 파싱하여 일반 태그는 앞으로,
        가중치 그룹은 뒤로 모아서 배치함.
        """
        import re

        # 1. 모든 원본 태그 수집
        raw_parts = []

        # X축
        if self.chk_pov.isChecked():
            raw_parts.append("pov, first person view")

        idx_x = self.combo_x.currentIndex()
        if idx_x > 0 and idx_x < len(self.tags_x):
            raw_parts.append(self.tags_x[idx_x])

        # Y축
        idx_y = self.combo_y.currentIndex()
        if idx_y > 0 and idx_y < len(self.tags_y):
            raw_parts.append(self.tags_y[idx_y])

        # Z축
        idx_z = self.combo_z.currentIndex()
        if idx_z > 0 and idx_z < len(self.tags_z):
            raw_parts.append(self.tags_z[idx_z])

        # Special
        for chk in self.special_checks:
            if chk.isChecked():
                raw_parts.append(chk.property("tag"))

        full_raw = ", ".join(raw_parts)

        # 2. 가중치 태그 추출 (Regex)
        # 예: "0.5::content ::" 형태 찾기
        weighted_map = {} # weight -> list of contents

        def extract_weighted(match):
            w = match.group(1)
            c = match.group(2).strip()
            if w not in weighted_map:
                weighted_map[w] = []
            if c:
                weighted_map[w].append(c)
            return "" # 원본 문자열에서 제거

        # 가중치 부분 추출 및 제거
        pattern = r'(\d+(?:\.\d+)?)::\s*(.*?)\s*::'
        remaining = re.sub(pattern, extract_weighted, full_raw)

        # 3. 일반 태그 처리
        plain_tags = [t.strip() for t in remaining.split(',') if t.strip()]

        # 4. 최종 결과 조합
        final_parts = plain_tags[:]

        # 가중치 그룹 추가
        for w, contents in weighted_map.items():
            if contents:
                merged_content = ", ".join(contents)
                final_parts.append(f"{w}::{merged_content} ::")

        return ", ".join(final_parts)

    def get_prompt_text(self) -> str:
        """
        preview_text에 표시된 프롬프트 문자열 반환
        (이미 _update_preview()에서 계산된 결과를 재사용)
        """
        return self.preview_text.toPlainText()
