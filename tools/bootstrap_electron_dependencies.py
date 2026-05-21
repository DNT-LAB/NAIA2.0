"""Plan or run the Electron dependency bootstrap for release packaging.

The default CLI mode is a dry run. Actual npm installation requires both
``--execute`` and ``--yes`` so this tool can be wired into package scripts
without accidental dependency changes.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any

try:
    from tools.check_electron_dependency_readiness import check_electron_dependency_readiness
except ModuleNotFoundError:  # pragma: no cover - used when executed as a script.
    from check_electron_dependency_readiness import check_electron_dependency_readiness


DEFAULT_ELECTRON_ROOT = Path("app/electron")
INSTALL_ARGS = ("install", "--include=dev", "--no-fund")
CI_ARGS = ("ci", "--include=dev", "--no-fund")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_output(payload: dict[str, Any], output: str | Path | None) -> None:
    if not output:
        return
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload["output"] = str(output_path.resolve())
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def summarize_electron_dependency_bootstrap(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a compact dependency-bootstrap summary without nested readiness payloads."""

    before = payload.get("before", {}) if isinstance(payload.get("before"), dict) else {}
    after = payload.get("after", {}) if isinstance(payload.get("after"), dict) else {}
    run = payload.get("run", {}) if isinstance(payload.get("run"), dict) else {}
    before_action = before.get("next_action", {}) if isinstance(before.get("next_action"), dict) else {}
    after_action = after.get("next_action", {}) if isinstance(after.get("next_action"), dict) else {}
    action_source = after_action if after_action else before_action
    return {
        "ok": bool(payload.get("ok")),
        "dry_run": bool(payload.get("dry_run")),
        "electron_root": str(payload.get("electron_root") or ""),
        "electron_package": str(payload.get("electron_package") or ""),
        "strategy": str(payload.get("strategy") or ""),
        "command": list(payload.get("command") or []),
        "requires_explicit_approval": bool(payload.get("requires_explicit_approval")),
        "mutation_targets": list(payload.get("mutation_targets") or []),
        "ready_before": bool(payload.get("ready_before")),
        "ready_after": bool(payload.get("ready_after")),
        "violation_count": len(payload.get("violations", [])),
        "warning_count": len(payload.get("warnings", [])),
        "before": {
            "ok": bool(before.get("ok")) if before else None,
            "violation_count": len(before.get("violations", [])) if before else 0,
            "next_action_required": bool(before_action.get("required")) if before_action else False,
            "next_action_strategy": str(before_action.get("strategy") or "") if before_action else "",
        },
        "after": {
            "ok": bool(after.get("ok")) if after else None,
            "violation_count": len(after.get("violations", [])) if after else 0,
            "next_action_required": bool(after_action.get("required")) if after_action else False,
            "next_action_strategy": str(after_action.get("strategy") or "") if after_action else "",
        },
        "next_action": {
            "required": bool(action_source.get("required")) if action_source else False,
            "requires_explicit_approval": bool(action_source.get("requires_explicit_approval")) if action_source else False,
            "script": str(action_source.get("script") or "") if action_source else "",
            "final_release_script": str(action_source.get("final_release_script") or "") if action_source else "",
            "strategy": str(action_source.get("strategy") or "") if action_source else "",
            "mutates": list(action_source.get("mutates") or []) if action_source else [],
        },
        "run": {
            "ok": bool(run.get("ok")) if run else None,
            "exit_code": run.get("exit_code") if run else None,
        },
    }


def _select_strategy(electron_root: Path, requested: str) -> str:
    if requested != "auto":
        return requested
    return "ci" if (electron_root / "package-lock.json").is_file() else "install"


def _package_pin_violations(package_path: Path) -> list[dict[str, str]]:
    if not package_path.is_file():
        return [{"path": str(package_path), "reason": "Electron package.json is missing"}]
    package = _read_json(package_path)
    dev_dependencies = package.get("devDependencies", {})
    violations: list[dict[str, str]] = []
    for dependency in ("electron", "electron-builder"):
        declared = str(dev_dependencies.get(dependency) or "")
        if not declared:
            violations.append({"path": str(package_path), "reason": f"devDependency is missing: {dependency}"})
        elif re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", declared) is None:
            violations.append({
                "path": str(package_path),
                "reason": f"devDependency must be pinned to an exact version before install: {dependency}",
            })
    return violations


