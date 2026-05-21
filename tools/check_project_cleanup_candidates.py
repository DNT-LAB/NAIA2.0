"""Validate non-destructive cleanup/delete candidate inventory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


DEFAULT_MANIFEST = Path("release_assets/manifests/project_cleanup_candidates.json")
DEFAULT_GITIGNORE = Path(".gitignore")
REQUIRED_GROUPS = {
    "root_electron_residue",
    "legacy_remote_web_source",
    "runtime_generated_roots",
    "root_sample_and_debug_assets",
    "legacy_desktop_reference",
}
RESOLVED_STATUSES = {
    "resolved_removed",
    "resolved_moved",
    "resolved_not_present",
}


def _repo_relative(path: Path, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return path.as_posix()


def _is_safe_relative_path(value: str) -> bool:
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts


def _path_may_be_glob(value: str) -> bool:
    return any(char in value for char in "*?[")


def _validate_candidate_group(group: dict[str, Any]) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    group_id = str(group.get("id") or "")
    for key in ("id", "owner", "status", "decision", "replacement"):
        if not str(group.get(key) or "").strip():
            violations.append({
                "type": "candidate_missing_field",
                "path": group_id or "<unknown>",
                "reason": f"missing required field: {key}",
            })

    paths = group.get("paths")
    if not isinstance(paths, list) or not paths:
        violations.append({
            "type": "candidate_missing_paths",
            "path": group_id,
            "reason": "candidate group must include at least one path or glob",
        })
    else:
        for raw_path in paths:
            path = str(raw_path or "")
            if not path:
                violations.append({
                    "type": "candidate_empty_path",
                    "path": group_id,
                    "reason": "candidate path must not be empty",
                })
            elif not _is_safe_relative_path(path):
                violations.append({
                    "type": "candidate_unsafe_path",
                    "path": path,
                    "reason": "candidate paths must be relative",
                })

    gates = group.get("required_gates")
    if not isinstance(gates, list) or not gates:
        violations.append({
            "type": "candidate_missing_required_gates",
            "path": group_id,
            "reason": "candidate group must declare required gates",
        })

    gitignore_patterns = group.get("gitignore_required_patterns", [])
    if gitignore_patterns is not None and not isinstance(gitignore_patterns, list):
        violations.append({
            "type": "candidate_invalid_gitignore_required_patterns",
            "path": group_id,
            "reason": "gitignore_required_patterns must be a list when present",
        })
    elif isinstance(gitignore_patterns, list):
        for pattern in gitignore_patterns:
            if not isinstance(pattern, str) or not pattern.strip():
                violations.append({
                    "type": "candidate_invalid_gitignore_required_pattern",
                    "path": group_id,
                    "reason": "gitignore_required_patterns must contain non-empty strings",
                })
    return violations


def check_project_cleanup_candidates(
    *,
    repo_root: Path = Path("."),
    manifest_path: Path = DEFAULT_MANIFEST,
    gitignore_path: Path = DEFAULT_GITIGNORE,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    manifest_path = manifest_path if manifest_path.is_absolute() else repo_root / manifest_path
    gitignore_path = gitignore_path if gitignore_path.is_absolute() else repo_root / gitignore_path

    if not manifest_path.is_file():
        return {
            "ok": False,
            "manifest": _repo_relative(manifest_path, repo_root),
            "violations": [{"type": "missing_manifest", "path": _repo_relative(manifest_path, repo_root)}],
            "warnings": [],
        }

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    groups = manifest.get("candidate_groups", [])
    violations: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    if manifest.get("delete_approval_required") is not True:
        violations.append({
            "type": "delete_approval_not_required",
            "path": _repo_relative(manifest_path, repo_root),
            "reason": "cleanup candidates must require explicit deletion approval",
        })
    if not isinstance(groups, list) or not groups:
        violations.append({
            "type": "missing_candidate_groups",
            "path": _repo_relative(manifest_path, repo_root),
            "reason": "candidate_groups must be a non-empty list",
        })
        groups = []

    seen: set[str] = set()
    gitignore_lines: set[str] = set()
    if gitignore_path.is_file():
        gitignore_lines = {
            line.strip()
            for line in gitignore_path.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
    for group in groups:
        if not isinstance(group, dict):
            violations.append({
                "type": "invalid_candidate_group",
                "path": "<unknown>",
                "reason": "candidate group must be an object",
            })
            continue
        group_id = str(group.get("id") or "")
        if group_id in seen:
            violations.append({
                "type": "duplicate_candidate_group",
                "path": group_id,
                "reason": "candidate group ids must be unique",
            })
        seen.add(group_id)
        violations.extend(_validate_candidate_group(group))
        if group.get("requires_explicit_delete_approval") is not True:
            violations.append({
                "type": "candidate_missing_delete_approval",
                "path": group_id,
                "reason": "each candidate group must require explicit delete approval",
            })

        status = str(group.get("status") or "")
        gitignore_patterns = group.get("gitignore_required_patterns", [])
        if not isinstance(gitignore_patterns, list):
            gitignore_patterns = []
        for pattern in gitignore_patterns:
            pattern_text = str(pattern).strip()
            if pattern_text and pattern_text not in gitignore_lines:
                violations.append({
                    "type": "candidate_gitignore_pattern_missing",
                    "path": group_id,
                    "reason": f".gitignore must contain {pattern_text}",
                })
        for raw_path in group.get("paths", []):
            path = str(raw_path or "")
            if not path or not _is_safe_relative_path(path) or _path_may_be_glob(path):
                continue
            if status in RESOLVED_STATUSES:
                continue
            if not (repo_root / path).exists():
                warnings.append({
                    "type": "candidate_path_not_present",
                    "path": path,
                    "reason": "candidate path is not present in the current checkout",
                })

    missing = sorted(REQUIRED_GROUPS - seen)
    for group_id in missing:
        violations.append({
            "type": "missing_required_candidate_group",
            "path": group_id,
            "reason": "required cleanup candidate group is missing",
        })

    return {
        "ok": not violations,
        "manifest": _repo_relative(manifest_path, repo_root),
        "candidate_group_count": len(groups),
        "required_group_count": len(REQUIRED_GROUPS),
        "delete_approval_required": manifest.get("delete_approval_required") is True,
        "violations": violations,
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args(argv)

    payload = check_project_cleanup_candidates(repo_root=args.repo_root, manifest_path=args.manifest)
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
