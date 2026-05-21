import json
import subprocess
import sys
from pathlib import Path

from tools.check_project_cleanup_candidates import check_project_cleanup_candidates


def _write_manifest(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _current_manifest() -> dict:
    return json.loads(
        Path("release_assets/manifests/project_cleanup_candidates.json").read_text(encoding="utf-8")
    )


def test_project_cleanup_candidates_pass_current_repository():
    payload = check_project_cleanup_candidates(repo_root=Path("."))

    assert payload["ok"] is True
    assert payload["manifest"] == "release_assets/manifests/project_cleanup_candidates.json"
    assert payload["candidate_group_count"] >= 5
    assert payload["delete_approval_required"] is True
    assert payload["violations"] == []


def test_project_cleanup_candidates_rejects_missing_required_group(tmp_path):
    manifest = _current_manifest()
    manifest["candidate_groups"] = [
        group for group in manifest["candidate_groups"] if group["id"] != "legacy_desktop_reference"
    ]
    manifest_path = tmp_path / "cleanup.json"
    _write_manifest(manifest_path, manifest)

    payload = check_project_cleanup_candidates(repo_root=Path("."), manifest_path=manifest_path)

    assert payload["ok"] is False
    assert {
        "type": "missing_required_candidate_group",
        "path": "legacy_desktop_reference",
        "reason": "required cleanup candidate group is missing",
    } in payload["violations"]


def test_project_cleanup_candidates_rejects_disabled_delete_approval(tmp_path):
    manifest = _current_manifest()
    manifest["delete_approval_required"] = False
    manifest["candidate_groups"][0]["requires_explicit_delete_approval"] = False
    manifest_path = tmp_path / "cleanup.json"
    _write_manifest(manifest_path, manifest)

    payload = check_project_cleanup_candidates(repo_root=Path("."), manifest_path=manifest_path)

    assert payload["ok"] is False
    assert any(violation["type"] == "delete_approval_not_required" for violation in payload["violations"])
    assert any(violation["type"] == "candidate_missing_delete_approval" for violation in payload["violations"])


def test_project_cleanup_candidates_allows_resolved_removed_path_to_be_absent(tmp_path):
    manifest = _current_manifest()
    manifest["candidate_groups"][0]["status"] = "resolved_removed"
    manifest["candidate_groups"][0]["paths"] = ["missing_removed_residue.cjs"]
    manifest_path = tmp_path / "cleanup.json"
    _write_manifest(manifest_path, manifest)

    payload = check_project_cleanup_candidates(repo_root=Path("."), manifest_path=manifest_path)

    assert payload["ok"] is True
    assert not any(warning["path"] == "missing_removed_residue.cjs" for warning in payload["warnings"])


def test_project_cleanup_candidates_rejects_unsafe_path(tmp_path):
    manifest = _current_manifest()
    manifest["candidate_groups"][0]["paths"].append("../outside")
    manifest_path = tmp_path / "cleanup.json"
    _write_manifest(manifest_path, manifest)

    payload = check_project_cleanup_candidates(repo_root=Path("."), manifest_path=manifest_path)

    assert payload["ok"] is False
    assert any(violation["type"] == "candidate_unsafe_path" for violation in payload["violations"])


def test_project_cleanup_candidates_cli_returns_json():
    result = subprocess.run(
        [sys.executable, "tools/check_project_cleanup_candidates.py"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["manifest"] == "release_assets/manifests/project_cleanup_candidates.json"
