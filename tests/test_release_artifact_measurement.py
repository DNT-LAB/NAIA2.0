import json
import subprocess
import sys
from pathlib import Path

from tools.measure_release_artifact import measure_release_artifact
from tools.write_release_metadata import CHECKSUMS_NAME, MANIFEST_NAME


def _minimal_release(root: Path):
    backend = root / "resources" / "naia-backend"
    backend.mkdir(parents=True)
    (backend / "NAIA_web_headless.py").write_text("print('ok')\n", encoding="utf-8")
    (root / "README_RELEASE.txt").write_text("NAIA\n", encoding="utf-8")
    (root / MANIFEST_NAME).write_text("{}", encoding="utf-8")
    (root / CHECKSUMS_NAME).write_text("abc  README_RELEASE.txt\n", encoding="utf-8")


def test_measure_release_artifact_counts_files_and_metadata(tmp_path):
    _minimal_release(tmp_path)

    payload = measure_release_artifact(tmp_path)

    assert payload["ok"] is True
    assert payload["stats"]["file_count"] == 4
    assert payload["stats"]["total_bytes"] > 0
    assert payload["metadata"]["readme"] is True
    assert payload["metadata"]["release_manifest"] is True
    assert payload["metadata"]["checksums"] is True
    assert payload["metadata"]["backend_entry"] is True
    assert payload["metadata"]["bundled_python"] is False


def test_measure_release_artifact_reports_missing_metadata(tmp_path):
    payload = measure_release_artifact(tmp_path)

    assert payload["ok"] is False
    assert {item["path"] for item in payload["violations"]} == {
        "readme",
        "release_manifest",
        "checksums",
        "backend_entry",
    }


def test_measure_release_artifact_can_require_defender_scan(tmp_path, monkeypatch):
    _minimal_release(tmp_path)

    monkeypatch.setattr("tools.measure_release_artifact._find_defender_scanner", lambda: None)
    payload = measure_release_artifact(tmp_path, defender_scan=True, require_defender_scan=True)

    assert payload["ok"] is False
    assert payload["scanner"]["available"] is False
    assert any("Defender scan evidence is required" in item["reason"] for item in payload["violations"])


def test_measure_release_artifact_cli(tmp_path):
    _minimal_release(tmp_path)

    result = subprocess.run(
        [sys.executable, "tools/measure_release_artifact.py", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
