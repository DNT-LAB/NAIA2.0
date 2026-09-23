"""앱이 소유하는 llama.cpp ``llama-server`` 자식 프로세스 하나를 관리한다(Boost v2 · Assist v2 가 함께 쓴다 —
누가 쓰는지는 임대 ``hold/release`` 로 센다).

실행 계약은 ``C:\\VNR\\DEV\\llama_test`` 실험에서 확인한 값을 따른다: 최대 8 스레드 · context 4096 ·
``--jinja`` + ``enable_thinking=false`` · loopback 무작위 포트 · 단일 슬롯.

GPU(기본): ``-ngl 99 -fa on`` — 동봉 엔진은 공식 Vulkan 판이라 GPU(내장 그래픽 포함)가 있으면 거기서,
없거나 드라이버가 없으면 **자동으로 CPU** 로 돈다(실측 2026-09-23, 장치를 숨겨도 6/6 정상). 285H/Arc 140T
실측: 평소 호출 6.75초로 CPU(6.86초)와 같지만, CPU 가 바쁠 때 CPU 판은 25초로 느려지고 GPU 는 6.7초
그대로다. ``use_gpu=False`` 면 ``-ngl 0`` 으로 CPU 를 강제한다.

GPU 가 여럿이면 ``--device`` 로 하나를 고른다(기본 '자동' = 외장 우선). 실측 RTX 5090 Laptop: 호출 1.07초
(생성 177 tok/s) — Arc 140T 6.34초, CPU 6.86초. 첫 실행은 장치별 셰이더 준비로 한 번 느리다(5090 26초).

- 내가 띄운 프로세스만 다룬다(다른 앱의 llama-server/Ollama 는 절대 건드리지 않는다).
- 요청은 한 번에 하나. 뒤따르는 요청은 남은 제한시간 안에서 기다린다(Auto Gen 은 어차피 직렬).
- 제한시간을 넘기면 프로세스를 내린다 — llama-server 에 요청 단위 취소가 없어 이것이 유일한
  확실한 중단이다. 다음 요청이 다시 올린다.
- 유휴 ``idle_seconds`` 가 지나면 내려서 RAM(약 1.3~2.5 GiB)을 돌려준다.
- Windows 에선 Job Object(KILL_ON_JOB_CLOSE)에 넣어 백엔드가 강제 종료돼도 고아가 남지 않게 한다.
"""

from __future__ import annotations

import json
import math
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


