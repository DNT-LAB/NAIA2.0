import json
import subprocess
import sys
from pathlib import Path

from tools.check_source_layout_contract import check_source_layout_contract


def test_source_layout_contract_passes_current_repository():
    payload = check_source_layout_contract(repo_root=Path("."))

    assert payload["ok"] is True
    assert payload["required_directory_count"] >= 25
    assert payload["python_package_marker_count"] >= 10
    assert payload["violations"] == []


def test_source_layout_contract_rejects_missing_required_directory(tmp_path):
    manifest = tmp_path / "contract.json"
    manifest.write_text(
        json.dumps(
            {
                "required_directories": ["missing/source/root"],
                "python_package_markers": [],
                "runtime_only_roots": [],
            }
        ),
        encoding="utf-8",
    )

    payload = check_source_layout_contract(repo_root=Path("."), manifest_path=manifest)

    assert payload["ok"] is False
    assert payload["violations"] == [
        {
            "type": "missing_required_directory",
            "path": "missing/source/root",
        }
    ]


def test_source_layout_contract_cli_returns_json():
    result = subprocess.run(
        [sys.executable, "tools/check_source_layout_contract.py"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["contract"] == "release_assets/manifests/source_layout_contract.json"
