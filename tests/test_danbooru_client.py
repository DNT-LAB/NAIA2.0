from fastapi.testclient import TestClient

from core import danbooru_client
from core.danbooru_client import extract_danbooru_post_id, normalize_danbooru_post_payload
from legacy_desktop.core.remote_api_server import RemoteBridge, WebSocketManager, create_app


class _TokenManager:
    def get_token(self, key):
        return ""


class _AppContext:
    secure_token_manager = _TokenManager()
    cloudflared_active = False
    cloudflared_tunnel_url = ""
    cloudflared_status_text = ""
    main_window = None

    def get_api_mode(self):
        return "NAI"


def test_extract_danbooru_post_id_accepts_id_and_url():
    assert extract_danbooru_post_id("12345") == 12345
    assert extract_danbooru_post_id("https://danbooru.donmai.us/posts/67890?q=foo") == 67890


def test_normalize_danbooru_payload_moves_characteristic_tags():
    payload = {
        "id": 100,
        "tag_string_artist": "test_artist",
        "tag_string_copyright": "test_series",
        "tag_string_character": "test_character",
        "tag_string_general": "solo smile blue_eyes",
        "tag_string_meta": "highres",
        "preview_file_url": "https://cdn.example/preview.jpg",
        "large_file_url": "https://cdn.example/large.jpg",
        "rating": "s",
        "score": 42,
    }

    normalized = normalize_danbooru_post_payload(
        payload,
        characteristic_tags={"solo"},
    )

    assert normalized["post_id"] == 100
    assert normalized["image_url"] == "https://cdn.example/large.jpg"
    assert normalized["tags"]["character"] == ["test character", "solo"]
    assert normalized["tags"]["general"] == ["smile", "blue eyes"]
    assert normalized["tag_counts"]["character"] == 2


def test_danbooru_post_endpoint_uses_public_post_json(monkeypatch):
    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "id": 123,
                "tag_string_general": "solo smile",
                "tag_string_artist": "",
                "tag_string_copyright": "",
                "tag_string_character": "",
                "tag_string_meta": "",
                "preview_file_url": "https://cdn.example/preview.jpg",
                "rating": "g",
                "score": 7,
            }

    def fake_get(url, **kwargs):
        assert url == "https://danbooru.donmai.us/posts/123.json"
        assert kwargs["timeout"] == 12.0
        return _Response()

    monkeypatch.setattr(danbooru_client.requests, "get", fake_get)
    bridge = RemoteBridge(_AppContext())
    bridge._load_characteristic_tags = lambda: set()
    client = TestClient(create_app(bridge, WebSocketManager()))

    response = client.post("/api/danbooru/post", json={"query": "123"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["post_id"] == 123
    assert payload["tags"]["general"] == ["solo", "smile"]
    assert payload["prompt"] == "solo, smile"


def test_danbooru_browser_url_normalization_accepts_id_url_and_tags():
    bridge = RemoteBridge(_AppContext())

    assert bridge._normalize_danbooru_browser_url("123") == "https://danbooru.donmai.us/posts/123"
    assert bridge._normalize_danbooru_browser_url("/posts/456") == "https://danbooru.donmai.us/posts/456"
    assert bridge._normalize_danbooru_browser_url("rating:general 1girl") == (
        "https://danbooru.donmai.us/posts?tags=rating:general%201girl"
    )
