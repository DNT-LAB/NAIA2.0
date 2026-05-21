import json
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

from tools.run_electron_portable_workspace import run_electron_portable_workspace
from tools.run_electron_portable_workspace import summarize_electron_portable_workspace
from tools.run_electron_portable_workspace import _export_packaged_release


def test_electron_portable_workspace_dry_run_builds_clean_staging_and_config(tmp_path):
    workspace = tmp_path / "workspace"
    output = tmp_path / "portable_evidence.json"

    payload = run_electron_portable_workspace(
        source_root=Path.cwd(),
        workspace_root=workspace,
        output=output,
        dry_run=True,
    )

    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["run_electron_cdp"] is False
    assert isinstance(payload["ready_to_build"], bool)
    assert output.is_file()
    assert (workspace / "staged" / "NAIA-Web").is_dir()
    config = json.loads(Path(payload["builder_config"]).read_text(encoding="utf-8"))
    assert config["directories"]["output"] == str(workspace / "_build" / "electron-dist")
    assert payload["builder_packaged_root"] == str(workspace / "_build" / "electron-dist" / "win-unpacked")
    assert payload["portable_release_root"] == str(workspace / "NAIA-Portable")
    assert payload["packaged_root"] == str(workspace / "NAIA-Portable")
    assert config["win"]["target"] == "dir"
    assert config["win"]["signAndEditExecutable"] is False
    assert config["win"]["forceCodeSigning"] is False
    assert config["extraResources"][0]["from"] == str(
        (workspace / "staged" / "NAIA-Web" / "resources" / "naia-backend").resolve()
    )
    assert config["extraFiles"][0]["from"] == str((workspace / "staged" / "NAIA-Web" / "README_RELEASE.txt").resolve())
    assert Path(config["afterPack"]).is_absolute()
    assert "electron_dependencies" in payload["sections"]
    assert "distribution_strategy" in payload["sections"]
    assert "electron_shell_contract" in payload["sections"]
    assert isinstance(payload["sections"]["electron_dependencies"]["ok"], bool)
    assert payload["sections"]["distribution_strategy"]["ok"] is True
    assert payload["sections"]["electron_shell_contract"]["ok"] is True
    assert payload["sections"]["staged_workspace"]["ok"] is True


def test_electron_portable_workspace_dry_run_records_requested_cdp_smoke(tmp_path):
    payload = run_electron_portable_workspace(
        source_root=Path.cwd(),
        workspace_root=tmp_path / "workspace",
        dry_run=True,
        run_electron_cdp=True,
        electron_timeout=7,
    )

    assert payload["ok"] is True
    assert payload["run_electron_cdp"] is True
    assert payload["electron_timeout"] == 7.0
    assert "electron_cdp_smoke" not in payload["sections"]


def test_electron_portable_workspace_dry_run_records_defender_scan_gate(tmp_path):
    payload = run_electron_portable_workspace(
        source_root=Path.cwd(),
        workspace_root=tmp_path / "workspace",
        dry_run=True,
        defender_scan=True,
        require_defender_scan=True,
    )

    assert payload["ok"] is True
    assert payload["defender_scan"] is True
    assert payload["require_defender_scan"] is True


def test_electron_portable_workspace_bundled_python_config_includes_runtime(tmp_path):
    workspace = tmp_path / "workspace"
    runtime = tmp_path / "python-runtime"
    (runtime / "python.exe").parent.mkdir(parents=True)
    (runtime / "python.exe").write_text("python\n", encoding="utf-8")

    payload = run_electron_portable_workspace(
        source_root=Path.cwd(),
        workspace_root=workspace,
        python_runtime_dir=runtime,
        require_bundled_python=True,
        dry_run=True,
    )

    assert payload["ok"] is True
    config = json.loads(Path(payload["builder_config"]).read_text(encoding="utf-8"))
    assert {
        "from": str((workspace / "staged" / "NAIA-Web" / "resources" / "python").resolve()),
        "to": "python",
    } in config["extraResources"]


def test_electron_portable_workspace_can_build_clean_python_runtime(tmp_path):
    workspace = tmp_path / "workspace"

    payload = run_electron_portable_workspace(
        source_root=Path.cwd(),
        workspace_root=workspace,
        build_clean_python_runtime=True,
        require_bundled_python=True,
        dry_run=True,
    )

    runtime = workspace / "staged" / "NAIA-Web" / "resources" / "python"
    config = json.loads(Path(payload["builder_config"]).read_text(encoding="utf-8"))

    assert payload["ok"] is True
    assert payload["build_clean_python_runtime"] is True
    assert payload["sections"]["staged_workspace"]["sections"]["build_python_runtime"]["base_only"] is True
    assert (runtime / "python.exe").is_file()
    assert {
        "from": str(runtime.resolve()),
        "to": "python",
    } in config["extraResources"]


def test_export_packaged_release_copies_to_user_facing_portable_root(tmp_path):
    source = tmp_path / "_build" / "electron-dist" / "win-unpacked"
    destination = tmp_path / "NAIA-Portable"
    (source / "resources").mkdir(parents=True)
    (source / "NAIA.exe").write_text("exe\n", encoding="utf-8")
    (source / "resources" / "app.asar").write_text("asar\n", encoding="utf-8")

    payload = _export_packaged_release(source, destination)

    assert payload["ok"] is True
    assert (destination / "NAIA.exe").is_file()
    assert (destination / "resources" / "app.asar").is_file()
    assert payload["destination"] == str(destination)


