"""Validate local Electron dependency readiness before packaging."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import sys
from typing import Any


DEFAULT_ELECTRON_PACKAGE = Path("app/electron/package.json")
REQUIRED_DEV_DEPENDENCIES = ("electron", "electron-builder")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _is_exact_version(version: str) -> bool:
    return re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", version) is not None


def _bin_exists(electron_root: Path, name: str) -> bool:
    bin_dir = electron_root / "node_modules" / ".bin"
    return any((bin_dir / candidate).is_file() for candidate in (name, f"{name}.cmd", f"{name}.ps1"))


def _lock_dependency_version(lock: dict[str, Any], package_name: str) -> str | None:
    packages = lock.get("packages", {})
    entry = packages.get(f"node_modules/{package_name}")
    if isinstance(entry, dict) and entry.get("version"):
        return str(entry["version"])
    dependencies = lock.get("dependencies", {})
    entry = dependencies.get(package_name)
    if isinstance(entry, dict) and entry.get("version"):
        return str(entry["version"])
    return None


def _dependency_bootstrap_action(electron_root: Path, *, ready: bool) -> dict[str, Any]:
    has_lock = (electron_root / "package-lock.json").is_file()
    script = "deps:ci" if has_lock else "deps:install"
    return {
        "required": not ready,
        "requires_explicit_approval": not ready,
        "script": f"npm --prefix {electron_root} run {script}",
        "strategy": "ci" if has_lock else "install",
        "mutates": [
            str(electron_root / "package-lock.json"),
            str(electron_root / "node_modules"),
        ],
        "final_release_script": f"npm --prefix {electron_root} run release:final:install:scan",
    }


def summarize_electron_dependency_readiness(payload: dict[str, Any]) -> dict[str, Any]:
    """Return compact Electron dependency readiness without nested package metadata."""

    checks = payload.get("dependency_checks", {}) if isinstance(payload.get("dependency_checks"), dict) else {}
    next_action = payload.get("next_action", {}) if isinstance(payload.get("next_action"), dict) else {}
    dependencies: dict[str, dict[str, Any]] = {}
    for dependency in REQUIRED_DEV_DEPENDENCIES:
        check = checks.get(dependency, {}) if isinstance(checks.get(dependency), dict) else {}
        dependencies[dependency] = {
            "declared": str(check.get("declared") or ""),
            "declared_exact": bool(check.get("declared_exact")),
            "lock_version": str(check.get("lock_version") or ""),
            "installed_version": str(check.get("installed_version") or ""),
            "installed": bool(check.get("installed")),
            "bin_ready": bool(check.get("bin_ready")),
        }
    return {
        "ok": bool(payload.get("ok")),
        "electron_package": str(payload.get("electron_package") or ""),
        "electron_root": str(payload.get("electron_root") or ""),
        "package_lock": str(payload.get("package_lock") or ""),
        "node_ready": bool(payload.get("node_command")),
        "npm_ready": bool(payload.get("npm_command")),
        "violation_count": len(payload.get("violations", [])),
        "warning_count": len(payload.get("warnings", [])),
        "dependencies": dependencies,
        "next_action": {
            "required": bool(next_action.get("required")),
            "requires_explicit_approval": bool(next_action.get("requires_explicit_approval")),
            "script": str(next_action.get("script") or ""),
            "final_release_script": str(next_action.get("final_release_script") or ""),
            "strategy": str(next_action.get("strategy") or ""),
            "mutates": list(next_action.get("mutates") or []),
        },
    }


def check_electron_dependency_readiness(
    *,
    electron_package_path: str | Path = DEFAULT_ELECTRON_PACKAGE,
) -> dict[str, Any]:
    package_path = Path(electron_package_path).resolve()
    electron_root = package_path.parent
    violations: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    if not package_path.is_file():
        return {
            "ok": False,
            "electron_package": str(package_path),
            "violations": [{"path": str(package_path), "reason": "Electron package.json is missing"}],
            "warnings": warnings,
        }

    package = _read_json(package_path)
    dev_dependencies = package.get("devDependencies", {})
    dependency_checks: dict[str, dict[str, Any]] = {}

    lock_path = electron_root / "package-lock.json"
    lock_payload: dict[str, Any] | None = _read_json(lock_path) if lock_path.is_file() else None
    if lock_payload is None:
        violations.append({
            "path": str(lock_path),
            "reason": "package-lock.json is required for reproducible Electron dependency installation",
        })

    for dependency in REQUIRED_DEV_DEPENDENCIES:
        declared = str(dev_dependencies.get(dependency) or "")
        installed_package = electron_root / "node_modules" / dependency / "package.json"
        installed_version = ""
        if installed_package.is_file():
            try:
                installed_version = str(_read_json(installed_package).get("version") or "")
            except Exception:
                installed_version = ""
        lock_version = _lock_dependency_version(lock_payload, dependency) if lock_payload else None
        bin_name = dependency
        bin_ready = _bin_exists(electron_root, bin_name)
        check = {
            "declared": declared,
            "declared_exact": _is_exact_version(declared),
            "lock_version": lock_version or "",
            "installed_package": str(installed_package),
            "installed_version": installed_version,
            "installed": installed_package.is_file(),
            "bin_ready": bin_ready,
        }
        dependency_checks[dependency] = check

        if not declared:
            violations.append({"path": str(package_path), "reason": f"devDependency is missing: {dependency}"})
            continue
        if not _is_exact_version(declared):
            violations.append({"path": str(package_path), "reason": f"devDependency must be pinned to an exact version: {dependency}"})
        if lock_payload is not None and lock_version != declared:
            violations.append({
                "path": str(lock_path),
                "reason": f"lockfile version for {dependency} does not match package.json ({lock_version or 'missing'} != {declared})",
            })
        if not installed_package.is_file():
            violations.append({"path": str(installed_package), "reason": f"installed dependency is missing: {dependency}"})
        elif installed_version != declared:
            violations.append({
                "path": str(installed_package),
                "reason": f"installed version for {dependency} does not match package.json ({installed_version or 'unknown'} != {declared})",
            })
        if not bin_ready:
            violations.append({"path": str(electron_root / "node_modules" / ".bin"), "reason": f"dependency binary is missing: {bin_name}"})

    node_command = shutil.which("node")
    npm_command = shutil.which("npm")
    if node_command is None:
        warnings.append({"path": "PATH", "reason": "node executable was not found on PATH"})
    if npm_command is None:
        warnings.append({"path": "PATH", "reason": "npm executable was not found on PATH"})

    ok = not violations
    return {
        "ok": ok,
        "electron_package": str(package_path),
        "electron_root": str(electron_root),
        "package_lock": str(lock_path),
        "node_command": node_command or "",
        "npm_command": npm_command or "",
        "dependency_checks": dependency_checks,
        "next_action": _dependency_bootstrap_action(electron_root, ready=ok),
        "violations": violations,
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Electron dependency installation readiness.")
    parser.add_argument("--electron-package", default=str(DEFAULT_ELECTRON_PACKAGE), help="Electron package.json path.")
    parser.add_argument("--summary", action="store_true", help="Print a compact dependency readiness summary.")
    args = parser.parse_args(argv)

    payload = check_electron_dependency_readiness(electron_package_path=args.electron_package)
    if args.summary:
        payload = summarize_electron_dependency_readiness(payload)
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
