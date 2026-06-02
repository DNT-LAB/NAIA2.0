"""Build and stage the bundled Grok (progrok) runtime into a NAIA Electron release.

This mirrors ``tools/stage_python_runtime.py`` but for the optional Grok (xAI)
integration. The runtime is NOT committed as node_modules; instead it is built at
release time with ``npm ci`` from the committed ``app/electron/grok-runtime``
manifest (package.json + package-lock.json + the vendored progrok tarball), then
copied to ``resources/progrok-runtime`` so the packaged Electron main can spawn it
(``resources/progrok-runtime/{grok-launch.cjs, node_modules/progrok/dist/index.js}``).

Removable: delete ``app/electron/grok-runtime`` + this tool's call site in
``run_release_workspace`` + the Grok block in ``app/electron/main/main.cjs``.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

try:
    from tools.write_release_metadata import write_release_metadata
except ModuleNotFoundError:  # pragma: no cover - used when executed as a script.
    from write_release_metadata import write_release_metadata


GROK_RESOURCE_DIR = Path("resources") / "progrok-runtime"
PROGROK_ENTRY = Path("node_modules") / "progrok" / "dist" / "index.js"


@dataclass(frozen=True)
class GrokRuntimeStageResult:
    release_root: str
    runtime_source: str
    runtime_target: str
    entry: str
    package_count: int
    copied: bool


def _npm_command() -> str:
    found = shutil.which("npm.cmd") or shutil.which("npm")
    if found:
        return found
    return "npm.cmd" if os.name == "nt" else "npm"


def _build_node_modules(source: Path, build_dir: Path) -> None:
    """npm ci from the committed manifest into an isolated build dir (no source mutation)."""
    for name in ("package.json", "package-lock.json"):
        src = source / name
        if not src.is_file():
            raise RuntimeError(f"Grok runtime manifest is missing: {src}")
        shutil.copy2(src, build_dir / name)
    vendor = source / "vendor"
    if vendor.is_dir():
        shutil.copytree(vendor, build_dir / "vendor")
    completed = subprocess.run(
        [_npm_command(), "ci", "--omit=dev", "--no-audit", "--no-fund"],
        cwd=build_dir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "npm ci failed for the Grok runtime "
            f"(exit {completed.returncode}): {(completed.stderr or completed.stdout or '').strip()[:500]}"
        )
    entry = build_dir / PROGROK_ENTRY
    if not entry.is_file():
        raise RuntimeError(f"Grok runtime entry was not produced: {entry}")


def stage_grok_runtime(
    release_root: str | Path,
    runtime_source: str | Path,
    *,
    copy: bool = False,
) -> GrokRuntimeStageResult:
    release = Path(release_root).resolve()
    source = Path(runtime_source).resolve()
    if not release.is_dir():
        raise RuntimeError(f"Release root is not a directory: {release}")
    if not source.is_dir():
        raise RuntimeError(f"Grok runtime source is not a directory: {source}")
    launcher = source / "grok-launch.cjs"
    if not launcher.is_file():
        raise RuntimeError(f"Grok launcher is missing: {launcher}")

    target = release / GROK_RESOURCE_DIR
    target_entry = target / PROGROK_ENTRY
    package_count = 0
    if copy:
        if target.exists() and any(target.iterdir()):
            raise RuntimeError(f"Grok runtime target is not empty: {target}")
        with tempfile.TemporaryDirectory(prefix="naia-grok-build-") as tmp:
            build_dir = Path(tmp)
            _build_node_modules(source, build_dir)
            built_modules = build_dir / "node_modules"
            package_count = sum(1 for _ in built_modules.glob("*")) if built_modules.is_dir() else 0
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(launcher, target / "grok-launch.cjs")
            shutil.copytree(built_modules, target / "node_modules", symlinks=True)
        if not target_entry.is_file():
            raise RuntimeError(f"Staged Grok runtime entry is missing: {target_entry}")
        write_release_metadata(release)

    return GrokRuntimeStageResult(
        release_root=str(release),
        runtime_source=str(source),
        runtime_target=str(target),
        entry=str(target_entry),
        package_count=package_count,
        copied=copy,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and stage the Grok (progrok) runtime into a NAIA release.")
    parser.add_argument("release_root", help="Staged NAIA release directory.")
    parser.add_argument("runtime_source", help="Source app/electron/grok-runtime directory.")
    parser.add_argument("--copy", action="store_true", help="Build and copy the runtime. Dry-run when omitted.")
    args = parser.parse_args(argv)

    payload = stage_grok_runtime(args.release_root, args.runtime_source, copy=args.copy)
    json.dump(payload.__dict__, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
