"""앱이 소유하는 llama.cpp ``llama-server`` 자식 프로세스 하나를 관리한다(Boost v2 · Assist v2 가 함께 쓴다 —
누가 쓰는지는 임대 ``hold/release`` 로 센다).

실행 계약은 ``C:\\VNR\\DEV\\llama_test`` 실험에서 확인한 값을 따른다: 최대 8 스레드 · context 8192(HauhauCS 권장 ·
옛 Ollama 파이프라인의 num_ctx 와 같다) ·
``--jinja`` + ``enable_thinking=false`` · loopback 무작위 포트 · 단일 슬롯. 샘플링은 Gemma 4 권장값(``SAMPLING``) 그대로.

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
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

MODEL_ALIAS = "naia-boost"
DEFAULT_TIMEOUT = 60.0
DEFAULT_IDLE_SECONDS = 180.0
# Gemma 4 권장 샘플링 — Google 모델 카드 · generation_config.json · HauhauCS 모델 카드(E2B · E4B · 26B 셋 다) · Unsloth 가
# 모두 같다(모든 용도 공통). 모델은 core/llama_models 의 목록에서 고른다 — 셋 다 이 값 그대로다.
# 이 값을 벗어나지 않는다(사용자 지정 2026-09-26): 모든 요청(Boost · Assist)에 여기서만 싣고, 부르는 쪽은 넘기지 못한다.
# min_p 는 권장에 없다(= 끔) — llama.cpp 기본 0.05 가 끼어들지 않게 0 을 적는다.
SAMPLING: dict[str, float] = {"temperature": 1.0, "top_p": 0.95, "top_k": 64, "min_p": 0.0}


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
        ctx_size: int = 8192,
        idle_seconds: float = DEFAULT_IDLE_SECONDS,
        log_path: str | Path | None = None,
        use_gpu: bool = True,
        device: str | None = None,
        managed_engine: bool = False,
        managed_model: Any = None,
    ) -> None:
        # 요구 설정(use_gpu/device) — 실제로 GPU 를 쓰는지는 effective_gpu(실패하면 CPU 로 내려온다).
        self.use_gpu = bool(use_gpu)
        self.device = device or None
        self.gpu_failed: str | None = None     # GPU 로 못 띄웠거나 GPU 에서 죽은 이유 — 장치 선택을 바꾸면 지운다
        self._running_key: tuple | None = None  # 지금 떠 있는 엔진이 어떤 설정으로 떴는가
        self.engine_path = Path(engine_path) if engine_path else None
        self.model_path = Path(model_path) if model_path else None
        self.managed_engine = managed_engine
        self.managed_model = managed_model
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
        self._unload_pending = False           # [VRAM 회수] 를 요청이 도는 중에 눌렀다 — 그 요청이 끝나면 내린다(unload)
        self._unload_timer: threading.Timer | None = None
        self._unload_gen = 0                   # 내림 타이머 세대 — 이미 불리기 시작한 낡은 타이머가 새 유예를 무시하지 않게
        # 요청 하나가 모델을 여러 번 부른다(Assist 4~8번 — 사이에 한국어 층 · 이벤트 맵) — 마지막 부름 뒤 이만큼 조용하면 내린다
        self.unload_grace_seconds = 3.0

    # ── 구성·상태 ──────────────────────────────────────────────────────────

    _KEEP = object()

    def configure(
        self, engine_path: str | Path | None, model_path: str | Path | None, *,
        use_gpu: bool | None = None, device: Any = _KEEP,
        managed_engine: bool | None = None, managed_model: Any = _KEEP,
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
            if managed_engine is not None:
                self.managed_engine = managed_engine
            if managed_model is not self._KEEP:
                self.managed_model = managed_model
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
        from core.llama_engine_install import engine_files_ready
        from core.llama_install_checks import artifact_ready, vcredist_status

        with self._proc_lock:
            running = self._proc is not None and self._proc.poll() is None
            engine_exists = bool(self.engine_path and self.engine_path.is_file())
            if self.managed_engine and engine_exists:
                engine_exists = engine_files_ready(self.engine_path.parent) and vcredist_status()["ok"]
            model_exists = bool(self.model_path and self.model_path.is_file())
            if self.managed_model is not None and model_exists:
                model_exists = artifact_ready(self.model_path, self.managed_model.size, self.managed_model.sha256)
            return {
                "engine_path": str(self.engine_path or ""),
                "model_path": str(self.model_path or ""),
                "engine_exists": engine_exists,
                "model_exists": model_exists,
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
                "unload_pending": self._unload_pending,
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
        # Hash once per unchanged managed model, outside the process lock so status polling stays responsive.
        with self._proc_lock:
            if (self._proc is not None and self._proc.poll() is None and self._port
                    and self._running_key == self._desired_key()):
                return self._port
            checked_model, spec = self.model_path, self.managed_model
        if spec is not None and checked_model is not None:
            from core.llama_install_checks import verify_artifact

            if not verify_artifact(checked_model, spec.size, spec.sha256):
                raise LlamaRuntimeError("모델 파일이 없거나 손상되었습니다 — AI 모델 설정에서 검사 및 복구를 눌러 주세요.")
        with self._proc_lock:
            if (self._proc is not None and self._proc.poll() is None and self._port
                    and self._running_key == self._desired_key()):
                return self._port
            self.stop()
            if not self.engine_path or not self.engine_path.is_file():
                raise LlamaRuntimeError(f"llama-server 엔진이 없습니다: {self.engine_path or '(경로 미지정)'}")
            if not self.model_path or not self.model_path.is_file():
                raise LlamaRuntimeError(f"모델 파일이 없습니다: {self.model_path or '(경로 미지정)'}")
            if (checked_model, spec) != (self.model_path, self.managed_model):
                raise LlamaRuntimeError("검사 중 모델 설정이 바뀌었습니다 — 다시 시도해 주세요.")
            if self.managed_engine:
                from core.llama_engine_install import engine_files_ready
                from core.llama_install_checks import vcredist_status

                prerequisite = vcredist_status()
                if not prerequisite["ok"]:
                    raise LlamaRuntimeError(prerequisite["message"])
                if not engine_files_ready(self.engine_path.parent):
                    raise LlamaRuntimeError("엔진 파일이 없거나 손상되었습니다 — AI 모델 설정에서 엔진 복구를 눌러 주세요.")
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

    def unload(self) -> bool:
        """[VRAM 회수](사용자 지정 2026-09-28) — 지금 내린다(내렸으면 True). 도는 요청(Assist · Boost · 첫 준비)은 끊지 않고
        그 요청이 끝난 뒤 내린다(chat · warm 의 finally): 곧바로 stop() 하면 도는 chat 이 연결 끊김을 'GPU 에서 멈춤' 으로 읽어
        gpu_failed 를 적고 CPU 로 다시 띄웠다(옛 [엔진 내리기] · 09-28 VRAM 시험에서 본 것). 기한 있는 임대(Assist · 준비)는
        놓는다 — 그 타이머가 남은 시간을 셀 까닭이 없다. 무기한(Auto Boost)은 그대로: 다음 Boost 가 다시 올린다."""
        with self._proc_lock:
            for owner in [o for o, expiry in self._leases.items() if expiry != math.inf]:
                self._leases.pop(owner, None)
            self._unload_pending = True
        if not self._slot.acquire(blocking=False):
            return False
        try:
            self._unload_pending = False
            was = self.is_running()
            self.stop()
            return was
        finally:
            self._slot.release()

    def _unload_later(self) -> None:
        """부름 하나가 끝났다 — 같은 요청의 다음 부름이 곧 오지 않으면 내린다. 첫 부름 끝에 곧바로 내렸더니 다음 부름이 다시
        올려 요청이 끝나고도 떠 있었다(09-28 라이브). 그 사이 새 부름이 돌면 unload 는 기다리고, 그 부름의 끝이 다시 잰다."""
        with self._proc_lock:
            if self._unload_timer is not None:
                self._unload_timer.cancel()
            self._unload_gen += 1
            timer = threading.Timer(self.unload_grace_seconds, self._unload_if_quiet, args=(self._unload_gen,))
            timer.daemon = True
            self._unload_timer = timer
            timer.start()

    def _new_call(self) -> None:
        """부름이 슬롯을 쥐었다 — 그 전에 잰 내림 타이머는 낡았다(끝나면 finally 의 _unload_later 가 다시 잰다)."""
        with self._proc_lock:
            self._unload_gen += 1

    def _unload_if_quiet(self, gen: int) -> None:
        """마지막 부름 뒤 조용했다 — 내린다. 세대 확인부터 내리기까지 **슬롯을 쥐고** 한다. cancel() 은 이미 불리기 시작한
        타이머를 못 멈추고(Codex 10차 F1), 락만 쥐고 세대를 본 뒤 놓으면 그 사이 새 부름이 돌고 끝나도 낡은 콜백이 내렸다
        (11차 R1). 부름은 슬롯을 쥐면 세대를 올린다(_new_call) — 슬롯을 쥔 채 본 세대가 같으면 이 타이머 뒤로 부름이 없었다."""
        if not self._unload_pending:
            return
        if not self._slot.acquire(blocking=False):
            # 누가 슬롯을 쥐고 있다. 부름(chat · warm)이면 세대가 이미 올랐다 — 그 finally 가 다시 잰다(여기서 또 재면 그 타이머가
            # 부름이 슬롯을 놓은 틈에 세대를 맞춰 유예 없이 내렸다, Codex 12차 F1). 부름이 아닌 것(내림 · 교체)이면 다시 잰다
            with self._proc_lock:
                current = gen == self._unload_gen
            if current:
                self._unload_later()
            return
        try:
            with self._proc_lock:
                if gen != self._unload_gen or not self._unload_pending:
                    return
                self._unload_timer = None
                for owner in [o for o, expiry in self._leases.items() if expiry != math.inf]:
                    self._leases.pop(owner, None)
                self._unload_pending = False
            self.stop()
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
            self._new_call()
            self._ensure(time.monotonic() + float(timeout))
            return True
        except Exception:
            return False
        finally:
            if self._unload_pending:
                self._unload_later()           # 올리는 동안 [VRAM 회수] 를 눌렀다 — 슬롯을 놓기 **전에** 잰다(chat 과 같다)
                self._slot.release()
            else:
                self._slot.release()
                if self._unload_pending:
                    self._unload_later()       # 놓는 사이 눌렸다(chat 과 같다)
                elif self.is_running():
                    self._arm_idle_timer()

    # ── 요청 ─────────────────────────────────────────────────────────────

    def chat(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        timeout: float = DEFAULT_TIMEOUT,
        system: str | None = None,
        grammar: str | None = None,
    ) -> dict[str, Any]:
        """user 메시지 하나(+선택 system)를 보내고 완결된 응답만 성공으로 돌려준다. 절대 raise 하지 않는다.

        샘플링은 늘 ``SAMPLING``(Gemma 4 권장값) — 온도를 받지 않는다(예전 0.2 · 0.0 덮어쓰기는 권장 밖이었다, 09-26).
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
            self._new_call()
            self._cancel_idle_timer()
            for attempt in range(2):
                was_running = self.is_running() and not self.is_stale()
                try:
                    port = self._ensure(deadline)
                    data = self._post(port, prompt, max_tokens, deadline, **extra)
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
            if self._unload_pending:
                # 도는 동안 [VRAM 회수] 를 눌렀다 — 요청이 끝나면 내린다(새 설정으로 띄우지도 않는다). 슬롯을 놓기 **전에** 잰다:
                # 놓은 틈에 앞서 잰 타이머가 세대를 맞춰 유예 없이 내렸다(Codex 12차 F1)
                self._unload_later()
                self._slot.release()
            else:
                self._slot.release()
                if self._unload_pending:
                    # 끝을 본 뒤 · 놓기 전에 [VRAM 회수] 가 눌렸다 — 그 unload() 는 슬롯을 못 쥐어 기다리는 중이다. 놓은 뒤 다시
                    # 보지 않으면 아무도 재지 않아 떠 있었다(Codex 13차 R1). 놓은 뒤 눌렸으면 unload() 가 스스로 내린다
                    self._unload_later()
                elif self.is_stale():
                    # 요청 도중 장치가 바뀌었다 — 이제 비었으니 새 설정의 엔진을 뒤에서 띄운다(다음 요청이 기다리지 않게).
                    threading.Thread(target=self.warm, daemon=True, name="llama-swap").start()
                elif self.is_running():
                    self._arm_idle_timer()

    def _post(self, port: int, prompt: str, max_tokens: int, deadline: float,
              system: str | None = None, grammar: str | None = None) -> dict[str, Any]:
        messages = [{"role": "system", "content": str(system)}] if system else []
        messages.append({"role": "user", "content": str(prompt)})
        body: dict[str, Any] = {
            "model": MODEL_ALIAS,
            "messages": messages,
            "stream": False,
            "max_tokens": int(max_tokens),
            **SAMPLING,                   # 요청이 나가는 마지막 자리 — 여기만 고치면 모든 호출이 따른다
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

# 드라이버에게 못 물었을 때만 쓰는 이름 규칙. 외장: NVIDIA 전부 · 'Graphics' 가 안 붙은 Radeon(RX · PRO · VII —
# APU 내장은 'Radeon(TM) Graphics' · 'Radeon 780M Graphics' 처럼 붙는다) · Intel Arc A · B5xx 이상 · Arc Pro.
# 내장: Intel Arc 140T/140V · 'Arc(TM) Graphics'(Meteor Lake) · Arc B3xx(Panther Lake) · UHD · Iris.
_DISCRETE_NAME = re.compile(r"nvidia|geforce|quadro|tesla|\brtx\b|radeon(?!.*graphics)|arc\(tm\) (?:pro |a\d|b[5-9]\d)")
_SOFTWARE_NAME = re.compile(r"llvmpipe|lavapipe|swiftshader|basic render")   # CPU 로 흉내 내는 가짜 GPU
_VK_DEVICE_TYPES = {1: "integrated", 2: "discrete", 4: "cpu"}   # VkPhysicalDeviceType
# 별도 프로세스에서 돌리는 조회 — vkGetPhysicalDeviceProperties 의 deviceType(오프셋 16) · deviceName(20, 256바이트).
_VK_PROBE = r'''
import ctypes, json, os, sys
class Info(ctypes.Structure):
    _fields_ = [("sType", ctypes.c_uint32), ("pNext", ctypes.c_void_p), ("flags", ctypes.c_uint32),
                ("pApplicationInfo", ctypes.c_void_p), ("enabledLayerCount", ctypes.c_uint32),
                ("ppEnabledLayerNames", ctypes.c_void_p), ("enabledExtensionCount", ctypes.c_uint32),
                ("ppEnabledExtensionNames", ctypes.c_void_p)]
if os.name == "nt":
    vk = ctypes.WinDLL(os.path.join(os.environ.get("SystemRoot") or "C:\\Windows", "System32", "vulkan-1.dll"))
else:
    vk = ctypes.CDLL("libvulkan.so.1")
inst = ctypes.c_void_p()
if vk.vkCreateInstance(ctypes.byref(Info(sType=1)), None, ctypes.byref(inst)) != 0:
    sys.exit(1)
count = ctypes.c_uint32(0)
vk.vkEnumeratePhysicalDevices(inst, ctypes.byref(count), None)
handles = (ctypes.c_void_p * count.value)()
vk.vkEnumeratePhysicalDevices(inst, ctypes.byref(count), handles)
out = []
for handle in handles[:count.value]:
    props = ctypes.create_string_buffer(4096)
    vk.vkGetPhysicalDeviceProperties(ctypes.c_void_p(handle), props)
    raw = props.raw
    out.append([raw[20:276].split(b"\0", 1)[0].decode("utf-8", "replace"), int.from_bytes(raw[16:20], "little")])
vk.vkDestroyInstance(inst, None)
print(json.dumps(out))
'''


def list_devices(engine_path: str | Path | None) -> list[str]:
    """엔진이 쓸 수 있는 GPU 이름들(예: 'Intel(R) Arc(TM) 140T GPU (32GB)'). 비면 GPU 없음(CPU 로 돈다)."""
    return [entry["name"] for entry in list_device_entries(engine_path)]


def _kind_from_name(name: str) -> str:
    """이름으로 가린 GPU 종류('discrete' | 'integrated' | 'cpu') — 드라이버에게 못 물었을 때만 쓴다."""
    low = str(name or "").lower()
    if _SOFTWARE_NAME.search(low):
        return "cpu"
    return "discrete" if _DISCRETE_NAME.search(low) else "integrated"


def _vulkan_device_types() -> dict[str, str]:
    """Vulkan 드라이버가 스스로 밝히는 GPU 종류 — {이름: 'integrated' | 'discrete' | 'cpu'}. llama.cpp 가 내장(UMA)을
    가르는 것과 같은 값이고, 이름은 ``--list-devices`` 와 글자까지 같다. 별도 프로세스에서 묻는다 — 드라이버를
    앱 프로세스에 올리지 않고, 드라이버가 죽어도 앱은 산다. 못 물으면 빈 dict(이름으로 가린다)."""
    if not sys.executable:
        return {}
    try:
        out = subprocess.run(
            [sys.executable, "-c", _VK_PROBE], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        types: dict[str, str] = {}
        for name, code in json.loads((out.stdout or "").strip().splitlines()[-1]):
            if code in _VK_DEVICE_TYPES:
                types.setdefault(str(name), _VK_DEVICE_TYPES[code])
        return types
    except Exception:
        return {}


def is_discrete(entry: dict[str, Any]) -> bool:
    """외장 GPU 인가 — list_device_entries 가 단 종류(드라이버 답), 없으면 이름으로."""
    return (entry.get("kind") or _kind_from_name(entry.get("name", ""))) == "discrete"


def choose_device(entries: list[dict[str, str]], preference: str | None) -> str | None:
    """설정의 장치 선호로 ``--device`` 값을 고른다. 'auto' · 'gpu' = 외장 GPU 우선, 없으면 첫 GPU.
    지정한 장치가 사라졌으면 자동으로 되돌아간다. GPU 가 없으면 None(엔진이 CPU 로 돈다)."""
    if not entries:
        return None
    wanted = str(preference or "auto")
    if wanted not in ("auto", "gpu") and any(entry["id"] == wanted for entry in entries):
        return wanted
    for entry in entries:
        if is_discrete(entry):
            return entry["id"]
    return entries[0]["id"]


def list_device_entries(engine_path: str | Path | None) -> list[dict[str, str]]:
    """``llama-server --list-devices`` 결과를 [{id:'Vulkan1', name:'NVIDIA GeForce RTX 5090 Laptop GPU',
    vram_mib, kind:'discrete'|'integrated'}] 로. 종류는 드라이버에게 묻고(못 물으면 이름으로), CPU 로 흉내 내는
    가짜 GPU 는 뺀다. 엔진 파일(경로·수정시각)마다 한 번만 잰다 — 둘을 함께 재서 약 1~3초."""
    path = Path(engine_path) if engine_path else None
    if path is None or not path.is_file():
        return []
    key = (str(path), path.stat().st_mtime)
    if key in _DEVICE_CACHE:
        return [dict(entry) for entry in _DEVICE_CACHE[key]]

    driver_types: dict[str, str] = {}
    asker = threading.Thread(target=lambda: driver_types.update(_vulkan_device_types()), daemon=True)
    asker.start()
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
                devices.append({"id": device_id, "name": clean, "vram_mib": int(mem.group(1)) if mem else 0})
    except Exception:
        devices = []
    if devices:
        asker.join(timeout=25)
    for entry in devices:
        entry["kind"] = driver_types.get(entry["name"]) or _kind_from_name(entry["name"])
    devices = [entry for entry in devices if entry["kind"] != "cpu"]
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


def default_model_path(save_root: str | Path, model_id: Any = None) -> Path:
    """고른 모델(core/llama_models)을 내려받는 위치 — 사용자 데이터 쪽(업데이트로 지워지지 않게)."""
    from core.llama_models import model_path

    return model_path(save_root, model_id)


def resolve_paths(settings: dict[str, Any], *, repo_root: str | Path, save_root: str | Path) -> tuple[Path, Path]:
    """설정 > 환경변수(NAIA_LLAMA_SERVER / NAIA_LLAMA_MODEL) > 기본 위치(모델은 설정의 ``model`` 로 고른 것)."""
    engine = (settings or {}).get("engine_path") or os.environ.get("NAIA_LLAMA_SERVER") or ""
    model = (settings or {}).get("model_path") or os.environ.get("NAIA_LLAMA_MODEL") or ""
    return (
        Path(engine) if engine else default_engine_path(repo_root),
        Path(model) if model else default_model_path(save_root, (settings or {}).get("model")),
    )
