"""Validate legacy PyQt surface and desktop-test classification."""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
import fnmatch
import json
from pathlib import Path
import subprocess
from typing import Any
import warnings


DEFAULT_CLASSIFICATION = Path("release_assets/manifests/legacy_pyqt_surface_classification.json")
DEFAULT_RELEASE_MANIFEST = Path("release_assets/manifests/release_include_exclude_draft.json")
DEFAULT_HEADLESS_CORE_BOUNDARY = Path("release_assets/manifests/headless_core_boundary.json")
REQUIRED_SURFACE_IDS = {
    "comic_generator_tab",
    "variational_generation_window",
    "ontology_visualizer",
    "ezmode_temp",
}
LEGACY_IMPORT_ROOTS = {"PyQt6", "PySide2", "PySide6", "qtpy", "legacy_desktop", "NAIA_cold_v4"}


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


def _repo_relative(path: Path, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return path.as_posix()


def _path_matches(path: str, pattern: str) -> bool:
    normalized = path.replace("\\", "/")
    candidate = str(pattern or "").replace("\\", "/")
    if candidate.endswith("/**"):
        prefix = candidate[:-3].rstrip("/")
        return normalized == prefix or normalized.startswith(prefix + "/")
    return fnmatch.fnmatch(normalized, candidate)


def _import_root(name: str | None) -> str:
    return str(name or "").split(".", 1)[0]


def _iter_tracked_python_files(repo_root: Path) -> list[Path]:
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "*.py"],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=True,
        )
        return [repo_root / line.strip() for line in result.stdout.splitlines() if line.strip()]
    except Exception:
        return sorted(repo_root.rglob("*.py"))


def _legacy_import_roots(path: Path) -> set[str]:
    try:
        if not path.is_file():
            return set()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return set()
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            root = _import_root(node.module)
            if root in LEGACY_IMPORT_ROOTS:
                roots.add(root)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                root = _import_root(alias.name)
                if root in LEGACY_IMPORT_ROOTS:
                    roots.add(root)
    return roots


def _legacy_surface_patterns(manifest: dict[str, Any]) -> set[str]:
    patterns: set[str] = set()
    for item in manifest.get("legacy_surfaces", []):
        if not isinstance(item, dict):
            continue
        for key in ("path", "root_compatibility_entry"):
            value = str(item.get(key) or "").strip()
            if value:
                patterns.add(value)
        release_patterns = item.get("release_exclude_patterns")
        if isinstance(release_patterns, list):
            patterns.update(str(pattern) for pattern in release_patterns if str(pattern).strip())
    return patterns


def _boundary_patterns(boundary_manifest: dict[str, Any]) -> set[str]:
    patterns: set[str] = set()
    files = boundary_manifest.get("legacy_core_files")
    if not isinstance(files, list):
        return patterns
    for item in files:
        if isinstance(item, dict) and str(item.get("path") or "").strip():
            patterns.add(str(item.get("path")).strip())
    return patterns


def _allowed_legacy_import_patterns(manifest: dict[str, Any], boundary_manifest: dict[str, Any]) -> set[str]:
    patterns = {"legacy_desktop/**"}
    patterns.update(_legacy_surface_patterns(manifest))
    patterns.update(_boundary_patterns(boundary_manifest))
    for key in ("desktop_test_files", "desktop_source_static_tests"):
        paths = manifest.get(key)
        if isinstance(paths, list):
            patterns.update(str(path) for path in paths if str(path).strip())
    return patterns


def scan_unclassified_product_legacy_imports(
    classification_path: str | Path = DEFAULT_CLASSIFICATION,
    boundary_path: str | Path = DEFAULT_HEADLESS_CORE_BOUNDARY,
    repo_root: str | Path = ".",
) -> list[LegacySurfaceViolation]:
    repo = Path(repo_root).resolve()
    classification_file = Path(classification_path)
    if not classification_file.is_absolute():
        classification_file = repo / classification_file
    boundary_file = Path(boundary_path)
    if not boundary_file.is_absolute():
        boundary_file = repo / boundary_file
    if not classification_file.is_file():
        return [LegacySurfaceViolation(str(classification_file), "classification manifest does not exist")]
    manifest = _read_json(classification_file)
    boundary_manifest = _read_json(boundary_file) if boundary_file.is_file() else {}
    allowed_patterns = _allowed_legacy_import_patterns(manifest, boundary_manifest)
    violations: list[LegacySurfaceViolation] = []
    for path in _iter_tracked_python_files(repo):
        relative = _repo_relative(path, repo)
        roots = _legacy_import_roots(path)
        if not roots:
            continue
        if any(_path_matches(relative, pattern) for pattern in allowed_patterns):
            continue
        violations.append(
            LegacySurfaceViolation(
                relative,
                f"imports legacy desktop/Qt roots outside quarantine: {sorted(roots)}",
            )
        )
    return violations


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
    boundary_path: str | Path = DEFAULT_HEADLESS_CORE_BOUNDARY,
    repo_root: str | Path = ".",
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

    if Path(classification_path) == DEFAULT_CLASSIFICATION:
        violations.extend(scan_unclassified_product_legacy_imports(classification_path, boundary_path, repo_root))

    return violations


def validation_payload(
    classification_path: str | Path = DEFAULT_CLASSIFICATION,
    release_manifest_path: str | Path = DEFAULT_RELEASE_MANIFEST,
    tests_root: str | Path = "tests",
    boundary_path: str | Path = DEFAULT_HEADLESS_CORE_BOUNDARY,
    repo_root: str | Path = ".",
) -> dict[str, Any]:
    violations = validate_legacy_pyqt_surface_classification(
        classification_path,
        release_manifest_path,
        tests_root,
        boundary_path,
        repo_root,
    )
    manifest = _read_json(Path(classification_path)) if Path(classification_path).is_file() else {}
    product_import_violations = scan_unclassified_product_legacy_imports(
        classification_path,
        boundary_path,
        repo_root,
    ) if Path(classification_path) == DEFAULT_CLASSIFICATION else []
    return {
        "ok": not violations,
        "classification": str(Path(classification_path)),
        "release_manifest": str(Path(release_manifest_path)),
        "surface_count": len(manifest.get("legacy_surfaces", [])) if isinstance(manifest.get("legacy_surfaces"), list) else 0,
        "desktop_test_count": len(manifest.get("desktop_test_files", [])) if isinstance(manifest.get("desktop_test_files"), list) else 0,
        "scanned_desktop_test_imports": scan_legacy_desktop_test_imports(tests_root),
        "unclassified_product_legacy_imports": [violation.__dict__ for violation in product_import_violations],
        "violations": [violation.__dict__ for violation in violations],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate legacy PyQt surface classification.")
    parser.add_argument("--classification", default=str(DEFAULT_CLASSIFICATION), help="Legacy PyQt surface classification manifest.")
    parser.add_argument("--release-manifest", default=str(DEFAULT_RELEASE_MANIFEST), help="Release include/exclude manifest.")
    parser.add_argument("--tests-root", default="tests", help="Directory containing pytest files to scan.")
    parser.add_argument("--boundary", default=str(DEFAULT_HEADLESS_CORE_BOUNDARY), help="Headless core boundary manifest.")
    parser.add_argument("--repo-root", default=".", help="Repository root for tracked product import scans.")
    args = parser.parse_args(argv)

    payload = validation_payload(args.classification, args.release_manifest, args.tests_root, args.boundary, args.repo_root)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
