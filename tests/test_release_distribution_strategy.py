import json
import subprocess
import sys
from pathlib import Path

from tools.check_release_distribution_strategy import check_release_distribution_strategy


def test_release_distribution_strategy_accepts_current_contract():
    payload = check_release_distribution_strategy()

    assert payload["ok"] is True
    assert payload["first_release_artifact"] == "portable-app-folder"
    assert payload["installer_candidate_count"] == 3
    assert payload["auto_update_status"] == "deferred"
    assert payload["script_term_rule_count"] >= 8
    assert payload["non_mutating_script_rule_count"] >= 8
    assert payload["ok"] is True


def test_release_distribution_strategy_rejects_final_script_without_required_smoke_and_scan_terms(tmp_path):
    strategy = json.loads(Path("release_assets/manifests/release_distribution_strategy.json").read_text(encoding="utf-8"))
    package = json.loads(Path("app/electron/package.json").read_text(encoding="utf-8"))
    package["scripts"]["release:final"] = "cd ../.. && python tools/run_final_electron_release_gate.py --execute"
    strategy_path = tmp_path / "strategy.json"
    package_path = tmp_path / "package.json"
    strategy_path.write_text(json.dumps(strategy), encoding="utf-8")
    package_path.write_text(json.dumps(package), encoding="utf-8")

    payload = check_release_distribution_strategy(strategy_path, electron_package_path=package_path)

    assert payload["ok"] is False
    assert any("release:final must include --run-electron-cdp" in item["reason"] for item in payload["violations"])
    assert any("release:final must include --require-defender-scan" in item["reason"] for item in payload["violations"])


def test_release_distribution_strategy_rejects_required_script_terms_out_of_order(tmp_path):
    strategy = json.loads(Path("release_assets/manifests/release_distribution_strategy.json").read_text(encoding="utf-8"))
    package = json.loads(Path("app/electron/package.json").read_text(encoding="utf-8"))
    package["scripts"]["release:final:install:scan"] = (
        "cd ../.. && python tools/run_final_electron_release_gate.py "
        "--execute --install-deps --run-electron-cdp --yes --defender-scan --require-defender-scan"
    )
    strategy_path = tmp_path / "strategy.json"
    package_path = tmp_path / "package.json"
    strategy_path.write_text(json.dumps(strategy), encoding="utf-8")
    package_path.write_text(json.dumps(package), encoding="utf-8")

    payload = check_release_distribution_strategy(strategy_path, electron_package_path=package_path)

    assert payload["ok"] is False
    assert any(
        "release:final:install:scan must keep required term order: --run-electron-cdp" in item["reason"]
        for item in payload["violations"]
    )


def test_release_distribution_strategy_requires_unsigned_portable_win_build_settings(tmp_path):
    strategy = json.loads(Path("release_assets/manifests/release_distribution_strategy.json").read_text(encoding="utf-8"))
    package = json.loads(Path("app/electron/package.json").read_text(encoding="utf-8"))
    package["build"]["win"].pop("signAndEditExecutable", None)
    package["build"]["win"]["forceCodeSigning"] = True
    strategy_path = tmp_path / "strategy.json"
    package_path = tmp_path / "package.json"
    strategy_path.write_text(json.dumps(strategy), encoding="utf-8")
    package_path.write_text(json.dumps(package), encoding="utf-8")

    payload = check_release_distribution_strategy(strategy_path, electron_package_path=package_path)

    assert payload["ok"] is False
    assert any(
        "win.signAndEditExecutable=false" in item["reason"]
        for item in payload["violations"]
    )
    assert any(
        "win.forceCodeSigning=false" in item["reason"]
        for item in payload["violations"]
    )


