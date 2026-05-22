"""Validate the headless release boundary for legacy core files."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


DEFAULT_BOUNDARY = Path("release_assets/manifests/headless_core_boundary.json")
DEFAULT_RELEASE_MANIFEST = Path("release_assets/manifests/release_include_exclude_draft.json")
DEFAULT_HEADLESS_REQUIREMENTS = Path("requirements-headless.txt")
REQUIRED_LEGACY_CORE_IDS = {
    "desktop_app_context",
    "desktop_image_crud_controller",
    "desktop_mode_aware_manager",
    "desktop_tag_data_manager",
    "desktop_dll_fix",
}
BLOCKED_HEADLESS_REQUIREMENTS = {
    "pyqt6",
    "pyqt6-qt6",
    "pyqt6-webengine",
    "pyqt6-webengine-qt6",
    "pyqt6-sip",
    "pyqt6-qscintilla",
    "pyside2",
    "pyside6",
    "qtpy",
}


@dataclass(frozen=True)
class HeadlessCoreBoundaryViolation:
    feature: str
    reason: str


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _flatten_release_excludes(manifest: dict[str, Any]) -> set[str]:
    flattened: set[str] = set()
    for patterns in manifest.get("exclude", {}).values():
        if isinstance(patterns, list):
            flattened.update(str(pattern) for pattern in patterns)
    return flattened


def _normalize_requirement_name(name: str) -> str:
    return name.strip().replace("_", "-").lower()


def _requirement_name(line: str) -> str:
    text = line.split("#", 1)[0].strip()
    if not text or text.startswith(("-", "--")):
        return ""
    for separator in ("==", ">=", "<=", "~=", "!=", ">", "<", "[", ";"):
        if separator in text:
            text = text.split(separator, 1)[0]
            break
    return _normalize_requirement_name(text)


def _read_requirements(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def validate_headless_requirements_policy(
    manifest: dict[str, Any],
    requirements_path: str | Path = DEFAULT_HEADLESS_REQUIREMENTS,
) -> list[HeadlessCoreBoundaryViolation]:
    violations: list[HeadlessCoreBoundaryViolation] = []
    policy = manifest.get("headless_requirements_policy")
    if not isinstance(policy, dict):
        return [
            HeadlessCoreBoundaryViolation(
                "headless_requirements_policy",
                "headless requirements policy is required",
            )
        ]

    if policy.get("path") != str(DEFAULT_HEADLESS_REQUIREMENTS):
        violations.append(
            HeadlessCoreBoundaryViolation(
                "headless_requirements_policy",
                f"path must be {DEFAULT_HEADLESS_REQUIREMENTS}",
            )
        )
    if policy.get("classification") != "headless_runtime_dependencies":
        violations.append(
            HeadlessCoreBoundaryViolation(
                "headless_requirements_policy",
                "classification must be headless_runtime_dependencies",
            )
        )
    if policy.get("desktop_dependency_policy") != "forbidden":
        violations.append(
            HeadlessCoreBoundaryViolation(
                "headless_requirements_policy",
                "desktop_dependency_policy must be forbidden",
            )
        )

    blocked = {
        _normalize_requirement_name(str(item))
        for item in policy.get("blocked_dependencies", [])
        if str(item).strip()
    } if isinstance(policy.get("blocked_dependencies"), list) else set()
    missing_blocked = sorted(BLOCKED_HEADLESS_REQUIREMENTS - blocked)
    if missing_blocked:
        violations.append(
            HeadlessCoreBoundaryViolation(
                "headless_requirements_policy",
                f"blocked_dependencies missing required desktop packages: {missing_blocked}",
            )
        )

    requirement_file = Path(requirements_path)
    if not requirement_file.is_file():
        return violations + [
            HeadlessCoreBoundaryViolation(str(requirement_file), "headless requirements file does not exist")
        ]

    for line_number, line in enumerate(_read_requirements(requirement_file), start=1):
        stripped = line.split("#", 1)[0].strip()
        if not stripped:
            continue
        if stripped.startswith("-r") and "requirements-desktop-legacy" in stripped:
            violations.append(
                HeadlessCoreBoundaryViolation(
                    str(requirement_file),
                    f"line {line_number} must not include desktop legacy requirements",
                )
            )
            continue
        name = _requirement_name(line)
        if name in blocked:
            violations.append(
                HeadlessCoreBoundaryViolation(
                    str(requirement_file),
                    f"line {line_number} includes forbidden desktop dependency: {name}",
                )
            )
    return violations


def validate_headless_core_boundary(
    boundary_path: str | Path = DEFAULT_BOUNDARY,
    release_manifest_path: str | Path = DEFAULT_RELEASE_MANIFEST,
    requirements_path: str | Path = DEFAULT_HEADLESS_REQUIREMENTS,
) -> list[HeadlessCoreBoundaryViolation]:
    boundary_file = Path(boundary_path)
    release_file = Path(release_manifest_path)
    violations: list[HeadlessCoreBoundaryViolation] = []

    if not boundary_file.is_file():
        return [HeadlessCoreBoundaryViolation(str(boundary_file), "boundary manifest does not exist")]
    if not release_file.is_file():
        return [HeadlessCoreBoundaryViolation(str(release_file), "release manifest does not exist")]

    manifest = _read_json(boundary_file)
    release_excludes = _flatten_release_excludes(_read_json(release_file))
    items = manifest.get("legacy_core_files")
    if not isinstance(items, list):
        return [HeadlessCoreBoundaryViolation(str(boundary_file), "legacy_core_files must be a list")]

    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            violations.append(HeadlessCoreBoundaryViolation("<unknown>", "legacy core item must be an object"))
            continue
        item_id = str(item.get("id") or "").strip()
        feature = item_id or "<missing id>"
        if not item_id:
            violations.append(HeadlessCoreBoundaryViolation(feature, "id is required"))
        elif item_id in seen:
            violations.append(HeadlessCoreBoundaryViolation(feature, "duplicate legacy core id"))
        seen.add(item_id)

        path = str(item.get("path") or "").strip()
        if not path:
            violations.append(HeadlessCoreBoundaryViolation(feature, "path is required"))
        elif not Path(path).is_file():
            violations.append(HeadlessCoreBoundaryViolation(feature, f"classified core file does not exist: {path}"))

        if item.get("release_action") != "exclude":
            violations.append(HeadlessCoreBoundaryViolation(feature, "legacy core files must be release-excluded"))

        exclude_patterns = item.get("release_exclude_patterns")
        if not isinstance(exclude_patterns, list) or not exclude_patterns:
            violations.append(HeadlessCoreBoundaryViolation(feature, "release_exclude_patterns must be a non-empty list"))
        else:
            missing = [pattern for pattern in exclude_patterns if pattern not in release_excludes]
            if missing:
                violations.append(
                    HeadlessCoreBoundaryViolation(feature, f"release manifest missing exclude patterns: {missing}")
                )

    for item_id in sorted(REQUIRED_LEGACY_CORE_IDS - seen):
        violations.append(HeadlessCoreBoundaryViolation(item_id, "required legacy core file is missing"))

    if Path(boundary_path) == DEFAULT_BOUNDARY:
        violations.extend(validate_headless_requirements_policy(manifest, requirements_path))

    return violations


def validation_payload(
    boundary_path: str | Path = DEFAULT_BOUNDARY,
    release_manifest_path: str | Path = DEFAULT_RELEASE_MANIFEST,
    requirements_path: str | Path = DEFAULT_HEADLESS_REQUIREMENTS,
) -> dict[str, Any]:
    violations = validate_headless_core_boundary(boundary_path, release_manifest_path, requirements_path)
    manifest = _read_json(Path(boundary_path)) if Path(boundary_path).is_file() else {}
    return {
        "ok": not violations,
        "boundary": str(Path(boundary_path)),
        "release_manifest": str(Path(release_manifest_path)),
        "headless_requirements": str(Path(requirements_path)),
        "headless_requirements_policy": manifest.get("headless_requirements_policy", {}),
        "legacy_core_count": len(manifest.get("legacy_core_files", [])) if isinstance(manifest.get("legacy_core_files"), list) else 0,
        "required_legacy_core": sorted(REQUIRED_LEGACY_CORE_IDS),
        "violations": [violation.__dict__ for violation in violations],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate NAIA headless core boundary.")
    parser.add_argument("--boundary", default=str(DEFAULT_BOUNDARY), help="Headless core boundary manifest.")
    parser.add_argument("--release-manifest", default=str(DEFAULT_RELEASE_MANIFEST), help="Release include/exclude manifest.")
    parser.add_argument("--requirements", default=str(DEFAULT_HEADLESS_REQUIREMENTS), help="Headless requirements file.")
    args = parser.parse_args(argv)

    payload = validation_payload(args.boundary, args.release_manifest, args.requirements)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
