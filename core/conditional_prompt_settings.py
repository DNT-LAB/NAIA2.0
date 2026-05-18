import copy
import json
from pathlib import Path
from typing import Any, Callable


DEFAULT_CONDITIONAL_ENGINE_OPTIONS = {
    "max_passes": 1,
    "stop_on_match": False,
}

DEFAULT_CONDITIONAL_SETTINGS = {
    "enabled": False,
    "rules": "",
    "rules_v2": "",
    "editor_mode": "legacy",
    "engine_options": dict(DEFAULT_CONDITIONAL_ENGINE_OPTIONS),
    "active_preset": None,
}


def normalize_conditional_mode(mode: Any = None) -> str:
    text = str(mode or "NAI").strip().upper()
    return text if text in {"NAI", "WEBUI", "COMFYUI"} else "NAI"


def conditional_settings_path(mode: Any = None) -> Path:
    return Path("save") / f"PromptListModifierModule_{normalize_conditional_mode(mode)}.json"


def normalize_conditional_engine_options(raw: Any = None) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    try:
        max_passes = int(source.get("max_passes", 1))
    except Exception:
        max_passes = 1
    return {
        "max_passes": min(20, max(1, max_passes)),
        "stop_on_match": bool(source.get("stop_on_match", False)),
    }


def normalize_conditional_settings(raw: Any = None) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    settings = copy.deepcopy(DEFAULT_CONDITIONAL_SETTINGS)
    settings["enabled"] = bool(source.get("enabled", settings["enabled"]))
    settings["rules"] = str(source.get("rules", "") or "")
    settings["rules_v2"] = str(source.get("rules_v2", "") or "")
    editor_mode = str(source.get("editor_mode", settings["editor_mode"]) or "legacy")
    settings["editor_mode"] = editor_mode if editor_mode in {"legacy", "v2"} else "legacy"
    settings["engine_options"] = normalize_conditional_engine_options(source.get("engine_options"))
    active_preset = source.get("active_preset")
    settings["active_preset"] = str(active_preset) if active_preset else None
    return settings


def load_conditional_settings(mode: Any = None) -> dict[str, Any]:
    mode_key = normalize_conditional_mode(mode)
    path = conditional_settings_path(mode_key)
    if not path.exists():
        return normalize_conditional_settings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Conditional Prompt settings load failed: {exc}")
        return normalize_conditional_settings()
    payload = data.get(mode_key, {}) if isinstance(data, dict) else {}
    return normalize_conditional_settings(payload)


def save_conditional_settings(settings: dict[str, Any], mode: Any = None) -> None:
    mode_key = normalize_conditional_mode(mode)
    path = conditional_settings_path(mode_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {mode_key: normalize_conditional_settings(settings)}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=4), encoding="utf-8")


class ConditionalPromptHeadlessStore:
    def __init__(self, mode_getter: Callable[[], str] | None = None):
        self._mode_getter = mode_getter
        self._state_by_mode: dict[str, dict[str, Any]] = {}

    def mode(self) -> str:
        if callable(self._mode_getter):
            try:
                return normalize_conditional_mode(self._mode_getter())
            except Exception:
                pass
        return "NAI"

    def state(self, mode: Any = None) -> dict[str, Any]:
        mode_key = normalize_conditional_mode(mode or self.mode())
        if mode_key not in self._state_by_mode:
            self._state_by_mode[mode_key] = load_conditional_settings(mode_key)
        return self._state_by_mode[mode_key]

    def collect_settings(self, mode: Any = None) -> dict[str, Any]:
        return copy.deepcopy(self.state(mode))

    def apply_settings(self, updates: dict[str, Any], mode: Any = None, *, persist: bool = True) -> dict[str, Any]:
        mode_key = normalize_conditional_mode(mode or self.mode())
        current = self.state(mode_key)
        merged = {**current, **(updates or {})}
        normalized = normalize_conditional_settings(merged)
        self._state_by_mode[mode_key] = normalized
        if persist:
            save_conditional_settings(normalized, mode_key)
        return copy.deepcopy(normalized)


def get_conditional_prompt_store(app_context) -> ConditionalPromptHeadlessStore:
    store = getattr(app_context, "conditional_prompt_headless_store", None)
    if isinstance(store, ConditionalPromptHeadlessStore):
        return store
    mode_getter = getattr(app_context, "get_api_mode", None)
    store = ConditionalPromptHeadlessStore(mode_getter if callable(mode_getter) else None)
    setattr(app_context, "conditional_prompt_headless_store", store)
    return store
