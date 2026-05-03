import base64
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from core.comfyui_workflow_manager import ComfyUIWorkflowManager
from core.remote_api_server import RemoteBridge, WebSocketManager, create_app


class _TokenManager:
    def __init__(self, tokens=None):
        self._tokens = tokens or {}

    def get_token(self, key):
        return self._tokens.get(key, "")


class _AppContext:
    secure_token_manager = _TokenManager()
    cloudflared_active = False
    cloudflared_tunnel_url = ""
    cloudflared_status_text = ""
    main_window = None

    def get_api_mode(self):
        return "NAI"


def _ws(host):
    return SimpleNamespace(client=SimpleNamespace(host=host))


def test_api_status_only_forces_setup_for_allowed_loopback_clients():
    bridge = RemoteBridge(_AppContext())

    local = bridge.get_api_status(ws=_ws("127.0.0.1"))
    assert local["setup_allowed"] is True
    assert local["setup_required"] is True

    remote = bridge.get_api_status(ws=_ws("192.168.1.10"))
    assert remote["setup_allowed"] is False
    assert remote["setup_required"] is False


def test_api_status_does_not_force_setup_when_backend_exists():
    ctx = _AppContext()
    ctx.secure_token_manager = _TokenManager({"webui_url": "http://127.0.0.1:7860"})
    bridge = RemoteBridge(ctx)

    local = bridge.get_api_status(ws=_ws("127.0.0.1"))
    assert local["setup_allowed"] is True
    assert local["setup_required"] is False


class _TextEdit:
    def __init__(self, text=""):
        self.text = text
        self.set_calls = []

    def toPlainText(self):
        return self.text

    def setPlainText(self, text):
        self.set_calls.append(text)
        self.text = text


class _GenerationController:
    def __init__(self, is_generating=False):
        self.is_generating = is_generating
        self.executed = []
        self.enqueued = []

    def execute_generation_pipeline(self, overrides=None, priority=0):
        self.executed.append((dict(overrides or {}), priority))

    def _enqueue_current_request(self, overrides=None, priority=0):
        self.enqueued.append((dict(overrides or {}), priority))


class _QueueManager:
    def __init__(self, empty=True, paused=False):
        self._empty = empty
        self.is_paused = paused

    def is_empty(self):
        return self._empty


class _ToggleButton:
    def __init__(self, checked=False, enabled=True):
        self.checked = checked
        self.enabled = enabled

    def setChecked(self, value):
        self.checked = bool(value)

    def setEnabled(self, value):
        self.enabled = bool(value)


class _StatusBar:
    def __init__(self):
        self.messages = []

    def showMessage(self, message, timeout=0):
        self.messages.append((message, timeout))


class _ComfyWorkflowContext(_AppContext):
    def __init__(self):
        self.secure_token_manager = _TokenManager()
        self.cloudflared_active = False
        self.cloudflared_tunnel_url = ""
        self.cloudflared_status_text = ""
        self.comfyui_workflow_manager = ComfyUIWorkflowManager()
        self.comfyui_workflow_manager.set_app_context(self)
        self.events = []
        self.main_window = SimpleNamespace(
            workflow_default_btn=_ToggleButton(checked=True),
            workflow_custom_btn=_ToggleButton(checked=False, enabled=False),
            status_bar=_StatusBar(),
        )

    def get_api_mode(self):
        return "COMFYUI"

    def publish(self, event_name, payload):
        self.events.append((event_name, payload))


def _comfyui_workflow_png_bytes():
    fixture = Path("tests/comfyui/fixtures/anima_int8_metadata.json")
    metadata = json.loads(fixture.read_text(encoding="utf-8"))
    png_info = PngInfo()
    for key in ("prompt", "workflow"):
        png_info.add_text(key, metadata[key])
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(buffer, format="PNG", pnginfo=png_info)
    return buffer.getvalue()