class LlamaStartError(LlamaRuntimeError):
    """엔진이 떴다가 죽었거나 준비되지 못했다 — GPU 로 시작했다면 CPU 로 다시 해 볼 만한 실패."""


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
        use_gpu: bool = True,
        device: str | None = None,
    ) -> None:
        # 요구 설정(use_gpu/device) — 실제로 GPU 를 쓰는지는 effective_gpu(실패하면 CPU 로 내려온다).
        self.use_gpu = bool(use_gpu)
        self.device = device or None
        self.gpu_failed: str | None = None     # GPU 로 못 띄웠거나 GPU 에서 죽은 이유 — 장치 선택을 바꾸면 지운다
        self._running_key: tuple | None = None  # 지금 떠 있는 엔진이 어떤 설정으로 떴는가
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
        # 임대: 엔진을 쓰는 쪽(boost·assist) -> 만료 시각(monotonic). inf = 놓을 때까지. 모두 놓으면 내린다.
        self._leases: dict[str, float] = {}
        self._lease_timer: threading.Timer | None = None
        self.lease_retry_seconds = 5.0         # 요청이 도는 중이라 못 내렸을 때 다시 볼 때까지

    # ── 구성·상태 ──────────────────────────────────────────────────────────

    _KEEP = object()

    def configure(
        self, engine_path: str | Path | None, model_path: str | Path | None, *,
        use_gpu: bool | None = None, device: Any = _KEEP,
    ) -> None:
        """요구 설정을 바꾼다. 떠 있는 엔진이 새 설정과 다르면 **도는 요청이 없을 때만** 곧바로 내린다 —
        요청이 돌고 있으면 그 요청은 끝까지 가고, 끝난 뒤 백그라운드로 새 설정의 엔진을 띄운다(chat).
        장치 선택이 바뀌면 지난 GPU 실패 기록을 지운다(다시 GPU 를 시도한다)."""
        engine = Path(engine_path) if engine_path else None
        model = Path(model_path) if model_path else None
        gpu = self.use_gpu if use_gpu is None else bool(use_gpu)
        dev = self.device if device is LlamaServerRuntime._KEEP else (device or None)
        with self._proc_lock:
            if (gpu, dev) != (self.use_gpu, self.device):
                self.gpu_failed = None
            self.engine_path, self.model_path, self.use_gpu, self.device = engine, model, gpu, dev
        self._stop_if_stale()

    @property
    def effective_gpu(self) -> bool:
        return self.use_gpu and not self.gpu_failed

    def _desired_key(self) -> tuple:
        gpu = self.effective_gpu
        return (str(self.engine_path), str(self.model_path), gpu, self.device if gpu else None)

    def is_stale(self) -> bool:
        """떠 있는 엔진이 지금 요구 설정과 다른가."""
        with self._proc_lock:
            return self._proc is not None and self._proc.poll() is None and self._running_key != self._desired_key()

    def _stop_if_stale(self) -> bool:
        if not self._slot.acquire(blocking=False):
            return False  # 요청이 도는 중 — 끝나고 바꾼다
        try:
            if self.is_stale():
                self.stop()
                return True
            return False
        finally:
            self._slot.release()

    def server_args(self, port: int) -> list[str]:
        args = [
            str(self.engine_path), "-m", str(self.model_path),
            "--host", "127.0.0.1", "--port", str(port),
            "-c", str(self.ctx_size), "-t", str(self.threads),
            "--parallel", "1", "--jinja", "--reasoning-format", "deepseek",
            "--alias", MODEL_ALIAS,
        ]
        if self.effective_gpu:
            args += ["-ngl", "99", "-fa", "on"]
            if self.device:
                args += ["--device", self.device]
        else:
            args += ["-ngl", "0"]
        return args

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
                "use_gpu": self.use_gpu,
                "device": self.device,
                "effective_gpu": self.effective_gpu,
                "gpu_failed": self.gpu_failed,
                "stale": running and self._running_key != self._desired_key(),
                # 누가 붙잡고 있나(남은 초, None = 놓을 때까지)
                "leases": {owner: (None if expiry == math.inf else round(max(0.0, expiry - time.monotonic()), 1))
                           for owner, expiry in self._leases.items()},
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
            self._running_key = None
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
        """엔진을 요구 설정대로 띄워 둔다. GPU 로 시작하지 못하면 이유를 남기고 **CPU 로 한 번 더** 띄운다."""
        try:
            return self._launch(deadline)
        except LlamaStartError as exc:
            if not self.effective_gpu:
                raise
            self.gpu_failed = f"{self.device or 'GPU'} 로 시작하지 못함 — {exc}"
            # CPU 재시도에는 최소한의 시간을 준다(GPU 시도가 제한시간을 거의 다 썼어도).
            return self._launch(max(deadline, time.monotonic() + 30.0))

    def _launch(self, deadline: float) -> int:
        with self._proc_lock:
            if (self._proc is not None and self._proc.poll() is None and self._port
                    and self._running_key == self._desired_key()):
                return self._port
            self.stop()
            if not self.engine_path or not self.engine_path.is_file():
                raise LlamaRuntimeError(f"llama-server 엔진이 없습니다: {self.engine_path or '(경로 미지정)'}")
            if not self.model_path or not self.model_path.is_file():
                raise LlamaRuntimeError(f"모델 파일이 없습니다: {self.model_path or '(경로 미지정)'}")
            port = _free_port()
            args = self.server_args(port)
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
            self._running_key = self._desired_key()
            self._generation += 1
            proc = self._proc
        # 준비 대기는 락 밖에서(stop 이 끼어들 수 있게). /health 200 전엔 요청을 보내지 않는다.
        while True:
            if proc.poll() is not None:
                self.stop()
                raise LlamaStartError("엔진이 시작 중 종료됨(엔진 로그 확인)")
            if time.monotonic() >= deadline:
                self.stop()
                raise LlamaStartError("엔진 준비 시간 초과")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as resp:
                    if resp.status == 200:
                        self.last_load_seconds = round(time.monotonic() - started, 2)
                        return port
            except (urllib.error.URLError, TimeoutError, OSError):
                pass
            time.sleep(0.1)

    # ── 임대(여럿이 한 엔진을 쓴다: Auto Boost · Assist) ────────────────────

    def hold(self, owner: str, seconds: float | None = None) -> None:
        """owner 가 엔진을 쓰는 동안 내리지 않는다. seconds 가 없으면 release 까지, 있으면 그만큼 뒤 만료."""
        with self._proc_lock:
            self._leases[owner] = math.inf if seconds is None else time.monotonic() + max(0.0, float(seconds))
        self._arm_lease_timer()

    def release(self, owner: str) -> bool:
        """owner 의 임대를 끝낸다. 남은 임대가 없고 도는 요청도 없으면 곧바로 내린다(내렸으면 True).
        Auto Boost 를 꺼도 Assist 가 방금 썼다면 엔진은 남는다 — 그 임대가 끝나면 타이머가 내린다."""
        with self._proc_lock:
            self._leases.pop(owner, None)
        return self._stop_if_unleased()

    def leased(self) -> bool:
        now = time.monotonic()
        with self._proc_lock:
            return any(expiry > now for expiry in self._leases.values())

    def _stop_if_unleased(self) -> bool:
        if self.leased():
            self._arm_lease_timer()
            return False
        if not self._slot.acquire(blocking=False):
            self._arm_lease_timer(retry=self.lease_retry_seconds)   # 요청이 도는 중 — 끝난 뒤 다시 본다
            return False
        try:
            if self.leased() or not self.is_running():
                return False
            self.stop()
            return True
        finally:
            self._slot.release()

    def _arm_lease_timer(self, retry: float | None = None) -> None:
        with self._proc_lock:
            if self._lease_timer is not None:
                self._lease_timer.cancel()
                self._lease_timer = None
            if retry is None:
                expiries = list(self._leases.values())
                if not expiries or math.inf in expiries:
                    return          # 임대가 없거나(내릴 사람은 release) 무기한 임대가 있다
                delay = max(0.05, max(expiries) - time.monotonic())
            else:
                delay = retry
            timer = threading.Timer(delay, self._on_lease_timer)
            timer.daemon = True
            self._lease_timer = timer
            timer.start()

    def _on_lease_timer(self) -> None:
        now = time.monotonic()
        with self._proc_lock:
            self._lease_timer = None
            for owner in [o for o, expiry in self._leases.items() if expiry <= now]:
                self._leases.pop(owner, None)
        self._stop_if_unleased()

    def warm(self, timeout: float = DEFAULT_TIMEOUT) -> bool:
        """요청 없이 엔진만 올린다. 이미 요청이 도는 중이면(그 요청이 올린다) 아무것도 안 한다."""
        if not self._slot.acquire(blocking=False):
            return False
        try:
            self._ensure(time.monotonic() + float(timeout))
            return True
        except Exception:
            return False
        finally:
            self._slot.release()
            if self.is_running():
                self._arm_idle_timer()

    # ── 요청 ─────────────────────────────────────────────────────────────

    def chat(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.2,
        timeout: float = DEFAULT_TIMEOUT,
        system: str | None = None,
        grammar: str | None = None,
    ) -> dict[str, Any]:
        """user 메시지 하나(+선택 system)를 보내고 완결된 응답만 성공으로 돌려준다. 절대 raise 하지 않는다.

        ``grammar``(GBNF)를 주면 출력 모양을 강제한다(Assist v2 — 공백 없는 JSON).
        GPU 로 돌다가 엔진이 죽으면(연결 끊김) 이유를 남기고 CPU 로 **한 번 더** 보낸다 — 사용자는 느려질 뿐
        Boost 가 끊기지 않는다. 반환: {ok, text, finish_reason, usage, elapsed, queue_wait, load_seconds, error}
        """
        started = time.monotonic()
        deadline = started + float(timeout)
        extra: dict[str, Any] = {}
        if system:
            extra["system"] = system
        if grammar:
            extra["grammar"] = grammar
        if not self._slot.acquire(timeout=max(0.0, float(timeout))):
            return {"ok": False, "error": "엔진이 다른 요청(Boost·Assist)을 처리하느라 끝나지 않았습니다.",
                    "elapsed": round(time.monotonic() - started, 2)}
        queue_wait = round(time.monotonic() - started, 2)
        try:
            self._cancel_idle_timer()
            for attempt in range(2):
                was_running = self.is_running() and not self.is_stale()
                try:
                    port = self._ensure(deadline)
                    data = self._post(port, prompt, max_tokens, temperature, deadline, **extra)
                except urllib.error.URLError as exc:
                    if isinstance(getattr(exc, "reason", None), (TimeoutError, socket.timeout)):
                        raise TimeoutError from exc
                    crashed_on_gpu = self.effective_gpu
                    self.stop()
                    if crashed_on_gpu and attempt == 0:
                        self.gpu_failed = f"{self.device or 'GPU'} 에서 엔진이 멈춤 — {exc}"
                        deadline = max(deadline, time.monotonic() + 30.0)
                        continue  # CPU 로 한 번 더
                    return {"ok": False, "error": f"llama-server 통신 실패: {exc}",
                            "elapsed": round(time.monotonic() - started, 2)}
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
                    "load_seconds": 0.0 if was_running else self.last_load_seconds,
                    "gpu": self.effective_gpu,
                    "gpu_failed": self.gpu_failed,
                }
            return {"ok": False, "error": "llama-server 통신 실패", "elapsed": round(time.monotonic() - started, 2)}
        except (TimeoutError, socket.timeout):
            self.stop()  # 요청 단위 취소가 없다 — 내려야 다음 요청이 막히지 않는다.
            return {"ok": False, "error": f"{timeout:.0f}초 제한시간 초과", "elapsed": round(time.monotonic() - started, 2)}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "elapsed": round(time.monotonic() - started, 2)}
        finally:
            self._slot.release()
            if self.is_stale():
                # 요청 도중 장치가 바뀌었다 — 이제 비었으니 새 설정의 엔진을 뒤에서 띄운다(다음 요청이 기다리지 않게).
                threading.Thread(target=self.warm, daemon=True, name="llama-swap").start()
            elif self.is_running():
                self._arm_idle_timer()

    def _post(self, port: int, prompt: str, max_tokens: int, temperature: float, deadline: float,
              system: str | None = None, grammar: str | None = None) -> dict[str, Any]:
        messages = [{"role": "system", "content": str(system)}] if system else []
        messages.append({"role": "user", "content": str(prompt)})
        body: dict[str, Any] = {
            "model": MODEL_ALIAS,
            "messages": messages,
            "stream": False,
            "max_tokens": int(max_tokens),
            "temperature": float(temperature),
            "chat_template_kwargs": {"enable_thinking": False},
        }
        if grammar:
            body["grammar"] = grammar     # llama-server 는 chat 끝점에서도 GBNF 를 받는다(실측 b10830)
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        with urllib.request.urlopen(req, timeout=remaining) as resp:
            return json.loads(resp.read().decode("utf-8"))


