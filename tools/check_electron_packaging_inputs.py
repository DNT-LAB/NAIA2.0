"""Validate Electron packaging inputs before running electron-builder."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

try:
    from tools.check_clean_machine_readiness import check_clean_machine_readiness
except ModuleNotFoundError:  # pragma: no cover - used when executed as a script.
    from check_clean_machine_readiness import check_clean_machine_readiness


DEFAULT_ELECTRON_PACKAGE = Path("app/electron/package.json")
DEFAULT_STAGED_ROOT = Path("app/electron/dist/NAIA-Web")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_input(electron_root: Path, relative: str) -> Path:
    return (electron_root / relative).resolve()


def _check_entries(
    *,
    electron_root: Path,
    entries: list[dict[str, Any]],
    key: str,
    require_directory: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    checks: list[dict[str, Any]] = []
    violations: list[dict[str, str]] = []
    for index, entry in enumerate(entries):
        source = str(entry.get("from") or "")
        target = str(entry.get("to") or "")
        source_path = _resolve_input(electron_root, source)
        exists = source_path.exists()
        type_ok = source_path.is_dir() if require_directory else source_path.is_file()
        check = {
            "index": index,
            "from": source,
            "to": target,
            "resolved": str(source_path),
            "exists": exists,
            "type_ok": type_ok,
        }
        checks.append(check)
        if not source:
            violations.append({"path": f"build.{key}[{index}].from", "reason": "input source is empty"})
        elif not exists:
            violations.append({"path": source, "reason": f"electron-builder {key} input is missing"})
        elif not type_ok:
            expected = "directory" if require_directory else "file"
            violations.append({"path": source, "reason": f"electron-builder {key} input is not a {expected}"})
        if not target:
            violations.append({"path": f"build.{key}[{index}].to", "reason": "input target is empty"})
    return checks, violations


def check_electron_packaging_inputs(
    *,
    electron_package_path: str | Path = DEFAULT_ELECTRON_PACKAGE,
    staged_root: str | Path = DEFAULT_STAGED_ROOT,
    require_bundled_python: bool = False,
) -> dict[str, Any]:
    package_path = Path(electron_package_path).resolve()
    electron_root = package_path.parent
    staged = Path(staged_root).resolve()
    violations: list[dict[str, str]] = []

    if not package_path.is_file():
        return {
            "ok": False,
            "electron_package": str(package_path),
            "violations": [{"path": str(package_path), "reason": "Electron package.json is missing"}],
        }

    package = _load_json(package_path)
    build = package.get("build", {})
    extra_resources = build.get("extraResources", [])
    extra_files = build.get("extraFiles", [])
    resource_checks, resource_violations = _check_entries(
        electron_root=electron_root,
        entries=extra_resources,
        key="extraResources",
        require_directory=True,
    )
    file_checks, file_violations = _check_entries(
        electron_root=electron_root,
        entries=extra_files,
        key="extraFiles",
        require_directory=False,
    )
    violations.extend(resource_violations)
    violations.extend(file_violations)

    if not staged.is_dir():
        staged_readiness = {
            "ok": False,
            "artifact_root": str(staged),
            "violations": [{"path": str(staged), "reason": "staged release root is missing"}],
        }
    else:
        staged_readiness = check_clean_machine_readiness(
            staged,
            kind="staged-release",
            require_bundled_python=require_bundled_python,
        )
    for item in staged_readiness.get("violations", []):
        violations.append({
            "path": str(item.get("path", "")),
            "reason": f"staged-readiness: {item.get('reason', '')}",
        })

    return {
        "ok": not violations,
        "electron_package": str(package_path),
        "electron_root": str(electron_root),
        "staged_root": str(staged),
        "require_bundled_python": bool(require_bundled_python),
        "resource_checks": resource_checks,
        "file_checks": file_checks,
        "staged_readiness": staged_readiness,
        "violations": violations,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate inputs consumed by electron-builder.")
    parser.add_argument("--electron-package", default=str(DEFAULT_ELECTRON_PACKAGE), help="Electron package.json path.")
    parser.add_argument("--staged-root", default=str(DEFAULT_STAGED_ROOT), help="Staged NAIA-Web root.")
    parser.add_argument("--require-bundled-python", action="store_true", help="Fail unless staged resources/python exists.")
    args = parser.parse_args(argv)

    payload = check_electron_packaging_inputs(
        electron_package_path=args.electron_package,
        staged_root=args.staged_root,
        require_bundled_python=args.require_bundled_python,
    )
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
