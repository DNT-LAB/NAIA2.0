import json
import subprocess
import sys
from pathlib import Path

from tools.audit_final_goal_completion import audit_final_goal_completion


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _default_package_scripts() -> dict[str, str]:
    return {
        "release:check": "ok",
        "check:approval-gate": "ok",
        "test:main-contract": "ok",
        "deps:plan": "ok",
        "deps:plan:summary": "ok",
        "deps:install": "ok",
        "deps:ci": "ok",
        "release:evidence": "ok",
        "release:evidence:summary": "write_release_evidence --no-output --skip-electron-runtime --summary",
        "release:evidence:fresh": "ok",
        "release:evidence:fresh:summary": "ok",
        "release:workspace": "ok",
        "release:workspace:summary": "ok",
        "release:workspace:evidence": "ok",
        "release:workspace:evidence:summary": "ok",
        "release:workspace:bundled-python": "ok",
        "release:workspace:bundled-python:evidence": "ok",
        "release:workspace:clean-python": "ok",
        "release:workspace:clean-python:evidence": "ok",
        "release:portable:workspace:plan": "ok",
        "release:portable:workspace:plan:summary": "ok",
        "release:portable:workspace": "ok",
        "release:portable:workspace:bundled-python": "ok",
        "release:portable:workspace:clean-python": "ok",
        "release:final:plan": "ok",
        "release:final:plan:summary": "run_final --summary --output \"\" --portable-output \"\"",
        "release:final": "run_final --execute --run-electron-cdp --electron-timeout 180 --defender-scan --require-defender-scan",
        "release:final:smoke": "run_final --execute --run-electron-cdp --electron-timeout 180 --defender-scan --require-defender-scan",
        "release:final:install": "run_final --execute --install-deps --yes --run-electron-cdp --electron-timeout 180 --defender-scan --require-defender-scan",
        "release:final:install:scan": "run_final --execute --install-deps --yes --run-electron-cdp --electron-timeout 180 --defender-scan --require-defender-scan",
        "release:final:bundled-python": "run_final --execute --python-runtime-dir %NAIA_PYTHON_RUNTIME_DIR% --require-bundled-python --run-electron-cdp --electron-timeout 180 --defender-scan --require-defender-scan",
        "release:final:bundled-python:scan": "run_final --execute --python-runtime-dir %NAIA_PYTHON_RUNTIME_DIR% --require-bundled-python --run-electron-cdp --electron-timeout 180 --defender-scan --require-defender-scan",
        "release:final:clean-python": "run_final --execute --build-clean-python-runtime --python-runtime-version 3.12 --require-bundled-python --run-electron-cdp --electron-timeout 180 --defender-scan --require-defender-scan",
        "release:final:clean-python:scan": "run_final --execute --build-clean-python-runtime --python-runtime-version 3.12 --require-bundled-python --run-electron-cdp --electron-timeout 180 --defender-scan --require-defender-scan",
        "preflight:electron-deps": "ok",
        "preflight:electron-deps:summary": "ok",
        "goal:audit:summary": "ok",
        "check:source-layout": "ok",
        "preflight:packaging-inputs": "ok",
        "preflight:packaging-inputs:bundled-python": "ok",
        "smoke:packaged": "ok",
        "smoke:packaged:structure": "ok",
        "smoke:electron:source": "ok",
        "smoke:electron:packaged": "ok",
        "check:packaged-feature-smoke": "ok",
        "clean:staged": "ok",
        "clean:staged:bundled-python": "ok",
        "clean:packaged": "ok",
        "clean:packaged:bundled-python": "ok",
        "release:portable": "ok",
        "release:portable:bundled-python": "ok",
        "release:portable:clean-python": "ok",
        "release:portable:smoke": "ok",
        "release:portable:smoke:scan": "portable --run-electron-cdp --electron-timeout 180 --defender-scan --require-defender-scan",
        "release:portable:bundled-python:smoke": "ok",
        "release:portable:bundled-python:smoke:scan": "portable --python-runtime-dir %NAIA_PYTHON_RUNTIME_DIR% --require-bundled-python --run-electron-cdp --electron-timeout 180 --defender-scan --require-defender-scan",
        "release:portable:clean-python:smoke": "ok",
        "release:portable:clean-python:smoke:scan": "portable --build-clean-python-runtime --python-runtime-version 3.12 --require-bundled-python --run-electron-cdp --electron-timeout 180 --defender-scan --require-defender-scan",
        "pack:dir": "ok",
        "dist:win-dir": "ok",
    }


