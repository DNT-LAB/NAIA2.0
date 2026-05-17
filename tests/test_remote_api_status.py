import asyncio
import base64
import hashlib
import io
import json
import sys
import types
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
import pandas as pd
from fastapi.testclient import TestClient
from PIL import Image
from PIL.PngImagePlugin import PngInfo

import core.remote_api_server as remote_api_server
from core.comfyui_workflow_manager import ComfyUIWorkflowManager
from core.remote_api_server import RemoteBridge, WebSocketManager, create_app
from core.search_result_model import SearchResultModel
from modules.prompt_engineering_module import PromptEngineeringModule as RealPromptEngineeringModule

if "piexif" not in sys.modules:
    piexif_stub = types.ModuleType("piexif")
    piexif_stub.ExifIFD = SimpleNamespace(UserComment=0)
    piexif_stub.load = lambda _data: {}
    piexif_helper_stub = types.ModuleType("piexif.helper")
    piexif_helper_stub.UserComment = SimpleNamespace(load=lambda _value: "")
    piexif_stub.helper = piexif_helper_stub
    sys.modules["piexif"] = piexif_stub
    sys.modules["piexif.helper"] = piexif_helper_stub


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


class _FakeTextEdit:
    def __init__(self, text=""):
        self.text = text

    def toPlainText(self):
        return self.text

    def setPlainText(self, text):
        self.text = text


class _FakeLineEdit:
    def __init__(self, text=""):
        self._text = text

    def text(self):
        return self._text

    def setText(self, text):
        self._text = str(text)


class _FakeComboBox:
    def __init__(self, items=None, current=""):
        self.items = list(items or [])
        self.current = current or (self.items[0] if self.items else "")

    def count(self):
        return len(self.items)

    def itemText(self, index):
        return self.items[index]

    def currentText(self):
        return self.current

    def findText(self, text):
        try:
            return self.items.index(text)
        except ValueError:
            return -1

    def setCurrentIndex(self, index):
        self.current = self.items[index]

    def setCurrentText(self, text):
        self.current = text

    def blockSignals(self, _blocked):
        return None

    def clear(self):
        self.items = []
        self.current = ""

    def addItem(self, text):
        self.items.append(text)
        if not self.current:
            self.current = text

    def addItems(self, items):
        for item in items:
            self.addItem(item)


class PromptEngineeringModule:
    def __init__(self):
        self.preset_list = ["default", "alpha", "beta", "gamma"]
        self.randomized_preset_list = ["alpha"]
        self.preset_combo = _FakeComboBox(["*randomized", "default", "alpha", "beta", "gamma"], "*randomized")
        self.pre_textedit = _FakeTextEdit("pre")
        self.post_textedit = _FakeTextEdit("post")
        self.auto_hide_textedit = _FakeTextEdit("hide")
        self.preprocessing_checkboxes = {"Remove Artist": _FakeCheckBox(True)}
        self.option_key_map = {"Remove Artist": "remove_author"}
        self._e621_settings = {}
        self._danbooru_weight_settings = {}

    def get_debug_snapshot(self):
        return {}

    def get_preset_dir(self):
        return Path("missing-prompt-engineering-presets")

    def get_randomized_available_presets(self):
        selected = set(self.randomized_preset_list)
        return [
            preset for preset in self.preset_list
            if preset not in ("default", "*randomized") and preset not in selected
        ]

    def add_randomized_preset(self, preset):
        if preset not in self.get_randomized_available_presets():
            return False, "invalid"
        self.randomized_preset_list.append(preset)
        return True, preset

    def remove_randomized_preset(self, preset):
        if preset not in self.randomized_preset_list:
            return False, "missing"
        self.randomized_preset_list.remove(preset)
        return True, preset

    def clear_randomized_presets(self):
        self.randomized_preset_list = []
        return True, ""


class _FakeWsManager:
    active_connections = {object()}

    def __init__(self):
        self.messages = []

    async def broadcast_json(self, payload):
        self.messages.append(payload)


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
        self.file_hash = "fake-vibe-hash"
        self.file_name = "fake-vibe.png"
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


def test_select_remote_server_port_keeps_bindable_preferred(monkeypatch):
    probes = []
    monkeypatch.setattr(
        remote_api_server,
        "_can_bind_remote_port",
        lambda host, port: probes.append((host, port)) or True,
    )

    selected = remote_api_server._select_remote_server_port("127.0.0.1", "7243")

    assert selected == 7243
    assert probes == [("127.0.0.1", 7243)]


def test_select_remote_server_port_falls_forward_when_preferred_unavailable(monkeypatch):
    probes = []

    def can_bind(host, port):
        probes.append((host, port))
        return port == 7245

    monkeypatch.setattr(remote_api_server, "_can_bind_remote_port", can_bind)

    selected = remote_api_server._select_remote_server_port("0.0.0.0", 7243)

    assert selected == 7245
    assert probes == [
        ("0.0.0.0", 7243),
        ("0.0.0.0", 7244),
        ("0.0.0.0", 7245),
    ]


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


def test_api_status_exposes_autocomplete_warmup_and_cache_state():
    bridge = RemoteBridge(_AppContext())
    bridge._kr_tags_loaded = True
    bridge._tag_search_index = SimpleNamespace(metadata_fallback_index_ready=lambda: True)
    bridge._autocomplete_translation_cache = {"원본": "translated"}
    bridge._autocomplete_result_cache = {("원본", 12): ([], "translated")}

    local = bridge.get_api_status(ws=_ws("127.0.0.1"))

    assert local["autocomplete"] == {
        "kr_tags_loaded": True,
        "metadata_fallback": {
            "ready": True,
            "live_path_allows_build": False,
        },
        "translation_cache_size": 1,
        "result_cache_size": 1,
    }


def test_tag_lookup_accepts_webui_escaped_parentheses():
    bridge = RemoteBridge.__new__(RemoteBridge)
    bridge._kr_tags_raw = {
        "nahida (genshin impact)": {
            "_tag": "nahida (genshin impact)",
            "freq": 10000,
            "description": "character",
            "group": "character",
            "subgroup": "genshin impact",
            "_cat": "character",
            "relations": {},
        },
    }
    bridge._tag_relation_ranker = None
    bridge._char_analysis = {}
    bridge._load_kr_tags = lambda: None
    bridge._load_char_analysis = lambda: None

    info = bridge._lookup_tag_info(r"nahida \(genshin impact\)")

    assert info["tag"] == "nahida (genshin impact)"
    assert info["count"] == 10000


def test_generation_error_clears_remote_generation_status():
    bridge = RemoteBridge(_AppContext())
    broadcasts = []
    bridge._broadcast_json = broadcasts.append

    bridge.on_generation_error({"message": "API failed"})

    assert broadcasts == [
        {"type": "toast", "message": "API failed", "level": "error"},
        {"type": "status", "is_generating": False},
    ]


def test_event_preset_generation_error_keeps_scoped_error_and_clears_status():
    bridge = RemoteBridge(_AppContext())
    broadcasts = []
    bridge._broadcast_json = broadcasts.append

    bridge.on_generation_error({
        "message": "Preset failed",
        "event_preset_request": True,
        "event_preset_request_id": "req-1",
    })

    assert broadcasts == [
        {
            "type": "event_preset_generation_error",
            "requestId": "req-1",
            "message": "Preset failed",
        },
        {"type": "status", "is_generating": False},
    ]


def test_prompt_engineering_state_exposes_randomized_manage_pool():
    ctx = _AppContext()
    module = PromptEngineeringModule()
    ctx.middle_section_controller = SimpleNamespace(module_instances=[module])
    bridge = RemoteBridge(ctx)

    state = bridge._read_prompt_engineering()

    assert state["preset"] == "*randomized"
    assert state["randomized_active"] is True
    assert state["randomized_preset_list"] == ["alpha"]
    assert state["randomized_available_presets"] == ["beta", "gamma"]
    assert state["preset_can_save_current"] is False
    assert state["preset_can_delete"] is False