def _ci_preflight_violations(electron_root: Path, readiness: dict[str, Any]) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    lock_path = electron_root / "package-lock.json"
    if not lock_path.is_file():
        violations.append({
            "path": str(lock_path),
            "reason": "npm ci requires package-lock.json; run the install bootstrap first to create it",
        })
    for item in readiness.get("violations", []):
        reason = str(item.get("reason", ""))
        if "lockfile version" in reason:
            violations.append({
                "path": str(item.get("path", lock_path)),
                "reason": f"npm ci blocked by lockfile drift: {reason}",
            })
    return violations


def bootstrap_electron_dependencies(
    *,
    electron_root: str | Path = DEFAULT_ELECTRON_ROOT,
    strategy: str = "auto",
    npm_command: str = "npm",
    dry_run: bool = True,
    yes: bool = False,
    output: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(electron_root).resolve()
    package_path = root / "package.json"
    selected_strategy = _select_strategy(root, strategy)
    npm_path = shutil.which(npm_command) or npm_command
    command = [npm_path, *(CI_ARGS if selected_strategy == "ci" else INSTALL_ARGS)]
    before = check_electron_dependency_readiness(electron_package_path=package_path)
    violations = _package_pin_violations(package_path)
    warnings: list[dict[str, str]] = []

    if selected_strategy == "ci":
        violations.extend(_ci_preflight_violations(root, before))
    if not dry_run and not yes:
        violations.append({
            "path": str(root),
            "reason": "dependency installation requires --yes with --execute",
        })
    if not dry_run and shutil.which(npm_command) is None:
        violations.append({
            "path": "PATH",
            "reason": f"npm command is not executable: {npm_command}",
        })
    elif shutil.which(npm_command) is None:
        warnings.append({
            "path": "PATH",
            "reason": f"npm command was not found during dry run: {npm_command}",
        })

    run_result: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    if not dry_run and not violations:
        completed = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        run_result = {
            "ok": completed.returncode == 0,
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
        if completed.returncode != 0:
            violations.append({
                "path": str(root),
                "reason": f"npm {selected_strategy} exited with {completed.returncode}",
            })
        after = check_electron_dependency_readiness(electron_package_path=package_path)
        if not after.get("ok"):
            for item in after.get("violations", []):
                violations.append({
                    "path": str(item.get("path", "")),
                    "reason": f"post-install readiness: {item.get('reason', '')}",
                })

    payload: dict[str, Any] = {
        "ok": not violations,
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "electron_root": str(root),
        "electron_package": str(package_path),
        "strategy": selected_strategy,
        "dry_run": bool(dry_run),
        "command": command,
        "requires_explicit_approval": bool(dry_run and not before.get("ok")),
        "mutation_targets": [
            str(root / "package-lock.json"),
            str(root / "node_modules"),
        ],
        "ready_before": bool(before.get("ok")),
        "ready_after": bool(after.get("ok")) if after is not None else bool(before.get("ok")),
        "before": before,
        "after": after,
        "run": run_result,
        "violations": violations,
        "warnings": warnings,
    }
    _write_output(payload, output)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plan or run Electron dependency bootstrap.")
    parser.add_argument("--electron-root", default=str(DEFAULT_ELECTRON_ROOT), help="Electron package root.")
    parser.add_argument("--strategy", choices=("auto", "install", "ci"), default="auto", help="Bootstrap strategy.")
    parser.add_argument("--npm", default="npm", help="npm executable name or path.")
    parser.add_argument("--execute", action="store_true", help="Run npm instead of producing a dry-run plan.")
    parser.add_argument("--yes", action="store_true", help="Required with --execute to allow dependency changes.")
    parser.add_argument("--output", default=None, help="Optional JSON evidence output path.")
    parser.add_argument("--summary", action="store_true", help="Print a compact dependency bootstrap summary.")
    args = parser.parse_args(argv)

    payload = bootstrap_electron_dependencies(
        electron_root=args.electron_root,
        strategy=args.strategy,
        npm_command=args.npm,
        dry_run=not args.execute,
        yes=args.yes,
        output=args.output,
    )
    if args.summary:
        payload = summarize_electron_dependency_bootstrap(payload)
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
