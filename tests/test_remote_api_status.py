import asyncio
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


class _FakeCheckBox:
    def __init__(self, checked=False):
        self.checked = checked

    def isChecked(self):
        return self.checked

    def setChecked(self, checked):
        self.checked = checked


class _FakeVibeFrame:
    def __init__(
        self,
        encodings=None,
        reference_strength=0.6,
        information_extracted=1.0,
        is_enabled=True,
        target_model="NAID4.5F",
    ):
        self.vibe_encodings = encodings or {1.0: "encoded"}
        self.reference_strength = reference_strength
        self.information_extracted = information_extracted
        self.is_enabled = is_enabled
        self.is_no_image = True
        self.target_model = target_model
        self.enable_check = _FakeCheckBox(is_enabled)


class _FakeVibeModule:
    def __init__(self, frames=None):
        self.vibe_frames = frames or []
        self.normalize_checkbox = _FakeCheckBox(False)
        self.added = []
        self.removed = []

    def _get_current_model(self):
        return "NAID4.5F"

    def _remove_frame(self, frame):
        self.removed.append(frame)
        if frame in self.vibe_frames:
            self.vibe_frames.remove(frame)

    def _add_vibe_frame_from_metadata(self, no_image_path, vibe_data):
        encodings = {
            float(key): value
            for key, value in zip(
                vibe_data["reference_information_extracted_multiple"],
                vibe_data["reference_image_multiple"],
            )
        }
        frame = _FakeVibeFrame(
            encodings=encodings,
            reference_strength=vibe_data["reference_strength_multiple"][0],
            target_model=vibe_data["source_model"],
        )
        frame.no_image_path = no_image_path
        self.vibe_frames.append(frame)
        self.added.append(frame)
        return frame

    def _set_frame_information_extracted(self, frame, value):
        frame.information_extracted = float(value)
        return True

    def _set_frame_reference_strength(self, frame, value):
        frame.reference_strength = float(value)
        return True


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


