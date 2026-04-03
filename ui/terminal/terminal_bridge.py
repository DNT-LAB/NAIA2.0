"""QWebChannel 브리지 — Python ↔ JS 통신."""
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QApplication


class TerminalBridge(QObject):
    """QWebChannel을 통한 PTY ↔ xterm.js 브리지."""

    # Python → JS (시그널)
    ptyOutput = pyqtSignal(str, str)    # session_id, data
    ptyExited = pyqtSignal(str, int)    # session_id, exit_code
    clipboardResult = pyqtSignal(str)   # 클립보드 읽기 결과 → JS
    sendToGeneralRequested = pyqtSignal(str)  # 선택 텍스트 → 메인 프롬프트
    sendAndGenerateRequested = pyqtSignal(str)  # 선택 텍스트 → 메인 프롬프트 + 생성

    def __init__(self, parent=None):
        super().__init__(parent)
        self._input_callback = None
        self._resize_callback = None

    def set_input_callback(self, callback):
        """JS → Python 입력 콜백 등록."""
        self._input_callback = callback

    def set_resize_callback(self, callback):
        """JS → Python 리사이즈 콜백 등록."""
        self._resize_callback = callback

    @pyqtSlot(str, str)
    def ptyInput(self, session_id: str, data: str):
        """JS에서 호출: 키 입력을 PTY로 전달."""
        if self._input_callback:
            self._input_callback(session_id, data)

    @pyqtSlot(str, int, int)
    def ptyResize(self, session_id: str, cols: int, rows: int):
        """JS에서 호출: 터미널 크기 변경을 PTY로 전달."""
        if self._resize_callback:
            self._resize_callback(session_id, cols, rows)

    @pyqtSlot(str)
    def copyToClipboard(self, text: str):
        """JS → Python: Qt 클립보드에 텍스트 복사 (QtWebEngine 보안 우회)."""
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(text or "")

    @pyqtSlot()
    def readClipboard(self):
        """JS → Python: Qt 클립보드 읽기 → clipboardResult 시그널로 반환."""
        clipboard = QApplication.clipboard()
        text = clipboard.text() if clipboard else ""
        self.clipboardResult.emit(text)

    @pyqtSlot(str)
    def sendToGeneral(self, text: str):
        """JS → Python: 선택 텍스트를 메인 프롬프트로 전송."""
        if text and text.strip():
            self.sendToGeneralRequested.emit(text.strip())

    @pyqtSlot(str)
    def sendAndGenerate(self, text: str):
        """JS → Python: 선택 텍스트를 메인 프롬프트로 전송 + 이미지 생성."""
        if text and text.strip():
            self.sendAndGenerateRequested.emit(text.strip())
