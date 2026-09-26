"""llama.cpp 엔진(공식 Vulkan 판)을 앱 안에서 받는다 — 엔진이 없는 설치(소스 체크아웃)용.

포터블 릴리즈는 엔진을 동봉한다(``tools/stage_llama_runtime.py`` — 같은 상수를 여기서 가져간다, 한 곳).
받는 순서: 고정 zip(35 MB) -> SHA-256 확인 -> 임시 폴더에 풀기 -> 필수 파일 확인 -> 엔진 폴더로 옮기기.
해시가 틀리거나 파일이 모자라면 엔진 폴더를 건드리지 않는다.
"""

from __future__ import annotations

import hashlib
import shutil
import ssl
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from threading import Event, RLock, Thread
from typing import Any, Callable

ENGINE_VERSION = "b10830"
ENGINE_ASSET = f"llama-{ENGINE_VERSION}-bin-win-vulkan-x64.zip"
ENGINE_URL = f"https://github.com/ggml-org/llama.cpp/releases/download/{ENGINE_VERSION}/{ENGINE_ASSET}"
ENGINE_SHA256 = "732aa8999056d1694af2ec3ff61f1a60e2e56b2a5310eb765185909623e0f56f"
# 실측(llama_test, 2026-09-22): 이 파일들이 실제로 로드됐다. ggml-cpu-*.dll 은 CPU 에 따라 하나가 골라진다.
REQUIRED_FILES = (
    "llama-server.exe", "llama-server-impl.dll", "llama-common.dll", "llama.dll",
    "ggml.dll", "ggml-base.dll", "ggml-rpc.dll", "ggml-vulkan.dll", "mtmd.dll", "libomp.dll",
)
DROP_SUFFIXES = (".md", ".log")
_APPROX_MB = 35

try:
    import certifi

    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except Exception:  # pragma: no cover - platform fallback
    SSL_CONTEXT = ssl.create_default_context()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def extract_engine_zip(zip_path: Path, into: Path, *, sha256: str = ENGINE_SHA256) -> Path:
    """해시가 맞는 zip 만 푼다. 반환: llama-server.exe 가 든 폴더."""
    actual = sha256_file(zip_path)
    if actual != sha256:
        raise RuntimeError(f"llama.cpp zip SHA-256 mismatch: {actual} != {sha256} ({zip_path})")
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(into)
    servers = list(into.rglob("llama-server.exe"))
    if not servers:
        raise RuntimeError(f"llama-server.exe not found in {zip_path}")
    return servers[0].parent


def check_engine_dir(directory: Path) -> None:
    missing = [name for name in REQUIRED_FILES if not (directory / name).is_file()]
    if not list(directory.glob("ggml-cpu-*.dll")):
        missing.append("ggml-cpu-*.dll")
    if missing:
        raise RuntimeError(f"llama.cpp engine is incomplete in {directory}: missing {', '.join(missing)}")


def copy_engine_files(engine_dir: Path, target: Path) -> tuple[int, int]:
    """엔진 파일을 target 으로(있던 것은 지운다). 반환: (파일 수, 바이트)."""
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    count = size = 0
    for item in sorted(engine_dir.iterdir()):
        if not item.is_file() or item.suffix.lower() in DROP_SUFFIXES:
            continue
        shutil.copy2(item, target / item.name)
        count += 1
        size += item.stat().st_size
    return count, size


class LlamaEngineInstallService:
    """엔진 받기 — 스레드 하나, snapshot() 으로 폴링(모델 다운로더와 같은 모양)."""

    def __init__(self, target_dir: Path | str, *, url: str = ENGINE_URL, sha256: str = ENGINE_SHA256,
                 opener: Callable[..., Any] | None = None, on_complete: Callable[[], Any] | None = None) -> None:
        self.target_dir = Path(target_dir)
        self.url = url
        self.sha256 = sha256.lower()
        self.on_complete = on_complete
        self._open = opener or (lambda req, timeout: urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT))
        self._lock = RLock()
        self._cancel = Event()
        self._thread: Thread | None = None
        self._state: dict[str, Any] = {"active": False, "phase": "idle", "percent": 0, "message": "", "error": "",
                                       "done": False, "approx_mb": _APPROX_MB, "version": ENGINE_VERSION,
                                       "updated_at": ""}

    @property
    def installed(self) -> bool:
        return (self.target_dir / "llama-server.exe").is_file()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            state = dict(self._state)
        state["installed"] = self.installed
        return state

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._state.get("active"):
                return dict(self._state)
            if self.installed:
                return self._set(phase="complete", percent=100, done=True, message="엔진이 이미 있습니다.")
            self._cancel.clear()
            self._state.update({"active": True, "phase": "download", "percent": 0, "message": "연결 중...",
                                "error": "", "done": False})
            self._thread = Thread(target=self._run, daemon=True, name="llama-engine-install")
            self._thread.start()
            return dict(self._state)

    def wait(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self) -> None:
        try:
            with tempfile.TemporaryDirectory(prefix="naia-llama-engine-") as scratch:
                zip_path = Path(scratch) / ENGINE_ASSET
                self._download(zip_path)
                self._set(phase="verify", message="검증 중(SHA-256)...")
                engine_dir = extract_engine_zip(zip_path, Path(scratch) / "extract", sha256=self.sha256)
                check_engine_dir(engine_dir)
                self._set(phase="install", message="설치 중...")
                copy_engine_files(engine_dir, self.target_dir)
            self._set(active=False, phase="complete", percent=100, done=True, error="", message="설치 완료")
            if self.on_complete is not None:
                try:
                    self.on_complete()
                except Exception:
                    pass
        except urllib.error.HTTPError as exc:
            self._fail(f"HTTP 오류 {exc.code}: {exc.reason}")
        except urllib.error.URLError as exc:
            self._fail(f"네트워크 오류: {exc.reason}")
        except Exception as exc:
            self._fail(f"엔진 설치 실패: {exc}")

    def _download(self, dest: Path) -> None:
        request = urllib.request.Request(self.url, headers={"User-Agent": "NAIA/2.0 LlamaEngine"})
        with self._open(request, 60) as response, dest.open("wb") as out:
            total = int(response.headers.get("Content-Length") or 0) if getattr(response, "headers", None) else 0
            done, last = 0, 0.0
            while True:
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                now = time.monotonic()
                if total and now - last >= 0.25:
                    last = now
                    percent = min(99, int(done * 100 / total))
                    self._set(percent=percent, message=f"다운로드 중... {percent}% ({done / 1048576:.1f} MB)")

    def _fail(self, message: str) -> None:
        self._set(active=False, phase="error", message=message, error=message, done=False)

    def _set(self, **updates: Any) -> dict[str, Any]:
        with self._lock:
            self._state.update(updates)
            self._state["updated_at"] = datetime.now().isoformat(timespec="seconds")
            return dict(self._state)


__all__ = ["ENGINE_VERSION", "ENGINE_ASSET", "ENGINE_URL", "ENGINE_SHA256", "REQUIRED_FILES", "DROP_SUFFIXES",
           "LlamaEngineInstallService", "extract_engine_zip", "check_engine_dir", "copy_engine_files", "sha256_file"]
