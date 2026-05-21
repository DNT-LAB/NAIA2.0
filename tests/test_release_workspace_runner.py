import json
import subprocess
import sys
from pathlib import Path

from tools.run_release_workspace import run_release_workspace
from tools.run_release_workspace import summarize_release_workspace


def test_release_workspace_runner_builds_clean_staged_artifact(tmp_path):
    workspace = tmp_path / "workspace"
    output = tmp_path / "workspace_evidence.json"

    payload = run_release_workspace(
        source_root=Path.cwd(),
        workspace_root=workspace,
        output=output,
    )

    assert payload["ok"] is True
    assert output.is_file()
    assert (workspace / "NAIA-Web" / "resources" / "naia-backend" / "NAIA_web_headless.py").is_file()
    assert payload["sections"]["smoke_backend"]["ok"] is True
    assert payload["sections"]["smoke_web_contract"]["ok"] is True
    assert payload["sections"]["clean_machine"]["ok"] is True
    assert payload["sections"]["clean_machine"]["stats"]["file_count"] >= 300
    release_root = workspace / "NAIA-Web"
    assert not any((release_root / "user-data").iterdir())
    assert Path(payload["smoke_user_data_root"]).is_dir()
    assert not str(Path(payload["smoke_user_data_root"]).resolve()).startswith(str(release_root.resolve()))
    assert not any((release_root / "resources" / "naia-backend").rglob("__pycache__"))


def test_release_workspace_runner_can_build_base_only_python_runtime(tmp_path):
    workspace = tmp_path / "workspace"

    payload = run_release_workspace(
        source_root=Path.cwd(),
        workspace_root=workspace,
        build_clean_python_runtime=True,
        require_bundled_python=True,
    )

    runtime = workspace / "NAIA-Web" / "resources" / "python"
    site_packages = runtime / "Lib" / "site-packages"

    assert payload["ok"] is True
    assert payload["build_clean_python_runtime"] is True
    assert payload["sections"]["build_python_runtime"]["base_only"] is True
    assert (runtime / "python.exe").is_file()
    assert (runtime / "Lib" / "venv" / "__init__.py").is_file()
    assert not (site_packages / "fastapi").exists()


def test_release_workspace_runner_can_embed_final_evidence_without_failing_staged_gate(tmp_path):
    workspace = tmp_path / "workspace"

    payload = run_release_workspace(
        source_root=Path.cwd(),
        workspace_root=workspace,
        include_final_evidence=True,
    )

    assert payload["ok"] is True
    assert payload["include_final_evidence"] is True
    final_evidence = payload["sections"]["final_release_evidence"]
    assert final_evidence["ok"] is False
    assert final_evidence["staged_root"] == str((workspace / "NAIA-Web").resolve())
    assert "packaged_release" in final_evidence["failed_sections"]
    assert "electron_runtime" in final_evidence["failed_sections"]
    assert final_evidence["sections"]["staged_release"]["ok"] is True


def test_release_workspace_runner_summary_omits_nested_sections(tmp_path):
    workspace = tmp_path / "workspace"

    payload = run_release_workspace(
        source_root=Path.cwd(),
        workspace_root=workspace,
        include_final_evidence=True,
    )
    summary = summarize_release_workspace(payload)

    assert summary["ok"] is True
    assert summary["include_final_evidence"] is True
    assert summary["workspace_scope"] == "provided"
    assert summary["workspace_retained_for_inspection"] is False
    assert summary["release_root_exists"] is True
    assert summary["artifact_user_data_root"].endswith("NAIA-Web\\user-data") or summary["artifact_user_data_root"].endswith("NAIA-Web/user-data")
    assert summary["smoke_user_data_root"].endswith("smoke-user-data")
    assert summary["failed_sections"] == []
    assert summary["smoke_backend"]["ok"] is True
    assert summary["smoke_web_contract"]["ok"] is True
    assert summary["stage_backend"]["file_count"] >= 300
    assert summary["clean_machine"]["file_count"] >= 300
    assert summary["measurement"]["size_bytes"] > 0
    assert summary["final_release_evidence"]["ok"] is False
    assert "packaged_release" in summary["final_release_evidence"]["failed_sections"]
    assert "electron_runtime" in summary["final_release_evidence"]["failed_sections"]
    assert summary["final_release_evidence"]["goal_audit_blocker_count"] >= 0
    assert "sections" not in summary


def test_release_workspace_runner_refuses_nonempty_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "old.txt").write_text("old\n", encoding="utf-8")

    payload = run_release_workspace(source_root=Path.cwd(), workspace_root=workspace)

    assert payload["ok"] is False
    assert "refusing to overwrite" in payload["violations"][0]["reason"]


def test_release_workspace_runner_cli_writes_evidence(tmp_path):
    workspace = tmp_path / "workspace"
    output = tmp_path / "evidence.json"

    result = subprocess.run(
        [
            sys.executable,
            "tools/run_release_workspace.py",
            "--workspace",
            str(workspace),
            "--output",
            str(output),
            "--include-final-evidence",
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
    assert payload["sections"]["final_release_evidence"]["ok"] is False
    assert json.loads(output.read_text(encoding="utf-8"))["ok"] is True


def test_release_workspace_runner_cli_summary(tmp_path):
    workspace = tmp_path / "workspace"

    result = subprocess.run(
        [
            sys.executable,
            "tools/run_release_workspace.py",
            "--workspace",
            str(workspace),
            "--include-final-evidence",
            "--summary",
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
    assert payload["include_final_evidence"] is True
    assert payload["workspace_scope"] == "provided"
    assert payload["workspace_retained_for_inspection"] is False
    assert payload["release_root_exists"] is True
    assert payload["final_release_evidence"]["ok"] is False
    assert "sections" not in payload


def test_release_workspace_runner_cli_summary_marks_temporary_workspace_retained():
    result = subprocess.run(
        [
            sys.executable,
            "tools/run_release_workspace.py",
            "--summary",
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
    assert payload["created_temporary_workspace"] is True
    assert payload["workspace_scope"] == "temporary"
    assert payload["workspace_retained_for_inspection"] is True
    assert payload["release_root_exists"] is True
