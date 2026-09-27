"""Owned loopback ComfyUI process, health checks and installation smoke."""
from __future__ import annotations

import io
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from threading import Event, RLock, Thread

import requests
from PIL import Image

from core.llama_runtime import _attach_kill_on_close_job, _close_job, _free_port
from . import manifest
from .profile import compile_graph
from .settings import load_settings, quick_receipt, walk_files

REGISTRY = {}
REGISTRY_LOCK = RLock()
INSTALLING = set()


class ManagedEngineError(RuntimeError):
    def __init__(self, code, message="ANIMA 엔진을 확인해 주세요.", detail=""):
        self.code, self.detail = code, detail
        self.message = message
        super().__init__(f"[{code}] {message}")


def clean_environment():
    env = dict(os.environ)
    for key in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE", "PYTHONEXECUTABLE",
                "VIRTUAL_ENV", "CONDA_PREFIX", "CONDA_DEFAULT_ENV", "CONDA_SHLVL"):
        env.pop(key, None)
    env.update(PYTHONNOUSERSITE="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
               HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    return env


class AnimaEngineRuntime:
    def __init__(self, engine_root: Path, *, runtime_id: str, reserve_vram_gb: float, idle_minutes: int,
                 command_builder=None, popen=subprocess.Popen, clock=time.monotonic):
        self.engine_root, self.runtime_id = Path(engine_root).resolve(), runtime_id
        self.reserve_vram_gb, self.idle_minutes = reserve_vram_gb, idle_minutes
        self.command_builder, self.popen, self.clock = command_builder or self._command, popen, clock
        self._op, self._lock = RLock(), RLock()
        self._stop = Event()
        self.proc = self.job = None
        self.port = None
        self._state, self._code, self._message, self.started_at = "stopped", None, "", None
        self._last_used, self._crash_retries = clock(), 0
        self.system_stats = {}
        self._monitor = None

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def _command(self, port):
        rt = self.engine_root / "runtime" / self.runtime_id / "ComfyUI_windows_portable"
        state = self.engine_root / "state"
        return ([str(rt / "python_embeded/python.exe"), "-s", str(rt / "ComfyUI/main.py"),
                 "--listen", "127.0.0.1", "--port", str(port), "--disable-auto-launch",
                 "--extra-model-paths-config", str(state / "extra_model_paths.yaml"),
                 "--output-directory", str(state / "comfy_output"), "--temp-directory", str(state / "comfy_temp"),
                 "--user-directory", str(state / "comfy_user"), "--reserve-vram", str(self.reserve_vram_gb)],
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
                return "\n".join(handle.read().decode("utf-8", "replace").splitlines()[-40:])
        except OSError:
            return ""

    def _drain_log(self, proc):
        path = self.engine_root / "state/engine.log"
        handle = None
        try:
            handle = path.open("ab")
            while True:
                block = proc.stdout.read(4096)
                if not block:
                    break
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

    def ensure_running(self, timeout=180.0):
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
            argv, cwd, env = self.command_builder(self.port)
            try:
                self.proc = self.popen(argv, cwd=str(cwd), env=env, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self.job = _attach_kill_on_close_job(self.proc)
                if os.name == "nt" and not self.job:
                    print("ANIMA: kill-on-close job attachment unavailable", flush=True)
                Thread(target=self._drain_log, args=(self.proc,), daemon=True, name="anima-log").start()
                deadline = self.clock() + timeout
                while self.clock() < deadline and not self._stop.is_set():
                    if self.proc.poll() is not None:
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


def reserve_vram(context, settings):
    if settings.reserve_vram_gb != "auto":
        return float(settings.reserve_vram_gb)
    try:
        from core.boost_v2 import load_boost_v2_settings
        from core.llama_models import model_by_id, model_path
        from .integration import save_root_of
        save = save_root_of(context)
        config = load_boost_v2_settings(save_root=save)
        model = model_by_id(config["model"])
        path = Path(config["model_path"]) if config.get("model_path") else model_path(save, model.id)
        if config.get("device") != "cpu" and path.is_file():
            return 1.0 + model.size / 1e9 * 1.1 + 0.5
    except (OSError, KeyError, ValueError, AttributeError):
        pass
    return 1.0


def get_runtime(context):
    from .integration import save_root_of
    settings = load_settings(save_root_of(context))
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
        return runtime


def stop_all():
    with REGISTRY_LOCK:
        runtimes = list(REGISTRY.values())
    for runtime in runtimes:
        runtime.stop()
