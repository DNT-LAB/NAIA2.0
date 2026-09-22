"""Stage the bundled llama.cpp engine (Boost v2, official Vulkan build) into a NAIA Electron release.

The Vulkan build carries the CPU backends too: it runs on any GPU/iGPU with a Vulkan driver and falls
back to CPU by itself when there is none (measured 2026-09-23). On i9-285H/Arc 140T a call takes the
same ~6.8 s as the CPU build, but stays 6.7 s under CPU load where the CPU build degrades to 25 s.

The engine is NOT committed. At release time it is taken from, in order:
  1. ``--source-dir`` / env ``NAIA_LLAMA_ENGINE_SRC`` pointing at a directory that already holds
     the official Vulkan build (``llama-server.exe`` + DLLs), or at the official zip;
  2. otherwise the pinned official zip is downloaded (``ENGINE_URL``) into the cache dir.
A zip is accepted only when its SHA-256 matches ``ENGINE_SHA256``.

Target: ``resources/naia-backend/runtime/llama/engine`` — the default engine path the backend
resolves (``core.llama_runtime.default_engine_path``). ``*.md`` is dropped (release audit forbids
it); license files are kept and ``SOURCE.txt`` records where the files came from.

The model (3.1 GiB GGUF) is NOT bundled — the app downloads it on first use.

Removable: delete this tool, its call site in ``run_release_workspace`` and ``runtime/llama``.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import ssl
import sys
import tempfile
import urllib.request
import zipfile

try:
    from tools.write_release_metadata import write_release_metadata
except ModuleNotFoundError:  # pragma: no cover - used when executed as a script.
    from write_release_metadata import write_release_metadata

ENGINE_VERSION = "b10830"
ENGINE_ASSET = f"llama-{ENGINE_VERSION}-bin-win-vulkan-x64.zip"
ENGINE_URL = f"https://github.com/ggml-org/llama.cpp/releases/download/{ENGINE_VERSION}/{ENGINE_ASSET}"
ENGINE_SHA256 = "732aa8999056d1694af2ec3ff61f1a60e2e56b2a5310eb765185909623e0f56f"
ENGINE_TARGET = Path("resources") / "naia-backend" / "runtime" / "llama" / "engine"
# 실측(llama_test, 2026-09-22): 이 파일들이 실제로 로드됐다. ggml-cpu-*.dll 은 CPU 에 따라 하나가 골라진다.
REQUIRED_FILES = (
    "llama-server.exe", "llama-server-impl.dll", "llama-common.dll", "llama.dll",
    "ggml.dll", "ggml-base.dll", "ggml-rpc.dll", "ggml-vulkan.dll", "mtmd.dll", "libomp.dll",
)
DROP_SUFFIXES = (".md", ".log")


@dataclass(frozen=True)
class LlamaRuntimeStageResult:
    release_root: str
    source: str
    target: str
    file_count: int
    total_bytes: int
    engine_version: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _download(url: str, dest: Path) -> None:
    try:
        import certifi

        context = ssl.create_default_context(cafile=certifi.where())
    except Exception:  # pragma: no cover
        context = ssl.create_default_context()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "NAIA-release/stage_llama_runtime"})
    with urllib.request.urlopen(request, timeout=60, context=context) as response, tmp.open("wb") as out:
        shutil.copyfileobj(response, out, 1 << 20)
    tmp.replace(dest)


def _extract_zip(zip_path: Path, into: Path) -> Path:
    actual = _sha256(zip_path)
    if actual != ENGINE_SHA256:
        raise RuntimeError(f"llama.cpp zip SHA-256 mismatch: {actual} != {ENGINE_SHA256} ({zip_path})")
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(into)
    servers = list(into.rglob("llama-server.exe"))
    if not servers:
        raise RuntimeError(f"llama-server.exe not found in {zip_path}")
    return servers[0].parent


def _check_engine_dir(directory: Path) -> None:
    missing = [name for name in REQUIRED_FILES if not (directory / name).is_file()]
    if not list(directory.glob("ggml-cpu-*.dll")):
        missing.append("ggml-cpu-*.dll")
    if missing:
        raise RuntimeError(f"llama.cpp engine is incomplete in {directory}: missing {', '.join(missing)}")


def stage_llama_runtime(
    release_root: str | Path,
    *,
    source: str | Path | None = None,
    cache_dir: str | Path | None = None,
    allow_download: bool = True,
) -> LlamaRuntimeStageResult:
    release_root = Path(release_root)
    target = release_root / ENGINE_TARGET
    source = source or os.environ.get("NAIA_LLAMA_ENGINE_SRC") or None
    with tempfile.TemporaryDirectory(prefix="naia-llama-") as scratch:
        scratch_path = Path(scratch)
        if source and Path(source).is_dir():
            engine_dir = Path(source)
            origin = f"dir:{engine_dir}"
        else:
            if source:
                zip_path = Path(source)
            else:
                if not allow_download:
                    raise RuntimeError("no llama.cpp engine source and download disabled")
                zip_path = Path(cache_dir or scratch_path) / ENGINE_ASSET
                if not zip_path.is_file() or _sha256(zip_path) != ENGINE_SHA256:
                    _download(ENGINE_URL, zip_path)
            engine_dir = _extract_zip(zip_path, scratch_path / "extract")
            origin = f"zip:{ENGINE_URL}#sha256={ENGINE_SHA256}"
        _check_engine_dir(engine_dir)
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
        (target / "SOURCE.txt").write_text(
            f"llama.cpp {ENGINE_VERSION} Windows Vulkan x64 (official build, MIT; GPU if available, else CPU)\n"
            f"origin: {origin}\n"
            "Used by NAIA Boost v2. Model is downloaded separately on first use.\n",
            encoding="utf-8",
        )
    # 체크섬·매니페스트를 다시 쓴다 — preflight/audit 가 읽는 목록에 엔진 파일이 들어가야 한다(Grok 과 같은 이유).
    write_release_metadata(release_root)
    return LlamaRuntimeStageResult(
        release_root=str(release_root), source=origin, target=str(target),
        file_count=count, total_bytes=size, engine_version=ENGINE_VERSION,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage the llama.cpp engine (Vulkan build) into a NAIA release.")
    parser.add_argument("release_root")
    parser.add_argument("--source", help="Engine directory or official zip (default: env NAIA_LLAMA_ENGINE_SRC, then download)")
    parser.add_argument("--cache-dir", help="Where to keep the downloaded zip")
    parser.add_argument("--no-download", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = stage_llama_runtime(args.release_root, source=args.source, cache_dir=args.cache_dir,
                                     allow_download=not args.no_download)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"ok": True, **result.__dict__}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
