"""Build and validate a clean staged release workspace without deleting outputs."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

try:
    from tools.build_python_runtime_from_venv import build_python_runtime_from_python
    from tools.build_python_runtime_from_venv import build_python_runtime_from_venv
    from tools.build_python_runtime_from_venv import resolve_python_version
    from tools.check_clean_machine_readiness import check_clean_machine_readiness
    from tools.check_release_preflight import check_release_preflight
    from tools.measure_release_artifact import measure_release_artifact
    from tools.stage_electron_release import stage_electron_release
    from tools.stage_python_runtime import stage_python_runtime
    from tools.write_release_evidence_report import write_release_evidence_report
except ModuleNotFoundError:  # pragma: no cover - used when executed as a script.
    from build_python_runtime_from_venv import build_python_runtime_from_python
    from build_python_runtime_from_venv import build_python_runtime_from_venv
    from build_python_runtime_from_venv import resolve_python_version
    from check_clean_machine_readiness import check_clean_machine_readiness
    from check_release_preflight import check_release_preflight
    from measure_release_artifact import measure_release_artifact
    from stage_electron_release import stage_electron_release
    from stage_python_runtime import stage_python_runtime
    from write_release_evidence_report import write_release_evidence_report


DEFAULT_RELEASE_NAME = "NAIA-Web"


def _empty_or_missing(path: Path) -> bool:
    return not path.exists() or (path.is_dir() and not any(path.iterdir()))


def _failed_workspace(path: Path, reason: str) -> dict[str, Any]:
    return {
        "ok": False,
        "workspace_root": str(path.resolve()),
        "violations": [{"path": str(path), "reason": reason}],
    }


def _run_json_command(args: list[str], *, cwd: Path) -> dict[str, Any]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.stderr:
        sys.stderr.write(completed.stderr)
        if not completed.stderr.endswith("\n"):
            sys.stderr.write("\n")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = {
            "ok": False,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "violations": [{"path": "stdout", "reason": "command did not return JSON"}],
        }
    payload.setdefault("ok", completed.returncode == 0)
    payload["exit_code"] = completed.returncode
    payload["command"] = args
    return payload


def _violations_from(section_name: str, payload: dict[str, Any]) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    for item in payload.get("violations", []):
        violations.append({
            "path": str(item.get("path", "")),
            "reason": f"{section_name}: {item.get('reason', '')}",
        })
    if not payload.get("ok") and not payload.get("violations"):
        reason = payload.get("error") or f"{section_name} failed"
        violations.append({"path": section_name, "reason": str(reason)})
    return violations


def _section_ok(section: Any) -> bool:
    return isinstance(section, dict) and section.get("ok") is True


def summarize_release_workspace(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a compact staged-workspace summary without nested file inventories."""

    sections = payload.get("sections", {}) if isinstance(payload.get("sections"), dict) else {}

    def section(name: str) -> dict[str, Any]:
        value = sections.get(name, {})
        return value if isinstance(value, dict) else {}

    stage_backend = section("stage_backend")
    stage_python = section("stage_python_runtime")
    preflight = section("preflight")
    smoke_backend = section("smoke_backend")
    smoke_web = section("smoke_web_contract")
    clean_machine = section("clean_machine")
    measurement = section("measurement")
    final_evidence = section("final_release_evidence")
    return {
        "ok": bool(payload.get("ok")),
        "source_root": str(payload.get("source_root") or ""),
        "workspace_root": str(payload.get("workspace_root") or ""),
        "release_root": str(payload.get("release_root") or ""),
        "artifact_user_data_root": str(payload.get("artifact_user_data_root") or ""),
        "smoke_user_data_root": str(payload.get("smoke_user_data_root") or ""),
        "created_temporary_workspace": bool(payload.get("created_temporary_workspace")),
        "workspace_scope": "temporary" if payload.get("created_temporary_workspace") else "provided",
        "workspace_retained_for_inspection": bool(payload.get("created_temporary_workspace")),
        "release_root_exists": Path(str(payload.get("release_root") or "")).is_dir()
        if payload.get("release_root")
        else False,
        "require_bundled_python": bool(payload.get("require_bundled_python")),
        "build_clean_python_runtime": bool(payload.get("build_clean_python_runtime")),
        "include_final_evidence": bool(payload.get("include_final_evidence")),
        "python_runtime_dir": str(payload.get("python_runtime_dir") or ""),
        "python_runtime_venv": str(payload.get("python_runtime_venv") or ""),
        "python_runtime_python": str(payload.get("python_runtime_python") or ""),
        "python_runtime_version": str(payload.get("python_runtime_version") or ""),
        "violation_count": len(payload.get("violations", [])),
        "failed_sections": [
            name
            for name, value in sections.items()
            if name != "final_release_evidence" and not _section_ok(value)
        ],
        "stage_backend": {
            "ok": bool(stage_backend.get("ok")) if stage_backend else None,
            "file_count": len(stage_backend.get("files", [])) if isinstance(stage_backend.get("files"), list) else 0,
            "violation_count": len(stage_backend.get("violations", [])) if stage_backend else 0,
        },
        "stage_python_runtime": {
            "ok": bool(stage_python.get("ok")) if stage_python else None,
            "status": str(stage_python.get("status") or "") if stage_python else "",
            "violation_count": len(stage_python.get("violations", [])) if stage_python else 0,
        },
        "build_python_runtime": {
            "ok": bool(section("build_python_runtime").get("ok")) if section("build_python_runtime") else None,
            "base_only": bool(section("build_python_runtime").get("base_only"))
            if section("build_python_runtime") else None,
            "violation_count": len(section("build_python_runtime").get("violations", []))
            if section("build_python_runtime") else 0,
        },
        "preflight": {
            "ok": bool(preflight.get("ok")) if preflight else None,
            "warning_count": len(preflight.get("warnings", [])) if preflight else 0,
            "violation_count": len(preflight.get("violations", [])) if preflight else 0,
        },
        "smoke_backend": {
            "ok": bool(smoke_backend.get("ok")) if smoke_backend else None,
            "exit_code": smoke_backend.get("exit_code") if smoke_backend else None,
            "violation_count": len(smoke_backend.get("violations", [])) if smoke_backend else 0,
        },
        "smoke_web_contract": {
            "ok": bool(smoke_web.get("ok")) if smoke_web else None,
            "exit_code": smoke_web.get("exit_code") if smoke_web else None,
            "violation_count": len(smoke_web.get("violations", [])) if smoke_web else 0,
        },
        "clean_machine": {
            "ok": bool(clean_machine.get("ok")) if clean_machine else None,
            "violation_count": len(clean_machine.get("violations", [])) if clean_machine else 0,
            "file_count": int(clean_machine.get("stats", {}).get("file_count") or 0)
            if isinstance(clean_machine.get("stats"), dict)
            else 0,
            "size_bytes": int(clean_machine.get("stats", {}).get("total_bytes") or 0)
            if isinstance(clean_machine.get("stats"), dict)
            else 0,
        },
        "measurement": {
            "ok": bool(measurement.get("ok")) if measurement else None,
            "violation_count": len(measurement.get("violations", [])) if measurement else 0,
            "file_count": int(measurement.get("stats", {}).get("file_count") or 0)
            if isinstance(measurement.get("stats"), dict)
            else 0,
            "size_bytes": int(measurement.get("stats", {}).get("total_bytes") or 0)
            if isinstance(measurement.get("stats"), dict)
            else 0,
        },
        "final_release_evidence": {
            "ok": bool(final_evidence.get("ok")) if final_evidence else None,
            "failed_sections": list(final_evidence.get("failed_sections") or []) if final_evidence else [],
            "goal_audit_blocker_count": int(
                final_evidence.get("sections", {}).get("goal_audit", {}).get("blocker_count") or 0
            )
            if isinstance(final_evidence.get("sections"), dict)
            else 0,
        },
    }


