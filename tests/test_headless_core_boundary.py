import json
from pathlib import Path
import subprocess
import sys

from tools.check_headless_core_boundary import (
    BLOCKED_HEADLESS_REQUIREMENTS,
    REQUIRED_LEGACY_CORE_IDS,
    validation_payload,
    validate_headless_core_boundary,
    validate_headless_requirements_policy,
)


def test_headless_core_boundary_accepts_current_manifest():
    payload = validation_payload()

    assert payload["ok"] is True
    assert payload["legacy_core_count"] == len(REQUIRED_LEGACY_CORE_IDS)
    assert payload["headless_requirements"] == "requirements-headless.txt"
    assert payload["headless_requirements_policy"]["desktop_dependency_policy"] == "forbidden"
    assert payload["violations"] == []


def test_headless_core_boundary_classifies_known_desktop_core_files():
    manifest = json.loads(Path("release_assets/manifests/headless_core_boundary.json").read_text(encoding="utf-8"))
    items = {item["id"]: item for item in manifest["legacy_core_files"]}

    assert set(REQUIRED_LEGACY_CORE_IDS) == set(items)
    assert items["desktop_app_context"]["path"] == "core/context.py"
    assert items["desktop_image_crud_controller"]["path"] == "core/image_crud_controller.py"
    assert items["desktop_tag_data_manager"]["release_action"] == "exclude"
    policy = manifest["headless_requirements_policy"]
    blocked = {item.replace("_", "-").lower() for item in policy["blocked_dependencies"]}
    assert BLOCKED_HEADLESS_REQUIREMENTS <= blocked
    assert policy["path"] == "requirements-headless.txt"


def test_headless_requirements_policy_rejects_pyqt_dependency():
    manifest = json.loads(Path("release_assets/manifests/headless_core_boundary.json").read_text(encoding="utf-8"))
    requirements = Path("tests/fixtures/bad_headless_requirements_pyqt.txt")

    violations = validate_headless_requirements_policy(manifest, requirements)

    assert any("forbidden desktop dependency" in violation.reason for violation in violations)


def test_headless_requirements_policy_rejects_desktop_legacy_include():
    manifest = json.loads(Path("release_assets/manifests/headless_core_boundary.json").read_text(encoding="utf-8"))
    requirements = Path("tests/fixtures/bad_headless_requirements_desktop_include.txt")

    violations = validate_headless_requirements_policy(manifest, requirements)

    assert any("must not include desktop legacy requirements" in violation.reason for violation in violations)


def test_headless_core_boundary_rejects_missing_release_exclude(tmp_path):
    source = tmp_path / "core_file.py"
    source.write_text("", encoding="utf-8")
    boundary = {
        "version": 1,
        "legacy_core_files": [
            {
                "id": item_id,
                "path": str(source),
                "classification": "legacy",
                "release_action": "exclude",
                "release_exclude_patterns": [f"{item_id}.py"],
            }
            for item_id in REQUIRED_LEGACY_CORE_IDS
        ],
    }
    release_manifest = {"exclude": {"desktop_legacy": []}}
    boundary_path = tmp_path / "boundary.json"
    release_path = tmp_path / "release.json"
    boundary_path.write_text(json.dumps(boundary), encoding="utf-8")
    release_path.write_text(json.dumps(release_manifest), encoding="utf-8")

    violations = validate_headless_core_boundary(boundary_path, release_path)

    assert any("missing exclude patterns" in violation.reason for violation in violations)


def test_headless_core_boundary_cli_outputs_json():
    result = subprocess.run(
        [sys.executable, "tools/check_headless_core_boundary.py"],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["ok"] is True
    assert "desktop_app_context" in payload["required_legacy_core"]
