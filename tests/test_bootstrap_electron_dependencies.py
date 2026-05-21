import json
import subprocess
import sys
from pathlib import Path

from tools.bootstrap_electron_dependencies import bootstrap_electron_dependencies
from tools.bootstrap_electron_dependencies import summarize_electron_dependency_bootstrap


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_package(electron_root: Path, *, electron: str = "42.1.0", builder: str = "26.8.1") -> None:
    _write(
        electron_root / "package.json",
        json.dumps(
            {
                "devDependencies": {
                    "electron": electron,
                    "electron-builder": builder,
                }
            }
        ),
    )


def _write_lock(electron_root: Path, *, electron: str = "42.1.0", builder: str = "26.8.1") -> None:
    _write(
        electron_root / "package-lock.json",
        json.dumps(
            {
                "lockfileVersion": 3,
                "packages": {
                    "node_modules/electron": {"version": electron},
                    "node_modules/electron-builder": {"version": builder},
                },
            }
        ),
    )


def _write_installed(electron_root: Path, *, electron: str = "42.1.0", builder: str = "26.8.1") -> None:
    _write(electron_root / "node_modules" / "electron" / "package.json", json.dumps({"version": electron}))
    _write(electron_root / "node_modules" / "electron-builder" / "package.json", json.dumps({"version": builder}))
    _write(electron_root / "node_modules" / ".bin" / "electron.cmd", "")
    _write(electron_root / "node_modules" / ".bin" / "electron-builder.cmd", "")


def test_bootstrap_electron_dependencies_dry_run_uses_install_without_lock(tmp_path, monkeypatch):
    electron_root = tmp_path / "app" / "electron"
    _write_package(electron_root)
    monkeypatch.setattr("tools.bootstrap_electron_dependencies.shutil.which", lambda name: "npm.cmd")

    payload = bootstrap_electron_dependencies(electron_root=electron_root)

    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["strategy"] == "install"
    assert payload["command"] == ["npm.cmd", "install", "--include=dev", "--no-fund"]
    assert payload["requires_explicit_approval"] is True
    assert str(electron_root / "node_modules") in payload["mutation_targets"]
    assert payload["ready_before"] is False
    assert payload["ready_after"] is False


def test_bootstrap_electron_dependencies_dry_run_uses_ci_with_lock(tmp_path, monkeypatch):
    electron_root = tmp_path / "app" / "electron"
    _write_package(electron_root)
    _write_lock(electron_root)
    monkeypatch.setattr("tools.bootstrap_electron_dependencies.shutil.which", lambda name: "npm.cmd")

    payload = bootstrap_electron_dependencies(electron_root=electron_root)

    assert payload["ok"] is True
    assert payload["strategy"] == "ci"
    assert payload["command"] == ["npm.cmd", "ci", "--include=dev", "--no-fund"]


def test_bootstrap_electron_dependencies_refuses_execute_without_yes(tmp_path, monkeypatch):
    electron_root = tmp_path / "app" / "electron"
    _write_package(electron_root)
    monkeypatch.setattr("tools.bootstrap_electron_dependencies.shutil.which", lambda name: "npm.cmd")

    payload = bootstrap_electron_dependencies(electron_root=electron_root, dry_run=False, yes=False)

    assert payload["ok"] is False
    assert payload["run"] is None
    assert any("--yes" in item["reason"] for item in payload["violations"])


def test_bootstrap_electron_dependencies_execute_runs_and_rechecks(tmp_path, monkeypatch):
    electron_root = tmp_path / "app" / "electron"
    _write_package(electron_root)
    calls = []
    monkeypatch.setattr("tools.bootstrap_electron_dependencies.shutil.which", lambda name: "npm.cmd")

    def fake_run(command, cwd, **kwargs):
        calls.append((command, Path(cwd)))
        _write_lock(electron_root)
        _write_installed(electron_root)
        return subprocess.CompletedProcess(command, 0, stdout="installed\n", stderr="")

    monkeypatch.setattr("tools.bootstrap_electron_dependencies.subprocess.run", fake_run)

    payload = bootstrap_electron_dependencies(electron_root=electron_root, dry_run=False, yes=True)

    assert payload["ok"] is True
    assert payload["requires_explicit_approval"] is False
    assert payload["ready_before"] is False
    assert payload["ready_after"] is True
    assert calls == [(["npm.cmd", "install", "--include=dev", "--no-fund"], electron_root.resolve())]
    assert payload["run"]["stdout"] == "installed\n"


def test_bootstrap_electron_dependencies_ci_requires_lock(tmp_path, monkeypatch):
    electron_root = tmp_path / "app" / "electron"
    _write_package(electron_root)
    monkeypatch.setattr("tools.bootstrap_electron_dependencies.shutil.which", lambda name: "npm.cmd")

    payload = bootstrap_electron_dependencies(electron_root=electron_root, strategy="ci")

    assert payload["ok"] is False
    assert any("npm ci requires package-lock.json" in item["reason"] for item in payload["violations"])


def test_bootstrap_electron_dependencies_rejects_nonexact_package_versions(tmp_path, monkeypatch):
    electron_root = tmp_path / "app" / "electron"
    _write_package(electron_root, electron="42.x")
    monkeypatch.setattr("tools.bootstrap_electron_dependencies.shutil.which", lambda name: "npm.cmd")

    payload = bootstrap_electron_dependencies(electron_root=electron_root)

    assert payload["ok"] is False
    assert any("must be pinned to an exact version" in item["reason"] for item in payload["violations"])


def test_bootstrap_electron_dependencies_cli_dry_run(tmp_path):
    electron_root = tmp_path / "app" / "electron"
    output = tmp_path / "bootstrap.json"
    _write_package(electron_root)

    result = subprocess.run(
        [
            sys.executable,
            "tools/bootstrap_electron_dependencies.py",
            "--electron-root",
            str(electron_root),
            "--npm",
            "npm",
            "--output",
            str(output),
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
    assert payload["dry_run"] is True
    assert output.is_file()


def test_bootstrap_electron_dependencies_summary_omits_nested_readiness(tmp_path, monkeypatch):
    electron_root = tmp_path / "app" / "electron"
    _write_package(electron_root)
    monkeypatch.setattr("tools.bootstrap_electron_dependencies.shutil.which", lambda name: "npm.cmd")

    payload = bootstrap_electron_dependencies(electron_root=electron_root)
    summary = summarize_electron_dependency_bootstrap(payload)

    assert summary["ok"] is True
    assert summary["dry_run"] is True
    assert summary["strategy"] == "install"
    assert summary["requires_explicit_approval"] is True
    assert summary["ready_before"] is False
    assert summary["ready_after"] is False
    assert summary["before"]["violation_count"] == len(payload["before"]["violations"])
    assert summary["next_action"]["required"] is True
    assert summary["next_action"]["final_release_script"]
    assert "before" in summary
    assert "dependency_checks" not in summary["before"]


def test_bootstrap_electron_dependencies_cli_summary(tmp_path):
    electron_root = tmp_path / "app" / "electron"
    _write_package(electron_root)

    result = subprocess.run(
        [
            sys.executable,
            "tools/bootstrap_electron_dependencies.py",
            "--electron-root",
            str(electron_root),
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
    assert payload["dry_run"] is True
    assert payload["next_action"]["required"] is True
    assert "dependency_checks" not in payload["before"]
