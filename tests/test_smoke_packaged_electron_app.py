import json
import subprocess
import sys
from pathlib import Path

from tools.smoke_packaged_electron_app import smoke_packaged_electron_app


def _fake_packaged_app(root: Path):
    (root / "resources" / "app" / "main").mkdir(parents=True)
    (root / "resources" / "naia-backend").mkdir(parents=True)
    (root / "user-data").mkdir()
    (root / "NAIA.exe").write_bytes(b"exe")
    (root / "resources" / "app" / "main" / "main.cjs").write_text("'use strict';\n", encoding="utf-8")
    (root / "resources" / "naia-backend" / "NAIA_web_headless.py").write_text("print('ok')\n", encoding="utf-8")


def test_smoke_packaged_electron_app_accepts_portable_structure(tmp_path):
    _fake_packaged_app(tmp_path)

    payload = smoke_packaged_electron_app(tmp_path, skip_backend_smoke=True)

    assert payload["ok"] is True
    assert payload["bundled_python"] is False
    assert payload["backend_smoke"] is None
    assert payload["violations"] == []


def test_smoke_packaged_electron_app_requires_empty_user_data(tmp_path):
    _fake_packaged_app(tmp_path)
    (tmp_path / "user-data" / "old-state.json").write_text("{}", encoding="utf-8")

    payload = smoke_packaged_electron_app(tmp_path, skip_backend_smoke=True)

    assert payload["ok"] is False
    assert any(item["path"] == "user-data" for item in payload["violations"])


def test_smoke_packaged_electron_app_cli(tmp_path):
    _fake_packaged_app(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            "tools/smoke_packaged_electron_app.py",
            str(tmp_path),
            "--skip-backend-smoke",
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