def _package_json(root: Path, *, scripts: dict[str, str] | None = None) -> Path:
    package = root / "app" / "electron" / "package.json"
    payload = {
        "devDependencies": {
            "electron": "42.1.0",
            "electron-builder": "26.8.1",
        },
        "scripts": scripts or _default_package_scripts(),
        "build": {"win": {"target": "dir", "signAndEditExecutable": False, "forceCodeSigning": False}},
    }
    _write(package, json.dumps(payload),)
    return package


def _write_ready_electron_dependencies(package: Path) -> None:
    _write(
        package.parent / "package-lock.json",
        json.dumps(
            {
                "packages": {
                    "node_modules/electron": {"version": "42.1.0"},
                    "node_modules/electron-builder": {"version": "26.8.1"},
                }
            }
        ),
    )
    _write(package.parent / "node_modules" / "electron" / "package.json", json.dumps({"version": "42.1.0"}))
    _write(
        package.parent / "node_modules" / "electron-builder" / "package.json",
        json.dumps({"version": "26.8.1"}),
    )
    _write(package.parent / "node_modules" / ".bin" / "electron.cmd", "@echo off\n")
    _write(package.parent / "node_modules" / ".bin" / "electron-builder.cmd", "@echo off\n")


def _ready_packaged_root(root: Path) -> Path:
    packaged = root / "workspace" / "electron-dist" / "win-unpacked"
    _write(packaged / "NAIA.exe", "exe")
    (packaged / "resources" / "naia-backend").mkdir(parents=True)
    (packaged / "user-data").mkdir()
    return packaged


def _write_completion_map(path: Path) -> None:
    _write(
        path,
        json.dumps(
            {
                "rules": [
                    {
                        "item": "Build the Electron app with the chosen backend runtime.",
                        "requires": [
                            {"path": "dry_run", "equals": False},
                            {"path": "sections.electron_builder.ok", "equals": True},
                            {"path": "sections.packaged_smoke.ok", "equals": True},
                        ],
                    }
                ]
            }
        ),
    )


def test_final_goal_audit_reports_unchecked_items_and_missing_runtime(tmp_path):
    plan = tmp_path / "plan.md"
    _write(
        plan,
        "\n".join(
            [
                "## Round 9 - Packaged App Integration",
                "",
                "### Checklist",
                "",
                "- [x] Add package scripts.",
                "- [ ] Build the Electron app.",
            ]
        ),
    )
    package = _package_json(tmp_path)

    payload = audit_final_goal_completion(
        plan,
        electron_package_path=package,
        packaged_root=tmp_path / "dist" / "win-unpacked",
        portable_workspace_evidence_path=tmp_path / "missing-workspace-evidence.json",
    )

    assert payload["ok"] is False
    assert payload["unchecked_count"] == 1
    assert payload["unsatisfied_unchecked_count"] == 1
    assert payload["blockers_by_type"]["unchecked-plan-item"] == 1
    assert payload["blockers_by_round"]["Round 9 - Packaged App Integration"] == 1
    assert payload["blockers_by_round"]["Runtime Evidence"] >= 1
    assert payload["completion_status"]["release_ready"] is False
    assert payload["completion_status"]["blocked_on_approval"] is True
    assert payload["completion_status"]["blockers_by_round"]["Runtime Evidence"] >= 1
    assert [action["id"] for action in payload["completion_status"]["next_actions"]] == [
        "electron-dependencies",
        "packaged-electron-build",
    ]
    assert any(blocker["type"] == "unchecked-plan-item" for blocker in payload["blockers"])
    assert any("Electron dependency readiness failed" in blocker["reason"] for blocker in payload["blockers"])
    assert any("packaged Electron app artifact" in blocker["reason"] for blocker in payload["blockers"])


