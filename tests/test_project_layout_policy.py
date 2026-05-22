import json
import subprocess
import sys
from pathlib import Path

from tools.check_project_layout_policy import check_project_layout_policy


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _minimal_repo(root: Path, *, launcher_text: str | None = None) -> Path:
    _write(
        root / "PROJECT_LAYOUT_POLICY.md",
        "\n".join([
            "Python Headless Web",
            "app/web/remote",
            "Electron is optional",
            "Legacy PyQt6 reference-only",
            "not the active product baseline",
        ]),
    )
    _write(root / "NAIA_web_headless.py", "print('headless')\n")
    _write(root / "requirements-headless.txt", "fastapi\n")
    launcher = launcher_text or "pip install -r requirements-headless.txt\npython NAIA_web_headless.py\n"
    _write(root / "run_NAIA_web.bat", launcher)
    _write(root / "run_NAIA_web.command", launcher)
    _write(root / "run_NAIA.bat", launcher)
    _write(root / "run_NAIA.command", launcher)
    _write(root / "app" / "web" / "remote" / "index.html", "")
    _write(root / "app" / "web" / "remote" / "style.css", "")
    _write(root / "app" / "web" / "remote" / "app.js", "")
    _write(root / "app" / "web" / "__init__.py", "")
    _write(root / "app" / "electron" / "main" / "main.cjs", "")
    _write(root / "app" / "electron" / "package.json", "{}")
    _write(root / "legacy_desktop" / "NAIA_cold_v4.py", "print('legacy')\n")
    _write(root / "release_assets" / "manifests" / "project_layout_round_completion.json", "{}")
    _write(root / "release_assets" / "manifests" / "project_cleanup_candidates.json", "{}")
    _write(root / "release_assets" / "manifests" / "runtime_distribution_tracks.json", "{}")
    _write(root / "release_assets" / "manifests" / "refactor_plan_execution_contract.json", "{}")
    _write(root / "release_assets" / "manifests" / "legacy_pyqt_surface_classification.json", "{}")
    manifest = root / "policy.json"
    manifest.write_text(
        Path("release_assets/manifests/project_layout_policy.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return manifest


def test_project_layout_policy_passes_current_repository():
    payload = check_project_layout_policy(repo_root=Path("."))

    assert payload["ok"] is True
    assert payload["default_runtime"] == "Python Headless Web"
    assert payload["default_entrypoint"] == "NAIA_web_headless.py"
    assert payload["legacy_desktop_root"] == "legacy_desktop"
    assert payload["legacy_desktop_status"] == "reference_only"
    assert payload["canonical_remote_web"] == "app/web/remote"
    assert payload["optional_electron_root"] == "app/electron"
    assert payload["round_completion_manifest"] == "release_assets/manifests/project_layout_round_completion.json"
    assert payload["cleanup_candidates_manifest"] == "release_assets/manifests/project_cleanup_candidates.json"
    assert payload["runtime_distribution_tracks_manifest"] == (
        "release_assets/manifests/runtime_distribution_tracks.json"
    )
    assert payload["refactor_plan_execution_manifest"] == (
        "release_assets/manifests/refactor_plan_execution_contract.json"
    )
    assert payload["legacy_pyqt_surfaces_manifest"] == (
        "release_assets/manifests/legacy_pyqt_surface_classification.json"
    )
    assert payload["violations"] == []


def test_project_layout_policy_rejects_electron_requirement_in_default_launcher(tmp_path):
    manifest = _minimal_repo(
        tmp_path,
        launcher_text="npm install\npython NAIA_web_headless.py\npip install -r requirements-headless.txt\n",
    )

    payload = check_project_layout_policy(repo_root=tmp_path, manifest_path=manifest)

    assert payload["ok"] is False
    assert any(
        violation["type"] == "launcher_contains_forbidden_term"
        and violation["path"] == "run_NAIA_web.bat"
        for violation in payload["violations"]
    )


def test_project_layout_policy_rejects_legacy_desktop_default_launcher(tmp_path):
    manifest = _minimal_repo(
        tmp_path,
        launcher_text=(
            "pip install -r requirements-headless.txt\n"
            "python NAIA_web_headless.py\n"
            "python legacy_desktop/NAIA_cold_v4.py\n"
        ),
    )

    payload = check_project_layout_policy(repo_root=tmp_path, manifest_path=manifest)

    assert payload["ok"] is False
    assert any(
        violation["type"] in {
            "launcher_contains_forbidden_term",
            "launcher_references_legacy_desktop",
        }
        and violation["path"] == "run_NAIA_web.bat"
        for violation in payload["violations"]
    )


def test_project_layout_policy_rejects_missing_canonical_web_file(tmp_path):
    manifest = _minimal_repo(tmp_path)
    (tmp_path / "app" / "web" / "remote" / "app.js").unlink()

    payload = check_project_layout_policy(repo_root=tmp_path, manifest_path=manifest)

    assert payload["ok"] is False
    assert {
        "type": "missing_remote_web_file",
        "path": "app/web/remote/app.js",
        "reason": "canonical Remote Web required file is missing",
    } in payload["violations"]


def test_project_layout_policy_warns_about_root_electron_residue(tmp_path):
    manifest = _minimal_repo(tmp_path)
    _write(tmp_path / "main.cjs", "legacy root electron copy")

    payload = check_project_layout_policy(repo_root=tmp_path, manifest_path=manifest)

    assert payload["ok"] is True
    assert {
        "type": "root_electron_residue",
        "path": "main.cjs",
        "reason": "root-level Electron residue should be removed or moved in a later cleanup round",
    } in payload["warnings"]


def test_project_layout_policy_cli_returns_json():
    result = subprocess.run(
        [sys.executable, "tools/check_project_layout_policy.py"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["contract"] == "release_assets/manifests/project_layout_policy.json"