def _bridge_with_generate_context(is_generating=False, queue_empty=True):
    prompt_edit = _TextEdit("main prompt")
    negative_edit = _TextEdit("preset negative")
    generation_controller = _GenerationController(is_generating=is_generating)
    ctx = SimpleNamespace(
        main_window=SimpleNamespace(
            generation_controller=generation_controller,
            main_prompt_textedit=prompt_edit,
            negative_prompt_textedit=negative_edit,
        ),
        generation_queue_manager=_QueueManager(empty=queue_empty),
    )
    return RemoteBridge(ctx), generation_controller, prompt_edit, negative_edit


def test_remote_web_mjs_files_are_served_as_javascript():
    bridge = RemoteBridge(_AppContext())
    client = TestClient(create_app(bridge, WebSocketManager()))

    response = client.get("/js/features/quickFilter.mjs")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")


def test_studio_generate_overrides_do_not_mutate_main_prompt_fields():
    bridge, generation_controller, prompt_edit, negative_edit = _bridge_with_generate_context()
    overrides = {
        "input": "studio frame prompt",
        "negative_prompt": "studio additional negative",
        "studio_request": True,
        "_remote_queue_source": "Studio",
    }
    bridge._pending_generate_requests.append({
        "ws": None,
        "prompt": "should not touch main prompt",
        "negative": "should not touch preset negative",
        "overrides": overrides,
    })

    bridge._do_generate()

    assert prompt_edit.toPlainText() == "main prompt"
    assert negative_edit.toPlainText() == "preset negative"
    assert prompt_edit.set_calls == []
    assert negative_edit.set_calls == []
    assert generation_controller.executed == [(overrides, 0)]


def test_studio_generate_overrides_are_preserved_when_queued():
    bridge, generation_controller, prompt_edit, negative_edit = _bridge_with_generate_context(is_generating=True)
    overrides = {
        "input": "queued studio frame",
        "negative_prompt": "queued studio negative",
        "studio_request": True,
        "_remote_queue_source": "Studio",
    }
    bridge._pending_generate_requests.append({
        "ws": None,
        "prompt": "should not touch main prompt",
        "negative": "should not touch preset negative",
        "overrides": overrides,
    })

    bridge._do_generate()

    assert prompt_edit.toPlainText() == "main prompt"
    assert negative_edit.toPlainText() == "preset negative"
    assert generation_controller.executed == []
    assert generation_controller.enqueued == [(overrides, 0)]


def test_web_generate_overrides_do_not_mutate_main_prompt_fields():
    bridge, generation_controller, prompt_edit, negative_edit = _bridge_with_generate_context()
    overrides = {
        "input": "web session prompt",
        "negative_prompt": "web session negative",
        "model": "web-local-model",
        "steps": 31,
        "_remote_queue_source": "Web",
    }
    bridge._pending_generate_requests.append({
        "ws": None,
        "prompt": "legacy prompt field",
        "negative": "legacy negative field",
        "overrides": overrides,
    })

    bridge._do_generate()

    assert prompt_edit.toPlainText() == "main prompt"
    assert negative_edit.toPlainText() == "preset negative"
    assert prompt_edit.set_calls == []
    assert negative_edit.set_calls == []
    assert generation_controller.executed == [(overrides, 0)]


def test_web_generate_missing_custom_workflow_fails_before_starting():
    bridge, generation_controller, prompt_edit, negative_edit = _bridge_with_generate_context()
    bridge.app_context.get_api_mode = lambda: "COMFYUI"
    sent = []
    bridge._send_json_to = lambda ws, data: sent.append(data)
    overrides = {
        "input": "web session prompt",
        "negative_prompt": "web session negative",
        "_comfyui_workflow_mode": "custom",
        "_remote_queue_source": "Web",
    }
    bridge._pending_generate_requests.append({
        "ws": _ws("127.0.0.1"),
        "prompt": "legacy prompt field",
        "negative": "legacy negative field",
        "overrides": overrides,
    })

    bridge._do_generate()

    assert prompt_edit.toPlainText() == "main prompt"
    assert negative_edit.toPlainText() == "preset negative"
    assert generation_controller.executed == []
    assert sent == [{
        "type": "toast",
        "message": "ComfyUI custom workflow is no longer loaded on the server.",
        "level": "error",
    }]


