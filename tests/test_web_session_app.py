import json
import os
import subprocess
import sys

from fastapi.testclient import TestClient
import pandas as pd

from core.api_config_service import ApiConfigService, CloudflaredService
from core.api_verification import VerifyResult
from core.search_result_model import SearchResultModel
from core.web_session_app import create_headless_app
from core.web_session_context import InMemoryTokenManager, WebSessionContext


class _WildcardManager:
    wildcard_dict_tree = {}
    instant_wildcard_tree = {}
    instant_wildcard_dict = {}


def test_headless_app_import_and_factory_do_not_import_pyqt_in_fresh_process():
    env = dict(os.environ)
    env["PYTHONPATH"] = os.getcwd()
    code = r"""
import json
import sys
from core.web_session_app import create_headless_app
from core.web_session_context import InMemoryTokenManager, WebSessionContext
import NAIA_web_headless

context = WebSessionContext(token_manager=InMemoryTokenManager())
app = create_headless_app(context)
print(json.dumps({
    "pyqt_imported": "PyQt6" in sys.modules,
    "title": app.title,
    "main_window": context.main_window is None,
    "entrypoint": NAIA_web_headless.__name__,
}))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=os.getcwd(),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout.strip().splitlines()[-1])

    assert payload == {
        "pyqt_imported": False,
        "title": "NAIA Remote Headless",
        "main_window": True,
        "entrypoint": "NAIA_web_headless",
    }


def test_headless_websocket_random_generates_prompt_from_core_service():
    context = WebSessionContext(
        token_manager=InMemoryTokenManager(),
        wildcard_manager=_WildcardManager(),
        filter_data_manager=False,
        search_results=SearchResultModel(pd.DataFrame([
            {"general": "alpha, beta", "rating": "s"},
        ])),
    )
    app = create_headless_app(context)
    client = TestClient(app)

    with client.websocket_connect("/ws") as ws:
        for _ in range(9):
            ws.receive_json()
        ws.send_json({
            "type": "random",
            "random_request_id": "round34-random",
            "ratings": ["s"],
            "overrides": {"auto_generate": False},
        })
        message = ws.receive_json()

    assert message["type"] == "prompt_generated"
    assert message["source"] == "random"
    assert message["random_request_id"] == "round34-random"
    assert "alpha" in message["prompt"]
    assert "beta" in message["prompt"]
    assert message["remaining"] == 0
    assert context.prompt_text == message["prompt"]
    assert context.main_window is None
    assert context.remote_bridge is None


def test_headless_websocket_random_does_not_import_pyqt_in_fresh_process():
    env = dict(os.environ)
    env["PYTHONPATH"] = os.getcwd()
    code = r"""
import json
import sys
import pandas as pd
from fastapi.testclient import TestClient
from core.search_result_model import SearchResultModel
from core.web_session_app import create_headless_app
from core.web_session_context import InMemoryTokenManager, WebSessionContext

class WildcardManager:
    wildcard_dict_tree = {}
    instant_wildcard_tree = {}
    instant_wildcard_dict = {}

context = WebSessionContext(
    token_manager=InMemoryTokenManager(),
    wildcard_manager=WildcardManager(),
    filter_data_manager=False,
    search_results=SearchResultModel(pd.DataFrame([
        {"general": "fresh alpha, fresh beta", "rating": "s"},
    ])),
)
app = create_headless_app(context)
client = TestClient(app)
with client.websocket_connect("/ws") as ws:
    for _ in range(9):
        ws.receive_json()
    ws.send_json({"type": "random", "random_request_id": "fresh-random", "ratings": ["s"]})
    message = ws.receive_json()
print(json.dumps({
    "pyqt_imported": "PyQt6" in sys.modules,
    "type": message.get("type"),
    "source": message.get("source"),
    "has_prompt": "fresh alpha" in message.get("prompt", ""),
    "main_window": context.main_window is None,
    "remote_bridge": context.remote_bridge is None,
}))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=os.getcwd(),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout.strip().splitlines()[-1])

    assert payload == {
        "pyqt_imported": False,
        "type": "prompt_generated",
        "source": "random",
        "has_prompt": True,
        "main_window": True,
        "remote_bridge": True,
    }


def test_headless_status_endpoint_uses_web_session_context():
    context = WebSessionContext(
        token_manager=InMemoryTokenManager({"nai_token": "pst-example-token"})
    )
    context.is_generating = True
    context.autocomplete_state.kr_tags_loaded = True
    app = create_headless_app(context)
    client = TestClient(app)

    response = client.get("/api/status")

    assert response.status_code == 200
    assert response.json() == {
        "is_generating": True,
        "api_mode": "NAI",
        "autocomplete": {
            "kr_tags_loaded": True,
            "metadata_fallback": {
                "ready": False,
                "live_path_allows_build": False,
            },
            "translation_cache_size": 0,
            "result_cache_size": 0,
        },
    }


