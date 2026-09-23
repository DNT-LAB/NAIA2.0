"""Kiwi(한국어 형태소 분석기)를 **처음 쓸 때** 설치한다 — 사용자 결정 2026-09-23.

요구사항(requirements-headless.txt)에 넣으면 업데이트 뒤 첫 실행에 모든 사용자가 약 90MB 를 받고, 그 설치가
실패하면(오프라인 등) 앱이 아예 뜨지 않는다(main.cjs ``ensureManagedRuntimeEnv`` 가 던진다). 그래서 Assist 를
처음 열 때 사용자가 [설치]를 눌러, 지금 도는 파이썬 환경(포터블 = user-data/runtime-env)에 넣는다.

- kiwipiepy_model 은 PyPI 에 **sdist 만** 있다 → pip 가 받아서 현장에서 빌드한다(빌드 격리용 setuptools 도 받는다).
  그래서 확장 의존성 설치(``--only-binary=:all: --target``)와 달리 소스 빌드를 막지 않고 지금 환경에 그대로 넣는다.
- 포터블의 **기본 파이썬에는 pip 가 없다** — runtime-env(venv) 안의 pip 를 쓴다(= ``sys.executable``).
- 설치 전이거나 실패해도 Assist 는 산다 — 한국어 층만 꺼지고 모델 구조 추출로 간다.
"""

from __future__ import annotations

import collections
import importlib
import importlib.util
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

REQUIREMENT = "kiwipiepy==0.23.2"
MODULES = ("kiwipiepy", "kiwipiepy_model")
APPROX_MB = 90                    # kiwipiepy_model sdist 88.1MB + kiwipiepy 휠 + tqdm
TIMEOUT_SECONDS = 30 * 60
MANUAL_COMMAND = f"python -m pip install {REQUIREMENT}"
_PROGRESS = re.compile(r"^Progress (\d+) of (\d+)")          # --progress-bar raw (pip 24.1+, 0.25초 간격)
_DOWNLOADING = re.compile(r"^\s*Downloading (\S+?)(?: \(([^)]+)\))?\s*$")
_TAIL = 30


def kiwi_installed() -> bool:
    """두 모듈이 지금 환경에서 찾아지나. 설치 직후 같은 프로세스에서도 보이게 찾기 캐시를 비운다."""
    importlib.invalidate_caches()
    return all(importlib.util.find_spec(name) is not None for name in MODULES)


def explain_failure(lines: list[str]) -> str:
    """pip 출력 꼬리 -> 사용자에게 보일 한 줄."""
    text = "\n".join(lines)
    low = text.lower()
    if any(k in low for k in ("failed to establish a new connection", "getaddrinfo failed", "name resolution",
                              "connection aborted", "read timed out", "no matching distribution found",
                              "could not find a version that satisfies")):
        return "인터넷에 연결할 수 없습니다 — 연결을 확인하고 다시 눌러 주세요."
    if "no space left" in low or "errno 28" in low:
        return "디스크 공간이 부족합니다(설치에 약 200MB 가 필요합니다)."
    if "externally-managed-environment" in low:
        return f"이 파이썬은 pip 설치를 막아 둔 환경입니다 — 직접 설치해 주세요: {MANUAL_COMMAND}"
    if "permission denied" in low or "access is denied" in low or "winerror 5" in low:
        return "설치할 권한이 없습니다(다른 프로그램이 파일을 쓰고 있을 수 있습니다) — 앱을 다시 시작한 뒤 눌러 주세요."
    errors = [ln.strip() for ln in lines if ln.strip().startswith("ERROR:")]
    last = errors[-1] if errors else next((ln.strip() for ln in reversed(lines) if ln.strip()), "")
    return f"설치 실패: {last[:200]}" if last else "설치 실패(원인 불명) — 로그를 확인해 주세요."


