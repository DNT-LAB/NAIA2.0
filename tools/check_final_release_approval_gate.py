"""Validate the final Electron release approval boundary.

This checker is intentionally non-mutating. It does not install Electron
dependencies or build the packaged app. Its job is to make sure the pre-release
state is either fully release-ready or clearly blocked on explicit approval for
the dependency/build/scan path.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

try:
    from tools.audit_final_goal_completion import audit_final_goal_completion
except ModuleNotFoundError:  # pragma: no cover - used when executed as a script.
    from audit_final_goal_completion import audit_final_goal_completion


DEFAULT_PLAN = Path("refactor_plans/final_headless_electron_release_reorganization_plan.md")
DEFAULT_APPROVAL_DOC = Path("refactor_docs/round_final_release_approval_gate.md")
DEFAULT_ELECTRON_PACKAGE = Path("app/electron/package.json")
FINAL_SCRIPT = "release:final:install:scan"
FINAL_SCRIPT_TERMS = (
    "--execute",
    "--install-deps",
    "--yes",
    "--run-electron-cdp",
    "--electron-timeout",
    "180",
    "--defender-scan",
    "--require-defender-scan",
)
DOC_TERMS = (
    "Final Release Approval Gate",
    "blocked_on_approval=true",
    "release:final:install:scan",
    "app/electron/package-lock.json",
    "app/electron/node_modules",
    "app/electron/dist",
    "app/electron/dist/win-unpacked",
    "Defender",
)
ALLOWED_PREAPPROVAL_BLOCKER_TYPES = {
    "unchecked-plan-item",
    "unmet-when-done-condition",
    "missing-runtime-evidence",
}
ALLOWED_PREAPPROVAL_ROUNDS = {
    "Round 7 - Electron Shell Prototype",
    "Round 8 - Backend Packaging and Antivirus Risk Gate",
    "Round 9 - Packaged App Integration",
    "Round 10 - Clean-Machine Release Gate and Optional Installer",
    "",
}


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _ordered_terms_present(command: str, terms: tuple[str, ...]) -> list[str]:
    violations: list[str] = []
    last_index = -1
    for term in terms:
        index = command.find(term)
        if index < 0:
            violations.append(f"missing {term}")
            continue
        if index < last_index:
            violations.append(f"out of order {term}")
        last_index = max(last_index, index)
    return violations


def _action_mutations(actions: list[dict[str, Any]]) -> list[str]:
    mutations: list[str] = []
    for action in actions:
        mutations.extend(str(item).replace("\\", "/") for item in action.get("mutates", []))
    return mutations


def check_final_release_approval_gate(
    *,
    plan_path: str | Path = DEFAULT_PLAN,
    approval_doc_path: str | Path = DEFAULT_APPROVAL_DOC,
    electron_package_path: str | Path = DEFAULT_ELECTRON_PACKAGE,
) -> dict[str, Any]:
    plan_file = Path(plan_path)
    doc_file = Path(approval_doc_path)
    package_file = Path(electron_package_path)
    violations: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    audit = audit_final_goal_completion(
        plan_path=plan_file,
        electron_package_path=package_file,
    )
    completion = audit.get("completion_status", {}) if isinstance(audit.get("completion_status"), dict) else {}
    next_actions = completion.get("next_actions", []) if isinstance(completion.get("next_actions"), list) else []
    release_ready = bool(completion.get("release_ready"))
    blocked_on_approval = bool(completion.get("blocked_on_approval"))
    if release_ready:
        mode = "release_ready"
    elif blocked_on_approval or next_actions:
        mode = "approval_required"
    else:
        mode = "runtime_evidence_incomplete"

    if release_ready and next_actions:
        violations.append({
            "path": str(plan_file),
            "reason": "release-ready audit must not still report approval-gated next actions",
        })
    if mode == "approval_required" and not blocked_on_approval:
        violations.append({
            "path": str(plan_file),
            "reason": "incomplete final release must be explicitly marked blocked_on_approval",
        })

    for blocker in audit.get("blockers", []):
        blocker_type = str(blocker.get("type") or "")
        blocker_round = str(blocker.get("round") or "")
        if blocker_type not in ALLOWED_PREAPPROVAL_BLOCKER_TYPES:
            violations.append({
                "path": str(blocker.get("path") or plan_file),
                "reason": f"non-approval blocker type remains before final release: {blocker_type}",
            })
        if blocker_round not in ALLOWED_PREAPPROVAL_ROUNDS:
            violations.append({
                "path": str(blocker.get("path") or plan_file),
                "reason": f"blocker is outside the approval-gated final rounds: {blocker_round}",
            })

    if mode == "approval_required":
        if not next_actions:
            violations.append({
                "path": str(plan_file),
                "reason": "approval-required state must include next_actions",
            })
        for action in next_actions:
            if not action.get("requires_explicit_approval"):
                violations.append({
                    "path": str(plan_file),
                    "reason": f"next action must require explicit approval: {action.get('id', '')}",
                })
        mutations = _action_mutations(next_actions)
        action_ids = {str(action.get("id") or "") for action in next_actions}
        required_targets: list[str] = []
        if "electron-dependencies" in action_ids:
            required_targets.extend(["package-lock.json", "node_modules"])
        if "packaged-electron-build" in action_ids:
            required_targets.append("dist/win-unpacked")
        for required_target in required_targets:
            if not any(required_target in item for item in mutations):
                violations.append({
                    "path": str(plan_file),
                    "reason": f"approval next actions must mention mutation target: {required_target}",
                })

    if not package_file.is_file():
        violations.append({"path": str(package_file), "reason": "Electron package.json is missing"})
        package: dict[str, Any] = {}
    else:
        package = _load_json(package_file)
    scripts = package.get("scripts", {}) if isinstance(package.get("scripts"), dict) else {}
    final_command = str(scripts.get(FINAL_SCRIPT) or "")
    if not final_command:
        violations.append({"path": str(package_file), "reason": f"final approval script missing: {FINAL_SCRIPT}"})
    for reason in _ordered_terms_present(final_command, FINAL_SCRIPT_TERMS):
        violations.append({"path": str(package_file), "reason": f"{FINAL_SCRIPT} {reason}"})

    release_check = str(scripts.get("release:check") or "")
    if "check:approval-gate" not in release_check:
        violations.append({
            "path": str(package_file),
            "reason": "release:check must include check:approval-gate",
        })
    approval_check = str(scripts.get("check:approval-gate") or "")
    if "check_final_release_approval_gate.py" not in approval_check:
        violations.append({
            "path": str(package_file),
            "reason": "check:approval-gate must run tools/check_final_release_approval_gate.py",
        })

    if doc_file.is_file():
        doc_text = doc_file.read_text(encoding="utf-8")
        for term in DOC_TERMS:
            if term not in doc_text:
                violations.append({
                    "path": str(doc_file),
                    "reason": f"approval gate document must mention {term}",
                })

    return {
        "ok": not violations,
        "mode": mode,
        "plan": str(plan_file),
        "approval_doc": str(doc_file),
        "electron_package": str(package_file),
        "release_ready": release_ready,
        "blocked_on_approval": blocked_on_approval,
        "blocker_count": int(audit.get("blocker_count") or 0),
        "blockers_by_type": audit.get("blockers_by_type", {}),
        "blockers_by_round": audit.get("blockers_by_round", {}),
        "final_script": FINAL_SCRIPT,
        "final_script_command": final_command,
        "next_actions": next_actions,
        "violation_count": len(violations),
        "warning_count": len(warnings),
        "violations": violations,
        "warnings": warnings,
    }


def summarize_final_release_approval_gate(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": bool(payload.get("ok")),
        "mode": str(payload.get("mode") or ""),
        "release_ready": bool(payload.get("release_ready")),
        "blocked_on_approval": bool(payload.get("blocked_on_approval")),
        "blocker_count": int(payload.get("blocker_count") or 0),
        "blockers_by_type": payload.get("blockers_by_type", {}),
        "blockers_by_round": payload.get("blockers_by_round", {}),
        "final_script": str(payload.get("final_script") or ""),
        "next_action_count": len(payload.get("next_actions", [])),
        "violation_count": len(payload.get("violations", [])),
        "warning_count": len(payload.get("warnings", [])),
        "violations": payload.get("violations", []),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the final Electron release approval boundary.")
    parser.add_argument("--plan", default=str(DEFAULT_PLAN), help="Final roadmap plan path.")
    parser.add_argument("--approval-doc", default=str(DEFAULT_APPROVAL_DOC), help="Approval-gate handoff document path.")
    parser.add_argument("--electron-package", default=str(DEFAULT_ELECTRON_PACKAGE), help="Electron package.json path.")
    parser.add_argument("--summary", action="store_true", help="Print a compact approval-gate summary.")
    args = parser.parse_args(argv)

    payload = check_final_release_approval_gate(
        plan_path=args.plan,
        approval_doc_path=args.approval_doc,
        electron_package_path=args.electron_package,
    )
    if args.summary:
        payload = summarize_final_release_approval_gate(payload)
    json.dump(payload, sys.stdout, ensure_ascii=True, indent=2)
    sys.stdout.write("\n")
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