def test_final_goal_audit_accepts_complete_fixture(tmp_path, monkeypatch):
    plan = tmp_path / "plan.md"
    _write(
        plan,
        "\n".join(
            [
                "## Round 9 - Packaged App Integration",
                "",
                "### Checklist",
                "",
                "- [x] Build the Electron app.",
            ]
        ),
    )
    package = _package_json(tmp_path)
    _write_ready_electron_dependencies(package)
    packaged = tmp_path / "dist" / "win-unpacked"
    _write(packaged / "NAIA.exe", "exe")
    (packaged / "resources" / "naia-backend").mkdir(parents=True)
    (packaged / "user-data").mkdir()
    monkeypatch.setenv("PATH", "")

    payload = audit_final_goal_completion(
        plan,
        electron_package_path=package,
        packaged_root=packaged,
    )

    assert payload["ok"] is True
    assert payload["blockers"] == []
    assert payload["warnings"] == []
    assert payload["completion_status"]["release_ready"] is True
    assert payload["completion_status"]["blocked_on_approval"] is False
    assert payload["completion_status"]["next_actions"] == []


def test_final_goal_audit_can_use_completed_workspace_packaged_evidence(tmp_path, monkeypatch):
    plan = tmp_path / "plan.md"
    _write(
        plan,
        "\n".join(
            [
                "## Round 9 - Packaged App Integration",
                "",
                "### Checklist",
                "",
                "- [x] Build the Electron app.",
            ]
        ),
    )
    package = _package_json(tmp_path)
    _write_ready_electron_dependencies(package)
    workspace_packaged = tmp_path / "workspace" / "electron-dist" / "win-unpacked"
    _write(workspace_packaged / "NAIA.exe", "exe")
    (workspace_packaged / "resources" / "naia-backend").mkdir(parents=True)
    (workspace_packaged / "user-data").mkdir()
    evidence = tmp_path / "workspace_evidence.json"
    _write(
        evidence,
        json.dumps({
            "ok": True,
            "dry_run": False,
            "packaged_root": str(workspace_packaged),
        }),
    )
    monkeypatch.setenv("PATH", "")

    payload = audit_final_goal_completion(
        plan,
        electron_package_path=package,
        packaged_root=tmp_path / "dist" / "missing-win-unpacked",
        portable_workspace_evidence_path=evidence,
    )

    assert payload["ok"] is True
    assert payload["evidence"]["configured_packaged_app_ready"] is False
    assert payload["evidence"]["portable_workspace_evidence_status"] == "ready"
    assert payload["evidence"]["packaged_root"] == str(workspace_packaged)


def test_final_goal_audit_rejects_dry_run_workspace_evidence_as_packaged_artifact(tmp_path, monkeypatch):
    plan = tmp_path / "plan.md"
    _write(
        plan,
        "\n".join(
            [
                "## Round 9 - Packaged App Integration",
                "",
                "### Checklist",
                "",
                "- [x] Build the Electron app.",
            ]
        ),
    )
    package = _package_json(tmp_path)
    _write_ready_electron_dependencies(package)
    packaged = tmp_path / "workspace" / "electron-dist" / "win-unpacked"
    _write(packaged / "NAIA.exe", "exe")
    (packaged / "resources" / "naia-backend").mkdir(parents=True)
    (packaged / "user-data").mkdir()
    evidence = tmp_path / "workspace_evidence.json"
    _write(
        evidence,
        json.dumps({
            "ok": True,
            "dry_run": True,
            "packaged_root": str(packaged),
        }),
    )
    monkeypatch.setenv("PATH", "")

    payload = audit_final_goal_completion(
        plan,
        electron_package_path=package,
        packaged_root=tmp_path / "dist" / "missing-win-unpacked",
        portable_workspace_evidence_path=evidence,
    )

    assert payload["ok"] is False
    assert payload["evidence"]["portable_workspace_evidence_status"] == "dry_run"
    assert any("packaged Electron app artifact" in blocker["reason"] for blocker in payload["blockers"])


