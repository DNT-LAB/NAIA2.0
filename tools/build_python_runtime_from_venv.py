"""Build a portable Python runtime folder from an existing virtualenv.

The output is intended to be passed to ``tools/stage_python_runtime.py`` or the
Electron release scripts as ``--python-runtime-dir``.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any


DEFAULT_SMOKE_IMPORTS = (
    "fastapi",
    "uvicorn",
    "pandas",
    "pyarrow",
    "PIL",
)
BASE_ONLY_SMOKE_IMPORTS = (
    "venv",
    "ensurepip",
)

SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
}
TEST_DIR_NAMES = {"test", "tests", "testing"}
SKIP_SUFFIXES = {".md", ".pyc", ".pyo"}
SKIP_PACKAGE_PREFIXES = (
    "pyqt6",
    "pyqt6_",
    "pyqt6-",
    "pyqt6_qt6",
    "pyqt6_sip",
)
WINDOWS_RUNTIME_DIRS = ("DLLs", "Lib", "libs", "tcl")
POSIX_RUNTIME_DIRS = ("bin", "lib", "lib64")


@dataclass
class CopyStats:
    files: int = 0
    bytes: int = 0
    skipped: int = 0

    def add(self, other: "CopyStats") -> None:
        self.files += other.files
        self.bytes += other.bytes
        self.skipped += other.skipped


@dataclass
class PythonRuntimeBuildResult:
    ok: bool
    venv_root: str
    output_root: str
    base_prefix: str
    venv_python: str
    base_python: str
    site_packages: str
    copied: bool
    base_only: bool
    smoke_imports: list[str]
    smoke: dict[str, Any] | None = None
    planned: dict[str, int] = field(default_factory=dict)
    copied_stats: dict[str, int] = field(default_factory=dict)
    warnings: list[dict[str, str]] = field(default_factory=list)
    source_kind: str = "venv"
    source_python: str = ""


def find_venv_python(venv_root: str | Path) -> Path | None:
    root = Path(venv_root)
    candidates = (
        root / "Scripts" / "python.exe",
        root / "bin" / "python",
        root / "bin" / "python3",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def query_python_executable(python: str | Path) -> dict[str, Any]:
    python_path = Path(python).resolve()
    if not python_path.is_file():
        raise RuntimeError(f"Python executable not found: {python_path}")
    code = r"""
import json
import sys
import sysconfig

