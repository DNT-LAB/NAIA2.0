"""Single managed installation job; pinned downloads and restart-safe journal."""
from __future__ import annotations

import csv
import ctypes
import math
import os
import platform
import re
import shutil
import subprocess
import time
import traceback
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from functools import partial
from pathlib import Path
from threading import Event, RLock, Thread

from core.llama_model_download import LlamaModelDownloadService, sha256_of
from . import manifest
from .runtime import (AnimaEngineRuntime, INSTALLING, REGISTRY, REGISTRY_LOCK, TRACE_CHARS, ManagedEngineError,
                      register_runtime)
from .settings import LOCK as SETTINGS_LOCK
from .settings import (AnimaSettings, atomic_json, load_settings, quick_receipt, read_json, save_settings,
                       verified_hash, walk_files, write_instance_model_config)


@dataclass
class GpuInfo:
    name: str
    driver: str
    compute_cap: float | None
    vram_mb: int
    cuda_version: str = ""
    uuid: str = ""
    source: str = "nvidia-smi"


def _load_nvml():
    # Use the driver's DLL in System32, never one from the app/current directory.
    if os.name != "nt":
        raise OSError("NVML fallback is Windows-only")
    return ctypes.CDLL(str(system_directory() / "nvml.dll"))


def _nvml_gpus(load=None):
    """Read driver-owned metadata without importing torch or creating a CUDA context."""
    class Memory(ctypes.Structure):
        _fields_ = [(key, ctypes.c_ulonglong) for key in ("total", "free", "used")]

    try:
        lib = (load or _load_nvml)()
        signatures = {
            "nvmlInit_v2": [], "nvmlShutdown": [],
            "nvmlDeviceGetCount_v2": [ctypes.POINTER(ctypes.c_uint)],
            "nvmlDeviceGetHandleByIndex_v2": [ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)],
            "nvmlSystemGetDriverVersion": [ctypes.c_char_p, ctypes.c_uint],
            "nvmlSystemGetCudaDriverVersion_v2": [ctypes.POINTER(ctypes.c_int)],
            "nvmlDeviceGetName": [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint],
            "nvmlDeviceGetUUID": [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint],
            "nvmlDeviceGetCudaComputeCapability": [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int),
                                                    ctypes.POINTER(ctypes.c_int)],
            "nvmlDeviceGetMemoryInfo": [ctypes.c_void_p, ctypes.POINTER(Memory)],
        }
        for name, args in signatures.items():
            func = getattr(lib, name)
            func.argtypes, func.restype = args, ctypes.c_int
        if lib.nvmlInit_v2() != 0:
            return []
    except (OSError, AttributeError):
        return []
    try:
        def string_value(func, *args):
            value = ctypes.create_string_buffer(256)
            return value.value.decode("utf-8", "replace") if func(*args, value, len(value)) == 0 else ""

        driver = string_value(lib.nvmlSystemGetDriverVersion)
        version, count = ctypes.c_int(), ctypes.c_uint()
        cuda = (f"{version.value // 1000}.{version.value % 1000 // 10}"
                if lib.nvmlSystemGetCudaDriverVersion_v2(ctypes.byref(version)) == 0 and version.value > 0 else "")
        if lib.nvmlDeviceGetCount_v2(ctypes.byref(count)) != 0:
            return []
        gpus = []
        for index in range(count.value):
            handle = ctypes.c_void_p()
            if lib.nvmlDeviceGetHandleByIndex_v2(index, ctypes.byref(handle)) != 0:
                continue
            name = string_value(lib.nvmlDeviceGetName, handle)
            gpu_uuid = string_value(lib.nvmlDeviceGetUUID, handle)
            major, minor, memory = ctypes.c_int(), ctypes.c_int(), Memory()
            cc = (float(f"{major.value}.{minor.value}") if lib.nvmlDeviceGetCudaComputeCapability(
                  handle, ctypes.byref(major), ctypes.byref(minor)) == 0 else None)
            vram = memory.total // (1024 ** 2) if lib.nvmlDeviceGetMemoryInfo(handle, ctypes.byref(memory)) == 0 else 0
            gpus.append(GpuInfo(name or "NVIDIA", driver, cc, vram, cuda, gpu_uuid, "NVML"))
        return gpus
    except OSError:
        return []
    finally:
        lib.nvmlShutdown()


def _number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (ValueError, TypeError):
        return None


def _cuda_version(value):
    value = str(value or "").strip()
    return tuple(map(int, value.split("."))) if re.fullmatch(r"\d+\.\d+(?:\.\d+)*", value) else None


