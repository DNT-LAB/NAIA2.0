import json
import subprocess
import sys

from tools.check_release_source_payload import (
    check_release_source_payload,
    validate_selected_release_files,
)
from tools.release_manifest_audit import audit_release_paths


def test_release_source_payload_accepts_current_manifest_selection():
    payload = check_release_source_payload()

    assert payload["ok"] is True
    assert payload["selected_file_count"] > 0
    assert payload["violations"] == []


def test_release_source_payload_rejects_runtime_wildcards_and_downloaded_data():
    violations = validate_selected_release_files([
        "NAIA_web_headless.py",
        "requirements-headless.txt",
        "app/web/remote/index.html",
        "app/web/remote/app.js",
        "data/clothes_list.txt",
        "data/color.txt",
        "data/characteristic_list.txt",
        "data/taglist/expression_tags.json",
        "wildcards/favorite_artist.txt",
        "data/tags/tags_129.parquet",
    ])

    assert any("wildcards/**" in violation["reason"] for violation in violations)
    assert any("data/tags/**" in violation["reason"] for violation in violations)


def test_release_manifest_audit_rejects_forbidden_selected_paths_without_directory():
    violations = audit_release_paths([
        "NAIA_web_headless.py",
        "data/clothes_list.txt",
        "wildcards/runtime.txt",
    ])

    assert any(violation.path == "wildcards/runtime.txt" for violation in violations)


def test_release_source_payload_cli_outputs_json():
    result = subprocess.run(
        [sys.executable, "tools/check_release_source_payload.py"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
