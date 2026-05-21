import json
import subprocess
import sys
from pathlib import Path

from tools.run_final_electron_release_gate import run_final_electron_release_gate, summarize_final_release_gate


def _ready_portable_payload(tmp_path: Path) -> dict[str, object]:
    return {
        "ok": True,
        "dry_run": False,
        "ready_to_build": True,
        "run_electron_cdp": True,
        "defender_scan": True,
        "require_defender_scan": True,
        "packaged_root": str(tmp_path / "dist" / "win-unpacked"),
        "sections": {
            "electron_builder": {"ok": True},
            "packaged_smoke": {"ok": True},
            "clean_packaged": {"ok": True},
            "electron_cdp_smoke": {"ok": True},
        },
    }


def test_final_electron_release_gate_plan_mode_runs_safe_dry_run(monkeypatch, tmp_path):
    calls = {}

    def fake_bootstrap(**kwargs):
        calls["bootstrap"] = kwargs
        return {
            "ok": True,
            "ready_before": False,
            "ready_after": False,
            "violations": [],
            "before": {
                "next_action": {
                    "required": True,
                    "requires_explicit_approval": True,
                    "script": "npm --prefix app/electron run deps:install",
                    "final_release_script": "npm --prefix app/electron run release:final:install:scan",
                    "strategy": "install",
                    "mutates": ["app/electron/package-lock.json", "app/electron/node_modules"],
                }
            },
        }

    def fake_portable(**kwargs):
        calls["portable"] = kwargs
        return {"ok": True, "dry_run": True, "blocking_violations": [{"reason": "deps missing"}]}

    def fake_audit(**kwargs):
        calls["audit"] = kwargs
        return {
            "ok": False,
            "blocker_count": 1,
            "blockers_by_round": {"Runtime Evidence": 1},
            "blockers": [{"type": "missing-runtime-evidence", "reason": "packaged missing"}],
        }

    monkeypatch.setattr("tools.run_final_electron_release_gate.bootstrap_electron_dependencies", fake_bootstrap)
    monkeypatch.setattr("tools.run_final_electron_release_gate.run_electron_portable_workspace", fake_portable)
    monkeypatch.setattr("tools.run_final_electron_release_gate.audit_final_goal_completion", fake_audit)

    payload = run_final_electron_release_gate(
        source_root=tmp_path,
        output=tmp_path / "gate.json",
        portable_output=tmp_path / "portable.json",
        defender_scan=True,
        require_defender_scan=True,
    )

    assert payload["ok"] is True
    assert payload["release_ready"] is False
    assert payload["execute"] is False
    assert payload["failed_sections"] == ["goal_audit"]
    assert payload["sections"]["release_policy"]["ok"] is True
    assert payload["blocked_on_approval"] is True
    assert [action["id"] for action in payload["next_actions"]] == [
        "electron-dependencies",
        "final-release-execute",
    ]
    assert payload["completion_blockers"]["goal_audit"]["by_type"] == {"missing-runtime-evidence": 1}
    assert payload["completion_blockers"]["goal_audit"]["by_round"] == {"Runtime Evidence": 1}
    assert payload["completion_blockers"]["portable_blocking_violations"] == 1
    assert calls["bootstrap"]["dry_run"] is True
    assert calls["portable"]["dry_run"] is True
    assert calls["portable"]["defender_scan"] is True
    assert calls["portable"]["require_defender_scan"] is True
    assert Path(payload["output"]).is_file()

    summary = summarize_final_release_gate(payload)
    assert "sections" not in summary
    assert summary["ok"] is True
    assert summary["release_ready"] is False
    assert summary["blocked_on_approval"] is True
    assert summary["dependency_readiness"]["requires_explicit_approval"] is False
    assert summary["portable_workspace"]["blocking_violation_count"] == 1
    assert summary["portable_runtime_evidence"]["required"] is False
    assert summary["portable_runtime_evidence"]["status"] == "not_required_in_plan_mode"
    assert summary["portable_runtime_evidence"]["checked_sections"] == []
    assert summary["goal_audit"]["blocker_count"] == 1
    assert summary["goal_audit"]["blockers_by_round"] == {"Runtime Evidence": 1}


