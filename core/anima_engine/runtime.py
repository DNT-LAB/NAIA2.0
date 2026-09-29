"""Owned loopback ComfyUI process, health checks and installation smoke."""
from __future__ import annotations

import io
import os
import subprocess
import time
import traceback
from datetime import datetime
from functools import partial
from pathlib import Path
from threading import Event, RLock, Thread

import requests
from PIL import Image

from core.llama_runtime import _attach_kill_on_close_job, _close_job, _free_port
from . import manifest
from .profile import compile_graph
from .settings import load_settings, quick_receipt, walk_files, write_instance_model_config

REGISTRY = {}
REGISTRY_LOCK = RLock()
INSTALLING = set()
# 진단 정보에 싣는 Traceback 의 끝부분 길이(글자) - 어디서 났는지는 끝에 있다
TRACE_CHARS = 8000


class ManagedEngineError(RuntimeError):
    def __init__(self, code, message="ANIMA 엔진을 확인해 주세요.", detail=""):
        self.code, self.detail = code, detail
        self.message = message
        super().__init__(f"[{code}] {message}")


def clean_environment():
    env = dict(os.environ)
    # PYTHONDONTWRITEBYTECODE · PYTHONPYCACHEPREFIX 는 Electron 셸이 NAIA 백엔드에 준다(앱 폴더에 .pyc 를 안 쓰게).
    # ComfyUI 가 물려받으면 동봉된 __pycache__(.pyc 14,741개)를 못 찾고 켤 때마다 소스를 다시 번역한다(약 3초,
    # 09-29 관측) - 엔진의 파이썬은 제 캐시를 쓴다.
    for key in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE", "PYTHONEXECUTABLE",
                "PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX",
                "VIRTUAL_ENV", "CONDA_PREFIX", "CONDA_DEFAULT_ENV", "CONDA_SHLVL"):
        env.pop(key, None)
    env.update(PYTHONNOUSERSITE="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
               HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    return env


# 엔진이 뜨기를 기다리는 한도(초). 출력 없이 START_QUIET_TIMEOUT 이 지나면 멈추고, 로그가 이어지는 동안은 기다리되
# 전체로 START_HARD_TIMEOUT 을 넘지 않는다(09-29 관측: 180초 고정 한도에 끊긴 기동이 무엇을 하던 중인지 알 수 없었다).
START_QUIET_TIMEOUT = 180.0
START_HARD_TIMEOUT = 600.0
# 기동마다 engine.log 에 적는 머리줄 - log_tail 은 마지막 머리줄부터만 돌려준다(오류 상세에 지난 실행의 로그가 섞였다).
LOG_START_MARK = "===== NAIA: engine start "


def read_log_since(path, since=None, limit=65536):
    """engine.log 를 since(바이트)부터 - (글, 다음 since). 생성 화면의 '엔진 켜는 중' 콘솔이 이어 받는다.

    since 가 없으면 이번 기동의 머리줄부터(끝 limit 바이트 안에서). 파일이 since 보다 짧아졌으면(10MB 에서 돌려 새
    파일) 처음부터. 한 번에 limit 까지 - 너무 뒤처졌으면 끝 쪽만. 끝의 덜 적힌 줄은 다음에 준다(UTF-8 이 잘리지 않게).
    """
    path = Path(path)
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if since is None or not 0 <= since <= size or size - since > limit:
                start = max(0, size - limit) if since is None or size - (since or 0) > limit else 0
                handle.seek(start)
                data = handle.read(limit)
                mark = data.rfind(LOG_START_MARK.encode("utf-8")) if since is None else -1
                if mark >= 0:
                    data, start = data[mark:], start + mark
                elif start > 0:                     # 창이 줄 한가운데서 시작한다 - 다음 줄부터
                    cut = data.find(b"\n")
                    data, start = (data[cut + 1:], start + cut + 1) if cut >= 0 else (b"", size)
            else:
                start = since
                handle.seek(start)
                data = handle.read(limit)
    except OSError:
        return "", since or 0
    end = data.rfind(b"\n")
    if end < 0:
        return "", start
    return data[:end + 1].decode("utf-8", "replace"), start + end + 1


def start_timed_out(now, started, last_output, *, quiet=START_QUIET_TIMEOUT, hard=START_HARD_TIMEOUT):
    """기동을 그만 기다릴 때인가 - 마지막 출력(없으면 시작) 뒤 quiet 초가 조용했거나, 시작 뒤 hard 초가 지났다."""
    return now - max(started, last_output or started) >= quiet or now - started >= hard


class AnimaEngineRuntime:
    def __init__(self, engine_root: Path, *, runtime_id: str, reserve_vram_gb: float, idle_minutes: int,
                 model_config=None, command_builder=None, popen=subprocess.Popen, clock=time.monotonic):
        self.engine_root, self.runtime_id = Path(engine_root).resolve(), runtime_id
        self.reserve_vram_gb, self.idle_minutes = reserve_vram_gb, idle_minutes
        # 켜기 직전에 부른다: 켜는 NAIA(user-data)의 LoRA · 모델 폴더로 모델 경로 파일을 쓰고 그 경로를 돌려준다
        # (settings.write_instance_model_config). 엔진 하나를 NAIA 여럿이 같이 쓴다 - 파일은 NAIA 마다.
        self.model_config, self.model_config_path = model_config, None
        self.command_builder, self.popen, self.clock = command_builder or self._command, popen, clock
        self._op, self._lock = RLock(), RLock()
        self._stop = Event()
        self.proc = self.job = None
        self.port = None
        self._state, self._code, self._message, self.started_at = "stopped", None, "", None
        self._last_used, self._crash_retries = clock(), 0
        self.system_stats = {}
        self._monitor = None
        # 마지막 시작 오류 {at, code, message, detail, trace} - 실패 화면의 [자세히] · [에러 로그 복사](diagnostics)
        self.last_error = None

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def _command(self, port):
        if self.model_config_path is None:
            # 엔진 폴더의 옛 파일(state/extra_model_paths.yaml)은 같은 엔진을 쓰는 다른 NAIA 의 폴더일 수 있다
            raise ManagedEngineError("ENGINE_START_FAILED", detail="model paths not prepared")
        rt = self.engine_root / "runtime" / self.runtime_id / "ComfyUI_windows_portable"
        state = self.engine_root / "state"
        return ([str(rt / "python_embeded/python.exe"), "-s", str(rt / "ComfyUI/main.py"),
                 "--listen", "127.0.0.1", "--port", str(port), "--disable-auto-launch",
                 "--extra-model-paths-config", str(self.model_config_path),
                 "--output-directory", str(state / "comfy_output"), "--temp-directory", str(state / "comfy_temp"),
                 "--user-directory", str(state / "comfy_user"), "--reserve-vram", str(self.reserve_vram_gb),
                 # 추가 패키지 없는 내장 가속(torch 2.7+). 같은 그래프 실측 11.57 -> 11.05초/장(09-27, 사용자 결정).
                 # 00132 기준선의 comfylaunch.bat 도 이 플래그로 돌았다. sage attention 은 넣지 않는다.
                 "--fast", "fp16_accumulation"],
                rt, clean_environment())

    def _set(self, state, code=None, message=""):
        with self._lock:
            self._state, self._code, self._message = state, code, message

    def status(self):
        with self._lock:
            if self.proc is not None and self.proc.poll() is not None and self._state == "running":
                self._state, self._code = "crashed", "ENGINE_CRASHED"
            return {"state": self._state, "port": self.port,
                    "pid": self.proc.pid if self.proc and self.proc.poll() is None else None,
                    "started_at": self.started_at, "code": self._code, "message": self._message}

    def touch(self):
        self._last_used = self.clock()

    def log_tail(self):
        try:
            path = self.engine_root / "state/engine.log"
            with path.open("rb") as handle:
                handle.seek(max(0, path.stat().st_size - 16384))
                text = handle.read().decode("utf-8", "replace")
        except OSError:
            return ""
        # 이번 기동의 머리줄부터 - 머리줄이 16KB 밖이면 창 전체가 이번 기동의 출력이다
        mark = text.rfind(LOG_START_MARK)
        return "\n".join((text[mark:] if mark >= 0 else text).splitlines()[-40:])

    def _mark_log_start(self):
        path = self.engine_root / "state/engine.log"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("ab") as handle:
                handle.write(f"\n{LOG_START_MARK}{datetime.now().astimezone().isoformat()} =====\n".encode("utf-8"))
        except OSError:
            pass

    def _drain_log(self, proc, progress=None):
        path = self.engine_root / "state/engine.log"
        handle = None
        # ⚠️ read(4096) 은 4KB 가 찰 때까지 안 돌아온다(파이프의 버퍼 리더) - 기동 출력은 3~4KB 라 한도가 다 되도록
        #    파일에 한 줄도 안 적혔다(09-29 관측: 3,462바이트). read1 은 온 만큼 바로 준다.
        read = getattr(proc.stdout, "read1", None) or proc.stdout.read
        try:
            handle = path.open("ab")
            while True:
                block = read(4096)
                if not block:
                    break
                if progress is not None:
                    progress["last"] = self.clock()   # 기동 한도는 마지막 출력부터 잰다(start_timed_out)
                if handle.tell() + len(block) > 10 * 1024 * 1024:
                    handle.close()
                    os.replace(path, path.with_name("engine.log.1"))
                    handle = path.open("ab")
                handle.write(block)
                handle.flush()
        finally:
            if handle is not None:
                handle.close()
            proc.stdout.close()

    def _cleanup_outputs(self):
        root = (self.engine_root / "state/comfy_output").resolve()
        for path in walk_files(root):
            # Only owned output copies, never external model folders or links.
            try:
                if path.resolve().is_relative_to(root) and time.time() - path.stat().st_mtime > 7 * 86400:
                    path.unlink()
            except OSError:
                pass

    def ensure_running(self, timeout=START_QUIET_TIMEOUT, hard_timeout=START_HARD_TIMEOUT):
        with self._op:
            if self.status()["state"] == "running":
                self.touch()
                return self.url
            crashed = self._state == "crashed"
            if crashed:
                if self._crash_retries >= 1:
                    raise ManagedEngineError("ENGINE_CRASHED", detail=self.log_tail())
                self._crash_retries += 1
            _close_job(self.job)
            self.job = None
            self._stop.clear()
            self._set("starting")
            self.port = _free_port()
            for folder in ("comfy_output", "comfy_temp", "comfy_user"):
                (self.engine_root / "state" / folder).mkdir(parents=True, exist_ok=True)
            self._cleanup_outputs()
            self._mark_log_start()
            try:
                if self.model_config is not None:
                    try:
                        self.model_config_path = self.model_config()
                    except Exception as exc:
                        raise ManagedEngineError("ENGINE_START_FAILED", detail=f"model paths: {exc}") from exc
                argv, cwd, env = self.command_builder(self.port)
                self.proc = self.popen(argv, cwd=str(cwd), env=env, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self.job = _attach_kill_on_close_job(self.proc)
                if os.name == "nt" and not self.job:
                    print("ANIMA: kill-on-close job attachment unavailable", flush=True)
                progress = {"last": None}
                drain = Thread(target=self._drain_log, args=(self.proc, progress), daemon=True, name="anima-log")
                drain.start()
                started = self.clock()
                while not self._stop.is_set() and not start_timed_out(self.clock(), started, progress["last"],
                                                                        quiet=timeout, hard=hard_timeout):
                    if self.proc.poll() is not None:
                        drain.join(timeout=2)      # 끝난 프로세스의 마지막 출력까지 적은 뒤 읽는다
                        raise ManagedEngineError("ENGINE_START_FAILED", detail=self.log_tail())
                    try:
                        response = requests.get(self.url + "/system_stats", timeout=2)
                        response.raise_for_status()
                        stats = response.json()
                    except (requests.RequestException, ValueError):
                        self._stop.wait(0.5)
                        continue
                    if not any(x.get("type") == "cuda" for x in stats.get("devices", [])):
                        raise ManagedEngineError("GPU_NOT_USED", "엔진이 GPU를 쓰지 못하고 있습니다.")
                    self.system_stats = stats
                    self.started_at = datetime.now().astimezone().isoformat()
                    self._set("running")
                    self._crash_retries = 0
                    self.touch()
                    if self._monitor is None or not self._monitor.is_alive():
                        self._monitor = Thread(target=self._watch_idle, daemon=True, name="anima-idle")
                        self._monitor.start()
                    return self.url
                raise ManagedEngineError("CANCELED" if self._stop.is_set() else "ENGINE_START_TIMEOUT")
            except Exception as exc:
                code = "ENGINE_CRASHED" if crashed else getattr(exc, "code", "ENGINE_START_FAILED")
                detail = getattr(exc, "detail", "") or self.log_tail() or str(exc)
                self.last_error = {"at": datetime.now().astimezone().isoformat(timespec="seconds"), "code": code,
                                   "message": "엔진을 시작하지 못했습니다.", "detail": detail,
                                   "trace": traceback.format_exc()[-TRACE_CHARS:]}
                self._terminate()
                self._set("crashed", code, "엔진을 시작하지 못했습니다.")
                raise ManagedEngineError(code, "엔진을 시작하지 못했습니다.", detail) from exc

    def _watch_idle(self):
        while not self._stop.wait(1):
            if self.status()["state"] != "running":
                return
            if self.idle_minutes and self.clock() - self._last_used >= self.idle_minutes * 60:
                if self.queue_busy():
                    self.touch()
                    continue
                self.stop()
                return

    def queue_busy(self):
        """An idle timer must never terminate an in-flight generation."""
        if self.status()["state"] != "running":
            return False
        try:
            response = requests.get(self.url + "/queue", timeout=3)
            response.raise_for_status()
            queue = response.json()
            if not isinstance(queue.get("queue_running"), list) or not isinstance(queue.get("queue_pending"), list):
                return True
            return bool(queue["queue_running"] or queue["queue_pending"])
        except (requests.RequestException, ValueError, TypeError, AttributeError):
            return True

    def _terminate(self):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=10)
        _close_job(self.job)
        self.job, self.proc = None, None

    def stop(self):
        self._stop.set()
        with self._op:
            self._set("stopping")
            self._terminate()
            self._set("stopped")
            self.port = None
            self._crash_retries = 0

    def preflight(self):
        preflight(self.url)

    def smoke(self):
        return smoke(self.url)


def preflight(url, *, get=requests.get):
    from core.headless_api_option_service import extract_combo_options
    classes = {x["class_type"] for x in manifest.GRAPH_TEMPLATE.values()} | {"LoraLoaderModelOnly"}
    nodes = {}
    for name in sorted(classes):
        try:
            response = get(url + "/object_info/" + name, timeout=10)
            response.raise_for_status()
            nodes[name] = response.json()[name]["input"]["required"]
        except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
            raise ManagedEngineError("PREFLIGHT_MISSING_NODE", detail=name) from exc
    for cls, field, expected in (("UNETLoader", "unet_name", manifest.MODELS[0]["filename"]),
                                  ("CLIPLoader", "clip_name", manifest.MODELS[1]["filename"]),
                                  ("VAELoader", "vae_name", manifest.MODELS[2]["filename"])):
        if expected not in extract_combo_options(nodes[cls].get(field)):
            raise ManagedEngineError("PREFLIGHT_MISSING_MODEL", detail=expected)
    for cls, field, expected in (("CLIPLoader", "type", "stable_diffusion"), ("UNETLoader", "weight_dtype", "default"),
                                  ("SpectrumSPDKSampler", "sampler_name", "euler"),
                                  ("SpectrumSPDKSampler", "scheduler", "simple"), ("SpectrumSPDKSampler", "split_mode", "single")):
        if expected not in extract_combo_options(nodes[cls].get(field)):
            raise ManagedEngineError("PREFLIGHT_SCHEMA_MISMATCH", detail=cls + "." + field)
    if not set(manifest.GRAPH_TEMPLATE["48"]["inputs"]) <= set(nodes["SpectrumSPDKSampler"]):
        raise ManagedEngineError("PREFLIGHT_SCHEMA_MISMATCH", detail="SpectrumSPDKSampler inputs")


def smoke(url, *, service_factory=None, clock=time.monotonic):
    from core.comfyui_service import ComfyUIService
    service = (service_factory or ComfyUIService)(url)
    compiled = compile_graph({"input": "scenery, blue sky, cloud", "seed": 1, "steps": 10,
                              "width": 512, "height": 512}, [], available_loras=[])
    started = clock()
    prompt_id = service.queue_workflow(compiled.workflow)
    if not prompt_id:
        raise ManagedEngineError("SMOKE_FAILED", detail="prompt submission failed; not resubmitted")
    if not service.wait_for_completion(prompt_id, timeout=600):
        detail = ""
        if clock() - started < 600:
            try:
                detail = str(requests.get(url + "/history/" + prompt_id, timeout=5).json().get(prompt_id, {}).get("status", {}))
            except requests.RequestException:
                pass
        raise ManagedEngineError("SMOKE_TIMEOUT" if clock() - started >= 600 else "SMOKE_FAILED", detail=detail)
    results = service.get_generation_result(prompt_id, workflow=compiled.workflow, preferred_output_node_id="53")
    if not results:
        raise ManagedEngineError("SMOKE_BAD_OUTPUT")
    item = results[0]
    downloaded = service.download_image(item["filename"], item.get("subfolder", ""), item.get("type", "output"))
    try:
        if not downloaded:
            raise ValueError("image download failed")
        _image, data = downloaded  # Public ComfyUIService returns (PIL.Image, raw_bytes).
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            if image.format != "PNG" or image.size != (512, 512):
                raise ValueError("expected 512x512 PNG")
    except Exception as exc:
        raise ManagedEngineError("SMOKE_BAD_OUTPUT", detail=str(exc)) from exc
    return {"elapsed_ms": int((clock() - started) * 1000), "width": 512, "height": 512}


def register_runtime(runtime):
    with REGISTRY_LOCK:
        REGISTRY[str(runtime.engine_root.resolve())] = runtime


# ANIMA 가 설 자리(GB) - 모델 셋(manifest) + 1MP 추론 여유. reserve_vram 이 이 자리까지 먹지 않게 한다.
ANIMA_MIN_VRAM_GB = sum(model["size"] for model in manifest.MODELS) / 1e9 + 1.5


def _gpu_total_gb(settings):
    """설치 때 잰 GPU 메모리(GiB) - 영수증의 gpu.vram_mb. 모르면 None."""
    try:
        vram_mb = float(((quick_receipt(settings) or {}).get("gpu") or {}).get("vram_mb") or 0)
    except (TypeError, ValueError, AttributeError):
        return None
    return vram_mb / 1024 if vram_mb > 0 else None


def reserve_vram(context, settings):
    """ComfyUI 가 **지금 쓰는 몫 밖으로** 더 비워 둘 VRAM(GB) - --reserve-vram. 엔진을 켤 때 한 번 정해진다.

    ComfyUI 는 드라이버가 잰 빈 메모리에서 이만큼을 더 남기고 모델을 올린다(09-29 관측: 26B 를 받아 두기만 해도
    16.81GB - 16GB GPU 전체보다 크다).
    - Assist · Auto Boost 의 llama-server 가 **이미 떠 있으면** 기본값만: 그 몫은 드라이버가 이미 '사용 중' 으로
      잰다(또 비우면 이중 계산).
    - 안 떠 있는데 GPU 모드로 받아 둔 모델이 있으면 나중에 올라올 자리를 남긴다. 단 GPU 메모리(설치 때 잰 값)에서
      ANIMA 가 설 자리(ANIMA_MIN_VRAM_GB)를 뺀 만큼까지만 - 넘으면 ANIMA 가 느린 분할 적재로 밀린다.
      GPU 메모리를 모르면(첫 설치 - 영수증은 연기 시험 뒤에 생긴다) 상한을 걸 수 없으니 남기지 않는다(Codex 09-29).
    """
    if settings.reserve_vram_gb != "auto":
        return float(settings.reserve_vram_gb)
    base = 1.0
    try:
        llama = getattr(context, "boost_llama_runtime", None)
        if llama is not None and getattr(llama, "is_running", lambda: False)():
            return base
        from core.boost_v2 import load_boost_v2_settings
        from core.llama_models import model_by_id, model_path
        from .integration import save_root_of
        save = save_root_of(context)
        config = load_boost_v2_settings(save_root=save)
        model = model_by_id(config["model"])
        path = Path(config["model_path"]) if config.get("model_path") else model_path(save, model.id)
        if config.get("device") != "cpu" and path.is_file():
            total = _gpu_total_gb(settings)
            if not total:
                return base
            want = min(base + model.size / 1e9 * 1.1 + 0.5, total - ANIMA_MIN_VRAM_GB)
            return round(max(base, want), 2)
    except (OSError, KeyError, ValueError, AttributeError):
        pass
    return base


def get_runtime(context):
    from .integration import save_root_of
    save_root = save_root_of(context)
    settings = load_settings(save_root)
    if not quick_receipt(settings):
        return None
    key = str(Path(settings.engine_root).resolve())
    with REGISTRY_LOCK:
        if key in INSTALLING:
            return None
        runtime = REGISTRY.get(key)
        if runtime is None:
            runtime = AnimaEngineRuntime(Path(key), runtime_id=manifest.RUNTIME_ID,
                                         reserve_vram_gb=reserve_vram(context, settings), idle_minutes=settings.idle_minutes)
            REGISTRY[key] = runtime
        runtime.idle_minutes = settings.idle_minutes
        runtime.reserve_vram_gb = reserve_vram(context, settings)
        # 켤 때 이 NAIA 의 폴더로(설치 작업이 등록한 런타임도 여기서 영수증 기준으로 바뀐다)
        runtime.model_config = partial(write_instance_model_config, save_root)
        return runtime


def stop_all():
    with REGISTRY_LOCK:
        runtimes = list(REGISTRY.values())
    for runtime in runtimes:
        runtime.stop()
