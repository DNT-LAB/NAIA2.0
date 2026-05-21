"""Validate the NAIA backend runtime packaging strategy manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_STRATEGY = Path("release_assets/manifests/backend_runtime_strategy.json")
DEFAULT_ELECTRON_MAIN = Path("app/electron/main/main.cjs")


def load_strategy(path: str | Path = DEFAULT_STRATEGY) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def check_backend_runtime_strategy(
    strategy_path: str | Path = DEFAULT_STRATEGY,
    *,
    electron_main_path: str | Path = DEFAULT_ELECTRON_MAIN,
) -> dict[str, Any]:
    strategy = load_strategy(strategy_path)
    candidates = strategy.get("candidate_summary", {})
    rules = "\n".join(strategy.get("hard_rules", []))
    selected = strategy.get("selected_first_milestone")
    violations: list[str] = []

    if selected != "python-runtime-folder":
        violations.append("selected_first_milestone must remain python-runtime-folder until binary measurements exist")
    if candidates.get("pyinstaller-onefile", {}).get("allowed") is not False:
        violations.append("pyinstaller-onefile must be explicitly blocked for the first milestone")
    if "UPX must not be used" not in rules:
        violations.append("hard rules must explicitly ban UPX")
    if "non-PyInstaller backend runtime path" not in rules:
        violations.append("hard rules must preserve a non-PyInstaller runtime path")
    if not strategy.get("scanner_policy", {}).get("submission_notes_required"):
        violations.append("scanner policy must require submission notes")
    if "scanner_result_notes" not in strategy.get("required_measurements", []):
        violations.append("required measurements must include scanner_result_notes")
    python_runtime = candidates.get("python-runtime-folder", {})
    if python_runtime.get("staging_tool") != "tools/stage_python_runtime.py":
        violations.append("python-runtime-folder must declare tools/stage_python_runtime.py as its staging tool")
    if python_runtime.get("runtime_builder") != "tools/build_python_runtime_from_venv.py --base-only --python-version 3.12":
        violations.append("python-runtime-folder must declare the Python 3.12 base-only runtime builder")
    if "--require-bundled-python" not in str(python_runtime.get("preflight_gate", "")):
        violations.append("python-runtime-folder must declare a bundled-python preflight gate")

    main_text = Path(electron_main_path).read_text(encoding="utf-8")
    required_electron_terms = [
        "resourcesRoot()",
        "resources",
        "python.exe",
        "NAIA_web_headless.exe",
        "NAIA_web_headless.py",
        "NAIA_USER_DATA_DIR",
        "NAIA_RESOURCE_ROOT",
        "NAIA_REMOTE_WEB_DIR",
    ]
    for term in required_electron_terms:
        if term not in main_text:
            violations.append(f"Electron main process does not expose runtime contract term: {term}")

    return {
        "ok": not violations,
        "strategy": str(Path(strategy_path)),
        "electron_main": str(Path(electron_main_path)),
        "selected_first_milestone": selected,
        "violations": violations,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate NAIA backend runtime packaging strategy.")
    parser.add_argument("--strategy", default=str(DEFAULT_STRATEGY), help="Backend runtime strategy manifest.")
    parser.add_argument("--electron-main", default=str(DEFAULT_ELECTRON_MAIN), help="Electron main process file.")
    args = parser.parse_args(argv)

    payload = check_backend_runtime_strategy(args.strategy, electron_main_path=args.electron_main)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
