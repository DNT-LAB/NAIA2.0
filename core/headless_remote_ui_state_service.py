"""Persistent Remote Web UI state for the headless runtime."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from core.headless_remote_state_service import (
    REMOTE_OPTION_DEFAULTS,
    HeadlessRemoteStateService,
    SUPPORTED_API_MODES,
)


REMOTE_WEB_STATE_KEY = "remote_web"
STATE_VERSION = 1


def _settings_path(context: Any) -> Path:
    return context._save_path("app_settings.json")


def _read_app_settings(context: Any) -> dict[str, Any]:
    path = context._existing_save_path("app_settings.json")
    if not path.exists():
        legacy = Path(context.repo_root) / "app_settings.json"
        path = legacy if legacy.exists() else path
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_app_settings(context: Any, data: dict[str, Any]) -> None:
    path = _settings_path(context)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _normalize_options(raw: Any) -> dict[str, bool]:
    options = dict(REMOTE_OPTION_DEFAULTS)
    if isinstance(raw, dict):
        for key in options:
            if key in raw:
                options[key] = HeadlessRemoteStateService.coerce_bool(raw.get(key))
    return options


def _normalize_mapping(raw: Any) -> dict[str, Any]:
    return copy.deepcopy(raw) if isinstance(raw, dict) else {}


def _normalize_state(raw: Any) -> dict[str, Any]:
    state = raw if isinstance(raw, dict) else {}
    mode = str(state.get("api_mode") or "NAI").strip().upper()
    if mode not in SUPPORTED_API_MODES:
        mode = "NAI"
    return {
        "version": STATE_VERSION,
        "api_mode": mode,
        "prompt": str(state.get("prompt") or ""),
        "negative_prompt": str(state.get("negative_prompt") or state.get("negative") or ""),
        "remote_options": _normalize_options(state.get("remote_options")),
        "remote_params": _normalize_mapping(state.get("remote_params")),
        "auto_save_state": _normalize_mapping(state.get("auto_save_state")),
        "save_directory_state": _normalize_mapping(state.get("save_directory_state")),
    }


def load_remote_ui_state(context: Any) -> dict[str, Any]:
    settings = _read_app_settings(context)
    return _normalize_state(settings.get(REMOTE_WEB_STATE_KEY))


def apply_remote_ui_state(context: Any) -> dict[str, Any]:
    state = load_remote_ui_state(context)
    context.current_api_mode = state["api_mode"]
    context.prompt_text = state["prompt"]
    context.negative_prompt_text = state["negative_prompt"]
    context.remote_options.update(state["remote_options"])
    context.remote_params.update(state["remote_params"])
    context.auto_save_state.update(state["auto_save_state"])
    context.save_directory_state.update(state["save_directory_state"])
    if "auto_save" not in context.auto_save_state:
        context.auto_save_state["auto_save"] = bool(context.remote_options.get("auto_save", True))
    context.remote_options["auto_save"] = bool(context.auto_save_state.get("auto_save", True))
    return state


def save_remote_ui_state(context: Any) -> dict[str, Any]:
    settings = _read_app_settings(context)
    state = {
        "version": STATE_VERSION,
        "api_mode": context.get_api_mode(),
        "prompt": str(context.prompt_text or ""),
        "negative_prompt": str(context.negative_prompt_text or ""),
        "remote_options": dict(context.get_options()),
        "remote_params": _json_safe(dict(context.remote_params or {})),
        "auto_save_state": _json_safe(dict(context.auto_save_state or {})),
        "save_directory_state": _json_safe(dict(context.save_directory_state or {})),
    }
    normalized = _normalize_state(state)
    previous = (
        _normalize_state(settings.get(REMOTE_WEB_STATE_KEY))
        if REMOTE_WEB_STATE_KEY in settings
        else None
    )
    if previous == normalized:
        return normalized
    settings[REMOTE_WEB_STATE_KEY] = normalized
    _write_app_settings(context, settings)
    return normalized