def test_final_goal_audit_satisfies_unchecked_item_from_completion_evidence(tmp_path, monkeypatch):
    plan = tmp_path / "plan.md"
    _write(
        plan,
        "\n".join(
            [
                "## Round 9 - Packaged App Integration",
                "",
                "### Checklist",
                "",
                "- [ ] Build the Electron app with the chosen backend runtime.",
            ]
        ),
    )
    package = _package_json(tmp_path)
    _write_ready_electron_dependencies(package)
    packaged = _ready_packaged_root(tmp_path)
    evidence = tmp_path / "workspace_evidence.json"
    _write(
        evidence,
        json.dumps(
            {
                "ok": True,
                "dry_run": False,
                "packaged_root": str(packaged),
                "sections": {
                    "electron_builder": {"ok": True},
                    "packaged_smoke": {"ok": True},
                },
            }
        ),
    )
    completion_map = tmp_path / "completion_map.json"
    _write_completion_map(completion_map)
    monkeypatch.setenv("PATH", "")

    payload = audit_final_goal_completion(
        plan,
        electron_package_path=package,
        packaged_root=tmp_path / "dist" / "missing-win-unpacked",
        portable_workspace_evidence_path=evidence,
        completion_evidence_map_path=completion_map,
    )

    assert payload["ok"] is True
    assert payload["unchecked_count"] == 1
    assert payload["blockers"] == []
    satisfied = payload["evidence"]["evidence_satisfied_unchecked_items"]
    assert satisfied[0]["item"] == "Build the Electron app with the chosen backend runtime."


def test_final_goal_audit_does_not_satisfy_unchecked_item_from_partial_evidence(tmp_path, monkeypatch):
    plan = tmp_path / "plan.md"
    _write(
        plan,
        "\n".join(
            [
                "## Round 9 - Packaged App Integration",
                "",
                "### Checklist",
                "",
                "- [ ] Build the Electron app with the chosen backend runtime.",
            ]
        ),
    )
    package = _package_json(tmp_path)
    _write_ready_electron_dependencies(package)
    packaged = _ready_packaged_root(tmp_path)
    evidence = tmp_path / "workspace_evidence.json"
    _write(
        evidence,
        json.dumps(
            {
                "ok": True,
                "dry_run": True,
                "packaged_root": str(packaged),
                "sections": {
                    "electron_builder": {"ok": True},
                    "packaged_smoke": {"ok": True},
                },
            }
        ),
    )
    completion_map = tmp_path / "completion_map.json"
    _write_completion_map(completion_map)
    monkeypatch.setenv("PATH", "")

    payload = audit_final_goal_completion(
        plan,
        electron_package_path=package,
        packaged_root=packaged,
        portable_workspace_evidence_path=evidence,
        completion_evidence_map_path=completion_map,
    )

    assert payload["ok"] is False
    assert any(blocker["type"] == "unchecked-plan-item" for blocker in payload["blockers"])
    evaluated = payload["evidence"]["evidence_evaluated_unchecked_items"]
    assert evaluated[0]["satisfied"] is False


def test_final_goal_audit_accepts_proven_when_done_rule(tmp_path, monkeypatch):
    plan = tmp_path / "plan.md"
    item = "Startup and supported Remote Web workflows are validated from the release artifact."
    _write(
        plan,
        "\n".join(
            [
                "## Round 10 - Clean-Machine Release Gate and Optional Installer",
                "",
                "### Checklist",
                "",
                "- [x] Validate packaged app.",
                "",
                "### When Done",
                "",
                f"- {item}",
            ]
        ),
    )
    package = _package_json(tmp_path)
    _write_ready_electron_dependencies(package)
    packaged = _ready_packaged_root(tmp_path)
    evidence = tmp_path / "workspace_evidence.json"
    _write(
        evidence,
        json.dumps(
            {
                "ok": True,
                "dry_run": False,
                "run_electron_cdp": True,
                "packaged_root": str(packaged),
                "sections": {
                    "electron_cdp_smoke": {
                        "ok": True,
                        "timings": {"shell_ready_s": 1.25},
                    },
                },
            }
        ),
    )
    completion_map = tmp_path / "completion_map.json"
    _write(
        completion_map,
        json.dumps(
            {
                "rules": [],
                "when_done_rules": [
                    {
                        "round": "Round 10 - Clean-Machine Release Gate and Optional Installer",
                        "item": item,
                        "requires": [
                            {"path": "dry_run", "equals": False},
                            {"path": "run_electron_cdp", "equals": True},
                            {"path": "sections.electron_cdp_smoke.ok", "equals": True},
                            {"path": "sections.electron_cdp_smoke.timings.shell_ready_s", "number_gt": 0},
                        ],
                    }
                ],
            }
        ),
    )
    monkeypatch.setenv("PATH", "")

    payload = audit_final_goal_completion(
        plan,
        electron_package_path=package,
        packaged_root=packaged,
        portable_workspace_evidence_path=evidence,
        completion_evidence_map_path=completion_map,
    )

    assert payload["ok"] is True
    assert payload["blockers"] == []
    assert payload["when_done_count"] == 1
    satisfied = payload["evidence"]["evidence_satisfied_when_done_items"]
    assert satisfied[0]["item"] == item