# ── 장치 감지 ──────────────────────────────────────────────────────────────

_DEVICE_CACHE: dict[tuple[str, float], list[dict[str, str]]] = {}
_DISCRETE_HINTS = ("nvidia", "geforce", "rtx", "quadro", "radeon rx", "arc(tm) a", "arc(tm) b")


def list_devices(engine_path: str | Path | None) -> list[str]:
    """엔진이 쓸 수 있는 GPU 이름들(예: 'Intel(R) Arc(TM) 140T GPU (32GB)'). 비면 GPU 없음(CPU 로 돈다)."""
    return [entry["name"] for entry in list_device_entries(engine_path)]


def choose_device(entries: list[dict[str, str]], preference: str | None) -> str | None:
    """설정의 장치 선호로 ``--device`` 값을 고른다. 'auto' = 외장 GPU(NVIDIA·Radeon RX·Arc A/B) 우선,
    없으면 첫 GPU. 지정한 장치가 사라졌으면 자동으로 되돌아간다. GPU 가 없으면 None(엔진이 CPU 로 돈다)."""
    if not entries:
        return None
    wanted = str(preference or "auto")
    if wanted != "auto" and any(entry["id"] == wanted for entry in entries):
        return wanted
    for entry in entries:
        if any(hint in entry["name"].lower() for hint in _DISCRETE_HINTS):
            return entry["id"]
    return entries[0]["id"]


