import json
import subprocess
import sys
from pathlib import Path

from tools.check_clean_machine_readiness import check_clean_machine_readiness
from tools.write_release_metadata import write_release_metadata


RELEASE_NOTES = """NAIA release
External runtime dependencies:
- NovelAI account/token for NovelAI generation.
- WebUI endpoint for WEBUI generation.
- ComfyUI endpoint for COMFYUI generation.
- Optional downloadable tag, preset, thumbnail, and model-support data.
"""


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fake_staged_release(root: Path) -> None:
    _write(root / "README_RELEASE.txt", RELEASE_NOTES)
    _write(root / "resources" / "naia-backend" / "NAIA_web_headless.py", "print('ok')\n")
    _write(root / "resources" / "naia-backend" / "app" / "web" / "remote" / "index.html", "<!doctype html>\n")
    _write(root / "resources" / "naia-backend" / "app" / "web" / "remote" / "app.js", "console.log('ok');\n")
    (root / "user-data").mkdir(parents=True)
    write_release_metadata(root)


def _fake_packaged_app(root: Path) -> None:
    _fake_staged_release(root)
    _write(root / "NAIA.exe", "exe")
    _write(root / "resources" / "app" / "main" / "main.cjs", "'use strict';\n")


def test_clean_machine_readiness_accepts_staged_release(tmp_path):
    _fake_staged_release(tmp_path)

    payload = check_clean_machine_readiness(tmp_path, kind="staged-release")

    assert payload["ok"] is True
    assert payload["kind"] == "staged-release"
    assert payload["bundled_python"] is False
    assert payload["violations"] == []
    assert payload["checks"]["packaged_smoke"] is None


def test_clean_machine_readiness_can_require_bundled_python(tmp_path):
    _fake_staged_release(tmp_path)

    failed = check_clean_machine_readiness(tmp_path, kind="staged-release", require_bundled_python=True)
    assert failed["ok"] is False
    assert any(item["path"] == "resources/python" for item in failed["violations"])

    _write(tmp_path / "resources" / "python" / "python.exe", "python")
    write_release_metadata(tmp_path)
    passed = check_clean_machine_readiness(tmp_path, kind="staged-release", require_bundled_python=True)
    assert passed["ok"] is True
    assert passed["bundled_python"] is True


def test_clean_machine_readiness_rejects_source_checkout_residue(tmp_path):
    _fake_staged_release(tmp_path)
    _write(tmp_path / ".git" / "HEAD", "ref: refs/heads/main\n")
    _write(tmp_path / "tests" / "test_leak.py", "")

    payload = check_clean_machine_readiness(tmp_path, kind="staged-release")
    paths = {item["path"] for item in payload["violations"]}

    assert payload["ok"] is False
    assert ".git" in paths
    assert "tests" in paths


def test_clean_machine_readiness_accepts_packaged_electron_structure(tmp_path):
    _fake_packaged_app(tmp_path)

    payload = check_clean_machine_readiness(tmp_path, kind="packaged-electron")

    assert payload["ok"] is True
    assert payload["checks"]["packaged_smoke"]["ok"] is True
    assert payload["violations"] == []


def test_clean_machine_readiness_can_require_defender_scan(tmp_path, monkeypatch):
    _fake_packaged_app(tmp_path)
    monkeypatch.setattr("tools.measure_release_artifact._find_defender_scanner", lambda: None)

    payload = check_clean_machine_readiness(
        tmp_path,
        kind="packaged-electron",
        require_defender_scan=True,
    )

    assert payload["ok"] is False
    assert payload["defender_scan"] is True
    assert payload["require_defender_scan"] is True
    assert any("Defender scan evidence is required" in item["reason"] for item in payload["violations"])


def test_clean_machine_readiness_cli(tmp_path):
    _fake_packaged_app(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            "tools/check_clean_machine_readiness.py",
            str(tmp_path),
            "--kind",
            "packaged-electron",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
