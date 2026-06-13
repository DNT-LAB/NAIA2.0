"""Persistent Remote Web UI state for the headless runtime."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from core.headless_remote_state_service import (
    REMOTE_OPTION_DEFAULTS,
    RUNTIME_REMOTE_PARAM_KEYS,
    HeadlessRemoteStateService,
    SUPPORTED_API_MODES,
)


REMOTE_WEB_STATE_KEY = "remote_web"
STATE_VERSION = 2


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


def _strip_runtime_keys(params: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in params.items() if key not in RUNTIME_REMOTE_PARAM_KEYS}


def _normalize_param_planes(raw: Any, *, legacy_params: dict[str, Any], legacy_mode: str) -> dict[str, dict[str, Any]]:
    """Per-mode parameter planes. Falls back to migrating a legacy single
    ``remote_params`` blob into the mode it was last used under."""
    planes: dict[str, dict[str, Any]] = {}
    if isinstance(raw, dict):
        for mode in SUPPORTED_API_MODES:
            plane = raw.get(mode)
            if isinstance(plane, dict):
                planes[mode] = _strip_runtime_keys(_normalize_mapping(plane))
    if not planes and legacy_params:
        planes[legacy_mode] = _strip_runtime_keys(_normalize_mapping(legacy_params))
    return planes


def _normalize_prompt_plane(raw: Any) -> dict[str, str]:
    plane = raw if isinstance(raw, dict) else {}
    return {
        "prompt": str(plane.get("prompt") or ""),
        "negative_prompt": str(plane.get("negative_prompt") or plane.get("negative") or ""),
    }


def _normalize_prompt_planes(
    raw: Any,
    *,
    legacy_prompt: str,
    legacy_negative: str,
    legacy_mode: str,
) -> dict[str, dict[str, str]]:
    """Per-mode prompt planes. Falls back to migrating the legacy single
    ``prompt``/``negative_prompt`` blob into the mode it was last used under."""
    planes: dict[str, dict[str, str]] = {}
    if isinstance(raw, dict):
        for mode in SUPPORTED_API_MODES:
            if mode in raw:
                planes[mode] = _normalize_prompt_plane(raw.get(mode))
    if not planes and (legacy_prompt or legacy_negative):
        planes[legacy_mode] = {"prompt": legacy_prompt, "negative_prompt": legacy_negative}
    return planes


def _normalize_state(raw: Any) -> dict[str, Any]:
    state = raw if isinstance(raw, dict) else {}
    mode = str(state.get("api_mode") or "NAI").strip().upper()
    if mode not in SUPPORTED_API_MODES:
        mode = "NAI"
    remote_params = _normalize_mapping(state.get("remote_params"))
    planes = _normalize_param_planes(
        state.get("remote_param_planes"),
        legacy_params=remote_params,
        legacy_mode=mode,
    )
    # Keep the flat remote_params mirror in sync with the active mode's plane.
    active_plane = _strip_runtime_keys(planes.get(mode, {}))
    legacy_prompt = str(state.get("prompt") or "")
    legacy_negative = str(state.get("negative_prompt") or state.get("negative") or "")
    prompt_planes = _normalize_prompt_planes(
        state.get("prompt_planes"),
        legacy_prompt=legacy_prompt,
        legacy_negative=legacy_negative,
        legacy_mode=mode,
    )
    # Keep the flat prompt/negative mirror in sync with the active mode's plane.
    active_prompt_plane = prompt_planes.get(mode) or {"prompt": legacy_prompt, "negative_prompt": legacy_negative}
    return {
        "version": STATE_VERSION,
        "api_mode": mode,
        "prompt": str(active_prompt_plane.get("prompt") or ""),
        "negative_prompt": str(active_prompt_plane.get("negative_prompt") or ""),
        "remote_options": _normalize_options(state.get("remote_options")),
        "remote_params": active_plane,
        "remote_param_planes": planes,
        "prompt_planes": prompt_planes,
        "auto_save_state": _normalize_mapping(state.get("auto_save_state")),
        "save_directory_state": _normalize_mapping(state.get("save_directory_state")),
    }


def load_remote_ui_state(context: Any) -> dict[str, Any]:
    settings = _read_app_settings(context)
    return _normalize_state(settings.get(REMOTE_WEB_STATE_KEY))


def apply_remote_ui_state(context: Any) -> dict[str, Any]:
    state = load_remote_ui_state(context)
    runtime_params = {
        key: context.remote_params[key]
        for key in RUNTIME_REMOTE_PARAM_KEYS
        if key in context.remote_params
    }
    mode = state["api_mode"]
    context.current_api_mode = mode
    context.prompt_text = state["prompt"]
    context.negative_prompt_text = state["negative_prompt"]
    # Restore per-mode prompt planes; the flat prompt_text/negative_prompt_text
    # already mirror the active mode's plane (set above from state).
    prompt_planes = {
        plane_mode: dict(values)
        for plane_mode, values in state["prompt_planes"].items()
    }
    prompt_planes[mode] = {
        "prompt": str(context.prompt_text or ""),
        "negative_prompt": str(context.negative_prompt_text or ""),
    }
    context.prompt_planes = prompt_planes
    context.remote_options.update(state["remote_options"])
    # Restore per-mode parameter planes and activate the saved mode's plane.
    # Mutate the existing remote_params dict (rather than replacing it) so any
    # values set before apply survive, then register it as the active plane.
    planes = {plane_mode: dict(values) for plane_mode, values in state["remote_param_planes"].items()}
    active = context.remote_params
    active.update(planes.get(mode, {}))
    active.update(runtime_params)
    planes[mode] = active
    context.remote_param_planes = planes
    context.auto_save_state.update(state["auto_save_state"])
    context.save_directory_state.update(state["save_directory_state"])
    if "auto_save" not in context.auto_save_state:
        context.auto_save_state["auto_save"] = HeadlessRemoteStateService.coerce_bool(
            context.remote_options.get("auto_save", True)
        )
    else:
        context.auto_save_state["auto_save"] = HeadlessRemoteStateService.coerce_bool(
            context.auto_save_state.get("auto_save")
        )
    context.remote_options["auto_save"] = bool(context.auto_save_state["auto_save"])
    return state


def save_remote_ui_state(context: Any) -> dict[str, Any]:
    settings = _read_app_settings(context)
    mode = context.get_api_mode()
    planes = getattr(context, "remote_param_planes", None)
    if not isinstance(planes, dict):
        planes = {}
        context.remote_param_planes = planes
    # Keep the active mode's plane pointing at the live remote_params (same
    # object the state service swaps), so persistence always captures it.
    planes[mode] = context.remote_params
    prompt_planes = getattr(context, "prompt_planes", None)
    if not isinstance(prompt_planes, dict):
        prompt_planes = {}
        context.prompt_planes = prompt_planes
    # Snapshot the active mode's prompt from the live fields (set_prompt and the
    # random-prompt service write prompt_text directly), so persistence captures it.
    prompt_planes[mode] = {
        "prompt": str(context.prompt_text or ""),
        "negative_prompt": str(context.negative_prompt_text or ""),
    }
    state = {
        "version": STATE_VERSION,
        "api_mode": mode,
        "prompt": str(context.prompt_text or ""),
        "negative_prompt": str(context.negative_prompt_text or ""),
        "remote_options": dict(context.get_options()),
        "remote_param_planes": _json_safe({
            plane_mode: dict(values or {})
            for plane_mode, values in planes.items()
            if plane_mode in SUPPORTED_API_MODES
        }),
        "prompt_planes": _json_safe({
            plane_mode: dict(values or {})
            for plane_mode, values in prompt_planes.items()
            if plane_mode in SUPPORTED_API_MODES
        }),
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
