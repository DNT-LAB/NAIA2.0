import json
from pathlib import Path
import subprocess
import sys

from tools.check_legacy_pyqt_surface_classification import (
    REQUIRED_SURFACE_IDS,
    REQUIRED_WEB_REBUILD_STATUS,
    scan_legacy_desktop_test_imports,
    validation_payload,
    validate_legacy_pyqt_surface_classification,
    validate_web_rebuild_candidates,
)


def test_legacy_pyqt_surface_classification_accepts_current_manifest():
    payload = validation_payload()

    assert payload["ok"] is True
    assert payload["surface_count"] == len(REQUIRED_SURFACE_IDS)
    assert payload["web_rebuild_candidate_count"] == len(REQUIRED_SURFACE_IDS)
    assert payload["web_rebuild_candidate_policy"]["required_candidate_status"] == REQUIRED_WEB_REBUILD_STATUS
    assert payload["desktop_test_execution_policy"]["classification"] == "explicit_only"
    assert payload["desktop_test_execution_policy"]["electron_release_check"] == "must_not_run_pytest"
    assert payload["unclassified_product_legacy_imports"] == []
    assert payload["violations"] == []


def test_legacy_pyqt_surface_classification_covers_required_surfaces_and_tests():
    manifest = json.loads(
        Path("release_assets/manifests/legacy_pyqt_surface_classification.json").read_text(encoding="utf-8")
    )
    surfaces = {item["id"]: item for item in manifest["legacy_surfaces"]}
    rebuild_candidates = {item["legacy_surface_id"]: item for item in manifest["web_rebuild_candidates"]}
    desktop_tests = set(manifest["desktop_test_files"])

    assert set(REQUIRED_SURFACE_IDS) == set(surfaces)
    assert set(REQUIRED_SURFACE_IDS) == set(rebuild_candidates)
    assert surfaces["comic_generator_tab"]["path"] == "tabs/comic_generator/**"
    assert surfaces["comic_generator_tab"]["root_compatibility_entry"] == "tabs/comic_generator_tab.py"
    assert "tabs/comic_generator_tab.py" in surfaces["comic_generator_tab"]["release_exclude_patterns"]
    assert surfaces["ontology_visualizer"]["classification"] == "desktop_only_pyqt_webengine_experiment"
    assert rebuild_candidates["comic_generator_tab"]["target_owner"] == "app/web/remote"
    assert rebuild_candidates["comic_generator_tab"]["status"] == REQUIRED_WEB_REBUILD_STATUS
    assert "tabs/comic_generator_tab.py" in rebuild_candidates["comic_generator_tab"]["must_not_import"]
    assert manifest["desktop_test_execution_policy"]["required_release_script"] == "check:legacy-pyqt"
    assert "tests/test_remote_api_status.py" in desktop_tests
    assert set(scan_legacy_desktop_test_imports()) <= desktop_tests


def test_legacy_pyqt_surface_classification_rejects_missing_rebuild_candidate():
    manifest = json.loads(
        Path("release_assets/manifests/legacy_pyqt_surface_classification.json").read_text(encoding="utf-8")
    )
    manifest["web_rebuild_candidates"] = [
        item
        for item in manifest["web_rebuild_candidates"]
        if item["legacy_surface_id"] != "comic_generator_tab"
    ]

    violations = validate_web_rebuild_candidates(manifest)

    assert any(
        violation.feature == "comic_generator_tab" and "has no web rebuild candidate" in violation.reason
        for violation in violations
    )


def test_legacy_pyqt_surface_classification_rejects_candidate_import_outside_surface():
    manifest = json.loads(
        Path("release_assets/manifests/legacy_pyqt_surface_classification.json").read_text(encoding="utf-8")
    )
    manifest["web_rebuild_candidates"][0]["must_not_import"] = ["legacy_desktop/**"]

    violations = validate_web_rebuild_candidates(manifest)

    assert any("outside the classified legacy surface" in violation.reason for violation in violations)


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


def test_legacy_pyqt_surface_classification_rejects_release_check_pytest(tmp_path):
    package = json.loads(Path("app/electron/package.json").read_text(encoding="utf-8"))
    package["scripts"]["release:check"] += " && python -m pytest tests/test_remote_api_status.py"
    package_path = tmp_path / "package.json"
    package_path.write_text(json.dumps(package), encoding="utf-8")

    violations = validate_legacy_pyqt_surface_classification(electron_package_path=package_path)

    assert any("must not run pytest directly" in violation.reason for violation in violations)
    assert any("must not run desktop test file directly" in violation.reason for violation in violations)


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