def test_final_goal_audit_rejects_unproven_when_done_rule(tmp_path, monkeypatch):
    plan = tmp_path / "plan.md"
    item = "Startup and supported Remote Web workflows are validated from the release artifact."
    _write(
        plan,
        "\n".join(
            [
                "## Round 10 - Clean-Machine Release Gate and Optional Installer",
                "",
                "### Checklist",
                "",
                "- [x] Validate packaged app.",
                "",
                "### When Done",
                "",
                f"- {item}",
            ]
        ),
    )
    package = _package_json(tmp_path)
    _write_ready_electron_dependencies(package)
    packaged = _ready_packaged_root(tmp_path)
    evidence = tmp_path / "workspace_evidence.json"
    _write(
        evidence,
        json.dumps(
            {
                "ok": True,
                "dry_run": True,
                "run_electron_cdp": False,
                "packaged_root": str(packaged),
                "sections": {"electron_cdp_smoke": {"ok": False}},
            }
        ),
    )
    completion_map = tmp_path / "completion_map.json"
    _write(
        completion_map,
        json.dumps(
            {
                "rules": [],
                "when_done_rules": [
                    {
                        "round": "Round 10 - Clean-Machine Release Gate and Optional Installer",
                        "item": item,
                        "requires": [
                            {"path": "dry_run", "equals": False},
                            {"path": "run_electron_cdp", "equals": True},
                            {"path": "sections.electron_cdp_smoke.ok", "equals": True},
                        ],
                    }
                ],
            }
        ),
    )
    monkeypatch.setenv("PATH", "")

    payload = audit_final_goal_completion(
        plan,
        electron_package_path=package,
        packaged_root=packaged,
        portable_workspace_evidence_path=evidence,
        completion_evidence_map_path=completion_map,
    )

    assert payload["ok"] is False
    assert any(blocker["type"] == "unmet-when-done-condition" for blocker in payload["blockers"])
    evaluated = payload["evidence"]["evidence_evaluated_when_done_items"]
    assert evaluated[0]["satisfied"] is False


def test_final_goal_audit_rejects_unmapped_when_done_rule(tmp_path, monkeypatch):
    plan = tmp_path / "plan.md"
    item = "A release-specific completion claim must be mapped."
    _write(
        plan,
        "\n".join(
            [
                "## Round X - Evidence Discipline",
                "",
                "### Checklist",
                "",
                "- [x] Add an unmapped claim.",
                "",
                "### When Done",
                "",
                f"- {item}",
            ]
        ),
    )
    package = _package_json(tmp_path)
    _write_ready_electron_dependencies(package)
    packaged = _ready_packaged_root(tmp_path)
    completion_map = tmp_path / "completion_map.json"
    _write(completion_map, json.dumps({"rules": [], "when_done_rules": []}))
    monkeypatch.setenv("PATH", "")

    payload = audit_final_goal_completion(
        plan,
        electron_package_path=package,
        packaged_root=packaged,
        completion_evidence_map_path=completion_map,
    )

    assert payload["ok"] is False
    assert any(blocker["type"] == "unmapped-when-done-condition" for blocker in payload["blockers"])