def test_final_electron_release_gate_execute_does_not_report_plan_only_action(monkeypatch, tmp_path):
    def fake_bootstrap(**kwargs):
        return {"ok": True, "ready_after": True, "violations": [], "before": {"next_action": {"required": False}}}

    def fake_portable(**kwargs):
        return _ready_portable_payload(tmp_path)

    def fake_audit(**kwargs):
        return {"ok": True, "blocker_count": 0, "blockers": []}

    monkeypatch.setattr("tools.run_final_electron_release_gate.bootstrap_electron_dependencies", fake_bootstrap)
    monkeypatch.setattr("tools.run_final_electron_release_gate.run_electron_portable_workspace", fake_portable)
    monkeypatch.setattr("tools.run_final_electron_release_gate.audit_final_goal_completion", fake_audit)

    payload = run_final_electron_release_gate(
        source_root=tmp_path,
        execute=True,
        run_electron_cdp=True,
        defender_scan=True,
        require_defender_scan=True,
        output=None,
    )

    assert payload["ok"] is True
    assert payload["release_ready"] is True
    assert payload["blocked_on_approval"] is False
    assert payload["next_actions"] == []


def test_final_electron_release_gate_execute_install_success_clears_dependency_action(monkeypatch, tmp_path):
    def fake_bootstrap(**kwargs):
        return {
            "ok": True,
            "ready_before": False,
            "ready_after": True,
            "violations": [],
            "before": {
                "next_action": {
                    "required": True,
                    "requires_explicit_approval": True,
                    "script": "npm --prefix app/electron run deps:install",
                }
            },
            "after": {"ok": True, "violations": [], "next_action": {"required": False}},
        }

    def fake_portable(**kwargs):
        return _ready_portable_payload(tmp_path)

    def fake_audit(**kwargs):
        return {"ok": True, "blocker_count": 0, "blockers": []}

    monkeypatch.setattr("tools.run_final_electron_release_gate.bootstrap_electron_dependencies", fake_bootstrap)
    monkeypatch.setattr("tools.run_final_electron_release_gate.run_electron_portable_workspace", fake_portable)
    monkeypatch.setattr("tools.run_final_electron_release_gate.audit_final_goal_completion", fake_audit)

    payload = run_final_electron_release_gate(
        source_root=tmp_path,
        execute=True,
        install_deps=True,
        yes=True,
        run_electron_cdp=True,
        defender_scan=True,
        require_defender_scan=True,
        output=None,
    )

    assert payload["ok"] is True
    assert payload["release_ready"] is True
    assert payload["blocked_on_approval"] is False
    assert payload["next_actions"] == []
    summary = summarize_final_release_gate(payload)
    assert summary["dependency_readiness"]["ok"] is True
    assert summary["dependency_readiness"]["violation_count"] == 0
    assert summary["next_actions"] == []
    assert summary["portable_runtime_evidence"]["ok"] is True
    assert summary["portable_runtime_evidence"]["required"] is True
    assert summary["portable_runtime_evidence"]["status"] == "validated"
    assert summary["portable_runtime_evidence"]["checked_sections"] == [
        "electron_builder",
        "packaged_smoke",
        "clean_packaged",
        "electron_cdp_smoke",
    ]


