"""Stage and optionally build an Electron portable release from a clean workspace."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any

try:
    from tools.check_clean_machine_readiness import check_clean_machine_readiness
    from tools.check_electron_dependency_readiness import check_electron_dependency_readiness
    from tools.check_electron_shell_contract import check_electron_shell_contract
    from tools.check_release_distribution_strategy import check_release_distribution_strategy
    from tools.apply_windows_exe_icon import apply_windows_exe_icon
    from tools.run_release_workspace import run_release_workspace
    from tools.smoke_electron_cdp import smoke_electron_cdp
    from tools.smoke_packaged_electron_app import smoke_packaged_electron_app
    from tools.write_release_evidence_report import write_release_evidence_report
except ModuleNotFoundError:  # pragma: no cover - used when executed as a script.
    from check_clean_machine_readiness import check_clean_machine_readiness
    from check_electron_dependency_readiness import check_electron_dependency_readiness
    from check_electron_shell_contract import check_electron_shell_contract
    from check_release_distribution_strategy import check_release_distribution_strategy
    from apply_windows_exe_icon import apply_windows_exe_icon
    from run_release_workspace import run_release_workspace
    from smoke_electron_cdp import smoke_electron_cdp
    from smoke_packaged_electron_app import smoke_packaged_electron_app
    from write_release_evidence_report import write_release_evidence_report


DEFAULT_OUTPUT = Path("app/electron/dist/electron_workspace_release_evidence.json")


def _section_ok(section: Any) -> bool:
    return isinstance(section, dict) and section.get("ok") is True


def summarize_electron_portable_workspace(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a compact portable-workspace summary without nested file inventories."""

    sections = payload.get("sections", {}) if isinstance(payload.get("sections"), dict) else {}

    def section(name: str) -> dict[str, Any]:
        value = sections.get(name, {})
        return value if isinstance(value, dict) else {}

    dependencies = section("electron_dependencies")
    dependency_next_action = dependencies.get("next_action", {}) if isinstance(dependencies, dict) else {}
    builder = section("electron_builder")
    staged = section("staged_workspace")
    packaged_smoke = section("packaged_smoke")
    clean_packaged = section("clean_packaged")
    electron_cdp = section("electron_cdp_smoke")
    final_evidence = section("final_release_evidence")
    blocking_violations = payload.get("blocking_violations", [])
    failed_sections = []
    for name, value in sections.items():
        if _section_ok(value):
            continue
        if bool(payload.get("dry_run")) and name == "electron_builder" and str(builder.get("status") or "") == "dry_run":
            continue
        failed_sections.append(name)
    return {
        "ok": bool(payload.get("ok")),
        "dry_run": bool(payload.get("dry_run")),
        "source_root": str(payload.get("source_root") or ""),
        "workspace_root": str(payload.get("workspace_root") or ""),
        "release_root": str(payload.get("release_root") or ""),
        "builder_packaged_root": str(payload.get("builder_packaged_root") or ""),
        "portable_release_root": str(payload.get("portable_release_root") or ""),
        "packaged_root": str(payload.get("packaged_root") or ""),
        "created_temporary_workspace": bool(payload.get("created_temporary_workspace")),
        "ready_to_build": bool(payload.get("ready_to_build")),
        "run_electron_cdp": bool(payload.get("run_electron_cdp")),
        "defender_scan": bool(payload.get("defender_scan")),
        "require_defender_scan": bool(payload.get("require_defender_scan")),
        "require_bundled_python": bool(payload.get("require_bundled_python")),
        "build_clean_python_runtime": bool(payload.get("build_clean_python_runtime")),
        "python_runtime_version": str(payload.get("python_runtime_version") or ""),
        "failed_sections": failed_sections,
        "blocking_violation_count": len(blocking_violations),
        "staged_workspace": {
            "ok": bool(staged.get("ok")) if staged else None,
            "violation_count": len(staged.get("violations", [])) if staged else 0,
        },
        "electron_dependencies": {
            "ok": bool(dependencies.get("ok")) if dependencies else None,
            "violation_count": len(dependencies.get("violations", [])) if dependencies else 0,
            "next_action_required": bool(dependency_next_action.get("required"))
            if isinstance(dependency_next_action, dict)
            else False,
            "requires_explicit_approval": bool(dependency_next_action.get("requires_explicit_approval"))
            if isinstance(dependency_next_action, dict)
            else False,
            "script": str(dependency_next_action.get("script") or "")
            if isinstance(dependency_next_action, dict)
            else "",
            "final_release_script": str(dependency_next_action.get("final_release_script") or "")
            if isinstance(dependency_next_action, dict)
            else "",
        },
        "electron_builder": {
            "ok": bool(builder.get("ok")) if builder else None,
            "status": str(builder.get("status") or "") if builder else "",
            "violation_count": len(builder.get("violations", [])) if builder else 0,
        },
        "exe_icon": {
            "ok": bool(section("exe_icon").get("ok")) if section("exe_icon") else None,
            "violation_count": len(section("exe_icon").get("violations", [])) if section("exe_icon") else 0,
        },
        "portable_export": {
            "ok": bool(section("portable_export").get("ok")) if section("portable_export") else None,
            "violation_count": len(section("portable_export").get("violations", [])) if section("portable_export") else 0,
        },
        "packaged_smoke": {
            "ok": bool(packaged_smoke.get("ok")) if packaged_smoke else None,
            "violation_count": len(packaged_smoke.get("violations", [])) if packaged_smoke else 0,
        },
        "clean_packaged": {
            "ok": bool(clean_packaged.get("ok")) if clean_packaged else None,
            "violation_count": len(clean_packaged.get("violations", [])) if clean_packaged else 0,
        },
        "electron_cdp_smoke": {
            "ok": bool(electron_cdp.get("ok")) if electron_cdp else None,
            "violation_count": len(electron_cdp.get("violations", [])) if electron_cdp else 0,
        },
        "final_release_evidence": {
            "ok": bool(final_evidence.get("ok")) if final_evidence else None,
            "failed_sections": list(final_evidence.get("failed_sections") or []) if final_evidence else [],
        },
    }


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _builder_bin(electron_root: Path) -> Path:
    for candidate in (
        electron_root / "node_modules" / ".bin" / "electron-builder.cmd",
        electron_root / "node_modules" / ".bin" / "electron-builder",
    ):
        if candidate.is_file():
            return candidate
    return electron_root / "node_modules" / ".bin" / "electron-builder.cmd"


