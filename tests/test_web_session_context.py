import json
import os
import subprocess
import sys

from core.web_session_context import (
    AutocompleteRuntimeState,
    InMemoryTokenManager,
    WebSessionContext,
)


def test_web_session_context_constructs_without_importing_pyqt_in_fresh_process():
    env = dict(os.environ)
    env["PYTHONPATH"] = os.getcwd()
    code = r"""
import json
import sys
from core.web_session_context import InMemoryTokenManager, WebSessionContext

ctx = WebSessionContext(
    token_manager=InMemoryTokenManager({
        "nai_token": "pst-example-token",
        "webui_url": "http://127.0.0.1:7860",
    })
)
ctx.set_option("auto_generate", True)
print(json.dumps({
    "pyqt_imported": "PyQt6" in sys.modules,
    "main_window": ctx.main_window is None,
    "api_mode": ctx.get_api_mode(),
    "auto_generate": ctx.get_options()["auto_generate"],
    "status": ctx.http_status_payload(),
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

    assert payload["pyqt_imported"] is False
    assert payload["main_window"] is True
    assert payload["api_mode"] == "NAI"
    assert payload["auto_generate"] is True
    assert payload["status"] == {
        "is_generating": False,
        "api_mode": "NAI",
        "autocomplete": {
            "kr_tags_loaded": False,
            "metadata_fallback": {
                "ready": False,
                "live_path_allows_build": False,
            },
            "translation_cache_size": 0,
            "result_cache_size": 0,
        },
    }


def test_api_status_payload_matches_remote_web_setup_contract():
    ctx = WebSessionContext(
        token_manager=InMemoryTokenManager({
            "nai_token": "pst-123456789",
            "webui_url": "http://127.0.0.1:7860",
            "comfyui_url": "http://127.0.0.1:8188",
            "nai_token_last_verified": "2026-05-19 12:00:00",
        }),
        autocomplete_state=AutocompleteRuntimeState(
            kr_tags_loaded=True,
            metadata_fallback_ready=True,
            translation_cache_size=2,
            result_cache_size=3,
        ),
    )

    local = ctx.api_status_payload("127.0.0.1")
    remote = ctx.api_status_payload("192.168.1.10")

    assert local["type"] == "api_status"
    assert local["nai_configured"] is True
    assert local["nai_token_preview"] == "pst-123"
    assert local["webui_url"] == "http://127.0.0.1:7860"
    assert local["comfyui_url"] == "http://127.0.0.1:8188"
    assert local["active_mode"] == "NAI"
    assert local["setup_allowed"] is True
    assert local["setup_required"] is False
    assert local["cloudflared_control_allowed"] is True
    assert local["autocomplete"]["kr_tags_loaded"] is True
    assert local["autocomplete"]["metadata_fallback"]["ready"] is True
    assert local["autocomplete"]["translation_cache_size"] == 2
    assert local["autocomplete"]["result_cache_size"] == 3

    assert remote["setup_allowed"] is False
    assert remote["setup_required"] is False
    assert remote["cloudflared_control_allowed"] is False


def test_initial_websocket_messages_cover_headless_startup_state():
    ctx = WebSessionContext(token_manager=InMemoryTokenManager())
    ctx.remote_params["model"] = "NAID4.5F"
    ctx.set_api_mode("WEBUI")
    ctx.set_option("prompt_fixed", True)

    messages = ctx.initial_websocket_messages(
        session_id="session-1",
        client_host="127.0.0.1",
    )

    assert [message["type"] for message in messages] == [
        "session",
        "desktop_window_state",
        "mode",
        "options",
        "params",
        "queue_state",
        "api_status",
        "init_complete",
    ]
    assert messages[1]["visible"] is False
    assert messages[1]["control_allowed"] is False
    assert messages[2]["mode"] == "WEBUI"
    assert messages[3]["prompt_fixed"] is True
    assert messages[4]["api_mode"] == "WEBUI"
    assert messages[4]["model"] == "NAID4.5F"
    assert messages[5]["is_generating"] is False
    assert messages[6]["setup_allowed"] is True
    assert messages[6]["setup_required"] is True


def test_event_bus_mode_changes_and_pipeline_hooks_are_appcontext_compatible():
    ctx = WebSessionContext(token_manager=InMemoryTokenManager())
    events = []
    ctx.subscribe("api_mode_changed", events.append)

    ctx.set_api_mode("COMFYUI")

    assert ctx.get_api_mode() == "COMFYUI"
    assert events == [{"old_mode": "NAI", "new_mode": "COMFYUI"}]

    module_low = object()
    module_high = object()
    ctx.register_pipeline_hook(
        {"target_pipeline": "PromptProcessor", "hook_point": "after_wildcard", "priority": 50},
        module_low,
    )
    ctx.register_pipeline_hook(
        {"target_pipeline": "PromptProcessor", "hook_point": "after_wildcard", "priority": 10},
        module_high,
    )

    assert ctx.get_pipeline_hooks("PromptProcessor", "after_wildcard") == [module_high, module_low]
