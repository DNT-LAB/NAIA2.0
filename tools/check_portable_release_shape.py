"""Validate that Electron portable release outputs expose NAIA-Portable."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


DEFAULT_MANIFEST = Path("release_assets/manifests/portable_release_shape.json")
DEFAULT_PACKAGE = Path("app/electron/package.json")
DEFAULT_RUNNER = Path("tools/run_electron_portable_workspace.py")
DEFAULT_SMOKE = Path("tools/smoke_packaged_electron_app.py")


def _read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _read_text(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def _as_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def check_portable_release_shape(
    manifest_path: str | Path = DEFAULT_MANIFEST,
    *,
    electron_package_path: str | Path = DEFAULT_PACKAGE,
    runner_path: str | Path = DEFAULT_RUNNER,
    smoke_path: str | Path = DEFAULT_SMOKE,
) -> dict[str, Any]:
    manifest_file = Path(manifest_path)
    package_file = Path(electron_package_path)
    runner_file = Path(runner_path)
    smoke_file = Path(smoke_path)
    manifest = _read_json(manifest_file)
    package = _read_json(package_file)
    runner = _read_text(runner_file)
    smoke = _read_text(smoke_file)
    scripts = dict(package.get("scripts") or {})
    workspace_contract = dict(manifest.get("workspace_contract") or {})
    violations: list[dict[str, str]] = []

    if workspace_contract.get("portable_root_name") != "NAIA-Portable":
        violations.append({
            "path": str(manifest_file),
            "reason": "portable root name must remain NAIA-Portable",
        })
    if workspace_contract.get("packaged_root_source") != "portable_release_root":
        violations.append({
            "path": str(manifest_file),
            "reason": "packaged root must resolve to portable_release_root, not electron-builder win-unpacked",
        })

    for term in _as_list(manifest.get("required_runner_terms")):
        if term not in runner:
            violations.append({"path": str(runner_file), "reason": f"portable runner term missing: {term}"})
    for term in _as_list(manifest.get("required_smoke_terms")):
        if term not in smoke:
            violations.append({"path": str(smoke_file), "reason": f"packaged smoke term missing: {term}"})

    for script in _as_list(manifest.get("required_package_scripts")):
        command = str(scripts.get(script) or "")
        if not command:
            violations.append({"path": str(package_file), "reason": f"electron package script missing: {script}"})
            continue
        uses_portable_runner = (
            "run_electron_portable_workspace.py" in command
            or "npm run release:portable:workspace" in command
        )
        if script.startswith("release:portable") and not uses_portable_runner:
            violations.append({
                "path": str(package_file),
                "reason": f"electron package script {script} must route through run_electron_portable_workspace.py",
            })

    release_check = str(scripts.get(str(manifest.get("release_check_script") or "release:check")) or "")
    required_release_check_term = str(manifest.get("release_check_required_term") or "")
    if required_release_check_term and required_release_check_term not in release_check:
        violations.append({
            "path": str(package_file),
            "reason": f"release:check must include {required_release_check_term}",
        })

    direct_release_scripts = [
        script
        for script, command in scripts.items()
        if script.startswith("release:portable") and "electron-builder" in str(command)
    ]
    for script in direct_release_scripts:
        violations.append({
            "path": str(package_file),
            "reason": f"release-facing portable script must not call electron-builder directly: {script}",
        })

    return {
        "ok": not violations,
        "manifest": str(manifest_file),
        "electron_package": str(package_file),
        "runner": str(runner_file),
        "smoke": str(smoke_file),
        "portable_root_name": workspace_contract.get("portable_root_name"),
        "internal_builder_root": workspace_contract.get("internal_builder_root"),
        "required_user_visible_entries": _as_list(workspace_contract.get("required_user_visible_entries")),
        "required_package_script_count": len(_as_list(manifest.get("required_package_scripts"))),
        "violations": violations,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the Electron portable release folder shape contract.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="Portable release shape manifest.")
    parser.add_argument("--electron-package", default=str(DEFAULT_PACKAGE), help="Electron package manifest.")
    parser.add_argument("--runner", default=str(DEFAULT_RUNNER), help="Portable workspace runner source.")
    parser.add_argument("--smoke", default=str(DEFAULT_SMOKE), help="Packaged app smoke source.")
    args = parser.parse_args(argv)

    payload = check_portable_release_shape(
        args.manifest,
        electron_package_path=args.electron_package,
        runner_path=args.runner,
        smoke_path=args.smoke,
    )
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
