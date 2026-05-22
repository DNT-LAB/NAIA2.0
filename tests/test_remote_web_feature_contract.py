import json
from pathlib import Path
import subprocess
import sys

from tools.check_remote_web_feature_contract import validate_remote_web_feature_contract


CONTRACT_PATH = Path("release_assets/manifests/remote_web_feature_contract.json")


def test_remote_web_feature_contract_covers_real_headless_routes():
    payload = validate_remote_web_feature_contract(CONTRACT_PATH)

    assert payload["ok"] is True
    assert payload["feature_count"] >= 10
    assert any(source.endswith("app\\backend\\server\\danbooru_routes.py") or source.endswith("app/backend/server/danbooru_routes.py") for source in payload["route_sources"])
    assert any(source.endswith("app\\backend\\server\\install_manager_routes.py") or source.endswith("app/backend/server/install_manager_routes.py") for source in payload["route_sources"])
    assert any(source.endswith("app\\backend\\server\\prompt_tools_routes.py") or source.endswith("app/backend/server/prompt_tools_routes.py") for source in payload["route_sources"])
    assert any(source.endswith("app\\backend\\server\\state_routes.py") or source.endswith("app/backend/server/state_routes.py") for source in payload["route_sources"])
    assert any(source.endswith("app\\backend\\server\\style_thumbnail_routes.py") or source.endswith("app/backend/server/style_thumbnail_routes.py") for source in payload["route_sources"])
    assert payload["contract_route_count"] == payload["source_route_count"]
    assert payload["violations"] == []


def test_remote_web_feature_contract_names_expected_required_workflows():
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    features = {feature["id"]: feature for feature in contract["feature_groups"]}

    assert "prompt_tools" in features
    assert "params_workflow_search" in features
    assert "presets" in features
    assert "danbooru" in features
    assert "artist_thumbnail" in features
    assert "result_history_viewer_actions" in features
    assert "websocket_shared_state" in features
    assert "Generate dispatch with configured NovelAI/WebUI/ComfyUI or controlled test doubles" in contract["required_live_smoke"]


def test_check_remote_web_feature_contract_cli_outputs_machine_readable_json():
    result = subprocess.run(
        [sys.executable, "tools/check_remote_web_feature_contract.py"],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["ok"] is True
    assert payload["violations"] == []


def test_check_remote_web_feature_contract_rejects_undocumented_source_route(tmp_path):
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    removed_route = contract["feature_groups"][0]["routes"].pop()
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")

    payload = validate_remote_web_feature_contract(contract_path)

    assert payload["ok"] is False
    assert {
        "method": removed_route["method"],
        "path": removed_route["path"],
        "reason": "source route is not documented in contract",
    } in payload["violations"]