def test_generation_param_schema_strips_desktop_selected_values():
    params = {
        "type": "params",
        "api_mode": "NAI",
        "model": "desktop-model",
        "sampler": "desktop-sampler",
        "scheduler": "desktop-scheduler",
        "resolution": "832x1216",
        "steps": 28,
        "cfg_scale": 5.0,
        "cfg_rescale": 0.4,
        "seed": "1234",
        "seed_fixed": True,
        "random_resolution": True,
        "auto_fit_resolution": True,
        "SMEA": True,
        "comfyui_workflow": {"has_custom": True, "workflow_label": "Desktop Workflow"},
        "comfyui_workflow_has_custom": True,
        "comfyui_workflow_label": "Desktop Workflow",
        "options_model": ["desktop-model", "other-model"],
        "options_sampler": ["desktop-sampler"],
        "steps_range": [1, 50],
    }

    schema = RemoteBridge._strip_generation_param_values(params)

    assert schema == {
        "type": "params",
        "api_mode": "NAI",
        "options_model": ["desktop-model", "other-model"],
        "options_sampler": ["desktop-sampler"],
        "steps_range": [1, 50],
        "schema_only": True,
    }


def test_refresh_cache_does_not_replay_desktop_control_state():
    bridge = RemoteBridge(_AppContext())
    schema = {"type": "params", "api_mode": "NAI", "schema_only": True}
    bridge.get_current_prompts = lambda: {"type": "prompt_sync", "prompt": "desktop prompt"}
    bridge.get_options = lambda: {"prompt_fixed": True}
    bridge.get_generation_param_schema = lambda: schema
    bridge._result_enhance_config_payload = lambda: {"type": "result_enhance_config", "strength": 0.7}
    bridge._has_clients = lambda: True
    broadcasts = []
    bridge._broadcast_json = broadcasts.append

    bridge._do_refresh_cache()

    assert bridge._cached_prompts == {}
    assert bridge._cached_options == {}
    assert bridge._cached_params == schema
    assert bridge._cached_result_enhance_config == {}
    assert broadcasts == [schema]


def test_desktop_control_state_hooks_do_not_broadcast():
    bridge = RemoteBridge(_AppContext())
    schema = {"type": "params", "api_mode": "COMFYUI", "schema_only": True}
    bridge.get_generation_param_schema = lambda: schema
    bridge._has_clients = lambda: True
    broadcasts = []
    bridge._broadcast_json = broadcasts.append

    bridge._on_prompt_text_changed()
    bridge._on_option_toggled_slot(True)
    bridge._on_param_changed_slot()
    bridge._on_params_changed()
    bridge.on_result_enhance_config_changed()
    bridge._on_auto_save_settings_changed()
    bridge.on_save_directory_changed({})
    bridge.on_comfyui_workflow_changed({})

    assert bridge._cached_prompts == {}
    assert bridge._cached_options == {}
    assert bridge._cached_params == schema
    assert bridge._cached_result_enhance_config == {}
    assert broadcasts == []


def test_result_enhance_config_update_is_session_only():
    image_window = SimpleNamespace(
        auto_save_checkbox=object(),
        _enhance_upscale=1.5,
        _enhance_strength=0.2,
        _enhance_noise=0.0,
    )
    ctx = _AppContext()
    ctx.main_window = SimpleNamespace(image_window=image_window)
    bridge = RemoteBridge(ctx)
    sent = []
    bridge._send_json_to = lambda ws, data: sent.append(data)

    bridge._do_set_result_enhance_config(
        ws=_ws("127.0.0.1"),
        payload_json=json.dumps({"upscale": 1.0, "strength": 0.7, "noise": 0.1}),
    )

    assert image_window._enhance_upscale == 1.5
    assert image_window._enhance_strength == 0.2
    assert image_window._enhance_noise == 0.0
    assert sent[0] == {
        "type": "result_enhance_config",
        "upscale": 1.0,
        "strength": 0.7,
        "noise": 0.1,
        "_session_echo": True,
    }