def gpu_probe(run=None, *, preferred_uuid=""):
    """NVIDIA GPU(nvidia-smi) - 없으면 None. run = subprocess.run 대신(진단 정보가 원문을 적으려고 넘긴다).

    설치 검사는 가장 좋은 카드. 기동은 영수증의 UUID가 아직 있으면 그 카드, 없으면 가장 좋은 카드를 고른다.
    """
    run = run or subprocess.run
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    def output(args):
        try:
            result = run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                         timeout=10, creationflags=flags)
            return (result.stdout or "") if result.returncode == 0 else ""
        except (OSError, subprocess.TimeoutExpired):
            return ""

    query = output(["nvidia-smi", "--query-gpu=index,uuid,name,driver_version,compute_cap,memory.total",
                    "--format=csv,noheader,nounits"])
    header = output(["nvidia-smi"])
    cuda = re.search(r"CUDA Version\s*:\s*(\d+\.\d+)", header, re.IGNORECASE)
    gpus = []
    for row in csv.reader(query.splitlines(), skipinitialspace=True):
        if len(row) != 6:
            continue
        _index, gpu_uuid, name, driver, cc, mem = [s.strip() for s in row]
        # Missing optional VRAM must not discard a supported card and its UUID.
        gpus.append(GpuInfo(name, driver, _number(cc), int(_number(mem) or 0), cuda[1] if cuda else "", gpu_uuid))
    if not gpus or any(g.compute_cap is None or not _cuda_version(g.cuda_version) or not g.uuid for g in gpus):
        for fallback in _nvml_gpus():
            original = next((g for g in gpus if g.uuid and g.uuid == fallback.uuid), None)
            if original is None:
                gpus.append(fallback)
            else:
                original.compute_cap = original.compute_cap or fallback.compute_cap
                original.cuda_version = original.cuda_version or fallback.cuda_version
                original.vram_mb = original.vram_mb or fallback.vram_mb
                original.driver = original.driver or fallback.driver
                original.source = "nvidia-smi + NVML"
    if preferred_uuid:
        for gpu in gpus:
            if gpu.uuid == preferred_uuid:
                return gpu
    return max(gpus, key=lambda g: (g.compute_cap or 0, bool(_cuda_version(g.cuda_version)), g.vram_mb),
               default=GpuInfo("NVIDIA", "", None, 0, cuda[1] if cuda else "") if query or cuda else None)


def validate_gpu(gpu):
    if gpu is None:
        raise ManagedEngineError("NO_NVIDIA_GPU", "NVIDIA 그래픽 카드와 드라이버를 찾지 못했습니다.")
    data = asdict(gpu) if isinstance(gpu, GpuInfo) else dict(gpu)
    cc = _number(data.get("compute_cap"))
    cuda = _cuda_version(data.get("cuda_version"))
    if cc is None:
        raise ManagedEngineError("GPU_PROBE_FAILED", "GPU 연산 능력을 확인하지 못했습니다. 자세히에서 GPU 조회 결과를 확인해 주세요.")
    if cc < manifest.ARTIFACTS[0]["min_compute_cap"]:
        raise ManagedEngineError("GPU_UNSUPPORTED", "이 판은 RTX 20 시리즈 이상에서 동작합니다.")
    if cuda is None:
        raise ManagedEngineError("GPU_PROBE_FAILED", "드라이버의 CUDA 지원 버전을 확인하지 못했습니다. 자세히에서 GPU 조회 결과를 확인해 주세요.")
    required = manifest.ARTIFACTS[0]["min_driver_cuda"]
    if cuda < _cuda_version(required):
        raise ManagedEngineError("DRIVER_TOO_OLD", f"CUDA {required} 지원 그래픽 드라이버가 필요합니다.")
    return data


def _windows_nvidia_gpu():
    # Imported only on a failed probe; diagnostics also imports the strict validator.
    from .diagnostics import windows_adapters
    adapter = next((a for a in windows_adapters() if a["vendor"] == "NVIDIA"), None)
    if adapter is None:
        return None
    return GpuInfo(adapter["name"], adapter["driver"], None, 0, source="Windows")


def system_directory():
    """The native system directory (System32 in the supported 64-bit Python)."""
    buffer = ctypes.create_unicode_buffer(32768)
    size = ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer))
    if not 0 < size < len(buffer):
        raise OSError("GetSystemDirectoryW failed")
    return Path(buffer.value)


