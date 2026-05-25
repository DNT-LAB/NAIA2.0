"""Run the final Electron release gate orchestration.

Default mode is plan-only: it prepares dependency and portable-build evidence
without installing packages or invoking electron-builder. Use ``--execute`` for
the actual packaged build, and add ``--install-deps --yes`` only when dependency
installation is explicitly approved.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

try:
    from tools.audit_final_goal_completion import audit_final_goal_completion
    from tools.bootstrap_electron_dependencies import bootstrap_electron_dependencies
    from tools.run_electron_portable_workspace import DEFAULT_OUTPUT as DEFAULT_PORTABLE_EVIDENCE
    from tools.run_electron_portable_workspace import run_electron_portable_workspace
except ModuleNotFoundError:  # pragma: no cover - used when executed as a script.
    from audit_final_goal_completion import audit_final_goal_completion
    from bootstrap_electron_dependencies import bootstrap_electron_dependencies
    from run_electron_portable_workspace import DEFAULT_OUTPUT as DEFAULT_PORTABLE_EVIDENCE
    from run_electron_portable_workspace import run_electron_portable_workspace


DEFAULT_OUTPUT = Path("app/electron/dist/final_electron_release_gate.json")


def _write_output(payload: dict[str, Any], output: str | Path | None) -> None:
    if not output:
        return
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload["output"] = str(output_path.resolve())
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _section_ok(section: Any) -> bool:
    return isinstance(section, dict) and section.get("ok") is True


def _check_release_execution_policy(
    *,
    execute: bool,
    run_electron_cdp: bool,
    defender_scan: bool,
    require_defender_scan: bool,
) -> dict[str, Any]:
    violations: list[dict[str, str]] = []
    if execute and not run_electron_cdp:
        violations.append({
            "path": "release-final-flags",
            "reason": "final release execution requires --run-electron-cdp so packaged UI workflows are proven",
        })
    if execute and not defender_scan:
        violations.append({
            "path": "release-final-flags",
            "reason": "final release execution requires --defender-scan so scanner evidence is produced",
        })
    if execute and not require_defender_scan:
        violations.append({
            "path": "release-final-flags",
            "reason": "final release execution requires --require-defender-scan so scanner evidence is release-blocking",
        })
    return {
        "ok": not violations,
        "execute": bool(execute),
        "run_electron_cdp": bool(run_electron_cdp),
        "defender_scan": bool(defender_scan),
        "require_defender_scan": bool(require_defender_scan),
        "violations": violations,
    }


def _goal_blocker_summary(goal_audit: dict[str, Any]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for blocker in goal_audit.get("blockers", []):
        blocker_type = str(blocker.get("type") or "unknown")
        counts[blocker_type] = counts.get(blocker_type, 0) + 1
    by_round = goal_audit.get("blockers_by_round", {}) if isinstance(goal_audit, dict) else {}
    return {
        "ok": bool(goal_audit.get("ok")),
        "blocker_count": int(goal_audit.get("blocker_count") or len(goal_audit.get("blockers", []))),
        "by_type": counts,
        "by_round": by_round if isinstance(by_round, dict) else {},
    }


def _dependency_next_actions(dependency_bootstrap: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(dependency_bootstrap, dict) and dependency_bootstrap.get("ready_after") is True:
        return []
    before = dependency_bootstrap.get("before") if isinstance(dependency_bootstrap, dict) else {}
    after = dependency_bootstrap.get("after") if isinstance(dependency_bootstrap, dict) else {}
    action_source = after if isinstance(after, dict) and after else before
    next_action = action_source.get("next_action", {}) if isinstance(action_source, dict) else {}
    if not isinstance(next_action, dict) or not next_action.get("required"):
        return []
    return [{
        "id": "electron-dependencies",
        "reason": "Electron dependency installation is required before packaging can run.",
        "requires_explicit_approval": bool(next_action.get("requires_explicit_approval")),
        "script": str(next_action.get("script") or ""),
        "final_release_script": str(next_action.get("final_release_script") or ""),
        "strategy": str(next_action.get("strategy") or ""),
        "mutates": list(next_action.get("mutates") or []),
    }]


def _release_next_actions(*, electron_root: Path, dependency_bootstrap: dict[str, Any], execute: bool) -> list[dict[str, Any]]:
    actions = _dependency_next_actions(dependency_bootstrap)
    if not execute:
        actions.append({
            "id": "final-release-execute",
            "reason": "A real final build still requires dependency readiness, packaged Electron CDP smoke, and Defender scan evidence.",
            "requires_explicit_approval": True,
            "script": f"npm --prefix {electron_root} run release:final:clean-python:scan",
            "strategy": "final-clean-python-scan",
            "mutates": [
                str(electron_root / "dist"),
            ],
        })
    return actions


def _check_portable_runtime_evidence(
    *,
    execute: bool,
    portable_workspace: dict[str, Any],
) -> dict[str, Any]:
    violations: list[dict[str, str]] = []
    if not execute:
        return {
            "ok": True,
            "execute": False,
            "required": False,
            "status": "not_required_in_plan_mode",
            "checked_sections": [],
            "violations": violations,
        }
    sections = portable_workspace.get("sections", {}) if isinstance(portable_workspace.get("sections"), dict) else {}

    def require(condition: bool, path: str, reason: str) -> None:
        if not condition:
            violations.append({"path": path, "reason": reason})

    require(portable_workspace.get("dry_run") is False, "portable_workspace.dry_run", "final release requires non-dry-run portable build evidence")
    require(portable_workspace.get("run_electron_cdp") is True, "portable_workspace.run_electron_cdp", "final release requires packaged Electron CDP smoke evidence")
    require(portable_workspace.get("defender_scan") is True, "portable_workspace.defender_scan", "final release requires actual Defender scan evidence")
    require(portable_workspace.get("require_defender_scan") is True, "portable_workspace.require_defender_scan", "final release requires Defender scan to be release-blocking")
    require(_section_ok(sections.get("electron_builder")), "portable_workspace.sections.electron_builder", "electron-builder must complete successfully")
    require(_section_ok(sections.get("packaged_smoke")), "portable_workspace.sections.packaged_smoke", "packaged app structure/backend smoke must pass")
    require(_section_ok(sections.get("clean_packaged")), "portable_workspace.sections.clean_packaged", "packaged clean-machine readiness must pass")
    require(_section_ok(sections.get("electron_cdp_smoke")), "portable_workspace.sections.electron_cdp_smoke", "packaged Electron CDP smoke must pass")
    return {
        "ok": not violations,
        "execute": True,
        "required": True,
        "status": "validated" if not violations else "failed",
        "checked_sections": [
            "electron_builder",
            "packaged_smoke",
            "clean_packaged",
            "electron_cdp_smoke",
        ],
        "violations": violations,
    }


def summarize_final_release_gate(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a compact operator-facing summary without the nested evidence tree."""

    dependency_bootstrap = payload.get("sections", {}).get("dependency_bootstrap", {})
    bootstrap_before = dependency_bootstrap.get("before", {}) if isinstance(dependency_bootstrap, dict) else {}
    bootstrap_after = dependency_bootstrap.get("after", {}) if isinstance(dependency_bootstrap, dict) else {}
    dependency_status = bootstrap_after if isinstance(bootstrap_after, dict) and bootstrap_after else bootstrap_before
    dependency_violations = dependency_status.get("violations", []) if isinstance(dependency_status, dict) else []
    portable = payload.get("sections", {}).get("portable_workspace", {})
    portable_evidence = payload.get("sections", {}).get("portable_runtime_evidence", {})
    portable_blocking = portable.get("blocking_violations", []) if isinstance(portable, dict) else []
    goal_audit = payload.get("sections", {}).get("goal_audit", {})
    goal_status = goal_audit.get("completion_status", {}) if isinstance(goal_audit, dict) else {}
    return {
        "ok": bool(payload.get("ok")),
        "release_ready": bool(payload.get("release_ready")),
        "execute": bool(payload.get("execute")),
        "install_deps": bool(payload.get("install_deps")),
        "run_electron_cdp": bool(payload.get("run_electron_cdp")),
        "defender_scan": bool(payload.get("defender_scan")),
        "require_defender_scan": bool(payload.get("require_defender_scan")),
        "blocked_on_approval": bool(payload.get("blocked_on_approval")),
        "failed_sections": list(payload.get("failed_sections") or []),
        "next_actions": list(payload.get("next_actions") or []),
        "completion_blockers": payload.get("completion_blockers", {}),
        "dependency_readiness": {
            "ok": bool(dependency_status.get("ok")) if isinstance(dependency_status, dict) else False,
            "strategy": str(dependency_bootstrap.get("strategy") or "") if isinstance(dependency_bootstrap, dict) else "",
            "requires_explicit_approval": bool(dependency_bootstrap.get("requires_explicit_approval"))
            if isinstance(dependency_bootstrap, dict)
            else False,
            "violation_count": len(dependency_violations),
        },
        "portable_workspace": {
            "ok": bool(portable.get("ok")) if isinstance(portable, dict) else False,
            "dry_run": bool(portable.get("dry_run")) if isinstance(portable, dict) else False,
            "ready_to_build": bool(portable.get("ready_to_build")) if isinstance(portable, dict) else False,
            "blocking_violation_count": len(portable_blocking),
            "packaged_root": str(portable.get("packaged_root") or "") if isinstance(portable, dict) else "",
        },
        "portable_runtime_evidence": {
            "ok": bool(portable_evidence.get("ok")) if isinstance(portable_evidence, dict) else False,
            "required": bool(portable_evidence.get("required")) if isinstance(portable_evidence, dict) else False,
            "status": str(portable_evidence.get("status") or "") if isinstance(portable_evidence, dict) else "",
            "checked_sections": list(portable_evidence.get("checked_sections") or [])
            if isinstance(portable_evidence, dict)
            else [],
            "violation_count": len(portable_evidence.get("violations", []))
            if isinstance(portable_evidence, dict)
            else 0,
        },
        "goal_audit": {
            "ok": bool(goal_audit.get("ok")) if isinstance(goal_audit, dict) else False,
            "blocker_count": int(goal_audit.get("blocker_count") or 0) if isinstance(goal_audit, dict) else 0,
            "blockers_by_type": goal_audit.get("blockers_by_type", {}) if isinstance(goal_audit, dict) else {},
            "blockers_by_round": goal_audit.get("blockers_by_round", {}) if isinstance(goal_audit, dict) else {},
            "unchecked_count": int(goal_audit.get("unchecked_count") or 0) if isinstance(goal_audit, dict) else 0,
            "unsatisfied_unchecked_count": int(goal_audit.get("unsatisfied_unchecked_count") or 0)
            if isinstance(goal_audit, dict)
            else 0,
            "when_done_count": int(goal_audit.get("when_done_count") or 0) if isinstance(goal_audit, dict) else 0,
            "satisfied_when_done_count": int(goal_audit.get("satisfied_when_done_count") or 0)
            if isinstance(goal_audit, dict)
            else 0,
            "unmet_when_done_count": int(goal_audit.get("unmet_when_done_count") or 0)
            if isinstance(goal_audit, dict)
            else 0,
            "intentionally_unmapped_when_done_count": int(goal_audit.get("intentionally_unmapped_when_done_count") or 0)
            if isinstance(goal_audit, dict)
            else 0,
            "completion_status": goal_status,
        },
        "violations": list(payload.get("violations") or []),
    }


