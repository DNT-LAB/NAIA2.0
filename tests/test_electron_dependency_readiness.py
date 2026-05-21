import json
import subprocess
import sys
from pathlib import Path

from tools.check_electron_dependency_readiness import check_electron_dependency_readiness
from tools.check_electron_dependency_readiness import summarize_electron_dependency_readiness


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_package(electron_root: Path, *, electron: str = "42.1.0", builder: str = "26.8.1") -> Path:
    package = electron_root / "package.json"
    _write(
        package,
        json.dumps(
            {
                "devDependencies": {
                    "electron": electron,
                    "electron-builder": builder,
                }
            }
        ),
    )
    return package


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


def test_electron_dependency_readiness_accepts_pinned_installed_dependencies(tmp_path):
    electron_root = tmp_path / "app" / "electron"
    package = _write_package(electron_root)
    _write_lock(electron_root)
    _write_installed(electron_root)

    payload = check_electron_dependency_readiness(electron_package_path=package)

    assert payload["ok"] is True
    assert payload["violations"] == []
    assert payload["next_action"]["required"] is False
    assert payload["next_action"]["requires_explicit_approval"] is False
    assert payload["dependency_checks"]["electron"]["installed"] is True
    assert payload["dependency_checks"]["electron-builder"]["bin_ready"] is True


def test_electron_dependency_readiness_summary_omits_package_paths(tmp_path):
    electron_root = tmp_path / "app" / "electron"
    package = _write_package(electron_root)

    payload = check_electron_dependency_readiness(electron_package_path=package)
    summary = summarize_electron_dependency_readiness(payload)

    assert summary["ok"] is False
    assert summary["violation_count"] == len(payload["violations"])
    assert summary["dependencies"]["electron"]["declared"] == "42.1.0"
    assert summary["dependencies"]["electron"]["installed"] is False
    assert summary["dependencies"]["electron-builder"]["bin_ready"] is False
    assert summary["next_action"]["required"] is True
    assert summary["next_action"]["requires_explicit_approval"] is True
    assert "installed_package" not in summary["dependencies"]["electron"]
    assert "dependency_checks" not in summary


def test_electron_dependency_readiness_rejects_missing_lock_and_node_modules(tmp_path):
    electron_root = tmp_path / "app" / "electron"
    package = _write_package(electron_root)

    payload = check_electron_dependency_readiness(electron_package_path=package)

    assert payload["ok"] is False
    assert payload["next_action"]["required"] is True
    assert payload["next_action"]["requires_explicit_approval"] is True
    assert payload["next_action"]["strategy"] == "install"
    assert "release:final:install:scan" in payload["next_action"]["final_release_script"]
    reasons = "\n".join(item["reason"] for item in payload["violations"])
    assert "package-lock.json" in reasons
    assert "installed dependency is missing: electron" in reasons
    assert "installed dependency is missing: electron-builder" in reasons


def test_electron_dependency_readiness_recommends_ci_when_lock_exists(tmp_path):
    electron_root = tmp_path / "app" / "electron"
    package = _write_package(electron_root)
    _write_lock(electron_root)

    payload = check_electron_dependency_readiness(electron_package_path=package)

    assert payload["ok"] is False
    assert payload["next_action"]["strategy"] == "ci"
    assert "deps:ci" in payload["next_action"]["script"]


def test_electron_dependency_readiness_rejects_version_drift(tmp_path):
    electron_root = tmp_path / "app" / "electron"
    package = _write_package(electron_root, electron="^42.1.0")
    _write_lock(electron_root, electron="42.1.0")
    _write_installed(electron_root, electron="42.1.0")

    payload = check_electron_dependency_readiness(electron_package_path=package)

    assert payload["ok"] is False
    reasons = "\n".join(item["reason"] for item in payload["violations"])
    assert "must be pinned to an exact version" in reasons
    assert "does not match package.json" in reasons


def test_electron_dependency_readiness_cli(tmp_path):
    electron_root = tmp_path / "app" / "electron"
    package = _write_package(electron_root)
    _write_lock(electron_root)
    _write_installed(electron_root)

    result = subprocess.run(
        [
            sys.executable,
            "tools/check_electron_dependency_readiness.py",
            "--electron-package",
            str(package),
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


def test_electron_dependency_readiness_cli_summary(tmp_path):
    electron_root = tmp_path / "app" / "electron"
    package = _write_package(electron_root)

    result = subprocess.run(
        [
            sys.executable,
            "tools/check_electron_dependency_readiness.py",
            "--electron-package",
            str(package),
            "--summary",
        ],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["next_action"]["required"] is True
    assert "dependency_checks" not in payload
