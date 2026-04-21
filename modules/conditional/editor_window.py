# modules/conditional/editor_window.py
# 조건부 프롬프트 편집기 창 (Phase 0 스켈레톤)
# - Non-modal QDialog, 단일 인스턴스
# - 현재 단계: 메인 모듈의 DSL 규칙을 읽기 전용 프리뷰로 표시
# - 이후 단계: Phase 1에서 블록 기반 조건/액션 빌더 삽입

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal

from ui.theme import DARK_COLORS, get_dynamic_styles
from ui.scaling_manager import get_scaled_font_size, get_scaled_size


class RuleEditorWindow(QDialog):
    """조건부 프롬프트 블록 편집기 (Phase 0 스켈레톤).

    메인 모듈(`modules/conditional_prompt_module.PromptListModifierModule`)이
    보유한 DSL 규칙을 읽기 전용으로 미리 보여준다. Phase 1부터는 이 자리에
    블록 기반 조건/액션 빌더가 들어온다.
    """

    rules_applied = pyqtSignal(str)  # Phase 1: Apply 시 DSL 텍스트 송신

    def __init__(self, app_context, module, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.module = module  # PromptListModifierModule 참조

        self.setWindowTitle("조건부 프롬프트 편집기 (Preview)")
        self.setMinimumSize(820, 600)
        self.setModal(False)
        # 닫아도 객체 파괴하지 않음 (단일 인스턴스 재사용)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        self.setStyleSheet(
            f"QDialog {{ background-color: {DARK_COLORS['bg_primary']}; }}"
        )

        self._build_ui()
        self.load_current_rules()

    def _build_ui(self):
        dynamic_styles = get_dynamic_styles()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            get_scaled_size(16), get_scaled_size(16),
            get_scaled_size(16), get_scaled_size(16)
        )
        layout.setSpacing(get_scaled_size(10))

        # 헤더
        header_label = QLabel("조건부 프롬프트 편집기")
        header_label.setStyleSheet(
            f"color: {DARK_COLORS['text_primary']};"
            f" font-size: {get_scaled_font_size(22)}px;"
            f" font-weight: bold;"
        )
        layout.addWidget(header_label)

        # 서브 설명 (Phase 0 안내)
        subtitle_label = QLabel(
            "새 편집기 개발의 첫 단계입니다. 현재는 메인 모듈의 DSL 규칙을 읽기 전용으로 보여줍니다.\n"
            "다음 단계에서 블록 기반 조건/액션 빌더 · 시뮬레이션 뷰 · 프리셋 시스템이 추가됩니다."
        )
        subtitle_label.setStyleSheet(
            f"color: {DARK_COLORS['text_secondary']};"
            f" font-size: {get_scaled_font_size(14)}px;"
        )
        subtitle_label.setWordWrap(True)
        layout.addWidget(subtitle_label)

        # 구분선
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet(
            f"background-color: {DARK_COLORS['border']}; max-height: 1px;"
        )
        layout.addWidget(divider)

        # 현재 DSL 섹션
        rules_section_label = QLabel("현재 DSL 규칙 (읽기 전용)")
        rules_section_label.setStyleSheet(
            f"color: {DARK_COLORS['text_primary']};"
            f" font-size: {get_scaled_font_size(16)}px;"
            f" font-weight: bold;"
        )
        layout.addWidget(rules_section_label)

        self.rules_preview = QTextEdit()
        self.rules_preview.setReadOnly(True)
        self.rules_preview.setAcceptRichText(False)
        self.rules_preview.setStyleSheet(dynamic_styles['compact_textedit'])
        layout.addWidget(self.rules_preview, stretch=1)

        # 상태 힌트
        status_label = QLabel(
            "다음 단계: 블록 기반 편집기 · DSL 확장(char:N, uc:N, 가중치 보존) · 시뮬레이션 diff · 프리셋"
        )
        status_label.setStyleSheet(
            f"color: {DARK_COLORS['accent_blue_light']};"
            f" font-size: {get_scaled_font_size(13)}px;"
            f" padding: {get_scaled_size(8)}px;"
            f" background-color: {DARK_COLORS['bg_secondary']};"
            f" border-radius: {get_scaled_size(4)}px;"
        )
        status_label.setWordWrap(True)
        layout.addWidget(status_label)

        # 버튼 행
        button_row = QHBoxLayout()
        button_row.setSpacing(get_scaled_size(8))

        refresh_button = QPushButton("🔄 현재 규칙 다시 불러오기")
        refresh_button.setStyleSheet(dynamic_styles['secondary_button'])
        refresh_button.clicked.connect(self.load_current_rules)
        button_row.addWidget(refresh_button)

        button_row.addStretch()

        close_button = QPushButton("닫기")
        close_button.setStyleSheet(dynamic_styles['secondary_button'])
        close_button.clicked.connect(self.close)
        button_row.addWidget(close_button)

        layout.addLayout(button_row)

    def load_current_rules(self):
        """메인 모듈의 DSL 규칙 텍스트를 가져와 프리뷰에 표시."""
        text = ""
        if self.module is not None:
            rules_textedit = getattr(self.module, 'rules_textedit', None)
            if rules_textedit is not None:
                text = rules_textedit.toPlainText()

        if text.strip():
            self.rules_preview.setPlainText(text)
        else:
            self.rules_preview.setPlainText(
                "(규칙이 비어있습니다. 메인 모듈에서 규칙을 작성하면 여기에 표시됩니다.)"
            )

    def showEvent(self, event):
        """창이 표시될 때마다 최신 규칙으로 동기화."""
        self.load_current_rules()
        super().showEvent(event)
