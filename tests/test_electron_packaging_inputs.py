import json
import subprocess
import sys
from pathlib import Path

from tools.check_electron_packaging_inputs import check_electron_packaging_inputs
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


def _write_package(electron_root: Path) -> Path:
    package = electron_root / "package.json"
    _write(
        package,
        json.dumps(
            {
                "build": {
                    "extraResources": [
                        {
                            "from": "dist/NAIA-Web/resources/naia-backend",
                            "to": "naia-backend",
                        }
                    ],
                    "extraFiles": [
                        {"from": "dist/NAIA-Web/README_RELEASE.txt", "to": "README_RELEASE.txt"},
                        {"from": "dist/NAIA-Web/RELEASE_MANIFEST.json", "to": "RELEASE_MANIFEST.json"},
                        {"from": "dist/NAIA-Web/CHECKSUMS.sha256", "to": "CHECKSUMS.sha256"},
                    ],
                }
            }
        ),
    )
    return package


def _fake_staged_release(root: Path) -> None:
    _write(root / "README_RELEASE.txt", RELEASE_NOTES)
    _write(root / "resources" / "naia-backend" / "NAIA_web_headless.py", "print('ok')\n")
    _write(root / "resources" / "naia-backend" / "app" / "web" / "remote" / "index.html", "<!doctype html>\n")
    _write(root / "resources" / "naia-backend" / "app" / "web" / "remote" / "app.js", "console.log('ok');\n")
    (root / "user-data").mkdir(parents=True)
    write_release_metadata(root)


def test_electron_packaging_inputs_accept_clean_staged_release(tmp_path):
    electron_root = tmp_path / "app" / "electron"
    package = _write_package(electron_root)
    staged = electron_root / "dist" / "NAIA-Web"
    _fake_staged_release(staged)

    payload = check_electron_packaging_inputs(electron_package_path=package, staged_root=staged)

    assert payload["ok"] is True
    assert payload["violations"] == []
    assert payload["resource_checks"][0]["type_ok"] is True
    assert len(payload["file_checks"]) == 3
    assert payload["staged_readiness"]["ok"] is True


def test_electron_packaging_inputs_reject_missing_extra_file(tmp_path):
    electron_root = tmp_path / "app" / "electron"
    package = _write_package(electron_root)
    staged = electron_root / "dist" / "NAIA-Web"
    _fake_staged_release(staged)
    (staged / "CHECKSUMS.sha256").unlink()

    payload = check_electron_packaging_inputs(electron_package_path=package, staged_root=staged)

    assert payload["ok"] is False
    assert any("extraFiles input is missing" in item["reason"] for item in payload["violations"])


def test_electron_packaging_inputs_reject_staged_residue(tmp_path):
    electron_root = tmp_path / "app" / "electron"
    package = _write_package(electron_root)
    staged = electron_root / "dist" / "NAIA-Web"
    _fake_staged_release(staged)
    _write(staged / "resources" / "naia-backend" / "core" / "__pycache__" / "bad.pyc", "bad")

    payload = check_electron_packaging_inputs(electron_package_path=package, staged_root=staged)

    assert payload["ok"] is False
    assert any("__pycache__" in item["path"] for item in payload["violations"])


def test_electron_packaging_inputs_cli(tmp_path):
    electron_root = tmp_path / "app" / "electron"
    package = _write_package(electron_root)
    staged = electron_root / "dist" / "NAIA-Web"
    _fake_staged_release(staged)

    result = subprocess.run(
        [
            sys.executable,
            "tools/check_electron_packaging_inputs.py",
            "--electron-package",
            str(package),
            "--staged-root",
            str(staged),
        ],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