def test_result_enhance_request_payload_overrides_desktop_config():
    image = Image.new("RGB", (64, 64), "white")
    item = SimpleNamespace(
        image=image,
        generation_params={"input": "1girl", "negative_prompt": "", "seed": 123},
    )
    image_window = SimpleNamespace(
        auto_save_checkbox=object(),
        current_history_item=item,
        _enhance_upscale=1.0,
        _enhance_strength=0.9,
        _enhance_noise=0.0,
    )
    ctx = _AppContext()
    ctx.main_window = SimpleNamespace(image_window=image_window)
    bridge = RemoteBridge(ctx)

    context = bridge._prepare_result_enhance_context({
        "upscale": 1.5,
        "strength": 0.4,
        "noise": 0.1,
    })

    assert context["upscale"] == 1.5
    assert context["strength"] == 0.4
    assert context["noise"] == 0.1
    assert context["new_w"] == 128
    assert context["new_h"] == 128
    assert context["params"]["strength"] == 0.4
    assert context["params"]["noise"] == 0.1


def _comfy_generation_params(**overrides):
    params = {
        "input": "1girl",
        "negative_prompt": "",
        "model": "model.safetensors",
        "seed": 1,
        "steps": 20,
        "cfg_scale": 5.0,
        "sampler": "euler",
        "scheduler": "normal",
        "width": 512,
        "height": 512,
        "workflow_type": "checkpoint",
        "sampling_mode": "eps",
    }
    params.update(overrides)
    return params


def test_comfyui_basic_workflow_mode_ignores_global_custom_workflow():
    manager = ComfyUIWorkflowManager()
    manager.user_workflow = {"invalid": {"class_type": "Invalid", "inputs": {}}}
    manager.user_workflow_node_map = {"positive_prompt": "missing"}

    workflow = manager.apply_params_to_workflow(_comfy_generation_params(_comfyui_workflow_mode="basic"))

    assert workflow is not None


def test_comfyui_custom_workflow_mode_requires_loaded_custom_workflow():
    manager = ComfyUIWorkflowManager()

    workflow = manager.apply_params_to_workflow(_comfy_generation_params(_comfyui_workflow_mode="custom"))

    assert workflow is None


def test_comfyui_workflow_upload_and_default_endpoints_load_png_metadata():
    ctx = _ComfyWorkflowContext()
    bridge = RemoteBridge(ctx)

    async def run_workflow_action(action, metadata=None, timeout=30.0):
        if action == "load":
            return bridge._load_comfyui_workflow_from_metadata(metadata or {})
        if action == "clear":
            return bridge._clear_comfyui_workflow()
        return {"ok": False, "error": "Unsupported ComfyUI workflow action"}

    bridge._request_comfyui_workflow_action = run_workflow_action
    client = TestClient(create_app(bridge, WebSocketManager()))

    upload = client.post(
        "/api/comfyui/workflow/upload",
        content=_comfyui_workflow_png_bytes(),
        headers={"content-type": "image/png"},
    )

    assert upload.status_code == 200
    data = upload.json()
    assert data["ok"] is True
    assert data["workflow"]["has_custom"] is True
    assert data["workflow"]["workflow_label"] == "Custom Workflow"
    assert ctx.comfyui_workflow_manager.user_workflow is not None
    assert ctx.main_window.workflow_custom_btn.enabled is True
    assert ctx.main_window.workflow_custom_btn.checked is True

    reset = client.post("/api/comfyui/workflow/default")

    assert reset.status_code == 200
    reset_data = reset.json()
    assert reset_data["workflow"]["has_custom"] is False
    assert reset_data["workflow"]["workflow_label"] == "Basic Workflow"
    assert ctx.comfyui_workflow_manager.user_workflow is None
    assert ctx.main_window.workflow_default_btn.checked is True
    assert ctx.main_window.workflow_custom_btn.enabled is False