def test_final_electron_release_gate_execute_refuses_install_without_yes(monkeypatch, tmp_path):
    portable_called = False

    def fake_bootstrap(**kwargs):
        return {
            "ok": False,
            "violations": [{"path": "app/electron", "reason": "dependency installation requires --yes with --execute"}],
        }

    def fake_portable(**kwargs):
        nonlocal portable_called
        portable_called = True
        return {"ok": True}

    def fake_audit(**kwargs):
        return {"ok": False, "blockers": [{"path": "plan", "reason": "missing"}]}

    monkeypatch.setattr("tools.run_final_electron_release_gate.bootstrap_electron_dependencies", fake_bootstrap)
    monkeypatch.setattr("tools.run_final_electron_release_gate.run_electron_portable_workspace", fake_portable)
    monkeypatch.setattr("tools.run_final_electron_release_gate.audit_final_goal_completion", fake_audit)

    payload = run_final_electron_release_gate(
        source_root=tmp_path,
        execute=True,
        install_deps=True,
        yes=False,
        run_electron_cdp=True,
        defender_scan=True,
        require_defender_scan=True,
        output=None,
    )

    assert payload["ok"] is False
    assert payload["release_ready"] is False
    assert portable_called is False
    assert any("dependency-bootstrap" in item["reason"] for item in payload["violations"])
    assert payload["sections"]["portable_workspace"]["status"] == "skipped"


def test_final_electron_release_gate_execute_requires_runtime_and_scan_flags(monkeypatch, tmp_path):
    portable_called = False

    def fake_bootstrap(**kwargs):
        return {"ok": True, "ready_after": True, "violations": []}

    def fake_portable(**kwargs):
        nonlocal portable_called
        portable_called = True
        return {"ok": True}

    def fake_audit(**kwargs):
        return {"ok": False, "blockers": [{"path": "plan", "reason": "missing"}]}

    monkeypatch.setattr("tools.run_final_electron_release_gate.bootstrap_electron_dependencies", fake_bootstrap)
    monkeypatch.setattr("tools.run_final_electron_release_gate.run_electron_portable_workspace", fake_portable)
    monkeypatch.setattr("tools.run_final_electron_release_gate.audit_final_goal_completion", fake_audit)

    payload = run_final_electron_release_gate(source_root=tmp_path, execute=True, output=None)

    assert payload["ok"] is False
    assert payload["release_ready"] is False
    assert portable_called is False
    assert payload["sections"]["release_policy"]["ok"] is False
    assert len(payload["sections"]["release_policy"]["violations"]) == 3
    assert any("release-policy" in item["reason"] for item in payload["violations"])


def test_final_electron_release_gate_execute_requires_actual_defender_scan_flag(monkeypatch, tmp_path):
    portable_called = False

    def fake_bootstrap(**kwargs):
        return {"ok": True, "ready_after": True, "violations": []}

    def fake_portable(**kwargs):
        nonlocal portable_called
        portable_called = True
        return {"ok": True}

    def fake_audit(**kwargs):
        return {"ok": True, "blockers": []}

    monkeypatch.setattr("tools.run_final_electron_release_gate.bootstrap_electron_dependencies", fake_bootstrap)
    monkeypatch.setattr("tools.run_final_electron_release_gate.run_electron_portable_workspace", fake_portable)
    monkeypatch.setattr("tools.run_final_electron_release_gate.audit_final_goal_completion", fake_audit)

    payload = run_final_electron_release_gate(
        source_root=tmp_path,
        execute=True,
        run_electron_cdp=True,
        require_defender_scan=True,
        output=None,
    )

    assert payload["ok"] is False
    assert payload["release_ready"] is False
    assert payload["defender_scan"] is False
    assert payload["require_defender_scan"] is True
    assert portable_called is False
    assert payload["sections"]["release_policy"]["ok"] is False
    assert any("--defender-scan" in item["reason"] for item in payload["sections"]["release_policy"]["violations"])
    summary = summarize_final_release_gate(payload)
    assert summary["defender_scan"] is False
    assert summary["require_defender_scan"] is True


