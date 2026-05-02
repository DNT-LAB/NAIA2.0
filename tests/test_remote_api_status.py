import base64
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient
from PIL import Image
from PIL.PngImagePlugin import PngInfo

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
    assert asset["capabilities"]["copy_png"] is True
    assert "copy_webp" not in asset["capabilities"]


def test_current_result_asset_does_not_advertise_webp_clipboard_copy(tmp_path):
    bridge, _image_path = _bridge_with_history(tmp_path)

    asset = bridge._build_current_result_asset_payload()

    assert asset["capabilities"]["copy_png"] is True
    assert "copy_webp" not in asset["capabilities"]


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
