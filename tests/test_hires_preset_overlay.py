"""Hires Preset Overlay sidecar — `_hires_overlay_*` helpers on RemoteBridge.

검증 범위:
- 경로 게이트 (예약 이름, 경로 탈출, 비-WEBUI 모드)
- 원본 프리셋만 있을 때 응답 (overlay=None)
- write→read 라운드트립
- reset 이 sidecar 파일을 제거
"""

import json
from pathlib import Path

import pytest

from legacy_desktop.core.remote_api_server import RemoteBridge


class _TokenManager:
    def get_token(self, key):
        return ""


class _AppContext:
    secure_token_manager = _TokenManager()
    cloudflared_active = False
    cloudflared_tunnel_url = ""
    cloudflared_status_text = ""
    main_window = None
    _mode = "WEBUI"

    def get_api_mode(self):
        return self._mode


@pytest.fixture
def bridge_in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "save" / "presets" / "WEBUI").mkdir(parents=True)
    return RemoteBridge(_AppContext())


def _write_preset(name: str, *, pre: str = "PRE", post: str = "POST", negative: str = "NEG"):
    data = {
        "schema_version": 1,
        "api_mode": "WEBUI",
        "module_settings": {
            "pre_prompt": pre,
            "post_prompt": post,
            "auto_hide_prompt": "",
            "preprocessing_options": {},
        },
        "main_settings": {
            "negative": negative,
        },
    }
    path = Path("save") / "presets" / "WEBUI" / f"{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_overlay_path_rejects_reserved_names(bridge_in_tmp):
    assert bridge_in_tmp._hires_overlay_path("") is None
    assert bridge_in_tmp._hires_overlay_path("*randomized") is None
    assert bridge_in_tmp._hires_overlay_path("(프리셋 없음)") is None


def test_overlay_path_rejects_traversal(bridge_in_tmp):
    assert bridge_in_tmp._hires_overlay_path("../escape") is None
    assert bridge_in_tmp._hires_overlay_path("nested/path") is None
    assert bridge_in_tmp._hires_overlay_path("/abs") is None


def test_overlay_path_rejects_non_webui_mode(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ctx = _AppContext()
    ctx._mode = "NAI"
    bridge = RemoteBridge(ctx)
    assert bridge._hires_overlay_path("fast1") is None


def test_read_response_returns_original_when_no_overlay(bridge_in_tmp):
    _write_preset("fast1", pre="anime, masterpiece", post="detailed", negative="lowres, blurry")

    response = bridge_in_tmp._hires_overlay_response("fast1")

    assert response["type"] == "hires_preset_overlay"
    assert response["preset_name"] == "fast1"
    assert response["editable"] is True
    assert response["original"] == {
        "prefix_prompt": "anime, masterpiece",
        "postfix_prompt": "detailed",
        "negative_prompt": "lowres, blurry",
    }
    assert response["overlay"] is None


def test_write_then_read_roundtrip(bridge_in_tmp):
    _write_preset("fast1", pre="anime", post="detailed", negative="lowres")
    body = {
        "prefix_prompt": "edited prefix",
        "postfix_prompt": "edited postfix",
        "negative_prompt": "edited negative",
    }

    ok, msg = bridge_in_tmp._write_hires_overlay("fast1", body)
    assert ok is True
    assert "saved" in msg.lower()

    sidecar = Path("save") / "presets" / "WEBUI" / "fast1.hires.json"
    assert sidecar.exists()
    persisted = json.loads(sidecar.read_text(encoding="utf-8"))
    assert persisted["schema_version"] == 1
    assert persisted["prefix_prompt"] == "edited prefix"

    response = bridge_in_tmp._hires_overlay_response("fast1")
    assert response["overlay"] == body
    # 원본은 그대로 보존
    assert response["original"]["prefix_prompt"] == "anime"


def test_write_empty_body_persists_empty_strings(bridge_in_tmp):
    """빈 칸으로 저장 = 의도된 빈 값 (원본 fallback 아님)."""
    _write_preset("fast1", pre="anime", post="detailed", negative="lowres")
    ok, _ = bridge_in_tmp._write_hires_overlay("fast1", {
        "prefix_prompt": "",
        "postfix_prompt": "",
        "negative_prompt": "",
    })
    assert ok is True
    response = bridge_in_tmp._hires_overlay_response("fast1")
    assert response["overlay"] == {
        "prefix_prompt": "",
        "postfix_prompt": "",
        "negative_prompt": "",
    }


def test_reset_removes_sidecar(bridge_in_tmp):
    _write_preset("fast1")
    bridge_in_tmp._write_hires_overlay("fast1", {
        "prefix_prompt": "x", "postfix_prompt": "y", "negative_prompt": "z",
    })
    sidecar = Path("save") / "presets" / "WEBUI" / "fast1.hires.json"
    assert sidecar.exists()

    ok, msg = bridge_in_tmp._reset_hires_overlay("fast1")
    assert ok is True
    assert not sidecar.exists()

    response = bridge_in_tmp._hires_overlay_response("fast1")
    assert response["overlay"] is None


def test_reset_when_no_sidecar_is_noop_success(bridge_in_tmp):
    _write_preset("fast1")
    ok, msg = bridge_in_tmp._reset_hires_overlay("fast1")
    assert ok is True
    assert "absent" in msg.lower() or "already" in msg.lower()


def test_write_rejects_disallowed_name(bridge_in_tmp):
    ok, msg = bridge_in_tmp._write_hires_overlay("*randomized", {
        "prefix_prompt": "x", "postfix_prompt": "y", "negative_prompt": "z",
    })
    assert ok is False
    assert "WEBUI" in msg or "편집" in msg