def test_comfyui_workflow_upload_rejects_png_without_workflow_metadata():
    ctx = _ComfyWorkflowContext()
    bridge = RemoteBridge(ctx)
    client = TestClient(create_app(bridge, WebSocketManager()))
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), "white").save(buffer, format="PNG")

    response = client.post(
        "/api/comfyui/workflow/upload",
        content=buffer.getvalue(),
        headers={"content-type": "image/png"},
    )

    assert response.status_code == 400
    assert response.json()["ok"] is False
    assert ctx.comfyui_workflow_manager.user_workflow is None


def test_comfyui_web_endpoint_redirects_to_configured_url():
    ctx = _ComfyWorkflowContext()
    ctx.secure_token_manager = _TokenManager({"comfyui_url": "127.0.0.1:8188"})
    bridge = RemoteBridge(ctx)
    client = TestClient(create_app(bridge, WebSocketManager()))

    response = client.get("/api/comfyui/web", follow_redirects=False)

    assert response.status_code in (307, 308)
    assert response.headers["location"] == "http://127.0.0.1:8188"


class _ImageCrud:
    def __init__(self, save_dir):
        self._save_dir = save_dir
        self._use_timestamp_folder = True

    def get_save_directory(self):
        return self._save_dir

    def get_use_timestamp_folder(self):
        return self._use_timestamp_folder


def _bridge_with_history(tmp_path, mode="NAI"):
    old_save_dir = tmp_path / "old_output" / "20260501_120000"
    new_save_dir = tmp_path / "new_output" / "20260501_120000"
    old_save_dir.mkdir(parents=True)
    new_save_dir.mkdir(parents=True)
    image_path = old_save_dir / "00001.png"
    image_path.write_bytes(b"fake-png")

    item = SimpleNamespace(
        filepath=str(image_path),
        image=object(),
        generation_params={"input": "1girl"},
        prompt_context={},
        source_row=None,
    )
    image_window = SimpleNamespace(
        auto_save_checkbox=object(),
        image_history_window=SimpleNamespace(
            history_widgets=[SimpleNamespace(history_item=item)]
        ),
        current_history_item=item,
    )
    ctx = _AppContext()
    ctx.get_api_mode = lambda: mode
    ctx.image_crud_controller = _ImageCrud(new_save_dir)
    ctx.main_window = SimpleNamespace(image_window=image_window)
    bridge = RemoteBridge(ctx)
    return bridge, image_path


def test_memory_history_uses_stable_path_when_save_directory_changes(tmp_path):
    bridge, image_path = _bridge_with_history(tmp_path)

    entries = bridge._scan_memory_history()

    assert len(entries) == 1
    history_key = entries[0]["rel_path"]
    assert history_key.startswith(RemoteBridge.MEMORY_HISTORY_PATH_PREFIX)
    assert bridge._validate_viewer_path(history_key) == image_path.resolve()


def test_stale_relative_history_path_resolves_from_memory_history(tmp_path):
    bridge, image_path = _bridge_with_history(tmp_path)

    assert bridge._validate_viewer_path("00001.png") == image_path.resolve()


def test_saved_result_asset_accepts_memory_history_key(tmp_path):
    bridge, image_path = _bridge_with_history(tmp_path)
    history_key = bridge._scan_memory_history()[0]["rel_path"]

    asset = bridge._build_saved_result_asset_payload(history_key)

    assert asset["path"] == history_key
    assert asset["file_path"] == str(image_path.resolve())
    assert asset["capabilities"]["image_action"] is True
    assert asset["capabilities"]["enhance"] is True
    assert asset["capabilities"]["copy_png"] is True
    assert "copy_webp" not in asset["capabilities"]