def test_final_electron_release_gate_execute_success_requires_audit_success(monkeypatch, tmp_path):
    def fake_bootstrap(**kwargs):
        return {"ok": True, "ready_after": True, "violations": []}

    def fake_portable(**kwargs):
        return _ready_portable_payload(tmp_path)

    def fake_audit(**kwargs):
        return {"ok": True, "blockers": []}

    monkeypatch.setattr("tools.run_final_electron_release_gate.bootstrap_electron_dependencies", fake_bootstrap)
    monkeypatch.setattr("tools.run_final_electron_release_gate.run_electron_portable_workspace", fake_portable)
    monkeypatch.setattr("tools.run_final_electron_release_gate.audit_final_goal_completion", fake_audit)

    payload = run_final_electron_release_gate(
        source_root=tmp_path,
        execute=True,
        run_electron_cdp=True,
        defender_scan=True,
        require_defender_scan=True,
        output=None,
    )

    assert payload["ok"] is True
    assert payload["release_ready"] is True
    assert payload["failed_sections"] == []


def test_final_electron_release_gate_execute_requires_complete_portable_runtime_evidence(monkeypatch, tmp_path):
    def fake_bootstrap(**kwargs):
        return {"ok": True, "ready_after": True, "violations": []}

    def fake_portable(**kwargs):
        return {"ok": True, "dry_run": False, "packaged_root": str(tmp_path / "dist" / "win-unpacked")}

    def fake_audit(**kwargs):
        return {"ok": True, "blockers": []}

    monkeypatch.setattr("tools.run_final_electron_release_gate.bootstrap_electron_dependencies", fake_bootstrap)
    monkeypatch.setattr("tools.run_final_electron_release_gate.run_electron_portable_workspace", fake_portable)
    monkeypatch.setattr("tools.run_final_electron_release_gate.audit_final_goal_completion", fake_audit)

    payload = run_final_electron_release_gate(
        source_root=tmp_path,
        execute=True,
        run_electron_cdp=True,
        defender_scan=True,
        require_defender_scan=True,
        output=None,
    )

    assert payload["ok"] is False
    assert payload["release_ready"] is False
    assert "portable_runtime_evidence" in payload["failed_sections"]
    assert payload["sections"]["portable_runtime_evidence"]["ok"] is False
    assert any("portable-runtime-evidence" in item["reason"] for item in payload["violations"])


def test_final_electron_release_gate_execute_fails_when_audit_fails(monkeypatch, tmp_path):
    def fake_bootstrap(**kwargs):
        return {"ok": True, "ready_after": True, "violations": []}

    def fake_portable(**kwargs):
        return _ready_portable_payload(tmp_path)

    def fake_audit(**kwargs):
        return {"ok": False, "blockers": [{"path": "plan.md:1", "reason": "unchecked"}]}

    monkeypatch.setattr("tools.run_final_electron_release_gate.bootstrap_electron_dependencies", fake_bootstrap)
    monkeypatch.setattr("tools.run_final_electron_release_gate.run_electron_portable_workspace", fake_portable)
    monkeypatch.setattr("tools.run_final_electron_release_gate.audit_final_goal_completion", fake_audit)

    payload = run_final_electron_release_gate(
        source_root=tmp_path,
        execute=True,
        run_electron_cdp=True,
        defender_scan=True,
        require_defender_scan=True,
        output=None,
    )

    assert payload["ok"] is False
    assert payload["release_ready"] is False
    assert payload["failed_sections"] == ["goal_audit"]
    assert any("goal-audit" in item["reason"] for item in payload["violations"])


def test_final_electron_release_gate_cli_summary_omits_nested_evidence():
    result = subprocess.run(
        [
            sys.executable,
            "tools/run_final_electron_release_gate.py",
            "--summary",
            "--output",
            "",
            "--portable-output",
            "",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert "sections" not in payload
    assert payload["ok"] is True
    assert payload["release_ready"] is False
    assert payload["blocked_on_approval"] is True
    assert payload["goal_audit"]["blocker_count"] >= 0
    assert any(action.get("id") == "final-release-execute" for action in payload["next_actions"])