def test_final_goal_audit_allows_intentionally_unmapped_when_done_rule(tmp_path, monkeypatch):
    plan = tmp_path / "plan.md"
    item = "No code files or large data files have been moved."
    round_name = "Round 0 - Baseline Freeze and Ownership Map"
    _write(
        plan,
        "\n".join(
            [
                f"## {round_name}",
                "",
                "### Checklist",
                "",
                "- [x] Capture baseline.",
                "",
                "### When Done",
                "",
                f"- {item}",
            ]
        ),
    )
    package = _package_json(tmp_path)
    _write_ready_electron_dependencies(package)
    packaged = _ready_packaged_root(tmp_path)
    completion_map = tmp_path / "completion_map.json"
    _write(
        completion_map,
        json.dumps(
            {
                "rules": [],
                "when_done_rules": [],
                "intentionally_unmapped": [
                    {
                        "section": "when_done_rules",
                        "round": round_name,
                        "item": item,
                        "reason": "phase-local invariant",
                    }
                ],
            }
        ),
    )
    monkeypatch.setenv("PATH", "")

    payload = audit_final_goal_completion(
        plan,
        electron_package_path=package,
        packaged_root=packaged,
        completion_evidence_map_path=completion_map,
    )

    assert payload["ok"] is True
    assert payload["blockers"] == []
    assert payload["unmet_when_done_count"] == 0
    assert payload["unmapped_when_done_count"] == 0
    assert payload["intentionally_unmapped_when_done_count"] == 1


def test_final_goal_audit_accepts_static_shell_contract_when_done_rule(tmp_path, monkeypatch):
    plan = tmp_path / "plan.md"
    item = "Logs are accessible from the Electron shell."
    _write(
        plan,
        "\n".join(
            [
                "## Round 9 - Packaged App Integration",
                "",
                "### Checklist",
                "",
                "- [x] Add shell controls.",
                "",
                "### When Done",
                "",
                f"- {item}",
            ]
        ),
    )
    package = _package_json(tmp_path)
    _write_ready_electron_dependencies(package)
    packaged = _ready_packaged_root(tmp_path)
    evidence = tmp_path / "workspace_evidence.json"
    _write(
        evidence,
        json.dumps(
            {
                "ok": True,
                "dry_run": True,
                "packaged_root": str(packaged),
                "sections": {
                    "electron_shell_contract": {
                        "ok": True,
                        "checks": {
                            "maintenance_logs": {
                                "logs_accessible": True,
                            }
                        },
                    },
                },
            }
        ),
    )
    completion_map = tmp_path / "completion_map.json"
    _write(
        completion_map,
        json.dumps(
            {
                "rules": [],
                "when_done_rules": [
                    {
                        "round": "Round 9 - Packaged App Integration",
                        "item": item,
                        "requires": [
                            {"path": "sections.electron_shell_contract.ok", "equals": True},
                            {
                                "path": "sections.electron_shell_contract.checks.maintenance_logs.logs_accessible",
                                "equals": True,
                            },
                        ],
                    }
                ],
            }
        ),
    )
    monkeypatch.setenv("PATH", "")

    payload = audit_final_goal_completion(
        plan,
        electron_package_path=package,
        packaged_root=packaged,
        portable_workspace_evidence_path=evidence,
        completion_evidence_map_path=completion_map,
    )

    assert payload["ok"] is True
    assert payload["blockers"] == []
    assert payload["evidence"]["evidence_satisfied_when_done_items"][0]["item"] == item


def test_final_goal_audit_can_use_extra_completion_evidence(tmp_path, monkeypatch):
    plan = tmp_path / "plan.md"
    item = "Release notes list external dependencies such as NovelAI, WebUI, ComfyUI endpoints, and optional downloadable data."
    _write(
        plan,
        "\n".join(
            [
                "## Round 10 - Clean-Machine Release Gate and Optional Installer",
                "",
                "### Checklist",
                "",
                "- [x] Validate release notes.",
                "",
                "### When Done",
                "",
                f"- {item}",
            ]
        ),
    )
    package = _package_json(tmp_path)
    _write_ready_electron_dependencies(package)
    packaged = _ready_packaged_root(tmp_path)
    completion_map = tmp_path / "completion_map.json"
    _write(
        completion_map,
        json.dumps(
            {
                "rules": [],
                "when_done_rules": [
                    {
                        "round": "Round 10 - Clean-Machine Release Gate and Optional Installer",
                        "item": item,
                        "requires": [
                            {"path": "sections.staged_workspace.sections.preflight.ok", "equals": True},
                            {
                                "path": "sections.staged_workspace.sections.preflight.checks.release_notes.external_dependencies_listed",
                                "equals": True,
                            },
                        ],
                    }
                ],
            }
        ),
    )
    monkeypatch.setenv("PATH", "")

    payload = audit_final_goal_completion(
        plan,
        electron_package_path=package,
        packaged_root=packaged,
        portable_workspace_evidence_path=tmp_path / "missing-evidence.json",
        completion_evidence_map_path=completion_map,
        extra_completion_evidence={
            "sections": {
                "staged_workspace": {
                    "sections": {
                        "preflight": {
                            "ok": True,
                            "checks": {"release_notes": {"external_dependencies_listed": True}},
                        }
                    }
                }
            }
        },
    )

    assert payload["ok"] is True
    assert payload["blockers"] == []
    assert payload["evidence"]["evidence_satisfied_when_done_items"][0]["item"] == item


