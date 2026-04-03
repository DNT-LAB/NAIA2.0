"""
한→영 번역 팝업 창
Google Translate 스타일 레이아웃
"""

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit,
    QLabel, QPushButton
)
from ui.theme import DARK_COLORS, DARK_STYLES
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from utils.translator import korean_to_english


class TranslateWorker(QThread):
    """번역 백그라운드 스레드"""
    finished = pyqtSignal(str, str)  # (원문, 번역)
    failed = pyqtSignal(str)  # 에러 메시지

    def __init__(self, text: str):
        super().__init__()
        self.text = text

    def run(self):
        try:
            result = korean_to_english(self.text)
            if result:
                self.finished.emit(self.text, result)
            else:
                self.failed.emit("번역 실패")
        except Exception as e:
            self.failed.emit(str(e))


class TranslateDialog(QWidget):
    """한→영 번역 독립 창 (X 버튼으로만 닫힘)"""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("한→영 번역")
        self.setMinimumSize(get_scaled_size(600), get_scaled_size(300))
        self.resize(get_scaled_size(700), get_scaled_size(350))
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowCloseButtonHint
        )

        self._worker = None
        self._last_translated_text = ""

        # 입력 유휴 감지 타이머 (350ms)
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(350)
        self._idle_timer.timeout.connect(self._request_translation)

        self._setup_ui()
        self._setup_style()
        self._connect_signals()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            get_scaled_size(12), get_scaled_size(8),
            get_scaled_size(12), get_scaled_size(12)
        )
        layout.setSpacing(get_scaled_size(6))

        # --- 상단: 언어 헤더 ---
        header = QHBoxLayout()
        header.setSpacing(0)

        lang_font = f"font-size: {get_scaled_font_size(15)}px; font-weight: bold; color: {DARK_COLORS['text_primary']};"
        arrow_font = f"font-size: {get_scaled_font_size(15)}px; color: {DARK_COLORS['text_secondary']};"

        ko_label = QLabel("한국어")
        ko_label.setStyleSheet(lang_font)
        ko_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        arrow_label = QLabel("→")
        arrow_label.setStyleSheet(arrow_font)
        arrow_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        arrow_label.setFixedWidth(get_scaled_size(40))

        en_label = QLabel("English")
        en_label.setStyleSheet(lang_font)
        en_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        header.addWidget(ko_label, 1)
        header.addWidget(arrow_label, 0)
        header.addWidget(en_label, 1)

        layout.addLayout(header)

        # --- 중앙: 좌우 텍스트 에디트 ---
        editors_layout = QHBoxLayout()
        editors_layout.setSpacing(get_scaled_size(8))

        self.input_edit = QTextEdit()
        self.input_edit.setAcceptRichText(False)
        self.input_edit.setProperty("autocomplete_ignore", True)
        self.input_edit.setPlaceholderText("번역할 한국어를 입력하세요...")
        self.input_edit.setStyleSheet(DARK_STYLES['compact_textedit'])

        self.output_edit = QTextEdit()
        self.output_edit.setAcceptRichText(False)
        self.output_edit.setReadOnly(True)
        self.output_edit.setPlaceholderText("번역 결과가 여기에 표시됩니다")
        self.output_edit.setStyleSheet(DARK_STYLES['compact_textedit'])

        editors_layout.addWidget(self.input_edit, 1)
        editors_layout.addWidget(self.output_edit, 1)

        layout.addLayout(editors_layout, 1)

        # --- 하단: 번역(좌) ... 복사 + 닫기(우) ---
        btn_h = get_scaled_size(32)
        copy_w = get_scaled_size(100)
        close_w = get_scaled_size(44)

        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(get_scaled_size(6))

        self.translate_btn = QPushButton("번역")
        self.translate_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.translate_btn.setFixedHeight(btn_h)
        self.translate_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        self.copy_btn = QPushButton("복사")
        self.copy_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.copy_btn.setFixedSize(copy_w, btn_h)
        self.copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        self.close_btn = QPushButton("닫기")
        self.close_btn.setFixedSize(close_w, btn_h)
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['text_secondary']};
                color: #000000;
                border: none;
                border-radius: {get_scaled_size(4)}px;
                font-size: {get_scaled_font_size(13)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['border_light']};
            }}
        """)

        bottom_layout.addWidget(self.translate_btn)
        bottom_layout.addStretch()
        bottom_layout.addWidget(self.copy_btn)
        bottom_layout.addWidget(self.close_btn)

        layout.addLayout(bottom_layout)

    def _connect_signals(self):
        self.translate_btn.clicked.connect(self._request_translation)
        self.copy_btn.clicked.connect(self._copy_result)
        self.close_btn.clicked.connect(self.close)
        self.input_edit.textChanged.connect(self._on_text_changed)

    def _on_text_changed(self):
        """텍스트 변경 시 유휴 타이머 리셋 (350ms 후 자동 번역)"""
        self._idle_timer.start()

    def _request_translation(self):
        """번역 요청 — 텍스트가 변경된 경우에만"""
        text = self.input_edit.toPlainText().strip()
        if not text or text == self._last_translated_text:
            return

        # 진행 중인 워커가 있으면 결과 무시 처리
        old_worker = self._worker
        if old_worker is not None:
            try:
                if old_worker.isRunning():
                    old_worker.finished.disconnect(self._on_translation_done)
                    old_worker.failed.disconnect(self._on_translation_failed)
            except (TypeError, RuntimeError):
                pass

        self._last_translated_text = text
        self._worker = TranslateWorker(text)
        self._worker.finished.connect(self._on_translation_done)
        self._worker.failed.connect(self._on_translation_failed)
        self._worker.finished.connect(self._cleanup_worker)
        self._worker.failed.connect(self._cleanup_worker)
        self._worker.start()

    def _cleanup_worker(self, *args):
        """워커 참조 정리"""
        sender = self.sender()
        if sender is self._worker:
            self._worker = None

    def _on_translation_done(self, original: str, translated: str):
        """번역 완료"""
        self.output_edit.setPlainText(translated)

    def _on_translation_failed(self, error: str):
        """번역 실패"""
        self.output_edit.setPlainText(f"(번역 실패: {error})")

    def _setup_style(self):
        self.setObjectName("TranslateDialog")
        self.setAutoFillBackground(True)
        palette = self.palette()
        from PyQt6.QtGui import QColor
        palette.setColor(palette.ColorRole.Window, QColor(DARK_COLORS['bg_primary']))
        self.setPalette(palette)

    def show_at_button(self, button: QWidget):
        """버튼의 오른쪽에 창을 표시 (하단 정렬 — 위로 펼쳐짐)"""
        btn_global = button.mapToGlobal(button.rect().bottomRight())
        x = btn_global.x() + get_scaled_size(4)
        y = btn_global.y() - self.height()
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()
        self.input_edit.setFocus()

    def _copy_result(self):
        """번역 결과를 클립보드에 복사"""
        from PyQt6.QtWidgets import QApplication
        text = self.output_edit.toPlainText()
        if text:
            QApplication.clipboard().setText(text)

    def get_input_text(self) -> str:
        return self.input_edit.toPlainText().strip()

    def set_output_text(self, text: str):
        self.output_edit.setPlainText(text)
