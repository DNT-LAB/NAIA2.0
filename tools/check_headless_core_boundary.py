"""Validate the headless release boundary for legacy core files."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


DEFAULT_BOUNDARY = Path("release_assets/manifests/headless_core_boundary.json")
DEFAULT_RELEASE_MANIFEST = Path("release_assets/manifests/release_include_exclude_draft.json")
REQUIRED_LEGACY_CORE_IDS = {
    "desktop_app_context",
    "desktop_image_crud_controller",
    "desktop_mode_aware_manager",
    "desktop_tag_data_manager",
    "desktop_dll_fix",
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


def validate_headless_core_boundary(
    boundary_path: str | Path = DEFAULT_BOUNDARY,
    release_manifest_path: str | Path = DEFAULT_RELEASE_MANIFEST,
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

    return violations


def validation_payload(
    boundary_path: str | Path = DEFAULT_BOUNDARY,
    release_manifest_path: str | Path = DEFAULT_RELEASE_MANIFEST,
) -> dict[str, Any]:
    violations = validate_headless_core_boundary(boundary_path, release_manifest_path)
    manifest = _read_json(Path(boundary_path)) if Path(boundary_path).is_file() else {}
    return {
        "ok": not violations,
        "boundary": str(Path(boundary_path)),
        "release_manifest": str(Path(release_manifest_path)),
        "legacy_core_count": len(manifest.get("legacy_core_files", [])) if isinstance(manifest.get("legacy_core_files"), list) else 0,
        "required_legacy_core": sorted(REQUIRED_LEGACY_CORE_IDS),
        "violations": [violation.__dict__ for violation in violations],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate NAIA headless core boundary.")
    parser.add_argument("--boundary", default=str(DEFAULT_BOUNDARY), help="Headless core boundary manifest.")
    parser.add_argument("--release-manifest", default=str(DEFAULT_RELEASE_MANIFEST), help="Release include/exclude manifest.")
    args = parser.parse_args(argv)

    payload = validation_payload(args.boundary, args.release_manifest)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
