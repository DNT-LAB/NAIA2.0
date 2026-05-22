import json
from pathlib import Path
import subprocess
import sys

from tools.check_backend_runtime_strategy import check_backend_runtime_strategy


STRATEGY_PATH = Path("release_assets/manifests/backend_runtime_strategy.json")


def test_backend_runtime_strategy_selects_python_runtime_folder_first():
    strategy = json.loads(STRATEGY_PATH.read_text(encoding="utf-8"))
    candidates = strategy["candidate_summary"]

    assert strategy["selected_first_milestone"] == "python-runtime-folder"
    assert candidates["python-runtime-folder"]["status"] == "selected_first_milestone"
    assert candidates["pyinstaller-onefile"]["allowed"] is False
    assert "no UPX" in candidates["pyinstaller-onedir"]["requires"]
    assert candidates["python-runtime-folder"]["staging_tool"] == "tools/stage_python_runtime.py"
    assert candidates["python-runtime-folder"]["runtime_builder"] == "tools/build_python_runtime_from_venv.py --base-only --python-version 3.12"
    assert "--require-bundled-python" in candidates["python-runtime-folder"]["preflight_gate"]
    managed_env = candidates["python-runtime-folder"]["first_launch_dependency_env"]
    assert managed_env["path"] == "user-data/runtime-env"
    assert managed_env["marker"] == "naia-runtime-env.json"
    assert managed_env["requirements"] == "requirements-headless.txt"
    assert {"-m", "venv", "pip", "install", "-r", "requirements-headless.txt"} <= set(
        managed_env["install_command_terms"]
    )
    assert "scanner_result_notes" in strategy["required_measurements"]
    assert strategy["scanner_policy"]["submission_notes_required"] is True


def test_backend_runtime_strategy_checker_accepts_current_contract():
    payload = check_backend_runtime_strategy()

    assert payload["ok"] is True
    assert payload["violations"] == []


def test_backend_runtime_strategy_checker_cli():
    result = subprocess.run(
        [sys.executable, "tools/check_backend_runtime_strategy.py"],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["ok"] is True
    assert payload["selected_first_milestone"] == "python-runtime-folder"
