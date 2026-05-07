from core.api_service import APIService


def _service_with_captured_nai(monkeypatch):
    service = APIService(app_context=None)
    captured = {}

    def fake_call(params):
        captured.update(params)
        return {"status": "success", "image": None}

    monkeypatch.setattr(service, "_call_nai_api", fake_call)
    return service, captured


def test_api_service_does_not_clamp_general_generation_resolution(monkeypatch):
    service, captured = _service_with_captured_nai(monkeypatch)

    service.call_generation_api({
        "api_mode": "NAI",
        "input": "prompt",
        "width": 4000,
        "height": 3000,
    })

    assert captured["width"] == 4000
    assert captured["height"] == 3000


def test_api_service_clamps_artist_thumbnail_resolution(monkeypatch):
    service, captured = _service_with_captured_nai(monkeypatch)

    service.call_generation_api({
        "api_mode": "NAI",
        "input": "prompt",
        "width": 4000,
        "height": 3000,
        "artist_thumb_request": True,
    })

    assert captured["width"] == 1152
    assert captured["height"] == 896
