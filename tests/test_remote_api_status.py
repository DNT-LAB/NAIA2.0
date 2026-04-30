from types import SimpleNamespace

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
