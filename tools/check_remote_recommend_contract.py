"""Check Remote Web recommended-preset synchronization contracts."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
from typing import Any

from fastapi.testclient import TestClient


REPO_ROOT = Path(__file__).resolve().parents[1]
REMOTE_WEB_DIR = REPO_ROOT / "app" / "web" / "remote"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.web_session_app import create_headless_app
from core.web_session_context import InMemoryTokenManager, WebSessionContext


def _context(root: Path) -> WebSessionContext:
    context = WebSessionContext(
        repo_root=root,
        token_manager=InMemoryTokenManager(
            {
                "nai_token": "pst-contract-token",
                "webui_url": "http://127.0.0.1:7860",
                "comfyui_url": "http://127.0.0.1:8188",
            }
        ),
        headless_generation_execute_enabled=False,
    )
    context.refresh_api_options = lambda _mode: {}
    return context


def _client(context: WebSessionContext) -> TestClient:
    return TestClient(create_headless_app(context, web_dir=REMOTE_WEB_DIR))


def _drain_startup(ws: Any) -> None:
    for _ in range(9):
        message = ws.receive_json()
        if message.get("type") == "lazy_indices_ready":
            return
    raise AssertionError("startup messages did not finish")


def _drain_until_lazy(ws: Any, cap: int = 60) -> list[dict[str, Any]]:
    """Collect messages up to and including the ``lazy_indices_ready`` terminator."""
    out: list[dict[str, Any]] = []
    for _ in range(cap):
        message = ws.receive_json()
        out.append(message)
        if message.get("type") == "lazy_indices_ready":
            return out
    raise AssertionError(f"sync terminator not seen; got {[m.get('type') for m in out]!r}")


def _collect_after(ws: Any, command: dict[str, Any]) -> list[dict[str, Any]]:
    """Send ``command`` then a ``sync`` and return every message they produced.

    Draining to the ``sync`` terminator (instead of a fixed count) keeps the
    contract robust to incidental traffic — e.g. an ``anlas_update`` or an extra
    ``api_status`` — and to broadcast ordering, while still asserting the exact
    payload types a recommended-preset application must emit.
    """
    ws.send_json(command)
    ws.send_json({"type": "sync"})
    return _drain_until_lazy(ws)


def _first(messages: list[dict[str, Any]], message_type: str) -> dict[str, Any]:
    for message in messages:
        if message.get("type") == message_type:
            return message
    raise AssertionError(f"missing message type: {message_type}; got {messages!r}")


def _first_module(messages: list[dict[str, Any]], module_id: str) -> dict[str, Any]:
    for message in messages:
        if message.get("type") == "module_state" and message.get("module_id") == module_id:
            return message
    raise AssertionError(f"missing module state: {module_id}; got {messages!r}")


def check_webui_mode_switch_applies_recommend(root: Path) -> None:
    context = _context(root)
    with _client(context).websocket_connect("/ws") as ws:
        _drain_startup(ws)
        messages = _collect_after(ws, {"type": "set_mode", "mode": "WEBUI"})

    module_state = _first_module(messages, "prompt_engineering")
    params = _first(messages, "params")
    prompt_sync = _first(messages, "prompt_sync")

    assert module_state["preset"] == "recommend"
    assert module_state["pre_prompt"] == "newest, year 2024, (best quality), score_8, highres, absurdres"
    assert params["api_mode"] == "WEBUI"
    assert params["steps"] == 32
    assert params["enable_hr"] is False
    assert params["webui_hiresfix_assist"] is False
    assert prompt_sync["negative"].startswith("ai-generated, 3d, (worst quality)")


def check_comfyui_anima_param_applies_recommend(root: Path) -> None:
    context = _context(root)
    with _client(context).websocket_connect("/ws") as ws:
        _drain_startup(ws)
        _collect_after(ws, {"type": "set_mode", "mode": "COMFYUI"})
        messages = _collect_after(ws, {"type": "set_param", "key": "sampling_mode", "value": "anima"})

    module_state = _first_module(messages, "prompt_engineering")
    params = _first(messages, "params")
    prompt_sync = _first(messages, "prompt_sync")

    assert module_state["preset"] == "recommend_anima"
    assert module_state["pre_prompt"] == "(@myowa), newest, year2024, (best quality), highres, absurdres"
    assert params["api_mode"] == "COMFYUI"
    assert params["sampling_mode"] == "anima"
    assert params["workflow_type"] == "unet"
    assert params["sampler"] == "er_sde"
    assert params["scheduler"] == "simple"
    assert prompt_sync["negative"].startswith("ai-generated, face in shadow")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        check_webui_mode_switch_applies_recommend(root / "webui")
        check_comfyui_anima_param_applies_recommend(root / "comfyui")
    print(json.dumps({"ok": True, "contract": "remote_recommend"}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
