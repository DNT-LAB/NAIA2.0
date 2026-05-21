import copy
import json
import os
from pathlib import Path
from typing import Any, Callable


PROMPT_ENGINEERING_PRESET_MODES = ("NAI", "WEBUI", "COMFYUI")
PRESET_RUNTIME_STATE_KEYS = frozenset({
    "random_resolution",
    "auto_fit_resolution",
})
PREPROCESSING_OPTION_KEYS = (
    "remove_author",
    "remove_work_title",
    "remove_character_name",
    "remove_character_features",
    "remove_clothes",
    "remove_clothing_event",
    "remove_color",
    "remove_location_and_background_color",
    "remove_expression",
    "remove_pose_action",
    "remove_meta_tags",
    "remove_object_tags",
    "remove_noise_tags",
    "closed_eyes_sync",
    "e621_auto_boost",
    "danbooru_auto_weight",
    "tag_implication_compression",
)


def normalize_prompt_engineering_mode(mode: str | None, *, allow_empty: bool = False) -> str:
    value = str(mode or "").strip().upper()
    if not value:
        return "" if allow_empty else "NAI"
    if value not in PROMPT_ENGINEERING_PRESET_MODES:
        raise ValueError("Invalid prompt engineering mode")
    return value


def sanitize_preset_name(preset_name: str) -> str:
    if not isinstance(preset_name, str):
        return ""
    sanitized = preset_name.strip()
    for char in '<>:"/\\|?*':
        sanitized = sanitized.replace(char, "")
    return sanitized.strip()


def _default_save_root() -> Path:
    user_data_dir = os.environ.get("NAIA_USER_DATA_DIR")
    if user_data_dir:
        return Path(user_data_dir).expanduser().resolve() / "save"
    return Path("save")


def _coerce_save_root(save_root: str | Path | None = None) -> Path:
    return Path(save_root).expanduser().resolve() if save_root is not None else _default_save_root()


def _legacy_save_fallback_enabled() -> bool:
    if os.environ.get("NAIA_DISABLE_LEGACY_SAVE_FALLBACK") == "1":
        return False
    if os.environ.get("NAIA_ELECTRON") == "1":
        return False
    return True


def _save_read_roots(save_root: str | Path | None = None) -> list[Path]:
    primary = _coerce_save_root(save_root)
    roots = [primary]
    legacy = Path("save").resolve()
    if _legacy_save_fallback_enabled() and legacy != primary.resolve():
        roots.append(legacy)
    return roots


def _existing_save_file(relative: str | Path, save_root: str | Path | None = None) -> Path:
    primary = _coerce_save_root(save_root) / relative
    if primary.exists():
        return primary
    for root in _save_read_roots(save_root)[1:]:
        candidate = root / relative
        if candidate.exists():
            return candidate
    return primary


def _existing_save_dirs(relative: str | Path, save_root: str | Path | None = None) -> list[Path]:
    dirs: list[Path] = []
    seen: set[Path] = set()
    for root in _save_read_roots(save_root):
        candidate = root / relative
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if candidate.exists() and candidate.is_dir():
            dirs.append(candidate)
    return dirs


def normalize_preset_main_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    normalized = dict(settings or {})
    for key in PRESET_RUNTIME_STATE_KEYS:
        normalized.pop(key, None)
    return normalized


def default_preprocessing_options() -> dict[str, bool]:
    return {key: False for key in PREPROCESSING_OPTION_KEYS}


def default_prompt_engineering_settings(save_root: str | Path | None = None) -> dict[str, Any]:
    return {
        "pre_prompt": "",
        "post_prompt": "",
        "auto_hide_prompt": "",
        "preprocessing_options": default_preprocessing_options(),
        "e621_settings": load_e621_settings(save_root=save_root),
        "danbooru_weight_settings": load_danbooru_weight_settings(save_root=save_root),
    }


def preset_dir(mode: str | None = None, *, save_root: str | Path | None = None) -> Path:
    mode_key = normalize_prompt_engineering_mode(mode)
    path = _coerce_save_root(save_root) / "presets" / mode_key
    path.mkdir(parents=True, exist_ok=True)
    return path


def is_user_preset_file(path: Path) -> bool:
    name = getattr(path, "stem", "")
    return bool(name) and name != "*randomized" and not name.endswith(".hires")


def list_preset_names(mode: str | None = None, *, save_root: str | Path | None = None) -> list[str]:
    mode_key = normalize_prompt_engineering_mode(mode)
    directories = _existing_save_dirs(Path("presets") / mode_key, save_root)
    names = [
        path.stem
        for directory in directories
        for path in sorted(directory.glob("*.json"))
        if path.is_file() and is_user_preset_file(path)
    ]
    names = list(dict.fromkeys(names))
    if "default" in names:
        names.remove("default")
        names.insert(0, "default")
    return names


