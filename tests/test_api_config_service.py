from types import SimpleNamespace

from core.api_config_service import ApiConfigService, CloudflaredService
from core.api_verification import VerifyResult
from core.web_session_context import InMemoryTokenManager


def test_api_config_service_verifies_and_persists_nai_token(tmp_path):
    tokens = InMemoryTokenManager()
    service = ApiConfigService(
        tokens,
        timestamp_path=tmp_path / "timestamps.json",
        verify_nai_token=lambda token: VerifyResult(True, "ok", "info", value=token),
    )

    result = service.verify("NAI", "pst-test-token")
    status = service.status_payload(active_mode="NAI", autocomplete={}, client_host="127.0.0.1")

    assert result["success"] is True
    assert tokens.get_token("nai_token") == "pst-test-token"
    assert status["nai_configured"] is True
    assert status["nai_token_preview"] == "pst-tes"
    assert status["setup_required"] is False
    assert status["setup_allowed"] is True
    assert status["last_verified"]["nai"]


def test_api_config_service_verifies_and_persists_backend_urls(tmp_path):
    tokens = InMemoryTokenManager()
    service = ApiConfigService(
        tokens,
        timestamp_path=tmp_path / "timestamps.json",
        verify_webui_url=lambda url: VerifyResult(
            True,
            "webui ok",
            "info",
            value="127.0.0.1:7860",
            extra={"protocol": "http"},
        ),
        verify_comfyui_url=lambda url: VerifyResult(
            True,
            "comfy ok",
            "info",
            value="127.0.0.1:8188",
            extra={"protocol": "http"},
        ),
    )

    webui = service.verify("WEBUI", "127.0.0.1:7860")
    comfy = service.verify("COMFYUI", "127.0.0.1:8188")

    assert webui["success"] is True
    assert comfy["success"] is True
    assert tokens.get_token("webui_url") == "http://127.0.0.1:7860"
    assert tokens.get_token("comfyui_url") == "http://127.0.0.1:8188"
    assert service.status_payload(active_mode="NAI")["setup_required"] is False


def test_api_config_service_probe_and_clear(tmp_path):
    tokens = InMemoryTokenManager({
        "nai_token": "pst-token",
        "webui_url": "http://127.0.0.1:7860",
    })
    service = ApiConfigService(
        tokens,
        timestamp_path=tmp_path / "timestamps.json",
        verify_nai_token=lambda _token: VerifyResult(True, "nai ok", "info"),
        verify_webui_url=lambda _url: VerifyResult(False, "webui fail", "error"),
    )

    assert service.probe() == {"NAI": True, "WEBUI": False, "COMFYUI": None}

    result = service.clear("WEBUI")

    assert result == {
        "type": "clear_api_result",
        "mode": "WEBUI",
        "success": True,
        "message": "연결 해제됨",
        "message_type": "info",
    }
    assert tokens.get_token("webui_url") == ""


def test_cloudflared_service_controls_tunnel_state():
    calls = []

    def start_tunnel(port, on_progress=None):
        calls.append(("start", port))
        if on_progress:
            on_progress("connecting")
        return SimpleNamespace(tunnel_url="https://example.trycloudflare.com")

    def stop_tunnel(port):
        calls.append(("stop", port))

    service = CloudflaredService(
        port=7281,
        start_tunnel=start_tunnel,
        stop_tunnel=stop_tunnel,
    )

    started = service.set_enabled(True)
    stopped = service.set_enabled(False)

    assert started["success"] is True
    assert started["active"] is True
    assert started["url"] == "https://example.trycloudflare.com"
    assert stopped["success"] is True
    assert stopped["active"] is False
    assert calls == [("start", 7281), ("stop", 7281)]
