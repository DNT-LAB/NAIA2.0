import json
import os
import subprocess
import sys

from fastapi.testclient import TestClient

from core.web_session_app import create_headless_app
from core.web_session_context import InMemoryTokenManager, WebSessionContext


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
    payload = json.loads(result.stdout)

    assert payload == {
        "pyqt_imported": False,
        "title": "NAIA Remote Headless",
        "main_window": True,
        "entrypoint": "NAIA_web_headless",
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
