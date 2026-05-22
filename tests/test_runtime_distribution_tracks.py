import json
import subprocess
import sys
from pathlib import Path

from tools.check_runtime_distribution_tracks import check_runtime_distribution_tracks


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _minimal_release_manifest() -> dict:
    return {
        "include": {
            "web_ui": ["app/web/remote/**"],
        },
        "exclude": {
            "local_runtime_state": [
                "app/electron/dist/**",
                "user-data/**",
                "wildcards/**",
            ],
            "development_only": [
                "app/electron/node_modules/**",
            ],
        },
    }


def _minimal_repo(root: Path, *, launcher_text: str | None = None, package_scripts: dict | None = None) -> Path:
    launcher = launcher_text or "pip install -r requirements-headless.txt\npython NAIA_web_headless.py --auto-port\n"
    for path in (
        "run_NAIA_web.bat",
        "run_NAIA_web.command",
        "run_NAIA.bat",
        "run_NAIA.command",
    ):
        _write(root / path, launcher)
    _write(root / "NAIA_web_headless.py", "print('headless')\n")
    _write(root / "requirements-headless.txt", "fastapi\nuvicorn[standard]\n")
    _write(root / "core" / "web_session_app.py", "")
    _write(root / "core" / "runtime_paths.py", "")
    _write(root / "app" / "web" / "remote" / "index.html", "")
    _write(root / "app" / "web" / "remote" / "style.css", "")
    _write(root / "app" / "web" / "remote" / "app.js", "")
    _write(
        root / "app" / "electron" / "main" / "main.cjs",
        "NAIA_REMOTE_WEB_DIR; app; web; remote; NAIA_web_headless.py; NAIA_USER_DATA_DIR;\n",
    )
    scripts = package_scripts or {
        "check": "node --check main/main.cjs",
        "start": "electron .",
        "pack:dir": "electron-builder --dir",
        "dist:win-dir": "electron-builder --win dir",
        "release:portable:clean-python": "python tool.py",
        "check:runtime-distribution": "python tools/check_runtime_distribution_tracks.py",
        "smoke:electron:source": "python smoke.py",
        "smoke:electron:packaged": "python smoke.py",
    }
    _write(
        root / "app" / "electron" / "package.json",
        json.dumps({"main": "main/main.cjs", "scripts": scripts}, indent=2),
    )
    _write(
        root / "release_assets" / "manifests" / "release_include_exclude_draft.json",
        json.dumps(_minimal_release_manifest(), indent=2),
    )
    manifest = root / "runtime_distribution_tracks.json"
    manifest.write_text(
        Path("release_assets/manifests/runtime_distribution_tracks.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return manifest


def test_runtime_distribution_tracks_pass_current_repository():
    payload = check_runtime_distribution_tracks(repo_root=Path("."))

    assert payload["ok"] is True
    assert payload["source_track"] == "Clone-user Python Headless Web"
    assert payload["electron_track"] == "Electron release shell"
    assert payload["shared_remote_web"] == "app/web/remote"
    assert payload["violations"] == []


def test_runtime_distribution_tracks_rejects_npm_in_source_launcher(tmp_path):
    manifest = _minimal_repo(
        tmp_path,
        launcher_text="npm install\npip install -r requirements-headless.txt\npython NAIA_web_headless.py\n",
    )

    payload = check_runtime_distribution_tracks(repo_root=tmp_path, manifest_path=manifest)

    assert payload["ok"] is False
    assert any(violation["type"] == "source_launcher_forbidden_term" for violation in payload["violations"])


def test_runtime_distribution_tracks_rejects_recreated_legacy_remote_web(tmp_path):
    manifest = _minimal_repo(tmp_path)
    _write(tmp_path / "ui" / "remote_web" / "index.html", "legacy")

    payload = check_runtime_distribution_tracks(repo_root=tmp_path, manifest_path=manifest)

    assert payload["ok"] is False
    assert {
        "type": "removed_legacy_remote_web_present",
        "path": "ui/remote_web",
        "reason": "ui/remote_web must not be recreated as a source-owned Remote Web UI",
    } in payload["violations"]


def test_runtime_distribution_tracks_rejects_missing_electron_release_script(tmp_path):
    scripts = {
        "check": "node --check main/main.cjs",
        "start": "electron .",
    }
    manifest = _minimal_repo(tmp_path, package_scripts=scripts)

    payload = check_runtime_distribution_tracks(repo_root=tmp_path, manifest_path=manifest)

    assert payload["ok"] is False
    assert {
        "type": "electron_package_missing_script",
        "path": "pack:dir",
        "reason": "Electron release track requires this package script",
    } in payload["violations"]


def test_runtime_distribution_tracks_rejects_release_manifest_legacy_web_include(tmp_path):
    manifest = _minimal_repo(tmp_path)
    release = _minimal_release_manifest()
    release["include"]["web_ui"] = ["ui/remote_web/**"]
    _write(
        tmp_path / "release_assets" / "manifests" / "release_include_exclude_draft.json",
        json.dumps(release, indent=2),
    )

    payload = check_runtime_distribution_tracks(repo_root=tmp_path, manifest_path=manifest)

    assert payload["ok"] is False
    assert any(
        violation["type"] in {
            "release_manifest_missing_canonical_web",
            "release_manifest_includes_legacy_web",
        }
        for violation in payload["violations"]
    )


def test_runtime_distribution_tracks_cli_returns_json():
    result = subprocess.run(
        [sys.executable, "tools/check_runtime_distribution_tracks.py"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["manifest"] == "release_assets/manifests/runtime_distribution_tracks.json"