def list_device_entries(engine_path: str | Path | None) -> list[dict[str, str]]:
    """``llama-server --list-devices`` 결과를 [{id:'Vulkan1', name:'NVIDIA GeForce RTX 5090 Laptop GPU'}] 로.
    엔진 파일(경로·수정시각)마다 한 번만 잰다 — 약 1초 걸린다."""
    path = Path(engine_path) if engine_path else None
    if path is None or not path.is_file():
        return []
    key = (str(path), path.stat().st_mtime)
    if key in _DEVICE_CACHE:
        return [dict(entry) for entry in _DEVICE_CACHE[key]]
    import re

    devices: list[dict[str, Any]] = []
    try:
        out = subprocess.run(
            [str(path), "--list-devices"], cwd=str(path.parent), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        seen = False
        for line in (out.stdout or "").splitlines() + (out.stderr or "").splitlines():
            if line.strip().startswith("Available devices"):
                seen = True
                continue
            if seen and ":" in line and "(none)" not in line:
                # "  Vulkan0: Intel(R) Arc(TM) 140T GPU (32GB) (37024 MiB, 47802 MiB free)"
                device_id, name = (part.strip() for part in line.split(":", 1))
                mem = re.search(r"\((\d+) MiB, (\d+) MiB free\)\s*$", name)
                clean = re.sub(r"\s*\(\d+ MiB[^)]*\)\s*$", "", name)
                devices.append({
                    "id": device_id,
                    "name": clean,
                    "vram_mib": int(mem.group(1)) if mem else 0,
                    "kind": "discrete" if any(h in clean.lower() for h in _DISCRETE_HINTS) else "integrated",
                })
    except Exception:
        devices = []
    _DEVICE_CACHE[key] = devices
    return [dict(entry) for entry in devices]


def _cpu_name() -> str:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            return " ".join(str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).split())
    except Exception:
        import platform

        return platform.processor() or "CPU"


def _ram_gib() -> float:
    try:
        import ctypes

        class _Mem(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        mem = _Mem()
        mem.dwLength = ctypes.sizeof(_Mem)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)):
            return round(mem.ullTotalPhys / (1024 ** 3), 1)
    except Exception:
        pass
    return 0.0


def hardware_summary(engine_path: str | Path | None) -> dict[str, Any]:
    """이 PC 의 할당 가능한 자원: CPU(이름·스레드) · RAM · 엔진이 볼 수 있는 GPU(VRAM · 외장/내장)."""
    return {
        "cpu": _cpu_name(),
        "threads": os.cpu_count() or 0,
        "ram_gib": _ram_gib(),
        "gpus": list_device_entries(engine_path),
    }


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