def _workspace_builder_config(
    *,
    electron_package: Path,
    release_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    package = _load_json(electron_package)
    build = dict(package.get("build") or {})
    build["directories"] = {**dict(build.get("directories") or {}), "output": str(output_dir)}
    build["win"] = {
        **dict(build.get("win") or {}),
        "target": "dir",
        "signAndEditExecutable": False,
        "forceCodeSigning": False,
    }
    extra_resources = [
        {
            "from": str((release_root / "resources" / "naia-backend").resolve()),
            "to": "naia-backend",
        }
    ]
    python_runtime = release_root / "resources" / "python"
    if python_runtime.is_dir():
        extra_resources.append({
            "from": str(python_runtime.resolve()),
            "to": "python",
        })
    progrok_runtime = release_root / "resources" / "progrok-runtime"
    if progrok_runtime.is_dir():
        extra_resources.append({
            "from": str(progrok_runtime.resolve()),
            "to": "progrok-runtime",
        })
    build["extraResources"] = extra_resources
    build["extraFiles"] = [
        {"from": str((release_root / "README_RELEASE.txt").resolve()), "to": "README_RELEASE.txt"},
        {"from": str((release_root / "RELEASE_MANIFEST.json").resolve()), "to": "RELEASE_MANIFEST.json"},
        {"from": str((release_root / "CHECKSUMS.sha256").resolve()), "to": "CHECKSUMS.sha256"},
    ]
    if build.get("afterPack"):
        build["afterPack"] = str((electron_package.parent / str(build["afterPack"])).resolve())
    return build


def _write_output(payload: dict[str, Any], output: str | Path | None) -> None:
    if not output:
        return
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload["output"] = str(output_path.resolve())
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _failed_workspace(path: Path, reason: str) -> dict[str, Any]:
    return {
        "ok": False,
        "workspace_root": str(path.resolve()),
        "violations": [{"path": str(path), "reason": reason}],
    }


def _empty_or_missing(path: Path) -> bool:
    return not path.exists() or (path.is_dir() and not any(path.iterdir()))


def _export_packaged_release(source: Path, destination: Path) -> dict[str, Any]:
    if not source.is_dir():
        return {
            "ok": False,
            "source": str(source),
            "destination": str(destination),
            "violations": [{"path": str(source), "reason": "electron-builder output is missing"}],
        }
    if destination.exists():
        return {
            "ok": False,
            "source": str(source),
            "destination": str(destination),
            "violations": [{"path": str(destination), "reason": "portable release destination already exists"}],
        }
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)
    return {
        "ok": True,
        "source": str(source),
        "destination": str(destination),
        "violations": [],
    }


