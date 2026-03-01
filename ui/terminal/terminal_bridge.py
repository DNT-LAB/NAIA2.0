"""QWebChannel 브리지 — Python ↔ JS 통신."""
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot


class TerminalBridge(QObject):
    """QWebChannel을 통한 PTY ↔ xterm.js 브리지."""

    # Python → JS (시그널)
    ptyOutput = pyqtSignal(str, str)    # session_id, data
    ptyExited = pyqtSignal(str, int)    # session_id, exit_code

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