def mode_settings_file(mode: str | None = None, *, save_root: str | Path | None = None) -> Path:
    mode_key = normalize_prompt_engineering_mode(mode)
    return _coerce_save_root(save_root) / f"PromptEngineeringModule_{mode_key}.json"


def load_mode_settings(mode: str | None = None, *, save_root: str | Path | None = None) -> dict[str, Any]:
    mode_key = normalize_prompt_engineering_mode(mode)
    path = _existing_save_file(f"PromptEngineeringModule_{mode_key}.json", save_root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    settings = data.get(mode_key, {}) if isinstance(data, dict) else {}
    return copy.deepcopy(settings) if isinstance(settings, dict) else {}


def save_mode_settings(mode: str | None, settings: dict[str, Any], *, save_root: str | Path | None = None) -> None:
    mode_key = normalize_prompt_engineering_mode(mode)
    path = mode_settings_file(mode_key, save_root=save_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({mode_key: copy.deepcopy(settings)}, ensure_ascii=False, indent=4),
        encoding="utf-8",
    )


def load_e621_settings(*, save_root: str | Path | None = None) -> dict[str, Any]:
    path = _existing_save_file("e621_boost_user.json", save_root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {"weight": 0.0, "hidden_tags": [], "mode": "stable"}


def save_e621_settings(settings: dict[str, Any], *, save_root: str | Path | None = None) -> None:
    path = _coerce_save_root(save_root) / "e621_boost_user.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(settings or {}), ensure_ascii=False, indent=2), encoding="utf-8")


def load_danbooru_weight_settings(*, save_root: str | Path | None = None) -> dict[str, Any]:
    path = _existing_save_file("danbooru_auto_weight_user.json", save_root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {"magnitude": 3}


def save_danbooru_weight_settings(settings: dict[str, Any], *, save_root: str | Path | None = None) -> None:
    path = _coerce_save_root(save_root) / "danbooru_auto_weight_user.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(settings or {}), ensure_ascii=False, indent=2), encoding="utf-8")


def last_used_preset_file(*, save_root: str | Path | None = None) -> Path:
    return _coerce_save_root(save_root) / "presets" / "last_used_preset.json"


def load_last_used_preset(mode: str | None = None, *, save_root: str | Path | None = None) -> str | None:
    mode_key = normalize_prompt_engineering_mode(mode)
    path = _existing_save_file(Path("presets") / "last_used_preset.json", save_root)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    value = data.get(mode_key)
    return str(value) if value else None


def save_last_used_preset(mode: str | None, preset_name: str, *, save_root: str | Path | None = None) -> None:
    mode_key = normalize_prompt_engineering_mode(mode)
    path = last_used_preset_file(save_root=save_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    data[mode_key] = str(preset_name or "")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def randomized_pool_file(*, save_root: str | Path | None = None) -> Path:
    return _coerce_save_root(save_root) / "presets" / "randomized_pool.json"


def load_randomized_pool(
    mode: str | None,
    preset_names: list[str] | None = None,
    *,
    save_root: str | Path | None = None,
) -> list[str]:
    mode_key = normalize_prompt_engineering_mode(mode)
    path = _existing_save_file(Path("presets") / "randomized_pool.json", save_root)
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        data = {}
    pool = data.get(mode_key, []) if isinstance(data, dict) else []
    if not isinstance(pool, list):
        pool = []
    valid = set(preset_names or list_preset_names(mode_key, save_root=save_root))
    seen = set()
    restored = []
    for raw_name in pool:
        name = sanitize_preset_name(str(raw_name or ""))
        if (
            name
            and name not in seen
            and name not in {"default", "*randomized"}
            and name in valid
        ):
            restored.append(name)
            seen.add(name)
    return restored


def save_randomized_pool(mode: str | None, pool: list[str], *, save_root: str | Path | None = None) -> None:
    mode_key = normalize_prompt_engineering_mode(mode)
    path = randomized_pool_file(save_root=save_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    data[mode_key] = list(pool or [])
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_preset_data(
    preset_name: str,
    mode: str | None = None,
    *,
    save_root: str | Path | None = None,
) -> dict[str, Any]:
    name = sanitize_preset_name(preset_name)
    if not name:
        return {}
    mode_key = normalize_prompt_engineering_mode(mode)
    path = _existing_save_file(Path("presets") / mode_key / f"{name}.json", save_root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_preset_data(
    preset_name: str,
    mode: str | None,
    data: dict[str, Any],
    *,
    save_root: str | Path | None = None,
) -> None:
    name = sanitize_preset_name(preset_name)
    if not name:
        raise ValueError("Preset name is required")
    payload = copy.deepcopy(data or {})
    if isinstance(payload.get("main_settings"), dict):
        payload["main_settings"] = normalize_preset_main_settings(payload["main_settings"])
    path = preset_dir(mode, save_root=save_root) / f"{name}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def merge_settings(base: dict[str, Any], updates: dict[str, Any] | None) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    incoming = dict(updates or {})
    options = incoming.pop("preprocessing_options", None)
    if isinstance(options, dict):
        current_options = dict(merged.get("preprocessing_options") or {})
        for key, value in options.items():
            current_options[key] = bool(value)
        merged["preprocessing_options"] = current_options
    for key, value in incoming.items():
        if key in {"e621_settings", "danbooru_weight_settings"} and isinstance(value, dict):
            merged[key] = dict(value)
        elif key in {"pre_prompt", "post_prompt", "auto_hide_prompt"}:
            merged[key] = str(value or "")
        else:
            merged[key] = copy.deepcopy(value)
    return merged


class PromptEngineeringHeadlessStore:
    def __init__(
        self,
        mode_getter: Callable[[], str] | None = None,
        *,
        save_root: str | Path | None = None,
    ):
        self._mode_getter = mode_getter or (lambda: "NAI")
        self._save_root = _coerce_save_root(save_root)
        self._states: dict[str, dict[str, Any]] = {}

    def mode(self, mode: str | None = None) -> str:
        return normalize_prompt_engineering_mode(mode or self._mode_getter())

    def _load_state(self, mode: str) -> dict[str, Any]:
        preset_names = self.list_preset_names(mode)
        current_preset = self.load_last_used_preset(mode)
        if current_preset not in preset_names:
            current_preset = "default" if "default" in preset_names else "(프리셋 없음)"

        settings = default_prompt_engineering_settings(save_root=self._save_root)
        settings = merge_settings(settings, self.load_mode_settings(mode))
        if current_preset in preset_names:
            preset_data = self.read_preset_data(current_preset, mode)
            settings = merge_settings(settings, preset_data.get("module_settings") or {})

        randomized_pool = self.load_randomized_pool(mode, preset_names)
        return {
            "settings": settings,
            "preset_list": preset_names,
            "current_preset": current_preset,
            "randomized_preset_list": randomized_pool,
        }

    def list_preset_names(self, mode: str | None = None) -> list[str]:
        return list_preset_names(mode, save_root=self._save_root)

    def read_preset_data(self, preset_name: str, mode: str | None = None) -> dict[str, Any]:
        return read_preset_data(preset_name, mode, save_root=self._save_root)

    def write_preset_data(self, preset_name: str, mode: str | None, data: dict[str, Any]) -> None:
        write_preset_data(preset_name, mode, data, save_root=self._save_root)

    def load_mode_settings(self, mode: str | None = None) -> dict[str, Any]:
        return load_mode_settings(mode, save_root=self._save_root)

    def save_mode_settings(self, mode: str | None, settings: dict[str, Any]) -> None:
        save_mode_settings(mode, settings, save_root=self._save_root)

    def load_last_used_preset(self, mode: str | None = None) -> str | None:
        return load_last_used_preset(mode, save_root=self._save_root)

    def save_last_used_preset(self, mode: str | None, preset_name: str) -> None:
        save_last_used_preset(mode, preset_name, save_root=self._save_root)

    def load_randomized_pool(self, mode: str | None, preset_names: list[str] | None = None) -> list[str]:
        return load_randomized_pool(mode, preset_names, save_root=self._save_root)

    def save_randomized_pool(self, mode: str | None, pool: list[str]) -> None:
        save_randomized_pool(mode, pool, save_root=self._save_root)

    def save_e621_settings(self, settings: dict[str, Any]) -> None:
        save_e621_settings(settings, save_root=self._save_root)

    def save_danbooru_weight_settings(self, settings: dict[str, Any]) -> None:
        save_danbooru_weight_settings(settings, save_root=self._save_root)

    def state(self, mode: str | None = None) -> dict[str, Any]:
        mode_key = self.mode(mode)
        if mode_key not in self._states:
            self._states[mode_key] = self._load_state(mode_key)
        return self._states[mode_key]

    def refresh(self, mode: str | None = None) -> dict[str, Any]:
        mode_key = self.mode(mode)
        self._states[mode_key] = self._load_state(mode_key)
        return self._states[mode_key]

    def collect_settings(self, mode: str | None = None) -> dict[str, Any]:
        return copy.deepcopy(self.state(mode)["settings"])

    def apply_settings(self, updates: dict[str, Any], mode: str | None = None) -> dict[str, Any]:
        state = self.state(mode)
        state["settings"] = merge_settings(state["settings"], updates)
        return copy.deepcopy(state["settings"])

    def preset_options(self, mode: str | None = None) -> list[str]:
        names = list(self.state(mode)["preset_list"])
        return ["*randomized", *names]

    def randomized_available_presets(self, mode: str | None = None) -> list[str]:
        state = self.state(mode)
        selected = set(state["randomized_preset_list"])
        return [
            name for name in state["preset_list"]
            if name not in {"default", "*randomized"} and name not in selected
        ]

    def set_preset(self, preset_name: str, mode: str | None = None) -> bool:
        state = self.state(mode)
        name = sanitize_preset_name(preset_name) if preset_name != "*randomized" else "*randomized"
        if name == "*randomized":
            state["current_preset"] = "*randomized"
            return True
        if name not in state["preset_list"]:
            return False
        preset_data = self.read_preset_data(name, self.mode(mode))
        state["settings"] = merge_settings(state["settings"], preset_data.get("module_settings") or {})
        state["current_preset"] = name
        self.save_last_used_preset(self.mode(mode), name)
        return True

    def save_current_preset(self, mode: str | None = None) -> tuple[bool, str]:
        mode_key = self.mode(mode)
        state = self.state(mode_key)
        name = state["current_preset"]
        if name in {"", "(프리셋 없음)", "*randomized"}:
            return False, "저장할 현재 프리셋이 없습니다."
        data = self.read_preset_data(name, mode_key)
        data["api_mode"] = mode_key
        data["module_settings"] = copy.deepcopy(state["settings"])
        self.write_preset_data(name, mode_key, data)
        self.save_last_used_preset(mode_key, name)
        return True, name

    def create_preset(self, preset_name: str, mode: str | None = None) -> tuple[bool, str]:
        mode_key = self.mode(mode)
        name = sanitize_preset_name(preset_name)
        if not name:
            return False, "프리셋 이름이 비어 있습니다."
        data = {
            "api_mode": mode_key,
            "module_settings": copy.deepcopy(self.state(mode_key)["settings"]),
            "main_settings": {},
        }
        self.write_preset_data(name, mode_key, data)
        self.refresh(mode_key)
        self.set_preset(name, mode_key)
        return True, name

    def delete_preset(self, preset_name: str, mode: str | None = None) -> tuple[bool, str]:
        mode_key = self.mode(mode)
        name = sanitize_preset_name(preset_name)
        if not name:
            return False, "삭제할 프리셋 이름이 없습니다."
        if name == "default":
            return False, "기본 프리셋은 삭제할 수 없습니다."
        if name == "*randomized":
            return False, "랜덤 프리셋 모드는 삭제할 수 없습니다."
        path = preset_dir(mode_key, save_root=self._save_root) / f"{name}.json"
        if not path.exists():
            return False, f"프리셋을 찾을 수 없습니다: {name}"
        path.unlink()
        self.refresh(mode_key)
        return True, name

    def add_randomized_preset(self, preset_name: str, mode: str | None = None) -> tuple[bool, str]:
        mode_key = self.mode(mode)
        state = self.state(mode_key)
        name = sanitize_preset_name(preset_name)
        if name not in self.randomized_available_presets(mode_key):
            return False, "랜덤 풀에 추가할 수 없는 프리셋입니다."
        state["randomized_preset_list"].append(name)
        self.save_randomized_pool(mode_key, state["randomized_preset_list"])
        return True, name

    def remove_randomized_preset(self, preset_name: str, mode: str | None = None) -> tuple[bool, str]:
        mode_key = self.mode(mode)
        state = self.state(mode_key)
        name = sanitize_preset_name(preset_name)
        if name not in state["randomized_preset_list"]:
            return False, "랜덤 풀에 없는 프리셋입니다."
        state["randomized_preset_list"].remove(name)
        self.save_randomized_pool(mode_key, state["randomized_preset_list"])
        return True, name

    def clear_randomized_presets(self, mode: str | None = None) -> tuple[bool, str]:
        mode_key = self.mode(mode)
        self.state(mode_key)["randomized_preset_list"] = []
        self.save_randomized_pool(mode_key, [])
        return True, ""


def get_prompt_engineering_store(app_context) -> PromptEngineeringHeadlessStore:
    store = getattr(app_context, "prompt_engineering_headless_store", None)
    if isinstance(store, PromptEngineeringHeadlessStore):
        return store
    mode_getter = getattr(app_context, "get_api_mode", None)
    runtime_paths = getattr(app_context, "runtime_paths", None)
    save_root = getattr(runtime_paths, "save_dir", None)
    store = PromptEngineeringHeadlessStore(
        mode_getter if callable(mode_getter) else None,
        save_root=save_root,
    )
    setattr(app_context, "prompt_engineering_headless_store", store)
    return store
