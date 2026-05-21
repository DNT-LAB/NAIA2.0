import subprocess


def test_electron_main_contract_node_tests_pass():
    result = subprocess.run(
        ["node", "--test", "app/electron/test/main_contract.test.cjs"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