print(json.dumps({
    "executable": sys.executable,
    "base_executable": getattr(sys, "_base_executable", ""),
    "prefix": sys.prefix,
    "base_prefix": sys.base_prefix,
    "version": sys.version,
    "version_info": list(sys.version_info[:3]),
    "purelib": sysconfig.get_paths().get("purelib", ""),
    "platlib": sysconfig.get_paths().get("platlib", ""),
    "stdlib": sysconfig.get_paths().get("stdlib", ""),
    "platstdlib": sysconfig.get_paths().get("platstdlib", ""),
}))
"""
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [str(python_path), "-B", "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"venv introspection failed: {completed.stderr.strip() or completed.stdout.strip()}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"venv introspection did not return JSON: {completed.stdout!r}") from exc


def query_venv(venv_root: str | Path) -> dict[str, Any]:
    python = find_venv_python(venv_root)
    if python is None:
        raise RuntimeError(f"venv Python executable not found under: {Path(venv_root).resolve()}")
    return query_python_executable(python)


def resolve_python_version(version: str) -> Path:
    """Resolve a Python executable for a version such as ``3.12``."""

    cleaned = version.strip()
    if not cleaned:
        raise RuntimeError("Python version must not be empty")

    candidates: list[list[str]] = []
    if os.name == "nt":
        candidates.append(["py", f"-{cleaned}"])
    compact = cleaned.replace(".", "")
    candidates.extend((
        [f"python{cleaned}"],
        [f"python{compact}"],
        ["python"],
    ))
    code = "import sys; print(sys.executable)"
    errors: list[str] = []
    for command in candidates:
        completed = subprocess.run(
            [*command, "-B", "-c", code],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode != 0:
            errors.append(f"{' '.join(command)}: {completed.stderr.strip() or completed.stdout.strip()}")
            continue
        path = Path(completed.stdout.strip())
        if not path.is_file():
            errors.append(f"{' '.join(command)}: resolved path is not a file: {path}")
            continue
        info = query_python_executable(path)
        actual = info.get("version_info") or []
        expected = [int(part) for part in cleaned.split(".") if part.isdigit()]
        if expected and list(actual[:len(expected)]) != expected:
            errors.append(f"{path}: expected Python {cleaned}, got {info.get('version', '')}")
            continue
        return path.resolve()
    raise RuntimeError(f"Python {cleaned} executable was not found. Tried: {'; '.join(errors)}")


def _should_skip(relative: Path, *, keep_tests: bool = False, skip_base_site_packages: bool = False) -> bool:
    parts = tuple(part.lower() for part in relative.parts)
    if any(part in SKIP_DIR_NAMES for part in parts):
        return True
    if any(part.startswith(SKIP_PACKAGE_PREFIXES) for part in parts):
        return True
    if not keep_tests and any(part in TEST_DIR_NAMES for part in parts):
        return True
    if relative.suffix.lower() in SKIP_SUFFIXES:
        return True
    if skip_base_site_packages and parts and parts[0] == "site-packages":
        return True
    return False


def _copy_or_plan_tree(
    source: Path,
    destination: Path,
    *,
    copy: bool,
    keep_tests: bool,
    skip_base_site_packages: bool = False,
) -> CopyStats:
    stats = CopyStats()
    if not source.exists():
        return stats
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if _should_skip(relative, keep_tests=keep_tests, skip_base_site_packages=skip_base_site_packages):
            stats.skipped += 1
            if path.is_dir():
                continue
            continue
        if path.is_dir():
            continue
        stats.files += 1
        try:
            stats.bytes += path.stat().st_size
        except OSError:
            pass
        if copy:
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    return stats


def _copy_or_plan_file(source: Path, destination: Path, *, copy: bool) -> CopyStats:
    stats = CopyStats()
    if not source.is_file():
        return stats
    stats.files = 1
    stats.bytes = source.stat().st_size
    if copy:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return stats


def _base_runtime_items(base_prefix: Path) -> list[tuple[Path, Path, dict[str, bool]]]:
    items: list[tuple[Path, Path, dict[str, bool]]] = []
    runtime_dirs = WINDOWS_RUNTIME_DIRS if os.name == "nt" else POSIX_RUNTIME_DIRS
    for name in runtime_dirs:
        source = base_prefix / name
        if source.is_dir():
            items.append((source, Path(name), {"skip_base_site_packages": name.lower() in {"lib", "lib64"}}))

    for source in base_prefix.iterdir() if base_prefix.is_dir() else ():
        lower = source.name.lower()
        if not source.is_file():
            continue
        if lower in {"python.exe", "pythonw.exe", "license.txt"}:
            items.append((source, Path(source.name), {}))
        elif lower.startswith("python") and lower.endswith((".dll", ".so", ".dylib")):
            items.append((source, Path(source.name), {}))
        elif lower.startswith("vcruntime") and lower.endswith(".dll"):
            items.append((source, Path(source.name), {}))
    return items


def _write_manifest(
    output: Path,
    *,
    info: dict[str, Any],
    stats: CopyStats,
    smoke: dict[str, Any] | None,
    base_only: bool,
) -> None:
    manifest = {
        "schema_version": 1,
        "builder": "tools/build_python_runtime_from_venv.py",
        "base_only": bool(base_only),
        "base_prefix": info.get("base_prefix", ""),
        "venv_prefix": info.get("prefix", ""),
        "venv_python": info.get("executable", ""),
        "base_python": info.get("base_executable", ""),
        "version": info.get("version", ""),
        "stats": asdict(stats),
        "smoke": smoke,
    }
    (output / "NAIA_PYTHON_RUNTIME_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run_smoke(output_root: str | Path, imports: list[str]) -> dict[str, Any]:
    output = Path(output_root).resolve()
    python = output / "python.exe" if os.name == "nt" else output / "bin" / "python"
    if not python.is_file():
        return {
            "ok": False,
            "python": str(python),
            "imports": imports,
            "error": "runtime Python executable is missing",
        }
    code = (
        "import importlib, json, sys; "
        "mods=json.loads(sys.argv[1]); "
        "loaded=[]; "
        "[loaded.append(importlib.import_module(m).__name__) for m in mods]; "
        "print(json.dumps({'ok': True, 'loaded': loaded, 'executable': sys.executable, 'prefix': sys.prefix}))"
    )
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [str(python), "-B", "-c", code, json.dumps(imports)],
        cwd=output,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )
    payload: dict[str, Any]
    try:
        payload = json.loads(completed.stdout) if completed.stdout.strip() else {}
    except json.JSONDecodeError:
        payload = {}
    payload.update({
        "ok": completed.returncode == 0 and payload.get("ok") is True,
        "python": str(python),
        "imports": imports,
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    })
    return payload


def build_python_runtime_from_venv(
    *,
    venv_root: str | Path,
    output_root: str | Path,
    copy: bool = False,
    smoke_imports: list[str] | None = None,
    skip_smoke: bool = False,
    keep_tests: bool = False,
    base_only: bool = False,
) -> PythonRuntimeBuildResult:
    venv = Path(venv_root).resolve()
    info = query_venv(venv)
    return _build_python_runtime_from_info(
        info=info,
        source_root=venv,
        source_kind="venv",
        output_root=output_root,
        copy=copy,
        smoke_imports=smoke_imports,
        skip_smoke=skip_smoke,
        keep_tests=keep_tests,
        base_only=base_only,
    )


def build_python_runtime_from_python(
    *,
    python_executable: str | Path,
    output_root: str | Path,
    copy: bool = False,
    smoke_imports: list[str] | None = None,
    skip_smoke: bool = False,
    keep_tests: bool = False,
    base_only: bool = True,
) -> PythonRuntimeBuildResult:
    python = Path(python_executable).resolve()
    info = query_python_executable(python)
    if not base_only:
        raise RuntimeError("building a dependency runtime from a base Python executable is not supported; use --venv")
    return _build_python_runtime_from_info(
        info=info,
        source_root=python.parent,
        source_kind="python",
        output_root=output_root,
        copy=copy,
        smoke_imports=smoke_imports,
        skip_smoke=skip_smoke,
        keep_tests=keep_tests,
        base_only=base_only,
    )


def _build_python_runtime_from_info(
    *,
    info: dict[str, Any],
    source_root: str | Path,
    source_kind: str,
    output_root: str | Path,
    copy: bool,
    smoke_imports: list[str] | None,
    skip_smoke: bool,
    keep_tests: bool,
    base_only: bool,
) -> PythonRuntimeBuildResult:
    source_root_path = Path(source_root).resolve()
    output = Path(output_root).resolve()
    base_prefix = Path(str(info.get("base_prefix") or "")).resolve()
    site_packages = Path(str(info.get("purelib") or info.get("platlib") or "")).resolve()
    warnings: list[dict[str, str]] = []

    if not base_prefix.is_dir():
        raise RuntimeError(f"base Python prefix is not a directory: {base_prefix}")
    if not base_only and not site_packages.is_dir():
        raise RuntimeError(f"venv site-packages is not a directory: {site_packages}")
    if copy and output.exists() and any(output.iterdir()):
        raise RuntimeError(f"output directory is not empty: {output}")

    stats = CopyStats()
    if copy:
        output.mkdir(parents=True, exist_ok=True)

    for runtime_source, relative_target, options in _base_runtime_items(base_prefix):
        target = output / relative_target
        if runtime_source.is_dir():
            stats.add(_copy_or_plan_tree(
                runtime_source,
                target,
                copy=copy,
                keep_tests=keep_tests,
                skip_base_site_packages=bool(options.get("skip_base_site_packages")),
            ))
        else:
            stats.add(_copy_or_plan_file(runtime_source, target, copy=copy))

    if not base_only:
        stats.add(_copy_or_plan_tree(
            site_packages,
            output / "Lib" / "site-packages" if os.name == "nt" else output / "lib" / "site-packages",
            copy=copy,
            keep_tests=keep_tests,
        ))

    imports = list(smoke_imports or (BASE_ONLY_SMOKE_IMPORTS if base_only else DEFAULT_SMOKE_IMPORTS))
    smoke = None
    if copy and not skip_smoke:
        smoke = run_smoke(output, imports)
        if not smoke.get("ok"):
            warnings.append({"path": str(output), "reason": "runtime smoke failed"})
    if copy:
        _write_manifest(output, info=info, stats=stats, smoke=smoke, base_only=base_only)

    ok = not copy or skip_smoke or smoke is None or bool(smoke.get("ok"))
    return PythonRuntimeBuildResult(
        ok=ok,
        venv_root=str(source_root_path),
        output_root=str(output),
        base_prefix=str(base_prefix),
        venv_python=str(info.get("executable") or ""),
        base_python=str(info.get("base_executable") or ""),
        site_packages=str(site_packages),
        copied=copy,
        base_only=base_only,
        smoke_imports=imports,
        smoke=smoke,
        planned=asdict(stats) if not copy else {},
        copied_stats=asdict(stats) if copy else {},
        warnings=warnings,
        source_kind=source_kind,
        source_python=str(info.get("executable") or ""),
    )


def summarize_result(result: PythonRuntimeBuildResult) -> dict[str, Any]:
    smoke = result.smoke or {}
    return {
        "ok": result.ok,
        "copied": result.copied,
        "base_only": result.base_only,
        "venv_root": result.venv_root,
        "output_root": result.output_root,
        "base_prefix": result.base_prefix,
        "base_python": result.base_python,
        "site_packages": result.site_packages,
        "smoke_imports": result.smoke_imports,
        "smoke_ok": smoke.get("ok") if smoke else None,
        "planned": result.planned,
        "copied_stats": result.copied_stats,
        "warnings": result.warnings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a portable Python runtime from an existing venv.")
    parser.add_argument("--venv", default="venv", help="Virtualenv root to inspect.")
    parser.add_argument("--python", default=None, help="Base Python executable to inspect for a base-only runtime.")
    parser.add_argument("--python-version", default=None, help="Resolve a base Python executable by version, for example 3.12.")
    parser.add_argument("--output", required=True, help="Output runtime directory. Must be missing or empty when --copy is used.")
    parser.add_argument("--copy", action="store_true", help="Copy files. Dry-run plan when omitted.")
    parser.add_argument("--skip-smoke", action="store_true", help="Do not run runtime import smoke after copying.")
    parser.add_argument("--keep-tests", action="store_true", help="Keep package test directories in the runtime.")
    parser.add_argument(
        "--base-only",
        action="store_true",
        help="Copy only the base Python runtime. The packaged app will create a managed env on first launch.",
    )
    parser.add_argument(
        "--smoke-import",
        action="append",
        default=None,
        help="Module to import in the copied runtime smoke. Repeatable. Defaults to NAIA headless essentials.",
    )
    parser.add_argument("--summary", action="store_true", help="Print compact JSON.")
    args = parser.parse_args(argv)

    if args.python and args.python_version:
        parser.error("--python and --python-version are mutually exclusive")
    if (args.python or args.python_version) and not args.base_only:
        parser.error("--python/--python-version require --base-only")

    if args.python_version:
        result = build_python_runtime_from_python(
            python_executable=resolve_python_version(args.python_version),
            output_root=args.output,
            copy=args.copy,
            smoke_imports=args.smoke_import,
            skip_smoke=args.skip_smoke,
            keep_tests=args.keep_tests,
            base_only=True,
        )
    elif args.python:
        result = build_python_runtime_from_python(
            python_executable=args.python,
            output_root=args.output,
            copy=args.copy,
            smoke_imports=args.smoke_import,
            skip_smoke=args.skip_smoke,
            keep_tests=args.keep_tests,
            base_only=True,
        )
    else:
        result = build_python_runtime_from_venv(
            venv_root=args.venv,
            output_root=args.output,
            copy=args.copy,
            smoke_imports=args.smoke_import,
            skip_smoke=args.skip_smoke,
            keep_tests=args.keep_tests,
            base_only=args.base_only,
        )
    payload: dict[str, Any] = summarize_result(result) if args.summary else asdict(result)
    json.dump(payload, sys.stdout, ensure_ascii=True, indent=2)
    sys.stdout.write("\n")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