def test_headless_root_serves_remote_web_shell():
    context = WebSessionContext(token_manager=InMemoryTokenManager())
    app = create_headless_app(context)
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "NAIA Remote" in response.text


def test_headless_websocket_sends_initial_remote_web_state():
    context = WebSessionContext(
        token_manager=InMemoryTokenManager({"webui_url": "http://127.0.0.1:7860"})
    )
    context.remote_params["model"] = "NAID4.5F"
    app = create_headless_app(context)
    client = TestClient(app)

    with client.websocket_connect("/ws") as ws:
        messages = [ws.receive_json() for _ in range(9)]
        ws.send_text("sync")
        sync_mode = ws.receive_json()

    assert [message["type"] for message in messages] == [
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
    assert messages[1]["visible"] is False
    assert messages[2]["mode"] == "NAI"
    assert messages[4]["model"] == "NAID4.5F"
    assert messages[6]["webui_url"] == "http://127.0.0.1:7860"
    assert sync_mode == {"type": "mode", "mode": "NAI"}


def test_headless_websocket_verify_and_clear_api(tmp_path):
    tokens = InMemoryTokenManager()
    context = WebSessionContext(
        token_manager=tokens,
        api_config_service=ApiConfigService(
            tokens,
            timestamp_path=tmp_path / "timestamps.json",
            verify_nai_token=lambda token: VerifyResult(True, "verified", "info", value=token),
        ),
    )
    app = create_headless_app(context)
    client = TestClient(app)

    with client.websocket_connect("/ws") as ws:
        for _ in range(9):
            ws.receive_json()
        ws.send_json({"type": "verify_nai", "token": "pst-headless-token"})
        verify_result = ws.receive_json()
        api_status = ws.receive_json()
        ws.send_json({"type": "clear_api", "mode": "NAI"})
        clear_result = ws.receive_json()
        cleared_status = ws.receive_json()

    assert verify_result["type"] == "verify_result"
    assert verify_result["success"] is True
    assert api_status["type"] == "api_status"
    assert api_status["nai_configured"] is True
    assert api_status["setup_required"] is False
    assert clear_result["type"] == "clear_api_result"
    assert clear_result["success"] is True
    assert cleared_status["nai_configured"] is False
    assert cleared_status["setup_required"] is True


def test_headless_websocket_probe_and_cloudflared_state(tmp_path):
    tokens = InMemoryTokenManager({"webui_url": "http://127.0.0.1:7860"})
    cloudflared = CloudflaredService(
        port=7281,
        start_tunnel=lambda _port, on_progress=None: type(
            "Info",
            (),
            {"tunnel_url": "https://headless.trycloudflare.com"},
        )(),
        stop_tunnel=lambda _port: None,
    )
    context = WebSessionContext(
        token_manager=tokens,
        api_config_service=ApiConfigService(
            tokens,
            timestamp_path=tmp_path / "timestamps.json",
            cloudflared=cloudflared,
            verify_webui_url=lambda _url: VerifyResult(True, "webui ok", "info"),
        ),
    )
    app = create_headless_app(context)
    client = TestClient(app)

    with client.websocket_connect("/ws") as ws:
        for _ in range(9):
            ws.receive_json()
        ws.send_json({"type": "probe_api"})
        probe = ws.receive_json()
        ws.send_json({"type": "set_cloudflared_enabled", "enabled": True})
        cloudflared_status = ws.receive_json()
        ws.send_json({"type": "set_cloudflared_enabled", "enabled": False})
        stopped_status = ws.receive_json()

    assert probe["type"] == "probe_result"
    assert probe["results"] == {"NAI": None, "WEBUI": True, "COMFYUI": None}
    assert cloudflared_status["type"] == "api_status"
    assert cloudflared_status["cloudflared_active"] is True
    assert cloudflared_status["cloudflared_url"] == "https://headless.trycloudflare.com"
    assert stopped_status["cloudflared_active"] is False


def test_headless_websocket_generate_normalizes_nai_request_without_desktop_widgets():
    context = WebSessionContext(
        token_manager=InMemoryTokenManager({"nai_token": "pst-headless-token"}),
    )
    app = create_headless_app(context)
    client = TestClient(app)

    with client.websocket_connect("/ws") as ws:
        for _ in range(9):
            ws.receive_json()
        ws.send_json({
            "type": "generate",
            "prompt": "1girl, blue eyes",
            "negative_prompt": "low quality",
            "overrides": {
                "resolution": "1024 x 1024",
                "steps": "31",
                "cfg_scale": "6.5",
                "seed_fixed": "false",
                "seed": "",
                "model": "NAID4.5F",
                "sampler": "k_euler_ancestral",
                "scheduler": "karras",
            },
        })
        dispatched = ws.receive_json()
        status = ws.receive_json()
        queue_state = ws.receive_json()

    request = context.last_generation_request
    assert dispatched["type"] == "generation_dispatched"
    assert dispatched["ok"] is True
    assert dispatched["api_mode"] == "NAI"
    assert dispatched["request_id"] == request.request_id
    assert dispatched["params"]["credential_configured"] is True
    assert "credential" not in dispatched["params"]
    assert status == {"type": "status", "is_generating": False, "message": "queued"}
    assert queue_state["type"] == "queue_state"
    assert queue_state["total"] == 1
    assert request.params["api_mode"] == "NAI"
    assert request.params["credential"] == "pst-headless-token"
    assert request.params["input"] == "1girl, blue eyes"
    assert request.params["negative_prompt"] == "low quality"
    assert request.params["width"] == 1024
    assert request.params["height"] == 1024
    assert request.params["steps"] == 31
    assert request.params["cfg_scale"] == 6.5
    assert isinstance(request.params["seed"], int)
    assert context.main_window is None
    assert context.remote_bridge is None


def test_headless_websocket_generate_normalizes_webui_request_contract():
    context = WebSessionContext(
        token_manager=InMemoryTokenManager({"webui_url": "http://127.0.0.1:7860"}),
    )
    context.set_api_mode("WEBUI")
    app = create_headless_app(context)
    client = TestClient(app)

    with client.websocket_connect("/ws") as ws:
        for _ in range(9):
            ws.receive_json()
        ws.send_json({
            "type": "generate",
            "prompt": "webui prompt",
            "negative_prompt": "webui negative",
            "overrides": {
                "width": "640",
                "height": "960",
                "seed": "-1",
                "enable_hr": "true",
                "hr_scale": "1.7",
                "denoising_strength": "0.42",
                "webui_hiresfix_assist": "false",
            },
        })
        dispatched = ws.receive_json()
        ws.receive_json()
        queue_state = ws.receive_json()

    request = context.last_generation_request
    assert dispatched["ok"] is True
    assert dispatched["api_mode"] == "WEBUI"
    assert queue_state["total"] == 1
    assert request.params["api_mode"] == "WEBUI"
    assert request.params["credential"] == "http://127.0.0.1:7860"
    assert request.params["input"] == "webui prompt"
    assert request.params["negative_prompt"] == "webui negative"
    assert request.params["width"] == 640
    assert request.params["height"] == 960
    assert request.params["seed"] == -1
    assert request.params["enable_hr"] is True
    assert request.params["hr_scale"] == 1.7
    assert request.params["denoising_strength"] == 0.42
    assert request.params["webui_hiresfix_assist"] is False


def test_headless_websocket_generate_missing_credential_is_controlled_error():
    context = WebSessionContext(token_manager=InMemoryTokenManager())
    app = create_headless_app(context)
    client = TestClient(app)

    with client.websocket_connect("/ws") as ws:
        for _ in range(9):
            ws.receive_json()
        ws.send_json({"type": "generate", "prompt": "missing token"})
        dispatched = ws.receive_json()
        toast = ws.receive_json()
        status = ws.receive_json()

    assert dispatched == {
        "type": "generation_dispatched",
        "ok": False,
        "api_mode": "NAI",
        "message": "NAI credential is not configured.",
    }
    assert toast["type"] == "toast"
    assert toast["level"] == "error"
    assert status == {"type": "status", "is_generating": False, "message": "blocked"}
    assert not hasattr(context, "last_generation_request")


def test_headless_websocket_generate_does_not_import_pyqt_in_fresh_process():
    env = dict(os.environ)
    env["PYTHONPATH"] = os.getcwd()
    code = r"""
import json
import sys
from fastapi.testclient import TestClient
from core.web_session_app import create_headless_app
from core.web_session_context import InMemoryTokenManager, WebSessionContext

context = WebSessionContext(token_manager=InMemoryTokenManager({"nai_token": "pst-token"}))
app = create_headless_app(context)
client = TestClient(app)
with client.websocket_connect("/ws") as ws:
    for _ in range(9):
        ws.receive_json()
    ws.send_json({
        "type": "generate",
        "prompt": "fresh prompt",
        "negative_prompt": "",
        "overrides": {"resolution": "832 x 1216"},
    })
    dispatched = ws.receive_json()
    status = ws.receive_json()
    queue_state = ws.receive_json()
print(json.dumps({
    "pyqt_imported": "PyQt6" in sys.modules,
    "type": dispatched.get("type"),
    "ok": dispatched.get("ok"),
    "status": status.get("message"),
    "queue_total": queue_state.get("total"),
    "main_window": context.main_window is None,
    "remote_bridge": context.remote_bridge is None,
}))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=os.getcwd(),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout.strip().splitlines()[-1])

    assert payload == {
        "pyqt_imported": False,
        "type": "generation_dispatched",
        "ok": True,
        "status": "queued",
        "queue_total": 1,
        "main_window": True,
        "remote_bridge": True,
    }
