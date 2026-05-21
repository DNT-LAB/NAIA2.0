import json
from pathlib import Path
import subprocess
import sys

from tools.stage_electron_release import stage_electron_release


CONTRACT_PATH = Path("release_assets/manifests/remote_web_smoke_contract.json")


def test_remote_web_smoke_contract_lists_core_feature_surface():
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    features = {check["feature"] for check in contract["http_checks"]}

    assert "web_shell" in features
    assert "setup_api_status" in features
    assert "params_resolutions" in features
    assert "prompt_tools_highlight_index" in features
    assert "event_preset_status" in features
    assert "artist_thumb_state" in features
    assert "character_viewer_state" in features
    assert "history_list" in features
    assert contract["websocket_checks"][0]["expected_initial_types"] == [
        "session",
        "desktop_window_state",
        "mode",
        "options",
        "params",
        "queue_state",
        "api_status",
        "init_complete",
        "lazy_indices_ready",
    ]


def test_smoke_remote_web_contract_cli_validates_real_staged_backend(tmp_path):
    target = tmp_path / "NAIA-Web"
    stage_electron_release(Path.cwd(), target, copy=True)
    backend = target / "resources" / "naia-backend"

    result = subprocess.run(
        [
            sys.executable,
            "tools/smoke_remote_web_contract.py",
            str(backend),
            "--user-data",
            str(target / "user-data"),
        ],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["ok"] is True
    assert payload["failures"] == []
    assert len(payload["http_checks"]) >= 15
    assert payload["websocket_checks"][0]["ok"] is True
    assert not any(backend.rglob("__pycache__"))


def test_smoke_remote_web_contract_cli_reports_missing_backend(tmp_path):
    result = subprocess.run(
        [sys.executable, "tools/smoke_remote_web_contract.py", str(tmp_path / "missing")],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "backend root is not a directory" in result.stdout