def test_final_goal_audit_rejects_missing_electron_builder_even_when_electron_is_present(tmp_path, monkeypatch):
    plan = tmp_path / "plan.md"
    _write(
        plan,
        "\n".join(
            [
                "## Round 9 - Packaged App Integration",
                "",
                "### Checklist",
                "",
                "- [x] Build the Electron app.",
            ]
        ),
    )
    package = _package_json(tmp_path)
    _write(
        package.parent / "package-lock.json",
        json.dumps({"packages": {"node_modules/electron": {"version": "42.1.0"}}}),
    )
    _write(package.parent / "node_modules" / "electron" / "package.json", json.dumps({"version": "42.1.0"}))
    _write(package.parent / "node_modules" / ".bin" / "electron.cmd", "@echo off\n")
    packaged = _ready_packaged_root(tmp_path)
    monkeypatch.setenv("PATH", "")

    payload = audit_final_goal_completion(
        plan,
        electron_package_path=package,
        packaged_root=packaged,
    )

    assert payload["ok"] is False
    assert payload["evidence"]["electron_dependency_ready"] is False
    assert any("electron-builder" in blocker["reason"] for blocker in payload["blockers"])


def test_final_goal_audit_rejects_release_distribution_strategy_drift(tmp_path, monkeypatch):
    plan = tmp_path / "plan.md"
    _write(
        plan,
        "\n".join(
            [
                "## Round 10 - Clean-Machine Release Gate",
                "",
                "### Checklist",
                "",
                "- [x] Run the strict final release gate.",
            ]
        ),
    )
    scripts = _default_package_scripts()
    scripts["release:final"] = "run_final --execute"
    package = _package_json(tmp_path, scripts=scripts)
    _write_ready_electron_dependencies(package)
    packaged = _ready_packaged_root(tmp_path)
    monkeypatch.setenv("PATH", "")

    payload = audit_final_goal_completion(
        plan,
        electron_package_path=package,
        packaged_root=packaged,
    )

    assert payload["ok"] is False
    assert payload["evidence"]["release_distribution_strategy_ok"] is False
    assert any(blocker["type"] == "release-policy" for blocker in payload["blockers"])
    assert any("release:final must include --run-electron-cdp" in blocker["reason"] for blocker in payload["blockers"])


