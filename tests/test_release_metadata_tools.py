import json
from pathlib import Path
import subprocess
import sys

from tools.check_release_preflight import check_release_preflight
from tools.stage_electron_release import stage_electron_release
from tools.write_release_metadata import build_release_metadata, write_release_metadata


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _source_tree(root: Path) -> None:
    _write(root / "NAIA_web_headless.py", "print('naia')\n")
    _write(root / "requirements-headless.txt")
    _write(root / "app" / "__init__.py")
    _write(root / "app" / "backend" / "__init__.py")
    _write(root / "app" / "backend" / "server" / "__init__.py")
    _write(root / "app" / "backend" / "server" / "headless.py")
    _write(root / "app" / "backend" / "runtime" / "__init__.py")
    _write(root / "app" / "backend" / "runtime" / "paths.py")
    _write(root / "app" / "web" / "__init__.py")
    _write(root / "app" / "web" / "assets.py")
    _write(root / "app" / "web" / "remote" / "index.html")
    _write(root / "app" / "web" / "remote" / "app.js")
    _write(root / "core" / "web_session_app.py")
    _write(root / "core" / "web_session_context.py")
    _write(root / "core" / "runtime_paths.py")
    _write(root / "interfaces" / "base_module.py")
    _write(root / "utils" / "clipboard_image.py")


def test_write_release_metadata_creates_manifest_and_checksums(tmp_path):
    release = tmp_path / "release"
    _write(release / "README_RELEASE.txt", "NAIA\n")
    _write(release / "resources" / "naia-backend" / "NAIA_web_headless.py", "print('x')\n")
    _write(release / "user-data" / ".keep", "")
    (release / "user-data" / ".keep").unlink()

    payload = write_release_metadata(release)
    manifest = json.loads((release / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
    checksums = (release / "CHECKSUMS.sha256").read_text(encoding="utf-8")

    assert payload["file_count"] == 2
    assert manifest["runtime"]["backend_entry_exists"] is True
    assert "README_RELEASE.txt" in checksums
    assert "RELEASE_MANIFEST.json" not in checksums
    assert "CHECKSUMS.sha256" not in checksums


def test_stage_electron_release_writes_release_metadata_and_notes(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "NAIA-Web"
    _source_tree(source)

    stage_electron_release(source, target, copy=True)
    metadata = build_release_metadata(target)
    preflight = check_release_preflight(target)
    readme = (target / "README_RELEASE.txt").read_text(encoding="utf-8")

    assert (target / "RELEASE_MANIFEST.json").is_file()
    assert (target / "CHECKSUMS.sha256").is_file()
    assert metadata["runtime"]["backend_entry_exists"] is True
    assert "NovelAI account/token" in readme
    assert preflight["checks"]["release_notes"]["external_dependencies_listed"] is True
    assert preflight["ok"] is True
    assert preflight["bundled_python"] is False
    assert preflight["warnings"]


def test_release_preflight_rejects_release_notes_without_external_dependencies(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "NAIA-Web"
    _source_tree(source)
    stage_electron_release(source, target, copy=True)
    (target / "README_RELEASE.txt").write_text("NAIA release\n", encoding="utf-8")

    preflight = check_release_preflight(target)

    assert preflight["ok"] is False
    assert preflight["checks"]["release_notes"]["external_dependencies_listed"] is False
    assert "NovelAI" in preflight["checks"]["release_notes"]["missing_readme_terms"]
    assert any(item["path"] == "README_RELEASE.txt" for item in preflight["violations"])


def test_release_preflight_can_require_bundled_python(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "NAIA-Web"
    _source_tree(source)
    stage_electron_release(source, target, copy=True)

    preflight = check_release_preflight(target, require_bundled_python=True)

    assert preflight["ok"] is False
    assert any(item["path"] == "resources/python" for item in preflight["violations"])


def test_release_preflight_cli_reports_json(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "NAIA-Web"
    _source_tree(source)
    stage_electron_release(source, target, copy=True)

    result = subprocess.run(
        [sys.executable, "tools/check_release_preflight.py", str(target)],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["ok"] is True
    assert payload["release_root"] == str(target.resolve())