def validate_root(path, *, forbidden=(), write_check=True):
    path = Path(path)
    resolved = path.resolve()
    banned = [Path(p).resolve() for p in forbidden if p]
    if os.environ.get("APPDATA"):
        banned.append(Path(os.environ["APPDATA"]).resolve())
    if (not path.is_absolute() or str(path).startswith("\\\\") or len(str(resolved)) > 80
            or any(resolved == base or resolved.is_relative_to(base) for base in banned)):
        raise ManagedEngineError("PATH_INVALID", "앱 폴더 밖의 짧은 로컬 경로를 선택해 주세요.")
    if os.name == "nt" and ctypes.windll.kernel32.GetDriveTypeW(str(resolved.anchor)) != 3:
        raise ManagedEngineError("PATH_INVALID", "로컬 고정 드라이브를 선택해 주세요.")
    for part in (path, *path.parents):
        if part.is_symlink() or getattr(part, "is_junction", lambda: False)():
            raise ManagedEngineError("PATH_INVALID", "연결 폴더에는 설치할 수 없습니다.")
    if resolved.exists() and (not resolved.is_dir() or (any(resolved.iterdir()) and not
            ((resolved / "state").is_dir() or (resolved / "receipt.json").is_file()))):
        raise ManagedEngineError("PATH_INVALID", "다른 파일이 있는 폴더에는 설치할 수 없습니다.")
    if write_check:
        try:
            resolved.mkdir(parents=True, exist_ok=True)
            probe = resolved / (".write-test-" + uuid.uuid4().hex)
            with probe.open("xb"):
                pass
            probe.unlink()
        except OSError as exc:
            raise ManagedEngineError("PATH_NOT_WRITABLE", "이 폴더에 쓸 수 없습니다.", str(exc)) from exc
    return resolved


def runtime_needs_extract(engine_root, force_verify=False):
    """Whether the pinned runtime needs extraction, independent of job state."""
    active = Path(engine_root) / "runtime" / manifest.RUNTIME_ID
    if force_verify or not active.exists():
        return True
    portable = active / "ComfyUI_windows_portable"
    return (not (portable / "python_embeded/python.exe").is_file()
            or not (portable / "ComfyUI/main.py").is_file())


def disk_free(path):
    path = Path(path)
    while not path.exists() and path != path.parent:
        path = path.parent
    return shutil.disk_usage(path).free


def suggested_root(required, disk=disk_free):
    local = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "NAIA/engines/anima"
    if disk(local) >= required:
        return local
    if os.name == "nt":
        drives = [Path(f"{letter}:/") for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ"
                  if ctypes.windll.kernel32.GetDriveTypeW(f"{letter}:\\") == 3]
        if drives:
            return max(drives, key=disk) / "NAIA_engines/anima"
    return local


def standard_roots():
    """설치가 제안하는 자리 전부(suggested_root 의 후보와 같다) - 로컬 앱 데이터 먼저, 그다음 고정 드라이브."""
    roots = [Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "NAIA/engines/anima"]
    if os.name == "nt":
        roots += [Path(f"{letter}:/") / "NAIA_engines/anima" for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ"
                  if ctypes.windll.kernel32.GetDriveTypeW(f"{letter}:\\") == 3]
    return roots


def adopt_installed_engine(save_root, *, forbidden_roots=(), roots=None):
    """이 user-data 에 설치 위치가 아직 없는데 표준 자리에 **끝난 설치**(유효한 영수증)가 있으면 그 자리를 적는다.

    같은 PC 의 다른 NAIA(새 user-data 의 포터블 · 격리 시험)가 이미 설치해 둔 엔진이다. 그대로 두면 설치 화면이
    '설치 (0KB)' 를 보이고, 누르면 받을 것도 없이 엔진을 켜서 연기 시험까지 다시 돈다(사용자 제보 2026-09-29).
    - 판정은 quick_receipt 그대로(파일 존재 · 크기 - 해시 없음, status 가 부른다). 설치 중인 자리는 건너뛴다.
    - 동의 기록은 만들지 않는다: 준비됨 판정에 동의는 들지 않고, 동의는 설치를 새로 시작할 때 묻는다.
    - 엔진 폴더에는 아무것도 쓰지 않는다: LoRA · 모델 폴더는 user-data 마다 제 파일에 적어 엔진을 켤 때 넘긴다
      (settings.write_instance_model_config).
    돌려주는 것: 적은 자리(Path) 또는 None.
    """
    if load_settings(save_root).engine_root:
        return None
    for root in (standard_roots() if roots is None else roots):
        root = Path(root)
        try:
            if not (root / "receipt.json").is_file() or not quick_receipt(AnimaSettings({"engine_root": str(root)})):
                continue
            resolved = validate_root(root, forbidden=forbidden_roots, write_check=False)
        except (OSError, ManagedEngineError):
            continue
        with REGISTRY_LOCK:
            if str(resolved) in INSTALLING:
                continue
        with SETTINGS_LOCK:
            if load_settings(save_root).engine_root:    # 그사이 설치 화면에서 사람이 정했다 - 그쪽이 이긴다
                return None
            save_settings(save_root, {"engine_root": str(resolved)})
        return resolved
    return None