def test_final_goal_audit_rejects_zero_latency_numeric_completion_evidence(tmp_path, monkeypatch):
    plan = tmp_path / "plan.md"
    item = "Measure cold start, first paint, random prompt latency after warmup, and Generate dispatch latency."
    _write(
        plan,
        "\n".join(
            [
                "## Round 10 - Clean-Machine Release Gate",
                "",
                "### Checklist",
                "",
                f"- [ ] {item}",
            ]
        ),
    )
    package = _package_json(tmp_path)
    _write_ready_electron_dependencies(package)
    packaged = _ready_packaged_root(tmp_path)
    evidence = tmp_path / "workspace_evidence.json"
    _write(
        evidence,
        json.dumps(
            {
                "ok": True,
                "dry_run": False,
                "run_electron_cdp": True,
                "packaged_root": str(packaged),
                "sections": {
                    "electron_cdp_smoke": {
                        "ok": True,
                        "timings": {
                            "cdp_target_s": 0,
                            "shell_ready_s": 0,
                        },
                        "checks": {
                            "performance": {
                                "firstPaintReady": True,
                                "firstPaintProxyMs": 0,
                            },
                            "randomPromptRoundTrip": {
                                "promptUpdated": True,
                                "latencyMs": 0,
                            },
                            "actionDispatch": {
                                "generate": {
                                    "dispatched": True,
                                    "latencyMs": 0,
                                }
                            },
                        },
                    }
                },
            }
        ),
    )
    completion_map = tmp_path / "completion_map.json"
    _write(
        completion_map,
        json.dumps(
            {
                "rules": [
                    {
                        "item": item,
                        "requires": [
                            {"path": "dry_run", "equals": False},
                            {"path": "run_electron_cdp", "equals": True},
                            {"path": "sections.electron_cdp_smoke.ok", "equals": True},
                            {"path": "sections.electron_cdp_smoke.timings.cdp_target_s", "number_gt": 0},
                            {"path": "sections.electron_cdp_smoke.timings.shell_ready_s", "number_gt": 0},
                            {"path": "sections.electron_cdp_smoke.checks.performance.firstPaintReady", "equals": True},
                            {"path": "sections.electron_cdp_smoke.checks.performance.firstPaintProxyMs", "number_gt": 0},
                            {"path": "sections.electron_cdp_smoke.checks.randomPromptRoundTrip.promptUpdated", "equals": True},
                            {"path": "sections.electron_cdp_smoke.checks.randomPromptRoundTrip.latencyMs", "number_gt": 0},
                            {"path": "sections.electron_cdp_smoke.checks.actionDispatch.generate.dispatched", "equals": True},
                            {"path": "sections.electron_cdp_smoke.checks.actionDispatch.generate.latencyMs", "number_gte": 0},
                        ],
                    }
                ]
            }
        ),
    )
    monkeypatch.setenv("PATH", "")

    payload = audit_final_goal_completion(
        plan,
        electron_package_path=package,
        packaged_root=packaged,
        portable_workspace_evidence_path=evidence,
        completion_evidence_map_path=completion_map,
    )

    assert payload["ok"] is False
    evaluated = payload["evidence"]["evidence_evaluated_unchecked_items"]
    assert evaluated[0]["satisfied"] is False
    failed_paths = {item["path"] for item in evaluated[0]["requirements"] if not item["met"]}
    assert "sections.electron_cdp_smoke.timings.cdp_target_s" in failed_paths
    assert "sections.electron_cdp_smoke.checks.performance.firstPaintProxyMs" in failed_paths


def test_final_goal_audit_cli_returns_nonzero_for_current_incomplete_fixture(tmp_path):
    plan = tmp_path / "plan.md"
    _write(
        plan,
        "\n".join(
            [
                "## Round 10 - Clean-Machine Release Gate",
                "",
                "### Checklist",
                "",
                "- [ ] Test portable package.",
            ]
        ),
    )
    package = _package_json(tmp_path, scripts={"release:check": "ok"})

    result = subprocess.run(
        [
            sys.executable,
            "tools/audit_final_goal_completion.py",
            "--plan",
            str(plan),
            "--electron-package",
            str(package),
            "--packaged-root",
            str(tmp_path / "missing"),
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
    assert payload["blocker_count"] > 0


def test_final_goal_audit_cli_summary_omits_full_evidence(tmp_path):
    plan = tmp_path / "plan.md"
    _write(
        plan,
        "\n".join(
            [
                "## Round 10 - Clean-Machine Release Gate",
                "",
                "### Checklist",
                "",
                "- [ ] Test portable package.",
            ]
        ),
    )
    package = _package_json(tmp_path, scripts={"release:check": "ok"})

    result = subprocess.run(
        [
            sys.executable,
            "tools/audit_final_goal_completion.py",
            "--plan",
            str(plan),
            "--electron-package",
            str(package),
            "--packaged-root",
            str(tmp_path / "missing"),
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
    assert "evidence" not in payload
    assert payload["blockers_by_round"]["Round 10 - Clean-Machine Release Gate"] == 1
    assert payload["blockers_by_round"]["Runtime Evidence"] >= 1
    assert payload["completion_status"]["blocked_on_approval"] is True
    assert payload["completion_status"]["next_actions"]