class KiwiInstaller:
    """pip 를 뒤에서 돌리고 진행을 상태로 들고 있는다(Boost 모델 받기와 같은 모양: snapshot/start)."""

    def __init__(self, *, python: str | None = None, log_path: Path | str | None = None,
                 popen: Callable[..., Any] | None = None, installed: Callable[[], bool] | None = None,
                 on_installed: Callable[[], Any] | None = None, timeout: float = TIMEOUT_SECONDS) -> None:
        self.python = python or sys.executable
        self.log_path = Path(log_path) if log_path else None
        self._popen = popen or subprocess.Popen
        self._check = installed or kiwi_installed
        self._on_installed = on_installed
        self.timeout = float(timeout)
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._known = False                 # 한 번 설치를 확인하면 이 프로세스 동안은 다시 안 찾는다
        self._timed_out = False
        self._state: dict[str, Any] = {
            "active": False, "phase": "idle", "percent": 0, "message": "", "error": "", "done": False,
            "approx_mb": APPROX_MB, "manual_command": MANUAL_COMMAND, "log_tail": [], "updated_at": "",
        }

    def command(self) -> list[str]:
        return [self.python, "-m", "pip", "install", "--disable-pip-version-check", "--no-input",
                "--progress-bar", "raw", REQUIREMENT]

    def installed(self) -> bool:
        if not self._known:
            try:
                self._known = bool(self._check())
            except Exception:
                self._known = False
        return self._known

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            state = dict(self._state)
            state["log_tail"] = list(self._state["log_tail"])
        state["installed"] = self.installed()
        return state

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._state["active"]:
                return self.snapshot()
            if self.installed():
                self._set(phase="complete", percent=100, done=True, error="", message="이미 설치되어 있습니다.")
                return self.snapshot()
            self._timed_out = False
            self._state.update({"active": True, "phase": "start", "percent": 0, "message": "설치를 시작하는 중...",
                                "error": "", "done": False, "log_tail": []})
            self._thread = threading.Thread(target=self._run, daemon=True, name="assist-kiwi-install")
            self._thread.start()
        return self.snapshot()

    def wait(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    # ── 내부 ──────────────────────────────────────────────────────────────

    def _set(self, **changes: Any) -> None:
        with self._lock:
            self._state.update(changes)
            self._state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    def _kill(self, proc: Any) -> None:
        self._timed_out = True
        try:
            proc.kill()
        except Exception:
            pass

    def _run(self) -> None:
        tail: collections.deque[str] = collections.deque(maxlen=_TAIL)
        log = None
        try:
            if self.log_path is not None:
                try:
                    self.log_path.parent.mkdir(parents=True, exist_ok=True)
                    log = self.log_path.open("w", encoding="utf-8")
                except OSError:
                    log = None
            env = dict(os.environ, PIP_DISABLE_PIP_VERSION_CHECK="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
            proc = self._popen(self.command(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                               encoding="utf-8", errors="replace", env=env,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            timer = threading.Timer(self.timeout, self._kill, args=(proc,))   # 끝없이 매달리지 않게
            timer.daemon = True
            timer.start()
            try:
                for raw in proc.stdout:
                    line = raw.rstrip()
                    if not line:
                        continue
                    if log is not None:
                        log.write(line + "\n")
                    if not _PROGRESS.match(line):
                        tail.append(line)
                    self._on_line(line)
                code = proc.wait()
            finally:
                timer.cancel()
            if self._timed_out:
                raise TimeoutError(f"설치가 {int(self.timeout // 60)}분 안에 끝나지 않아 멈췄습니다 — 다시 눌러 주세요.")
            if code != 0:
                raise RuntimeError(explain_failure(list(tail)))
            if not self.installed():
                raise RuntimeError("설치는 끝났지만 불러올 수 없습니다 — 앱을 다시 시작해 주세요.")
            if self._on_installed is not None:
                self._set(phase="prepare", percent=100, message="한국어 분석기를 준비하는 중...")
                try:
                    self._on_installed()
                except Exception:
                    pass                      # 준비는 첫 요청이 다시 한다
            self._set(active=False, phase="complete", percent=100, done=True, error="", message="설치 완료",
                      log_tail=list(tail)[-5:])
        except FileNotFoundError:
            self._fail(f"파이썬(pip)을 찾을 수 없습니다 — 직접 설치해 주세요: {MANUAL_COMMAND}", tail)
        except Exception as exc:
            self._fail(str(exc) or type(exc).__name__, tail)
        finally:
            if log is not None:
                log.close()

    def _fail(self, message: str, tail: Any) -> None:
        self._set(active=False, phase="error", message=message, error=message, done=False,
                  log_tail=list(tail)[-12:])

    def _on_line(self, line: str) -> None:
        m = _PROGRESS.match(line)
        if m:
            done, total = int(m.group(1)), int(m.group(2))
            if total > 0:
                self._set(percent=min(99, done * 100 // total))
            return
        text = line.strip()
        if text.startswith("Collecting "):
            self._set(phase="resolve", message=f"찾는 중: {text[len('Collecting '):]}")
        elif text.startswith("Downloading "):
            d = _DOWNLOADING.match(text)
            name = (d.group(1) if d else text[len("Downloading "):]).rsplit("/", 1)[-1]
            size = d.group(2) if d and d.group(2) else ""
            self._set(phase="download", percent=0, message=f"받는 중: {name}" + (f" ({size})" if size else ""))
        elif text.startswith(("Building wheel", "Building wheels")):
            self._set(phase="build", percent=0, message="모델 패키지를 만드는 중 — 1~2분 걸릴 수 있습니다.")
        elif text.startswith("Installing collected packages"):
            self._set(phase="install", percent=0, message="설치 중...")