def run_electron_portable_workspace(
    *,
    source_root: str | Path = ".",
    workspace_root: str | Path | None = None,
    output: str | Path | None = None,
    python_runtime_dir: str | Path | None = None,
    build_clean_python_runtime: bool = False,
    python_runtime_venv: str | Path = "venv",
    python_runtime_python: str | Path | None = None,
    python_runtime_version: str | None = None,
    require_bundled_python: bool = False,
    dry_run: bool = False,
    run_backend_smoke: bool = False,
    run_electron_cdp: bool = False,
    electron_timeout: float = 60.0,
    defender_scan: bool = False,
    require_defender_scan: bool = False,
) -> dict[str, Any]:
    source = Path(source_root).resolve()
    if workspace_root is None:
        workspace = Path(tempfile.mkdtemp(prefix="naia-electron-portable-")).resolve()
        created_temporary = True
    else:
        workspace = Path(workspace_root).resolve()
        created_temporary = False
    if not _empty_or_missing(workspace):
        payload = _failed_workspace(workspace, "workspace root must be missing or empty; refusing to overwrite")
        _write_output(payload, output)
        return payload

    electron_package = source / "app" / "electron" / "package.json"
    electron_root = electron_package.parent
    release_workspace = workspace / "staged"
    staged_payload = run_release_workspace(
        source_root=source,
        workspace_root=release_workspace,
        python_runtime_dir=python_runtime_dir,
        build_clean_python_runtime=build_clean_python_runtime,
        python_runtime_venv=python_runtime_venv,
        python_runtime_python=python_runtime_python,
        python_runtime_version=python_runtime_version,
        require_bundled_python=require_bundled_python,
        include_final_evidence=False,
    )
    release_root = release_workspace / "NAIA-Web"
    output_dir = workspace / "_build" / "electron-dist"
    builder_packaged_root = output_dir / "win-unpacked"
    portable_release_root = workspace / "NAIA-Portable"
    packaged_root = portable_release_root
    config_path = workspace / "electron-builder.workspace.json"
    build_config = _workspace_builder_config(
        electron_package=electron_package,
        release_root=release_root,
        output_dir=output_dir,
    )
    workspace.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(build_config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    dependency_readiness = check_electron_dependency_readiness(electron_package_path=electron_package)
    builder_command = [
        str(_builder_bin(electron_root)),
        "--dir",
        "--config",
        str(config_path),
    ]
    distribution_strategy = check_release_distribution_strategy(electron_package_path=electron_package)
    electron_shell_contract = check_electron_shell_contract(electron_root=electron_root)
    sections: dict[str, Any] = {
        "staged_workspace": staged_payload,
        "electron_dependencies": dependency_readiness,
        "distribution_strategy": distribution_strategy,
        "electron_shell_contract": electron_shell_contract,
    }
    violations: list[dict[str, str]] = []
    if not staged_payload.get("ok"):
        violations.extend({
            "path": str(item.get("path", "")),
            "reason": f"staged-workspace: {item.get('reason', '')}",
        } for item in staged_payload.get("violations", []))
    if not dependency_readiness.get("ok"):
        violations.extend({
            "path": str(item.get("path", "")),
            "reason": f"electron-dependencies: {item.get('reason', '')}",
        } for item in dependency_readiness.get("violations", []))
    if not distribution_strategy.get("ok"):
        violations.extend({
            "path": str(item.get("path", "")),
            "reason": f"distribution-strategy: {item.get('reason', '')}",
        } for item in distribution_strategy.get("violations", []))
    if not electron_shell_contract.get("ok"):
        violations.extend({
            "path": str(item.get("path", "")),
            "reason": f"electron-shell-contract: {item.get('reason', '')}",
        } for item in electron_shell_contract.get("violations", []))

    build_result: dict[str, Any] = {
        "ok": False,
        "status": "dry_run" if dry_run else "blocked",
        "command": builder_command,
        "cwd": str(electron_root),
        "violations": [],
    }
    packaged_smoke: dict[str, Any] | None = None
    clean_packaged: dict[str, Any] | None = None
    electron_cdp: dict[str, Any] | None = None
    final_evidence: dict[str, Any] | None = None
    exe_icon: dict[str, Any] | None = None
    portable_export: dict[str, Any] | None = None

    if not dry_run and not violations:
        completed = subprocess.run(
            builder_command,
            cwd=electron_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        build_result = {
            "ok": completed.returncode == 0,
            "status": "checked",
            "command": builder_command,
            "cwd": str(electron_root),
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "violations": [] if completed.returncode == 0 else [{
                "path": "electron-builder",
                "reason": f"electron-builder exited with {completed.returncode}",
            }],
        }
        sections["electron_builder"] = build_result
        if not build_result["ok"]:
            violations.extend(build_result["violations"])
        else:
            exe_icon = apply_windows_exe_icon(
                builder_packaged_root / "NAIA.exe",
                electron_root / "assets" / "naia.ico",
            )
            sections["exe_icon"] = exe_icon
            if not exe_icon.get("ok"):
                violations.extend(exe_icon.get("violations", []))
            else:
                portable_export = _export_packaged_release(builder_packaged_root, portable_release_root)
                sections["portable_export"] = portable_export
            if portable_export is None or not portable_export.get("ok"):
                if portable_export is not None:
                    violations.extend(portable_export.get("violations", []))
            else:
                packaged_smoke = smoke_packaged_electron_app(
                    packaged_root,
                    require_bundled_python=require_bundled_python,
                    skip_backend_smoke=not run_backend_smoke,
                )
                clean_packaged = check_clean_machine_readiness(
                    packaged_root,
                    kind="packaged-electron",
                    require_bundled_python=require_bundled_python,
                    skip_backend_smoke=not run_backend_smoke,
                    defender_scan=defender_scan,
                    require_defender_scan=require_defender_scan,
                )
                if run_electron_cdp:
                    electron_cdp = smoke_electron_cdp(
                        mode="packaged",
                        package_root=packaged_root,
                        timeout=electron_timeout,
                    )
                final_evidence = write_release_evidence_report(
                    staged_root=release_root,
                    packaged_root=packaged_root,
                    electron_package=electron_package,
                    output=None,
                    require_bundled_python=require_bundled_python,
                    skip_electron_runtime=not run_electron_cdp,
                    skip_backend_smoke=not run_backend_smoke,
                    electron_timeout=electron_timeout,
                    defender_scan=defender_scan,
                    require_defender_scan=require_defender_scan,
                )
                for section_name, section in (
                    ("packaged-smoke", packaged_smoke),
                    ("clean-packaged", clean_packaged),
                    ("electron-cdp", electron_cdp or {"violations": []}),
                ):
                    for item in section.get("violations", []):
                        violations.append({
                            "path": str(item.get("path", "")),
                            "reason": f"{section_name}: {item.get('reason', '')}",
                        })
    else:
        sections["electron_builder"] = build_result

    if packaged_smoke is not None:
        sections["packaged_smoke"] = packaged_smoke
    if clean_packaged is not None:
        sections["clean_packaged"] = clean_packaged
    if electron_cdp is not None:
        sections["electron_cdp_smoke"] = electron_cdp
    if final_evidence is not None:
        sections["final_release_evidence"] = final_evidence
    if exe_icon is not None:
        sections["exe_icon"] = exe_icon
    if portable_export is not None:
        sections["portable_export"] = portable_export

    effective_python_runtime_dir = staged_payload.get("python_runtime_dir") or python_runtime_dir
    payload = {
        "ok": not violations if not dry_run else bool(staged_payload.get("ok")),
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_root": str(source),
        "workspace_root": str(workspace),
        "created_temporary_workspace": created_temporary,
        "release_root": str(release_root),
        "builder_config": str(config_path),
        "builder_output_dir": str(output_dir),
        "builder_packaged_root": str(builder_packaged_root),
        "portable_release_root": str(portable_release_root),
        "packaged_root": str(packaged_root),
        "dry_run": bool(dry_run),
        "run_electron_cdp": bool(run_electron_cdp),
        "defender_scan": bool(defender_scan or require_defender_scan),
        "require_defender_scan": bool(require_defender_scan),
        "electron_timeout": float(electron_timeout),
        "require_bundled_python": bool(require_bundled_python),
        "build_clean_python_runtime": bool(build_clean_python_runtime),
        "python_runtime_venv": str(Path(python_runtime_venv).resolve()) if Path(python_runtime_venv).is_absolute() else str(source / python_runtime_venv),
        "python_runtime_python": str(Path(python_runtime_python).resolve()) if python_runtime_python else "",
        "python_runtime_version": str(python_runtime_version or ""),
        "python_runtime_dir": str(Path(effective_python_runtime_dir).resolve()) if effective_python_runtime_dir else "",
        "builder_command": builder_command,
        "ready_to_build": bool(staged_payload.get("ok") and dependency_readiness.get("ok")),
        "violations": [] if dry_run else violations,
        "blocking_violations": violations,
        "sections": sections,
    }
    _write_output(payload, output)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build an Electron portable release from a clean staged workspace.")
    parser.add_argument("--source", default=".", help="Source checkout root.")
    parser.add_argument("--workspace", default=None, help="Missing or empty workspace directory to populate.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Optional JSON evidence output path.")
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
    parser.add_argument("--dry-run", action="store_true", help="Prepare staging/config evidence without running electron-builder.")
    parser.add_argument("--run-backend-smoke", action="store_true", help="Run packaged backend smoke after electron-builder.")
    parser.add_argument("--run-electron-cdp", action="store_true", help="Run packaged Electron CDP smoke after electron-builder.")
    parser.add_argument("--electron-timeout", type=float, default=60.0, help="Electron CDP smoke timeout in seconds.")
    parser.add_argument("--defender-scan", action="store_true", help="Run Microsoft Defender local scan after packaging.")
    parser.add_argument("--require-defender-scan", action="store_true", help="Fail unless Defender scan evidence succeeds.")
    parser.add_argument("--no-output", action="store_true", help="Only write JSON to stdout.")
    parser.add_argument("--summary", action="store_true", help="Print a compact portable workspace summary.")
    args = parser.parse_args(argv)

    payload = run_electron_portable_workspace(
        source_root=args.source,
        workspace_root=args.workspace,
        output=None if args.no_output else args.output,
        python_runtime_dir=args.python_runtime_dir,
        build_clean_python_runtime=args.build_clean_python_runtime,
        python_runtime_venv=args.python_runtime_venv,
        python_runtime_python=args.python_runtime_python,
        python_runtime_version=args.python_runtime_version,
        require_bundled_python=args.require_bundled_python,
        dry_run=args.dry_run,
        run_backend_smoke=args.run_backend_smoke,
        run_electron_cdp=args.run_electron_cdp,
        electron_timeout=args.electron_timeout,
        defender_scan=args.defender_scan,
        require_defender_scan=args.require_defender_scan,
    )
    if args.summary:
        payload = summarize_electron_portable_workspace(payload)
    json.dump(payload, sys.stdout, ensure_ascii=True, indent=2)
    sys.stdout.write("\n")
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
