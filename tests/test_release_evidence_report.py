import json
import subprocess
import sys
from pathlib import Path

from tools.write_release_evidence_report import summarize_release_evidence_report, write_release_evidence_report
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
    write_release_metadata(root)


def _fake_electron_dependencies(root: Path) -> Path:
    package_path = root / "package.json"
    package = {
        "main": "main/main.cjs",
        "scripts": {},
        "devDependencies": {
            "electron": "42.1.0",
            "electron-builder": "26.8.1",
        },
    }
    lock = {
        "lockfileVersion": 3,
        "packages": {
            "": package,
            "node_modules/electron": {"version": "42.1.0"},
            "node_modules/electron-builder": {"version": "26.8.1"},
        },
    }
    _write(package_path, json.dumps(package))
    _write(root / "package-lock.json", json.dumps(lock))
    _write(root / "node_modules" / "electron" / "package.json", json.dumps({"version": "42.1.0"}))
    _write(root / "node_modules" / "electron-builder" / "package.json", json.dumps({"version": "26.8.1"}))
    _write(root / "node_modules" / ".bin" / "electron.cmd", "@echo off\n")
    _write(root / "node_modules" / ".bin" / "electron-builder.cmd", "@echo off\n")
    _write(root / "main" / "main.cjs", Path("app/electron/main/main.cjs").read_text(encoding="utf-8"))
    _write(root / "preload" / "preload.cjs", Path("app/electron/preload/preload.cjs").read_text(encoding="utf-8"))
    _write(
        root / "renderer" / "maintenance.html",
        Path("app/electron/renderer/maintenance.html").read_text(encoding="utf-8"),
    )
    return package_path


def test_release_evidence_report_records_missing_artifacts_and_skipped_runtime(tmp_path):
    output = tmp_path / "evidence.json"

    payload = write_release_evidence_report(
        staged_root=tmp_path / "missing-staged",
        packaged_root=tmp_path / "missing-packaged",
        output=output,
        skip_electron_runtime=True,
    )

    assert payload["ok"] is False
    assert output.is_file()
    assert "staged_release" in payload["failed_sections"]
    assert "packaged_release" in payload["failed_sections"]
    assert "electron_dependencies" in payload["failed_sections"]
    assert "electron_runtime" in payload["failed_sections"]
    assert payload["sections"]["feature_smoke_mapping"]["ok"] is True

    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["ok"] is False
    assert written["output"] == str(output.resolve())
    summary = summarize_release_evidence_report(payload)
    assert "sections" not in summary
    assert summary["ok"] is False
    assert summary["staged_release"]["ok"] is False
    assert summary["packaged_release"]["ok"] is False
    assert summary["electron_runtime"]["status"] == "skipped"
    assert summary["goal_audit"]["blocker_count"] > 0


def test_release_evidence_report_accepts_structural_artifacts_but_keeps_runtime_blockers(tmp_path):
    staged = tmp_path / "NAIA-Web"
    packaged = tmp_path / "win-unpacked"
    electron_package = _fake_electron_dependencies(tmp_path / "electron")
    _fake_staged_release(staged)
    _fake_packaged_app(packaged)

    payload = write_release_evidence_report(
        staged_root=staged,
        packaged_root=packaged,
        electron_package=electron_package,
        output=None,
        skip_electron_runtime=True,
    )

    assert payload["ok"] is False
    assert payload["sections"]["staged_release"]["ok"] is True
    assert payload["sections"]["packaged_release"]["ok"] is True
    assert payload["sections"]["electron_dependencies"]["ok"] is True
    assert payload["sections"]["electron_shell_contract"]["ok"] is True
    assert payload["sections"]["feature_smoke_mapping"]["ok"] is True
    assert payload["sections"]["electron_runtime"]["status"] == "skipped"
    assert "goal_audit" in payload["failed_sections"]


def test_release_evidence_report_can_collect_fresh_staged_workspace(tmp_path):
    workspace = tmp_path / "fresh-workspace"

    payload = write_release_evidence_report(
        source_root=Path.cwd(),
        fresh_staged_workspace=True,
        workspace_root=workspace,
        packaged_root=tmp_path / "missing-packaged",
        output=None,
        skip_electron_runtime=True,
    )

    assert payload["ok"] is False
    assert payload["fresh_staged_workspace"] is True
    assert payload["workspace_root"] == str(workspace.resolve())
    assert payload["staged_root"] == str((workspace / "NAIA-Web").resolve())
    assert payload["sections"]["fresh_staged_workspace"]["ok"] is True
    assert payload["sections"]["staged_release"]["ok"] is True
    assert payload["sections"]["goal_audit"]["evidence"]["evidence_satisfied_when_done_items"]
    assert "staged_release" not in payload["failed_sections"]
    assert "packaged_release" in payload["failed_sections"]
    assert "electron_dependencies" in payload["failed_sections"]
    assert "electron_runtime" in payload["failed_sections"]
    assert not any((workspace / "NAIA-Web" / "resources" / "naia-backend").rglob("__pycache__"))


def test_release_evidence_report_refuses_nonempty_fresh_workspace(tmp_path):
    workspace = tmp_path / "fresh-workspace"
    workspace.mkdir()
    (workspace / "old.txt").write_text("old\n", encoding="utf-8")

    payload = write_release_evidence_report(
        source_root=Path.cwd(),
        fresh_staged_workspace=True,
        workspace_root=workspace,
        packaged_root=tmp_path / "missing-packaged",
        output=None,
        skip_electron_runtime=True,
    )

    assert payload["ok"] is False
    assert "fresh_staged_workspace" in payload["failed_sections"]
    assert payload["sections"]["fresh_staged_workspace"]["status"] == "blocked"
    assert "refusing to overwrite" in payload["sections"]["fresh_staged_workspace"]["violations"][0]["reason"]


def test_release_evidence_report_cli_writes_json_and_returns_nonzero_for_incomplete_evidence(tmp_path):
    output = tmp_path / "release_evidence.json"

    result = subprocess.run(
        [
            sys.executable,
            "tools/write_release_evidence_report.py",
            "--staged-root",
            str(tmp_path / "missing-staged"),
            "--packaged-root",
            str(tmp_path / "missing-packaged"),
            "--output",
            str(output),
            "--skip-electron-runtime",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 1
    assert output.is_file()
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["output"] == str(output.resolve())


def test_release_evidence_report_cli_summary_omits_nested_evidence(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "tools/write_release_evidence_report.py",
            "--staged-root",
            str(tmp_path / "missing-staged"),
            "--packaged-root",
            str(tmp_path / "missing-packaged"),
            "--no-output",
            "--skip-electron-runtime",
            "--summary",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "sections" not in payload
    assert "staged_release" in payload["failed_sections"]
    assert payload["electron_dependencies"]["violation_count"] > 0
    assert payload["goal_audit"]["blocker_count"] > 0
