"""Collect release gate evidence for the final headless/Electron roadmap."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
from typing import Any

try:
    from tools.audit_final_goal_completion import audit_final_goal_completion
    from tools.check_clean_machine_readiness import check_clean_machine_readiness
    from tools.check_electron_dependency_readiness import check_electron_dependency_readiness
    from tools.check_electron_shell_contract import check_electron_shell_contract
    from tools.check_packaged_electron_feature_smoke import check_packaged_electron_feature_smoke
    from tools.check_release_distribution_strategy import check_release_distribution_strategy
    from tools.check_release_preflight import check_release_preflight
    from tools.measure_release_artifact import measure_release_artifact
    from tools.smoke_electron_cdp import smoke_electron_cdp
    from tools.smoke_packaged_electron_app import smoke_packaged_electron_app
    from tools.stage_electron_release import stage_electron_release
except ModuleNotFoundError:  # pragma: no cover - used when executed as a script.
    from audit_final_goal_completion import audit_final_goal_completion
    from check_clean_machine_readiness import check_clean_machine_readiness
    from check_electron_dependency_readiness import check_electron_dependency_readiness
    from check_electron_shell_contract import check_electron_shell_contract
    from check_packaged_electron_feature_smoke import check_packaged_electron_feature_smoke
    from check_release_distribution_strategy import check_release_distribution_strategy
    from check_release_preflight import check_release_preflight
    from measure_release_artifact import measure_release_artifact
    from smoke_electron_cdp import smoke_electron_cdp
    from smoke_packaged_electron_app import smoke_packaged_electron_app
    from stage_electron_release import stage_electron_release


DEFAULT_STAGED_ROOT = Path("app/electron/dist/NAIA-Web")
DEFAULT_PACKAGED_ROOT = Path("app/electron/dist/win-unpacked")
DEFAULT_ELECTRON_PACKAGE = Path("app/electron/package.json")
DEFAULT_OUTPUT = Path("app/electron/dist/release_evidence.json")
DEFAULT_FRESH_RELEASE_NAME = "NAIA-Web"


def _missing_root_section(name: str, root: Path) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "missing",
        "root": str(root.resolve()),
        "violations": [{"path": str(root), "reason": f"{name} root is missing"}],
    }


def _skipped_section(name: str, reason: str) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "skipped",
        "violations": [{"path": name, "reason": reason}],
    }


def _section_ok(section: Any) -> bool:
    return isinstance(section, dict) and section.get("ok") is True


def summarize_release_evidence_report(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a compact release-evidence summary without nested file inventories."""

    sections = payload.get("sections", {}) if isinstance(payload.get("sections"), dict) else {}

    def section(name: str) -> dict[str, Any]:
        value = sections.get(name, {})
        return value if isinstance(value, dict) else {}

    staged = section("staged_release")
    packaged = section("packaged_release")
    dependencies = section("electron_dependencies")
    runtime = section("electron_runtime")
    goal = section("goal_audit")
    fresh = section("fresh_staged_workspace")
    return {
        "ok": bool(payload.get("ok")),
        "failed_sections": list(payload.get("failed_sections") or []),
        "fresh_staged_workspace": bool(payload.get("fresh_staged_workspace")),
        "workspace_root": str(payload.get("workspace_root") or ""),
        "staged_root": str(payload.get("staged_root") or ""),
        "packaged_root": str(payload.get("packaged_root") or ""),
        "electron_package": str(payload.get("electron_package") or ""),
        "require_bundled_python": bool(payload.get("require_bundled_python")),
        "skip_electron_runtime": bool(payload.get("skip_electron_runtime")),
        "skip_backend_smoke": bool(payload.get("skip_backend_smoke")),
        "defender_scan": bool(payload.get("defender_scan")),
        "require_defender_scan": bool(payload.get("require_defender_scan")),
        "fresh_workspace": {
            "ok": bool(fresh.get("ok")) if fresh else None,
            "status": str(fresh.get("status") or "") if fresh else "",
        },
        "staged_release": {
            "ok": bool(staged.get("ok")),
            "status": str(staged.get("status") or ""),
            "violation_count": len(staged.get("violations", [])),
        },
        "packaged_release": {
            "ok": bool(packaged.get("ok")),
            "status": str(packaged.get("status") or ""),
            "violation_count": len(packaged.get("violations", [])),
        },
        "electron_dependencies": {
            "ok": bool(dependencies.get("ok")),
            "violation_count": len(dependencies.get("violations", [])),
            "next_action": dependencies.get("next_action", {}),
        },
        "electron_runtime": {
            "ok": bool(runtime.get("ok")),
            "status": str(runtime.get("status") or ""),
            "violation_count": len(runtime.get("violations", [])),
        },
        "goal_audit": {
            "ok": bool(goal.get("ok")),
            "blocker_count": int(goal.get("blocker_count") or 0),
            "blockers_by_type": goal.get("blockers_by_type", {}),
            "unchecked_count": int(goal.get("unchecked_count") or 0),
            "unsatisfied_unchecked_count": int(goal.get("unsatisfied_unchecked_count") or 0),
            "when_done_count": int(goal.get("when_done_count") or 0),
            "satisfied_when_done_count": int(goal.get("satisfied_when_done_count") or 0),
            "unmet_when_done_count": int(goal.get("unmet_when_done_count") or 0),
            "intentionally_unmapped_when_done_count": int(goal.get("intentionally_unmapped_when_done_count") or 0),
        },
    }