def run_final_electron_release_gate(
    *,
    source_root: str | Path = ".",
    workspace_root: str | Path | None = None,
    output: str | Path | None = DEFAULT_OUTPUT,
    portable_output: str | Path | None = DEFAULT_PORTABLE_EVIDENCE,
    python_runtime_dir: str | Path | None = None,
    build_clean_python_runtime: bool = False,
    python_runtime_venv: str | Path = "venv",
    python_runtime_python: str | Path | None = None,
    python_runtime_version: str | None = None,
    require_bundled_python: bool = False,
    execute: bool = False,
    install_deps: bool = False,
    install_strategy: str = "auto",
    yes: bool = False,
    run_backend_smoke: bool = False,
    run_electron_cdp: bool = False,
    electron_timeout: float = 60.0,
    defender_scan: bool = False,
    require_defender_scan: bool = False,
) -> dict[str, Any]:
    source = Path(source_root).resolve()
    electron_root = source / "app" / "electron"
    dry_run = not execute
    sections: dict[str, Any] = {}
    violations: list[dict[str, str]] = []

    release_policy = _check_release_execution_policy(
        execute=execute,
        run_electron_cdp=run_electron_cdp,
        defender_scan=defender_scan,
        require_defender_scan=require_defender_scan,
    )
    sections["release_policy"] = release_policy
    if not release_policy.get("ok"):
        for item in release_policy.get("violations", []):
            violations.append({
                "path": str(item.get("path", "")),
                "reason": f"release-policy: {item.get('reason', '')}",
            })

    dependency_bootstrap = bootstrap_electron_dependencies(
        electron_root=electron_root,
        strategy=install_strategy,
        dry_run=not install_deps,
        yes=yes,
    )
    sections["dependency_bootstrap"] = dependency_bootstrap
    if install_deps and not dependency_bootstrap.get("ok"):
        for item in dependency_bootstrap.get("violations", []):
            violations.append({
                "path": str(item.get("path", "")),
                "reason": f"dependency-bootstrap: {item.get('reason', '')}",
            })

    should_run_portable = not violations and not (install_deps and not dependency_bootstrap.get("ok"))
    if should_run_portable:
        portable_workspace = run_electron_portable_workspace(
            source_root=source,
            workspace_root=workspace_root,
            output=portable_output,
            python_runtime_dir=python_runtime_dir,
            build_clean_python_runtime=build_clean_python_runtime,
            python_runtime_venv=python_runtime_venv,
            python_runtime_python=python_runtime_python,
            python_runtime_version=python_runtime_version,
            require_bundled_python=require_bundled_python,
            dry_run=dry_run,
            run_backend_smoke=run_backend_smoke,
            run_electron_cdp=run_electron_cdp,
            electron_timeout=electron_timeout,
            defender_scan=defender_scan,
            require_defender_scan=require_defender_scan,
        )
    else:
        portable_workspace = {
            "ok": False,
            "status": "skipped",
            "violations": [{
                "path": str(electron_root),
                "reason": "portable build skipped because final release preconditions failed",
            }],
        }
    sections["portable_workspace"] = portable_workspace
    if execute and not portable_workspace.get("ok"):
        for item in portable_workspace.get("violations") or portable_workspace.get("blocking_violations", []):
            violations.append({
                "path": str(item.get("path", "")),
                "reason": f"portable-workspace: {item.get('reason', '')}",
            })
    portable_runtime_evidence = _check_portable_runtime_evidence(
        execute=execute,
        portable_workspace=portable_workspace,
    )
    sections["portable_runtime_evidence"] = portable_runtime_evidence
    if execute and not portable_runtime_evidence.get("ok"):
        for item in portable_runtime_evidence.get("violations", []):
            violations.append({
                "path": str(item.get("path", "")),
                "reason": f"portable-runtime-evidence: {item.get('reason', '')}",
            })

    goal_audit = audit_final_goal_completion(
        electron_package_path=electron_root / "package.json",
        portable_workspace_evidence_path=portable_output or DEFAULT_PORTABLE_EVIDENCE,
    )
    sections["goal_audit"] = goal_audit
    if execute and not goal_audit.get("ok"):
        for item in goal_audit.get("blockers", []):
            violations.append({
                "path": str(item.get("path", "")),
                "reason": f"goal-audit: {item.get('reason', '')}",
            })

    failed_sections = [name for name, section in sections.items() if not _section_ok(section)]
    next_actions = _release_next_actions(
        electron_root=electron_root,
        dependency_bootstrap=dependency_bootstrap,
        execute=execute,
    )
    payload = {
        "ok": not violations if execute else bool(portable_workspace.get("ok")),
        "release_ready": execute and not violations and bool(goal_audit.get("ok")),
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_root": str(source),
        "workspace_root": str(Path(workspace_root).resolve()) if workspace_root else "",
        "execute": bool(execute),
        "install_deps": bool(install_deps),
        "install_strategy": install_strategy,
        "run_backend_smoke": bool(run_backend_smoke),
        "run_electron_cdp": bool(run_electron_cdp),
        "defender_scan": bool(defender_scan),
        "require_defender_scan": bool(require_defender_scan),
        "require_bundled_python": bool(require_bundled_python),
        "build_clean_python_runtime": bool(build_clean_python_runtime),
        "python_runtime_venv": str(Path(python_runtime_venv).resolve()) if Path(python_runtime_venv).is_absolute() else str(source / python_runtime_venv),
        "python_runtime_python": str(Path(python_runtime_python).resolve()) if python_runtime_python else "",
        "python_runtime_version": str(python_runtime_version or ""),
        "python_runtime_dir": str(Path(python_runtime_dir).resolve()) if python_runtime_dir else "",
        "electron_timeout": float(electron_timeout),
        "portable_evidence": str(Path(portable_output).resolve()) if portable_output else "",
        "failed_sections": failed_sections,
        "blocked_on_approval": any(bool(action.get("requires_explicit_approval")) for action in next_actions),
        "next_actions": next_actions,
        "completion_blockers": {
            "goal_audit": _goal_blocker_summary(goal_audit),
            "portable_blocking_violations": len(portable_workspace.get("blocking_violations", []))
            if isinstance(portable_workspace, dict)
            else 0,
            "ready_to_build": bool(portable_workspace.get("ready_to_build"))
            if isinstance(portable_workspace, dict)
            else False,
            "portable_runtime_evidence_violations": len(portable_runtime_evidence.get("violations", []))
            if isinstance(portable_runtime_evidence, dict)
            else 0,
            "portable_runtime_evidence_required": bool(portable_runtime_evidence.get("required"))
            if isinstance(portable_runtime_evidence, dict)
            else False,
        },
        "violations": violations,
        "sections": sections,
    }
    _write_output(payload, output)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run final NAIA Electron release gate orchestration.")
    parser.add_argument("--source", default=".", help="Source checkout root.")
    parser.add_argument("--workspace", default=None, help="Missing or empty workspace directory for portable packaging.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Final gate evidence output path.")
    parser.add_argument("--portable-output", default=str(DEFAULT_PORTABLE_EVIDENCE), help="Portable workspace evidence output path.")
    parser.add_argument("--python-runtime-dir", default=None, help="Optional Python runtime folder to stage.")
    parser.add_argument(
        "--build-clean-python-runtime",
        action="store_true",
        help="Build and stage a base-only Python runtime from --python-runtime-venv.",
    )
    parser.add_argument("--python-runtime-venv", default="venv", help="Virtualenv used to locate the base Python runtime.")
    parser.add_argument("--python-runtime-python", default=None, help="Base Python executable used for --build-clean-python-runtime.")
    parser.add_argument("--python-runtime-version", default=None, help="Resolve a base Python executable by version, for example 3.12.")
    parser.add_argument("--require-bundled-python", action="store_true", help="Fail unless resources/python is staged.")
    parser.add_argument("--execute", action="store_true", help="Run the actual portable Electron build instead of plan-only mode.")
    parser.add_argument("--install-deps", action="store_true", help="Run dependency bootstrap before packaging.")
    parser.add_argument("--install-strategy", choices=("auto", "install", "ci"), default="auto", help="Dependency bootstrap strategy.")
    parser.add_argument("--yes", action="store_true", help="Required with --install-deps to allow dependency changes.")
    parser.add_argument("--run-backend-smoke", action="store_true", help="Run packaged backend smoke after electron-builder.")
    parser.add_argument("--run-electron-cdp", action="store_true", help="Run packaged Electron CDP smoke after electron-builder.")
    parser.add_argument("--electron-timeout", type=float, default=60.0, help="Electron CDP smoke timeout in seconds.")
    parser.add_argument("--defender-scan", action="store_true", help="Run Microsoft Defender local scan after packaging.")
    parser.add_argument("--require-defender-scan", action="store_true", help="Fail unless Defender scan evidence succeeds.")
    parser.add_argument("--summary", action="store_true", help="Print a compact release gate summary instead of full evidence JSON.")
    args = parser.parse_args(argv)

    payload = run_final_electron_release_gate(
        source_root=args.source,
        workspace_root=args.workspace,
        output=args.output,
        portable_output=args.portable_output,
        python_runtime_dir=args.python_runtime_dir,
        build_clean_python_runtime=args.build_clean_python_runtime,
        python_runtime_venv=args.python_runtime_venv,
        python_runtime_python=args.python_runtime_python,
        python_runtime_version=args.python_runtime_version,
        require_bundled_python=args.require_bundled_python,
        execute=args.execute,
        install_deps=args.install_deps,
        install_strategy=args.install_strategy,
        yes=args.yes,
        run_backend_smoke=args.run_backend_smoke,
        run_electron_cdp=args.run_electron_cdp,
        electron_timeout=args.electron_timeout,
        defender_scan=args.defender_scan,
        require_defender_scan=args.require_defender_scan,
    )
    if args.summary:
        payload = summarize_final_release_gate(payload)
    json.dump(payload, sys.stdout, ensure_ascii=True, indent=2)
    sys.stdout.write("\n")
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