def test_prompt_engineering_state_exposes_webui_presets_separately(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    webui_dir = tmp_path / "save" / "presets" / "WEBUI"
    nai_dir = tmp_path / "save" / "presets" / "NAI"
    webui_dir.mkdir(parents=True)
    nai_dir.mkdir(parents=True)
    (webui_dir / "default.json").write_text(json.dumps({
        "api_mode": "WEBUI",
        "module_settings": {"pre_prompt": "webui default"},
    }), encoding="utf-8")
    (webui_dir / "fast1.json").write_text(json.dumps({
        "api_mode": "WEBUI",
        "module_settings": {"pre_prompt": "webui fast"},
    }), encoding="utf-8")
    (webui_dir / "fast1.hires.json").write_text("{}", encoding="utf-8")
    (nai_dir / "260108.json").write_text(json.dumps({
        "api_mode": "NAI",
        "module_settings": {"pre_prompt": "nai only"},
    }), encoding="utf-8")

    ctx = _AppContext()
    module = PromptEngineeringModule()
    module.preset_combo = _FakeComboBox(["*randomized", "default", "260108"], "260108")
    ctx.middle_section_controller = SimpleNamespace(module_instances=[module])
    bridge = RemoteBridge(ctx)

    state = bridge._read_prompt_engineering()

    assert "260108" in state["preset_options"]
    assert state["webui_preset_options"] == ["default", "fast1"]
    assert {s["name"]: s["api_mode"] for s in state["webui_preset_summaries"]} == {
        "default": "WEBUI",
        "fast1": "WEBUI",
    }
    assert {s["name"]: s["pre_prompt_preview"] for s in state["webui_preset_summaries"]}["fast1"] == "webui fast"


def test_prompt_engineering_randomized_manage_commands_update_pool():
    ctx = _AppContext()
    module = PromptEngineeringModule()
    ctx.middle_section_controller = SimpleNamespace(module_instances=[module])
    bridge = RemoteBridge(ctx)
    broadcasts = []
    bridge._broadcast_json = broadcasts.append
    bridge._broadcast_prompt_engineering_state = lambda: broadcasts.append({"type": "module_state"})

    bridge._set_prompt_engineering("randomized_add", "beta")
    assert module.randomized_preset_list == ["alpha", "beta"]
    assert broadcasts[-1] == {"type": "module_state"}

    bridge._set_prompt_engineering("randomized_remove", "alpha")
    assert module.randomized_preset_list == ["beta"]
    assert broadcasts[-1] == {"type": "module_state"}

    bridge._set_prompt_engineering("randomized_clear", "true")
    assert module.randomized_preset_list == []
    assert broadcasts[-1] == {"type": "module_state"}

    bridge._set_prompt_engineering("randomized_add", "default")
    assert broadcasts[-1] == {"type": "toast", "message": "invalid", "level": "error"}


def _bare_real_prompt_engineering_module(mode="NAI"):
    module = object.__new__(RealPromptEngineeringModule)
    module.app_context = SimpleNamespace(get_api_mode=lambda: mode)
    module.preset_list = ["default", "alpha", "beta", "gamma"]
    module.randomized_preset_list = []
    module.randomized_listbox = None
    module.randomized_combo = None
    module.randomized_add_btn = None
    return module


def test_prompt_engineering_randomized_pool_persists_per_mode(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    module = _bare_real_prompt_engineering_module("NAI")
    assert module.add_randomized_preset("alpha") == (True, "alpha")
    assert module.add_randomized_preset("beta") == (True, "beta")

    pool_file = tmp_path / "save" / "presets" / "randomized_pool.json"
    assert json.loads(pool_file.read_text(encoding="utf-8")) == {"NAI": ["alpha", "beta"]}

    reloaded = _bare_real_prompt_engineering_module("NAI")
    reloaded._load_randomized_preset_list()
    reloaded._prune_randomized_preset_list(persist=True)
    assert reloaded.randomized_preset_list == ["alpha", "beta"]

    webui = _bare_real_prompt_engineering_module("WEBUI")
    assert webui.add_randomized_preset("gamma") == (True, "gamma")
    assert json.loads(pool_file.read_text(encoding="utf-8")) == {
        "NAI": ["alpha", "beta"],
        "WEBUI": ["gamma"],
    }

    assert reloaded.remove_randomized_preset("alpha") == (True, "alpha")
    assert json.loads(pool_file.read_text(encoding="utf-8"))["NAI"] == ["beta"]

    reloaded.current_preset = "*randomized"
    reloaded.save_current_preset = lambda *args, **kwargs: pytest.fail("should not save *randomized as a preset file")
    reloaded.save_last_used_preset_info = lambda *args, **kwargs: pytest.fail("should not mark *randomized as last used")
    reloaded.save_on_exit()
    assert json.loads(pool_file.read_text(encoding="utf-8"))["NAI"] == ["beta"]

    assert reloaded.clear_randomized_presets() == (True, "")
    assert json.loads(pool_file.read_text(encoding="utf-8"))["NAI"] == []


def test_prompt_engineering_ignores_legacy_randomized_preset_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    class _FakePresetPath:
        def __init__(self, stem):
            self.stem = stem

        def __lt__(self, other):
            return self.stem < other.stem

    module = _bare_real_prompt_engineering_module("NAI")
    module.preset_combo = _FakeComboBox(["*randomized"], "*randomized")
    module.get_preset_dir = lambda mode=None: SimpleNamespace(
        glob=lambda _pattern: [
            _FakePresetPath("*randomized"),
            _FakePresetPath("default"),
            _FakePresetPath("alpha"),
            _FakePresetPath("alpha.hires"),
        ]
    )

    module.load_preset_list()

    assert module.preset_list == ["default", "alpha"]
    assert module.preset_combo.items == ["*randomized", "default", "alpha"]


def test_auto_generated_prompt_broadcast_uses_auto_generate_source(monkeypatch):
    ctx = _AppContext()
    ctx.current_prompt_context = None
    bridge = RemoteBridge(ctx)
    ws_manager = _FakeWsManager()
    loop = asyncio.new_event_loop()
    bridge.set_ws_manager(ws_manager)
    bridge.set_event_loop(loop)
    bridge._build_prompt_token_payload = lambda *_args, **_kwargs: {}
    bridge._read_wildcard = lambda: None
    bridge._read_prompt_engineering = lambda: None
    bridge._read_character = lambda: None

    def run_now(coro, target_loop):
        target_loop.run_until_complete(coro)
        return SimpleNamespace()

    monkeypatch.setattr(remote_api_server.asyncio, "run_coroutine_threadsafe", run_now)
    prompt_context = SimpleNamespace(
        final_prompt="auto prompt",
        settings={"auto_generate": True},
        source_row=SimpleNamespace(name=""),
        metadata={"detected_resolution": (640, 960)},
        wildcard_history={},
        wildcard_state={},
    )

    try:
        bridge.on_prompt_generated(prompt_context)
    finally:
        loop.close()

    assert ws_manager.messages[0]["type"] == "prompt_generated"
    assert ws_manager.messages[0]["source"] == "auto_generate"
    assert ws_manager.messages[0]["prompt"] == "auto prompt"
    assert ws_manager.messages[0]["resolution"] == "640 x 960"
    assert ws_manager.messages[0]["detected_resolution"] == {"width": 640, "height": 960}


def test_web_random_pending_keeps_random_source_when_auto_gen_checked(monkeypatch):
    ctx = _AppContext()
    ctx.current_prompt_context = None
    ctx.main_window = SimpleNamespace(
        search_results=None,
        generation_controller=SimpleNamespace(is_generating=True),
    )
    bridge = RemoteBridge(ctx)
    ws_manager = _FakeWsManager()
    loop = asyncio.new_event_loop()
    ws = object()
    bridge.set_ws_manager(ws_manager)
    bridge.set_event_loop(loop)
    bridge._pending_overrides[ws] = {
        "params": None,
        "negative": None,
        "source": "random",
        "auto_generate": True,
        "remote_random_request_id": "rid-random-auto",
    }
    bridge._build_prompt_token_payload = lambda *_args, **_kwargs: {}
    bridge._read_wildcard = lambda: None
    bridge._read_prompt_engineering = lambda: None
    bridge._read_character = lambda: None

    def run_now(coro, target_loop):
        target_loop.run_until_complete(coro)
        return SimpleNamespace()

    monkeypatch.setattr(remote_api_server.asyncio, "run_coroutine_threadsafe", run_now)
    prompt_context = SimpleNamespace(
        final_prompt="manual web random",
        settings={"auto_generate": True},
        source_row=SimpleNamespace(name=""),
        wildcard_history={},
        wildcard_state={},
    )

    try:
        bridge.on_prompt_generated(prompt_context)
    finally:
        loop.close()

    assert ws_manager.messages[0]["source"] == "random"
    assert ws_manager.messages[0]["random_request_id"] == "rid-random-auto"
    assert ws_manager.messages[0]["requestId"] == "rid-random-auto"


def test_web_random_pending_echoes_request_id_after_button_timeout(monkeypatch):
    ctx = _AppContext()
    ctx.current_prompt_context = None
    ctx.main_window = SimpleNamespace(
        search_results=None,
        generation_controller=SimpleNamespace(is_generating=False),
    )
    bridge = RemoteBridge(ctx)
    ws_manager = _FakeWsManager()
    loop = asyncio.new_event_loop()
    ws = object()
    bridge.set_ws_manager(ws_manager)
    bridge.set_event_loop(loop)
    bridge._pending_overrides[ws] = {
        "params": None,
        "negative": None,
        "source": "random",
        "auto_generate": False,
        "remote_random_request_id": "rid-random-late",
    }
    bridge._build_prompt_token_payload = lambda *_args, **_kwargs: {}
    bridge._read_wildcard = lambda: None
    bridge._read_prompt_engineering = lambda: None
    bridge._read_character = lambda: None

    def run_now(coro, target_loop):
        target_loop.run_until_complete(coro)
        return SimpleNamespace()

    monkeypatch.setattr(remote_api_server.asyncio, "run_coroutine_threadsafe", run_now)
    prompt_context = SimpleNamespace(
        final_prompt="late web random",
        settings={},
        source_row=SimpleNamespace(name=""),
        metadata={"detected_resolution": (704, 832)},
        wildcard_history={},
        wildcard_state={},
    )

    try:
        bridge.on_prompt_generated(prompt_context)
    finally:
        loop.close()

    message = ws_manager.messages[0]
    assert message["source"] == "random"
    assert message["random_request_id"] == "rid-random-late"
    assert message["requestId"] == "rid-random-late"
    assert message["resolution"] == "704 x 832"
    assert message["detected_resolution"] == {"width": 704, "height": 832}
    assert ws not in bridge._pending_overrides


def test_web_random_auto_generate_respects_boolean_seed_fixed(monkeypatch):
    ctx = _AppContext()
    ctx.current_prompt_context = None
    generation_controller = _GenerationController()
    ctx.main_window = SimpleNamespace(
        search_results=None,
        generation_controller=generation_controller,
        negative_prompt_textedit=_TextEdit(""),
    )
    bridge = RemoteBridge(ctx)
    monkeypatch.setattr(remote_api_server.random, "randint", lambda *_args: 9999999999)
    bridge._pending_overrides[object()] = {
        "params": {"seed": "12345", "seed_fixed": True},
        "negative": None,
        "source": "random",
        "auto_generate": True,
    }

    bridge.on_prompt_generated(SimpleNamespace(
        final_prompt="prompt",
        settings={"auto_generate": True},
        source_row=SimpleNamespace(name=""),
    ))

    assert generation_controller.executed == [
        ({"seed": "12345", "seed_fixed": True}, 0),
    ]


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


def test_vibe_cluster_save_accepts_korean_names(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bridge = RemoteBridge(_AppContext())
    bridge._broadcast_json = lambda payload: None
    module = _FakeVibeModule([_FakeVibeFrame({1.0: "encoded-a"}, 0.21, 1.0, True)])

    saved = bridge._save_current_vibe_cluster(
        module,
        json.dumps({"name": "테스트Vibe1", "description": "desc"}),
    )

    assert saved is True
    item = bridge._scan_vibe_clusters()["items"][0]
    assert item["name"] == "테스트Vibe1"


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


def test_preset_autocomplete_root_returns_axis_tokens(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bridge = RemoteBridge(_AppContext())

    results = bridge._search_preset_paths("preset:")

    assert [item["value"] for item in results] == [
        "preset:events(s|1girl_solo)",
        "preset:clothes",
        "preset:expressions",
    ]
    assert all(item["_wc_type"] == "preset_path" for item in results)


def test_preset_autocomplete_missing_axis_returns_status_row(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bridge = RemoteBridge(_AppContext())
    bridge._event_preset_service = remote_api_server.EventPresetService(tmp_path)
    bridge._publish_preset_services()

    results = bridge._search_preset_paths("preset:events")

    assert len(results) == 1
    assert results[0]["_wc_type"] == "preset_status"
    assert results[0]["disabled"] is True


def test_preset_autocomplete_payload_passes_event_context(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    captured = {}

    class _FakePresetInputBridge:
        def __init__(self, _root, *, context=None):
            captured["context"] = context

        def suggest(self, token, limit=12):
            captured["token"] = token
            captured["limit"] = limit
            return {
                "axis": "events",
                "stage": "category",
                "dataReady": True,
                "loadState": {"main": "ready", "message": "ready"},
                "presetContext": {
                    "ratingId": "q",
                    "personId": "2girls",
                    "ratingOptions": [{"id": "q", "label": "Q"}],
                    "personOptions": [{"id": "2girls", "label": "2girls"}],
                },
                "suggestions": [
                    {
                        "tag": "Gaze",
                        "value": "preset:events/expression%20action%3A%3Agaze",
                        "_wc_type": "preset_path",
                        "axis": "events",
                    }
                ],
                "secondaryResults": [
                    {
                        "tag": "Looking Back",
                        "value": "preset:events(e|2girls)/gaze/gaze_direction/looking_back",
                        "_wc_type": "preset_path",
                        "axis": "events",
                    }
                ],
            }

    monkeypatch.setattr(remote_api_server, "PresetInputBridge", _FakePresetInputBridge)
    bridge = RemoteBridge(_AppContext())

    payload = bridge._preset_autocomplete_payload(
        "preset:events",
        context={"ratingId": "q", "personId": "2girls"},
    )

    assert captured["context"] == {"ratingId": "q", "personId": "2girls"}
    assert bridge.app_context.preset_input_context == {"ratingId": "q", "personId": "2girls"}
    assert bridge.app_context.preset_input_context_source == "autocomplete"
    assert bridge.app_context.preset_input_context_fields == {"ratingId", "personId"}
    assert payload["preset"]["axis"] == "events"
    assert payload["preset"]["context"]["personId"] == "2girls"
    assert payload["results"][0]["tag"] == "Gaze"
    assert payload["secondaryResults"][0]["tag"] == "Looking Back"
    assert payload["preset"]["secondaryResults"] == payload["secondaryResults"]


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


def test_remote_vibe_upload_capacity_error_is_remote_owned(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ctx = _AppContext()
    bridge = RemoteBridge(ctx)
    module = _FakeVibeModule([
        _FakeVibeFrame()
        for _ in range(remote_api_server.MAX_NAI_VIBE_REFERENCES)
    ])
    bridge._find_module = lambda name: module if name == "vibe_transfer" else None
    broadcasts = []
    bridge._broadcast_json = broadcasts.append

    buffer = io.BytesIO()
    Image.new("RGB", (1, 1), "white").save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")

    bridge._set_vibe_transfer("upload_image", encoded)

    assert broadcasts[0] == {
        "type": "toast",
        "message": "Maximum 16 Vibe Transfer frames allowed",
        "level": "error",
    }
    assert broadcasts[-1]["module_id"] == "vibe_transfer"
    assert len(module.vibe_frames) == remote_api_server.MAX_NAI_VIBE_REFERENCES


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


def test_prompt_preset_file_rejects_invalid_mode(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    preset_dir = tmp_path / "save" / "presets" / "NAI"
    preset_dir.mkdir(parents=True)
    preset_file = preset_dir / "safe.json"
    preset_file.write_text("{}", encoding="utf-8")
    bridge = RemoteBridge(_AppContext())

    assert bridge._prompt_engineering_preset_file("safe", "nai").resolve() == preset_file.resolve()
    with pytest.raises(ValueError, match="Invalid preset mode"):
        bridge._prompt_engineering_preset_file("safe", "../../NAI")


def test_prompt_preset_thumbnail_upload_rejects_invalid_mode_before_write(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bridge = RemoteBridge(_AppContext())
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(buffer, format="PNG")

    with pytest.raises(ValueError, match="Invalid preset mode"):
        bridge._save_prompt_engineering_thumbnail_bytes("safe", "../NAI", buffer.getvalue())

    assert not (tmp_path / "save" / "presets" / "previews" / "safe.png").exists()


def test_prompt_preset_thumbnail_generation_queues_vibe_safe_request(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    preset_dir = tmp_path / "save" / "presets" / "NAI"
    preset_dir.mkdir(parents=True)
    (preset_dir / "safe.json").write_text(
        json.dumps({"module_settings": {"pre_prompt": "preset prefix"}}),
        encoding="utf-8",
    )
    bridge, _generation_controller, _prompt_edit, negative_edit = _bridge_with_generate_context()
    negative_edit.text = "thumbnail negative"
    bridge._broadcast_json = lambda _payload: None
    bridge._active_vibe_transfer_count_for_generation = lambda: 2

    result = bridge._request_prompt_engineering_thumbnail_generation({
        "name": "safe",
        "mode": "nai",
        "request_id": "req-1",
    })

    queued = bridge._pending_generate_requests.pop()
    overrides = queued["overrides"]
    assert result["mode"] == "NAI"
    assert result["vibe_active"] is True
    assert "Vibe Transfer" in result["message"]
    assert overrides["input"] == "preset prefix, 1girl, original, solo, upper body"
    assert overrides["negative_prompt"] == "thumbnail negative"
    assert overrides["_skip_vibe_transfer_late_binding"] is True
    assert overrides["prompt_preset_thumbnail_request"] is True


def _bridge_with_search_snapshots(master_df, visible_df):
    ctx = _AppContext()
    ctx.main_window = SimpleNamespace(
        _master_filter_snapshot=master_df.copy(),
        _search_results_snapshot=visible_df.copy(),
        search_results=SearchResultModel(visible_df.copy()),
    )
    return RemoteBridge(ctx)


def test_tag_filter_search_uses_master_snapshot_not_current_rating_subset():
    master = pd.DataFrame([
        {"id": 1, "rating": "s", "general": "angel wings blue hair"},
        {"id": 2, "rating": "e", "general": "angel wings red hair"},
        {"id": 3, "rating": "q", "general": "solo smile"},
    ])
    visible = master[master["rating"] == "s"].copy()
    bridge = _bridge_with_search_snapshots(master, visible)

    result = bridge._do_tag_filter_search(["angel_wings"])

    assert result["count"] == 2
    assert result["rating_counts"] == {"g": 0, "s": 1, "q": 0, "e": 1}
    assert result["_ids"] == {1, 2}


def test_tag_filter_random_pick_uses_master_snapshot_after_rating_switch():
    master = pd.DataFrame([
        {"id": 1, "rating": "s", "general": "angel wings blue hair"},
        {"id": 2, "rating": "e", "general": "angel wings red hair"},
    ])
    stale_visible = master[master["rating"] == "s"].copy()
    bridge = _bridge_with_search_snapshots(master, stale_visible)

    picked = bridge._pick_from_tag_filter({"ids": {1, 2}}, {"e"})

    assert picked is not None
    assert int(picked["id"]) == 2


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


def test_web_random_passes_session_overrides_to_prompt_generation():
    triggered = []
    ctx = _AppContext()
    ctx.main_window = SimpleNamespace(
        generation_checkboxes={"자동 생성": _ToggleButton(True)},
        trigger_random_prompt=lambda **kwargs: triggered.append(kwargs),
    )
    bridge = RemoteBridge(ctx)
    overrides = {
        "api_mode": "WEBUI",
        "anima_weight": "0.85",
        "random_prompt_weight": "0.85",
    }
    ws = object()
    bridge._pending_random_requests.append({
        "ws": ws,
        "source_row": None,
        "active_ratings": {"g", "s"},
        "overrides": overrides,
        "remote_random_request_id": "rid-random-click",
    })

    bridge._do_random()

    assert triggered == [{
        "settings_override": overrides,
        "active_ratings": {"g", "s"},
        "source_row_override": None,
    }]
    assert bridge._pending_overrides[ws]["params"] == overrides
    assert bridge._pending_overrides[ws]["auto_generate"] is True
    assert bridge._pending_overrides[ws]["remote_random_request_id"] == "rid-random-click"


def test_remote_web_ui_state_persists_hires_assist_and_random_prompt_weight(tmp_path, monkeypatch):
    class _WebuiContext(_AppContext):
        def get_api_mode(self):
            return "WEBUI"

    monkeypatch.chdir(tmp_path)
    ctx = _WebuiContext()
    bridge = RemoteBridge(ctx)

    assert bridge._read_webui_hiresfix_assist() == {
        "type": "module_state",
        "module_id": "webui_hiresfix_assist",
        "enabled": True,
        "target": 512,
    }

    bridge._set_webui_hiresfix_assist("enabled", "false")
    bridge._set_webui_hiresfix_assist("target", "768")
    bridge._save_remote_web_ui_state(
        hires_preset_swap="prev5",
        random_prompt_weight="0.85",
        resolution_preset={
            "WEBUI": {"enabled": True, "preset": "quality"},
            "COMFYUI": {"enabled": False, "preset": "standard"},
        },
    )

    saved = json.loads(Path("app_settings.json").read_text(encoding="utf-8"))
    assert saved["remote_web"]["webui_hiresfix_assist"] == {"enabled": False, "target": 768}
    assert saved["remote_web"]["resolution_preset"]["WEBUI"] == {"enabled": True, "preset": "quality"}
    assert saved["remote_web"]["hires_preset_swap"] == "prev5"
    assert saved["remote_web"]["random_prompt_weight"] == "0.85"

    restarted = RemoteBridge(ctx)
    assert restarted._read_webui_hiresfix_assist()["enabled"] is False
    assert restarted._read_webui_hiresfix_assist()["target"] == 768
    schema = restarted.get_generation_param_schema()
    assert schema["hires_preset_swap"] == "prev5"
    assert schema["random_prompt_weight"] == "0.85"
    assert schema["anima_weight"] == "0.85"
    assert schema["resolution_preset_enabled"] is True
    assert schema["resolution_preset"] == "quality"


def test_remote_web_ui_state_normalizes_conflicting_resolution_tools(tmp_path, monkeypatch):
    class _WebuiContext(_AppContext):
        def get_api_mode(self):
            return "WEBUI"

    monkeypatch.chdir(tmp_path)
    ctx = _WebuiContext()
    bridge = RemoteBridge(ctx)

    bridge._save_remote_web_ui_state(
        webui_hiresfix_assist={"enabled": True, "target": 768},
        resolution_preset={
            "WEBUI": {"enabled": True, "preset": "quality"},
            "COMFYUI": {"enabled": False, "preset": "standard"},
        },
    )

    saved = json.loads(Path("app_settings.json").read_text(encoding="utf-8"))
    assert saved["remote_web"]["webui_hiresfix_assist"] == {"enabled": False, "target": 768}
    assert saved["remote_web"]["resolution_preset"]["WEBUI"] == {"enabled": True, "preset": "quality"}
    assert bridge._read_webui_hiresfix_assist()["enabled"] is False


def test_remote_web_resolution_preset_enabling_disables_hiresfix_server_state(tmp_path, monkeypatch):
    class _WebuiContext(_AppContext):
        def get_api_mode(self):
            return "WEBUI"

    monkeypatch.chdir(tmp_path)
    ctx = _WebuiContext()
    bridge = RemoteBridge(ctx)
    bridge._set_webui_hiresfix_assist("target", "768")

    bridge._do_set_param("resolution_preset_enabled", "true")

    saved = json.loads(Path("app_settings.json").read_text(encoding="utf-8"))
    assert saved["remote_web"]["resolution_preset"]["WEBUI"]["enabled"] is True
    assert saved["remote_web"]["webui_hiresfix_assist"] == {"enabled": False, "target": 768}
    assert bridge._read_webui_hiresfix_assist()["enabled"] is False


def test_remote_web_hiresfix_enabling_disables_webui_resolution_preset_server_state(tmp_path, monkeypatch):
    class _WebuiContext(_AppContext):
        def get_api_mode(self):
            return "WEBUI"

    monkeypatch.chdir(tmp_path)
    ctx = _WebuiContext()
    bridge = RemoteBridge(ctx)
    bridge._save_remote_web_ui_state(
        webui_hiresfix_assist={"enabled": False, "target": 768},
        resolution_preset={
            "WEBUI": {"enabled": True, "preset": "quality"},
            "COMFYUI": {"enabled": False, "preset": "standard"},
        },
    )

    bridge._set_webui_hiresfix_assist("enabled", "true")

    saved = json.loads(Path("app_settings.json").read_text(encoding="utf-8"))
    assert saved["remote_web"]["webui_hiresfix_assist"] == {"enabled": True, "target": 768}
    assert saved["remote_web"]["resolution_preset"]["WEBUI"] == {"enabled": False, "preset": "quality"}
    assert bridge.get_generation_param_schema()["resolution_preset_enabled"] is False


def test_remote_web_hires_preset_swap_param_is_saved_for_auto_generation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ctx = _AppContext()
    bridge = RemoteBridge(ctx)

    bridge._do_set_param("hires_preset_swap", "prev5")

    saved = json.loads(Path("app_settings.json").read_text(encoding="utf-8"))
    assert saved["remote_web"]["hires_preset_swap"] == "prev5"
    assert bridge.get_webui_hires_preset_swap_params() == {"hires_preset_swap": "prev5"}

    bridge._do_set_param("hires_preset_swap", "")

    saved = json.loads(Path("app_settings.json").read_text(encoding="utf-8"))
    assert saved["remote_web"]["hires_preset_swap"] == ""
    assert bridge.get_webui_hires_preset_swap_params() == {}


def test_remote_auto_generate_owner_tracks_remote_toggle_and_desktop_off(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ctx = _AppContext()
    auto_generate = _ToggleButton(False)
    ctx.main_window = SimpleNamespace(
        generation_checkboxes={"자동 생성": auto_generate}
    )
    bridge = RemoteBridge(ctx)

    bridge._do_set_option("auto_generate", True)

    assert auto_generate.isChecked() is True
    assert bridge.is_remote_auto_generate_enabled() is True

    auto_generate.setChecked(False)
    bridge.broadcast_options()

    assert bridge.is_remote_auto_generate_enabled() is False


def test_remote_web_anima_weight_param_is_saved_for_next_session(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ctx = _AppContext()
    ctx.main_window = SimpleNamespace(anima_weight_edit=_FakeLineEdit("1"))
    bridge = RemoteBridge(ctx)

    bridge._do_set_param("anima_weight", "0.850")

    assert ctx.main_window.anima_weight_edit.text() == "0.85"
    saved = json.loads(Path("app_settings.json").read_text(encoding="utf-8"))
    assert saved["remote_web"]["random_prompt_weight"] == "0.85"


def test_webui_desktop_snapshot_uses_saved_remote_prompt_weight(tmp_path, monkeypatch):
    class _ValueWidget:
        def __init__(self, value, minimum=1, maximum=50):
            self._value = value
            self._minimum = minimum
            self._maximum = maximum

        def value(self):
            return self._value

        def minimum(self):
            return self._minimum

        def maximum(self):
            return self._maximum

    class _WebuiContext(_AppContext):
        def get_api_mode(self):
            return "WEBUI"

    monkeypatch.chdir(tmp_path)
    Path("app_settings.json").write_text(
        json.dumps({"remote_web": {"random_prompt_weight": "0.85"}}),
        encoding="utf-8",
    )
    ctx = _WebuiContext()
    ctx.main_window = SimpleNamespace(
        model_combo=_FakeComboBox(["desktop-webui-model"], "desktop-webui-model"),
        sampler_combo=_FakeComboBox(["Euler a"], "Euler a"),
        scheduler_combo=_FakeComboBox(["Automatic"], "Automatic"),
        resolution_combo=_FakeComboBox(["832 x 1216"], "832 x 1216"),
        steps_spinbox=_ValueWidget(28),
        cfg_scale_slider=_ValueWidget(50),
        cfg_rescale_slider=_ValueWidget(40),
        seed_input=_FakeLineEdit("-1"),
        seed_fix_checkbox=_FakeCheckBox(False),
        random_resolution_checkbox=_FakeCheckBox(False),
        auto_fit_resolution_checkbox=_FakeCheckBox(False),
        advanced_checkboxes={},
        enable_hr_checkbox=_FakeCheckBox(True),
        hr_scale_spinbox=_ValueWidget(3.0),
        hr_upscaler_combo=_FakeComboBox(["Latent"], "Latent"),
        denoising_strength_spinbox=_ValueWidget(0.5),
        hires_steps_spinbox=_ValueWidget(12),
        hr_cfg_spinbox=_ValueWidget(7.0),
        anima_weight_edit=_FakeLineEdit("1"),
    )
    bridge = RemoteBridge(ctx)

    params = bridge.get_generation_params()

    assert params["api_mode"] == "WEBUI"
    assert params["anima_weight"] == "0.85"
    assert params["anima_weight_raw"] == "0.85"
    assert params["random_prompt_weight"] == "0.85"


def test_remote_web_resolution_state_keeps_saved_webui_items_with_anima_model(tmp_path, monkeypatch):
    class _WebuiContext(_AppContext):
        def get_api_mode(self):
            return "WEBUI"

    monkeypatch.chdir(tmp_path)
    ctx = _WebuiContext()
    ctx.main_window = SimpleNamespace(
        model_combo=_FakeComboBox(["anima-preview3-base"], "anima-preview3-base"),
        resolution_combo=_FakeComboBox(["1024 x 1024"], "1024 x 1024"),
        resolutions=["640 x 640"],
        _load_resolutions=lambda mode=None: ["640 x 640"],
    )
    bridge = RemoteBridge(ctx)

    state = bridge._resolution_manager_state("WEBUI")

    assert state["api_mode"] == "WEBUI"
    assert state["current_resolution"] == "1024 x 1024"
    assert state["resolutions"] == ["1024 x 1024"]
    assert state["defaults"] == bridge.DEFAULT_RESOLUTIONS


def test_remote_web_resolution_preset_param_is_saved_by_mode(tmp_path, monkeypatch):
    class _ComfyContext(_AppContext):
        def get_api_mode(self):
            return "COMFYUI"

    monkeypatch.chdir(tmp_path)
    ctx = _ComfyContext()
    bridge = RemoteBridge(ctx)

    bridge._do_set_param("resolution_preset_enabled", "true")
    bridge._do_set_param("resolution_preset", "max")

    saved = json.loads(Path("app_settings.json").read_text(encoding="utf-8"))
    assert saved["remote_web"]["resolution_preset"]["COMFYUI"] == {
        "enabled": True,
        "preset": "max",
    }
    assert bridge.get_generation_param_schema()["resolution_preset_enabled"] is True
    assert bridge.get_generation_param_schema()["resolution_preset"] == "max"


def test_remote_web_resolution_param_clears_detected_auto_resolution(tmp_path, monkeypatch):
    class _WebuiContext(_AppContext):
        def get_api_mode(self):
            return "WEBUI"

    monkeypatch.chdir(tmp_path)
    cleared = []
    ctx = _WebuiContext()
    ctx.main_window = SimpleNamespace(
        resolution_combo=_FakeComboBox(["1024 x 1024"], "1024 x 1024"),
        auto_fit_resolution_checkbox=_FakeCheckBox(True),
        clear_detected_resolution_override=lambda: cleared.append(True),
    )
    bridge = RemoteBridge(ctx)

    bridge._do_set_param("resolution", "1024 x 1024")
    bridge._do_set_param("auto_fit_resolution", "false")

    assert len(cleared) == 2


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


def test_desktop_option_hook_broadcasts_shared_options_only():
    ctx = _AppContext()
    ctx.main_window = SimpleNamespace(
        generation_checkboxes={
            "프롬프트 고정": _FakeCheckBox(True),
            "자동 생성": _FakeCheckBox(False),
            "와일드카드 단독 모드": _FakeCheckBox(True),
        },
    )
    bridge = RemoteBridge(ctx)
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
    bridge.on_save_directory_changed({})
    bridge.on_comfyui_workflow_changed({})

    assert bridge._cached_prompts == {}
    assert bridge._cached_options == {
        "type": "options",
        "prompt_fixed": True,
        "auto_generate": False,
        "wildcard_standalone": True,
        "auto_save": False,
    }
    assert bridge._cached_params == schema
    assert bridge._cached_result_enhance_config == {}
    assert broadcasts == [bridge._cached_options]


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


def test_webui_result_enhance_context_uses_current_hires_settings_snapshot():
    image = Image.new("RGB", (320, 384), "white")
    item = SimpleNamespace(
        image=image,
        generation_params={
            "input": "1girl",
            "negative_prompt": "",
            "seed": 123,
            "width": 512,
            "height": 640,
            "type": "inpaint",
            "image_bytes": b"stale",
            "mask_bytes": b"stale-mask",
            "hr_scale": 1.1,
            "denoising_strength": 0.2,
            "hires_steps": 4,
            "hr_cfg": 3.0,
        },
    )
    image_window = SimpleNamespace(
        auto_save_checkbox=object(),
        current_history_item=item,
    )
    ctx = _AppContext()
    ctx.get_api_mode = lambda: "WEBUI"
    ctx.secure_token_manager = _TokenManager({"webui_url": "127.0.0.1:7860"})
    ctx.main_window = SimpleNamespace(image_window=image_window)
    bridge = RemoteBridge(ctx)

    context = bridge._prepare_result_enhance_context({
        "mode": "WEBUI",
        "hires_settings": {
            "hr_scale": 3,
            "hr_upscaler": "Latent (nearest-exact)",
            "denoising_strength": 0.7,
            "hires_steps": 10,
            "hr_cfg": 5.5,
            "webui_hiresfix_assist": True,
            "webui_hiresfix_assist_target": 768,
        },
    }, mode="WEBUI")

    params = context["params"]
    assert context["api_mode"] == "WEBUI"
    assert context["upscale"] == 3.0
    assert context["strength"] == 0.7
    assert context["hr_upscaler"] == "Latent (nearest-exact)"
    assert params["api_mode"] == "WEBUI"
    assert params["credential"] == "127.0.0.1:7860"
    assert params["enable_hr"] is True
    assert params["hr_scale"] == 3.0
    assert params["denoising_strength"] == 0.7
    assert params["hires_steps"] == 10
    assert params["hr_cfg"] == 5.5
    assert params["webui_hiresfix_assist"] is True
    assert params["webui_hiresfix_assist_target"] == 768
    assert "image_bytes" not in params
    assert "mask_bytes" not in params
    assert "type" not in params


def test_webui_result_enhance_context_locks_random_seed_and_resolution():
    image = Image.new("RGB", (512, 640), "white")
    item = SimpleNamespace(
        image=image,
        info_text=(
            "1girl\n"
            "Negative prompt: bad\n"
            "Steps: 28, Sampler: Euler a, CFG scale: 5, "
            "Seed: 987654321, Size: 512x640"
        ),
        generation_params={
            "input": "1girl",
            "negative_prompt": "bad",
            "seed": -1,
            "seed_fixed": False,
            "width": 512,
            "height": 640,
            "resolution": "512 x 640",
            "random_resolution": True,
            "resolution_preset_enabled": True,
            "resolution_preset": "draft",
        },
    )
    image_window = SimpleNamespace(
        auto_save_checkbox=object(),
        current_history_item=item,
    )
    ctx = _AppContext()
    ctx.get_api_mode = lambda: "WEBUI"
    ctx.secure_token_manager = _TokenManager({"webui_url": "127.0.0.1:7860"})
    ctx.main_window = SimpleNamespace(image_window=image_window)
    bridge = RemoteBridge(ctx)

    context = bridge._prepare_result_enhance_context({
        "mode": "WEBUI",
        "hires_settings": {
            "hr_scale": 2,
            "hr_upscaler": "Latent",
            "denoising_strength": 0.55,
            "hires_steps": 12,
            "hr_cfg": 6,
        },
    }, mode="WEBUI")

    params = context["params"]
    assert params["seed"] == 987654321
    assert params["seed_fixed"] is True
    assert params["random_resolution"] is False
    assert params["resolution_preset_enabled"] is False
    assert params["resolution"] == "512 x 640"
    assert params["width"] == 512
    assert params["height"] == 640
    assert context["new_w"] == 1024
    assert context["new_h"] == 1280


def test_webui_result_enhance_caps_final_size_with_hiresfix_limit():
    from core.api_service import APIService

    image = Image.new("RGB", (512, 768), "white")
    item = SimpleNamespace(
        image=image,
        generation_params={
            "input": "1girl",
            "negative_prompt": "",
            "seed": 123,
            "width": 512,
            "height": 768,
        },
    )
    image_window = SimpleNamespace(
        auto_save_checkbox=object(),
        current_history_item=item,
    )
    ctx = _AppContext()
    ctx.get_api_mode = lambda: "WEBUI"
    ctx.secure_token_manager = _TokenManager({"webui_url": "127.0.0.1:7860"})
    ctx.main_window = SimpleNamespace(image_window=image_window)
    ctx.api_service = APIService(ctx)
    bridge = RemoteBridge(ctx)

    context = bridge._prepare_result_enhance_context({
        "mode": "WEBUI",
        "hires_settings": {
            "hr_scale": 3,
            "hr_upscaler": "Latent (nearest-exact)",
            "denoising_strength": 0.7,
            "hires_steps": 10,
            "hr_cfg": 5.5,
        },
    }, mode="WEBUI")

    params = context["params"]
    assert params["width"] == 512
    assert params["height"] == 768
    assert params["hr_scale"] == 2.4
    assert context["upscale"] == 2.4
    assert context["new_w"] * context["new_h"] <= 1536 * 1536
    assert context["new_w"] == 1229
    assert context["new_h"] == 1843


class _EnhanceQueueManager:
    def __init__(self, paused=False):
        self.requests = []
        self._paused = paused

    def enqueue_request(self, request):
        self.requests.append(request)
        return request.request_id

    def remove_request(self, request_id):
        for index, request in enumerate(self.requests):
            if request.request_id == request_id:
                del self.requests[index]
                return True
        return False

    def clear_queue(self):
        self.requests.clear()

    def is_paused(self):
        return self._paused

    def is_empty(self):
        return not self.requests

    def get_queue_size(self):
        return len(self.requests)

    def get_all_requests(self):
        return list(self.requests)

    def get_queue_stats(self):
        return {
            "is_paused": self._paused,
            "total": len(self.requests),
            "has_urgent": False,
            "priority_counts": {0: len(self.requests)},
        }


def test_webui_result_enhance_queues_generation_request_when_generation_is_busy():
    image = Image.new("RGB", (320, 384), "white")
    item = SimpleNamespace(
        image=image,
        generation_params={
            "input": "1girl",
            "negative_prompt": "",
            "seed": 123,
            "width": 512,
            "height": 640,
        },
        source_row=None,
    )
    image_window = SimpleNamespace(
        auto_save_checkbox=object(),
        current_history_item=item,
    )
    queue_manager = _EnhanceQueueManager()
    ctx = _AppContext()
    ctx.get_api_mode = lambda: "WEBUI"
    ctx.secure_token_manager = _TokenManager({"webui_url": "127.0.0.1:7860"})
    ctx.generation_queue_manager = queue_manager
    ctx.main_window = SimpleNamespace(
        image_window=image_window,
        generation_controller=SimpleNamespace(
            is_generating=True,
            _process_next_queue_request=lambda: None,
        ),
    )
    bridge = RemoteBridge(ctx)
    broadcasts = []
    sent = []
    bridge._broadcast_json = broadcasts.append
    bridge._send_json_to = lambda ws, data: sent.append(data)

    bridge._do_result_enhance(
        ws=_ws("127.0.0.1"),
        payload_json=json.dumps({
            "mode": "WEBUI",
            "hires_settings": {
                "hr_scale": 3,
                "hr_upscaler": "Latent (nearest-exact)",
                "denoising_strength": 0.7,
                "hires_steps": 10,
                "hr_cfg": 5.5,
            },
        }),
    )

    assert len(queue_manager.requests) == 1
    params = queue_manager.requests[0].params
    assert params["api_mode"] == "WEBUI"
    assert params["result_enhance_request"] is True
    assert params["result_enhance_backend"] == "WEBUI"
    assert params["enable_hr"] is True
    assert params["hr_scale"] == 3.0
    assert params["denoising_strength"] == 0.7
    assert params["_remote_queue_source"] == "WEBUI Enhance"
    assert "image_bytes" not in params
    assert "mask_bytes" not in params
    assert bridge._remote_enhance_in_flight is True
    assert broadcasts[0] == {
        "type": "result_enhance_state",
        "running": True,
        "message": "Enhance queued",
    }
    assert sent == [{"type": "toast", "message": "Enhance queued", "level": "success"}]


def test_webui_result_enhance_allows_multiple_queue_requests_while_running():
    image = Image.new("RGB", (320, 384), "white")
    item = SimpleNamespace(
        image=image,
        generation_params={
            "input": "1girl",
            "negative_prompt": "",
            "seed": 123,
            "width": 512,
            "height": 640,
        },
        source_row=None,
    )
    image_window = SimpleNamespace(
        auto_save_checkbox=object(),
        current_history_item=item,
    )
    queue_manager = _EnhanceQueueManager()
    ctx = _AppContext()
    ctx.get_api_mode = lambda: "WEBUI"
    ctx.secure_token_manager = _TokenManager({"webui_url": "127.0.0.1:7860"})
    ctx.generation_queue_manager = queue_manager
    ctx.main_window = SimpleNamespace(
        image_window=image_window,
        generation_controller=SimpleNamespace(
            is_generating=True,
            _process_next_queue_request=lambda: None,
        ),
    )
    bridge = RemoteBridge(ctx)
    broadcasts = []
    sent = []
    bridge._broadcast_json = broadcasts.append
    bridge._send_json_to = lambda ws, data: sent.append(data)
    payload = json.dumps({
        "mode": "WEBUI",
        "hires_settings": {
            "hr_scale": 3,
            "hr_upscaler": "Latent (nearest-exact)",
            "denoising_strength": 0.7,
            "hires_steps": 10,
            "hr_cfg": 5.5,
        },
    })

    bridge._do_result_enhance(ws=_ws("127.0.0.1"), payload_json=payload)
    bridge._do_result_enhance(ws=_ws("127.0.0.1"), payload_json=payload)

    assert len(queue_manager.requests) == 2
    assert len({request.request_id for request in queue_manager.requests}) == 2
    assert {request.request_id for request in queue_manager.requests} == bridge._remote_webui_enhance_request_ids
    assert bridge._remote_enhance_in_flight is True
    assert [data["message"] for data in broadcasts if data.get("type") == "result_enhance_state"] == [
        "Enhance queued",
        "Enhance queued",
    ]
    assert sent == [
        {"type": "toast", "message": "Enhance queued", "level": "success"},
        {"type": "toast", "message": "Enhance queued", "level": "success"},
    ]


def test_webui_result_enhance_completion_keeps_state_running_until_tracked_queue_empty():
    bridge = RemoteBridge(_AppContext())
    bridge._remote_enhance_in_flight = True
    bridge._remote_enhance_api_mode = "WEBUI"
    bridge._remote_webui_enhance_request_ids = {"enhance-1", "enhance-2"}
    broadcasts = []
    bridge._broadcast_json = broadcasts.append

    bridge.on_result_enhance_completed(True, "Enhance complete", "enhance-1")

    assert bridge._remote_enhance_in_flight is True
    assert bridge._remote_enhance_api_mode == "WEBUI"
    assert bridge._remote_webui_enhance_request_ids == {"enhance-2"}
    assert broadcasts[-1] == {
        "type": "result_enhance_state",
        "running": True,
        "success": True,
        "message": "Enhance complete",
    }

    bridge.on_result_enhance_completed(True, "Enhance complete", "enhance-2")

    assert bridge._remote_enhance_in_flight is False
    assert bridge._remote_enhance_api_mode == ""
    assert bridge._remote_enhance_request_id == ""
    assert bridge._remote_webui_enhance_request_ids == set()
    assert broadcasts[-1] == {
        "type": "result_enhance_state",
        "running": False,
        "success": True,
        "message": "Enhance complete",
    }


def test_webui_result_enhance_queue_remove_clears_enhance_state():
    queue_manager = _EnhanceQueueManager()
    request = SimpleNamespace(
        request_id="enhance-1",
        params={"result_enhance_request": True, "result_enhance_backend": "WEBUI"},
        priority=0,
        status="pending",
        created_at=None,
        started_at=None,
        completed_at=None,
    )
    queue_manager.requests.append(request)
    ctx = _AppContext()
    ctx.generation_queue_manager = queue_manager
    bridge = RemoteBridge(ctx)
    bridge._remote_enhance_in_flight = True
    bridge._remote_enhance_api_mode = "WEBUI"
    bridge._remote_enhance_request_id = "enhance-1"
    broadcasts = []
    bridge._broadcast_json = broadcasts.append

    bridge._do_queue_action(json.dumps({"action": "remove", "request_id": "enhance-1"}))

    assert queue_manager.requests == []
    assert bridge._remote_enhance_in_flight is False
    assert bridge._remote_enhance_api_mode == ""
    assert bridge._remote_enhance_request_id == ""
    assert broadcasts == [
        {
            "type": "result_enhance_state",
            "running": False,
            "success": False,
            "message": "Enhance canceled",
        }
    ]


def test_webui_result_enhance_completion_records_webui_metadata_without_credential():
    source_item = SimpleNamespace(
        image=Image.new("RGB", (320, 384), "white"),
        info_text="source",
        source_row=None,
        generation_params={"input": "1girl"},
        prompt_context={},
        api_metadata={},
    )
    history = []
    image_window = SimpleNamespace(
        add_to_history=lambda *args, **kwargs: history.append(kwargs["generation_result"]),
    )
    ctx = _AppContext()
    published = []
    ctx.publish = lambda event, payload: published.append((event, payload))
    bridge = RemoteBridge(ctx)
    completions = []
    bridge.on_result_enhance_completed = lambda success, message: completions.append((success, message))
    context = {
        "api_mode": "WEBUI",
        "image_window": image_window,
        "item": source_item,
        "params": {
            "input": "1girl",
            "credential": "http://127.0.0.1:7860",
            "enable_hr": True,
            "hr_scale": 3.0,
            "hr_upscaler": "Latent (nearest-exact)",
            "denoising_strength": 0.7,
            "hires_steps": 10,
            "hr_cfg": 5.5,
            "api_mode": "WEBUI",
        },
        "orig_w": 320,
        "orig_h": 384,
        "new_w": 960,
        "new_h": 1152,
        "upscale": 3.0,
        "strength": 0.7,
        "hr_upscaler": "Latent (nearest-exact)",
        "hires_steps": 10,
        "hr_cfg": 5.5,
    }

    bridge._handle_remote_result_enhance(
        {"status": "success", "image": Image.new("RGB", (960, 1152), "white")},
        context,
    )

    generation_result = history[0]
    params = generation_result["generation_params"]
    assert completions == [(True, "Enhance complete")]
    assert published == [("generation_result_available", generation_result)]
    assert generation_result["backend_type"] == "WEBUI"
    assert "denoise=0.7" in generation_result["info"]
    assert params["api_mode"] == "WEBUI"
    assert params["width"] == 960
    assert params["height"] == 1152
    assert params["enable_hr"] is True
    assert params["hr_scale"] == 3.0
    assert params["denoising_strength"] == 0.7
    assert "credential" not in params
    assert generation_result["api_metadata"]["enhance_backend"] == "WEBUI"
    assert generation_result["api_metadata"]["result_size"] == (960, 1152)


def test_generation_worker_records_webui_result_enhance_metadata_without_credential():
    from core.generation_controller import GenerationWorker

    worker = GenerationWorker(SimpleNamespace())
    worker.params = {
        "input": "1girl",
        "negative_prompt": "",
        "credential": "http://127.0.0.1:7860",
        "api_mode": "WEBUI",
        "result_enhance_request": True,
        "result_enhance_backend": "WEBUI",
        "result_enhance_upscale": 3.0,
        "result_enhance_strength": 0.7,
        "result_enhance_hr_upscaler": "Latent (nearest-exact)",
        "result_enhance_hires_steps": 10,
        "result_enhance_hr_cfg": 5.5,
        "result_enhance_source_size": [320, 384],
    }
    worker.source_row = pd.Series({"general": None}, name="webui_result_enhance")
    worker._main_prompt_text = "1girl"
    result = {
        "image": Image.new("RGB", (960, 1152), "white"),
        "info": "source",
    }

    worker._collect_enhanced_metadata(result)

    params = result["generation_params"]
    assert "credential" not in params
    assert params["result_enhance_request"] is True
    assert result["backend_type"] == "WEBUI"
    assert "Enhanced: x3" in result["info"]
    assert "denoise=0.7" in result["info"]
    assert result["api_metadata"]["enhanced"] is True
    assert result["api_metadata"]["enhance_backend"] == "WEBUI"
    assert result["api_metadata"]["source_size"] == (320, 384)
    assert result["api_metadata"]["result_size"] == (960, 1152)


def test_generation_worker_promotes_webui_response_seed_for_replay():
    from core.generation_controller import GenerationWorker

    worker = GenerationWorker(SimpleNamespace())
    worker.params = {
        "input": "1girl",
        "negative_prompt": "bad",
        "credential": "http://127.0.0.1:7860",
        "api_mode": "WEBUI",
        "seed": -1,
        "seed_fixed": False,
    }
    worker.source_row = pd.Series({"general": None}, name="webui")
    worker._main_prompt_text = "1girl"
    infotext = (
        "1girl\n"
        "Negative prompt: bad\n"
        "Steps: 28, Sampler: Euler a, CFG scale: 5, "
        "Seed: 246813579, Size: 512x640"
    )
    result = {
        "image": Image.new("RGB", (512, 640), "white"),
        "info": "AI 생성 이미지가 아니거나, 인식할 수 있는 메타데이터가 없습니다.",
        "generation_info": json.dumps({
            "all_seeds": [246813579],
            "infotexts": [infotext],
        }),
    }

    worker._collect_enhanced_metadata(result)

    params = result["generation_params"]
    assert params["seed"] == 246813579
    assert params["seed_fixed"] is True
    assert result["info"] == infotext
    assert result["api_metadata"]["webui_seed"] == 246813579


def test_result_enhance_generation_error_clears_enhance_state_without_duplicate_toast():
    bridge = RemoteBridge(_AppContext())
    broadcasts = []
    bridge._broadcast_json = broadcasts.append

    bridge.on_generation_error({"message": "WEBUI failed", "result_enhance_request": True})

    assert broadcasts == [
        {
            "type": "result_enhance_state",
            "running": False,
            "success": False,
            "message": "WEBUI failed",
        },
        {"type": "toast", "message": "WEBUI failed", "level": "error"},
        {"type": "status", "is_generating": False},
    ]


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


class _SavingImageCrud(_ImageCrud):
    def __init__(self, save_dir):
        super().__init__(save_dir)
        self.saved = []

    def get_classification_method(self):
        return "none"

    def save_image(self, image_bytes, as_webp=False, classification_info=None, metadata=None):
        self._save_dir.mkdir(parents=True, exist_ok=True)
        suffix = "webp" if as_webp else "png"
        path = self._save_dir / f"{len(self.saved) + 1:05d}.{suffix}"
        path.write_bytes(bytes(image_bytes))
        self.saved.append({
            "path": path,
            "as_webp": as_webp,
            "classification_info": classification_info,
        })
        return True, str(path), None


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


def _png_bytes(color):
    buf = io.BytesIO()
    Image.new("RGB", (2, 2), color).save(buf, format="PNG")
    return buf.getvalue()


def _bridge_with_unsaved_history(tmp_path, count=2):
    save_dir = tmp_path / "output" / "20260501_120000"
    crud = _SavingImageCrud(save_dir)
    items = []
    for index in range(count):
        image = Image.new("RGB", (2, 2), (index * 30, 0, 0))
        items.append(SimpleNamespace(
            filepath="",
            image=image,
            raw_bytes=_png_bytes((index * 30, 0, 0)),
            info_text=f"prompt {index}",
            generation_params={"input": f"prompt {index}"},
            prompt_context={},
            source_row=None,
            backend_type="NAI",
        ))
    widgets = [SimpleNamespace(history_item=item) for item in items]
    history_window = SimpleNamespace(history_widgets=widgets)
    image_window = SimpleNamespace(
        auto_save_checkbox=_FakeCheckBox(False),
        save_as_webp_checkbox=_FakeCheckBox(False),
        image_history_window=history_window,
        current_history_item=items[0] if items else None,
    )
    image_window._create_classification_info = lambda item: {
        "method": "none",
        "prompt": getattr(item, "info_text", ""),
        "image_size": getattr(item.image, "size", (0, 0)),
        "tags": [],
        "backend_type": "NAI",
    }
    ctx = _AppContext()
    ctx.image_crud_controller = crud
    ctx.main_window = SimpleNamespace(image_window=image_window)
    bridge = RemoteBridge(ctx)
    return bridge, crud, items


def test_memory_history_uses_stable_path_when_save_directory_changes(tmp_path):
    bridge, image_path = _bridge_with_history(tmp_path)

    entries = bridge._scan_memory_history()

    assert len(entries) == 1
    history_key = entries[0]["rel_path"]
    assert history_key.startswith(RemoteBridge.HISTORY_ITEM_PATH_PREFIX)
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


def test_auto_save_state_counts_unsaved_history_items(tmp_path):
    bridge, _crud, _items = _bridge_with_unsaved_history(tmp_path, count=2)

    state = bridge._read_auto_save_settings()

    assert state["unsaved_history_count"] == 2


def test_save_all_unsaved_history_items_writes_to_save_folder(tmp_path):
    bridge, crud, items = _bridge_with_unsaved_history(tmp_path, count=2)

    result = bridge._save_all_unsaved_history_items()

    assert result["ok"] is True
    assert result["saved"] == 2
    assert result["remaining"] == 0
    assert len(crud.saved) == 2
    assert all(Path(item.filepath).exists() for item in items)
    assert bridge._read_auto_save_settings()["unsaved_history_count"] == 0


def test_unsaved_history_download_endpoint_returns_zip(tmp_path):
    bridge, _crud, _items = _bridge_with_unsaved_history(tmp_path, count=2)

    async def fake_history_action(action, payload=None, timeout=30.0):
        assert action == "collect_unsaved_download"
        return bridge._collect_unsaved_history_download_entries()

    bridge._request_result_history_action = fake_history_action
    client = TestClient(create_app(bridge, WebSocketManager()))

    response = client.get("/api/history/unsaved/download")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/zip")
    with zipfile.ZipFile(io.BytesIO(response.content), "r") as zf:
        names = zf.namelist()
        assert len(names) == 2
        assert all(name.startswith("history-") for name in names)


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


def test_current_result_asset_allows_webui_enhance_but_blocks_nai_image_actions(tmp_path):
    bridge, _image_path = _bridge_with_history(tmp_path, mode="WEBUI")

    asset = bridge._build_current_result_asset_payload()

    assert asset["can_enhance"] is True
    assert asset["capabilities"]["image_action"] is False
    assert asset["capabilities"]["inpaint"] is False
    assert asset["capabilities"]["enhance"] is True
    assert asset["capabilities"]["upscale_nai"] is False


def test_saved_result_asset_allows_webui_enhance_but_blocks_nai_image_actions(tmp_path):
    bridge, _image_path = _bridge_with_history(tmp_path, mode="WEBUI")
    history_key = bridge._scan_memory_history()[0]["rel_path"]

    asset = bridge._build_saved_result_asset_payload(history_key)

    assert asset["can_enhance"] is True
    assert asset["capabilities"]["image_action"] is False
    assert asset["capabilities"]["enhance"] is True
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

    async def fake_request_clipboard_png(timeout=2.0):
        return image_path.read_bytes()

    bridge._request_clipboard_png = fake_request_clipboard_png
    client = TestClient(create_app(bridge, WebSocketManager()))

    response = client.post(
        "/api/result/clipboard/png",
        json={"source": "saved", "path": history_key},
    )

    assert response.status_code == 200
    assert response.json()["filename"] == "00001.png"
    assert response.json()["bytes"] == len(image_path.read_bytes())


def test_clipboard_png_read_endpoint_returns_png_bytes():
    bridge = RemoteBridge(_AppContext())

    async def fake_request_clipboard_png(timeout=2.0):
        return b"\x89PNG\r\n\x1a\nclipboard-png"

    bridge._request_clipboard_png = fake_request_clipboard_png
    client = TestClient(create_app(bridge, WebSocketManager()))

    response = client.get("/api/clipboard/png")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.content == b"\x89PNG\r\n\x1a\nclipboard-png"


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


def test_artist_thumb_favorite_add_copies_loaded_thumbnail_cache(tmp_path, monkeypatch):
    bridge = _bridge_with_artist_thumb_lists(tmp_path, monkeypatch)
    bridge._artist_thumb_data_cache["NAID4.5F-31000"] = {"c": ["thumb_c"]}

    bridge._set_artist_thumb_favorite("c", True, "NAID4.5F-31000")

    cache = json.loads(Path("artist_thumb/favorite_thumbnail_cache.json").read_text(encoding="utf-8"))
    assert cache["items"]["c"]["mode"] == "NAID4.5F-31000"
    assert cache["items"]["c"]["thumbnail"] == "thumb_c"

    bridge._set_artist_thumb_favorite("c", False, "NAID4.5F-31000")

    cache = json.loads(Path("artist_thumb/favorite_thumbnail_cache.json").read_text(encoding="utf-8"))
    assert "c" not in cache["items"]


def test_artist_thumb_favorite_state_survives_corrupt_thumbnail_cache(tmp_path, monkeypatch):
    bridge = _bridge_with_artist_thumb_lists(tmp_path, monkeypatch)
    Path("artist_thumb/favorite_thumbnail_cache.json").write_text("{", encoding="utf-8")
    bridge._artist_thumb_data_cache["NAID4.5F-31000"] = {"c": ["thumb_c"]}

    bridge._set_artist_thumb_favorite("c", True, "NAID4.5F-31000")

    state = json.loads(Path("artist_thumb/artist_state.json").read_text(encoding="utf-8"))
    cache = json.loads(Path("artist_thumb/favorite_thumbnail_cache.json").read_text(encoding="utf-8"))
    assert "c" in state["favorites"]
    assert cache["items"]["c"]["thumbnail"] == "thumb_c"


def test_artist_thumb_favorites_list_uses_cached_thumbnail_without_mode(tmp_path, monkeypatch):
    bridge = _bridge_with_artist_thumb_lists(tmp_path, monkeypatch)
    Path("artist_thumb/favorite_thumbnail_cache.json").write_text(
        json.dumps({
            "version": 1,
            "items": {
                "a": {
                    "mode": "NAID4.5F-31000",
                    "thumbnail": "thumb_a",
                    "updated_at": "2026-05-05T00:00:00",
                },
            },
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    payload = bridge._build_artist_thumb_list("", "favorites", "", 0, 48)

    assert [item["artist"] for item in payload["items"]] == ["a"]
    assert payload["items"][0]["has_image"] is True
    assert payload["items"][0]["image_url"] == "/api/artist-thumb/favorite-image?artist=a"


def test_artist_thumb_nai_data_load_syncs_missing_favorite_thumbnail_cache(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("artist_thumb").mkdir()
    Path("data").mkdir()
    Path("artist_thumb/artist_state.json").write_text(
        json.dumps({"version": 1, "favorites": ["a", "c"], "banned": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    Path("artist_thumb/favorite_thumbnail_cache.json").write_text(
        json.dumps({
            "version": 1,
            "items": {
                "a": {"mode": "NAID4.5F-31000", "thumbnail": "thumb_a"},
                "stale": {"mode": "NAID4.5F-31000", "thumbnail": "thumb_stale"},
            },
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    Path("data/artist_thumbnail_nai.json").write_text(
        json.dumps({"a": ["thumb_a"], "c": ["thumb_c"]}, ensure_ascii=False),
        encoding="utf-8",
    )
    bridge = RemoteBridge(_AppContext())

    bridge._load_artist_thumb_data("NAID4.5F-31000")

    cache = json.loads(Path("artist_thumb/favorite_thumbnail_cache.json").read_text(encoding="utf-8"))
    assert set(cache["items"]) == {"a", "c"}
    assert cache["items"]["c"]["thumbnail"] == "thumb_c"


def test_artist_thumb_anima_mode_uses_configured_local_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("data").mkdir()
    Path("data/artist_thumbnail_anima.json").write_text(
        json.dumps({"a": ["thumb_a"]}, ensure_ascii=False),
        encoding="utf-8",
    )
    bridge = RemoteBridge(_AppContext())
    mode_info = dict(bridge.ARTIST_THUMB_MODES["ANIMA-14000"])
    mode_info["expected_size"] = Path("data/artist_thumbnail_anima.json").stat().st_size
    monkeypatch.setitem(bridge.ARTIST_THUMB_MODES, "ANIMA-14000", mode_info)
    bridge._artist_thumb_artist_weights = lambda: {"a": 10}

    state = bridge._build_artist_thumb_state()
    anima = next(mode for mode in state["modes"] if mode["key"] == "ANIMA-14000")

    assert anima["available"] is True
    assert anima["needs_update"] is False
    assert anima["size_mb"] >= 0
    assert bridge._load_artist_thumb_data("ANIMA-14000") == {"a": ["thumb_a"]}


def test_artist_thumb_anima_mode_reports_update_for_old_local_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("data").mkdir()
    old_file = Path("data/artist_thumbnail_anima.json")
    old_file.write_text(json.dumps({"a": ["thumb_a"]}, ensure_ascii=False), encoding="utf-8")
    bridge = RemoteBridge(_AppContext())
    bridge._artist_thumb_artist_weights = lambda: {"a": 10}

    state = bridge._build_artist_thumb_state()
    anima = next(mode for mode in state["modes"] if mode["key"] == "ANIMA-14000")

    assert anima["available"] is False
    assert anima["needs_update"] is True
    assert anima["size"] == old_file.stat().st_size
    assert anima["expected_size"] == 1699850378
    with pytest.raises(RuntimeError, match="needs update"):
        bridge._load_artist_thumb_data("ANIMA-14000")


def test_artist_thumb_download_validation_checks_sha256(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("data").mkdir()
    payload = b"x" * (1024 * 1024 + 7)
    target = Path("data/artist_thumbnail_anima.json.tmp")
    target.write_bytes(payload)
    bridge = RemoteBridge(_AppContext())
    mode_info = dict(bridge.ARTIST_THUMB_MODES["ANIMA-14000"])
    mode_info["expected_size"] = len(payload)
    mode_info["sha256"] = hashlib.sha256(payload).hexdigest().upper()
    monkeypatch.setitem(bridge.ARTIST_THUMB_MODES, "ANIMA-14000", mode_info)

    assert bridge._validate_artist_thumb_download_file("ANIMA-14000", target) == len(payload)

    mode_info["sha256"] = "0" * 64
    monkeypatch.setitem(bridge.ARTIST_THUMB_MODES, "ANIMA-14000", mode_info)
    with pytest.raises(ValueError, match="해시"):
        bridge._validate_artist_thumb_download_file("ANIMA-14000", target)


def test_artist_thumb_options_are_scoped_by_api_mode(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bridge = RemoteBridge(_AppContext())

    bridge._save_artist_thumb_options({
        "mode": "NAI",
        "prefix": "nai prefix",
        "postfix": "nai postfix",
    })
    bridge._save_artist_thumb_options({
        "mode": "WEBUI",
        "prefix": "webui prefix",
        "postfix": "webui postfix",
    })

    assert bridge._load_artist_thumb_options("NAI")["prefix"] == "nai prefix"
    assert bridge._load_artist_thumb_options("NAI")["postfix"] == "nai postfix"
    assert bridge._load_artist_thumb_options("WEBUI")["prefix"] == "webui prefix"
    assert bridge._load_artist_thumb_options("WEBUI")["postfix"] == "webui postfix"

    data = json.loads(Path("artist_thumb/generate_options.json").read_text(encoding="utf-8"))
    assert data["modes"]["NAI"]["prefix"] == "nai prefix"
    assert data["modes"]["WEBUI"]["postfix"] == "webui postfix"
    assert data["modes"]["COMFYUI"] == {"prefix": "", "postfix": ""}


def test_artist_thumb_cached_nai_data_syncs_missing_favorite_thumbnail_cache(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("artist_thumb").mkdir()
    Path("data").mkdir()
    Path("artist_thumb/artist_state.json").write_text(
        json.dumps({"version": 1, "favorites": ["a", "c"], "banned": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    Path("artist_thumb/favorite_thumbnail_cache.json").write_text(
        json.dumps({
            "version": 1,
            "items": {
                "a": {"mode": "NAID4.5F-31000", "thumbnail": "thumb_a"},
            },
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    bridge = RemoteBridge(_AppContext())
    data = {"a": ["thumb_a"], "c": ["thumb_c"]}
    bridge._artist_thumb_data_cache["NAID4.5F-31000"] = data

    loaded = bridge._load_artist_thumb_data("NAID4.5F-31000")

    cache = json.loads(Path("artist_thumb/favorite_thumbnail_cache.json").read_text(encoding="utf-8"))
    assert loaded is data
    assert set(cache["items"]) == {"a", "c"}
    assert cache["items"]["c"]["thumbnail"] == "thumb_c"


def test_artist_thumb_cached_nai_data_skips_complete_thumbnail_cache(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("artist_thumb").mkdir()
    Path("data").mkdir()
    Path("artist_thumb/artist_state.json").write_text(
        json.dumps({"version": 1, "favorites": ["a", "c"], "banned": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    Path("artist_thumb/favorite_thumbnail_cache.json").write_text(
        json.dumps({
            "version": 1,
            "items": {
                "a": {"mode": "NAID4.5F-31000", "thumbnail": "thumb_a"},
                "c": {"mode": "NAID4.5F-31000", "thumbnail": "thumb_c"},
            },
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    bridge = RemoteBridge(_AppContext())
    data = {"a": ["new_thumb_a"], "c": ["new_thumb_c"]}
    bridge._artist_thumb_data_cache["NAID4.5F-31000"] = data

    def fail_if_reindexed(*_args, **_kwargs):
        raise AssertionError("complete favorite thumbnail cache should not be reindexed")

    def fail_if_rewritten(*_args, **_kwargs):
        raise AssertionError("complete favorite thumbnail cache should not be rewritten")

    bridge._artist_thumb_cache_entry_from_data = fail_if_reindexed
    bridge._write_artist_thumb_thumbnail_cache = fail_if_rewritten

    loaded = bridge._load_artist_thumb_data("NAID4.5F-31000")

    cache = json.loads(Path("artist_thumb/favorite_thumbnail_cache.json").read_text(encoding="utf-8"))
    assert loaded is data
    assert cache["items"]["a"]["thumbnail"] == "thumb_a"
    assert cache["items"]["c"]["thumbnail"] == "thumb_c"


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


def test_artist_thumb_random_resolution_normalizes_to_standard_1mp_sizes(tmp_path, monkeypatch):
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

    assert bridge._artist_thumb_resolution_options() == [
        (1024, 1024),
        (896, 1152),
        (832, 1216),
    ]
    assert bridge._coerce_artist_thumb_resolution(4096, 4096) == (1024, 1024)
    assert bridge._coerce_artist_thumb_resolution(1000, 1000) == (1024, 1024)
    assert bridge._coerce_artist_thumb_resolution(4096, 6144) == (832, 1216)
    assert bridge._coerce_artist_thumb_resolution(1536, 2048) == (896, 1152)
    assert bridge._coerce_artist_thumb_resolution(1, 100000) == (832, 1216)
    assert bridge._coerce_artist_thumb_resolution(100000, 1) == (1216, 832)


def test_artist_thumb_random_prompt_fits_detected_resolution_to_standard_1mp(tmp_path, monkeypatch):
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


def test_artist_thumb_generate_coerces_invalid_resolution_to_standard_1mp(tmp_path, monkeypatch):
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


def test_artist_thumb_generate_keeps_active_resolution_request(tmp_path, monkeypatch):
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
        "api_mode": "WEBUI",
        "resolution": "1536 x 1536",
        "width": 1536,
        "height": 1536,
        "resolution_preset_enabled": True,
        "resolution_preset": "max",
        "artist_thumb_use_active_resolution": True,
    })

    overrides, priority = ctx.main_window.generation_controller.executed[0]
    assert priority == 0
    assert overrides["width"] == 1536
    assert overrides["height"] == 1536
    assert overrides["resolution"] == "1536 x 1536"
    assert overrides["resolution_preset_enabled"] is True
    assert overrides["resolution_preset"] == "max"
    assert overrides["artist_thumb_use_active_resolution"] is True


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
