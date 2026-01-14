"""
Sequence Edit Widget

시퀀스 프롬프트 수정 위젯 - 생성 중 현재 단계 하이라이트 지원
추가된 태그는 연노랑색으로 강조 표시
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame,
    QLabel, QScrollArea, QTextEdit, QCheckBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QTextCharFormat, QColor, QFont, QTextCursor

from ui.theme import DARK_STYLES, DARK_COLORS
from ui.scaling_manager import get_scaled_font_size, get_scaled_size

# 추가된 태그 강조 색상 (연노랑)
ADDED_TAG_COLOR = "#FFEB3B"  # Light yellow
# 자동 삽입 태그 강조 색상 (회색)
AUTO_INSERTED_TAG_COLOR = "#9E9E9E"  # Gray
# 빨간색 (비활성화 표시용, DARK_COLORS에 없어서 직접 정의)
ACCENT_RED = "#F44336"
ACCENT_RED_DARK = "#D32F2F"


class SequenceEditWidget(QWidget):
    """시퀀스 수정 위젯"""

    # 시그널
    prompts_updated = pyqtSignal(list)  # 수정된 프롬프트 리스트
    prompt_engineering_toggled = pyqtSignal(bool)  # 프롬프트 엔지니어링 토글 시그널
    disable_state_changed = pyqtSignal(int, bool)  # 인덱스, 비활성화 여부

    def __init__(self, app_context=None, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.prompts = []
        self.prompt_frames = []  # (frame, label, textedit, added_tags, auto_inserted_tags, disable_checkbox) 튜플 리스트
        self.current_highlight_index = -1  # 현재 하이라이트 인덱스
        self.prompt_engineering_enabled = False  # 프롬프트 엔지니어링 토글 상태
        self.disabled_indices = set()  # 비활성화된 인덱스 집합

        self._init_ui()

    def _init_ui(self):
        """UI 초기화"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 메인 카드
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border-radius: {get_scaled_size(4)}px;
            }}
        """)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(8, 8, 8, 8)
        card_layout.setSpacing(6)

        # 타이틀
        title_layout = QHBoxLayout()
        title = QLabel("✏️ 시퀀스 수정")
        title.setStyleSheet(f"""
            font-size: {get_scaled_font_size(16) + 3}px;
            font-weight: bold;
            color: {DARK_COLORS['text_primary']};
        """)
        title_layout.addWidget(title)

        self.info_label = QLabel("프롬프트를 수정할 수 있습니다")
        self.info_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(13) + 3}px;
            color: {DARK_COLORS['text_secondary']};
        """)
        title_layout.addWidget(self.info_label)

        # 프롬프트 엔지니어링 적용 토글
        self.prompt_engineering_checkbox = QCheckBox("프롬프트 엔지니어링 적용")
        self.prompt_engineering_checkbox.setStyleSheet(f"""
            QCheckBox {{
                font-size: {get_scaled_font_size(12) + 6}px;
                color: {DARK_COLORS['text_primary']};
                spacing: {get_scaled_size(4)}px;
            }}
            QCheckBox::indicator {{
                width: {get_scaled_size(17)}px;
                height: {get_scaled_size(17)}px;
            }}
            QCheckBox::indicator:unchecked {{
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(3)}px;
                background-color: {DARK_COLORS['bg_tertiary']};
            }}
            QCheckBox::indicator:checked {{
                border: 1px solid {DARK_COLORS['accent_blue']};
                border-radius: {get_scaled_size(3)}px;
                background-color: {DARK_COLORS['accent_blue']};
            }}
        """)
        self.prompt_engineering_checkbox.toggled.connect(self._on_prompt_engineering_toggled)
        title_layout.addWidget(self.prompt_engineering_checkbox)

        title_layout.addStretch()

        card_layout.addLayout(title_layout)

        # 스크롤 영역
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet(f"""
            QScrollArea {{
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                background-color: {DARK_COLORS['bg_primary']};
            }}
            QScrollBar:vertical {{
                background-color: {DARK_COLORS['bg_primary']};
                width: 12px;
                border-radius: 6px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border-radius: 6px;
                min-height: 20px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)

        self.edit_container = QWidget()
        self.edit_container.setStyleSheet(f"background-color: {DARK_COLORS['bg_primary']};")
        self.edit_layout = QVBoxLayout(self.edit_container)
        self.edit_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.edit_layout.setSpacing(8)
        self.edit_layout.setContentsMargins(4, 4, 4, 4)

        # 플레이스홀더
        self.placeholder = QLabel("시퀀스가 확정되면\n여기서 프롬프트를 수정할 수 있습니다.")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setStyleSheet(f"""
            color: {DARK_COLORS['text_secondary']};
            font-size: {get_scaled_font_size(14) + 3}px;
            padding: {get_scaled_size(20)}px;
            background-color: {DARK_COLORS['bg_primary']};
        """)
        self.edit_layout.addWidget(self.placeholder)

        scroll.setWidget(self.edit_container)
        card_layout.addWidget(scroll, stretch=1)

        layout.addWidget(card)

    def set_prompts(self, prompts: list):
        """프롬프트 설정"""
        self.prompts = prompts
        self.prompt_frames = []
        self.current_highlight_index = -1
        self.disabled_indices = set()  # 비활성화 상태 초기화

        # 기존 위젯 클리어
        self._clear_edits()

        if not prompts:
            self.placeholder.show()
            self.info_label.setText("프롬프트를 수정할 수 있습니다")
            return

        self.placeholder.hide()

        # 이전 단계의 태그 추적
        prev_tags = set()

        # 프롬프트별 편집 위젯 생성
        for i, prompt_data in enumerate(prompts):
            current_tags = set(prompt_data.get('general', '').split(', '))

            # 추가된 태그 계산 (이전 단계와 비교)
            if i == 0:
                # Parent는 추가 태그 없음
                added_tags = set()
            else:
                added_tags = current_tags - prev_tags

            frame = self._create_edit_frame(i, prompt_data, added_tags)
            self.edit_layout.addWidget(frame)

            # 다음 비교를 위해 현재 태그 저장
            prev_tags = current_tags

        self.info_label.setText(f"총 {len(prompts)}개 프롬프트")

    def _clear_edits(self):
        """편집 위젯 클리어"""
        while self.edit_layout.count():
            item = self.edit_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.prompt_frames = []

        # 플레이스홀더 재추가
        self.placeholder = QLabel("시퀀스가 확정되면\n여기서 프롬프트를 수정할 수 있습니다.")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setStyleSheet(f"""
            color: {DARK_COLORS['text_secondary']};
            font-size: {get_scaled_font_size(14) + 3}px;
            padding: {get_scaled_size(20)}px;
            background-color: {DARK_COLORS['bg_primary']};
        """)
        self.edit_layout.addWidget(self.placeholder)

    def _create_edit_frame(self, index: int, prompt_data: dict, added_tags: set = None) -> QFrame:
        """편집 프레임 생성

        Args:
            index: 프롬프트 인덱스
            prompt_data: 프롬프트 데이터 딕셔너리
            added_tags: 이전 단계 대비 추가된 태그 집합
        """
        is_parent = prompt_data.get('is_parent', False)
        prompt_text = prompt_data.get('general', '')
        added_tags = added_tags or set()
        auto_inserted_tags = prompt_data.get('auto_inserted_tags', set())

        frame = QFrame()
        frame.setObjectName(f"edit_frame_{index}")
        frame.setStyleSheet(self._get_frame_style(is_highlighted=False))

        layout = QVBoxLayout(frame)
        layout.setSpacing(4)
        layout.setContentsMargins(8, 6, 8, 6)

        # 상단 헤더 (라벨 + Disable 체크박스)
        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)

        # 라벨 (추가 태그 개수 표시)
        if is_parent:
            label_text = "📌 Parent"
        else:
            if added_tags:
                label_text = f"└→ Child {index} (+{len(added_tags)} tags)"
            else:
                label_text = f"└→ Child {index}"

        label = QLabel(label_text)
        label.setObjectName(f"edit_label_{index}")
        label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(13) + 3}px;
            font-weight: bold;
            color: {DARK_COLORS['accent_blue'] if is_parent else DARK_COLORS['text_primary']};
            background: transparent;
        """)
        header_layout.addWidget(label)

        header_layout.addStretch()

        # Disable 체크박스 (Parent는 비활성화 불가)
        disable_checkbox = QCheckBox("⛔ Skip")
        disable_checkbox.setObjectName(f"edit_disable_{index}")
        disable_checkbox.setStyleSheet(f"""
            QCheckBox {{
                font-size: {get_scaled_font_size(11) + 3}px;
                color: {DARK_COLORS['text_secondary']};
                spacing: {get_scaled_size(3)}px;
            }}
            QCheckBox::indicator {{
                width: {get_scaled_size(14)}px;
                height: {get_scaled_size(14)}px;
            }}
            QCheckBox::indicator:unchecked {{
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(2)}px;
                background-color: #FFFFFF;
            }}
            QCheckBox::indicator:checked {{
                border: 1px solid {ACCENT_RED};
                border-radius: {get_scaled_size(2)}px;
                background-color: {ACCENT_RED};
            }}
            QToolTip {{
                color: white;
                background-color: {DARK_COLORS['bg_tertiary']};
                border: 1px solid {DARK_COLORS['border']};
            }}
        """)
        disable_checkbox.toggled.connect(lambda checked, idx=index: self._on_disable_toggled(idx, checked))

        # Parent는 Disable 불가
        if is_parent:
            disable_checkbox.setEnabled(False)
            disable_checkbox.setToolTip("Parent는 비활성화할 수 없습니다")
        else:
            disable_checkbox.setToolTip("체크 시 이 프롬프트는 생성/그리드에서 제외됩니다")

        header_layout.addWidget(disable_checkbox)

        layout.addLayout(header_layout)

        # 텍스트 에디터
        textedit = QTextEdit()
        textedit.setObjectName(f"edit_textedit_{index}")
        textedit.setMinimumHeight(get_scaled_size(60))
        textedit.setMaximumHeight(get_scaled_size(120))
        textedit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(4)}px;
                font-size: {get_scaled_font_size(12) + 3}px;
            }}
            QTextEdit:focus {{
                border-color: {DARK_COLORS['accent_blue']};
            }}
        """)

        # 텍스트 설정 및 하이라이팅 적용
        textedit.setPlainText(prompt_text)
        # 자동 삽입 태그 회색 하이라이팅 (먼저 적용)
        if auto_inserted_tags:
            self._apply_auto_inserted_highlighting(textedit, auto_inserted_tags)
        # 추가된 태그 연노랑 하이라이팅 (자동 삽입 태그 제외)
        if added_tags:
            # 자동 삽입 태그는 added_tags에서 제외
            highlight_tags = added_tags - auto_inserted_tags
            if highlight_tags:
                self._apply_tag_highlighting(textedit, highlight_tags)

        # 텍스트 변경 시 프롬프트 업데이트
        textedit.textChanged.connect(lambda idx=index: self._on_text_changed(idx))
        layout.addWidget(textedit)

        # 프레임 정보 저장 (added_tags, auto_inserted_tags, disable_checkbox 포함)
        self.prompt_frames.append((frame, label, textedit, added_tags, auto_inserted_tags, disable_checkbox))

        return frame

    def _on_disable_toggled(self, index: int, disabled: bool):
        """Disable 토글 상태 변경"""
        if disabled:
            self.disabled_indices.add(index)
        else:
            self.disabled_indices.discard(index)

        # 프레임 스타일 업데이트 (비활성화 시 어둡게)
        if index < len(self.prompt_frames):
            frame, _, textedit, _, _, _ = self.prompt_frames[index]
            frame.setStyleSheet(self._get_frame_style(is_highlighted=False, is_disabled=disabled))
            textedit.setEnabled(not disabled)

        print(f"🔇 프롬프트 #{index} {'비활성화' if disabled else '활성화'}")
        self.disable_state_changed.emit(index, disabled)

    def _apply_auto_inserted_highlighting(self, textedit: QTextEdit, auto_inserted_tags: set):
        """자동 삽입 태그에 회색 하이라이트 적용"""
        if not auto_inserted_tags:
            return

        # 하이라이트 포맷 생성 (회색)
        highlight_format = QTextCharFormat()
        highlight_format.setForeground(QColor(AUTO_INSERTED_TAG_COLOR))

        text = textedit.toPlainText()
        cursor = textedit.textCursor()

        # 시그널 임시 차단
        textedit.blockSignals(True)

        # 각 자동 삽입 태그 찾아서 하이라이트
        for tag in auto_inserted_tags:
            tag = tag.strip()
            if not tag:
                continue

            # 태그 위치 찾기
            start_pos = 0
            while True:
                pos = text.find(tag, start_pos)
                if pos == -1:
                    break

                # 정확한 태그 매칭 확인
                before_ok = (pos == 0 or text[pos-1] in ', ')
                after_ok = (pos + len(tag) >= len(text) or text[pos + len(tag)] in ', ')

                if before_ok and after_ok:
                    cursor.setPosition(pos)
                    cursor.setPosition(pos + len(tag), QTextCursor.MoveMode.KeepAnchor)
                    cursor.setCharFormat(highlight_format)

                start_pos = pos + len(tag)

        # 커서를 처음으로 이동
        cursor.setPosition(0)
        textedit.setTextCursor(cursor)

        # 시그널 복원
        textedit.blockSignals(False)

    def _apply_tag_highlighting(self, textedit: QTextEdit, added_tags: set):
        """추가된 태그에 연노랑색 하이라이트 적용"""
        if not added_tags:
            return

        # 하이라이트 포맷 생성
        highlight_format = QTextCharFormat()
        highlight_format.setForeground(QColor(ADDED_TAG_COLOR))
        highlight_format.setFontWeight(QFont.Weight.Bold)

        text = textedit.toPlainText()
        cursor = textedit.textCursor()

        # 시그널 임시 차단 (하이라이팅 중 textChanged 방지)
        textedit.blockSignals(True)

        # 각 추가 태그 찾아서 하이라이트
        for tag in added_tags:
            tag = tag.strip()
            if not tag:
                continue

            # 태그 위치 찾기 (모든 발생 위치)
            start_pos = 0
            while True:
                pos = text.find(tag, start_pos)
                if pos == -1:
                    break

                # 정확한 태그 매칭 확인 (앞뒤로 ", " 또는 문자열 끝)
                before_ok = (pos == 0 or text[pos-1] in ', ')
                after_ok = (pos + len(tag) >= len(text) or text[pos + len(tag)] in ', ')

                if before_ok and after_ok:
                    # 커서 이동 및 선택
                    cursor.setPosition(pos)
                    cursor.setPosition(pos + len(tag), QTextCursor.MoveMode.KeepAnchor)
                    cursor.setCharFormat(highlight_format)

                start_pos = pos + len(tag)

        # 커서를 처음으로 이동
        cursor.setPosition(0)
        textedit.setTextCursor(cursor)

        # 시그널 복원
        textedit.blockSignals(False)

    def _get_frame_style(self, is_highlighted: bool = False, is_disabled: bool = False) -> str:
        """프레임 스타일 반환"""
        if is_disabled:
            # 비활성화 스타일 - 어두운 배경, 빨간색 테두리
            return f"""
                QFrame {{
                    background-color: {DARK_COLORS['bg_primary']};
                    border: 2px dashed {ACCENT_RED}80;
                    border-radius: {get_scaled_size(4)}px;
                    opacity: 0.6;
                }}
            """
        elif is_highlighted:
            # 하이라이트 스타일 - accent 색상 배경
            return f"""
                QFrame {{
                    background-color: {DARK_COLORS['accent_blue']}40;
                    border: 2px solid {DARK_COLORS['accent_blue']};
                    border-radius: {get_scaled_size(6)}px;
                }}
            """
        else:
            # 기본 스타일
            return f"""
                QFrame {{
                    background-color: {DARK_COLORS['bg_secondary']};
                    border: 1px solid {DARK_COLORS['border']};
                    border-radius: {get_scaled_size(4)}px;
                }}
            """

    def _on_text_changed(self, index: int):
        """텍스트 변경 시 프롬프트 업데이트"""
        if index < len(self.prompt_frames) and index < len(self.prompts):
            _, _, textedit, _, _, _ = self.prompt_frames[index]
            self.prompts[index]['general'] = textedit.toPlainText()
            self.prompts_updated.emit(self.prompts)

    def set_highlight_index(self, index: int):
        """현재 생성 중인 인덱스 하이라이트"""
        # 이전 하이라이트 해제
        if self.current_highlight_index >= 0 and self.current_highlight_index < len(self.prompt_frames):
            old_frame, _, _, _, _, _ = self.prompt_frames[self.current_highlight_index]
            is_disabled = self.current_highlight_index in self.disabled_indices
            old_frame.setStyleSheet(self._get_frame_style(is_highlighted=False, is_disabled=is_disabled))

        self.current_highlight_index = index

        # 새 하이라이트 적용
        if index >= 0 and index < len(self.prompt_frames):
            frame, _, _, _, _, _ = self.prompt_frames[index]
            frame.setStyleSheet(self._get_frame_style(is_highlighted=True))

            # 해당 프레임으로 스크롤
            self._scroll_to_frame(frame)

    def clear_highlight(self):
        """하이라이트 제거"""
        if self.current_highlight_index >= 0 and self.current_highlight_index < len(self.prompt_frames):
            frame, _, _, _, _, _ = self.prompt_frames[self.current_highlight_index]
            is_disabled = self.current_highlight_index in self.disabled_indices
            frame.setStyleSheet(self._get_frame_style(is_highlighted=False, is_disabled=is_disabled))
        self.current_highlight_index = -1

    def _scroll_to_frame(self, frame: QFrame):
        """프레임으로 스크롤"""
        # 부모 스크롤 영역 찾기
        scroll_area = self.findChild(QScrollArea)
        if scroll_area:
            # 프레임 위치로 스크롤
            scroll_area.ensureWidgetVisible(frame, 50, 50)

    def get_prompts(self) -> list:
        """현재 프롬프트 목록 반환"""
        return self.prompts

    def get_enabled_prompts(self) -> list:
        """비활성화되지 않은 프롬프트 목록 반환"""
        return [p for i, p in enumerate(self.prompts) if i not in self.disabled_indices]

    def get_disabled_indices(self) -> set:
        """비활성화된 인덱스 집합 반환"""
        return self.disabled_indices.copy()

    def is_index_disabled(self, index: int) -> bool:
        """특정 인덱스가 비활성화되었는지 확인"""
        return index in self.disabled_indices

    def set_disabled(self, index: int, disabled: bool):
        """특정 인덱스의 비활성화 상태 설정 (외부에서 호출)

        Args:
            index: 프롬프트 인덱스
            disabled: 비활성화 여부
        """
        if index < 0 or index >= len(self.prompt_frames):
            return

        # 현재 상태와 동일하면 무시
        current_disabled = index in self.disabled_indices
        if current_disabled == disabled:
            return

        # 체크박스 상태 업데이트 (시그널 발생으로 _on_disable_toggled 호출됨)
        _, _, _, _, _, disable_checkbox = self.prompt_frames[index]
        if disable_checkbox:
            disable_checkbox.setChecked(disabled)

    def update_prompt_text(self, index: int, text: str):
        """특정 인덱스의 프롬프트 텍스트 업데이트 (외부에서 호출)"""
        if index < len(self.prompt_frames) and index < len(self.prompts):
            _, _, textedit, added_tags, auto_inserted_tags, _ = self.prompt_frames[index]
            # 시그널 임시 차단
            textedit.blockSignals(True)
            textedit.setPlainText(text)
            # 하이라이팅 재적용
            if auto_inserted_tags:
                self._apply_auto_inserted_highlighting(textedit, auto_inserted_tags)
            if added_tags:
                highlight_tags = added_tags - auto_inserted_tags
                if highlight_tags:
                    self._apply_tag_highlighting(textedit, highlight_tags)
            textedit.blockSignals(False)
            self.prompts[index]['general'] = text

    def _on_prompt_engineering_toggled(self, checked: bool):
        """프롬프트 엔지니어링 토글 상태 변경"""
        self.prompt_engineering_enabled = checked
        print(f"🔧 프롬프트 엔지니어링: {'활성화' if checked else '비활성화'}")
        # 시그널 발생하여 상위 컴포넌트에 알림
        self.prompt_engineering_toggled.emit(checked)

    def is_prompt_engineering_enabled(self) -> bool:
        """프롬프트 엔지니어링 활성화 여부 반환"""
        return self.prompt_engineering_enabled

    def apply_prompt_engineering(self, prompt: str) -> str:
        """프롬프트 엔지니어링 적용 (토글이 활성화된 경우)

        Args:
            prompt: 원본 프롬프트

        Returns:
            처리된 프롬프트 (토글 비활성화 시 원본 반환)
        """
        if not self.prompt_engineering_enabled:
            print(f"🔧 [PE] 비활성화 상태 - 원본 반환")
            return prompt

        if not self.app_context:
            print("⚠️ app_context가 없어 프롬프트 엔지니어링을 적용할 수 없습니다.")
            return prompt

        try:
            # MiddleSectionController를 통해 PromptEngineeringModule 가져오기
            controller = self.app_context.middle_section_controller
            if not controller:
                print("⚠️ middle_section_controller가 없습니다.")
                return prompt

            pe_module = controller.get_module_instance("PromptEngineeringModule")
            if not pe_module:
                print("⚠️ PromptEngineeringModule을 찾을 수 없습니다.")
                return prompt

            # preprocess_prompt_turbo 호출
            print(f"🔧 [PE] preprocess_prompt_turbo 호출 중...")
            print(f"🔧 [PE] 입력: {prompt[:100]}...")
            processed = pe_module.preprocess_prompt_turbo(prompt)
            print(f"🔧 [PE] 출력: {processed[:100]}...")
            return processed

        except Exception as e:
            print(f"❌ 프롬프트 엔지니어링 적용 오류: {e}")
            import traceback
            traceback.print_exc()
            return prompt

    def set_app_context(self, app_context):
        """AppContext 설정 (외부에서 주입)"""
        self.app_context = app_context
