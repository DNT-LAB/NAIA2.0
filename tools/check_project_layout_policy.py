"""Validate NAIA2 project layout and runtime boundary policy."""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


DEFAULT_MANIFEST = Path("release_assets/manifests/project_layout_policy.json")


def _repo_relative(path: Path, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return path.as_posix()


def _is_safe_relative_path(value: str) -> bool:
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _check_relative_file(repo_root: Path, raw_path: str, violations: list[dict[str, str]], reason: str) -> Path | None:
    if not _is_safe_relative_path(raw_path):
        violations.append({"type": "unsafe_path", "path": raw_path, "reason": reason})
        return None
    path = repo_root / raw_path
    if not path.is_file():
        violations.append({"type": "missing_file", "path": raw_path, "reason": reason})
        return None
    return path


def _check_relative_dir(repo_root: Path, raw_path: str, violations: list[dict[str, str]], reason: str) -> Path | None:
    if not _is_safe_relative_path(raw_path):
        violations.append({"type": "unsafe_path", "path": raw_path, "reason": reason})
        return None
    path = repo_root / raw_path
    if not path.is_dir():
        violations.append({"type": "missing_directory", "path": raw_path, "reason": reason})
        return None
    return path


def _check_policy_document(repo_root: Path, manifest: dict[str, Any]) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    policy_doc = str(manifest.get("policy_document") or "")
    path = _check_relative_file(repo_root, policy_doc, violations, "policy document is required")
    if path is None:
        return violations

    text = _read_text(path)
    required_terms = [
        "Python Headless Web",
        "app/web/remote",
        "Electron is optional",
        "Legacy PyQt6",
    ]
    for term in required_terms:
        if term not in text:
            violations.append({
                "type": "policy_document_missing_term",
                "path": policy_doc,
                "reason": f"missing required term: {term}",
            })
    return violations


def _git_tracked_paths(repo_root: Path, root: str) -> list[str]:
    git_dir = repo_root / ".git"
    if not git_dir.exists():
        return []
    try:
        result = subprocess.run(
            ["git", "ls-files", "--", root],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError:
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _check_remote_publish_boundary(repo_root: Path, manifest: dict[str, Any]) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    remote_publish = manifest.get("remote_publish") if isinstance(manifest.get("remote_publish"), dict) else {}
    policy_doc = str(manifest.get("policy_document") or "")

    local_only_roots = [str(root).strip().strip("/\\") for root in remote_publish.get("local_only_roots", [])]
    if "tests" not in local_only_roots:
        violations.append({
            "type": "remote_publish_missing_tests_local_only",
            "path": "remote_publish.local_only_roots",
            "reason": "tests must be declared as local-development-only",
        })

    for root in local_only_roots:
        if not root:
            continue
        if not _is_safe_relative_path(root):
            violations.append({
                "type": "unsafe_remote_publish_local_only_root",
                "path": root,
                "reason": "remote publish local-only roots must be relative",
            })
            continue
        tracked = _git_tracked_paths(repo_root, root)
        if tracked:
            violations.append({
                "type": "remote_publish_local_only_root_tracked",
                "path": root,
                "reason": f"local-only root has tracked files: {len(tracked)}",
            })

    if policy_doc:
        policy_path = repo_root / policy_doc
        if policy_path.is_file():
            policy_text = _read_text(policy_path)
            for term in remote_publish.get("required_terms", []):
                term_text = str(term)
                if term_text and term_text not in policy_text:
                    violations.append({
                        "type": "policy_document_missing_remote_publish_term",
                        "path": policy_doc,
                        "reason": f"missing remote publish term: {term_text}",
                    })
    return violations


def _check_default_runtime(repo_root: Path, manifest: dict[str, Any]) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    runtime = manifest.get("default_runtime") if isinstance(manifest.get("default_runtime"), dict) else {}

    _check_relative_file(repo_root, str(runtime.get("entrypoint") or ""), violations, "default Python entrypoint is required")
    _check_relative_file(repo_root, str(runtime.get("requirements") or ""), violations, "headless requirements are required")

    required_terms = [str(term).lower() for term in runtime.get("required_launcher_terms", [])]
    forbidden_terms = [str(term).lower() for term in runtime.get("forbidden_launcher_terms", [])]
    for launcher in runtime.get("launchers", []):
        launcher_path = _check_relative_file(repo_root, str(launcher), violations, "default launcher is required")
        if launcher_path is None:
            continue
        text = _read_text(launcher_path).lower()
        for term in required_terms:
            if term and term not in text:
                violations.append({
                    "type": "launcher_missing_required_term",
                    "path": str(launcher),
                    "reason": f"missing required term: {term}",
                })
        for term in forbidden_terms:
            if term and term in text:
                violations.append({
                    "type": "launcher_contains_forbidden_term",
                    "path": str(launcher),
                    "reason": f"default launcher must not require {term}",
                })
    return violations


def _check_legacy_desktop_boundary(repo_root: Path, manifest: dict[str, Any]) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    legacy = manifest.get("legacy_desktop") if isinstance(manifest.get("legacy_desktop"), dict) else {}
    runtime = manifest.get("default_runtime") if isinstance(manifest.get("default_runtime"), dict) else {}
    policy_doc = str(manifest.get("policy_document") or "")

    root = str(legacy.get("root") or "")
    entrypoint = str(legacy.get("entrypoint") or "")

    if legacy.get("status") != "removed":
        violations.append({
            "type": "legacy_desktop_not_removed",
            "path": "legacy_desktop.status",
            "reason": "legacy desktop status must be removed",
        })

    for raw_path, violation_type, reason in (
        (root, "legacy_desktop_root_still_present", "removed legacy desktop root must stay absent"),
        (entrypoint, "legacy_desktop_entrypoint_still_present", "removed legacy desktop entrypoint must stay absent"),
    ):
        if not _is_safe_relative_path(raw_path):
            violations.append({"type": "unsafe_path", "path": raw_path, "reason": reason})
            continue
        if (repo_root / raw_path).exists():
            violations.append({
                "type": violation_type,
                "path": raw_path,
                "reason": reason,
            })

    if policy_doc:
        policy_path = repo_root / policy_doc
        if policy_path.is_file():
            policy_text = _read_text(policy_path)
            for term in ("Legacy Desktop source must stay removed", "git history"):
                if term not in policy_text:
                    violations.append({
                        "type": "policy_document_missing_legacy_boundary_term",
                        "path": policy_doc,
                        "reason": f"missing legacy boundary term: {term}",
                    })

    forbidden_terms = [
        str(term).lower()
        for term in legacy.get("forbidden_default_launcher_terms", [])
        if str(term).strip()
    ]
    for launcher in runtime.get("launchers", []):
        launcher_path = repo_root / str(launcher)
        if not launcher_path.is_file():
            continue
        text = _read_text(launcher_path).lower()
        for term in forbidden_terms:
            if term in text:
                violations.append({
                    "type": "launcher_references_legacy_desktop",
                    "path": str(launcher),
                    "reason": f"default launcher must not reference legacy desktop term: {term}",
                })
    return violations


def _check_remote_web(repo_root: Path, manifest: dict[str, Any]) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    remote = manifest.get("canonical_remote_web") if isinstance(manifest.get("canonical_remote_web"), dict) else {}
    web_path = str(remote.get("path") or "")
    web_dir = _check_relative_dir(repo_root, web_path, violations, "canonical Remote Web source directory is required")
    required_files = [str(item) for item in remote.get("required_files", [])]
    if web_dir is not None:
        for filename in required_files:
            if not _is_safe_relative_path(filename) or "/" in filename or "\\" in filename:
                violations.append({
                    "type": "unsafe_remote_web_file",
                    "path": filename,
                    "reason": "remote web required file must be a filename",
                })
                continue
            if not (web_dir / filename).is_file():
                violations.append({
                    "type": "missing_remote_web_file",
                    "path": f"{web_path}/{filename}",
                    "reason": "canonical Remote Web required file is missing",
                })

    module_name = str(remote.get("resolver_module") or "")
    function_name = str(remote.get("resolver_function") or "")
    if module_name and function_name and web_dir is not None:
        inserted_repo_root = False
        try:
            repo_root_text = str(repo_root)
            if repo_root_text not in sys.path:
                sys.path.insert(0, repo_root_text)
                inserted_repo_root = True
            module = importlib.import_module(module_name)
            resolver = getattr(module, function_name)
            resolved = Path(resolver(repo_root, env={})).resolve()
            if resolved != web_dir.resolve():
                violations.append({
                    "type": "remote_web_resolver_not_canonical",
                    "path": f"{module_name}.{function_name}",
                    "reason": f"resolved {_repo_relative(resolved, repo_root)} instead of {web_path}",
                })
        except Exception as exc:
            violations.append({
                "type": "remote_web_resolver_failed",
                "path": f"{module_name}.{function_name}",
                "reason": str(exc),
            })
        finally:
            if inserted_repo_root:
                try:
                    sys.path.remove(repo_root_text)
                except ValueError:
                    pass
    return violations


def _check_optional_electron(repo_root: Path, manifest: dict[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    violations: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    electron = manifest.get("optional_electron") if isinstance(manifest.get("optional_electron"), dict) else {}

    _check_relative_dir(repo_root, str(electron.get("root") or ""), violations, "optional Electron root is required")
    _check_relative_file(repo_root, str(electron.get("main") or ""), violations, "Electron main process source is required")
    _check_relative_file(repo_root, str(electron.get("package_manifest") or ""), violations, "Electron package manifest is required")

    for root in electron.get("allowed_roots", []):
        raw_root = str(root)
        if not _is_safe_relative_path(raw_root):
            violations.append({
                "type": "unsafe_electron_allowed_root",
                "path": raw_root,
                "reason": "Electron allowed roots must be relative",
            })

    for raw_path in electron.get("root_residue_warning_paths", []):
        path = repo_root / str(raw_path)
        if path.exists():
            warnings.append({
                "type": "root_electron_residue",
                "path": str(raw_path),
                "reason": "root-level Electron residue should be removed or moved in a later cleanup round",
            })
    return violations, warnings


def _check_runtime_only_roots(manifest: dict[str, Any]) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    for root in manifest.get("runtime_only_roots", []):
        raw_root = str(root)
        if not _is_safe_relative_path(raw_root):
            violations.append({
                "type": "unsafe_runtime_only_root",
                "path": raw_root,
                "reason": "runtime-only roots must be relative",
            })
    return violations


def _check_evidence_manifests(repo_root: Path, manifest: dict[str, Any]) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    evidence_manifests = manifest.get("evidence_manifests")
    if not isinstance(evidence_manifests, dict):
        return [{
            "type": "missing_evidence_manifests",
            "path": "evidence_manifests",
            "reason": "layout policy must reference round completion, cleanup candidate, runtime distribution, and refactor-plan execution manifests",
        }]

    for key in (
        "round_completion",
        "cleanup_candidates",
        "runtime_distribution_tracks",
        "refactor_plan_execution",
    ):
        raw_path = str(evidence_manifests.get(key) or "")
        if not raw_path:
            violations.append({
                "type": "missing_evidence_manifest_reference",
                "path": key,
                "reason": f"missing evidence manifest reference: {key}",
            })
            continue
        _check_relative_file(repo_root, raw_path, violations, f"evidence manifest is required: {key}")
    return violations


def check_project_layout_policy(
    *,
    repo_root: Path = Path("."),
    manifest_path: Path = DEFAULT_MANIFEST,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    manifest_path = manifest_path if manifest_path.is_absolute() else repo_root / manifest_path

    if not manifest_path.is_file():
        return {
            "ok": False,
            "contract": _repo_relative(manifest_path, repo_root),
            "violations": [{"type": "missing_manifest", "path": _repo_relative(manifest_path, repo_root)}],
            "warnings": [],
        }

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    violations: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    violations.extend(_check_policy_document(repo_root, manifest))
    violations.extend(_check_remote_publish_boundary(repo_root, manifest))
    violations.extend(_check_default_runtime(repo_root, manifest))
    violations.extend(_check_legacy_desktop_boundary(repo_root, manifest))
    violations.extend(_check_remote_web(repo_root, manifest))
    electron_violations, electron_warnings = _check_optional_electron(repo_root, manifest)
    violations.extend(electron_violations)
    warnings.extend(electron_warnings)
    violations.extend(_check_runtime_only_roots(manifest))
    violations.extend(_check_evidence_manifests(repo_root, manifest))

    runtime = manifest.get("default_runtime") if isinstance(manifest.get("default_runtime"), dict) else {}
    legacy = manifest.get("legacy_desktop") if isinstance(manifest.get("legacy_desktop"), dict) else {}
    remote = manifest.get("canonical_remote_web") if isinstance(manifest.get("canonical_remote_web"), dict) else {}
    electron = manifest.get("optional_electron") if isinstance(manifest.get("optional_electron"), dict) else {}
    evidence_manifests = manifest.get("evidence_manifests") if isinstance(manifest.get("evidence_manifests"), dict) else {}
    return {
        "ok": not violations,
        "contract": _repo_relative(manifest_path, repo_root),
        "default_runtime": runtime.get("name", ""),
        "default_entrypoint": runtime.get("entrypoint", ""),
        "legacy_desktop_root": legacy.get("root", ""),
        "legacy_desktop_status": legacy.get("status", ""),
        "canonical_remote_web": remote.get("path", ""),
        "optional_electron_root": electron.get("root", ""),
        "round_completion_manifest": evidence_manifests.get("round_completion", ""),
        "cleanup_candidates_manifest": evidence_manifests.get("cleanup_candidates", ""),
        "runtime_distribution_tracks_manifest": evidence_manifests.get("runtime_distribution_tracks", ""),
        "refactor_plan_execution_manifest": evidence_manifests.get("refactor_plan_execution", ""),
        "violation_count": len(violations),
        "warning_count": len(warnings),
        "violations": violations,
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args(argv)

    payload = check_project_layout_policy(repo_root=args.repo_root, manifest_path=args.manifest)
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
