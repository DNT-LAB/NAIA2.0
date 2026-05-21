import json
import subprocess
import sys
from pathlib import Path

from tools.check_packaged_electron_feature_smoke import check_packaged_electron_feature_smoke


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_packaged_electron_feature_smoke_accepts_current_contract():
    payload = check_packaged_electron_feature_smoke()

    assert payload["ok"] is True
    assert payload["required_feature_count"] == 15
    assert payload["mapped_feature_count"] == 15
    assert payload["violations"] == []


def test_packaged_electron_feature_smoke_rejects_missing_required_feature(tmp_path):
    contract = tmp_path / "remote_contract.json"
    manifest = tmp_path / "feature_smoke.json"
    package = tmp_path / "package.json"
    cdp = tmp_path / "smoke_electron_cdp.py"
    _write(
        contract,
        json.dumps({
            "feature_groups": [
                {
                    "id": "websocket_shared_state",
                    "routes": [{"method": "WEBSOCKET", "path": "/ws"}],
                    "websocket_commands": ["random"],
                }
            ]
        }),
    )
    _write(
        manifest,
        json.dumps({
            "remote_feature_contract": str(contract),
            "cdp_smoke_tool": str(cdp),
            "package_scripts": ["smoke:electron:packaged"],
            "required_features": [
                {
                    "id": "random_prompt",
                    "feature_groups": ["websocket_shared_state"],
                    "websocket_commands": ["random"],
                }
            ],
        }),
    )
    _write(package, json.dumps({"scripts": {"smoke:electron:packaged": "ok"}}))
    _write(
        cdp,
        "shell_ready_s timings under_runtime_downloads backendRestart "
        "localStoragePersistsAfterReload featureWorkflows allRequiredFeaturesObserved "
        "firstPaintProxyMs randomPromptRoundTrip",
    )

    payload = check_packaged_electron_feature_smoke(manifest, electron_package_path=package)

    assert payload["ok"] is False
    assert any("required packaged feature smoke mapping missing" in item["reason"] for item in payload["violations"])


def test_packaged_electron_feature_smoke_cli():
    result = subprocess.run(
        [sys.executable, "tools/check_packaged_electron_feature_smoke.py"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
