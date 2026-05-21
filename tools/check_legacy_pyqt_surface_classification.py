"""Validate legacy PyQt surface and desktop-test classification."""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


DEFAULT_CLASSIFICATION = Path("release_assets/manifests/legacy_pyqt_surface_classification.json")
DEFAULT_RELEASE_MANIFEST = Path("release_assets/manifests/release_include_exclude_draft.json")
REQUIRED_SURFACE_IDS = {
    "comic_generator_tab",
    "variational_generation_window",
    "ontology_visualizer",
    "ezmode_temp",
}
LEGACY_IMPORT_ROOTS = {"PyQt6", "legacy_desktop", "NAIA_cold_v4"}


@dataclass(frozen=True)
class LegacySurfaceViolation:
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


def _import_root(name: str | None) -> str:
    return str(name or "").split(".", 1)[0]


def scan_legacy_desktop_test_imports(tests_root: str | Path = "tests") -> list[str]:
    root = Path(tests_root)
    matched: list[str] = []
    for path in sorted(root.glob("test_*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if _import_root(node.module) in LEGACY_IMPORT_ROOTS:
                    matched.append(path.as_posix())
                    break
            elif isinstance(node, ast.Import):
                if any(_import_root(alias.name) in LEGACY_IMPORT_ROOTS for alias in node.names):
                    matched.append(path.as_posix())
                    break
    return matched


def validate_legacy_pyqt_surface_classification(
    classification_path: str | Path = DEFAULT_CLASSIFICATION,
    release_manifest_path: str | Path = DEFAULT_RELEASE_MANIFEST,
    tests_root: str | Path = "tests",
) -> list[LegacySurfaceViolation]:
    classification_file = Path(classification_path)
    release_file = Path(release_manifest_path)
    violations: list[LegacySurfaceViolation] = []

    if not classification_file.is_file():
        return [LegacySurfaceViolation(str(classification_file), "classification manifest does not exist")]
    if not release_file.is_file():
        return [LegacySurfaceViolation(str(release_file), "release manifest does not exist")]

    manifest = _read_json(classification_file)
    release_manifest = _read_json(release_file)
    release_excludes = _flatten_release_excludes(release_manifest)
    surfaces = manifest.get("legacy_surfaces")
    if not isinstance(surfaces, list):
        return [LegacySurfaceViolation(str(classification_file), "legacy_surfaces must be a list")]

    seen_surface_ids: set[str] = set()
    for item in surfaces:
        if not isinstance(item, dict):
            violations.append(LegacySurfaceViolation("<unknown>", "legacy surface item must be an object"))
            continue
        surface_id = str(item.get("id") or "").strip()
        feature = surface_id or "<missing id>"
        if not surface_id:
            violations.append(LegacySurfaceViolation(feature, "id is required"))
        elif surface_id in seen_surface_ids:
            violations.append(LegacySurfaceViolation(feature, "duplicate surface id"))
        seen_surface_ids.add(surface_id)

        path = str(item.get("path") or "").strip()
        if not path:
            violations.append(LegacySurfaceViolation(feature, "path is required"))
        elif not Path(path.replace("/**", "")).exists():
            violations.append(LegacySurfaceViolation(feature, f"classified path does not exist: {path}"))

        if item.get("release_action") != "exclude":
            violations.append(LegacySurfaceViolation(feature, "legacy PyQt surfaces must be release-excluded"))

        exclude_patterns = item.get("release_exclude_patterns")
        if not isinstance(exclude_patterns, list) or not exclude_patterns:
            violations.append(LegacySurfaceViolation(feature, "release_exclude_patterns must be a non-empty list"))
        else:
            missing = [pattern for pattern in exclude_patterns if pattern not in release_excludes]
            if missing:
                violations.append(
                    LegacySurfaceViolation(feature, f"release manifest missing exclude patterns: {missing}")
                )

    for surface_id in sorted(REQUIRED_SURFACE_IDS - seen_surface_ids):
        violations.append(LegacySurfaceViolation(surface_id, "required legacy surface is missing"))

    classified_tests = set(str(path) for path in manifest.get("desktop_test_files", []))
    scanned_tests = set(scan_legacy_desktop_test_imports(tests_root))
    missing_tests = sorted(scanned_tests - classified_tests)
    extra_tests = sorted(path for path in classified_tests - scanned_tests if not Path(path).is_file())
    for path in missing_tests:
        violations.append(LegacySurfaceViolation(path, "test imports PyQt6/legacy_desktop but is not classified"))
    for path in extra_tests:
        violations.append(LegacySurfaceViolation(path, "classified desktop test file does not exist"))

    for path in manifest.get("desktop_source_static_tests", []):
        if not Path(str(path)).is_file():
            violations.append(LegacySurfaceViolation(str(path), "classified desktop static test file does not exist"))

    return violations


def validation_payload(
    classification_path: str | Path = DEFAULT_CLASSIFICATION,
    release_manifest_path: str | Path = DEFAULT_RELEASE_MANIFEST,
    tests_root: str | Path = "tests",
) -> dict[str, Any]:
    violations = validate_legacy_pyqt_surface_classification(
        classification_path,
        release_manifest_path,
        tests_root,
    )
    manifest = _read_json(Path(classification_path)) if Path(classification_path).is_file() else {}
    return {
        "ok": not violations,
        "classification": str(Path(classification_path)),
        "release_manifest": str(Path(release_manifest_path)),
        "surface_count": len(manifest.get("legacy_surfaces", [])) if isinstance(manifest.get("legacy_surfaces"), list) else 0,
        "desktop_test_count": len(manifest.get("desktop_test_files", [])) if isinstance(manifest.get("desktop_test_files"), list) else 0,
        "scanned_desktop_test_imports": scan_legacy_desktop_test_imports(tests_root),
        "violations": [violation.__dict__ for violation in violations],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate legacy PyQt surface classification.")
    parser.add_argument("--classification", default=str(DEFAULT_CLASSIFICATION), help="Legacy PyQt surface classification manifest.")
    parser.add_argument("--release-manifest", default=str(DEFAULT_RELEASE_MANIFEST), help="Release include/exclude manifest.")
    parser.add_argument("--tests-root", default="tests", help="Directory containing pytest files to scan.")
    args = parser.parse_args(argv)

    payload = validation_payload(args.classification, args.release_manifest, args.tests_root)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
