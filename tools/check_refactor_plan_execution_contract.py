"""Validate executable refactor-plan contracts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any


DEFAULT_MANIFEST = Path("release_assets/manifests/refactor_plan_execution_contract.json")


def _repo_relative(path: Path, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return path.as_posix()


def _is_safe_relative_path(value: str) -> bool:
    path = Path(value)
    return bool(value) and not path.is_absolute() and ".." not in path.parts


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _normalize_heading(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def _heading_titles(text: str) -> set[str]:
    headings: set[str] = set()
    for line in text.splitlines():
        match = re.match(r"^\s{0,3}#{2,6}\s+(.+?)\s*$", line)
        if match:
            headings.add(_normalize_heading(match.group(1)))
    return headings


def _contains_any(text: str, terms: list[str]) -> bool:
    lowered = text.casefold()
    return any(str(term).strip().casefold() in lowered for term in terms if str(term).strip())


def _round_blocks(text: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    current_title = ""
    current_lines: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^##\s+(Round\s+.+?)\s*$", line)
        if match:
            if current_title:
                blocks.append((current_title, "\n".join(current_lines)))
            current_title = match.group(1).strip()
            current_lines = []
            continue
        if current_title:
            current_lines.append(line)
    if current_title:
        blocks.append((current_title, "\n".join(current_lines)))
    return blocks


def _section_has_list_item(block: str, section: str) -> bool:
    in_section = False
    for line in block.splitlines():
        if re.match(rf"^###\s+{re.escape(section)}\s*$", line, flags=re.IGNORECASE):
            in_section = True
            continue
        if in_section and line.startswith("### "):
            return False
        if in_section and re.match(r"^\s*-\s+(\[[ xX]\]\s+)?\S+", line):
            return True
    return False


def _check_relative_file(
    repo_root: Path,
    raw_path: str,
    violations: list[dict[str, str]],
    reason: str,
) -> Path | None:
    if not _is_safe_relative_path(raw_path):
        violations.append({"type": "unsafe_or_empty_path", "path": raw_path or "<empty>", "reason": reason})
        return None
    path = repo_root / raw_path
    if not path.is_file():
        violations.append({"type": "missing_file", "path": raw_path, "reason": reason})
        return None
    return path


def _check_plan_document(
    repo_root: Path,
    plan: dict[str, Any],
    required_phase_terms: dict[str, list[str]],
) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    raw_path = str(plan.get("path") or "")
    path = _check_relative_file(repo_root, raw_path, violations, "tracked refactor plan document is required")
    if path is None:
        return violations

    text = _read_text(path)
    headings = _heading_titles(text)
    for section in plan.get("required_sections", []):
        section_text = str(section)
        if _normalize_heading(section_text) not in headings:
            violations.append({
                "type": "plan_missing_required_section",
                "path": raw_path,
                "reason": f"missing required section: {section_text}",
            })

    for phase, terms in required_phase_terms.items():
        if not _contains_any(text, [str(term) for term in terms]):
            violations.append({
                "type": "plan_missing_phase_terms",
                "path": raw_path,
                "reason": f"plan must mention phase {phase}",
            })

    if str(plan.get("kind") or "") == "multi_round":
        rounds = _round_blocks(text)
        if not rounds:
            violations.append({
                "type": "plan_missing_rounds",
                "path": raw_path,
                "reason": "multi_round plan must contain at least one Round heading",
            })
        for title, block in rounds:
            for section in ("Checklist", "When Done"):
                if _normalize_heading(section) not in _heading_titles(block):
                    violations.append({
                        "type": "round_missing_required_section",
                        "path": raw_path,
                        "reason": f"{title} is missing {section}",
                    })
                elif not _section_has_list_item(block, section):
                    violations.append({
                        "type": "round_section_without_items",
                        "path": raw_path,
                        "reason": f"{title} {section} must contain at least one list item",
                    })

    return violations


def check_refactor_plan_execution_contract(
    *,
    repo_root: Path = Path("."),
    manifest_path: Path = DEFAULT_MANIFEST,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    manifest_path = manifest_path if manifest_path.is_absolute() else repo_root / manifest_path
    violations: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    if not manifest_path.is_file():
        return {
            "ok": False,
            "manifest": _repo_relative(manifest_path, repo_root),
            "violations": [{"type": "missing_manifest", "path": _repo_relative(manifest_path, repo_root)}],
            "warnings": warnings,
        }

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    contract_document = str(manifest.get("contract_document") or "")
    _check_relative_file(repo_root, contract_document, violations, "contract document is required")

    required_phase_terms = manifest.get("required_phase_terms")
    if not isinstance(required_phase_terms, dict) or not required_phase_terms:
        violations.append({
            "type": "missing_required_phase_terms",
            "path": _repo_relative(manifest_path, repo_root),
            "reason": "required_phase_terms must be a non-empty object",
        })
        required_phase_terms = {}
    normalized_phase_terms: dict[str, list[str]] = {}
    for key, value in required_phase_terms.items():
        phase = str(key)
        if not isinstance(value, list) or not value:
            violations.append({
                "type": "invalid_required_phase_terms",
                "path": phase,
                "reason": "each required phase must map to a non-empty term list",
            })
            continue
        terms = [str(term) for term in value if str(term).strip()]
        if not terms:
            violations.append({
                "type": "invalid_required_phase_terms",
                "path": phase,
                "reason": "each required phase must include at least one non-empty term",
            })
            continue
        normalized_phase_terms[phase] = terms

    for raw_path in manifest.get("required_tooling", []):
        _check_relative_file(repo_root, str(raw_path), violations, "required plan execution tooling is missing")

    plans = manifest.get("tracked_plan_documents")
    if not isinstance(plans, list) or not plans:
        violations.append({
            "type": "missing_tracked_plan_documents",
            "path": _repo_relative(manifest_path, repo_root),
            "reason": "tracked_plan_documents must be a non-empty list",
        })
        plans = []
    for plan in plans:
        if not isinstance(plan, dict):
            violations.append({
                "type": "invalid_tracked_plan_document",
                "path": "<unknown>",
                "reason": "tracked plan document must be an object",
            })
            continue
        required_sections = plan.get("required_sections")
        if not isinstance(required_sections, list) or not required_sections:
            violations.append({
                "type": "invalid_plan_required_sections",
                "path": str(plan.get("path") or "<unknown>"),
                "reason": "required_sections must be a non-empty list",
            })
            continue
        violations.extend(_check_plan_document(repo_root, plan, normalized_phase_terms))

    return {
        "ok": not violations,
        "manifest": _repo_relative(manifest_path, repo_root),
        "contract_document": contract_document,
        "tracked_plan_count": len(plans),
        "required_phase_count": len(normalized_phase_terms),
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

    payload = check_refactor_plan_execution_contract(repo_root=args.repo_root, manifest_path=args.manifest)
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