def test_electron_portable_workspace_refuses_nonempty_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "old.txt").write_text("old\n", encoding="utf-8")

    payload = run_electron_portable_workspace(
        source_root=Path.cwd(),
        workspace_root=workspace,
        dry_run=True,
    )

    assert payload["ok"] is False
    assert "refusing to overwrite" in payload["violations"][0]["reason"]


def test_electron_portable_workspace_cli_dry_run_writes_evidence(tmp_path):
    workspace = tmp_path / "workspace"
    output = tmp_path / "evidence.json"

    result = subprocess.run(
        [
            sys.executable,
            "tools/run_electron_portable_workspace.py",
            "--workspace",
            str(workspace),
            "--output",
            str(output),
            "--dry-run",
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
    assert payload["output"] == str(output.resolve())
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["builder_config"] == payload["builder_config"]


def test_electron_portable_workspace_summary_omits_nested_sections(tmp_path):
    payload = run_electron_portable_workspace(
        source_root=Path.cwd(),
        workspace_root=tmp_path / "workspace",
        dry_run=True,
    )

    summary = summarize_electron_portable_workspace(payload)

    assert summary["ok"] is True
    assert summary["dry_run"] is True
    assert isinstance(summary["ready_to_build"], bool)
    assert isinstance(summary["electron_dependencies"]["ok"], bool)
    assert isinstance(summary["electron_dependencies"]["next_action_required"], bool)
    assert summary["electron_builder"]["status"] == "dry_run"
    assert summary["blocking_violation_count"] == len(payload["blocking_violations"])
    assert ("electron_dependencies" in summary["failed_sections"]) is (not summary["electron_dependencies"]["ok"])
    assert "electron_builder" not in summary["failed_sections"]
    assert "sections" not in summary


def test_electron_portable_workspace_cli_summary_no_output(tmp_path):
    workspace = tmp_path / "workspace"
    output = tmp_path / "should_not_exist.json"

    result = subprocess.run(
        [
            sys.executable,
            "tools/run_electron_portable_workspace.py",
            "--workspace",
            str(workspace),
            "--output",
            str(output),
            "--dry-run",
            "--summary",
            "--no-output",
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
    assert payload["dry_run"] is True
    assert isinstance(payload["electron_dependencies"]["next_action_required"], bool)
    assert "sections" not in payload
    assert not output.exists()


def test_electron_portable_workspace_passes_runtime_smoke_into_final_evidence(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    def fake_staging(*, workspace_root, **_kwargs):
        release_root = Path(workspace_root) / "NAIA-Web"
        (release_root / "resources" / "naia-backend").mkdir(parents=True)
        return {"ok": True, "violations": []}

    def fake_dependency_readiness(*_args, **_kwargs):
        return {"ok": True, "violations": []}

    def fake_distribution_strategy(*_args, **_kwargs):
        return {"ok": True, "violations": []}

    def fake_run(*_args, **_kwargs):
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def fake_smoke(*_args, **_kwargs):
        return {"ok": True, "violations": []}

    def fake_clean(*_args, **_kwargs):
        return {"ok": True, "violations": []}

    def fake_icon(exe, icon):
        captured["icon_exe"] = exe
        captured["icon"] = icon
        return {"ok": True, "exe": str(exe), "icon": str(icon), "violations": []}

    def fake_export(source, destination):
        captured["export_source"] = source
        captured["export_destination"] = destination
        return {"ok": True, "source": str(source), "destination": str(destination), "violations": []}

    def fake_evidence(**kwargs):
        captured.update(kwargs)
        return {"ok": True, "violations": []}

    monkeypatch.setattr("tools.run_electron_portable_workspace.run_release_workspace", fake_staging)
    monkeypatch.setattr("tools.run_electron_portable_workspace.check_electron_dependency_readiness", fake_dependency_readiness)
    monkeypatch.setattr("tools.run_electron_portable_workspace.check_release_distribution_strategy", fake_distribution_strategy)
    monkeypatch.setattr("tools.run_electron_portable_workspace.subprocess.run", fake_run)
    monkeypatch.setattr("tools.run_electron_portable_workspace.apply_windows_exe_icon", fake_icon)
    monkeypatch.setattr("tools.run_electron_portable_workspace._export_packaged_release", fake_export)
    monkeypatch.setattr("tools.run_electron_portable_workspace.smoke_packaged_electron_app", fake_smoke)
    monkeypatch.setattr("tools.run_electron_portable_workspace.check_clean_machine_readiness", fake_clean)
    monkeypatch.setattr("tools.run_electron_portable_workspace.smoke_electron_cdp", fake_smoke)
    monkeypatch.setattr("tools.run_electron_portable_workspace.write_release_evidence_report", fake_evidence)

    payload = run_electron_portable_workspace(
        source_root=Path.cwd(),
        workspace_root=tmp_path / "workspace",
        dry_run=False,
        run_electron_cdp=True,
        electron_timeout=13,
    )

    assert payload["ok"] is True
    assert payload["sections"]["electron_cdp_smoke"]["ok"] is True
    assert payload["sections"]["exe_icon"]["ok"] is True
    assert captured["icon_exe"] == tmp_path / "workspace" / "_build" / "electron-dist" / "win-unpacked" / "NAIA.exe"
    assert captured["icon"] == Path.cwd() / "app" / "electron" / "assets" / "naia.ico"
    assert payload["sections"]["portable_export"]["ok"] is True
    assert captured["export_source"] == tmp_path / "workspace" / "_build" / "electron-dist" / "win-unpacked"
    assert captured["export_destination"] == tmp_path / "workspace" / "NAIA-Portable"
    assert captured["skip_electron_runtime"] is False
    assert captured["electron_timeout"] == 13
    assert captured["packaged_root"] == tmp_path / "workspace" / "NAIA-Portable"
