import json
from pathlib import Path
import subprocess
import sys

from tools.release_manifest_audit import audit_payload
from tools.stage_electron_release import collect_electron_backend_files, stage_electron_release


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _source_tree(root: Path) -> None:
    _write(root / "NAIA_web_headless.py")
    _write(root / "requirements-headless.txt")
    _write(root / "app" / "__init__.py")
    _write(root / "app" / "backend" / "server" / "headless.py")
    _write(root / "app" / "electron" / "main" / "main.cjs")
    _write(root / "app" / "web" / "__init__.py")
    _write(root / "app" / "web" / "assets.py")
    _write(root / "app" / "web" / "remote" / "index.html")
    _write(root / "core" / "web_session_app.py")
    _write(root / "interfaces" / "base_module.py")
    _write(root / "utils" / "clipboard_image.py")
    _write(root / "legacy_desktop" / "main.py")
    _write(root / "save" / "state.json")


def test_collect_electron_backend_files_excludes_electron_shell_source(tmp_path):
    _source_tree(tmp_path)

    files = {path.as_posix() for path in collect_electron_backend_files(tmp_path)}

    assert "NAIA_web_headless.py" in files
    assert "app/backend/server/headless.py" in files
    assert "app/web/remote/index.html" in files
    assert "core/web_session_app.py" in files
    assert "app/electron/main/main.cjs" not in files
    assert "legacy_desktop/main.py" not in files
    assert "save/state.json" not in files


def test_stage_electron_release_creates_auditable_resource_skeleton(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "NAIA-Web"
    _source_tree(source)

    result = stage_electron_release(source, target, copy=True)
    audit = audit_payload(target)

    assert result.copied is True
    assert (target / "resources" / "naia-backend" / "NAIA_web_headless.py").exists()
    assert (target / "resources" / "naia-backend" / "app" / "web" / "remote" / "index.html").exists()
    assert (target / "resources" / "naia-backend" / "app" / "electron").exists() is False
    assert (target / "user-data").is_dir()
    assert list((target / "user-data").iterdir()) == []
    assert (target / "README_RELEASE.txt").exists()
    assert (target / "RELEASE_MANIFEST.json").exists()
    assert (target / "CHECKSUMS.sha256").exists()
    assert audit["ok"] is True


def test_stage_electron_release_cli_dry_run(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "NAIA-Web"
    _source_tree(source)

    result = subprocess.run(
        [
            sys.executable,
            "tools/stage_electron_release.py",
            "--source",
            str(source),
            "--target",
            str(target),
        ],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["copied"] is False
    assert payload["backend_root"].endswith("resources\\naia-backend") or payload["backend_root"].endswith("resources/naia-backend")
    assert "app/electron/main/main.cjs" not in payload["files"]
