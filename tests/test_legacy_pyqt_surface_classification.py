import json
from pathlib import Path
import subprocess
import sys

from tools.check_legacy_pyqt_surface_classification import (
    REQUIRED_SURFACE_IDS,
    scan_legacy_desktop_test_imports,
    validation_payload,
    validate_legacy_pyqt_surface_classification,
)


def test_legacy_pyqt_surface_classification_accepts_current_manifest():
    payload = validation_payload()

    assert payload["ok"] is True
    assert payload["surface_count"] == len(REQUIRED_SURFACE_IDS)
    assert payload["violations"] == []


def test_legacy_pyqt_surface_classification_covers_required_surfaces_and_tests():
    manifest = json.loads(
        Path("release_assets/manifests/legacy_pyqt_surface_classification.json").read_text(encoding="utf-8")
    )
    surfaces = {item["id"]: item for item in manifest["legacy_surfaces"]}
    desktop_tests = set(manifest["desktop_test_files"])

    assert set(REQUIRED_SURFACE_IDS) == set(surfaces)
    assert surfaces["comic_generator_tab"]["path"] == "tabs/comic_generator/**"
    assert surfaces["ontology_visualizer"]["classification"] == "desktop_only_pyqt_webengine_experiment"
    assert "tests/test_remote_api_status.py" in desktop_tests
    assert set(scan_legacy_desktop_test_imports()) <= desktop_tests


def test_legacy_pyqt_surface_classification_rejects_unclassified_desktop_test(tmp_path):
    tests_root = tmp_path / "tests"
    tests_root.mkdir()
    (tests_root / "test_desktop_surface.py").write_text(
        "from PyQt6.QtWidgets import QWidget\n",
        encoding="utf-8",
    )
    classification = {
        "version": 1,
        "legacy_surfaces": [
            {
                "id": item_id,
                "path": "tests/**",
                "classification": "desktop_only_pyqt_tab",
                "release_action": "exclude",
                "release_exclude_patterns": ["tests/**"],
            }
            for item_id in REQUIRED_SURFACE_IDS
        ],
        "desktop_test_files": [],
        "desktop_source_static_tests": [],
    }
    release_manifest = {"exclude": {"desktop_legacy": ["tests/**"]}}
    classification_path = tmp_path / "classification.json"
    release_path = tmp_path / "release.json"
    classification_path.write_text(json.dumps(classification), encoding="utf-8")
    release_path.write_text(json.dumps(release_manifest), encoding="utf-8")

    violations = validate_legacy_pyqt_surface_classification(
        classification_path,
        release_path,
        tests_root,
    )

    assert any("not classified" in violation.reason for violation in violations)


def test_legacy_pyqt_surface_classification_cli_outputs_json():
    result = subprocess.run(
        [sys.executable, "tools/check_legacy_pyqt_surface_classification.py"],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["ok"] is True
    assert "tests/test_remote_api_status.py" in payload["scanned_desktop_test_imports"]