def test_vibe_cluster_save_and_scan_persists_current_encoded_frames(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bridge = RemoteBridge(_AppContext())
    broadcasts = []
    bridge._broadcast_json = broadcasts.append
    module = _FakeVibeModule([
        _FakeVibeFrame({1.0: "encoded-a", 0.5: "encoded-a-half"}, 0.21, 1.0, True),
        _FakeVibeFrame({0.6: "encoded-b"}, 0.17, 0.6, False),
    ])

    saved = bridge._save_current_vibe_cluster(
        module,
        json.dumps({"name": "TestCluster", "description": "desc"}),
    )

    assert saved is True
    listing = bridge._scan_vibe_clusters()
    assert listing["module_id"] == "vibe_cluster"
    assert len(listing["items"]) == 1
    item = listing["items"][0]
    assert item["name"] == "TestCluster"
    assert item["frame_count"] == 2
    assert item["enabled_count"] == 1

    storage_json = tmp_path / "save" / "vibe_transfer_clusters" / f"{item['id']}.json"
    data = json.loads(storage_json.read_text(encoding="utf-8"))
    assert data["description"] == "desc"
    assert data["frames"][0]["encodings"] == {"1.0": "encoded-a", "0.5": "encoded-a-half"}
    assert data["frames"][1]["reference_strength"] == 0.17


def test_vibe_cluster_save_rejects_invalid_names(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bridge = RemoteBridge(_AppContext())
    broadcasts = []
    bridge._broadcast_json = broadcasts.append
    module = _FakeVibeModule([_FakeVibeFrame({1.0: "encoded-a"}, 0.21, 1.0, True)])

    saved = bridge._save_current_vibe_cluster(
        module,
        json.dumps({"name": "Bad Cluster!", "description": "desc"}),
    )

    assert saved is False
    assert broadcasts[-1]["level"] == "error"
    assert not list((tmp_path / "save" / "vibe_transfer_clusters").glob("*.json"))


def test_vibe_cluster_autocomplete_search_returns_vibe_prompt_token(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bridge = RemoteBridge(_AppContext())
    bridge._broadcast_json = lambda payload: None
    module = _FakeVibeModule([_FakeVibeFrame({1.0: "encoded-a"}, 0.21, 1.0, True)])
    assert bridge._save_current_vibe_cluster(module, json.dumps({"name": "SearchableVibe"}))

    results = bridge._search_vibe_clusters("search")

    assert len(results) == 1
    assert results[0]["tag"] == "SearchableVibe"
    assert results[0]["value"] == "vibe:SearchableVibe"
    assert results[0]["_wc_type"] == "vibe_cluster"


def test_vibe_cluster_load_clean_recreates_no_image_frames(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bridge = RemoteBridge(_AppContext())
    bridge._broadcast_json = lambda payload: None
    bridge._disable_all_char_ref_frames = lambda: None
    source = _FakeVibeModule([
        _FakeVibeFrame({1.0: "encoded-a", 0.5: "encoded-a-half"}, 0.21, 0.5, True),
    ])
    assert bridge._save_current_vibe_cluster(source, json.dumps({"name": "LoadMe"}))
    cluster_id = bridge._scan_vibe_clusters()["items"][0]["id"]

    existing = _FakeVibeFrame({1.0: "old"}, 0.9, 1.0, True)
    target = _FakeVibeModule([existing])
    loaded = bridge._load_vibe_cluster(target, json.dumps({"id": cluster_id, "mode": "clean"}))

    assert loaded == 1
    assert target.removed == [existing]
    assert len(target.vibe_frames) == 1
    frame = target.vibe_frames[0]
    assert frame.vibe_encodings == {0.5: "encoded-a-half", 1.0: "encoded-a"}
    assert frame.reference_strength == 0.21
    assert frame.information_extracted == 0.5
    assert frame.is_enabled is True


def test_vibe_storage_scan_skips_no_image_and_missing_thumbnails(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    model_dir = tmp_path / "save" / "vibe_transfer" / "NAID4.5F"
    image_dir = model_dir / "images"
    image_dir.mkdir(parents=True)

    good_hash = "goodthumb1234567"
    Image.new("RGB", (64, 64), "white").save(image_dir / f"{good_hash}.png")
    (model_dir / f"{good_hash}.json").write_text(json.dumps({
        "file_hash": good_hash,
        "file_name": "good.png",
        "encodings": {"1.0": "encoded-good"},
    }), encoding="utf-8")
    (model_dir / "metadataonly1234.json").write_text(json.dumps({
        "file_hash": "metadataonly1234",
        "file_name": "metadata_vibe_metadataonly1234",
        "storage_type": "metadata_vibe",
        "is_no_image": True,
        "encodings": {"1.0": "encoded-no-image"},
    }), encoding="utf-8")
    (model_dir / "missingthumb1234.json").write_text(json.dumps({
        "file_hash": "missingthumb1234",
        "file_name": "missing.png",
        "encodings": {"1.0": "encoded-missing"},
    }), encoding="utf-8")

    listing = RemoteBridge(_AppContext())._scan_vibe_storage()

    items = listing["models"]["NAID4.5F"]
    assert [item["file_hash"] for item in items] == [good_hash]
    assert items[0]["thumbnail"]


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


class _ResolutionCombo:
    def __init__(self, items):
        self.items = list(items)

    def count(self):
        return len(self.items)

    def itemText(self, index):
        return self.items[index]


class _ToggleButton:
    def __init__(self, checked=False, enabled=True):
        self.checked = checked
        self.enabled = enabled

    def setChecked(self, value):
        self.checked = bool(value)

    def isChecked(self):
        return self.checked

    def setEnabled(self, value):
        self.enabled = bool(value)


class _ImmediateLoop:
    def call_soon_threadsafe(self, fn, *args):
        fn(*args)


class _DoneFuture:
    def __init__(self):
        self.value = None
        self.exception = None
        self._done = False

    def done(self):
        return self._done

    def set_result(self, value):
        self.value = value
        self._done = True

    def set_exception(self, exception):
        self.exception = exception
        self._done = True


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


def test_desktop_snapshot_builds_full_params_and_forced_prompts():
    bridge = RemoteBridge(_AppContext())
    bridge.get_generation_params = lambda: {
        "type": "params",
        "api_mode": "NAI",
        "model": "desktop-model",
        "options_model": ["desktop-model"],
    }
    bridge.get_current_prompts = lambda: {
        "type": "prompt_sync",
        "prompt": "desktop prompt",
        "negative_prompt": "desktop negative",
    }

    payloads = bridge._desktop_control_snapshot_payloads("initial")

    assert payloads == [
        {
            "type": "params",
            "api_mode": "NAI",
            "model": "desktop-model",
            "options_model": ["desktop-model"],
            "desktop_sync": True,
            "sync_reason": "initial",
        },
        {
            "type": "prompt_sync",
            "prompt": "desktop prompt",
            "negative_prompt": "desktop negative",
            "desktop_sync": True,
            "sync_reason": "initial",
            "force": True,
        },
    ]


def test_desktop_snapshot_ws_send_is_ordered_before_followup_messages():
    class _FakeWs:
        def __init__(self):
            self.sent = []

        async def send_text(self, text):
            self.sent.append(json.loads(text))

    async def _run():
        bridge = RemoteBridge(_AppContext())
        bridge.get_generation_params = lambda: {
            "type": "params",
            "api_mode": "NAI",
            "model": "desktop-model",
        }
        bridge.get_current_prompts = lambda: {
            "type": "prompt_sync",
            "prompt": "desktop prompt",
            "negative_prompt": "desktop negative",
        }
        bridge.request_send_desktop_sync.connect(bridge._do_send_desktop_control_snapshot)
        ws = _FakeWs()

        await bridge.send_desktop_control_snapshot_to_ws(ws, "initial")
        await ws.send_text(json.dumps({"type": "init_complete"}))

        assert ws.sent == [
            {
                "type": "params",
                "api_mode": "NAI",
                "model": "desktop-model",
                "desktop_sync": True,
                "sync_reason": "initial",
            },
            {
                "type": "prompt_sync",
                "prompt": "desktop prompt",
                "negative_prompt": "desktop negative",
                "desktop_sync": True,
                "sync_reason": "initial",
                "force": True,
            },
            {"type": "init_complete"},
        ]

    asyncio.run(_run())


def test_mode_change_broadcasts_schema_then_desktop_snapshot(monkeypatch):
    import core.remote_api_server as remote_api_server

    bridge = RemoteBridge(_AppContext())
    schema = {"type": "params", "api_mode": "WEBUI", "schema_only": True}
    full_params = {
        "type": "params",
        "api_mode": "WEBUI",
        "model": "desktop-webui-model",
        "options_model": ["desktop-webui-model"],
    }
    prompt_payload = {
        "type": "prompt_sync",
        "prompt": "webui preset prompt",
        "negative_prompt": "webui preset negative",
    }
    bridge.get_generation_param_schema = lambda: schema
    bridge.get_generation_params = lambda: full_params
    bridge.get_current_prompts = lambda: prompt_payload
    bridge._has_clients = lambda: True
    broadcasts = []
    bridge._broadcast_json = broadcasts.append
    monkeypatch.setattr(remote_api_server.QTimer, "singleShot", lambda _ms, callback: callback())

    bridge.on_api_mode_changed({"new_mode": "WEBUI"})

    assert broadcasts == [
        {"type": "mode", "mode": "WEBUI"},
        schema,
        {**full_params, "desktop_sync": True, "sync_reason": "mode_changed"},
        {**prompt_payload, "desktop_sync": True, "sync_reason": "mode_changed", "force": True},
    ]


def test_prompt_preset_loaded_broadcasts_desktop_snapshot(monkeypatch):
    import core.remote_api_server as remote_api_server

    bridge = RemoteBridge(_AppContext())
    full_params = {
        "type": "params",
        "api_mode": "NAI",
        "model": "preset-model",
        "steps": 28,
    }
    prompt_payload = {
        "type": "prompt_sync",
        "prompt": "preset prompt",
        "negative_prompt": "preset negative",
    }
    bridge.get_generation_params = lambda: full_params
    bridge.get_current_prompts = lambda: prompt_payload
    bridge._has_clients = lambda: True
    broadcasts = []
    bridge._broadcast_json = broadcasts.append
    monkeypatch.setattr(remote_api_server.QTimer, "singleShot", lambda _ms, callback: callback())

    bridge.on_prompt_preset_loaded({"preset_name": "default", "reason": "preset_loaded"})

    assert broadcasts == [
        {**full_params, "desktop_sync": True, "sync_reason": "preset_loaded"},
        {**prompt_payload, "desktop_sync": True, "sync_reason": "preset_loaded", "force": True},
    ]


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


def _bridge_with_artist_thumb_lists(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("artist_thumb").mkdir()
    Path("wildcards").mkdir()
    Path("artist_thumb/banned_artist.txt").write_text("b\nmissing\n", encoding="utf-8")
    Path("artist_thumb/group.txt").write_text("a\nb\nc\nmissing\n", encoding="utf-8")
    Path("wildcards/favorite_artist.txt").write_text("a\nb\n", encoding="utf-8")

    bridge = RemoteBridge(_AppContext())
    bridge._artist_thumb_artist_weights = lambda: {
        "a": 10,
        "b": 9,
        "c": 8,
        "d": 7,
        "e": 6,
    }
    bridge._load_artist_thumb_data = lambda mode: {
        "a": ["thumb"],
        "b": ["thumb"],
        "c": ["thumb"],
        "d": ["thumb"],
        "e": ["thumb"],
    }
    return bridge


def test_artist_thumb_state_migrates_legacy_files_to_json(tmp_path, monkeypatch):
    bridge = _bridge_with_artist_thumb_lists(tmp_path, monkeypatch)

    state_path = Path("artist_thumb/artist_state.json")
    assert state_path.exists()
    data = json.loads(state_path.read_text(encoding="utf-8"))

    assert data["version"] == 1
    assert data["favorites"] == ["a", "b"]
    assert data["banned"] == ["b", "missing"]
    assert bridge._artist_thumb_favorites() == ["a", "b"]
    assert bridge._artist_thumb_banned() == ["b", "missing"]


def test_artist_thumb_state_reads_legacy_additions_without_mirror_write(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("artist_thumb").mkdir()
    Path("wildcards").mkdir()
    Path("artist_thumb/artist_state.json").write_text(
        json.dumps({"version": 1, "favorites": ["c"], "banned": ["d"]}, ensure_ascii=False),
        encoding="utf-8",
    )
    Path("artist_thumb/banned_artist.txt").write_text("b\n", encoding="utf-8")
    Path("wildcards/favorite_artist.txt").write_text("a\n", encoding="utf-8")

    bridge = RemoteBridge(_AppContext())

    assert bridge._artist_thumb_favorites() == ["c", "a"]
    assert bridge._artist_thumb_banned() == ["d", "b"]
    assert Path("wildcards/favorite_artist.txt").read_text(encoding="utf-8") == "a\n"
    assert Path("artist_thumb/banned_artist.txt").read_text(encoding="utf-8") == "b\n"


def test_artist_thumb_state_updates_json_and_text_mirrors(tmp_path, monkeypatch):
    bridge = _bridge_with_artist_thumb_lists(tmp_path, monkeypatch)

    bridge._set_artist_thumb_favorite("c", True)
    data = json.loads(Path("artist_thumb/artist_state.json").read_text(encoding="utf-8"))
    assert data["favorites"] == ["a", "b", "c"]
    assert Path("wildcards/favorite_artist.txt").read_text(encoding="utf-8") == "a\nb\nc\n"

    bridge._set_artist_thumb_banned("a", True)
    data = json.loads(Path("artist_thumb/artist_state.json").read_text(encoding="utf-8"))
    assert data["favorites"] == ["b", "c"]
    assert data["banned"] == ["b", "missing", "a"]
    assert Path("wildcards/favorite_artist.txt").read_text(encoding="utf-8") == "b\nc\n"
    assert Path("artist_thumb/banned_artist.txt").read_text(encoding="utf-8") == "b\nmissing\na\n"


def test_artist_thumb_state_write_preserves_legacy_additions(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("artist_thumb").mkdir()
    Path("wildcards").mkdir()
    Path("artist_thumb/artist_state.json").write_text(
        json.dumps({"version": 1, "favorites": ["c"], "banned": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    Path("wildcards/favorite_artist.txt").write_text("a\n", encoding="utf-8")

    bridge = RemoteBridge(_AppContext())
    bridge._set_artist_thumb_favorite("d", True)

    data = json.loads(Path("artist_thumb/artist_state.json").read_text(encoding="utf-8"))
    assert data["favorites"] == ["c", "a", "d"]
    assert Path("wildcards/favorite_artist.txt").read_text(encoding="utf-8") == "c\na\nd\n"


def test_artist_thumb_state_rejects_corrupt_json_without_legacy_overwrite(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("artist_thumb").mkdir()
    Path("wildcards").mkdir()
    Path("artist_thumb/artist_state.json").write_text("{", encoding="utf-8")
    Path("wildcards/favorite_artist.txt").write_text("a\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="artist thumb state JSON is invalid"):
        RemoteBridge(_AppContext())

    assert Path("artist_thumb/artist_state.json").read_text(encoding="utf-8") == "{"
    assert Path("wildcards/favorite_artist.txt").read_text(encoding="utf-8") == "a\n"


def test_artist_thumb_random_resolution_filters_unsafe_nai_sizes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bridge = RemoteBridge(_AppContext())
    bridge.app_context.main_window = SimpleNamespace(
        resolution_combo=_ResolutionCombo([
            "2048 x 2048",
            "3072 x 4096",
            "1536 x 2048",
            "832 x 1216",
        ])
    )

    assert bridge._artist_thumb_resolution_options() == [(832, 1216)]
    assert bridge._coerce_artist_thumb_resolution(4096, 4096) == (1024, 1024)
    assert bridge._coerce_artist_thumb_resolution(1000, 1000) == (1024, 1024)
    assert bridge._coerce_artist_thumb_resolution(4096, 6144) == (832, 1216)
    assert bridge._coerce_artist_thumb_resolution(1536, 2048) == (832, 1152)
    assert bridge._coerce_artist_thumb_resolution(1, 100000) == (64, 16384)
    assert bridge._coerce_artist_thumb_resolution(100000, 1) == (16384, 64)


def test_artist_thumb_random_prompt_fits_detected_nai_resolution(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ctx = _AppContext()
    ctx.main_window = SimpleNamespace(
        negative_prompt_textedit=_TextEdit("negative"),
        search_results=None,
        resolution_combo=_ResolutionCombo(["832 x 1216"]),
    )
    ctx.current_prompt_context = None
    bridge = RemoteBridge(ctx)
    bridge._loop = _ImmediateLoop()
    future = _DoneFuture()
    bridge._pending_comfyui_requests["req"] = future
    bridge._pending_overrides[("comfyui", "req")] = {
        "comfyui_request_id": "req",
        "artist_thumb_random_prompt": True,
    }

    bridge.on_prompt_generated(SimpleNamespace(
        final_prompt="prompt",
        source_row={"image_width": 4096, "image_height": 6144},
    ))

    assert future.value["width"] == 832
    assert future.value["height"] == 1216
    assert future.value["resolution_source"] == "detected_fit"


def test_artist_thumb_random_prompt_empty_source_fails_pending_request(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    triggered = []
    ctx = _AppContext()
    ctx.session_p_eng_override = None
    ctx.main_window = SimpleNamespace(
        generation_checkboxes={"자동 생성": _ToggleButton(False)},
        trigger_random_prompt=lambda **kwargs: triggered.append(kwargs),
    )
    bridge = RemoteBridge(ctx)
    bridge._loop = _ImmediateLoop()
    bridge._pick_from_snapshot = lambda active_ratings: None
    future = _DoneFuture()
    bridge._pending_comfyui_requests["req"] = future
    bridge._pending_random_requests.append({
        "ws": None,
        "source_row": None,
        "active_ratings": {"s"},
        "comfyui_request_id": "req",
        "respect_naia_autogen": False,
        "force_naia_skip_generate": True,
    })

    bridge._do_random()

    assert triggered == []
    assert future.done()
    assert isinstance(future.exception, RuntimeError)
    assert "source is empty" in str(future.exception)
    assert "req" not in bridge._pending_comfyui_requests
    assert ("comfyui", "req") not in bridge._pending_overrides


def test_artist_thumb_generate_coerces_invalid_nai_resolution(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ctx = _AppContext()
    ctx.generation_queue_manager = _QueueManager(empty=True)
    ctx.main_window = SimpleNamespace(
        negative_prompt_textedit=_TextEdit(""),
        generation_checkboxes={"자동 생성": _ToggleButton(False)},
        generation_controller=_GenerationController(),
        resolution_combo=_ResolutionCombo(["832 x 1216"]),
    )
    bridge = RemoteBridge(ctx)
    bridge._broadcast_json = lambda payload: None
    bridge._broadcast_queue_state = lambda: None

    bridge._do_artist_thumb_generate({
        "request_id": "req",
        "artist": "artist",
        "positive": "1girl",
        "width": 4096,
        "height": 4096,
    })

    overrides, priority = ctx.main_window.generation_controller.executed[0]
    assert priority == 0
    assert overrides["width"] == 1024
    assert overrides["height"] == 1024


def test_artist_thumb_state_counts_visible_artists_after_bans(tmp_path, monkeypatch):
    bridge = _bridge_with_artist_thumb_lists(tmp_path, monkeypatch)

    state = bridge._build_artist_thumb_state()
    counts = {item["key"]: item["count"] for item in state["filters"]}

    assert counts["all"] == 4
    assert counts["favorites"] == 1
    assert counts["banned"] == 1
    assert counts["custom:group"] == 2


def test_artist_thumb_list_and_random_exclude_banned_artists(tmp_path, monkeypatch):
    bridge = _bridge_with_artist_thumb_lists(tmp_path, monkeypatch)

    payload = bridge._build_artist_thumb_list("mode", "all", "", 0, 48)
    assert payload["total"] == 4
    assert "b" not in {item["artist"] for item in payload["items"]}

    favorite_payload = bridge._build_artist_thumb_list("mode", "favorites", "", 0, 48)
    assert [item["artist"] for item in favorite_payload["items"]] == ["a"]

    custom_payload = bridge._build_artist_thumb_list("mode", "custom:group", "", 0, 48)
    assert custom_payload["total"] == 2
    assert "b" not in {item["artist"] for item in custom_payload["items"]}

    banned_random = bridge._build_artist_thumb_list("mode", "banned", "", 0, 2, True)
    assert banned_random["total"] == 0
    assert banned_random["items"] == []


def test_artist_thumb_random_sample_avoids_recent_repeats(tmp_path, monkeypatch):
    bridge = _bridge_with_artist_thumb_lists(tmp_path, monkeypatch)
    weights = {"b": 100, **{f"a{i}": i for i in range(25)}}
    bridge._artist_thumb_artist_weights = lambda: weights
    bridge._load_artist_thumb_data = lambda mode: {artist: ["thumb"] for artist in weights}

    first = bridge._build_artist_thumb_list("mode", "all", "", 0, 12, True)
    second = bridge._build_artist_thumb_list("mode", "all", "", 0, 12, True)

    first_artists = {item["artist"] for item in first["items"]}
    second_artists = {item["artist"] for item in second["items"]}
    assert len(first_artists) == 12
    assert len(second_artists) == 12
    assert first_artists.isdisjoint(second_artists)
