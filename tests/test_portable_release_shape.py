import json
import subprocess
import sys
from pathlib import Path

from tools.check_portable_release_shape import check_portable_release_shape


TMP_CASE_ROOT = Path("tmp/portable_release_shape_test_cases")


def _case_path(name: str) -> Path:
    TMP_CASE_ROOT.mkdir(parents=True, exist_ok=True)
    return TMP_CASE_ROOT / name


def test_portable_release_shape_accepts_current_contract():
    payload = check_portable_release_shape()

    assert payload["ok"] is True
    assert payload["portable_root_name"] == "NAIA-Portable"
    assert payload["internal_builder_root"] == "_build/electron-dist/win-unpacked"
    assert "NAIA.exe" in payload["required_user_visible_entries"]
    assert payload["required_package_script_count"] >= 8


def test_portable_release_shape_rejects_release_check_without_gate():
    manifest = json.loads(Path("release_assets/manifests/portable_release_shape.json").read_text(encoding="utf-8"))
    package = json.loads(Path("app/electron/package.json").read_text(encoding="utf-8"))
    package["scripts"]["release:check"] = package["scripts"]["release:check"].replace(
        " && npm run check:portable-shape",
        "",
    )
    manifest_path = _case_path("portable_shape_missing_gate.json")
    package_path = _case_path("package_missing_gate.json")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    package_path.write_text(json.dumps(package), encoding="utf-8")

    payload = check_portable_release_shape(manifest_path, electron_package_path=package_path)

    assert payload["ok"] is False
    assert any("release:check must include check:portable-shape" in item["reason"] for item in payload["violations"])


def test_portable_release_shape_rejects_exposing_win_unpacked_as_packaged_root():
    runner = Path("tools/run_electron_portable_workspace.py").read_text(encoding="utf-8")
    runner_path = _case_path("runner_exposes_win_unpacked.py")
    runner_path.write_text(
        runner.replace("packaged_root = portable_release_root", "packaged_root = builder_packaged_root"),
        encoding="utf-8",
    )

    payload = check_portable_release_shape(runner_path=runner_path)

    assert payload["ok"] is False
    assert any("packaged_root = portable_release_root" in item["reason"] for item in payload["violations"])


def test_portable_release_shape_rejects_direct_electron_builder_release_script():
    manifest = json.loads(Path("release_assets/manifests/portable_release_shape.json").read_text(encoding="utf-8"))
    package = json.loads(Path("app/electron/package.json").read_text(encoding="utf-8"))
    package["scripts"]["release:portable:smoke"] = "electron-builder --dir --config package.json"
    manifest_path = _case_path("portable_shape_direct_builder.json")
    package_path = _case_path("package_direct_builder.json")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    package_path.write_text(json.dumps(package), encoding="utf-8")

    payload = check_portable_release_shape(manifest_path, electron_package_path=package_path)

    assert payload["ok"] is False
    assert any("must route through run_electron_portable_workspace.py" in item["reason"] for item in payload["violations"])
    assert any("must not call electron-builder directly" in item["reason"] for item in payload["violations"])


def test_portable_release_shape_checker_cli():
    result = subprocess.run(
        [sys.executable, "tools/check_portable_release_shape.py"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
