import json
import subprocess
import sys
from pathlib import Path

from tools.check_project_layout_round_completion import check_project_layout_round_completion


def _write_manifest(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _current_manifest() -> dict:
    return json.loads(
        Path("release_assets/manifests/project_layout_round_completion.json").read_text(encoding="utf-8")
    )


def test_project_layout_round_completion_passes_current_repository():
    payload = check_project_layout_round_completion(repo_root=Path("."))

    assert payload["ok"] is True
    assert payload["manifest"] == "release_assets/manifests/project_layout_round_completion.json"
    assert payload["all_rounds_status"] == "complete_with_non_destructive_cleanup_candidates"
    assert payload["round_count"] == 10
    assert payload["violations"] == []


def test_project_layout_round_completion_rejects_missing_round(tmp_path):
    manifest = _current_manifest()
    manifest["rounds"] = [item for item in manifest["rounds"] if item["round"] != 8]
    manifest_path = tmp_path / "rounds.json"
    _write_manifest(manifest_path, manifest)

    payload = check_project_layout_round_completion(repo_root=Path("."), manifest_path=manifest_path)

    assert payload["ok"] is False
    assert {
        "type": "missing_required_round",
        "path": "8",
        "reason": "round completion evidence must cover Round 0 through Round 9",
    } in payload["violations"]


def test_project_layout_round_completion_rejects_missing_evidence_path(tmp_path):
    manifest = _current_manifest()
    manifest["rounds"][0]["evidence"].append("missing_layout_evidence.txt")
    manifest_path = tmp_path / "rounds.json"
    _write_manifest(manifest_path, manifest)

    payload = check_project_layout_round_completion(repo_root=Path("."), manifest_path=manifest_path)

    assert payload["ok"] is False
    assert {
        "type": "missing_round_evidence_path",
        "path": "missing_layout_evidence.txt",
        "reason": "round evidence path is not present in the current checkout",
    } in payload["violations"]


def test_project_layout_round_completion_requires_round_9_defer_marker(tmp_path):
    manifest = _current_manifest()
    for item in manifest["rounds"]:
        if item["round"] == 9:
            item["destructive_actions_deferred"] = False
    manifest_path = tmp_path / "rounds.json"
    _write_manifest(manifest_path, manifest)

    payload = check_project_layout_round_completion(repo_root=Path("."), manifest_path=manifest_path)

    assert payload["ok"] is False
    assert {
        "type": "round_9_destructive_actions_not_deferred",
        "path": "9",
        "reason": "cleanup/delete round must defer destructive actions until explicit approval",
    } in payload["violations"]


def test_project_layout_round_completion_cli_returns_json():
    result = subprocess.run(
        [sys.executable, "tools/check_project_layout_round_completion.py"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["manifest"] == "release_assets/manifests/project_layout_round_completion.json"