def _empty_or_missing(path: Path) -> bool:
    return not path.exists() or (path.is_dir() and not any(path.iterdir()))


def _prepare_fresh_staged_workspace(
    *,
    source_root: Path,
    workspace_root: Path | None,
) -> tuple[Path, dict[str, Any]]:
    if workspace_root is None:
        workspace = Path(tempfile.mkdtemp(prefix="naia-release-evidence-")).resolve()
        created_temporary = True
    else:
        workspace = workspace_root.resolve()
        created_temporary = False

    if not _empty_or_missing(workspace):
        return (
            workspace / DEFAULT_FRESH_RELEASE_NAME,
            {
                "ok": False,
                "status": "blocked",
                "workspace_root": str(workspace),
                "created_temporary_workspace": created_temporary,
                "violations": [{
                    "path": str(workspace),
                    "reason": "fresh staged workspace root must be missing or empty; refusing to overwrite",
                }],
            },
        )

    workspace.mkdir(parents=True, exist_ok=True)
    release_root = workspace / DEFAULT_FRESH_RELEASE_NAME
    try:
        stage_result = stage_electron_release(source_root, release_root, copy=True)
    except Exception as exc:
        return (
            release_root,
            {
                "ok": False,
                "status": "failed",
                "workspace_root": str(workspace),
                "release_root": str(release_root),
                "created_temporary_workspace": created_temporary,
                "violations": [{"path": str(release_root), "reason": str(exc)}],
            },
        )

    return (
        release_root,
        {
            "ok": True,
            "status": "staged",
            "workspace_root": str(workspace),
            "release_root": str(release_root),
            "created_temporary_workspace": created_temporary,
            "stage_backend": {**stage_result.__dict__, "ok": True, "violations": []},
            "violations": [],
        },
    )


def _collect_staged_release(
    root: Path,
    *,
    require_bundled_python: bool,
    defender_scan: bool,
    require_defender_scan: bool,
) -> dict[str, Any]:
    if not root.is_dir():
        return _missing_root_section("staged release", root)
    preflight = check_release_preflight(root, require_bundled_python=require_bundled_python)
    clean_machine = check_clean_machine_readiness(
        root,
        kind="staged-release",
        require_bundled_python=require_bundled_python,
        defender_scan=defender_scan,
        require_defender_scan=require_defender_scan,
    )
    measurement = measure_release_artifact(
        root,
        defender_scan=defender_scan or require_defender_scan,
        require_defender_scan=require_defender_scan,
    )
    violations = []
    for source, section in (
        ("preflight", preflight),
        ("clean_machine", clean_machine),
        ("measurement", measurement),
    ):
        for item in section.get("violations", []):
            violations.append({
                "path": str(item.get("path", "")),
                "reason": f"{source}: {item.get('reason', '')}",
            })
    return {
        "ok": not violations,
        "status": "checked",
        "root": str(root.resolve()),
        "preflight": preflight,
        "clean_machine": clean_machine,
        "measurement": measurement,
        "violations": violations,
    }


