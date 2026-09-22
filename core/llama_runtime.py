"""앱이 소유하는 llama.cpp ``llama-server`` 자식 프로세스 하나를 관리한다(Boost v2 용).

실행 계약은 ``C:\\VNR\\DEV\\llama_test`` 실험에서 확인한 값을 따른다: CPU(-ngl 0) · 최대 8 스레드 ·
context 4096 · ``--jinja`` + ``enable_thinking=false`` · loopback 무작위 포트 · 단일 슬롯.

- 내가 띄운 프로세스만 다룬다(다른 앱의 llama-server/Ollama 는 절대 건드리지 않는다).
- 요청은 한 번에 하나. 뒤따르는 요청은 남은 제한시간 안에서 기다린다(Auto Gen 은 어차피 직렬).
- 제한시간을 넘기면 프로세스를 내린다 — llama-server 에 요청 단위 취소가 없어 이것이 유일한
  확실한 중단이다. 다음 요청이 다시 올린다.
- 유휴 ``idle_seconds`` 가 지나면 내려서 RAM(약 1.3~2.5 GiB)을 돌려준다.
- Windows 에선 Job Object(KILL_ON_JOB_CLOSE)에 넣어 백엔드가 강제 종료돼도 고아가 남지 않게 한다.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_MODEL_FILE = "gemma-4-E2B-it-qat-q4_0.gguf"
MODEL_ALIAS = "naia-boost"
DEFAULT_TIMEOUT = 60.0
DEFAULT_IDLE_SECONDS = 180.0


class LlamaRuntimeError(RuntimeError):
    pass


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _attach_kill_on_close_job(proc: subprocess.Popen) -> Any:
    """자식을 KILL_ON_JOB_CLOSE Job 에 넣는다. 핸들이 닫히면(부모 사망 포함) 자식도 죽는다.
    실패는 조용히 None — 정상 종료 경로(stop)는 이것 없이도 동작한다."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class _BasicLimit(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class _IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
            )]

        class _ExtendedLimit(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _BasicLimit),
                ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.OpenProcess.restype = wintypes.HANDLE
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = _ExtendedLimit()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            kernel32.CloseHandle(job)
            return None
        handle = kernel32.OpenProcess(0x0001 | 0x0100, False, proc.pid)  # TERMINATE | SET_QUOTA
        if not handle:
            kernel32.CloseHandle(job)
            return None
        ok = kernel32.AssignProcessToJobObject(job, handle)
        kernel32.CloseHandle(handle)
        if not ok:
            kernel32.CloseHandle(job)
            return None
        return (kernel32, job)
    except Exception:
        return None


def _close_job(job: Any) -> None:
    if not job:
        return
    try:
        kernel32, handle = job
        kernel32.CloseHandle(handle)
    except Exception:
        pass


