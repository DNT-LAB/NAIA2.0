import json
import subprocess
import sys
from pathlib import Path

from tools.check_final_release_approval_gate import check_final_release_approval_gate


def test_final_release_approval_gate_accepts_current_preapproval_state():
    payload = check_final_release_approval_gate()

    assert payload["ok"] is True
    assert payload["mode"] in {"approval_required", "runtime_evidence_incomplete", "release_ready"}
    if payload["mode"] == "approval_required":
        assert payload["release_ready"] is False
        assert payload["blocked_on_approval"] is True
        assert payload["blocker_count"] > 0
    elif payload["mode"] == "runtime_evidence_incomplete":
        assert payload["release_ready"] is False
        assert payload["blocker_count"] > 0
    else:
        assert payload["release_ready"] is True
        assert payload["blocker_count"] == 0
    assert payload["final_script"] == "release:final:install:scan"
    assert payload["violation_count"] == 0


def test_final_release_approval_gate_rejects_missing_approval_gate_script(tmp_path):
    package = json.loads(Path("app/electron/package.json").read_text(encoding="utf-8"))
    package["scripts"].pop("check:approval-gate", None)
    package["scripts"]["release:check"] = package["scripts"]["release:check"].replace(
        " && npm run check:approval-gate",
        "",
    )
    package_path = tmp_path / "package.json"
    package_path.write_text(json.dumps(package), encoding="utf-8")

    payload = check_final_release_approval_gate(electron_package_path=package_path)

    assert payload["ok"] is False
    assert any("release:check must include check:approval-gate" in item["reason"] for item in payload["violations"])
    assert any(
        "check:approval-gate must run tools/check_final_release_approval_gate.py" in item["reason"]
        for item in payload["violations"]
    )


def test_final_release_approval_gate_rejects_final_install_scan_without_required_terms(tmp_path):
    package = json.loads(Path("app/electron/package.json").read_text(encoding="utf-8"))
    package["scripts"]["release:final:install:scan"] = (
        "cd ../.. && python tools/run_final_electron_release_gate.py --execute --install-deps --yes"
    )
    package_path = tmp_path / "package.json"
    package_path.write_text(json.dumps(package), encoding="utf-8")

    payload = check_final_release_approval_gate(electron_package_path=package_path)

    assert payload["ok"] is False
    assert any("release:final:install:scan missing --run-electron-cdp" in item["reason"] for item in payload["violations"])
    assert any("release:final:install:scan missing --defender-scan" in item["reason"] for item in payload["violations"])
    assert any(
        "release:final:install:scan missing --require-defender-scan" in item["reason"]
        for item in payload["violations"]
    )


def test_final_release_approval_gate_cli_summary():
    result = subprocess.run(
        [sys.executable, "tools/check_final_release_approval_gate.py", "--summary"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["mode"] in {"approval_required", "runtime_evidence_incomplete", "release_ready"}
    if payload["mode"] == "approval_required":
        assert payload["blocked_on_approval"] is True
        assert payload["blocker_count"] > 0
    elif payload["mode"] == "runtime_evidence_incomplete":
        assert payload["release_ready"] is False
        assert payload["blocker_count"] > 0
    else:
        assert payload["release_ready"] is True
        assert payload["blocker_count"] == 0
