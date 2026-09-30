"""Cheap polling checks and verified startup checks for the managed llama runtime."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from threading import Event, RLock
from typing import Any

# Same prerequisite and user-directed installer flow as the managed ANIMA engine.
VCREDIST_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
VCREDIST_MESSAGE = "Microsoft Visual C++ 재배포 패키지(x64)가 필요합니다."
VCREDIST_DLLS = ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll")


def vcredist_status(directory: Path | None = None) -> dict[str, Any]:
    missing = []
    if os.name == "nt" or directory is not None:
        try:
            if directory is None:
                import ctypes

                buffer = ctypes.create_unicode_buffer(32768)
                size = ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer))
                if not 0 < size < len(buffer):
                    raise OSError("GetSystemDirectoryW failed")
                directory = Path(buffer.value)
            missing = [name for name in VCREDIST_DLLS if not (directory / name).is_file()]
        except OSError:
            missing = list(VCREDIST_DLLS)
    return {"ok": not missing, "code": "VCREDIST_MISSING" if missing else None,
            "message": VCREDIST_MESSAGE if missing else "", "url": VCREDIST_URL, "missing": missing}


_VERIFIED: dict[tuple[str, int, str], tuple[tuple[int, int, int], bool]] = {}
_LOCK = RLock()


def _stamp(path: Path) -> tuple[int, int, int] | None:
    try:
        if path.is_file():
            stat = path.stat()
            return stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns
    except OSError:
        pass
    return None


def artifact_ready(path: Path, size: int, sha256: str) -> bool:
    """Polling never hashes GB files; a known hash failure remains unready until bytes change."""
    stamp = _stamp(path)
    if stamp is None or stamp[0] != size:
        return False
    with _LOCK:
        known = _VERIFIED.get((str(path.resolve()), size, sha256))
    return known is None or known[0] != stamp or known[1]


def verify_artifact(path: Path, size: int, sha256: str, *, force: bool = False,
                    cancel: Event | None = None) -> bool:
    """Verify existing managed files on launch/repair, caching only unchanged file stamps."""
    stamp = _stamp(path)
    if stamp is None or stamp[0] != size:
        return False
    key = (str(path.resolve()), size, sha256)
    with _LOCK:
        known = _VERIFIED.get(key)
    if not force and known is not None and known[0] == stamp:
        return known[1]
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            if cancel is not None and cancel.is_set():
                raise InterruptedError("검사가 취소되었습니다.")
            digest.update(block)
    if cancel is not None and cancel.is_set():
        raise InterruptedError("검사가 취소되었습니다.")
    valid = digest.hexdigest() == sha256 and _stamp(path) == stamp
    with _LOCK:
        _VERIFIED[key] = (stamp, valid)
    return valid
