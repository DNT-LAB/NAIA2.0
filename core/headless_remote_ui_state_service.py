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

# 세션마다 새로 시작하는 save_directory 키. 영속화 대상에서 제외한다.
RUNTIME_SAVE_DIRECTORY_KEYS = frozenset({"save_counter"})


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


def _normalize_save_directory_state(raw: Any) -> dict[str, Any]:
    """save_directory_state 에서 세션 한정 값을 걷어낸다.

    ``save_counter`` 는 **런타임 값**이다. 데스크톱 시절 계약은
    ``ImageCrudController._load_counter_from_settings`` 가 못 박은 대로
    "앱을 다시 켜면 1부터" 였는데, 헤드리스는 save_directory_state 를 통째로
    저장/복원하면서 카운터까지 딸려 와 재시작해도 번호가 이어졌다.
    저장 쪽과 복원 쪽이 같은 정규화를 지나므로 여기 한 곳에서 끊는다.
    """
    state = _normalize_mapping(raw)
    for key in RUNTIME_SAVE_DIRECTORY_KEYS:
        state.pop(key, None)
    return state


def _has_stale_runtime_keys(stored: Any) -> bool:
    """이미 저장된 blob 에 런타임 전용 키가 남아 있는가(옛 빌드가 쓴 파일)."""
    if not isinstance(stored, dict):
        return False
    save_directory_state = stored.get("save_directory_state")
    if not isinstance(save_directory_state, dict):
        return False
    return bool(RUNTIME_SAVE_DIRECTORY_KEYS & set(save_directory_state))


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
        "save_directory_state": _normalize_save_directory_state(state.get("save_directory_state")),
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
    _heal_nai_model_key(context, planes)
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


def _heal_nai_model_key(context: Any, planes: dict[str, Any]) -> None:
    """저장돼 있던 값이 모델 **이름**이면 키로 되돌린다. 모르는 값은 **그대로 둔다**.

    ⚠️ 여기까지 온 값은 이미 디스크에 앉은 값이다. 생성 시점 판정은 일부러 엄격해서
       (돈이 나가는 길이라) 모르는 키를 만나면 멈춘다 - 그래서 한 번 표시 라벨이
       저장되면 **껐다 켜도, API 키를 새로 받아도** 계속 막힌다(사용자 제보
       2026-08-25). 켤 때 한 번 훑어 되돌리면 그 막다른 길이 사라진다.

    ⚠️⚠️ **기본값으로 갈아 끼우지 않는다.** 그러면 사용자가 등록했다가 지운 커스텀
       모델이 말없이 4.5 Full 이 되어 돈을 태운다(Codex 리뷰 BLOCK, 재현됨).
       아는 이름만 번역하고, 모르는 것은 남겨 생성 직전에 막히게 둔다 - 그때
       화면이 PARAMS 를 열어 다시 고르게 안내한다.

    ⚠️ **NAI 판만 본다.** WEBUI/COMFYUI 의 `model` 은 체크포인트 파일 이름이라
       NAI 레지스트리에는 당연히 없다 - 같이 훑으면 멀쩡한 값을 지운다.
    """
    from core.nai_model_contract import nai_key_from_metadata, normalize_nai_model_key

    try:
        registry = context._nai_model_registry()
    except Exception as exc:  # noqa: BLE001 - 부팅을 막으면 안 된다
        print(f"[warn] NAI model registry unavailable during restore: {exc}", flush=True)
        return
    # 활성 모드가 NAI 면 `planes["NAI"] is active` 다(바로 위에서 그렇게 넣었다) -
    # 그래서 NAI 판 하나만 보면 화면에 뜬 값까지 함께 고쳐진다.
    planes_nai = planes.get("NAI")
    for plane in ([planes_nai] if isinstance(planes_nai, dict) else []):
        raw = plane.get("model")
        if raw in (None, ""):
            continue
        key = normalize_nai_model_key(raw)
        if registry.has_key(key):
            continue
        translated = nai_key_from_metadata(model_value=key)
        if not translated or translated == key:
            print(f"[warn] stored NAI model key is unknown, kept for reselect: {key}",
                  flush=True)
            continue
        plane["model"] = translated
        print(f"[warn] stored NAI model name mapped to key: {key} -> {translated}",
              flush=True)


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
    stored = settings.get(REMOTE_WEB_STATE_KEY)
    previous = _normalize_state(stored) if REMOTE_WEB_STATE_KEY in settings else None
    # 정규화끼리 비교하는 이유: 저장은 이미지 한 장마다 불린다. 왕복이 조금이라도
    # 어긋나면 매번 파일을 다시 쓰게 된다. 대신 옛 빌드가 박아 둔 런타임 키는
    # 이 비교에서 지워져 영영 파일에 남으므로, 그 경우만 따로 한 번 걷어낸다.
    if previous == normalized and not _has_stale_runtime_keys(stored):
        return normalized
    settings[REMOTE_WEB_STATE_KEY] = normalized
    _write_app_settings(context, settings)
    return normalized
