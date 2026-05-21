import json
import subprocess
import sys
from pathlib import Path

from tools.check_electron_shell_contract import check_electron_shell_contract


CONTRACT_PATH = Path("release_assets/manifests/electron_shell_contract.json")


def test_electron_shell_contract_checker_accepts_current_shell():
    payload = check_electron_shell_contract()

    assert payload["ok"] is True
    assert payload["violations"] == []


def test_electron_shell_contract_checker_cli():
    result = subprocess.run(
        [
            sys.executable,
            "tools/check_electron_shell_contract.py",
            "--contract",
            str(CONTRACT_PATH),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
