"""PTY 세션 관리 + QThread 기반 비동기 읽기."""
import logging
from PyQt6.QtCore import QObject, QThread, pyqtSignal
from legacy_desktop.ui.terminal.pty_backend import create_pty_backend

logger = logging.getLogger(__name__)


class _PtyReaderThread(QThread):
    """백그라운드에서 PTY 출력을 읽는 스레드.

    PtyProcess.read()는 블로킹 호출이므로 UI 스레드에서 직접 호출하면
    프로그램이 응답 없음 상태에 빠진다. 별도 스레드에서 읽어야 한다.
    """

    data_ready = pyqtSignal(str)   # 읽은 데이터
    exited = pyqtSignal(int)       # 종료 코드

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self._backend = backend
        self._running = True

    def run(self):
        while self._running:
            if not self._backend.is_alive():
                break
            try:
                data = self._backend.read()
                if data:
                    self.data_ready.emit(data)
            except EOFError:
                break
            except Exception:
                break

        exit_code = self._backend.get_exitstatus()
        self.exited.emit(exit_code)

    def stop(self):
        self._running = False


class PtySession:
    """단일 PTY 세션 + 리더 스레드."""

    def __init__(self, session_id: str, cmd: list[str], cwd: str):
        self.session_id = session_id
        self.backend = create_pty_backend()
        self.backend.spawn(cmd, cwd)
        self.reader: _PtyReaderThread | None = None


class TerminalManager(QObject):
    """PTY 세션 관리자. 리더 스레드에서 비동기 출력."""

    output_ready = pyqtSignal(str, str)     # session_id, data
    session_exited = pyqtSignal(str, int)   # session_id, exit_code

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sessions: dict[str, PtySession] = {}

    def create_session(self, session_id: str, cmd: list[str], cwd: str) -> bool:
        """새 PTY 세션 생성 + 리더 스레드 시작."""
        if session_id in self._sessions:
            logger.warning(f"Session already exists: {session_id}")
            return False
        try:
            session = PtySession(session_id, cmd, cwd)
            self._sessions[session_id] = session

            # 리더 스레드 시작
            reader = _PtyReaderThread(session.backend, self)
            reader.data_ready.connect(lambda data, sid=session_id: self.output_ready.emit(sid, data))
            reader.exited.connect(lambda code, sid=session_id: self._on_session_exited(sid, code))
            session.reader = reader
            reader.start()

            logger.info(f"Session created: {session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to create session {session_id}: {e}")
            return False

    def destroy_session(self, session_id: str):
        """세션 종료 및 제거."""
        session = self._sessions.pop(session_id, None)
        if not session:
            return
        # 프로세스 종료 → read() 블로킹 해제 → 스레드 자연 종료
        session.backend.kill()
        if session.reader and session.reader.isRunning():
            session.reader.stop()
            session.reader.wait(2000)
        logger.info(f"Session destroyed: {session_id}")

    def write(self, session_id: str, data: str):
        """세션에 입력 전송."""
        session = self._sessions.get(session_id)
        if session:
            session.backend.write(data)

    def resize(self, session_id: str, cols: int, rows: int):
        """세션 터미널 크기 변경."""
        session = self._sessions.get(session_id)
        if session:
            session.backend.resize(cols, rows)

    def destroy_all(self):
        """모든 세션 종료."""
        for sid in list(self._sessions.keys()):
            self.destroy_session(sid)

    def _on_session_exited(self, session_id: str, exit_code: int):
        """리더 스레드에서 프로세스 종료 감지."""
        self._sessions.pop(session_id, None)
        self.session_exited.emit(session_id, exit_code)
        logger.info(f"Session exited: {session_id} (code={exit_code})")