def run_release_workspace(
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
    include_final_evidence: bool = False,
) -> dict[str, Any]:
    source = Path(source_root).resolve()
    if workspace_root is None:
        workspace = Path(tempfile.mkdtemp(prefix="naia-release-workspace-")).resolve()
        created_temporary = True
    else:
        workspace = Path(workspace_root).resolve()
        created_temporary = False

    if not _empty_or_missing(workspace):
        payload = _failed_workspace(workspace, "workspace root must be missing or empty; refusing to overwrite")
        if output:
            output_path = Path(output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            payload["output"] = str(output_path.resolve())
            output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return payload

    workspace.mkdir(parents=True, exist_ok=True)
    release_root = workspace / DEFAULT_RELEASE_NAME
    backend_root = release_root / "resources" / "naia-backend"
    user_data_root = release_root / "user-data"
    smoke_user_data_root = workspace / "smoke-user-data"

    sections: dict[str, Any] = {}
    violations: list[dict[str, str]] = []
    stage_result = stage_electron_release(source, release_root, copy=True)
    sections["stage_backend"] = {**stage_result.__dict__, "ok": True, "violations": []}

    effective_python_runtime_dir = python_runtime_dir
    if build_clean_python_runtime and not effective_python_runtime_dir:
        runtime_output = workspace / "python-runtime-clean"
        venv_path = Path(python_runtime_venv)
        if not venv_path.is_absolute():
            venv_path = source / venv_path
        try:
            if python_runtime_python and python_runtime_version:
                raise RuntimeError("--python-runtime-python and --python-runtime-version are mutually exclusive")
            if python_runtime_version:
                build_result = build_python_runtime_from_python(
                    python_executable=resolve_python_version(str(python_runtime_version)),
                    output_root=runtime_output,
                    copy=True,
                    base_only=True,
                )
            elif python_runtime_python:
                build_result = build_python_runtime_from_python(
                    python_executable=python_runtime_python,
                    output_root=runtime_output,
                    copy=True,
                    base_only=True,
                )
            else:
                build_result = build_python_runtime_from_venv(
                    venv_root=venv_path,
                    output_root=runtime_output,
                    copy=True,
                    base_only=True,
                )
            sections["build_python_runtime"] = {
                **build_result.__dict__,
                "ok": bool(build_result.ok),
                "violations": [] if build_result.ok else [
                    {"path": str(runtime_output), "reason": "clean Python runtime build failed"}
                ],
            }
            if build_result.ok:
                effective_python_runtime_dir = runtime_output
        except Exception as exc:
            sections["build_python_runtime"] = {
                "ok": False,
                "violations": [{"path": str(runtime_output), "reason": str(exc)}],
            }
    elif build_clean_python_runtime and effective_python_runtime_dir:
        sections["build_python_runtime"] = {
            "ok": True,
            "status": "skipped_existing_runtime_dir",
            "violations": [],
        }

    if effective_python_runtime_dir:
        try:
            runtime_result = stage_python_runtime(release_root, effective_python_runtime_dir, copy=True)
            sections["stage_python_runtime"] = {**runtime_result.__dict__, "ok": True, "violations": []}
        except Exception as exc:
            sections["stage_python_runtime"] = {
                "ok": False,
                "violations": [{"path": str(effective_python_runtime_dir), "reason": str(exc)}],
            }
    elif require_bundled_python:
        sections["stage_python_runtime"] = {
            "ok": False,
            "violations": [{"path": "resources/python", "reason": "bundled Python runtime is required but no runtime source was provided"}],
        }
    else:
        sections["stage_python_runtime"] = {
            "ok": True,
            "status": "not_requested",
            "violations": [],
        }

    sections["preflight"] = check_release_preflight(release_root, require_bundled_python=require_bundled_python)
    sections["smoke_backend"] = _run_json_command(
        [
            sys.executable,
            "-B",
            str(source / "tools" / "smoke_staged_backend.py"),
            str(backend_root),
            "--user-data",
            str(smoke_user_data_root / "backend"),
        ],
        cwd=source,
    )
    sections["smoke_web_contract"] = _run_json_command(
        [
            sys.executable,
            "-B",
            str(source / "tools" / "smoke_remote_web_contract.py"),
            str(backend_root),
            "--user-data",
            str(smoke_user_data_root / "web-contract"),
        ],
        cwd=source,
    )
    sections["clean_machine"] = check_clean_machine_readiness(
        release_root,
        kind="staged-release",
        require_bundled_python=require_bundled_python,
    )
    sections["measurement"] = measure_release_artifact(release_root, defender_scan=False)
    if include_final_evidence:
        sections["final_release_evidence"] = write_release_evidence_report(
            staged_root=release_root,
            packaged_root=workspace / "win-unpacked",
            electron_package=source / "app" / "electron" / "package.json",
            output=None,
            require_bundled_python=require_bundled_python,
            skip_electron_runtime=True,
            skip_backend_smoke=True,
        )

    for section_name, section in sections.items():
        if section_name == "final_release_evidence":
            continue
        if not section.get("ok"):
            violations.extend(_violations_from(section_name, section))

    payload = {
        "ok": not violations,
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_root": str(source),
        "workspace_root": str(workspace),
        "release_root": str(release_root),
        "artifact_user_data_root": str(user_data_root),
        "smoke_user_data_root": str(smoke_user_data_root),
        "created_temporary_workspace": created_temporary,
        "require_bundled_python": bool(require_bundled_python),
        "build_clean_python_runtime": bool(build_clean_python_runtime),
        "include_final_evidence": bool(include_final_evidence),
        "python_runtime_dir": str(Path(effective_python_runtime_dir).resolve()) if effective_python_runtime_dir else "",
        "python_runtime_venv": str(Path(python_runtime_venv).resolve()) if Path(python_runtime_venv).is_absolute() else str(source / python_runtime_venv),
        "python_runtime_python": str(Path(python_runtime_python).resolve()) if python_runtime_python else "",
        "python_runtime_version": str(python_runtime_version or ""),
        "violations": violations,
        "sections": sections,
    }
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload["output"] = str(output_path.resolve())
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create and validate a clean NAIA staged release workspace.")
    parser.add_argument("--source", default=".", help="Source checkout root.")
    parser.add_argument("--workspace", default=None, help="Missing or empty workspace directory to populate.")
    parser.add_argument("--output", default=None, help="Optional JSON evidence output path.")
    parser.add_argument("--python-runtime-dir", default=None, help="Optional Python runtime folder to stage.")
    parser.add_argument(
        "--build-clean-python-runtime",
        action="store_true",
        help="Build a base-only Python runtime from --python-runtime-venv and stage it.",
    )
    parser.add_argument("--python-runtime-venv", default="venv", help="Virtualenv used to locate the base Python runtime.")
    parser.add_argument("--python-runtime-python", default=None, help="Base Python executable used for --build-clean-python-runtime.")
    parser.add_argument("--python-runtime-version", default=None, help="Resolve a base Python executable by version, for example 3.12.")
    parser.add_argument("--require-bundled-python", action="store_true", help="Fail unless resources/python is staged.")
    parser.add_argument(
        "--include-final-evidence",
        action="store_true",
        help="Also embed the strict release evidence report for this clean workspace without affecting staged-workspace success.",
    )
    parser.add_argument("--summary", action="store_true", help="Print a compact staged workspace summary.")
    args = parser.parse_args(argv)

    payload = run_release_workspace(
        source_root=args.source,
        workspace_root=args.workspace,
        output=args.output,
        python_runtime_dir=args.python_runtime_dir,
        build_clean_python_runtime=args.build_clean_python_runtime,
        python_runtime_venv=args.python_runtime_venv,
        python_runtime_python=args.python_runtime_python,
        python_runtime_version=args.python_runtime_version,
        require_bundled_python=args.require_bundled_python,
        include_final_evidence=args.include_final_evidence,
    )
    if args.summary:
        payload = summarize_release_workspace(payload)
    json.dump(payload, sys.stdout, ensure_ascii=True, indent=2)
    sys.stdout.write("\n")
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