def test_release_distribution_strategy_rejects_mutating_plan_scripts(tmp_path):
    strategy = json.loads(Path("release_assets/manifests/release_distribution_strategy.json").read_text(encoding="utf-8"))
    package = json.loads(Path("app/electron/package.json").read_text(encoding="utf-8"))
    package["scripts"]["release:final:plan"] = (
        "cd ../.. && python tools/run_final_electron_release_gate.py --execute --install-deps --yes"
    )
    package["scripts"]["check:approval-gate"] = (
        "cd ../.. && python tools/check_final_release_approval_gate.py --execute --defender-scan"
    )
    package["scripts"]["deps:plan"] = "npm install --include=dev"
    package["scripts"]["deps:plan:summary"] = (
        "cd ../.. && python tools/bootstrap_electron_dependencies.py --summary --execute --yes"
    )
    strategy_path = tmp_path / "strategy.json"
    package_path = tmp_path / "package.json"
    strategy_path.write_text(json.dumps(strategy), encoding="utf-8")
    package_path.write_text(json.dumps(package), encoding="utf-8")

    payload = check_release_distribution_strategy(strategy_path, electron_package_path=package_path)

    assert payload["ok"] is False
    assert any(
        "release:final:plan must not include --execute" in item["reason"]
        for item in payload["violations"]
    )
    assert any(
        "deps:plan must not include npm install" in item["reason"]
        for item in payload["violations"]
    )
    assert any(
        "deps:plan:summary must not include --yes" in item["reason"]
        for item in payload["violations"]
    )
    assert any(
        "check:approval-gate must not include --execute" in item["reason"]
        for item in payload["violations"]
    )
    assert any(
        "check:approval-gate must not include --defender-scan" in item["reason"]
        for item in payload["violations"]
    )


def test_release_distribution_strategy_requires_runtime_distribution_in_release_check(tmp_path):
    strategy = json.loads(Path("release_assets/manifests/release_distribution_strategy.json").read_text(encoding="utf-8"))
    package = json.loads(Path("app/electron/package.json").read_text(encoding="utf-8"))
    package["scripts"]["release:check"] = package["scripts"]["release:check"].replace(
        " && npm run check:runtime-distribution",
        "",
    )
    strategy_path = tmp_path / "strategy.json"
    package_path = tmp_path / "package.json"
    strategy_path.write_text(json.dumps(strategy), encoding="utf-8")
    package_path.write_text(json.dumps(package), encoding="utf-8")

    payload = check_release_distribution_strategy(strategy_path, electron_package_path=package_path)

    assert payload["ok"] is False
    assert any(
        "release:check must include check:runtime-distribution" in item["reason"]
        for item in payload["violations"]
    )


def test_release_distribution_strategy_requires_final_plan_summary_no_output(tmp_path):
    strategy = json.loads(Path("release_assets/manifests/release_distribution_strategy.json").read_text(encoding="utf-8"))
    package = json.loads(Path("app/electron/package.json").read_text(encoding="utf-8"))
    package["scripts"]["release:final:plan:summary"] = (
        "cd ../.. && python tools/run_final_electron_release_gate.py --summary"
    )
    strategy_path = tmp_path / "strategy.json"
    package_path = tmp_path / "package.json"
    strategy_path.write_text(json.dumps(strategy), encoding="utf-8")
    package_path.write_text(json.dumps(package), encoding="utf-8")

    payload = check_release_distribution_strategy(strategy_path, electron_package_path=package_path)

    assert payload["ok"] is False
    assert any(
        "release:final:plan:summary must include --output \"\"" in item["reason"]
        for item in payload["violations"]
    )
    assert any(
        "release:final:plan:summary must include --portable-output \"\"" in item["reason"]
        for item in payload["violations"]
    )


def test_release_distribution_strategy_requires_release_evidence_summary_no_output(tmp_path):
    strategy = json.loads(Path("release_assets/manifests/release_distribution_strategy.json").read_text(encoding="utf-8"))
    package = json.loads(Path("app/electron/package.json").read_text(encoding="utf-8"))
    package["scripts"]["release:evidence:summary"] = (
        "cd ../.. && python tools/write_release_evidence_report.py --summary"
    )
    strategy_path = tmp_path / "strategy.json"
    package_path = tmp_path / "package.json"
    strategy_path.write_text(json.dumps(strategy), encoding="utf-8")
    package_path.write_text(json.dumps(package), encoding="utf-8")

    payload = check_release_distribution_strategy(strategy_path, electron_package_path=package_path)

    assert payload["ok"] is False
    assert any(
        "release:evidence:summary must include --no-output" in item["reason"]
        for item in payload["violations"]
    )
    assert any(
        "release:evidence:summary must include --skip-electron-runtime" in item["reason"]
        for item in payload["violations"]
    )


def test_release_distribution_strategy_checker_cli():
    result = subprocess.run(
        [sys.executable, "tools/check_release_distribution_strategy.py"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