def test_current_result_asset_does_not_advertise_webp_clipboard_copy(tmp_path):
    bridge, _image_path = _bridge_with_history(tmp_path)

    asset = bridge._build_current_result_asset_payload()

    assert asset["capabilities"]["copy_png"] is True
    assert asset["capabilities"]["image_action"] is True
    assert asset["capabilities"]["inpaint"] is True
    assert asset["capabilities"]["enhance"] is True
    assert "copy_webp" not in asset["capabilities"]


def test_current_result_asset_blocks_nai_image_actions_outside_nai_mode(tmp_path):
    bridge, _image_path = _bridge_with_history(tmp_path, mode="COMFYUI")

    asset = bridge._build_current_result_asset_payload()

    assert asset["can_enhance"] is False
    assert asset["capabilities"]["image_action"] is False
    assert asset["capabilities"]["inpaint"] is False
    assert asset["capabilities"]["enhance"] is False
    assert asset["capabilities"]["upscale_nai"] is False


def test_saved_result_asset_blocks_nai_image_actions_outside_nai_mode(tmp_path):
    bridge, _image_path = _bridge_with_history(tmp_path, mode="WEBUI")
    history_key = bridge._scan_memory_history()[0]["rel_path"]

    asset = bridge._build_saved_result_asset_payload(history_key)

    assert asset["can_enhance"] is False
    assert asset["capabilities"]["image_action"] is False
    assert asset["capabilities"]["enhance"] is False
    assert asset["capabilities"]["upscale_nai"] is False


def test_result_image_action_rejects_desktop_img2img_outside_nai_mode():
    ctx = _AppContext()
    ctx.get_api_mode = lambda: "COMFYUI"
    bridge = RemoteBridge(ctx)
    broadcasts = []
    bridge._broadcast_json = broadcasts.append

    bridge._do_result_image_action(json.dumps({"action": "img2img", "source": "current"}))

    assert broadcasts == [{
        "type": "toast",
        "message": "Img2Img/Inpaint is available in NAI mode only",
        "level": "error",
    }]


def test_desktop_img2img_surface_rejects_non_nai_mode_before_manager_lookup():
    ctx = _AppContext()
    ctx.get_api_mode = lambda: "WEBUI"
    bridge = RemoteBridge(ctx)

    with pytest.raises(RuntimeError, match="NAI mode only"):
        bridge._open_desktop_img2img_surface(Image.new("RGB", (2, 2), "white"))


def test_original_result_file_prefers_memory_history_path(tmp_path):
    bridge, image_path = _bridge_with_history(tmp_path)
    history_key = bridge._scan_memory_history()[0]["rel_path"]

    target = bridge._resolve_result_original_file("current", history_key)

    assert target == image_path.resolve()
    assert bridge._image_media_type_for_path(target) == "image/png"


def test_png_payload_uses_path_even_for_current_source(tmp_path):
    bridge, image_path = _bridge_with_history(tmp_path)
    history_key = bridge._scan_memory_history()[0]["rel_path"]

    payload, filename = bridge._build_result_png_payload("current", history_key)

    assert payload == image_path.read_bytes()
    assert filename == "00001.png"


def test_png_payload_preserves_saved_png_metadata_bytes(tmp_path):
    bridge, image_path = _bridge_with_history(tmp_path)
    png_info = PngInfo()
    png_info.add_text("Comment", "naia-metadata-marker")
    Image.new("RGB", (2, 2), "white").save(image_path, pnginfo=png_info)
    original_bytes = image_path.read_bytes()
    history_key = bridge._scan_memory_history()[0]["rel_path"]

    payload, filename = bridge._build_result_png_payload("saved", history_key)

    assert b"naia-metadata-marker" in original_bytes
    assert payload == original_bytes
    assert filename == "00001.png"