class LlamaServerRuntime:
    def __init__(
        self,
        engine_path: str | Path | None = None,
        model_path: str | Path | None = None,
        *,
        threads: int | None = None,
        ctx_size: int = 4096,
        idle_seconds: float = DEFAULT_IDLE_SECONDS,
        log_path: str | Path | None = None,
    ) -> None:
        self.engine_path = Path(engine_path) if engine_path else None
        self.model_path = Path(model_path) if model_path else None
        self.threads = int(threads or min(8, os.cpu_count() or 4))
        self.ctx_size = int(ctx_size)
        self.idle_seconds = float(idle_seconds)
        self.log_path = Path(log_path) if log_path else None
        self._slot = threading.Lock()          # 요청 단일 슬롯
        self._proc_lock = threading.RLock()    # 프로세스 핸들·포트·세대
        self._proc: subprocess.Popen | None = None
        self._job: Any = None
        self._log_file: Any = None
        self._port: int | None = None
        self._generation = 0                   # 올릴 때마다 +1 (늦은 유휴 타이머가 새 프로세스를 못 내리게)
        self._idle_timer: threading.Timer | None = None
        self.last_load_seconds: float | None = None

    # ── 구성·상태 ──────────────────────────────────────────────────────────

    def configure(self, engine_path: str | Path | None, model_path: str | Path | None) -> None:
        """경로가 바뀌면 돌던 프로세스를 내린다(다음 요청이 새 경로로 올린다)."""
        engine = Path(engine_path) if engine_path else None
        model = Path(model_path) if model_path else None
        with self._proc_lock:
            if engine != self.engine_path or model != self.model_path:
                self.stop()
                self.engine_path, self.model_path = engine, model

    def is_running(self) -> bool:
        with self._proc_lock:
            return self._proc is not None and self._proc.poll() is None

    def status(self) -> dict[str, Any]:
        with self._proc_lock:
            running = self._proc is not None and self._proc.poll() is None
            return {
                "engine_path": str(self.engine_path or ""),
                "model_path": str(self.model_path or ""),
                "engine_exists": bool(self.engine_path and self.engine_path.is_file()),
                "model_exists": bool(self.model_path and self.model_path.is_file()),
                "running": running,
                "pid": self._proc.pid if running and self._proc else None,
                "port": self._port if running else None,
                "busy": self._slot.locked(),
                "last_load_seconds": self.last_load_seconds,
            }

    # ── 수명 ─────────────────────────────────────────────────────────────

    def stop(self) -> None:
        with self._proc_lock:
            self._cancel_idle_timer()
            proc, self._proc = self._proc, None
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        pass
            _close_job(self._job)
            self._job = None
            self._port = None
            if self._log_file is not None:
                try:
                    self._log_file.close()
                except Exception:
                    pass
                self._log_file = None

    def _cancel_idle_timer(self) -> None:
        timer, self._idle_timer = self._idle_timer, None
        if timer is not None:
            timer.cancel()

    def _arm_idle_timer(self) -> None:
        if self.idle_seconds <= 0:
            return
        with self._proc_lock:
            self._cancel_idle_timer()
            generation = self._generation
            timer = threading.Timer(self.idle_seconds, self._idle_stop, args=(generation,))
            timer.daemon = True
            self._idle_timer = timer
            timer.start()

    def _idle_stop(self, generation: int) -> None:
        # 요청이 도는 중이면 내리지 않는다(끝나면 다시 무장된다).
        if not self._slot.acquire(blocking=False):
            return
        try:
            with self._proc_lock:
                if generation == self._generation:
                    self.stop()
        finally:
            self._slot.release()

    def _ensure(self, deadline: float) -> int:
        with self._proc_lock:
            if self._proc is not None and self._proc.poll() is None and self._port:
                return self._port
            self.stop()
            if not self.engine_path or not self.engine_path.is_file():
                raise LlamaRuntimeError(f"llama-server 엔진이 없습니다: {self.engine_path or '(경로 미지정)'}")
            if not self.model_path or not self.model_path.is_file():
                raise LlamaRuntimeError(f"모델 파일이 없습니다: {self.model_path or '(경로 미지정)'}")
            port = _free_port()
            args = [
                str(self.engine_path), "-m", str(self.model_path),
                "--host", "127.0.0.1", "--port", str(port),
                "-c", str(self.ctx_size), "-ngl", "0", "-t", str(self.threads),
                "--parallel", "1", "--jinja", "--reasoning-format", "deepseek",
                "--alias", MODEL_ALIAS,
            ]
            if self.log_path is not None:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                self._log_file = self.log_path.open("ab")
                out = self._log_file
            else:
                out = subprocess.DEVNULL
            started = time.monotonic()
            self._proc = subprocess.Popen(
                args, cwd=str(self.engine_path.parent), stdin=subprocess.DEVNULL, stdout=out, stderr=out,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self._job = _attach_kill_on_close_job(self._proc)
            self._port = port
            self._generation += 1
            proc = self._proc
        # 준비 대기는 락 밖에서(stop 이 끼어들 수 있게). /health 200 전엔 요청을 보내지 않는다.
        while True:
            if proc.poll() is not None:
                self.stop()
                raise LlamaRuntimeError("llama-server 가 시작 중 종료되었습니다(엔진 로그 확인).")
            if time.monotonic() >= deadline:
                self.stop()
                raise LlamaRuntimeError("llama-server 준비 시간 초과")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as resp:
                    if resp.status == 200:
                        self.last_load_seconds = round(time.monotonic() - started, 2)
                        return port
            except (urllib.error.URLError, TimeoutError, OSError):
                pass
            time.sleep(0.1)

    # ── 요청 ─────────────────────────────────────────────────────────────

    def chat(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.2,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> dict[str, Any]:
        """user 메시지 하나를 보내고 완결된 응답만 성공으로 돌려준다. 절대 raise 하지 않는다.

        반환: {ok, text, finish_reason, usage, elapsed, queue_wait, load_seconds, error}
        """
        started = time.monotonic()
        deadline = started + float(timeout)
        if not self._slot.acquire(timeout=max(0.0, float(timeout))):
            return {"ok": False, "error": "다른 Boost 요청이 끝나지 않았습니다.", "elapsed": round(time.monotonic() - started, 2)}
        queue_wait = round(time.monotonic() - started, 2)
        loaded_now = False
        try:
            self._cancel_idle_timer()
            was_running = self.is_running()
            port = self._ensure(deadline)
            loaded_now = not was_running
            body = {
                "model": MODEL_ALIAS,
                "messages": [{"role": "user", "content": str(prompt)}],
                "stream": False,
                "max_tokens": int(max_tokens),
                "temperature": float(temperature),
                "chat_template_kwargs": {"enable_thinking": False},
            }
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/v1/chat/completions",
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            with urllib.request.urlopen(req, timeout=remaining) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            choice = (data.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            if message.get("reasoning_content"):
                raise LlamaRuntimeError("no-think 계약 위반: reasoning_content 가 반환되었습니다.")
            finish = choice.get("finish_reason")
            if finish != "stop":
                raise LlamaRuntimeError(f"응답이 정상 종료되지 않았습니다(finish_reason={finish}).")
            return {
                "ok": True,
                "text": str(message.get("content") or ""),
                "finish_reason": finish,
                "usage": data.get("usage") or {},
                "elapsed": round(time.monotonic() - started, 2),
                "queue_wait": queue_wait,
                "load_seconds": self.last_load_seconds if loaded_now else 0.0,
            }
        except (TimeoutError, socket.timeout):
            self.stop()  # 요청 단위 취소가 없다 — 내려야 다음 요청이 막히지 않는다.
            return {"ok": False, "error": f"{timeout:.0f}초 제한시간 초과", "elapsed": round(time.monotonic() - started, 2)}
        except urllib.error.URLError as exc:
            if isinstance(getattr(exc, "reason", None), (TimeoutError, socket.timeout)):
                self.stop()
                return {"ok": False, "error": f"{timeout:.0f}초 제한시간 초과", "elapsed": round(time.monotonic() - started, 2)}
            self.stop()
            return {"ok": False, "error": f"llama-server 통신 실패: {exc}", "elapsed": round(time.monotonic() - started, 2)}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "elapsed": round(time.monotonic() - started, 2)}
        finally:
            self._slot.release()
            if self.is_running():
                self._arm_idle_timer()


# ── 경로 해석 ──────────────────────────────────────────────────────────────


def default_engine_path(repo_root: str | Path) -> Path:
    """앱 동봉 위치. 배포본은 여기에 공식 CPU 배포본(DLL 포함)을 통째로 둔다."""
    exe = "llama-server.exe" if os.name == "nt" else "llama-server"
    return Path(repo_root) / "runtime" / "llama" / "engine" / exe


def default_model_path(save_root: str | Path) -> Path:
    """첫 사용 시 내려받는 위치 — 사용자 데이터 쪽(업데이트로 지워지지 않게)."""
    return Path(save_root) / "models" / "llm" / DEFAULT_MODEL_FILE


def resolve_paths(settings: dict[str, Any], *, repo_root: str | Path, save_root: str | Path) -> tuple[Path, Path]:
    """설정 > 환경변수(NAIA_LLAMA_SERVER / NAIA_LLAMA_MODEL) > 기본 위치."""
    engine = (settings or {}).get("engine_path") or os.environ.get("NAIA_LLAMA_SERVER") or ""
    model = (settings or {}).get("model_path") or os.environ.get("NAIA_LLAMA_MODEL") or ""
    return (
        Path(engine) if engine else default_engine_path(repo_root),
        Path(model) if model else default_model_path(save_root),
    )
