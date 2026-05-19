import json
import os
import subprocess
import sys
import io
import zipfile
import base64

from fastapi.testclient import TestClient
import pandas as pd
from PIL import Image

from core.api_config_service import ApiConfigService, CloudflaredService
from core.api_verification import VerifyResult
from core.search_result_model import SearchResultModel
from core.web_session_app import create_headless_app
from core.web_session_context import InMemoryTokenManager, WebSessionContext


class _WildcardManager:
    wildcard_dict_tree = {}
    instant_wildcard_tree = {}
    instant_wildcard_dict = {}


def _png_bytes(color=(255, 0, 0, 255)) -> bytes:
    image = Image.new("RGBA", (1, 1), color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _write_round47_tab_fixture(root):
    png_bytes = _png_bytes()
    data_dir = root / "data"
    taglist_dir = data_dir / "taglist"
    thumb_dir = data_dir / "character_thumbnails"
    taglist_dir.mkdir(parents=True)
    thumb_dir.mkdir(parents=True)
    style_b64 = base64.b64encode(png_bytes).decode("ascii")
    (taglist_dir / "style_meta_tags.json").write_text(
        json.dumps({
            "categories": {
                "render": {
                    "name": "Render",
                    "description": "render styles",
                    "tags": ["airbrush"],
                }
            }
        }),
        encoding="utf-8",
    )
    (taglist_dir / "style_thumbnails.json").write_text(
        json.dumps({"airbrush": f"data:image/png;base64,{style_b64}"}),
        encoding="utf-8",
    )
    (data_dir / "copyright_groups.json").write_text(
        json.dumps({"series": {"girl": ["hero"], "boy": []}}),
        encoding="utf-8",
    )
    (data_dir / "character_analysis.json").write_text(
        json.dumps({
            "series": {
                "hero": {
                    "total_rows": 3,
                    "gender": "girl",
                    "aliases": ["heroine"],
                    "personal_color": [{"tag": "blue eyes", "count": 2, "pct": 66.6}],
                    "characteristics": [{"tag": "long hair", "count": 2, "pct": 66.6}],
                    "breast_size": {"distribution": [{"tag": "small breasts", "count": 1, "pct": 33.3}]},
                    "alternates": [],
                }
            }
        }),
        encoding="utf-8",
    )
    (thumb_dir / "index.json").write_text(json.dumps({"series::hero": "hero.png"}), encoding="utf-8")
    (thumb_dir / "hero.png").write_bytes(png_bytes)


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


def test_headless_tab_services_cover_thumb_and_character_viewer(tmp_path):
    _write_round47_tab_fixture(tmp_path)
    context = WebSessionContext(
        repo_root=tmp_path,
        token_manager=InMemoryTokenManager({"nai_token": "token"}),
    )
    context.headless_generation_execute_enabled = False
    app = create_headless_app(context)
    client = TestClient(app)

    capabilities = client.get("/api/headless/capabilities")
    assert capabilities.status_code == 200
    right_tabs = capabilities.json()["right_tabs"]
    assert right_tabs["thumb"] is True
    assert right_tabs["characters"] is True
    assert right_tabs["artists"] is False

    thumb_state = client.get("/api/thumb/state")
    assert thumb_state.status_code == 200
    assert thumb_state.json()["selected"] == "render"
    thumb_category = client.get("/api/thumb/category/render")
    assert thumb_category.status_code == 200
    assert thumb_category.json()["tags"][0]["tag"] == "airbrush"
    thumb_image = client.get("/api/thumb/image?tag=airbrush")
    assert thumb_image.status_code == 200
    assert thumb_image.headers["content-type"].startswith("image/png")
    assert thumb_image.content.startswith(b"\x89PNG")

    viewer_state = client.get("/api/character-viewer/state")
    assert viewer_state.status_code == 200
    assert viewer_state.json()["available"] is True
    groups = client.get("/api/character-viewer/groups")
    assert groups.status_code == 200
    assert groups.json()["items"][0]["key"] == "__ALL__"
    listing = client.get("/api/character-viewer/list?group=series")
    assert listing.status_code == 200
    assert listing.json()["items"][0]["character"] == "hero"
    detail = client.post("/api/character-viewer/detail", json={"group": "series", "character": "hero"})
    assert detail.status_code == 200
    assert "blue eyes" in detail.json()["prompt"]["character_prompt"]
    thumbnail = client.get("/api/character-viewer/thumbnail?group=series&character=hero")
    assert thumbnail.status_code == 200
    assert thumbnail.headers["content-type"].startswith("image/png")

    generate = client.post("/api/character-viewer/generate", json={
        "request_id": "char-round47",
        "group": "series",
        "character": "hero",
        "character_prompt": "hero, blue eyes",
        "prefix": "1girl",
        "postfix": "best quality",
    })
    assert generate.status_code == 200
    assert generate.json()["ok"] is True
    assert context.last_generation_params["character_viewer_request"] is True


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


def test_headless_websocket_set_param_updates_server_owned_params():
    context = WebSessionContext(token_manager=InMemoryTokenManager())
    app = create_headless_app(context)
    client = TestClient(app)

    with client.websocket_connect("/ws") as ws:
        for _ in range(9):
            ws.receive_json()
        ws.send_json({"type": "set_param", "key": "steps", "value": "31"})
        steps_payload = ws.receive_json()
        ws.send_json({"type": "set_param", "key": "auto_fit_resolution", "value": "true"})
        auto_fit_payload = ws.receive_json()

    assert steps_payload["type"] == "params"
    assert steps_payload["steps"] == "31"
    assert context.remote_params["steps"] == "31"
    assert auto_fit_payload["auto_fit_resolution"] is True
    assert context.remote_params["auto_fit_resolution"] is True


def test_headless_websocket_active_ratings_update_search_state_and_random():
    context = WebSessionContext(
        token_manager=InMemoryTokenManager(),
        wildcard_manager=_WildcardManager(),
        filter_data_manager=False,
        search_results=SearchResultModel(pd.DataFrame([
            {"general": "general-only-tag", "rating": "g"},
            {"general": "sensitive-only-tag", "rating": "s"},
        ])),
    )
    app = create_headless_app(context)
    client = TestClient(app)

    with client.websocket_connect("/ws") as ws:
        for _ in range(9):
            ws.receive_json()
        ws.send_json({"type": "set_active_ratings", "ratings": ["s"]})
        state = ws.receive_json()
        ws.send_json({"type": "random", "random_request_id": "rating-filter"})
        random_msg = ws.receive_json()

    assert state["type"] == "search_state"
    assert state["active_ratings"] == ["s"]
    assert state["count"] == 1
    assert state["rating_counts"] == {"g": 1, "s": 1, "q": 0, "e": 0}
    assert random_msg["type"] == "prompt_generated"
    assert random_msg["random_request_id"] == "rating-filter"
    assert "sensitive-only-tag" in random_msg["prompt"]
    assert "general-only-tag" not in random_msg["prompt"]


def test_headless_websocket_retired_desktop_commands_are_explicit():
    context = WebSessionContext(token_manager=InMemoryTokenManager())
    app = create_headless_app(context)
    client = TestClient(app)

    with client.websocket_connect("/ws") as ws:
        for _ in range(9):
            ws.receive_json()
        ws.send_json({"type": "read_hires_preset_overlay", "preset_name": "legacy-preset"})
        overlay = ws.receive_json()
        ws.send_json({"type": "set_module_param", "module_id": "prompt_engineering", "key": "x", "value": "y"})
        retired = ws.receive_json()
        ws.send_json({"type": "result_upscale", "source": "current"})
        upscale_state = ws.receive_json()
        upscale_retired = ws.receive_json()
        ws.send_json({"type": "result_image_action", "action": "img2img", "source": "current"})
        image_action_retired = ws.receive_json()

    assert overlay == {
        "type": "hires_preset_overlay",
        "preset_name": "legacy-preset",
        "original": {},
        "overlay": None,
        "headless": True,
        "available": False,
    }
    assert retired["type"] == "toast"
    assert retired["level"] == "info"
    assert retired["headless"] is True
    assert "set_module_param" in retired["message"]
    assert upscale_state["type"] == "result_upscale_state"
    assert upscale_state["success"] is False
    assert upscale_state["headless"] is True
    assert upscale_retired["type"] == "toast"
    assert "result_upscale" in upscale_retired["message"]
    assert image_action_retired["type"] == "toast"
    assert "result_image_action/img2img" in image_action_retired["message"]


def test_headless_websocket_auto_save_and_save_directory_state_are_server_owned(tmp_path):
    context = WebSessionContext(token_manager=InMemoryTokenManager())
    app = create_headless_app(context)
    client = TestClient(app)

    with client.websocket_connect("/ws") as ws:
        for _ in range(9):
            ws.receive_json()
        ws.send_json({"type": "get_module_state", "module_id": "auto_save"})
        auto_save = ws.receive_json()
        ws.send_json({"type": "set_module_param", "module_id": "auto_save", "key": "save_as_webp", "value": "true"})
        updated_auto_save = ws.receive_json()
        ws.send_json({"type": "get_module_state", "module_id": "save_directory"})
        save_directory = ws.receive_json()
        ws.send_json({
            "type": "set_module_param",
            "module_id": "save_directory",
            "key": "base_path",
            "value": str(tmp_path),
        })
        updated_save_directory = ws.receive_json()

    assert auto_save["type"] == "module_state"
    assert auto_save["module_id"] == "auto_save"
    assert auto_save["available"] is True
    assert auto_save["unsaved_history_count"] == 0
    assert updated_auto_save["save_as_webp"] is True
    assert context.auto_save_state["save_as_webp"] is True
    assert save_directory["module_id"] == "save_directory"
    assert save_directory["available"] is True
    assert save_directory["control_allowed"] is True
    assert updated_save_directory["base_path"] == str(tmp_path)
    assert str(tmp_path) in updated_save_directory["current_save_directory"]


def test_headless_supported_module_states_do_not_import_middle_modules_in_fresh_process(tmp_path):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.getcwd()
    code = r"""
import json
import sys
from fastapi.testclient import TestClient
from core.web_session_app import create_headless_app
from core.web_session_context import InMemoryTokenManager, WebSessionContext

context = WebSessionContext(token_manager=InMemoryTokenManager({"webui_url": "http://127.0.0.1:7860"}))
app = create_headless_app(context)
client = TestClient(app)

with client.websocket_connect("/ws") as ws:
    for _ in range(9):
        ws.receive_json()
    ws.send_json({"type": "get_module_state", "module_id": "prompt_engineering"})
    pe_state = ws.receive_json()
    ws.send_json({"type": "set_module_param", "module_id": "prompt_engineering", "key": "pp_remove_author", "value": "true"})
    pe_updated = ws.receive_json()
    ws.send_json({"type": "get_module_state", "module_id": "conditional_prompt"})
    cond_state = ws.receive_json()
    ws.send_json({"type": "set_module_param", "module_id": "conditional_prompt", "key": "enabled", "value": "true"})
    cond_updated = ws.receive_json()
    ws.send_json({"type": "set_module_param", "module_id": "character", "key": "add_character", "value": "true"})
    char_added = ws.receive_json()
    ws.send_json({"type": "set_module_param", "module_id": "character", "key": "char_prompt_0", "value": "module-free character"})
    char_updated = ws.receive_json()
    ws.send_json({"type": "set_module_param", "module_id": "automation", "key": "auto_type", "value": "1"})
    automation_type = ws.receive_json()
    ws.send_json({"type": "set_module_param", "module_id": "automation", "key": "timer_minutes", "value": "15"})
    automation_updated = ws.receive_json()
    ws.send_json({"type": "set_module_param", "module_id": "webui_hiresfix_assist", "key": "enabled", "value": "true"})
    hires_enabled = ws.receive_json()
    ws.send_json({"type": "set_module_param", "module_id": "webui_hiresfix_assist", "key": "target", "value": "768"})
    hires_target = ws.receive_json()
    retired_states = {}
    for module_id in [
        "character_reference",
        "vibe_transfer",
        "instant_wildcard",
        "wildcard_status",
        "e621_event",
        "ollama",
    ]:
        ws.send_json({"type": "get_module_state", "module_id": module_id})
        retired_states[module_id] = ws.receive_json()

forbidden = [
    "PyQt6",
    "legacy_desktop",
    "core.remote_api_server",
    "core.middle_section_controller",
    "modules.prompt_engineering_module",
    "modules.conditional_prompt_module",
    "modules.character_module",
    "modules.automation_module",
]
print(json.dumps({
    "forbidden_loaded": [name for name in forbidden if name in sys.modules],
    "pe_available": pe_state.get("available"),
    "pe_remove_author": pe_updated.get("preprocessing", {}).get("remove_author"),
    "cond_available": cond_state.get("available"),
    "cond_enabled": cond_updated.get("enabled"),
    "char_count": char_added.get("character_count"),
    "char_prompt": char_updated.get("characters", [{}])[0].get("prompt"),
    "automation_auto_type": automation_type.get("auto_type"),
    "automation_timer": automation_updated.get("timer_minutes"),
    "hires_enabled": hires_enabled.get("enabled"),
    "hires_target": hires_target.get("target"),
    "remote_param_hires": context.remote_params.get("webui_hiresfix_assist"),
    "remote_param_target": context.remote_params.get("webui_hiresfix_assist_target"),
    "retired_modules": {
        module_id: {
            "available": state.get("available"),
            "retired": state.get("retired"),
            "has_message": bool(state.get("message")),
        }
        for module_id, state in retired_states.items()
    },
}))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout.strip().splitlines()[-1])

    assert payload == {
        "forbidden_loaded": [],
        "pe_available": True,
        "pe_remove_author": True,
        "cond_available": True,
        "cond_enabled": True,
        "char_count": 1,
        "char_prompt": "module-free character",
        "automation_auto_type": 1,
        "automation_timer": "15",
        "hires_enabled": True,
        "hires_target": 768,
        "remote_param_hires": True,
        "remote_param_target": 768,
        "retired_modules": {
            "character_reference": {"available": False, "retired": True, "has_message": True},
            "vibe_transfer": {"available": False, "retired": True, "has_message": True},
            "instant_wildcard": {"available": False, "retired": True, "has_message": True},
            "wildcard_status": {"available": False, "retired": True, "has_message": True},
            "e621_event": {"available": False, "retired": True, "has_message": True},
            "ollama": {"available": False, "retired": True, "has_message": True},
        },
    }


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
        headless_generation_execute_enabled=False,
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
        headless_generation_execute_enabled=False,
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

context = WebSessionContext(
    token_manager=InMemoryTokenManager({"nai_token": "pst-token"}),
    headless_generation_execute_enabled=False,
)
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


class _FakeApiService:
    def __init__(self):
        self.calls = []

    def call_generation_api(self, params, progress_callback=None):
        self.calls.append(dict(params))
        image = Image.new("RGB", (16, 12), (12, 34, 56))
        return {
            "status": "success",
            "image": image,
        }


def test_headless_generate_executes_result_store_and_history_without_imagewindow():
    context = WebSessionContext(
        token_manager=InMemoryTokenManager({"nai_token": "pst-headless-token"}),
    )
    context.api_service = _FakeApiService()
    app = create_headless_app(context)
    client = TestClient(app)

    with client.websocket_connect("/ws") as ws:
        for _ in range(9):
            ws.receive_json()
        ws.send_json({
            "type": "generate",
            "prompt": "result prompt",
            "negative_prompt": "result negative",
            "overrides": {"resolution": "16 x 12", "seed": 123, "seed_fixed": True},
        })
        dispatched = ws.receive_json()
        queued_status = ws.receive_json()
        queued_state = ws.receive_json()
        running_status = ws.receive_json()
        running_state = ws.receive_json()
        completed_status = ws.receive_json()
        image_meta = ws.receive_json()
        webp_bytes = ws.receive_bytes()
        history_message = ws.receive_json()
        final_state = ws.receive_json()

    assert dispatched["ok"] is True
    assert queued_status["message"] == "queued"
    assert queued_state["total"] == 1
    assert running_status == {"type": "status", "is_generating": True, "message": "generating"}
    assert running_state["total"] == 0
    assert completed_status == {"type": "status", "is_generating": False, "message": "completed"}
    assert image_meta["type"] == "image_meta"
    assert image_meta["width"] == 16
    assert image_meta["height"] == 12
    assert image_meta["prompt"] == "result prompt"
    assert webp_bytes.startswith(b"RIFF")
    assert history_message["type"] == "viewer_new_image"
    assert history_message["rel_path"].startswith("__history_item__/")
    assert history_message["total"] == 1
    assert final_state["type"] == "queue_state"
    assert final_state["total"] == 0
    assert context.main_window is None
    assert context.remote_bridge is None

    latest = client.get("/api/latest-image")
    assert latest.status_code == 200
    assert latest.headers["content-type"].startswith("image/webp")
    assert latest.content.startswith(b"RIFF")

    png = client.get("/api/result/image/png")
    assert png.status_code == 200
    assert png.headers["content-type"].startswith("image/png")
    assert png.content.startswith(b"\x89PNG")

    history = client.get("/api/history/list")
    assert history.status_code == 200
    history_payload = history.json()
    assert history_payload["total"] == 1
    history_id = history_payload["images"][0]["history_id"]

    thumb = client.get(f"/api/history/thumb/{history_id}")
    assert thumb.status_code == 200
    assert thumb.content.startswith(b"RIFF")

    image = client.get(f"/api/history/image/{history_id}")
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/png")

    meta = client.get(f"/api/history/meta/{history_id}?full=true")
    assert meta.status_code == 200
    assert meta.json()["prompt"] == "result prompt"


def test_headless_generate_executes_non_nai_backend_modes_without_desktop_controllers():
    backends = [
        ("WEBUI", "webui_url", "http://127.0.0.1:7860"),
        ("COMFYUI", "comfyui_url", "http://127.0.0.1:8188"),
    ]
    for mode, token_key, token_value in backends:
        context = WebSessionContext(token_manager=InMemoryTokenManager({token_key: token_value}))
        context.set_api_mode(mode)
        context.api_service = _FakeApiService()
        app = create_headless_app(context)
        client = TestClient(app)

        with client.websocket_connect("/ws") as ws:
            for _ in range(9):
                ws.receive_json()
            ws.send_json({
                "type": "generate",
                "prompt": f"{mode.lower()} result prompt",
                "negative_prompt": "",
                "overrides": {"resolution": "16 x 12", "seed": -1},
            })
            seen = []
            blob_seen = False
            for _ in range(10):
                message = ws.receive()
                if "text" in message:
                    payload = json.loads(message["text"])
                    seen.append(payload.get("type"))
                    if payload.get("type") == "viewer_new_image":
                        break
                elif "bytes" in message:
                    blob_seen = True

        assert "image_meta" in seen
        assert "viewer_new_image" in seen
        assert blob_seen is True
        assert context.api_service.calls[0]["api_mode"] == mode
        assert context.api_service.calls[0]["credential"] == token_value
        assert context.result_store.history_total() == 1
        assert context.main_window is None
        assert context.remote_bridge is None


def test_headless_unsaved_history_download_and_save_all_are_server_owned(tmp_path):
    context = WebSessionContext(
        token_manager=InMemoryTokenManager({"nai_token": "pst-headless-token"}),
    )
    context.api_service = _FakeApiService()
    context.set_module_param("save_directory", "base_path", str(tmp_path), client_host="127.0.0.1")
    context.set_module_param("save_directory", "use_timestamp_folder", "false", client_host="127.0.0.1")
    app = create_headless_app(context)
    client = TestClient(app)

    with client.websocket_connect("/ws") as ws:
        for _ in range(9):
            ws.receive_json()
        ws.send_json({
            "type": "generate",
            "prompt": "unsaved prompt",
            "overrides": {"resolution": "16 x 12", "seed": 99, "seed_fixed": True},
        })
        for _ in range(9):
            message = ws.receive()
            if "text" in message and json.loads(message["text"]).get("type") == "viewer_new_image":
                break

    auto_state = context.auto_save_state_payload()
    assert auto_state["unsaved_history_count"] == 1

    download = client.get("/api/history/unsaved/download")
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/zip")
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        names = archive.namelist()
        assert len(names) == 1
        assert names[0].endswith(".png")
        assert archive.read(names[0]).startswith(b"\x89PNG")

    save_all = client.post("/api/history/unsaved/save-all")
    assert save_all.status_code == 200
    save_payload = save_all.json()
    assert save_payload["saved"] == 1
    assert save_payload["remaining"] == 0
    assert len(save_payload["paths"]) == 1
    assert os.path.isfile(save_payload["paths"][0])

    history = client.get("/api/history/list").json()
    assert history["images"][0]["file_path"] == save_payload["paths"][0]
    assert history["images"][0]["source"] == "file"

    empty_download = client.get("/api/history/unsaved/download")
    assert empty_download.status_code == 404


def test_api_service_import_does_not_import_pyqt_in_fresh_process():
    env = dict(os.environ)
    env["PYTHONPATH"] = os.getcwd()
    code = r"""
import json
import sys
from core.api_service import APIService
print(json.dumps({
    "pyqt_imported": "PyQt6" in sys.modules,
    "api_service": APIService.__name__,
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

    assert payload == {"pyqt_imported": False, "api_service": "APIService"}


def test_headless_generation_result_broadcast_does_not_import_desktop_bridge_in_fresh_process():
    env = dict(os.environ)
    env["PYTHONPATH"] = os.getcwd()
    code = r"""
import json
import sys
from fastapi.testclient import TestClient
from PIL import Image
from core.web_session_app import create_headless_app
from core.web_session_context import InMemoryTokenManager, WebSessionContext

class FakeApiService:
    def call_generation_api(self, params, progress_callback=None):
        return {"status": "success", "image": Image.new("RGB", (8, 8), (1, 2, 3))}

context = WebSessionContext(token_manager=InMemoryTokenManager({"nai_token": "pst-token"}))
context.api_service = FakeApiService()
app = create_headless_app(context)
client = TestClient(app)
with client.websocket_connect("/ws") as ws:
    for _ in range(9):
        ws.receive_json()
    ws.send_json({"type": "generate", "prompt": "bridge-free", "overrides": {"resolution": "8 x 8"}})
    seen = []
    blob_seen = False
    for _ in range(10):
        message = ws.receive()
        if "text" in message:
            payload = json.loads(message["text"])
            seen.append(payload.get("type"))
            if payload.get("type") == "viewer_new_image":
                break
        elif "bytes" in message:
            blob_seen = True
print(json.dumps({
    "pyqt_imported": "PyQt6" in sys.modules,
    "remote_bridge_imported": "core.remote_api_server" in sys.modules,
    "modern_main_imported": "ui.main_window" in sys.modules,
    "image_window_imported": "ui.image_window" in sys.modules,
    "seen": seen,
    "blob_seen": blob_seen,
    "history_total": context.result_store.history_total(),
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

    assert payload["pyqt_imported"] is False
    assert payload["remote_bridge_imported"] is False
    assert payload["modern_main_imported"] is False
    assert payload["image_window_imported"] is False
    assert "image_meta" in payload["seen"]
    assert "viewer_new_image" in payload["seen"]
    assert payload["blob_seen"] is True
    assert payload["history_total"] == 1


def test_headless_startup_random_and_generate_do_not_import_desktop_tabs_or_modules_in_fresh_process():
    env = dict(os.environ)
    env["PYTHONPATH"] = os.getcwd()
    code = r"""
import json
import sys
import pandas as pd
from fastapi.testclient import TestClient
from PIL import Image
from core.search_result_model import SearchResultModel
from core.web_session_app import create_headless_app
from core.web_session_context import InMemoryTokenManager, WebSessionContext

class WildcardManager:
    wildcard_dict_tree = {}
    instant_wildcard_tree = {}
    instant_wildcard_dict = {}

class FakeApiService:
    def call_generation_api(self, params, progress_callback=None):
        return {"status": "success", "image": Image.new("RGB", (8, 8), (4, 5, 6))}

context = WebSessionContext(
    token_manager=InMemoryTokenManager({"nai_token": "pst-token"}),
    wildcard_manager=WildcardManager(),
    filter_data_manager=False,
    search_results=SearchResultModel(pd.DataFrame([
        {"general": "audit alpha, audit beta", "rating": "s"},
    ])),
)
context.api_service = FakeApiService()
app = create_headless_app(context)
client = TestClient(app)
with client.websocket_connect("/ws") as ws:
    for _ in range(9):
        ws.receive_json()
    ws.send_json({"type": "random", "ratings": ["s"], "random_request_id": "audit-random"})
    random_msg = ws.receive_json()
    ws.send_json({"type": "generate", "prompt": random_msg.get("prompt", ""), "overrides": {"resolution": "8 x 8"}})
    blob_seen = False
    seen = []
    for _ in range(12):
        message = ws.receive()
        if "text" in message:
            payload = json.loads(message["text"])
            seen.append(payload.get("type"))
            if payload.get("type") == "viewer_new_image":
                break
        elif "bytes" in message:
            blob_seen = True

forbidden = [
    "PyQt6",
    "legacy_desktop",
    "core.remote_api_server",
    "core.middle_section_controller",
    "core.tab_controller",
    "modules.character_module",
    "modules.prompt_engineering_module",
    "modules.conditional_prompt_module",
    "tabs.turbo_event_sequence_tab",
    "tabs.studio_tab",
    "tabs.image_window",
    "tabs.setting_tabs",
]
print(json.dumps({
    "forbidden_loaded": [name for name in forbidden if name in sys.modules],
    "random_type": random_msg.get("type"),
    "has_audit_prompt": "audit alpha" in random_msg.get("prompt", ""),
    "seen": seen,
    "blob_seen": blob_seen,
    "history_total": context.result_store.history_total(),
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

    assert payload["forbidden_loaded"] == []
    assert payload["random_type"] == "prompt_generated"
    assert payload["has_audit_prompt"] is True
    assert "image_meta" in payload["seen"]
    assert "viewer_new_image" in payload["seen"]
    assert payload["blob_seen"] is True
    assert payload["history_total"] == 1