def test_thumbnail_cache_is_not_created_inside_user_save_directory(tmp_path):
    bridge, image_path = _bridge_with_history(tmp_path)
    Image.new("RGB", (64, 96), "white").save(image_path)
    save_dir = bridge._get_viewer_save_dir().resolve()

    thumb_path = bridge._thumbnail_cache_path(image_path, 128)
    thumb_bytes = bridge._get_or_create_thumbnail(image_path, 128)

    assert thumb_bytes
    assert ".thumbnails" not in thumb_path.parts
    assert not thumb_path.resolve().is_relative_to(save_dir)
    assert not (save_dir / ".thumbnails").exists()


def _bridge_with_style_thumbs(tmp_path):
    meta_path = tmp_path / "style_meta_tags.json"
    thumb_path = tmp_path / "style_thumbnails.json"
    meta_path.write_text(
        json.dumps({
            "categories": {
                "medium": {
                    "name": "Medium",
                    "description": "Medium tags",
                    "tags": ["ink (medium)", "missing style"],
                },
                "color": {
                    "name": "Color",
                    "description": "Color tags",
                    "tags": ["blue palette"],
                },
            }
        }),
        encoding="utf-8",
    )
    thumb_path.write_text(
        json.dumps({
            "ink (medium)": base64.b64encode(b"\xff\xd8jpeg-bytes").decode("ascii"),
            "blue palette": base64.b64encode(b"\x89PNG\r\n\x1a\npng-bytes").decode("ascii"),
        }),
        encoding="utf-8",
    )
    bridge = RemoteBridge(_AppContext())
    bridge.STYLE_META_TAGS_PATH = meta_path
    bridge.STYLE_THUMBNAILS_PATH = thumb_path
    return bridge


def test_thumb_state_reports_available_style_categories(tmp_path):
    bridge = _bridge_with_style_thumbs(tmp_path)

    state = bridge._build_thumb_tab_state()

    assert state["selected"] == "medium"
    assert state["total_available"] == 2
    assert state["categories"][0]["key"] == "medium"
    assert state["categories"][0]["total"] == 2
    assert state["categories"][0]["available"] == 1


def test_thumb_category_payload_filters_missing_thumbnails(tmp_path):
    bridge = _bridge_with_style_thumbs(tmp_path)

    payload = bridge._build_thumb_category_payload("medium")

    assert payload["name"] == "Medium"
    assert [item["tag"] for item in payload["tags"]] == ["ink (medium)"]
    assert payload["tags"][0]["image_url"] == "/api/thumb/image?tag=ink%20%28medium%29"


def test_thumb_image_endpoint_returns_decoded_thumbnail(tmp_path):
    bridge = _bridge_with_style_thumbs(tmp_path)
    client = TestClient(create_app(bridge, WebSocketManager()))

    response = client.get("/api/thumb/image", params={"tag": "blue palette"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.content == b"\x89PNG\r\n\x1a\npng-bytes"


def test_original_endpoint_does_not_fallback_for_invalid_saved_path(tmp_path):
    bridge, _image_path = _bridge_with_history(tmp_path)
    bridge.latest_webp = b"latest-webp"
    client = TestClient(create_app(bridge, WebSocketManager()))

    response = client.get(
        "/api/result/image/original",
        params={"source": "saved", "path": "missing.png"},
    )

    assert response.status_code == 404


def test_clipboard_png_endpoint_uses_saved_path_payload(tmp_path):
    bridge, image_path = _bridge_with_history(tmp_path)
    history_key = bridge._scan_memory_history()[0]["rel_path"]
    client = TestClient(create_app(bridge, WebSocketManager()))

    response = client.post(
        "/api/result/clipboard/png",
        json={"source": "saved", "path": history_key},
    )

    assert response.status_code == 200
    assert response.json()["filename"] == "00001.png"
    assert response.json()["bytes"] == len(image_path.read_bytes())


def test_original_endpoint_falls_back_for_current_without_path():
    bridge = RemoteBridge(_AppContext())
    bridge.latest_webp = b"latest-webp"
    client = TestClient(create_app(bridge, WebSocketManager()))

    response = client.get("/api/result/image/original", params={"source": "current"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/webp")
    assert response.content == b"latest-webp"
