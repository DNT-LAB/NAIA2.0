"""QWebEngineView + QWebChannel + TerminalManager 통합 위젯."""
import os
import json
import logging
from PyQt6.QtCore import QUrl, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QComboBox, QInputDialog, QLineEdit,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PyQt6.QtWebChannel import QWebChannel
from ui.terminal.terminal_bridge import TerminalBridge
from ui.terminal.terminal_manager import TerminalManager
from ui.terminal.pty_backend import get_default_shell
from ui.scaling_manager import get_scaled_size, get_scaled_font_size
from ui.theme import DARK_COLORS, get_dynamic_styles

logger = logging.getLogger(__name__)

SESSION_ID = "main"
WEB_DIR = os.path.join(os.path.dirname(__file__), "web")
CLI_DIR = os.path.join(os.path.dirname(__file__), ".cli")
AUTO_EXEC_FILE = os.path.join(CLI_DIR, "auto_exec.json")

# 자동 실행 프리셋
AUTO_EXEC_PRESETS = [
    ("None", ""),
    ("Claude", "claude --dangerously-skip-permissions"),
    ("Codex", "codex --yolo"),
    ("Gemini", "gemini --yolo"),
    ("Custom", "__CUSTOM__"),
]


class _SilentPage(QWebEnginePage):
    """JS 콘솔 메시지 필터."""

    def javaScriptConsoleMessage(self, level, message, line, source):
        if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            logger.error(f"[terminal.js:{line}] {message}")


