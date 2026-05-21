"""Validate packaged Electron feature-smoke coverage.

This is a planning/contract gate, not a substitute for the real Electron smoke.
It makes sure every user-visible feature named in the final roadmap has a
mapped Remote Web route, websocket command, or CDP check before packaged app
validation is considered complete.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

try:
    from tools.check_remote_web_feature_contract import load_contract
except ModuleNotFoundError:  # pragma: no cover - used when executed as a script.
    from check_remote_web_feature_contract import load_contract


DEFAULT_MANIFEST = Path("release_assets/manifests/packaged_electron_feature_smoke.json")
DEFAULT_ELECTRON_PACKAGE = Path("app/electron/package.json")

REQUIRED_FEATURE_IDS = {
    "random_prompt",
    "generate",
    "result_display",
    "prompt_tools",
    "params",
    "presets",
    "danbooru",
    "artist_thumbnail",
    "img2img",
    "vibe_transfer_storage",
    "character_reference",
    "enhance",
    "setup_api_settings",
    "history",
    "save_output",
}

REQUIRED_CDP_TERMS = {
    "shell_ready": "shell_ready_s",
    "timings": "timings",
    "download_routing": "under_runtime_downloads",
    "backend_restart": "backendRestart",
    "storage": "localStoragePersistsAfterReload",
    "feature_workflows": "featureWorkflows",
    "all_required_features": "allRequiredFeaturesObserved",
    "performance_metrics": "firstPaintProxyMs",
    "random_prompt_roundtrip": "randomPromptRoundTrip",
}


def _read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _contract_index(contract: dict[str, Any]) -> tuple[set[str], set[tuple[str, str]], set[str]]:
    groups: set[str] = set()
    routes: set[tuple[str, str]] = set()
    commands: set[str] = set()
    for feature in contract.get("feature_groups", []):
        groups.add(str(feature.get("id")))
        for route in feature.get("routes", []):
            routes.add((str(route.get("method", "")).upper(), str(route.get("path", ""))))
        for command in feature.get("websocket_commands", []):
            commands.add(str(command))
    return groups, routes, commands


def check_packaged_electron_feature_smoke(
    manifest_path: str | Path = DEFAULT_MANIFEST,
    *,
    electron_package_path: str | Path = DEFAULT_ELECTRON_PACKAGE,
) -> dict[str, Any]:
    manifest_file = Path(manifest_path)
    manifest = _read_json(manifest_file)
    electron_package_file = Path(electron_package_path)
    electron_package = _read_json(electron_package_file)
    remote_contract_file = Path(manifest.get("remote_feature_contract", ""))
    remote_contract = load_contract(remote_contract_file)
    feature_groups, contract_routes, websocket_commands = _contract_index(remote_contract)
    package_scripts = electron_package.get("scripts", {})

    violations: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    features = manifest.get("required_features", [])
    feature_ids = {str(feature.get("id")) for feature in features}

    for required in sorted(REQUIRED_FEATURE_IDS - feature_ids):
        violations.append({
            "path": str(manifest_file),
            "reason": f"required packaged feature smoke mapping missing: {required}",
        })
    for extra in sorted(feature_ids - REQUIRED_FEATURE_IDS):
        warnings.append({
            "path": str(manifest_file),
            "reason": f"extra packaged feature smoke mapping is not in the required list: {extra}",
        })

    for script in manifest.get("package_scripts", []):
        if script not in package_scripts:
            violations.append({
                "path": str(electron_package_file),
                "reason": f"package script missing for packaged feature smoke: {script}",
            })

    cdp_tool = Path(str(manifest.get("cdp_smoke_tool", "")))
    cdp_source = cdp_tool.read_text(encoding="utf-8") if cdp_tool.is_file() else ""
    if not cdp_tool.is_file():
        violations.append({"path": str(cdp_tool), "reason": "CDP smoke tool is missing"})
    for proof_id, term in REQUIRED_CDP_TERMS.items():
        if term not in cdp_source:
            violations.append({"path": str(cdp_tool), "reason": f"CDP smoke proof term missing for {proof_id}: {term}"})

    for feature in features:
        feature_id = str(feature.get("id") or "<missing>")
        proof_count = 0
        for group in feature.get("feature_groups", []):
            proof_count += 1
            if group not in feature_groups:
                violations.append({
                    "feature": feature_id,
                    "path": str(remote_contract_file),
                    "reason": f"referenced feature group is absent from remote contract: {group}",
                })
        for route in feature.get("routes", []):
            proof_count += 1
            key = (str(route.get("method", "")).upper(), str(route.get("path", "")))
            if key not in contract_routes:
                violations.append({
                    "feature": feature_id,
                    "path": str(remote_contract_file),
                    "reason": f"referenced route is absent from remote contract: {key[0]} {key[1]}",
                })
        for command in feature.get("websocket_commands", []):
            proof_count += 1
            if command not in websocket_commands:
                violations.append({
                    "feature": feature_id,
                    "path": str(remote_contract_file),
                    "reason": f"referenced websocket command is absent from remote contract: {command}",
                })
        for check in feature.get("cdp_checks", []):
            proof_count += 1
            if check not in REQUIRED_CDP_TERMS:
                warnings.append({
                    "feature": feature_id,
                    "path": str(manifest_file),
                    "reason": f"CDP check is not part of the standard proof set: {check}",
                })
        if proof_count == 0:
            violations.append({
                "feature": feature_id,
                "path": str(manifest_file),
                "reason": "feature smoke mapping has no route, websocket command, feature group, or CDP proof",
            })
        if feature.get("requires_live_runtime") is not True and feature_id in {
            "random_prompt",
            "generate",
            "danbooru",
            "artist_thumbnail",
            "img2img",
            "vibe_transfer_storage",
            "character_reference",
            "enhance",
            "history",
            "save_output",
        }:
            warnings.append({
                "feature": feature_id,
                "path": str(manifest_file),
                "reason": "feature likely needs live packaged runtime validation but is not marked requires_live_runtime",
            })

    return {
        "ok": not violations,
        "manifest": str(manifest_file),
        "remote_feature_contract": str(remote_contract_file),
        "electron_package": str(electron_package_file),
        "required_feature_count": len(REQUIRED_FEATURE_IDS),
        "mapped_feature_count": len(features),
        "contract_feature_count": len(feature_groups),
        "contract_route_count": len(contract_routes),
        "websocket_command_count": len(websocket_commands),
        "violations": violations,
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate packaged Electron feature-smoke coverage.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="Packaged Electron feature smoke manifest.")
    parser.add_argument("--electron-package", default=str(DEFAULT_ELECTRON_PACKAGE), help="Electron package.json path.")
    args = parser.parse_args(argv)

    payload = check_packaged_electron_feature_smoke(args.manifest, electron_package_path=args.electron_package)
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
