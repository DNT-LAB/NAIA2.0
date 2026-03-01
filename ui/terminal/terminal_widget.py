"""QWebEngineView + QWebChannel + TerminalManager 통합 위젯."""
import os
import logging
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PyQt6.QtWebChannel import QWebChannel
from ui.terminal.terminal_bridge import TerminalBridge
from ui.terminal.terminal_manager import TerminalManager
from ui.terminal.pty_backend import get_default_shell

logger = logging.getLogger(__name__)

SESSION_ID = "main"
WEB_DIR = os.path.join(os.path.dirname(__file__), "web")


class _SilentPage(QWebEnginePage):
    """JS 콘솔 메시지 필터."""

    def javaScriptConsoleMessage(self, level, message, line, source):
        if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            logger.error(f"[terminal.js:{line}] {message}")


class TerminalWidget(QWidget):
    """임베디드 터미널 위젯 — xterm.js + pywinpty."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._session_started = False
        self._terminal_ready = False
        self._pending_start = False

        # 레이아웃
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

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

        # HTML 로드
        html_path = os.path.join(WEB_DIR, "terminal.html")
        self._view.load(QUrl.fromLocalFile(html_path))

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

    def stop_session(self):
        """PTY 세션 종료."""
        if self._session_started:
            self._manager.destroy_session(SESSION_ID)
            self._session_started = False

    def cleanup(self):
        """위젯 파괴 시 정리."""
        self._manager.destroy_all()

    def _on_input(self, session_id: str, data: str):
        """JS → Python: 키 입력 처리."""
        # xterm.js 초기화 완료 시그널 (세션은 탭 선택 시 시작)
        if data == "__TERMINAL_READY__":
            self._terminal_ready = True
            # 이미 start_session() 호출이 대기 중이었으면 실행
            if self._pending_start:
                self._pending_start = False
                self.start_session()
            return
        self._manager.write(session_id, data)

    def _on_resize(self, session_id: str, cols: int, rows: int):
        """JS → Python: 리사이즈 처리."""
        self._manager.resize(session_id, cols, rows)
