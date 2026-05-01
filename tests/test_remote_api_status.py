from types import SimpleNamespace

from PIL import Image

from core.remote_api_server import RemoteBridge


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


class _ImageCrud:
    def __init__(self, save_dir):
        self._save_dir = save_dir
        self._use_timestamp_folder = True

    def get_save_directory(self):
        return self._save_dir

    def get_use_timestamp_folder(self):
        return self._use_timestamp_folder


def _bridge_with_history(tmp_path):
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
