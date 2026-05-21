"""Validate completion evidence for the project layout/runtime boundary rounds."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


DEFAULT_MANIFEST = Path("release_assets/manifests/project_layout_round_completion.json")
EXPECTED_ROUNDS = set(range(10))
ACCEPTED_STATUSES = {
    "complete",
    "complete_as_policy_gate",
    "complete_non_destructive",
}
EXPECTED_ALL_STATUS = "complete_with_non_destructive_cleanup_candidates"


def _repo_relative(path: Path, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return path.as_posix()


def _is_safe_relative_path(value: str) -> bool:
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts


def _looks_like_command(value: str) -> bool:
    return value.startswith("python ") or value.startswith("node ") or value.startswith("npm ")


def _is_glob_path(value: str) -> bool:
    return any(char in value for char in "*?[")


def _validate_evidence_path(repo_root: Path, value: str) -> dict[str, str] | None:
    if _looks_like_command(value):
        return None
    if not _is_safe_relative_path(value):
        return {
            "type": "unsafe_round_evidence_path",
            "path": value,
            "reason": "round evidence paths must be repository-relative",
        }
    if _is_glob_path(value):
        return None
    if not (repo_root / value).exists():
        return {
            "type": "missing_round_evidence_path",
            "path": value,
            "reason": "round evidence path is not present in the current checkout",
        }
    return None


def check_project_layout_round_completion(
    *,
    repo_root: Path = Path("."),
    manifest_path: Path = DEFAULT_MANIFEST,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    manifest_path = manifest_path if manifest_path.is_absolute() else repo_root / manifest_path

    if not manifest_path.is_file():
        return {
            "ok": False,
            "manifest": _repo_relative(manifest_path, repo_root),
            "violations": [{"type": "missing_manifest", "path": _repo_relative(manifest_path, repo_root)}],
            "warnings": [],
        }

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    violations: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    if manifest.get("all_rounds_status") != EXPECTED_ALL_STATUS:
        violations.append({
            "type": "unexpected_all_rounds_status",
            "path": _repo_relative(manifest_path, repo_root),
            "reason": f"all_rounds_status must be {EXPECTED_ALL_STATUS}",
        })

    plan_path = str(manifest.get("plan") or "")
    if not plan_path or not _is_safe_relative_path(plan_path) or not (repo_root / plan_path).is_file():
        violations.append({
            "type": "missing_plan_document",
            "path": plan_path or "<empty>",
            "reason": "round completion manifest must point to the layout plan",
        })

    rounds = manifest.get("rounds", [])
    if not isinstance(rounds, list):
        violations.append({
            "type": "invalid_rounds",
            "path": _repo_relative(manifest_path, repo_root),
            "reason": "rounds must be a list",
        })
        rounds = []

    seen_rounds: set[int] = set()
    for item in rounds:
        if not isinstance(item, dict):
            violations.append({
                "type": "invalid_round_entry",
                "path": "<unknown>",
                "reason": "round entries must be objects",
            })
            continue

        round_number = item.get("round")
        if not isinstance(round_number, int):
            violations.append({
                "type": "invalid_round_number",
                "path": str(round_number),
                "reason": "round number must be an integer",
            })
            continue
        if round_number in seen_rounds:
            violations.append({
                "type": "duplicate_round",
                "path": str(round_number),
                "reason": "round numbers must be unique",
            })
        seen_rounds.add(round_number)

        status = str(item.get("status") or "")
        if status not in ACCEPTED_STATUSES:
            violations.append({
                "type": "unexpected_round_status",
                "path": str(round_number),
                "reason": f"status must be one of {sorted(ACCEPTED_STATUSES)}",
            })

        evidence = item.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            violations.append({
                "type": "missing_round_evidence",
                "path": str(round_number),
                "reason": "each round must declare evidence",
            })
        else:
            for raw_value in evidence:
                value = str(raw_value or "")
                if not value:
                    violations.append({
                        "type": "empty_round_evidence",
                        "path": str(round_number),
                        "reason": "round evidence entries must not be empty",
                    })
                    continue
                path_violation = _validate_evidence_path(repo_root, value)
                if path_violation is not None:
                    violations.append(path_violation)

        if round_number == 9 and item.get("destructive_actions_deferred") is not True:
            violations.append({
                "type": "round_9_destructive_actions_not_deferred",
                "path": "9",
                "reason": "cleanup/delete round must defer destructive actions until explicit approval",
            })
        if round_number != 9 and item.get("destructive_actions_deferred") is True:
            warnings.append({
                "type": "unexpected_destructive_deferred_marker",
                "path": str(round_number),
                "reason": "destructive_actions_deferred is only expected on Round 9",
            })

    missing_rounds = sorted(EXPECTED_ROUNDS - seen_rounds)
    extra_rounds = sorted(seen_rounds - EXPECTED_ROUNDS)
    for round_number in missing_rounds:
        violations.append({
            "type": "missing_required_round",
            "path": str(round_number),
            "reason": "round completion evidence must cover Round 0 through Round 9",
        })
    for round_number in extra_rounds:
        violations.append({
            "type": "unexpected_round",
            "path": str(round_number),
            "reason": "this completion manifest is scoped to Round 0 through Round 9",
        })

    commands = manifest.get("required_commands", [])
    if not isinstance(commands, list) or not commands:
        violations.append({
            "type": "missing_required_commands",
            "path": _repo_relative(manifest_path, repo_root),
            "reason": "round completion manifest must declare required validation commands",
        })
    else:
        for command in commands:
            command_text = str(command or "")
            if not command_text.startswith(("python tools/", "python tools\\")):
                violations.append({
                    "type": "unexpected_required_command",
                    "path": command_text,
                    "reason": "required validation commands should be explicit python tools checks",
                })

    return {
        "ok": not violations,
        "manifest": _repo_relative(manifest_path, repo_root),
        "plan": plan_path,
        "all_rounds_status": manifest.get("all_rounds_status"),
        "round_count": len(rounds),
        "required_round_count": len(EXPECTED_ROUNDS),
        "required_command_count": len(commands) if isinstance(commands, list) else 0,
        "violations": violations,
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args(argv)

    payload = check_project_layout_round_completion(repo_root=args.repo_root, manifest_path=args.manifest)
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
