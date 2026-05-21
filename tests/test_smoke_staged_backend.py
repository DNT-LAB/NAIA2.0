import json
from pathlib import Path
import subprocess
import sys

from tools.stage_electron_release import stage_electron_release


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _minimal_backend_source(root: Path) -> None:
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
    _write(root / "app" / "web" / "remote" / "index.html", "<!doctype html><title>NAIA</title>")
    _write(root / "app" / "web" / "remote" / "style.css", "body { color: white; }")
    _write(root / "app" / "web" / "remote" / "app.js", "console.log('naia');")
    _write(root / "core" / "web_session_app.py")
    _write(root / "core" / "web_session_context.py")
    _write(root / "core" / "runtime_paths.py")
    _write(root / "core" / "artist_thumbnail_service.py")
    _write(root / "core" / "headless_generation_service.py")
    _write(root / "core" / "api_config_service.py")
    _write(root / "core" / "api_service.py")
    _write(root / "core" / "headless_random_prompt_service.py")
    _write(root / "core" / "headless_result_service.py")
    _write(root / "core" / "style_thumbnail_service.py")
    _write(root / "core" / "character_viewer_service.py")
    _write(root / "core" / "prompt_generation_service.py")
    _write(root / "core" / "prompt_engineering_runtime.py")
    _write(root / "core" / "conditional_prompt_runtime.py")
    _write(root / "core" / "reference_inset_service.py")
    _write(root / "core" / "wildcard_manager.py")
    _write(root / "core" / "filter_data_manager.py")
    _write(root / "core" / "result_image_payload_service.py")
    _write(root / "core" / "search_result_model.py")
    _write(root / "core" / "web_shell_config.py")
    _write(root / "interfaces" / "base_module.py")
    _write(root / "interfaces" / "base_tab_module.py")
    _write(root / "utils" / "clipboard_image.py")


def test_smoke_staged_backend_cli_validates_real_staged_backend(tmp_path):
    target = tmp_path / "NAIA-Web"
    stage_electron_release(Path.cwd(), target, copy=True)
    backend = target / "resources" / "naia-backend"

    result = subprocess.run(
        [
            sys.executable,
            "tools/smoke_staged_backend.py",
            str(backend),
            "--user-data",
            str(target / "user-data"),
        ],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["ok"] is True
    assert payload["checks"]["web_dir_is_app_path"] is True
    assert payload["checks"]["save_outside_backend"] is True
    assert payload["checks"]["output_outside_backend"] is True
    assert payload["checks"]["pyqt_imported"] is False
    assert not any(backend.rglob("__pycache__"))


def test_smoke_staged_backend_cli_reports_missing_backend(tmp_path):
    missing = tmp_path / "missing"

    result = subprocess.run(
        [sys.executable, "tools/smoke_staged_backend.py", str(missing)],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "backend root is not a directory" in result.stdout
