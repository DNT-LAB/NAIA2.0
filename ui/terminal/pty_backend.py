"""크로스 플랫폼 PTY 백엔드. Windows: pywinpty, Unix: pty 표준 라이브러리."""
import os
import sys
import logging

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"


def get_default_shell() -> list[str]:
    """플랫폼에 맞는 기본 셸 반환."""
    if IS_WINDOWS:
        return ["cmd.exe"]
    shell = os.environ.get("SHELL", "/bin/bash")
    return [shell]


class _WinPtyBackend:
    """pywinpty 기반 Windows PTY."""

    def __init__(self):
        from winpty import PtyProcess
        self._pty_class = PtyProcess
        self._process = None

    def spawn(self, cmd: list[str], cwd: str, env: dict = None):
        spawn_env = os.environ.copy()
        if env:
            spawn_env.update(env)
        self._process = self._pty_class.spawn(cmd, cwd=cwd, env=spawn_env)
        logger.info(f"WinPTY spawned: {cmd} in {cwd}")

    def read(self) -> str:
        if not self._process:
            return ""
        try:
            return self._process.read(4096)
        except EOFError:
            return ""
        except Exception:
            return ""

    def write(self, data: str):
        if self._process:
            self._process.write(data)

    def resize(self, cols: int, rows: int):
        if self._process:
            try:
                self._process.setwinsize(rows, cols)
            except Exception as e:
                logger.debug(f"Resize failed: {e}")

    def is_alive(self) -> bool:
        if not self._process:
            return False
        return self._process.isalive()

    def get_exitstatus(self) -> int:
        if self._process:
            return self._process.exitstatus or 0
        return -1

    def kill(self):
        if self._process:
            try:
                if self._process.isalive():
                    self._process.terminate()
            except Exception as e:
                logger.debug(f"Kill failed: {e}")
            finally:
                self._process = None


class _UnixPtyBackend:
    """pty 표준 라이브러리 기반 Unix PTY (macOS/Linux)."""

    def __init__(self):
        import pty as _pty
        import fcntl
        import struct
        import termios
        import signal
        self._pty = _pty
        self._fcntl = fcntl
        self._struct = struct
        self._termios = termios
        self._signal = signal
        self._master_fd: int | None = None
        self._pid: int | None = None
        self._exited = False
        self._exit_code = -1

    def spawn(self, cmd: list[str], cwd: str, env: dict = None):
        spawn_env = os.environ.copy()
        spawn_env["TERM"] = "xterm-256color"
        if env:
            spawn_env.update(env)
        pid, master_fd = self._pty.fork()
        if pid == 0:
            # 자식 프로세스
            os.chdir(cwd)
            os.execvpe(cmd[0], cmd, spawn_env)
        else:
            # 부모 프로세스
            self._pid = pid
            self._master_fd = master_fd
            # non-blocking 불필요 — 리더 스레드에서 블로킹 read 사용
            logger.info(f"UnixPTY spawned: {cmd} in {cwd} (pid={pid})")

    def read(self) -> str:
        if self._master_fd is None:
            return ""
        try:
            data = os.read(self._master_fd, 4096)
            if not data:
                return ""
            return data.decode("utf-8", errors="replace")
        except OSError:
            return ""

    def write(self, data: str):
        if self._master_fd is not None:
            os.write(self._master_fd, data.encode("utf-8"))

    def resize(self, cols: int, rows: int):
        if self._master_fd is not None:
            try:
                winsize = self._struct.pack("HHHH", rows, cols, 0, 0)
                self._fcntl.ioctl(self._master_fd, self._termios.TIOCSWINSZ, winsize)
            except Exception as e:
                logger.debug(f"Resize failed: {e}")

    def is_alive(self) -> bool:
        if self._pid is None or self._exited:
            return False
        try:
            pid, status = os.waitpid(self._pid, os.WNOHANG)
            if pid == 0:
                return True
            self._exited = True
            if os.WIFEXITED(status):
                self._exit_code = os.WEXITSTATUS(status)
            else:
                self._exit_code = -1
            return False
        except ChildProcessError:
            self._exited = True
            return False

    def get_exitstatus(self) -> int:
        if not self._exited:
            self.is_alive()  # 종료 상태 업데이트
        return self._exit_code

    def kill(self):
        if self._pid and not self._exited:
            try:
                self._signal.signal(self._signal.SIGCHLD, self._signal.SIG_IGN)
                os.kill(self._pid, self._signal.SIGTERM)
            except ProcessLookupError:
                pass
            except Exception as e:
                logger.debug(f"Kill failed: {e}")
            finally:
                self._exited = True
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None
        self._pid = None


def create_pty_backend():
    """플랫폼에 맞는 PTY 백엔드 인스턴스 생성."""
    if IS_WINDOWS:
        return _WinPtyBackend()
    return _UnixPtyBackend()
