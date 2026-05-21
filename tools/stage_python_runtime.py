"""Stage a provided Python runtime folder into a NAIA Electron release."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import sys

try:
    from tools.write_release_metadata import write_release_metadata
except ModuleNotFoundError:  # pragma: no cover - used when executed as a script.
    from write_release_metadata import write_release_metadata


PYTHON_RESOURCE_DIR = Path("resources") / "python"


@dataclass(frozen=True)
class PythonRuntimeStageResult:
    release_root: str
    runtime_source: str
    runtime_target: str
    executable: str
    copied: bool


def find_python_executable(runtime_root: str | Path) -> Path | None:
    root = Path(runtime_root)
    candidates = (
        root / "python.exe",
        root / "python",
        root / "bin" / "python",
        root / "bin" / "python3",
        root / "Scripts" / "python.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _copy_runtime_tree(source: Path, target: Path) -> None:
    if target.exists() and any(target.iterdir()):
        raise RuntimeError(f"Python runtime target is not empty: {target}")
    target.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        destination = target / item.name
        if item.is_dir():
            shutil.copytree(item, destination, symlinks=True)
        elif item.is_file():
            shutil.copy2(item, destination)


def _target_executable(target: Path, source_executable: Path, source_root: Path) -> Path:
    try:
        relative = source_executable.relative_to(source_root)
    except ValueError:
        relative = Path(source_executable.name)
    return target / relative


def stage_python_runtime(
    release_root: str | Path,
    runtime_root: str | Path,
    *,
    copy: bool = False,
) -> PythonRuntimeStageResult:
    release = Path(release_root).resolve()
    source = Path(runtime_root).resolve()
    if not release.is_dir():
        raise RuntimeError(f"Release root is not a directory: {release}")
    if not source.is_dir():
        raise RuntimeError(f"Python runtime source is not a directory: {source}")

    source_executable = find_python_executable(source)
    if source_executable is None:
        raise RuntimeError(f"Python executable not found under runtime source: {source}")

    target = release / PYTHON_RESOURCE_DIR
    target_executable = _target_executable(target, source_executable, source)
    if copy:
        _copy_runtime_tree(source, target)
        if not target_executable.is_file():
            raise RuntimeError(f"Staged Python executable is missing: {target_executable}")
        write_release_metadata(release)

    return PythonRuntimeStageResult(
        release_root=str(release),
        runtime_source=str(source),
        runtime_target=str(target),
        executable=str(target_executable),
        copied=copy,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage a provided Python runtime into a NAIA Electron release.")
    parser.add_argument("release_root", help="Staged NAIA release directory.")
    parser.add_argument("runtime_root", help="Python runtime folder to copy into resources/python.")
    parser.add_argument("--copy", action="store_true", help="Copy the runtime folder. Dry-run when omitted.")
    args = parser.parse_args(argv)

    payload = stage_python_runtime(args.release_root, args.runtime_root, copy=args.copy)
    json.dump(payload.__dict__, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