class TerminalWidget(QWidget):
    """임베디드 터미널 위젯 — xterm.js + pywinpty."""

    apply_to_main_prompt = pyqtSignal(dict)  # {"general": prompt} → 메인 프롬프트 전송
    send_and_generate = pyqtSignal(dict)    # {"general": prompt} → 전송 + 생성

    def __init__(self, parent=None):
        super().__init__(parent)
        self._session_started = False
        self._terminal_ready = False
        self._pending_start = False
        self._auto_exec_done = False
        self._sketch_window = None

        # 레이아웃
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 상단 툴바 영역
        self.toolbar = QWidget(self)
        self.toolbar_layout = QHBoxLayout(self.toolbar)
        m5 = get_scaled_size(5)
        self.toolbar_layout.setContentsMargins(m5, m5, m5, m5)
        self.toolbar_layout.setSpacing(get_scaled_size(4))

        # Sketch 버튼 — 별도 윈도우 열기
        btn_h = get_scaled_size(36)
        r = get_scaled_size(4)
        self._sketch_btn = QPushButton("Sketch")
        self._sketch_btn.setFixedHeight(btn_h)
        self._sketch_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #2E7D32;
                color: #FFFFFF;
                border: none;
                border-radius: {r}px;
                font-size: {get_scaled_font_size(14)}px;
                padding: 0 {get_scaled_size(12)}px;
            }}
            QPushButton:hover {{
                background-color: #388E3C;
            }}
            QPushButton:pressed {{
                background-color: #1B5E20;
            }}
        """)
        self._sketch_btn.clicked.connect(self._open_sketch_window)
        self.toolbar_layout.addWidget(self._sketch_btn)

        self.toolbar_layout.addStretch()

        # 자동 실행 라벨 + 콤보박스
        label_style = f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(13)}px;"
        auto_label = QLabel(" 자동 입력:")
        auto_label.setStyleSheet(label_style)
        self.toolbar_layout.addWidget(auto_label)

        self._auto_exec_combo = QComboBox()
        self._auto_exec_combo.setFixedHeight(btn_h)
        styles = get_dynamic_styles()
        self._auto_exec_combo.setStyleSheet(styles['compact_combobox'])
        for display_name, _ in AUTO_EXEC_PRESETS:
            self._auto_exec_combo.addItem(display_name)
        self._auto_exec_combo.currentIndexChanged.connect(self._on_auto_exec_changed)
        self.toolbar_layout.addWidget(self._auto_exec_combo)

        # 실행 명령어 표시 (읽기 전용)
        self._auto_exec_display = QLineEdit()
        self._auto_exec_display.setReadOnly(True)
        self._auto_exec_display.setFixedHeight(btn_h)
        self._auto_exec_display.setMinimumWidth(get_scaled_size(200))
        self._auto_exec_display.setStyleSheet(f"""
            QLineEdit {{
                background-color: {DARK_COLORS['panel']};
                color: {DARK_COLORS['text_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {r}px;
                font-size: {get_scaled_font_size(13)}px;
                padding: 0 {get_scaled_size(6)}px;
            }}
        """)
        self.toolbar_layout.addWidget(self._auto_exec_display)

        self.toolbar.setFixedHeight(btn_h + m5 * 2)
        layout.addWidget(self.toolbar)

        # 저장된 자동 실행 설정 복원
        self._custom_command = ""
        self._load_auto_exec()
        self._update_auto_exec_display()

        # WebEngineView
        self._page = _SilentPage(self)
        settings = self._page.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)

        self._view = QWebEngineView(self)
        self._view.setPage(self._page)
        layout.addWidget(self._view)

        # TerminalManager
        self._manager = TerminalManager(self)

        # Bridge + WebChannel
        self._bridge = TerminalBridge(self)
        self._bridge.set_input_callback(self._on_input)
        self._bridge.set_resize_callback(self._on_resize)

        self._channel = QWebChannel(self._page)
        self._channel.registerObject("bridge", self._bridge)
        self._page.setWebChannel(self._channel)

        # Manager → Bridge 연결
        self._manager.output_ready.connect(self._bridge.ptyOutput.emit)
        self._manager.session_exited.connect(self._bridge.ptyExited.emit)

        # Send to General: JS → Bridge → Widget signal
        self._bridge.sendToGeneralRequested.connect(
            lambda text: self.apply_to_main_prompt.emit({"general": text})
        )
        self._bridge.sendAndGenerateRequested.connect(
            lambda text: self.send_and_generate.emit({"general": text})
        )

        # HTML 로드
        html_path = os.path.join(WEB_DIR, "terminal.html")
        self._view.load(QUrl.fromLocalFile(html_path))

    def _open_sketch_window(self):
        """Sketch 윈도우 열기 (이미 열려있으면 활성화)."""
        if self._sketch_window is not None:
            self._sketch_window.raise_()
            self._sketch_window.activateWindow()
            return
        from ui.terminal.paint_panel import SketchWindow
        self._sketch_window = SketchWindow()
        self._sketch_window.destroyed.connect(self._on_sketch_closed)
        self._sketch_window.show()

    def _on_sketch_closed(self):
        self._sketch_window = None

    def start_session(self, cmd: list[str] = None, cwd: str = None):
        """PTY 세션 시작. JS가 아직 준비 안 됐으면 ready 시 자동 시작."""
        if self._session_started:
            return
        if not self._terminal_ready:
            self._pending_start = True
            return
        if cmd is None:
            cmd = get_default_shell()
        if cwd is None:
            cwd = os.getcwd()
        success = self._manager.create_session(SESSION_ID, cmd, cwd)
        if success:
            self._session_started = True
            logger.info("Terminal session started")
            self._on_session_started()

    def stop_session(self):
        """PTY 세션 종료."""
        if self._session_started:
            self._manager.destroy_session(SESSION_ID)
            self._session_started = False

    def cleanup(self):
        """위젯 파괴 시 정리."""
        self._manager.destroy_all()
        if self._sketch_window:
            self._sketch_window.close()

    def _on_input(self, session_id: str, data: str):
        """JS → Python: 키 입력 처리."""
        if data == "__TERMINAL_READY__":
            self._terminal_ready = True
            if self._pending_start:
                self._pending_start = False
                self.start_session()
            return
        self._manager.write(session_id, data)

    def _on_session_started(self):
        """세션 시작 직후 자동 실행 명령 전송 (최초 1회)."""
        if not self._auto_exec_done:
            self._auto_exec_done = True
            self._try_auto_exec()

    def _on_resize(self, session_id: str, cols: int, rows: int):
        """JS → Python: 리사이즈 처리."""
        self._manager.resize(session_id, cols, rows)

    # ── 자동 실행 ──

    def _get_auto_exec_command(self) -> str:
        """현재 선택된 자동 실행 명령을 반환."""
        idx = self._auto_exec_combo.currentIndex()
        if idx < 0 or idx >= len(AUTO_EXEC_PRESETS):
            return ""
        _, cmd = AUTO_EXEC_PRESETS[idx]
        if cmd == "__CUSTOM__":
            return self._custom_command
        return cmd

    def _update_auto_exec_display(self):
        """명령어 표시 QLineEdit 갱신."""
        self._auto_exec_display.setText(self._get_auto_exec_command())

    def _on_auto_exec_changed(self, idx: int):
        """콤보박스 선택 변경 시."""
        if idx < 0 or idx >= len(AUTO_EXEC_PRESETS):
            return
        _, cmd = AUTO_EXEC_PRESETS[idx]
        if cmd == "__CUSTOM__":
            self._show_custom_dialog()
        self._save_auto_exec()
        self._update_auto_exec_display()

    def _show_custom_dialog(self):
        """사용자 지정 명령 입력 다이얼로그."""
        text, ok = QInputDialog.getText(
            self, "자동 실행 명령",
            "터미널 시작 시 자동 실행할 명령을 입력하세요:",
            text=self._custom_command,
        )
        if ok:
            self._custom_command = text.strip()
            self._save_auto_exec()
            self._update_auto_exec_display()

    def _save_auto_exec(self):
        """자동 실행 설정 저장."""
        os.makedirs(CLI_DIR, exist_ok=True)
        data = {
            "index": self._auto_exec_combo.currentIndex(),
            "custom_command": self._custom_command,
        }
        with open(AUTO_EXEC_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    def _load_auto_exec(self):
        """저장된 자동 실행 설정 복원."""
        if not os.path.isfile(AUTO_EXEC_FILE):
            return
        try:
            with open(AUTO_EXEC_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._custom_command = data.get("custom_command", "")
            idx = data.get("index", 0)
            if 0 <= idx < len(AUTO_EXEC_PRESETS):
                self._auto_exec_combo.blockSignals(True)
                self._auto_exec_combo.setCurrentIndex(idx)
                self._auto_exec_combo.blockSignals(False)
        except (json.JSONDecodeError, KeyError):
            pass

    def _try_auto_exec(self):
        """터미널 준비 후 자동 실행 명령 전송."""
        cmd = self._get_auto_exec_command()
        if cmd:
            QTimer.singleShot(300, lambda: self._manager.write(SESSION_ID, cmd + "\n"))