def _completion_evidence_from_staged_release(section: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(section, dict) or section.get("ok") is not True:
        return {}
    staged_workspace = {
        "ok": True,
        "sections": {
            "preflight": section.get("preflight", {}),
            "clean_machine": section.get("clean_machine", {}),
            "measurement": section.get("measurement", {}),
        },
    }
    return {"sections": {"staged_workspace": staged_workspace}}


def _collect_packaged_release(
    root: Path,
    *,
    require_bundled_python: bool,
    skip_backend_smoke: bool,
    defender_scan: bool,
    require_defender_scan: bool,
) -> dict[str, Any]:
    if not root.is_dir():
        return _missing_root_section("packaged Electron", root)
    structure_smoke = smoke_packaged_electron_app(
        root,
        require_bundled_python=require_bundled_python,
        skip_backend_smoke=skip_backend_smoke,
    )
    clean_machine = check_clean_machine_readiness(
        root,
        kind="packaged-electron",
        require_bundled_python=require_bundled_python,
        skip_backend_smoke=skip_backend_smoke,
        defender_scan=defender_scan,
        require_defender_scan=require_defender_scan,
    )
    measurement = measure_release_artifact(
        root,
        defender_scan=defender_scan or require_defender_scan,
        require_defender_scan=require_defender_scan,
    )
    violations = []
    for source, section in (
        ("structure_smoke", structure_smoke),
        ("clean_machine", clean_machine),
        ("measurement", measurement),
    ):
        for item in section.get("violations", []):
            violations.append({
                "path": str(item.get("path", "")),
                "reason": f"{source}: {item.get('reason', '')}",
            })
    return {
        "ok": not violations,
        "status": "checked",
        "root": str(root.resolve()),
        "structure_smoke": structure_smoke,
        "clean_machine": clean_machine,
        "measurement": measurement,
        "violations": violations,
    }


def _collect_electron_runtime(
    *,
    staged_root: Path,
    packaged_root: Path,
    skip_electron_runtime: bool,
    timeout: float,
) -> dict[str, Any]:
    if skip_electron_runtime:
        return _skipped_section(
            "electron_runtime",
            "Electron CDP runtime smoke was skipped; packaged release evidence is incomplete",
        )
    source = smoke_electron_cdp(mode="source", timeout=timeout)
    packaged = smoke_electron_cdp(mode="packaged", package_root=packaged_root, timeout=timeout)
    violations = []
    for source_name, section in (("source", source), ("packaged", packaged)):
        for item in section.get("violations", []):
            violations.append({
                "path": str(item.get("path", "")),
                "reason": f"{source_name}: {item.get('reason', '')}",
            })
    return {
        "ok": _section_ok(source) and _section_ok(packaged),
        "status": "checked",
        "staged_root": str(staged_root.resolve()),
        "packaged_root": str(packaged_root.resolve()),
        "source": source,
        "packaged": packaged,
        "violations": violations,
    }


def write_release_evidence_report(
    *,
    source_root: str | Path = ".",
    staged_root: str | Path = DEFAULT_STAGED_ROOT,
    packaged_root: str | Path = DEFAULT_PACKAGED_ROOT,
    electron_package: str | Path = DEFAULT_ELECTRON_PACKAGE,
    output: str | Path | None = None,
    fresh_staged_workspace: bool = False,
    workspace_root: str | Path | None = None,
    require_bundled_python: bool = False,
    skip_electron_runtime: bool = False,
    skip_backend_smoke: bool = True,
    electron_timeout: float = 60.0,
    defender_scan: bool = False,
    require_defender_scan: bool = False,
) -> dict[str, Any]:
    source = Path(source_root).resolve()
    staged = Path(staged_root)
    packaged = Path(packaged_root)
    electron_package_path = Path(electron_package)
    fresh_section: dict[str, Any] | None = None
    if fresh_staged_workspace:
        staged, fresh_section = _prepare_fresh_staged_workspace(
            source_root=source,
            workspace_root=Path(workspace_root) if workspace_root else None,
        )
    sections: dict[str, Any] = {
        "staged_release": _collect_staged_release(
            staged,
            require_bundled_python=require_bundled_python,
            defender_scan=defender_scan,
            require_defender_scan=require_defender_scan,
        ),
        "packaged_release": _collect_packaged_release(
            packaged,
            require_bundled_python=require_bundled_python,
            skip_backend_smoke=skip_backend_smoke,
            defender_scan=defender_scan,
            require_defender_scan=require_defender_scan,
        ),
        "electron_dependencies": check_electron_dependency_readiness(
            electron_package_path=electron_package_path,
        ),
        "electron_shell_contract": check_electron_shell_contract(electron_root=electron_package_path.parent),
        "feature_smoke_mapping": check_packaged_electron_feature_smoke(),
        "distribution_strategy": check_release_distribution_strategy(electron_package_path=electron_package_path),
        "electron_runtime": _collect_electron_runtime(
            staged_root=staged,
            packaged_root=packaged,
            skip_electron_runtime=skip_electron_runtime,
            timeout=electron_timeout,
        ),
    }
    sections["goal_audit"] = audit_final_goal_completion(
        electron_package_path=electron_package_path,
        packaged_root=packaged,
        extra_completion_evidence=_completion_evidence_from_staged_release(sections["staged_release"]),
    )
    if fresh_section is not None:
        sections = {"fresh_staged_workspace": fresh_section, **sections}
    failed_sections = [name for name, section in sections.items() if not _section_ok(section)]
    payload = {
        "ok": not failed_sections,
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_root": str(source),
        "staged_root": str(staged.resolve()),
        "packaged_root": str(packaged.resolve()),
        "electron_package": str(electron_package_path.resolve()),
        "fresh_staged_workspace": bool(fresh_staged_workspace),
        "workspace_root": str(Path(workspace_root).resolve()) if workspace_root else "",
        "require_bundled_python": bool(require_bundled_python),
        "skip_electron_runtime": bool(skip_electron_runtime),
        "skip_backend_smoke": bool(skip_backend_smoke),
        "defender_scan": bool(defender_scan or require_defender_scan),
        "require_defender_scan": bool(require_defender_scan),
        "failed_sections": failed_sections,
        "sections": sections,
    }
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload["output"] = str(output_path.resolve())
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write NAIA release gate evidence as JSON.")
    parser.add_argument("--source", default=".", help="Source checkout root.")
    parser.add_argument("--staged-root", default=str(DEFAULT_STAGED_ROOT), help="Staged NAIA-Web release directory.")
    parser.add_argument("--packaged-root", default=str(DEFAULT_PACKAGED_ROOT), help="Packaged Electron win-unpacked directory.")
    parser.add_argument("--electron-package", default=str(DEFAULT_ELECTRON_PACKAGE), help="Electron package.json path.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Where to write the evidence JSON.")
    parser.add_argument("--no-output", action="store_true", help="Only write JSON to stdout.")
    parser.add_argument("--fresh-staged-workspace", action="store_true", help="Stage a fresh temporary NAIA-Web workspace before collecting staged evidence.")
    parser.add_argument("--workspace", default=None, help="Missing or empty workspace root for --fresh-staged-workspace.")
    parser.add_argument("--require-bundled-python", action="store_true", help="Treat missing resources/python as a failure.")
    parser.add_argument("--skip-electron-runtime", action="store_true", help="Do not launch Electron CDP smoke; report remains not release-ready.")
    parser.add_argument("--run-backend-smoke", action="store_true", help="Run packaged backend smoke instead of structure-only checks.")
    parser.add_argument("--electron-timeout", type=float, default=60.0, help="Electron CDP smoke timeout in seconds.")
    parser.add_argument("--defender-scan", action="store_true", help="Run Microsoft Defender local scan when available.")
    parser.add_argument("--require-defender-scan", action="store_true", help="Fail unless a Defender scan runs and succeeds.")
    parser.add_argument("--summary", action="store_true", help="Print a compact evidence summary instead of full nested evidence.")
    args = parser.parse_args(argv)

    payload = write_release_evidence_report(
        source_root=args.source,
        staged_root=args.staged_root,
        packaged_root=args.packaged_root,
        electron_package=args.electron_package,
        output=None if args.no_output else args.output,
        fresh_staged_workspace=args.fresh_staged_workspace,
        workspace_root=args.workspace,
        require_bundled_python=args.require_bundled_python,
        skip_electron_runtime=args.skip_electron_runtime,
        skip_backend_smoke=not args.run_backend_smoke,
        electron_timeout=args.electron_timeout,
        defender_scan=args.defender_scan,
        require_defender_scan=args.require_defender_scan,
    )
    if args.summary:
        payload = summarize_release_evidence_report(payload)
    json.dump(payload, sys.stdout, ensure_ascii=True, indent=2)
    sys.stdout.write("\n")
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
