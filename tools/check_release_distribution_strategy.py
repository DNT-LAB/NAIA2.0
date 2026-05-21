"""Validate the NAIA release distribution strategy manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


DEFAULT_STRATEGY = Path("release_assets/manifests/release_distribution_strategy.json")
DEFAULT_ELECTRON_PACKAGE = Path("app/electron/package.json")


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def check_release_distribution_strategy(
    strategy_path: str | Path = DEFAULT_STRATEGY,
    *,
    electron_package_path: str | Path = DEFAULT_ELECTRON_PACKAGE,
) -> dict[str, Any]:
    strategy_file = Path(strategy_path)
    package_file = Path(electron_package_path)
    strategy = _load_json(strategy_file)
    package = _load_json(package_file)
    violations: list[dict[str, str]] = []

    if strategy.get("first_release_artifact") != "portable-app-folder":
        violations.append({
            "path": str(strategy_file),
            "reason": "first release artifact must remain portable-app-folder until packaged app and clean-machine gates pass",
        })

    portable = strategy.get("portable_strategy", {})
    required_release_gates = set(portable.get("requires_before_public_release", []))
    for required in {
        "real Electron package build",
        "packaged-app smoke test",
        "clean-machine readiness gate",
        "clean Windows machine launch test",
        "release artifact measurement",
        "Microsoft Defender local scan",
        "signed public artifact",
    }:
        if required not in required_release_gates:
            violations.append({"path": str(strategy_file), "reason": f"portable release gate missing: {required}"})

    candidates = strategy.get("installer_strategy", {}).get("candidates", {})
    for candidate in ("electron-builder-nsis", "electron-builder-msix", "inno-setup-wrapper"):
        if candidate not in candidates:
            violations.append({"path": str(strategy_file), "reason": f"installer candidate missing: {candidate}"})

    state_policy = strategy.get("user_state_policy", {})
    if state_policy.get("upgrade") != "preserve_user_data":
        violations.append({"path": str(strategy_file), "reason": "upgrade policy must preserve user data"})
    if state_policy.get("uninstall") != "do_not_delete_user_data_by_default":
        violations.append({"path": str(strategy_file), "reason": "uninstall policy must not delete user data by default"})
    if state_policy.get("delete_user_data") != "explicit_user_choice_only":
        violations.append({"path": str(strategy_file), "reason": "user data deletion must require explicit user choice"})
    forbidden = " ".join(str(item) for item in state_policy.get("forbidden", []))
    for term in ("user-data", "%APPDATA%/NAIA", "bundled resources"):
        if term not in forbidden:
            violations.append({"path": str(strategy_file), "reason": f"state policy forbidden list must mention {term}"})

    auto_update = strategy.get("auto_update", {})
    if auto_update.get("status") != "deferred":
        violations.append({"path": str(strategy_file), "reason": "auto-update must remain deferred until signed release artifacts exist"})
    allowed_after = set(auto_update.get("allowed_after", []))
    if "signed release artifacts exist" not in allowed_after:
        violations.append({"path": str(strategy_file), "reason": "auto-update gate must require signed release artifacts"})

    electron_contract = strategy.get("electron_builder_contract", {})
    if electron_contract.get("first_target") != "dir":
        violations.append({"path": str(strategy_file), "reason": "first electron-builder target must be dir"})

    scripts = package.get("scripts", {})
    for script in electron_contract.get("package_scripts", []):
        if script not in scripts:
            violations.append({"path": str(package_file), "reason": f"electron package script missing: {script}"})
    for script, required_terms in dict(electron_contract.get("required_script_terms", {})).items():
        script_command = str(scripts.get(script, ""))
        if not script_command:
            violations.append({"path": str(package_file), "reason": f"electron package script missing: {script}"})
            continue
        last_index = -1
        for term in required_terms:
            term_text = str(term)
            index = script_command.find(term_text)
            if index < 0:
                violations.append({
                    "path": str(package_file),
                    "reason": f"electron package script {script} must include {term_text}",
                })
                continue
            if index < last_index:
                violations.append({
                    "path": str(package_file),
                    "reason": f"electron package script {script} must keep required term order: {term_text}",
                })
            last_index = max(last_index, index)

    approval_boundary = strategy.get("approval_boundary", {})
    non_mutating_scripts = dict(approval_boundary.get("non_mutating_scripts", {}))
    for script, forbidden_terms in non_mutating_scripts.items():
        script_command = str(scripts.get(script, ""))
        if not script_command:
            violations.append({"path": str(package_file), "reason": f"non-mutating electron package script missing: {script}"})
            continue
        for term in forbidden_terms:
            term_text = str(term)
            if term_text and term_text in script_command:
                violations.append({
                    "path": str(package_file),
                    "reason": f"non-mutating electron package script {script} must not include {term_text}",
                })

    win_target = package.get("build", {}).get("win", {}).get("target")
    if win_target != "dir":
        violations.append({"path": str(package_file), "reason": "electron-builder win target must remain dir for portable-first release"})
    win_config = dict(package.get("build", {}).get("win", {}) or {})
    if win_config.get("signAndEditExecutable") is not False:
        violations.append({
            "path": str(package_file),
            "reason": "portable-first unsigned release must set win.signAndEditExecutable=false; NAIA.exe icon is applied by the release icon post-step",
        })
    if win_config.get("forceCodeSigning") is not False:
        violations.append({
            "path": str(package_file),
            "reason": "portable-first unsigned release must set win.forceCodeSigning=false",
        })

    return {
        "ok": not violations,
        "strategy": str(strategy_file),
        "electron_package": str(package_file),
        "first_release_artifact": strategy.get("first_release_artifact"),
        "installer_candidate_count": len(candidates),
        "auto_update_status": auto_update.get("status"),
        "script_term_rule_count": len(electron_contract.get("required_script_terms", {})),
        "non_mutating_script_rule_count": len(non_mutating_scripts),
        "violations": violations,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate NAIA release distribution strategy.")
    parser.add_argument("--strategy", default=str(DEFAULT_STRATEGY), help="Distribution strategy manifest.")
    parser.add_argument("--electron-package", default=str(DEFAULT_ELECTRON_PACKAGE), help="Electron package manifest.")
    args = parser.parse_args(argv)

    payload = check_release_distribution_strategy(args.strategy, electron_package_path=args.electron_package)
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