def run_7z(exe, archive, dest, cancel):
    proc = subprocess.Popen([str(exe), "x", "-y", "-o" + str(dest), str(archive)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    from core.llama_runtime import _attach_kill_on_close_job, _close_job
    job = _attach_kill_on_close_job(proc)
    try:
        while proc.poll() is None:
            if cancel.wait(0.2):
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=10)
                raise InterruptedError()
        if proc.returncode:
            raise ManagedEngineError("EXTRACT_FAILED", detail=str(proc.returncode))
    finally:
        _close_job(job)


class AnimaInstallJob:
    def __init__(self, *, save_root: Path, settings: AnimaSettings, opener=None, run_7z=None, gpu_probe=None,
                 disk_free=None, runtime_factory=None, on_ready=None, clock=time.time, forbidden_roots=(),
                 system_directory=None):
        self.save_root, self.settings = Path(save_root), settings
        self.opener, self.run_7z = opener, run_7z or globals()["run_7z"]
        self.gpu_probe, self.disk_free = gpu_probe or globals()["gpu_probe"], disk_free or globals()["disk_free"]
        self.system_directory = system_directory or globals()["system_directory"]
        self.runtime_factory = runtime_factory or (lambda root, runtime_id: AnimaEngineRuntime(
            root, runtime_id=runtime_id, reserve_vram_gb=1.0 if settings.reserve_vram_gb == "auto" else settings.reserve_vram_gb,
            idle_minutes=settings.idle_minutes))
        self.on_ready, self.clock = on_ready or register_runtime, clock
        self.forbidden_roots = forbidden_roots
        self._lock, self._cancel = RLock(), Event()
        self._thread = self._download = self._runtime = None
        self._state = {"state": "not_installed", "phase": None, "job_id": None,
                       "bytes_done": 0, "bytes_total": 0, "current_item": None, "code": None,
                       "message": "", "retryable": False, "warnings": [], "started_at": None, "updated_at": None}
        self._completed = []
        self._force = False
        self._select = False
        self._trace = ""       # 실패한 곳(Traceback) - 기록(job.json)과 진단 정보에 싣는다

    def snapshot(self):
        with self._lock:
            result = dict(self._state)
            download = self._download
        if download is not None:
            try:
                path = download.part_path if download.part_path.is_file() else download.target_path
                result["bytes_done"] = result["bytes_done"] + (path.stat().st_size if path.is_file() else 0)
            except OSError:
                pass
        if result["state"] == "not_installed" and self.settings.engine_root:
            journal = read_json(Path(self.settings.engine_root) / "state/job.json")
            error = journal.get("error", {})
            if quick_receipt(self.settings):
                result["state"] = "ready"
            elif journal.get("state") in ("failed", "canceled", "blocked"):
                result.update({key: journal.get(key) for key in ("state", "phase", "job_id", "started_at", "updated_at")})
                result.update({key: error.get(key) for key in ("code", "message", "retryable")})
        return result

    def _publish(self, **updates):
        with self._lock:
            self._state.update(updates, updated_at=datetime.now().astimezone().isoformat())
            state = dict(self._state)
        if self.settings.engine_root and state["job_id"]:
            atomic_json(Path(self.settings.engine_root) / "state/job.json", {
                "version": 1, "profile_revision": manifest.PROFILE_REVISION, "runtime_id": manifest.RUNTIME_ID,
                **{key: state[key] for key in ("job_id", "state", "phase", "started_at", "updated_at")},
                "select_on_ready": self._select, "completed_phases": list(self._completed),
                "error": {**{key: state.get(key) for key in ("code", "message", "retryable", "detail")},
                          "trace": self._trace}})

    def _check_cancel(self):
        if self._cancel.is_set():
            raise InterruptedError()

    def inspect(self, engine_root=None, model_dirs=None):
        initial = int((sum(x["size"] for x in manifest.ARTIFACTS + manifest.MODELS + manifest.SPECTRUM_FILES) + 7e9) * 1.1)
        suggestion = suggested_root(initial, self.disk_free)
        raw = engine_root or self.settings.engine_root or suggestion
        root = validate_root(raw, forbidden=self.forbidden_roots)
        checks, warnings = [], []
        is_windows = platform.system() == "Windows"
        if not is_windows or platform.machine().lower() not in ("amd64", "x86_64") or platform.release() not in ("10", "11"):
            checks.append({"id": "os", "ok": False, "code": "UNSUPPORTED_OS", "message": "Windows 10/11 64비트가 필요합니다."})
        else:
            checks.append({"id": "os", "ok": True, "code": None, "message": ""})
        if is_windows:
            try:
                directory = Path(self.system_directory())
                present = all((directory / name).is_file() for name in
                              ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll"))
            except OSError:
                present = False
            checks.append({"id": "vcredist", "ok": present, "code": None if present else "VCREDIST_MISSING",
                           "message": "" if present else manifest.VCREDIST_MESSAGE})
        probed_gpu = self.gpu_probe()
        gpu = None
        try:
            gpu = validate_gpu(probed_gpu)
            checks.append({"id": "gpu", "ok": True, "code": None, "message": ""})
            if gpu.get("vram_mb", 0) < 8192:
                warnings.append("메모리가 부족할 수 있습니다.")
        except ManagedEngineError as exc:
            # 2026-10-01 user policy: detected NVIDIA hardware may attempt install/start.
            # Keep runtime CUDA health + smoke failures authoritative; never claim these passed.
            detected = probed_gpu if probed_gpu is not None else _windows_nvidia_gpu()
            if detected is None:
                checks.append({"id": "gpu", "ok": False, "code": exc.code, "message": exc.message})
            else:
                gpu = asdict(detected) if isinstance(detected, GpuInfo) else dict(detected)
                code = "GPU_PROBE_FAILED" if probed_gpu is None else exc.code
                reason = "NVIDIA 카드의 CUDA 정보를 확인하지 못했습니다." if probed_gpu is None else exc.message
                message = f"{reason} NVIDIA 카드가 확인되어 설치 및 실행을 시도할 수 있습니다. 실제 동작은 실행 시 확인합니다."
                checks.append({"id": "gpu", "ok": True, "warning": True, "code": code, "message": message})
                warnings.append(message)
        candidates = {}
        for directory in (model_dirs if model_dirs is not None else self.settings.model_dirs):
            for path in walk_files(directory, depth=4):
                if path.name in {m["filename"] for m in manifest.MODELS}:
                    candidates.setdefault(path.name, []).append(path)
        plan = []
        for artifact in manifest.ARTIFACTS:
            target = root / "cache" / artifact["cache_name"]
            plan.append(self._artifact_plan(artifact, target, root))
        for model in manifest.MODELS:
            target = root / "models" / model["category"] / model["filename"]
            item = self._artifact_plan(model, target, root)
            if item["action"] != "present":
                for candidate in candidates.get(model["filename"], []):
                    self._check_cancel()
                    if candidate.stat().st_size == model["size"] and verified_hash(candidate, root, force=self._force, cancel=self._cancel) == model["sha256"]:
                        item.update(action="reuse", path=str(candidate))
                        break
            plan.append(item)
        for node in manifest.SPECTRUM_FILES:
            plan.append(self._artifact_plan(node, root / "cache/spectrum" / node["path"], root))
        download_bytes = partial_bytes = remaining_bytes = 0
        for item in plan:
            if item["action"] != "download":
                continue
            target = Path(item["path"])
            part = target.with_name(target.name + ".part")  # LlamaModelDownloadService.part_path
            have = part.stat().st_size if part.is_file() else 0
            download_bytes += item["size"]
            partial_bytes += have
            remaining_bytes += max(0, item["size"] - have)
        installed = 0
        if runtime_needs_extract(root, self._force):
            installed = manifest.ARTIFACTS[0].get("installed_bytes") or 7_000_000_000
        required = math.ceil((remaining_bytes + installed) * 1.1)
        free = self.disk_free(root)
        checks.append({"id": "disk", "ok": free >= required, "code": None if free >= required else "DISK_SPACE",
                       "message": "" if free >= required else "엔진 설치 공간이 부족합니다."})
        return {"engine_root": str(root), "suggested_root": str(suggestion), "gpu": gpu, "checks": checks,
                "artifacts": plan, "download_bytes": download_bytes, "partial_bytes": partial_bytes,
                "required_bytes": required, "free_bytes": free,
                "warnings": warnings}

    def _artifact_plan(self, artifact, target, root):
        present = target.is_file() and target.stat().st_size == artifact["size"] and verified_hash(
            target, root, force=self._force, cancel=self._cancel) == artifact["sha256"]
        return {"id": artifact["id"], "size": artifact["size"], "action": "present" if present else "download", "path": str(target)}

    def start(self, *, select_on_ready, force_verify=False):
        with self._lock:
            if self._state["state"] == "preparing":
                return {**self.snapshot(), "joined": True}
            if not self.settings.engine_root:
                raise ManagedEngineError("PATH_INVALID", "설치 위치를 먼저 확인해 주세요.")
            validate_root(self.settings.engine_root, forbidden=self.forbidden_roots)
            self._cancel.clear()
            self._force, self._select = force_verify, select_on_ready
            self._completed = []
            self._trace = ""
            self._state.update(state="preparing", phase="inspect", job_id=str(uuid.uuid4()), code=None,
                               message="PC 환경 확인 중", retryable=False, bytes_done=0, bytes_total=0,
                               started_at=datetime.now().astimezone().isoformat())
            with REGISTRY_LOCK:
                if str(Path(self.settings.engine_root).resolve()) in INSTALLING:
                    self._state["state"] = "not_installed"
                    raise ManagedEngineError("JOB_RUNNING", "이 엔진의 설치가 이미 진행 중입니다.")
                INSTALLING.add(str(Path(self.settings.engine_root).resolve()))
            self._thread = Thread(target=self._run, daemon=True, name="anima-install")
            self._thread.start()
            return {**self.snapshot(), "joined": False}

    def cancel(self):
        with self._lock:
            preparing = self._state["state"] == "preparing"
            if preparing:
                self._cancel.set()
                self._publish(message="취소 중입니다. 진행 중인 요청이 종료되면 완료됩니다.")
        if preparing:
            if self._download:
                self._download.cancel()
            if self._runtime:
                self._runtime.stop()
        return self.snapshot()

    def wait(self, timeout=None):
        if self._thread:
            self._thread.join(timeout)

    def _fetch(self, artifact, target):
        self._check_cancel()
        target = Path(target)
        if target.is_file():
            if target.stat().st_size == artifact["size"] and sha256_of(target, cancel=self._cancel) == artifact["sha256"]:
                self._cleanup_invalid(target)
                return
            # Keep evidence; this path is an owned artifact, never a reuse source.
            target.replace(target.with_name(target.name + ".invalid-" + uuid.uuid4().hex))
        self._publish(current_item=artifact["id"])
        service = LlamaModelDownloadService(target, url=artifact["url"], sha256=artifact["sha256"],
                                            expected_size=artifact["size"], opener=self.opener)
        self._download = service
        service.start()
        while service.snapshot()["active"]:
            if self._cancel.wait(0.05):
                service.cancel()
            service.wait(0.05)
        self._download = None
        self._check_cancel()
        state = service.snapshot()
        if not state["done"]:
            code = "HASH_MISMATCH" if "SHA-256" in state.get("error", "") else "DOWNLOAD_FAILED"
            raise ManagedEngineError(code, "파일 다운로드에 실패했습니다.", state.get("error", ""))
        self._cleanup_invalid(target)
        self._publish(bytes_done=self._state["bytes_done"] + artifact["size"])

    def _cleanup_invalid(self, target):
        root = Path(self.settings.engine_root).resolve()
        if target.parent.resolve() != target.parent or not target.resolve().is_relative_to(root):
            raise ManagedEngineError("PATH_INVALID")
        for path in target.parent.glob(target.name + ".invalid-*"):
            if path.is_symlink() or getattr(path, "is_junction", lambda: False)() or not path.is_file():
                raise ManagedEngineError("PATH_INVALID")
            try:
                path.unlink()
            except OSError as exc:
                print(f"ANIMA: invalid artifact cleanup failed ({type(exc).__name__})", flush=True)

    def _phase(self, name, action):
        self._check_cancel()
        self._publish(phase=name, message="ANIMA 준비: " + name)
        action()
        self._check_cancel()
        self._completed.append(name)
        self._publish()

    def _remove_staging(self, staging):
        base = Path(self.settings.engine_root).resolve() / "runtime"
        if base.resolve() != base or staging.is_symlink() or getattr(staging, "is_junction", lambda: False)() or staging.resolve().parent != base:
            raise ManagedEngineError("PATH_INVALID", "스테이징 경로를 확인해 주세요.")
        if staging.exists():
            shutil.rmtree(staging)

    def _cleanup_backups(self):
        base = Path(self.settings.engine_root).resolve() / "runtime"
        if base.resolve() != base:
            raise ManagedEngineError("PATH_INVALID")
        if not base.exists():
            return
        for path in base.iterdir():
            if path.name.startswith((manifest.RUNTIME_ID + ".previous-", manifest.RUNTIME_ID + ".failed-")):
                self._remove_staging(path)

    def _run(self):
        root = Path(self.settings.engine_root).resolve()
        active = root / "runtime" / manifest.RUNTIME_ID
        staging = active.with_name(active.name + ".staging")
        backup = None
        success = False
        try:
            self._cleanup_backups()
            plan = None
            def inspect_phase():
                nonlocal plan
                plan = self.inspect()
                for check in plan["checks"]:
                    if not check["ok"]:
                        raise ManagedEngineError(check["code"], check["message"])
                self._publish(bytes_total=plan["download_bytes"], warnings=plan["warnings"])
            self._phase("inspect", inspect_phase)
            items = {a["id"]: a for a in manifest.ARTIFACTS + manifest.MODELS + manifest.SPECTRUM_FILES}
            def download_phase():
                for item in plan["artifacts"]:
                    if item["action"] == "download":
                        self._fetch(items[item["id"]], item["path"])
            self._phase("download", download_phase)
            fresh = runtime_needs_extract(root, self._force)
            if fresh:
                def extract():
                    self._remove_staging(staging)
                    staging.mkdir(parents=True)
                    tool, archive = manifest.ARTIFACTS[1], manifest.ARTIFACTS[0]
                    exe = root / "cache" / tool["cache_name"]
                    if sha256_of(exe) != tool["sha256"]:
                        raise ManagedEngineError("HASH_MISMATCH")
                    self.run_7z(exe, root / "cache" / archive["cache_name"], staging, self._cancel)
                    rt = staging / "ComfyUI_windows_portable"
                    if not (rt / "python_embeded/python.exe").is_file() or not (rt / "ComfyUI/main.py").is_file():
                        raise ManagedEngineError("EXTRACT_FAILED")
                self._phase("extract", extract)
            def install_nodes():
                dest = (staging if fresh else active) / "ComfyUI_windows_portable/ComfyUI/custom_nodes/comfyui-spectrum-ksampler"
                for node in manifest.SPECTRUM_FILES:
                    target = dest / node["path"]
                    if not target.resolve().is_relative_to(root) or any(
                            path.is_symlink() or getattr(path, "is_junction", lambda: False)()
                            for path in (target, *target.parents)):
                        raise ManagedEngineError("PATH_INVALID", detail=node["path"])
                    if not fresh and target.is_file() and sha256_of(target, cancel=self._cancel) == node["sha256"]:
                        continue
                    cached = root / "cache/spectrum" / node["path"]
                    if not cached.is_file() or sha256_of(cached, cancel=self._cancel) != node["sha256"]:
                        raise ManagedEngineError("NODE_INSTALL_FAILED", detail=node["path"])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    # Replace a verified copy instead of overwriting a possible hard link.
                    temporary = target.with_name(target.name + ".tmp-" + uuid.uuid4().hex)
                    try:
                        shutil.copyfile(cached, temporary)
                        if sha256_of(temporary, cancel=self._cancel) != node["sha256"]:
                            raise ManagedEngineError("NODE_INSTALL_FAILED", detail=node["path"])
                        temporary.replace(target)
                    finally:
                        temporary.unlink(missing_ok=True)
            self._phase("install_nodes", install_nodes)
            model_paths = {item["id"]: item["path"] for item in plan["artifacts"] if item["id"] in {m["id"] for m in manifest.MODELS}}
            self._phase("write_config", lambda: write_instance_model_config(self.save_root, model_paths))
            # Stop the registered process before replacing files it may have open.
            with REGISTRY_LOCK:
                previous = REGISTRY.get(str(root))
            if previous:
                previous.stop()
            def promote():
                nonlocal backup
                if fresh:
                    if active.exists():
                        backup = active.with_name(active.name + ".previous-" + uuid.uuid4().hex)
                        active.rename(backup)
                    staging.rename(active)
            self._phase("promote", promote)
            def start():
                self._runtime = self.runtime_factory(root, manifest.RUNTIME_ID)
                # 영수증은 아직 없다 - 계획의 모델 자리(다른 폴더에서 재사용한 모델 포함)로 켠다
                self._runtime.model_config = partial(write_instance_model_config, self.save_root, model_paths)
                self._runtime.installation_gpu_uuid = plan["gpu"].get("uuid", "")
                try:
                    self._runtime.ensure_running()
                finally:
                    # 이후 기동은 영수증과 현재 카드 목록을 다시 확인한다.
                    self._runtime.installation_gpu_uuid = None
            self._phase("start", start)
            self._phase("preflight", self._runtime.preflight)
            smoke_result = {}
            self._phase("smoke", lambda: smoke_result.update(self._runtime.smoke()))
            def activate():
                receipt = {"version": 1, "profile_id": manifest.PROFILE_ID, "profile_revision": manifest.PROFILE_REVISION,
                           "runtime_id": manifest.RUNTIME_ID, "comfyui_portable_sha256": manifest.ARTIFACTS[0]["sha256"],
                           "spectrum_commit": manifest.SPECTRUM_COMMIT,
                           "models": {m["id"]: {"path": model_paths[m["id"]], "sha256": m["sha256"]} for m in manifest.MODELS},
                           "gpu": plan["gpu"], "system_stats": self._runtime.system_stats, "smoke": smoke_result,
                           "created_at": datetime.now().astimezone().isoformat(), "naia_version": app_version()}
                with self._lock:
                    self._check_cancel()
                    previous_receipt = read_json(root / "receipt.json")
                    atomic_json(root / "receipt.json", receipt)
                    try:
                        self.on_ready(self._runtime)
                    except Exception:
                        if previous_receipt:
                            atomic_json(root / "receipt.json", previous_receipt)
                        else:
                            (root / "receipt.json").unlink(missing_ok=True)
                        raise
                    self._publish(state="ready", phase="activate", code=None, message="ANIMA 준비 완료", current_item=None)
            self._phase("activate", activate)
            success = True
            if backup:
                try:
                    self._remove_staging(backup)
                except (OSError, ManagedEngineError) as exc:
                    print(f"ANIMA: runtime backup cleanup failed ({type(exc).__name__})", flush=True)
            self._publish(state="ready", phase="activate", code=None, message="ANIMA 준비 완료", current_item=None)
        except InterruptedError:
            self._publish(state="canceled", code="CANCELED", message="설치를 취소했습니다.", retryable=True)
        except Exception as exc:
            self._trace = traceback.format_exc()[-TRACE_CHARS:]      # 어디서 났는지 - 코드 · 메시지만으론 모른다
            code = getattr(exc, "code", None) or {"extract": "EXTRACT_FAILED", "install_nodes": "NODE_INSTALL_FAILED",
                      "promote": "EXTRACT_FAILED", "write_config": "PATH_NOT_WRITABLE"}.get(self._state["phase"], "DOWNLOAD_FAILED")
            self._publish(state="blocked" if self._state["phase"] == "inspect" else "failed", code=code,
                          message=getattr(exc, "message", "ANIMA 준비에 실패했습니다."), detail=getattr(exc, "detail", "") or str(exc),
                          retryable=code not in ("UNSUPPORTED_OS", "GPU_UNSUPPORTED"))
        finally:
            try:
                if not success and self._runtime:
                    self._runtime.stop()
                if staging.exists():
                    self._remove_staging(staging)
                if not success and backup and backup.exists():
                    if active.exists():
                        active.rename(active.with_name(active.name + ".failed-" + uuid.uuid4().hex))
                    backup.rename(active)
            finally:
                with REGISTRY_LOCK:
                    INSTALLING.discard(str(root))


def app_version():
    try:
        # Read the version without importing the root module's bootstrap code.
        text = (Path(__file__).resolve().parents[2] / "__init__.py").read_text(encoding="utf-8")
        match = re.search(r'^__version__\s*=\s*[\x22\x27]([^\x22\x27]+)', text, re.MULTILINE)
        return match[1] if match else "unknown"
    except OSError:
        return "unknown"


def recover_interrupted(save_root):
    settings = load_settings(save_root)
    if settings.engine_root:
        path = Path(settings.engine_root) / "state/job.json"
        journal = read_json(path)
        if journal.get("state") == "preparing":
            journal.update(state="failed", updated_at=datetime.now().astimezone().isoformat(),
                           error={"code": "INTERRUPTED", "message": "설치가 중단되었습니다. 다시 시도해 주세요.", "retryable": True, "detail": ""})
            atomic_json(path, journal)
