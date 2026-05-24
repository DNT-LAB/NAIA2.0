"""Audit whether the final headless/Electron roadmap is actually complete.

The tool is deliberately strict. It treats unchecked roadmap items and missing
runtime artifacts as blockers instead of inferring completion from passing
unit tests or partial scaffolding.
"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re
import sys
from typing import Any

try:
    from tools.check_backend_runtime_strategy import check_backend_runtime_strategy
    from tools.check_electron_dependency_readiness import check_electron_dependency_readiness
    from tools.check_electron_shell_contract import check_electron_shell_contract
    from tools.check_headless_core_boundary import validation_payload as check_headless_core_boundary_payload
    from tools.check_release_distribution_strategy import check_release_distribution_strategy
    from tools.check_remote_web_feature_contract import validate_remote_web_feature_contract
    from tools.check_runtime_asset_classification import validation_payload as check_runtime_asset_classification_payload
    from tools.check_runtime_write_policy import check_runtime_write_policy
    from tools.check_source_layout_contract import check_source_layout_contract
except ModuleNotFoundError:  # pragma: no cover - used when executed as a script.
    from check_backend_runtime_strategy import check_backend_runtime_strategy
    from check_electron_dependency_readiness import check_electron_dependency_readiness
    from check_electron_shell_contract import check_electron_shell_contract
    from check_headless_core_boundary import validation_payload as check_headless_core_boundary_payload
    from check_release_distribution_strategy import check_release_distribution_strategy
    from check_remote_web_feature_contract import validate_remote_web_feature_contract
    from check_runtime_asset_classification import validation_payload as check_runtime_asset_classification_payload
    from check_runtime_write_policy import check_runtime_write_policy
    from check_source_layout_contract import check_source_layout_contract


DEFAULT_PLAN = Path("refactor_plans/final_headless_electron_release_reorganization_plan.md")
DEFAULT_ELECTRON_PACKAGE = Path("app/electron/package.json")
DEFAULT_PACKAGED_ROOT = Path("app/electron/dist/win-unpacked")
DEFAULT_PORTABLE_WORKSPACE_EVIDENCE = Path("app/electron/dist/electron_workspace_release_evidence.json")
DEFAULT_COMPLETION_EVIDENCE_MAP = Path("release_assets/manifests/final_goal_completion_evidence.json")

REQUIRED_PACKAGE_SCRIPTS = (
    "release:check",
    "test:main-contract",
    "deps:plan",
    "deps:plan:summary",
    "deps:install",
    "deps:ci",
    "release:evidence",
    "release:evidence:summary",
    "release:evidence:fresh",
    "release:evidence:fresh:summary",
    "release:workspace",
    "release:workspace:summary",
    "release:workspace:evidence",
    "release:workspace:evidence:summary",
    "release:workspace:bundled-python",
    "release:workspace:bundled-python:evidence",
    "release:portable:workspace:plan",
    "release:portable:workspace:plan:summary",
    "release:portable:workspace",
    "release:portable:workspace:bundled-python",
    "release:final:plan",
    "release:final:plan:summary",
    "release:final",
    "release:final:smoke",
    "release:final:install",
    "release:final:install:scan",
    "release:final:bundled-python",
    "release:final:bundled-python:scan",
    "preflight:electron-deps",
    "preflight:electron-deps:summary",
    "goal:audit:summary",
    "check:source-layout",
    "preflight:packaging-inputs",
    "preflight:packaging-inputs:bundled-python",
    "smoke:electron:source",
    "smoke:electron:packaged",
    "release:portable",
    "release:portable:smoke",
    "release:portable:smoke:scan",
    "release:portable:bundled-python",
    "release:portable:bundled-python:smoke",
    "release:portable:bundled-python:smoke:scan",
)


def _parse_unchecked_items(plan_text: str) -> list[dict[str, str]]:
    unchecked: list[dict[str, str]] = []
    current_round = "Document"
    in_checklist = False
    for line_number, line in enumerate(plan_text.splitlines(), start=1):
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            current_round = heading.group(1).strip()
            in_checklist = False
            continue
        if re.match(r"^###\s+Checklist\s*$", line):
            in_checklist = True
            continue
        if line.startswith("### "):
            in_checklist = False
            continue
        match = re.match(r"^\s*-\s+\[\s\]\s+(.+?)\s*$", line)
        if in_checklist and match:
            unchecked.append({
                "round": current_round,
                "line": str(line_number),
                "item": match.group(1).strip(),
            })
    return unchecked


def _parse_when_done_items(plan_text: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    current_round = "Document"
    in_when_done = False
    for line_number, line in enumerate(plan_text.splitlines(), start=1):
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            current_round = heading.group(1).strip()
            in_when_done = False
            continue
        if re.match(r"^###\s+When Done\s*$", line):
            in_when_done = True
            continue
        if line.startswith("### "):
            in_when_done = False
            continue
        match = re.match(r"^\s*-\s+(.+?)\s*$", line)
        if in_when_done and match:
            items.append({
                "round": current_round,
                "line": str(line_number),
                "item": match.group(1).strip(),
            })
    return items


def _load_package(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _packaged_app_ready(root: Path) -> bool:
    return (
        root.is_dir()
        and (root / "NAIA.exe").is_file()
        and (root / "resources" / "naia-backend").is_dir()
        and (root / "user-data").is_dir()
    )


def _load_json_file(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _get_path(payload: dict[str, Any], dotted_path: str) -> tuple[bool, Any]:
    current: Any = payload
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _condition_met(payload: dict[str, Any], condition: dict[str, Any]) -> bool:
    path = str(condition.get("path") or "")
    exists, value = _get_path(payload, path)
    if "exists" in condition:
        return exists is bool(condition["exists"])
    if not exists:
        return False
    if "equals" in condition:
        return value == condition["equals"]
    if "number_gt" in condition:
        try:
            return float(value) > float(condition["number_gt"])
        except (TypeError, ValueError):
            return False
    if "number_gte" in condition:
        try:
            return float(value) >= float(condition["number_gte"])
        except (TypeError, ValueError):
            return False
    if condition.get("truthy") is True:
        return bool(value)
    return False


def _merge_evidence(primary: dict[str, Any] | None, extra: dict[str, Any] | None) -> dict[str, Any] | None:
    if primary is None and extra is None:
        return None
    merged = dict(primary or {})
    for key, value in (extra or {}).items():
        if key == "sections" and isinstance(value, dict):
            sections = dict(merged.get("sections") or {})
            for section_name, section_payload in value.items():
                sections.setdefault(section_name, section_payload)
            merged["sections"] = sections
        elif key not in merged:
            merged[key] = value
    return merged


def _items_satisfied_by_evidence(
    items: list[dict[str, str]],
    *,
    evidence_map_path: Path,
    portable_workspace_evidence_path: Path,
    rule_section: str,
    extra_evidence: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    evidence_map = _load_json_file(evidence_map_path)
    portable_evidence = _merge_evidence(_load_json_file(portable_workspace_evidence_path), extra_evidence)
    if evidence_map is None or portable_evidence is None:
        return [], []

    rules = {
        (str(rule.get("round") or ""), str(rule.get("item") or "")): rule
        for rule in evidence_map.get(rule_section, [])
        if isinstance(rule, dict)
    }
    satisfied: list[dict[str, Any]] = []
    evaluated: list[dict[str, Any]] = []
    for item in items:
        rule = rules.get((item["round"], item["item"])) or rules.get(("", item["item"]))
        if not rule:
            continue
        results = [
            {
                "path": str(condition.get("path") or ""),
                "met": _condition_met(portable_evidence, condition),
            }
            for condition in rule.get("requires", [])
            if isinstance(condition, dict)
        ]
        entry = {
            "round": item["round"],
            "line": item["line"],
            "item": item["item"],
            "evidence": str(rule.get("evidence") or ""),
            "requirements": results,
            "satisfied": bool(results) and all(result["met"] for result in results),
        }
        evaluated.append(entry)
        if entry["satisfied"]:
            satisfied.append(entry)
    return satisfied, evaluated


def _rule_keys(evidence_map_path: Path, rule_section: str) -> set[tuple[str, str]]:
    evidence_map = _load_json_file(evidence_map_path)
    if evidence_map is None:
        return set()
    return {
        (str(rule.get("round") or ""), str(rule.get("item") or ""))
        for rule in evidence_map.get(rule_section, [])
        if isinstance(rule, dict)
    }


def _intentionally_unmapped_keys(evidence_map_path: Path, rule_section: str) -> set[tuple[str, str]]:
    evidence_map = _load_json_file(evidence_map_path)
    if evidence_map is None:
        return set()
    keys: set[tuple[str, str]] = set()
    for item in evidence_map.get("intentionally_unmapped", []):
        if not isinstance(item, dict):
            continue
        if str(item.get("section") or "") != rule_section:
            continue
        keys.add((str(item.get("round") or ""), str(item.get("item") or "")))
    return keys


def _unmapped_evidence_items(
    items: list[dict[str, str]],
    *,
    evidence_map_path: Path,
    rule_section: str,
) -> list[dict[str, str]]:
    rules = _rule_keys(evidence_map_path, rule_section)
    intentionally_unmapped = _intentionally_unmapped_keys(evidence_map_path, rule_section)
    unmapped: list[dict[str, str]] = []
    for item in items:
        exact_key = (item["round"], item["item"])
        generic_key = ("", item["item"])
        if exact_key in rules or generic_key in rules:
            continue
        if exact_key in intentionally_unmapped or generic_key in intentionally_unmapped:
            continue
        unmapped.append(item)
    return unmapped


def _unchecked_items_satisfied_by_evidence(
    unchecked_items: list[dict[str, str]],
    *,
    evidence_map_path: Path,
    portable_workspace_evidence_path: Path,
    extra_evidence: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return _items_satisfied_by_evidence(
        unchecked_items,
        evidence_map_path=evidence_map_path,
        portable_workspace_evidence_path=portable_workspace_evidence_path,
        rule_section="rules",
        extra_evidence=extra_evidence,
    )


def _resolve_workspace_packaged_root(evidence_path: Path) -> tuple[Path | None, str]:
    payload = _load_json_file(evidence_path)
    if payload is None:
        return None, "missing"
    if payload.get("dry_run") is True:
        return None, "dry_run"
    packaged_root = str(payload.get("packaged_root") or "").strip()
    if not packaged_root:
        return None, "missing_packaged_root"
    packaged_path = Path(packaged_root)
    if not _packaged_app_ready(packaged_path):
        return packaged_path, "not_ready"
    return packaged_path, "ready"


def _safe_section(name: str, factory) -> dict[str, Any]:
    try:
        payload = factory()
    except Exception as exc:
        return {
            "ok": False,
            "violations": [{"path": name, "reason": str(exc)}],
        }
    return payload if isinstance(payload, dict) else {"ok": False, "violations": [{"path": name, "reason": "section did not return a payload"}]}


def _requirements_headless_payload(path: Path = Path("requirements-headless.txt")) -> dict[str, Any]:
    if not path.is_file():
        return {"ok": False, "path": str(path), "violations": [{"path": str(path), "reason": "requirements file is missing"}]}
    text = path.read_text(encoding="utf-8")
    blocked = ["PyQt6", "PySide6"]
    violations = [
        {"path": str(path), "reason": f"headless requirements include GUI dependency: {dependency}"}
        for dependency in blocked
        if re.search(rf"^\s*{re.escape(dependency)}\b", text, re.IGNORECASE | re.MULTILINE)
    ]
    return {"ok": not violations, "path": str(path), "violations": violations}


def _round0_artifacts_payload() -> dict[str, Any]:
    required = [
        Path("refactor_docs/round_final_agent_import_inventory.md"),
        Path("refactor_docs/round_final_agent_filesystem_inventory.md"),
        Path("refactor_docs/round_final_agent_move_matrix.md"),
    ]
    violations = [
        {"path": str(path), "reason": "required Round 0 evidence document is missing"}
        for path in required
        if not path.is_file()
    ]
    return {
        "ok": not violations,
        "required": [str(path) for path in required],
        "violations": violations,
    }


def _backend_package_staging_payload() -> dict[str, Any]:
    required = [
        Path("app/backend/server/headless.py"),
        Path("app/backend/runtime/paths.py"),
        Path("core/runtime_paths.py"),
    ]
    violations = [
        {"path": str(path), "reason": "backend staging compatibility path is missing"}
        for path in required
        if not path.is_file()
    ]
    return {
        "ok": not violations,
        "required": [str(path) for path in required],
        "violations": violations,
    }


def _import_root(name: str | None) -> str:
    return str(name or "").split(".", 1)[0]


def _supported_import_boundary_payload() -> dict[str, Any]:
    roots = [
        Path("NAIA_web_headless.py"),
        Path("core"),
        Path("app"),
        Path("interfaces"),
        Path("utils"),
    ]
    blocked = {"PyQt6", "legacy_desktop", "NAIA_cold_v4"}
    ignored = {
        Path("core/context.py"),
        Path("core/image_crud_controller.py"),
        Path("core/mode_ware_manager.py"),
        Path("core/tag_data_manager.py"),
        Path("core/dll_fix.py"),
    }
    sources: list[Path] = []
    for root in roots:
        if root.is_file():
            sources.append(root)
        elif root.is_dir():
            sources.extend(
                path
                for path in root.rglob("*.py")
                if "legacy_desktop" not in path.parts
                and "dist" not in path.parts
                and "node_modules" not in path.parts
            )
    violations: list[dict[str, str]] = []
    for path in sorted(set(sources)):
        if path in ignored:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            violations.append({"path": str(path), "reason": f"cannot parse supported source: {exc}"})
            continue
        parents: dict[ast.AST, ast.AST] = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent

        def inside_type_checking(node: ast.AST) -> bool:
            current = parents.get(node)
            while current is not None:
                if (
                    isinstance(current, ast.If)
                    and isinstance(current.test, ast.Name)
                    and current.test.id == "TYPE_CHECKING"
                ):
                    return True
                current = parents.get(current)
            return False

        for node in ast.walk(tree):
            if inside_type_checking(node):
                continue
            if isinstance(node, ast.ImportFrom):
                root = _import_root(node.module)
            elif isinstance(node, ast.Import):
                imported = [_import_root(alias.name) for alias in node.names]
                root = next((name for name in imported if name in blocked), "")
            else:
                continue
            if root in blocked:
                violations.append({"path": str(path), "reason": f"blocked supported import: {root}"})
                break
    return {
        "ok": not violations,
        "scanned_file_count": len(set(sources)),
        "ignored_legacy_core_files": [str(path) for path in sorted(ignored)],
        "violations": violations,
    }


def _backend_runtime_strategy_payload() -> dict[str, Any]:
    payload = check_backend_runtime_strategy()
    manifest_path = Path(str(payload.get("strategy") or "release_assets/manifests/backend_runtime_strategy.json"))
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}
        for key in ("candidate_summary", "hard_rules", "scanner_policy", "code_signing_strategy"):
            if key in manifest:
                payload[key] = manifest[key]
    return payload


def _blocker_type_counts(blockers: list[dict[str, str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for blocker in blockers:
        blocker_type = str(blocker.get("type") or "unknown")
        counts[blocker_type] = counts.get(blocker_type, 0) + 1
    return counts


def _blocker_round_counts(blockers: list[dict[str, str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for blocker in blockers:
        round_name = str(blocker.get("round") or "")
        if not round_name:
            blocker_type = str(blocker.get("type") or "unknown")
            if blocker_type == "missing-runtime-evidence":
                round_name = "Runtime Evidence"
            elif blocker_type == "release-policy":
                round_name = "Release Policy"
            elif blocker_type == "missing-package-script":
                round_name = "Electron Package Scripts"
            else:
                round_name = "Unscoped"
        counts[round_name] = counts.get(round_name, 0) + 1
    return counts


def _release_completion_status(
    *,
    blockers: list[dict[str, str]],
    dependency_readiness: dict[str, Any],
    packaged_ready: bool,
    packaged_dir: Path,
) -> dict[str, Any]:
    next_actions: list[dict[str, Any]] = []
    dependency_action = dependency_readiness.get("next_action", {})
    if isinstance(dependency_action, dict) and dependency_action.get("required"):
        next_actions.append({
            "id": "electron-dependencies",
            "reason": "Electron dependency installation is required before packaging can run.",
            "requires_explicit_approval": bool(dependency_action.get("requires_explicit_approval")),
            "script": str(dependency_action.get("script") or ""),
            "final_release_script": str(dependency_action.get("final_release_script") or ""),
            "strategy": str(dependency_action.get("strategy") or ""),
            "mutates": list(dependency_action.get("mutates") or []),
        })
    if not packaged_ready:
        next_actions.append({
            "id": "packaged-electron-build",
            "reason": "The final packaged Electron artifact is missing or incomplete.",
            "requires_explicit_approval": True,
            "script": str(dependency_action.get("final_release_script") or "npm --prefix app/electron run release:final:install:scan")
            if isinstance(dependency_action, dict)
            else "npm --prefix app/electron run release:final:install:scan",
            "strategy": "final-install-scan",
            "mutates": [
                str(packaged_dir),
            ],
        })

    runtime_blockers = [
        blocker
        for blocker in blockers
        if blocker.get("type") in {"missing-runtime-evidence", "unchecked-plan-item", "unmet-when-done-condition"}
    ]
    return {
        "release_ready": not blockers,
        "blocked_on_approval": any(bool(action.get("requires_explicit_approval")) for action in next_actions),
        "next_actions": next_actions,
        "runtime_blocker_count": len(runtime_blockers),
        "blockers_by_type": _blocker_type_counts(blockers),
        "blockers_by_round": _blocker_round_counts(blockers),
    }


def audit_final_goal_completion(
    plan_path: str | Path = DEFAULT_PLAN,
    *,
    electron_package_path: str | Path = DEFAULT_ELECTRON_PACKAGE,
    packaged_root: str | Path = DEFAULT_PACKAGED_ROOT,
    portable_workspace_evidence_path: str | Path = DEFAULT_PORTABLE_WORKSPACE_EVIDENCE,
    completion_evidence_map_path: str | Path = DEFAULT_COMPLETION_EVIDENCE_MAP,
    extra_completion_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    plan_file = Path(plan_path)
    electron_package_file = Path(electron_package_path)
    configured_packaged_dir = Path(packaged_root)
    packaged_dir = configured_packaged_dir
    portable_workspace_evidence_file = Path(portable_workspace_evidence_path)
    completion_evidence_map_file = Path(completion_evidence_map_path)
    workspace_packaged_dir, workspace_evidence_status = _resolve_workspace_packaged_root(portable_workspace_evidence_file)
    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    if not plan_file.is_file():
        plan_blocker = {"type": "plan", "reason": "final plan file is missing", "path": str(plan_file)}
        return {
            "ok": False,
            "plan": str(plan_file),
            "blocker_count": 1,
            "warning_count": len(warnings),
            "blockers_by_type": {"plan": 1},
            "blockers_by_round": {"Unscoped": 1},
            "completion_status": {
                "release_ready": False,
                "blocked_on_approval": False,
                "next_actions": [],
                "runtime_blocker_count": 0,
                "blockers_by_type": {"plan": 1},
                "blockers_by_round": {"Unscoped": 1},
            },
            "blockers": [plan_blocker],
            "warnings": warnings,
            "unchecked_items": [],
            "evidence": {},
        }

    plan_text = plan_file.read_text(encoding="utf-8")
    unchecked_items = _parse_unchecked_items(plan_text)
    when_done_items = _parse_when_done_items(plan_text)
    try:
        electron_shell_contract = check_electron_shell_contract(electron_root=electron_package_file.parent)
    except Exception as exc:
        electron_shell_contract = {
            "ok": False,
            "violations": [{
                "path": str(electron_package_file.parent),
                "reason": f"Electron shell contract check failed: {exc}",
            }],
        }
    static_sections = {
        "backend_runtime_strategy": _safe_section("backend_runtime_strategy", _backend_runtime_strategy_payload),
        "remote_web_feature_contract": _safe_section("remote_web_feature_contract", validate_remote_web_feature_contract),
        "runtime_write_policy": _safe_section("runtime_write_policy", check_runtime_write_policy),
        "runtime_asset_classification": _safe_section(
            "runtime_asset_classification",
            check_runtime_asset_classification_payload,
        ),
        "source_layout_contract": _safe_section("source_layout_contract", check_source_layout_contract),
        "headless_core_boundary": _safe_section("headless_core_boundary", check_headless_core_boundary_payload),
        "requirements_headless": _requirements_headless_payload(),
        "round0_artifacts": _round0_artifacts_payload(),
        "backend_package_staging": _backend_package_staging_payload(),
        "supported_import_boundary": _supported_import_boundary_payload(),
        "electron_shell_contract": electron_shell_contract,
    }
    static_evidence = {"sections": static_sections}
    completion_extra_evidence = _merge_evidence(extra_completion_evidence, static_evidence)
    satisfied_unchecked_items, evaluated_unchecked_items = _unchecked_items_satisfied_by_evidence(
        unchecked_items,
        evidence_map_path=completion_evidence_map_file,
        portable_workspace_evidence_path=portable_workspace_evidence_file,
        extra_evidence=completion_extra_evidence,
    )
    satisfied_when_done_items, evaluated_when_done_items = _items_satisfied_by_evidence(
        when_done_items,
        evidence_map_path=completion_evidence_map_file,
        portable_workspace_evidence_path=portable_workspace_evidence_file,
        rule_section="when_done_rules",
        extra_evidence=completion_extra_evidence,
    )
    satisfied_item_keys = {
        (item["round"], item["line"], item["item"])
        for item in satisfied_unchecked_items
    }
    for item in unchecked_items:
        if (item["round"], item["line"], item["item"]) in satisfied_item_keys:
            continue
        blockers.append({
            "type": "unchecked-plan-item",
            "reason": item["item"],
            "path": f"{plan_file}:{item['line']}",
            "round": item["round"],
        })
    for item in evaluated_when_done_items:
        if item["satisfied"]:
            continue
        blockers.append({
            "type": "unmet-when-done-condition",
            "reason": item["item"],
            "path": f"{plan_file}:{item['line']}",
            "round": item["round"],
        })
    unmapped_when_done_items = _unmapped_evidence_items(
        when_done_items,
        evidence_map_path=completion_evidence_map_file,
        rule_section="when_done_rules",
    )
    for item in unmapped_when_done_items:
        blockers.append({
            "type": "unmapped-when-done-condition",
            "reason": item["item"],
            "path": f"{plan_file}:{item['line']}",
            "round": item["round"],
        })

    package = _load_package(electron_package_file)
    scripts = package.get("scripts", {}) if package else {}
    missing_scripts = [script for script in REQUIRED_PACKAGE_SCRIPTS if script not in scripts]
    for script in missing_scripts:
        blockers.append({
            "type": "missing-package-script",
            "reason": f"required package script is missing: {script}",
            "path": str(electron_package_file),
        })

    try:
        distribution_strategy = check_release_distribution_strategy(electron_package_path=electron_package_file)
    except Exception as exc:
        distribution_strategy = {
            "ok": False,
            "violations": [{
                "path": str(electron_package_file),
                "reason": f"release distribution strategy check failed: {exc}",
            }],
        }
    if not distribution_strategy.get("ok"):
        for item in distribution_strategy.get("violations", []):
            blockers.append({
                "type": "release-policy",
                "reason": f"Release distribution strategy failed: {item.get('reason', '')}",
                "path": str(item.get("path", "")),
            })

    electron_root = electron_package_file.parent
    dependency_readiness = check_electron_dependency_readiness(electron_package_path=electron_package_file)
    if not dependency_readiness.get("ok"):
        for item in dependency_readiness.get("violations", []):
            blockers.append({
                "type": "missing-runtime-evidence",
                "reason": f"Electron dependency readiness failed: {item.get('reason', '')}",
                "path": str(item.get("path", "")),
            })

    configured_packaged_ready = _packaged_app_ready(configured_packaged_dir)
    if not configured_packaged_ready and workspace_evidence_status == "ready" and workspace_packaged_dir is not None:
        packaged_dir = workspace_packaged_dir
    packaged_ready = _packaged_app_ready(packaged_dir)
    if not packaged_ready:
        blockers.append({
            "type": "missing-runtime-evidence",
            "reason": "packaged Electron app artifact is missing or incomplete",
            "path": str(packaged_dir),
        })

    package_lock = electron_root / "package-lock.json"
    blocker_counts = _blocker_type_counts(blockers)
    blocker_round_counts = _blocker_round_counts(blockers)
    unmet_when_done_count = sum(1 for item in evaluated_when_done_items if not item["satisfied"])
    intentionally_unmapped_when_done_count = max(
        0,
        len(when_done_items) - len(evaluated_when_done_items) - len(unmapped_when_done_items),
    )
    completion_status = _release_completion_status(
        blockers=blockers,
        dependency_readiness=dependency_readiness,
        packaged_ready=packaged_ready,
        packaged_dir=packaged_dir,
    )

    return {
        "ok": not blockers,
        "plan": str(plan_file),
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
        "unchecked_count": len(unchecked_items),
        "satisfied_unchecked_count": len(satisfied_unchecked_items),
        "unsatisfied_unchecked_count": len(unchecked_items) - len(satisfied_unchecked_items),
        "when_done_count": len(when_done_items),
        "satisfied_when_done_count": len(satisfied_when_done_items),
        "unmet_when_done_count": unmet_when_done_count,
        "unmapped_when_done_count": len(unmapped_when_done_items),
        "intentionally_unmapped_when_done_count": intentionally_unmapped_when_done_count,
        "blockers_by_type": blocker_counts,
        "blockers_by_round": blocker_round_counts,
        "completion_status": completion_status,
        "blockers": blockers,
        "warnings": warnings,
        "unchecked_items": unchecked_items,
        "when_done_items": when_done_items,
        "evidence": {
            "electron_package": str(electron_package_file),
            "package_scripts_checked": list(REQUIRED_PACKAGE_SCRIPTS),
            "missing_package_scripts": missing_scripts,
            "release_distribution_strategy_ok": bool(distribution_strategy.get("ok")),
            "release_distribution_strategy": distribution_strategy,
            "electron_shell_contract_ok": bool(electron_shell_contract.get("ok")),
            "electron_shell_contract": electron_shell_contract,
            "static_sections": static_sections,
            "electron_dependency_ready": bool(dependency_readiness.get("ok")),
            "electron_dependency_readiness": dependency_readiness,
            "configured_packaged_root": str(configured_packaged_dir),
            "configured_packaged_app_ready": configured_packaged_ready,
            "portable_workspace_evidence": str(portable_workspace_evidence_file),
            "portable_workspace_evidence_status": workspace_evidence_status,
            "completion_evidence_map": str(completion_evidence_map_file),
            "evidence_satisfied_unchecked_items": satisfied_unchecked_items,
            "evidence_evaluated_unchecked_items": evaluated_unchecked_items,
            "evidence_satisfied_when_done_items": satisfied_when_done_items,
            "evidence_evaluated_when_done_items": evaluated_when_done_items,
            "packaged_root": str(packaged_dir),
            "packaged_app_ready": packaged_ready,
            "package_lock_exists": package_lock.is_file(),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit final NAIA headless/Electron goal completion.")
    parser.add_argument("--plan", default=str(DEFAULT_PLAN), help="Final roadmap markdown file.")
    parser.add_argument("--electron-package", default=str(DEFAULT_ELECTRON_PACKAGE), help="Electron package.json path.")
    parser.add_argument("--packaged-root", default=str(DEFAULT_PACKAGED_ROOT), help="Packaged Electron app folder.")
    parser.add_argument(
        "--portable-workspace-evidence",
        default=str(DEFAULT_PORTABLE_WORKSPACE_EVIDENCE),
        help="Evidence JSON written by tools/run_electron_portable_workspace.py.",
    )
    parser.add_argument(
        "--completion-evidence-map",
        default=str(DEFAULT_COMPLETION_EVIDENCE_MAP),
        help="Manifest mapping roadmap checklist items to release evidence requirements.",
    )
    parser.add_argument("--summary", action="store_true", help="Print a compact blocker summary instead of full evidence JSON.")
    args = parser.parse_args(argv)

    payload = audit_final_goal_completion(
        args.plan,
        electron_package_path=args.electron_package,
        packaged_root=args.packaged_root,
        portable_workspace_evidence_path=args.portable_workspace_evidence,
        completion_evidence_map_path=args.completion_evidence_map,
    )
    if args.summary:
        payload = {
            "ok": payload.get("ok"),
            "plan": payload.get("plan"),
            "blocker_count": payload.get("blocker_count"),
            "warning_count": payload.get("warning_count"),
            "unchecked_count": payload.get("unchecked_count"),
            "satisfied_unchecked_count": payload.get("satisfied_unchecked_count"),
            "unsatisfied_unchecked_count": payload.get("unsatisfied_unchecked_count"),
            "when_done_count": payload.get("when_done_count"),
            "satisfied_when_done_count": payload.get("satisfied_when_done_count"),
            "unmet_when_done_count": payload.get("unmet_when_done_count"),
            "unmapped_when_done_count": payload.get("unmapped_when_done_count"),
            "intentionally_unmapped_when_done_count": payload.get("intentionally_unmapped_when_done_count"),
            "blockers_by_type": payload.get("blockers_by_type"),
            "blockers_by_round": payload.get("blockers_by_round"),
            "completion_status": payload.get("completion_status"),
        }
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
