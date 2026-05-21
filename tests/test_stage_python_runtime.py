import json
from pathlib import Path
import subprocess
import sys

import pytest

from tools.check_release_preflight import check_release_preflight
from tools.stage_electron_release import stage_electron_release
from tools.stage_python_runtime import find_python_executable, stage_python_runtime


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _source_tree(root: Path) -> None:
    _write(root / "NAIA_web_headless.py")
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


def _runtime_tree(root: Path) -> None:
    _write(root / "python.exe", "fake python")
    _write(root / "Lib" / "site.py", "# fake stdlib")


def test_find_python_executable_accepts_root_or_nested_layout(tmp_path):
    root_layout = tmp_path / "root"
    nested_layout = tmp_path / "nested"
    _write(root_layout / "python.exe")
    _write(nested_layout / "bin" / "python")

    assert find_python_executable(root_layout) == root_layout / "python.exe"
    assert find_python_executable(nested_layout) == nested_layout / "bin" / "python"


def test_stage_python_runtime_copies_into_release_resources_and_updates_metadata(tmp_path):
    source = tmp_path / "source"
    release = tmp_path / "NAIA-Web"
    runtime = tmp_path / "python-runtime"
    _source_tree(source)
    _runtime_tree(runtime)
    stage_electron_release(source, release, copy=True)

    result = stage_python_runtime(release, runtime, copy=True)
    preflight = check_release_preflight(release, require_bundled_python=True)
    manifest = json.loads((release / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
    checksums = (release / "CHECKSUMS.sha256").read_text(encoding="utf-8")

    assert result.copied is True
    assert (release / "resources" / "python" / "python.exe").is_file()
    assert (release / "resources" / "python" / "Lib" / "site.py").is_file()
    assert preflight["ok"] is True
    assert preflight["bundled_python"] is True
    assert manifest["runtime"]["bundled_python_exists"] is True
    assert "resources/python/python.exe" in checksums


def test_stage_python_runtime_rejects_missing_python_executable(tmp_path):
    release = tmp_path / "NAIA-Web"
    runtime = tmp_path / "python-runtime"
    release.mkdir()
    runtime.mkdir()

    with pytest.raises(RuntimeError, match="Python executable not found"):
        stage_python_runtime(release, runtime, copy=True)


def test_stage_python_runtime_cli_dry_run_reports_target_executable(tmp_path):
    release = tmp_path / "NAIA-Web"
    runtime = tmp_path / "python-runtime"
    release.mkdir()
    _runtime_tree(runtime)

    result = subprocess.run(
        [sys.executable, "tools/stage_python_runtime.py", str(release), str(runtime)],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["copied"] is False
    assert payload["executable"].endswith("resources\\python\\python.exe") or payload["executable"].endswith("resources/python/python.exe")
