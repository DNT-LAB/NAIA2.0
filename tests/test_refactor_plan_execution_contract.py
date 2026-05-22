import json
from pathlib import Path
import subprocess
import sys

from tools.check_refactor_plan_execution_contract import check_refactor_plan_execution_contract


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _valid_plan_text() -> str:
    return "\n".join([
        "# Refactor Plan Execution Protocol",
        "",
        "## Goal",
        "Executable plan.",
        "",
        "## Protocol",
        "plan review, gate setup, implementation, modification, deletion, verification, static review, post-work evaluation, commit",
        "",
        "## Gate Setup",
        "- Add gate.",
        "",
        "## Implementation",
        "- 구현.",
        "",
        "## Modification",
        "- 수정.",
        "",
        "## Deletion",
        "- 삭제.",
        "",
        "## Verification",
        "- 검증.",
        "",
        "## Post-Work Evaluation",
        "- 작업 후 평가.",
        "",
        "## When Done",
        "- Done.",
        "",
    ])


def _valid_manifest(tmp_path: Path) -> Path:
    _write(tmp_path / "tools" / "check_refactor_plan_execution_contract.py")
    _write(tmp_path / "tests" / "test_refactor_plan_execution_contract.py")
    _write(tmp_path / "refactor_plans" / "protocol.md", _valid_plan_text())
    manifest = {
        "version": 1,
        "contract_document": "refactor_plans/protocol.md",
        "tracked_plan_documents": [
            {
                "path": "refactor_plans/protocol.md",
                "kind": "execution_protocol",
                "required_sections": [
                    "Goal",
                    "Protocol",
                    "Gate Setup",
                    "Implementation",
                    "Modification",
                    "Deletion",
                    "Verification",
                    "Post-Work Evaluation",
                    "When Done",
                ],
            }
        ],
        "required_phase_terms": {
            "plan_review": ["plan review"],
            "gate_setup": ["gate setup"],
            "implementation": ["implementation"],
            "modification": ["modification"],
            "deletion": ["deletion"],
            "verification": ["verification"],
            "static_review": ["static review"],
            "post_work_evaluation": ["post-work evaluation"],
            "commit": ["commit"],
        },
        "required_tooling": [
            "tools/check_refactor_plan_execution_contract.py",
            "tests/test_refactor_plan_execution_contract.py",
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    _write(manifest_path, json.dumps(manifest, indent=2))
    return manifest_path


def test_refactor_plan_execution_contract_passes_current_repository():
    payload = check_refactor_plan_execution_contract(repo_root=Path("."))

    assert payload["ok"] is True
    assert payload["manifest"] == "release_assets/manifests/refactor_plan_execution_contract.json"
    assert payload["contract_document"] == "refactor_plans/20260521_refactor_plan_execution_protocol.md"
    assert payload["tracked_plan_count"] >= 4
    assert payload["violations"] == []


def test_refactor_plan_execution_contract_tracks_prune_plan():
    manifest = json.loads(Path("release_assets/manifests/refactor_plan_execution_contract.json").read_text(encoding="utf-8"))
    paths = {item["path"] for item in manifest["tracked_plan_documents"]}

    assert "refactor_plans/20260521_headless_electron_prune_plan.md" in paths


def test_refactor_plan_execution_contract_rejects_missing_phase_terms(tmp_path):
    manifest_path = _valid_manifest(tmp_path)
    plan_path = tmp_path / "refactor_plans" / "protocol.md"
    text = plan_path.read_text(encoding="utf-8")
    text = text.replace("deletion", "").replace("## Deletion\n- 삭제.\n\n", "")
    plan_path.write_text(text, encoding="utf-8")

    payload = check_refactor_plan_execution_contract(repo_root=tmp_path, manifest_path=manifest_path)

    assert payload["ok"] is False
    assert any(violation["type"] == "plan_missing_phase_terms" for violation in payload["violations"])


def test_refactor_plan_execution_contract_rejects_missing_required_section(tmp_path):
    manifest_path = _valid_manifest(tmp_path)
    plan_path = tmp_path / "refactor_plans" / "protocol.md"
    plan_path.write_text(plan_path.read_text(encoding="utf-8").replace("## Gate Setup\n", ""), encoding="utf-8")

    payload = check_refactor_plan_execution_contract(repo_root=tmp_path, manifest_path=manifest_path)

    assert payload["ok"] is False
    assert {
        "type": "plan_missing_required_section",
        "path": "refactor_plans/protocol.md",
        "reason": "missing required section: Gate Setup",
    } in payload["violations"]


def test_refactor_plan_execution_contract_rejects_invalid_phase_term_shape(tmp_path):
    manifest_path = _valid_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["required_phase_terms"]["deletion"] = []
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    payload = check_refactor_plan_execution_contract(repo_root=tmp_path, manifest_path=manifest_path)

    assert payload["ok"] is False
    assert {
        "type": "invalid_required_phase_terms",
        "path": "deletion",
        "reason": "each required phase must map to a non-empty term list",
    } in payload["violations"]


def test_refactor_plan_execution_contract_cli_returns_json():
    result = subprocess.run(
        [sys.executable, "tools/check_refactor_plan_execution_contract.py"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
