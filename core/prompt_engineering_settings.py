import copy
import json
import os
from pathlib import Path
from typing import Any, Callable


# ANIMA = 관리형 ANIMA 엔진을 고른 COMFYUI 의 프리셋 색인(아래 prompt_engineering_mode_of - 사용자 지정 09-30)
PROMPT_ENGINEERING_PRESET_MODES = ("NAI", "WEBUI", "COMFYUI", "ANIMA")
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
    "category_annotation",
)


def normalize_prompt_engineering_mode(mode: str | None, *, allow_empty: bool = False) -> str:
    value = str(mode or "").strip().upper()
    if not value:
        return "" if allow_empty else "NAI"
    if value not in PROMPT_ENGINEERING_PRESET_MODES:
        raise ValueError("Invalid prompt engineering mode")
    return value


def prompt_engineering_mode_of(app_context: Any) -> str:
    """프리셋 색인(PE 모드). api_mode 그대로이되, 관리형 ANIMA 엔진을 고른 COMFYUI 는 "ANIMA".

    사용자 지정 2026-09-30: ANIMA 모드가 외부 COMFYUI 의 프리셋(다른 모드에서 옮겨 온 것까지)을 그대로 보여 줬다 -
    ANIMA 는 프리셋 · Prefix/Postfix · 마지막 프리셋 · 랜덤 풀을 따로 둔다(save/presets/ANIMA).
    생성 백엔드(api_mode)는 그대로 COMFYUI 다 - 이것은 프리셋을 어디에 두고 어디서 읽느냐만 정한다.
    """
    getter = getattr(app_context, "get_api_mode", None)
    mode = str((getter() if callable(getter) else "") or "NAI").strip().upper()
    if mode == "COMFYUI":
        try:
            from core.anima_engine.integration import managed_selected

            if managed_selected(app_context):
                return "ANIMA"
        except Exception:   # 엔진 모듈이 없는 축소 판 - 예전처럼 COMFYUI
            pass
    return mode


def sanitize_preset_name(preset_name: str) -> str:
    if not isinstance(preset_name, str):
        return ""
    sanitized = preset_name.strip()
    for char in '<>:"/\\|?*':
        sanitized = sanitized.replace(char, "")
    return sanitized.strip()


# ---- 랜덤 칸(랜더마이저) 이름 ------------------------------------------------
#
# 프리셋 목록 끝에 붙는 **합성 이름**이다 - 파일이 없다. `*` 는 프리셋 이름에 쓸 수 없는 글자라
# (`sanitize_preset_name` 이 지운다) 진짜 프리셋과 겹치지 않는다.
#   `*randomized`         기본 칸. 예전부터 있던 것 - 풀 하나, 생성 설정은 기억하지 않는다(고르면 그대로 둔다).
#   `*randomized:<이름>`  사용자가 더한 칸(사용자 지정 2026-10-04: "10개든 20개든 NAI4.5 나 NAI5.0 에 맞게").
#                         칸마다 풀 · Inject 가 따로이고, 프리셋처럼 **생성 설정(모델 · 파라미터 · 네거티브)을
#                         기억한다** - 고르는 순간 그 설정으로 넘어가고, 모델 배지와 갈래 필터에도 실린다.
# ⚠️ '랜덤 칸인가' 를 문자열 비교로 묻지 않는다(`== "*randomized"` 는 기본 칸만 맞는다) - 아래 판정을 쓴다.
#    기본 칸만 가리킬 때에만 `RANDOMIZED_PRESET` 과 견준다(생성 설정을 기억하지 않는 것은 그 칸뿐이다).
RANDOMIZED_PRESET = "*randomized"
RANDOMIZED_SLOT_PREFIX = "*randomized:"
# randomized_pool.json 에서 더한 칸들이 사는 최상위 키(모드 이름과 겹치지 않는다).
RANDOMIZED_SLOTS_KEY = "slots"


def is_randomized_preset_name(name: Any) -> bool:
    """기본 칸이든 더한 칸이든 - 랜덤 칸의 이름이면 참."""
    text = str(name or "")
    return text == RANDOMIZED_PRESET or bool(randomized_slot_label(text))


def randomized_slot_label(name: Any) -> str:
    """더한 칸의 이름 부분(`*randomized:5.0` -> `5.0`). 기본 칸 · 랜덤 칸이 아닌 것은 빈 문자열."""
    text = str(name or "")
    if not text.startswith(RANDOMIZED_SLOT_PREFIX):
        return ""
    return sanitize_preset_name(text[len(RANDOMIZED_SLOT_PREFIX):])


def randomized_slot_name(label: Any) -> str:
    """이름 부분 -> 목록에 보이는 이름. 빈 이름은 기본 칸이다."""
    clean = sanitize_preset_name(str(label or ""))
    return f"{RANDOMIZED_SLOT_PREFIX}{clean}" if clean else RANDOMIZED_PRESET


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
    options = {key: False for key in PREPROCESSING_OPTION_KEYS}
    options["closed_eyes_sync"] = True
    return options


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


# 카테고리별 랜덤 프롬프트 전처리 필터 커스터마이즈 — 전역(모드 무관) 디스크 SSOT.
# 각 전처리 카테고리(remove_* 체크박스)마다 exclude(자동 제거에서 보호할 태그)/
# include(해당 카테고리 ON일 때 함께 제거할 추가 태그)를 사용자가 지정한다.
# Auto Hide 라운드는 자체 문법(~/__..__)을 가지므로 여기서 제외한다.
# 세 번째 목록 hide(개별 숨김) 는 **라운드 스위치와 무관하게 항상** 제거한다.
# ⚠️ include 로는 이 일을 못 한다 - include 는 라운드가 ON 일 때만 도는데, 사전에
#    있는 태그는 그때 어차피 지워진다. 즉 사전 태그에 대해 include 는 언제나
#    no-op 다(실측 2026-08-31). 우클릭 '자동 숨김' 이 약속을 지키려면 별도 목록이
#    있어야 한다. 우선순위는 exclude(보호) > hide - 보호가 언제나 이긴다.
CATEGORY_FILTER_OPTION_KEYS = (
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
)


def sanitize_tag_list(value: Any) -> list[str]:
    """list[str] 위생화 — 비문자열/빈 항목 제거, 정규화(strip+lower) 기준 중복 제거.
    저장값은 사용자가 입력한 원형(대소문자 포함)을 보존한다."""
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    return cleaned


def normalize_category_filter_overrides(overrides: Any) -> dict[str, Any]:
    """전체 오버라이드 맵을 정규화. {schema_version, categories:{...}} 래핑 형태와
    맨 {option_key: {...}} 형태를 모두 받아 화이트리스트 키만, 세 목록 중 하나라도
    있는 카테고리만 남긴다(파일 청결 유지)."""
    data = overrides if isinstance(overrides, dict) else {}
    categories_raw = data.get("categories") if isinstance(data.get("categories"), dict) else data
    if not isinstance(categories_raw, dict):
        categories_raw = {}
    result: dict[str, Any] = {}
    for key in CATEGORY_FILTER_OPTION_KEYS:
        entry = categories_raw.get(key)
        if not isinstance(entry, dict):
            continue
        exclude = sanitize_tag_list(entry.get("exclude"))
        include = sanitize_tag_list(entry.get("include"))
        hide = sanitize_tag_list(entry.get("hide"))
        if exclude or include or hide:
            result[key] = {"exclude": exclude, "include": include, "hide": hide}
    return result


def load_category_filter_overrides(*, save_root: str | Path | None = None) -> dict[str, Any]:
    """pp_category_filters.json 에서 카테고리 오버라이드 맵을 로드.
    손상 파일/형식 오류는 빈 dict 로 떨어뜨린다."""
    path = _existing_save_file("pp_category_filters.json", save_root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return normalize_category_filter_overrides(data if isinstance(data, dict) else {})


def save_category_filter_overrides(overrides: dict[str, Any], *, save_root: str | Path | None = None) -> None:
    path = _coerce_save_root(save_root) / "pp_category_filters.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": 1, "categories": normalize_category_filter_overrides(overrides)}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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


# last_used_preset.json 에서 '마지막에 보던 랜덤 칸' 이 사는 최상위 키(모드 이름과 겹치지 않는다).
LAST_USED_RANDOMIZED_KEY = "randomized"


def load_last_used_randomized(mode: str | None = None, *, save_root: str | Path | None = None) -> str:
    """마지막에 보던 랜덤 칸(보고 있지 않았으면 빈 문자열).

    마지막 **프리셋**(`load_last_used_preset`)과 따로 적는다 - 랜덤 칸은 Prefix 밖의 설정을 직전 프리셋에서 빌려
    쓰므로, 다시 켤 때 둘 다 필요하다(프리셋 = 빌려 올 곳, 랜덤 칸 = 지금 서 있는 곳).
    """
    mode_key = normalize_prompt_engineering_mode(mode)
    path = _existing_save_file(Path("presets") / "last_used_preset.json", save_root)
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        return ""
    by_mode = data.get(LAST_USED_RANDOMIZED_KEY) if isinstance(data, dict) else None
    value = by_mode.get(mode_key) if isinstance(by_mode, dict) else ""
    return str(value) if value else ""


def save_last_used_randomized(mode: str | None, name: str, *, save_root: str | Path | None = None) -> None:
    """마지막에 보던 랜덤 칸을 적는다(빈 문자열 = 랜덤 칸을 떠났다)."""
    mode_key = normalize_prompt_engineering_mode(mode)
    path = last_used_preset_file(save_root=save_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    by_mode = data.get(LAST_USED_RANDOMIZED_KEY)
    by_mode = by_mode if isinstance(by_mode, dict) else {}
    by_mode[mode_key] = str(name or "")
    data[LAST_USED_RANDOMIZED_KEY] = by_mode
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def randomized_pool_file(*, save_root: str | Path | None = None) -> Path:
    return _coerce_save_root(save_root) / "presets" / "randomized_pool.json"


def _read_randomized_pool_data(save_root: str | Path | None) -> dict[str, Any]:
    path = _existing_save_file(Path("presets") / "randomized_pool.json", save_root)
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        data = {}
    return data if isinstance(data, dict) else {}


def _write_randomized_pool_data(data: dict[str, Any], save_root: str | Path | None) -> None:
    path = randomized_pool_file(save_root=save_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _randomized_raw_entry(data: dict[str, Any], mode_key: str, slot: str = "") -> Any:
    """그 칸이 파일에 적혀 있는 모양 그대로(`slot` = 더한 칸의 이름, 빈 문자열 = 기본 칸).

    기본 칸은 예전 자리 `data[mode]` 에 그대로 있고, 더한 칸은 `data["slots"][mode][이름]` 에 산다.
    ⚠️ 더한 칸을 `data[mode]` 안에 넣지 않는다 - 옛 판은 그 dict 를 네 키로 **다시 써서**
       (`_randomized_entry_dict`) 모르는 키를 지운다. 최상위 키는 읽고-고치고-쓰는 동안 그대로 남으므로,
       판을 내렸다 올려도 더한 칸이 살아 있다.
    """
    if not isinstance(data, dict):
        return None
    if not slot:
        return data.get(mode_key)
    slots = data.get(RANDOMIZED_SLOTS_KEY)
    by_mode = slots.get(mode_key) if isinstance(slots, dict) else None
    return by_mode.get(slot) if isinstance(by_mode, dict) else None


def _store_randomized_entry(
    data: dict[str, Any], mode_key: str, slot: str, entry: dict[str, Any], *, main_settings: Any = None,
) -> None:
    """칸 하나를 제자리에 적는다. 더한 칸은 생성 설정(`main_settings`)을 함께 쥔다 - 안 주면 있던 것을 지킨다
    (풀이나 Inject 만 고치러 온 길이 생성 설정을 지우면 안 된다)."""
    if not slot:
        data[mode_key] = entry
        return
    slots = data.get(RANDOMIZED_SLOTS_KEY)
    slots = slots if isinstance(slots, dict) else {}
    by_mode = slots.get(mode_key)
    by_mode = by_mode if isinstance(by_mode, dict) else {}
    if main_settings is None:
        previous = by_mode.get(slot)
        main_settings = previous.get("main_settings") if isinstance(previous, dict) else {}
    by_mode[slot] = {**entry, "main_settings": main_settings if isinstance(main_settings, dict) else {}}
    slots[mode_key] = by_mode
    data[RANDOMIZED_SLOTS_KEY] = slots


def _randomized_slot_labels(data: dict[str, Any], mode_key: str) -> list[str]:
    """이 모드에 더한 칸의 이름 - 파일에 적힌 차례(= 만든 차례)."""
    slots = data.get(RANDOMIZED_SLOTS_KEY) if isinstance(data, dict) else None
    by_mode = slots.get(mode_key) if isinstance(slots, dict) else None
    if not isinstance(by_mode, dict):
        return []
    # 이름이 `sanitize_preset_name` 을 그대로 통과하는 것만 - 손으로 고친 파일의 이상한 키는 목록에 올리지 않는다.
    return [label for label, entry in by_mode.items()
            if isinstance(label, str) and label and label == sanitize_preset_name(label) and isinstance(entry, dict)]


def _randomized_pool_entry(data: dict[str, Any], mode_key: str, slot: str = "") -> tuple[list, str, str, bool]:
    """Extract (pool, wildcard_front, wildcard_back, wildcard_enabled) for a mode (and slot).

    Accepts the legacy list format (``data[mode] = [...]``) and the dict format
    (``{"pool": [...], "wildcard_front": str, "wildcard_back": str, "wildcard_enabled": bool}``).
    The earlier single-slot ``"wildcard"`` key is migrated into ``wildcard_back``."""
    raw = _randomized_raw_entry(data, mode_key, slot)
    if isinstance(raw, dict):
        pool = raw.get("pool", [])
        front = raw.get("wildcard_front", "")
        back = raw.get("wildcard_back", raw.get("wildcard", ""))
        enabled = bool(raw.get("wildcard_enabled", False))
    elif isinstance(raw, list):
        pool, front, back, enabled = raw, "", "", False
    else:
        pool, front, back, enabled = [], "", "", False
    if not isinstance(pool, list):
        pool = []
    return pool, str(front or ""), str(back or ""), bool(enabled)


def _restore_randomized_pool(pool: list, valid: set[str]) -> list[str]:
    """파일의 풀에서 지금도 있는 프리셋만, 차례대로 한 번씩."""
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


def load_randomized_pool(
    mode: str | None,
    preset_names: list[str] | None = None,
    *,
    save_root: str | Path | None = None,
    slot: str = "",
) -> list[str]:
    mode_key = normalize_prompt_engineering_mode(mode)
    data = _read_randomized_pool_data(save_root)
    pool, _front, _back, _enabled = _randomized_pool_entry(data, mode_key, slot)
    valid = set(preset_names or list_preset_names(mode_key, save_root=save_root))
    return _restore_randomized_pool(pool, valid)


def _randomized_entry_dict(pool, front, back, enabled) -> dict[str, Any]:
    return {
        "pool": list(pool or []),
        "wildcard_front": str(front or ""),
        "wildcard_back": str(back or ""),
        "wildcard_enabled": bool(enabled),
    }


def save_randomized_pool(
    mode: str | None, pool: list[str], *, save_root: str | Path | None = None, slot: str = ""
) -> None:
    mode_key = normalize_prompt_engineering_mode(mode)
    data = _read_randomized_pool_data(save_root)
    _pool, front, back, enabled = _randomized_pool_entry(data, mode_key, slot)
    _store_randomized_entry(data, mode_key, slot, _randomized_entry_dict(pool, front, back, enabled))
    _write_randomized_pool_data(data, save_root)


def load_randomized_wildcard(
    mode: str | None, *, save_root: str | Path | None = None, slot: str = ""
) -> tuple[str, str, bool]:
    mode_key = normalize_prompt_engineering_mode(mode)
    data = _read_randomized_pool_data(save_root)
    _pool, front, back, enabled = _randomized_pool_entry(data, mode_key, slot)
    return front, back, enabled


def save_randomized_wildcard(
    mode: str | None, front: str, back: str, enabled: bool, *, save_root: str | Path | None = None,
    slot: str = "",
) -> None:
    mode_key = normalize_prompt_engineering_mode(mode)
    data = _read_randomized_pool_data(save_root)
    pool, _front, _back, _enabled = _randomized_pool_entry(data, mode_key, slot)
    _store_randomized_entry(data, mode_key, slot, _randomized_entry_dict(pool, front, back, enabled))
    _write_randomized_pool_data(data, save_root)


def load_randomized_slots(
    mode: str | None,
    preset_names: list[str] | None = None,
    *,
    save_root: str | Path | None = None,
) -> dict[str, dict[str, Any]]:
    """이 모드에 더한 랜덤 칸 전부 - `{이름: {pool, wildcard_*, main_settings}}`, 만든 차례. 파일은 한 번만 읽는다."""
    mode_key = normalize_prompt_engineering_mode(mode)
    data = _read_randomized_pool_data(save_root)
    valid = set(preset_names or list_preset_names(mode_key, save_root=save_root))
    slots: dict[str, dict[str, Any]] = {}
    for label in _randomized_slot_labels(data, mode_key):
        pool, front, back, enabled = _randomized_pool_entry(data, mode_key, label)
        raw = _randomized_raw_entry(data, mode_key, label)
        main = raw.get("main_settings") if isinstance(raw, dict) else None
        slots[label] = {
            **_randomized_entry_dict(_restore_randomized_pool(pool, valid), front, back, enabled),
            "main_settings": dict(main) if isinstance(main, dict) else {},
        }
    return slots


def save_randomized_slot(
    mode: str | None, slot: str, entry: dict[str, Any], *, save_root: str | Path | None = None
) -> None:
    """더한 칸 하나를 통째로 적는다(만들 때 · 생성 설정을 고쳤을 때)."""
    mode_key = normalize_prompt_engineering_mode(mode)
    label = sanitize_preset_name(str(slot or ""))
    if not label:
        raise ValueError("Randomized slot name is required")
    data = _read_randomized_pool_data(save_root)
    main = entry.get("main_settings") if isinstance(entry, dict) else None
    _store_randomized_entry(
        data, mode_key, label,
        _randomized_entry_dict(
            entry.get("pool"), entry.get("wildcard_front"), entry.get("wildcard_back"), entry.get("wildcard_enabled")),
        main_settings=normalize_preset_main_settings(copy.deepcopy(main)) if isinstance(main, dict) else {},
    )
    _write_randomized_pool_data(data, save_root)


def delete_randomized_slot(mode: str | None, slot: str, *, save_root: str | Path | None = None) -> bool:
    mode_key = normalize_prompt_engineering_mode(mode)
    data = _read_randomized_pool_data(save_root)
    slots = data.get(RANDOMIZED_SLOTS_KEY)
    by_mode = slots.get(mode_key) if isinstance(slots, dict) else None
    if not isinstance(by_mode, dict) or slot not in by_mode:
        return False
    del by_mode[slot]
    _write_randomized_pool_data(data, save_root)
    return True


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


def preset_preview_file(context: Any, preset_name: str, mode_key: str = "") -> Path | None:
    """Resolve the preset thumbnail file on disk.

    thumbnail_url은 프리셋 JSON에 기록된 적이 없다(작성 코드 부재) — 썸네일의
    SSOT는 save/presets/previews/<name>.<ext> 파일이며, 즐겨찾기 등록 프리셋은
    save/presets/favorites/도 함께 본다. prompt_tools_routes의 GET 라우트와
    상태 요약이 같은 해석을 쓰도록 core에 둔다.
    """
    if is_randomized_preset_name(preset_name):
        return None
    safe_name = Path(str(preset_name or "").strip()).name
    if not safe_name or safe_name == "*randomized":
        return None
    exts = (".png", ".webp", ".jpg", ".jpeg")
    # 썸네일은 장식 — 경로 헬퍼가 없는 축소 컨텍스트(테스트 하네스 등)에서도
    # 프리셋 목록 자체를 실패시키지 않는다.
    try:
        preview_dirs = context._existing_save_dirs("presets", "previews")
    except Exception:
        return None
    candidates = [
        preview_dir / f"{safe_name}{ext}"
        for preview_dir in preview_dirs
        for ext in exts
    ]
    try:
        favorites_path = context._existing_save_path("presets", "favorites.json")
        favorite_items = json.loads(favorites_path.read_text(encoding="utf-8")) if favorites_path.exists() else []
        if any(
            isinstance(item, dict)
            and item.get("name") == safe_name
            and (not mode_key or item.get("mode") == mode_key)
            for item in favorite_items
        ):
            for favorite_dir in context._existing_save_dirs("presets", "favorites"):
                candidates.extend(favorite_dir / f"{safe_name}{ext}" for ext in exts)
    except Exception:
        pass
    for candidate in candidates:
        try:
            target = candidate.resolve()
        except Exception:
            continue
        if target.is_file():
            return target
    return None


def preset_thumbnail_url(context: Any, preset_name: str, mode_key: str = "") -> str:
    """File-derived thumbnail URL for preset previews ("" when no file)."""
    from urllib.parse import quote

    target = preset_preview_file(context, preset_name, mode_key)
    if target is None:
        return ""
    safe_name = Path(str(preset_name or "").strip()).name
    try:
        version = int(target.stat().st_mtime)
    except OSError:
        version = 0
    return (
        "/api/prompt-engineering/preset-thumbnail"
        f"?name={quote(safe_name, safe='')}&mode={quote(str(mode_key or ''), safe='')}&v={version}"
    )


def preset_thumbnail_url_map(context: Any, names: list[str], mode_key: str = "") -> dict[str, str]:
    """Bulk ``preset_thumbnail_url`` for whole preset lists.

    state()가 module_state마다 프리셋 전수를 요약하므로, 프리셋별 확장자 stat
    프로브(n x 4) + favorites.json 재읽기 대신 디렉터리당 1회 listing으로
    줄인다(Codex CONCERN). 후보 순서(디렉터리 우선, 확장자 순)는 단건 버전과
    동일하다.
    """
    from urllib.parse import quote

    result = {str(name): "" for name in names}
    if not result:
        return result
    exts = (".png", ".webp", ".jpg", ".jpeg")
    try:
        preview_dirs = list(context._existing_save_dirs("presets", "previews"))
    except Exception:
        return result

    def _dir_listing(dirs: list[Path]) -> list[tuple[Path, set[str]]]:
        listing: list[tuple[Path, set[str]]] = []
        for directory in dirs:
            try:
                listing.append((Path(directory), set(os.listdir(directory))))
            except OSError:
                continue
        return listing

    preview_listing = _dir_listing(preview_dirs)
    favorite_names: set[str] = set()
    favorite_listing: list[tuple[Path, set[str]]] = []
    try:
        favorites_path = context._existing_save_path("presets", "favorites.json")
        favorite_items = json.loads(favorites_path.read_text(encoding="utf-8")) if favorites_path.exists() else []
        favorite_names = {
            str(item.get("name"))
            for item in favorite_items
            if isinstance(item, dict) and (not mode_key or item.get("mode") == mode_key)
        }
        if favorite_names:
            favorite_listing = _dir_listing(list(context._existing_save_dirs("presets", "favorites")))
    except Exception:
        pass

    def _find(listing: list[tuple[Path, set[str]]], safe_name: str) -> Path | None:
        for directory, entries in listing:
            for ext in exts:
                if f"{safe_name}{ext}" in entries:
                    return directory / f"{safe_name}{ext}"
        return None

    for name in names:
        if is_randomized_preset_name(name):
            continue
        safe_name = Path(str(name or "").strip()).name
        if not safe_name or safe_name == "*randomized":
            continue
        target = _find(preview_listing, safe_name)
        if target is None and safe_name in favorite_names:
            target = _find(favorite_listing, safe_name)
        if target is None:
            continue
        try:
            version = int(target.stat().st_mtime)
        except OSError:
            version = 0
        result[str(name)] = (
            "/api/prompt-engineering/preset-thumbnail"
            f"?name={quote(safe_name, safe='')}&mode={quote(str(mode_key or ''), safe='')}&v={version}"
        )
    return result


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
        self._dirty_modes: set[str] = set()

    def mode(self, mode: str | None = None) -> str:
        return normalize_prompt_engineering_mode(mode or self._mode_getter())

    def _load_state(self, mode: str) -> dict[str, Any]:
        preset_names = self.list_preset_names(mode)
        if "default" not in preset_names:
            preset_names.insert(0, "default")
        current_preset = self.load_last_used_preset(mode)
        if current_preset not in preset_names:
            current_preset = "default"

        settings = default_prompt_engineering_settings(save_root=self._save_root)
        settings = merge_settings(settings, self.load_mode_settings(mode))
        if current_preset in preset_names:
            preset_data = self.read_preset_data(current_preset, mode)
            settings = merge_settings(settings, preset_data.get("module_settings") or {})

        randomized_pool = self.load_randomized_pool(mode, preset_names)
        wc_front, wc_back, wc_enabled = self.load_randomized_wildcard(mode)
        randomized_slots = load_randomized_slots(mode, preset_names, save_root=self._save_root)
        # 마지막에 **랜덤 칸**을 보고 있었으면 그 칸으로 연다.
        # ⚠️ 안 그러면 다시 켰을 때 '직전 프리셋' 이 현재 프리셋으로 서는데 생성 설정은 랜덤 칸에서 쓰던 그대로라,
        #    다음 저장 길목이 그 설정을 **직전 프리셋 파일에 써 넣는다**(실측 10-04: 4.5 프리셋의 모델이 5.0 이 됐다).
        #    Prefix 밖의 설정(전처리 옵션 · Auto-Hide)은 위에서 읽은 직전 프리셋의 것 그대로다 - 랜덤 칸은 원래 그것을
        #    빌려 쓴다. Prefix · Postfix 는 서비스가 첫 상태를 낼 때 한 번 굴려 채운다(`randomized_needs_roll`).
        last_randomized = load_last_used_randomized(mode, save_root=self._save_root)
        needs_roll = False
        if last_randomized == RANDOMIZED_PRESET or randomized_slot_label(last_randomized) in randomized_slots:
            current_preset = randomized_slot_name(randomized_slot_label(last_randomized))
            needs_roll = True
        return {
            "settings": settings,
            "preset_list": preset_names,
            "current_preset": current_preset,
            "randomized_preset_list": randomized_pool,
            "randomized_wildcard_front": wc_front,
            "randomized_wildcard_back": wc_back,
            "randomized_wildcard_enabled": wc_enabled,
            # 위 넷은 기본 칸(`*randomized`)의 것 - 예전 자리 그대로다. 더한 칸은 여기에 이름별로 산다.
            "randomized_slots": randomized_slots,
            "randomized_needs_roll": needs_roll,
        }

    def list_preset_names(self, mode: str | None = None) -> list[str]:
        return list_preset_names(mode, save_root=self._save_root)

    def read_preset_data(self, preset_name: str, mode: str | None = None) -> dict[str, Any]:
        # ⚠️ 랜덤 칸은 **파일로 가지 않는다.** 이름을 그대로 넘기면 `sanitize_preset_name` 이 `*` 를 지워
        #    `randomized.json` 이라는 **남의 프리셋**을 읽는다(그런 이름의 프리셋이 있으면 그 설정이 적용된다).
        if is_randomized_preset_name(preset_name):
            return self._randomized_preset_data(str(preset_name), mode)
        return read_preset_data(preset_name, mode, save_root=self._save_root)

    def write_preset_data(self, preset_name: str, mode: str | None, data: dict[str, Any]) -> None:
        if is_randomized_preset_name(preset_name):
            self._write_randomized_preset_data(str(preset_name), mode, data)
            return
        write_preset_data(preset_name, mode, data, save_root=self._save_root)

    def _randomized_preset_data(self, name: str, mode: str | None = None) -> dict[str, Any]:
        """랜덤 칸을 프리셋 모양으로 돌려준다 - **생성 설정만** 있다(Prefix · Postfix 는 뽑을 때 정해진다).

        기본 칸은 기억하는 것이 없어 빈 dict 다(예전 그대로: 고르면 생성 설정을 건드리지 않는다).
        더한 칸은 빈 설정이어도 dict 를 준다 - 부르는 쪽이 `if not data` 로 '없는 프리셋' 을 가른다.
        """
        label = randomized_slot_label(name)
        entry = (self.state(mode).get("randomized_slots") or {}).get(label) if label else None
        if not isinstance(entry, dict):
            return {}
        return {
            "api_mode": self.mode(mode),
            "randomized": True,
            "module_settings": {},
            "main_settings": copy.deepcopy(entry.get("main_settings") or {}),
        }

    def _write_randomized_preset_data(self, name: str, mode: str | None, data: dict[str, Any]) -> None:
        """더한 칸에 생성 설정을 적는다. module_settings 는 받지 않는다 - 그 칸의 Prefix · Postfix 는 뽑힌
        프리셋의 것이라 저장할 것이 아니다. 기본 칸에는 아무것도 적지 않는다."""
        mode_key = self.mode(mode)
        label = randomized_slot_label(name)
        entry = (self.state(mode_key).get("randomized_slots") or {}).get(label) if label else None
        if not isinstance(entry, dict):
            return
        main = (data or {}).get("main_settings")
        entry["main_settings"] = normalize_preset_main_settings(copy.deepcopy(main)) if isinstance(main, dict) else {}
        save_randomized_slot(mode_key, label, entry, save_root=self._save_root)

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

    def save_randomized_pool(self, mode: str | None, pool: list[str], *, slot: str = "") -> None:
        save_randomized_pool(mode, pool, save_root=self._save_root, slot=slot)

    def load_randomized_wildcard(self, mode: str | None = None) -> tuple[str, str, bool]:
        return load_randomized_wildcard(mode, save_root=self._save_root)

    def save_randomized_wildcard(
        self, mode: str | None, front: str, back: str, enabled: bool, *, slot: str = ""
    ) -> None:
        save_randomized_wildcard(mode, front, back, enabled, save_root=self._save_root, slot=slot)

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
        mode_key = self.mode(mode)
        state = self.state(mode_key)
        merged = merge_settings(state["settings"], updates)
        if merged != state["settings"]:
            state["settings"] = merged
            self._dirty_modes.add(mode_key)
        return copy.deepcopy(state["settings"])

    def preset_options(self, mode: str | None = None) -> list[str]:
        names = list(self.state(mode)["preset_list"])
        if "default" not in names:
            names.insert(0, "default")
        return [*names, *self.randomized_names(mode)]

    # ---- 랜덤 칸 ----------------------------------------------------------------

    def randomized_names(self, mode: str | None = None) -> list[str]:
        """이 모드의 랜덤 칸 이름 - 기본 칸이 맨 앞, 더한 칸은 만든 차례."""
        slots = self.state(mode).get("randomized_slots") or {}
        return [RANDOMIZED_PRESET, *(randomized_slot_name(label) for label in slots)]

    def has_randomized(self, name: str, mode: str | None = None) -> bool:
        if str(name or "") == RANDOMIZED_PRESET:
            return True
        label = randomized_slot_label(name)
        return bool(label) and label in (self.state(mode).get("randomized_slots") or {})

    def active_randomized_name(self, mode: str | None = None) -> str:
        """풀 · Inject 편집이 향하는 칸: 지금 프리셋이 랜덤 칸이면 그 칸, 아니면 기본 칸(예전 그대로)."""
        current = str(self.state(mode).get("current_preset") or "")
        if is_randomized_preset_name(current) and self.has_randomized(current, mode):
            return current
        return RANDOMIZED_PRESET

    def randomized_view(self, name: str | None = None, mode: str | None = None) -> dict[str, Any]:
        """그 칸의 풀 · Inject · 생성 설정(사본). 이름을 안 주면 편집이 향하는 칸."""
        state = self.state(mode)
        target = str(name) if name else self.active_randomized_name(mode)
        label = randomized_slot_label(target)
        if label:
            entry = (state.get("randomized_slots") or {}).get(label) or {}
            return {
                "name": randomized_slot_name(label),
                "pool": list(entry.get("pool") or []),
                "wildcard_front": str(entry.get("wildcard_front") or ""),
                "wildcard_back": str(entry.get("wildcard_back") or ""),
                "wildcard_enabled": bool(entry.get("wildcard_enabled")),
                "main_settings": copy.deepcopy(entry.get("main_settings") or {}),
            }
        return {
            "name": RANDOMIZED_PRESET,
            "pool": list(state["randomized_preset_list"]),
            "wildcard_front": str(state.get("randomized_wildcard_front") or ""),
            "wildcard_back": str(state.get("randomized_wildcard_back") or ""),
            "wildcard_enabled": bool(state.get("randomized_wildcard_enabled")),
            "main_settings": {},
        }

    def _randomized_pool_ref(self, state: dict[str, Any], name: str) -> list[str]:
        """그 칸의 **살아 있는** 풀(같은 list). 기본 칸은 예전 자리를 그대로 쓴다."""
        label = randomized_slot_label(name)
        return state["randomized_slots"][label]["pool"] if label else state["randomized_preset_list"]

    def create_randomized_slot(
        self,
        label: str,
        mode: str | None = None,
        *,
        main_settings: dict[str, Any] | None = None,
    ) -> tuple[bool, str]:
        """랜덤 칸을 하나 더한다. 지금의 생성 설정을 그 칸이 기억하고(프리셋 만들기와 같다) 그 칸으로 넘어간다 -
        풀은 비어 있으니 곧바로 채우게."""
        mode_key = self.mode(mode)
        clean = sanitize_preset_name(str(label or ""))
        if not clean:
            return False, "랜덤 칸 이름이 비어 있습니다."
        state = self.state(mode_key)
        slots = state.setdefault("randomized_slots", {})
        if clean in slots:
            return False, f"이미 있는 랜덤 칸입니다: {clean}"
        entry = {
            **_randomized_entry_dict([], "", "", False),
            "main_settings": (
                normalize_preset_main_settings(copy.deepcopy(main_settings)) if main_settings is not None else {}
            ),
        }
        save_randomized_slot(mode_key, clean, entry, save_root=self._save_root)
        slots[clean] = entry
        name = randomized_slot_name(clean)
        state["current_preset"] = name
        self._remember_randomized(mode_key, name)
        self._dirty_modes.discard(mode_key)
        return True, name

    def _remember_randomized(self, mode_key: str, name: str) -> None:
        """마지막에 보던 랜덤 칸을 적는다(빈 문자열 = 랜덤 칸을 떠났다). 다시 켤 때 `_load_state` 가 읽는다."""
        save_last_used_randomized(mode_key, name, save_root=self._save_root)

    def delete_randomized_slot(self, name: str, mode: str | None = None) -> tuple[bool, str]:
        mode_key = self.mode(mode)
        label = randomized_slot_label(name)
        if not label:
            return False, "랜덤 프리셋 모드는 삭제할 수 없습니다."
        state = self.state(mode_key)
        slots = state.get("randomized_slots") or {}
        if label not in slots:
            return False, f"랜덤 칸을 찾을 수 없습니다: {label}"
        delete_randomized_slot(mode_key, label, save_root=self._save_root)
        del slots[label]
        if state.get("current_preset") == randomized_slot_name(label):
            # 지운 칸을 보고 있었다 - 기본 칸으로 물러난다(생성 설정 · Prefix 는 그대로 둔다).
            state["current_preset"] = RANDOMIZED_PRESET
            self._remember_randomized(mode_key, RANDOMIZED_PRESET)
        return True, randomized_slot_name(label)

    def randomized_available_presets(self, mode: str | None = None) -> list[str]:
        state = self.state(mode)
        selected = set(self._randomized_pool_ref(state, self.active_randomized_name(mode)))
        return [
            name for name in state["preset_list"]
            if name not in {"default", "*randomized"} and name not in selected
        ]

    def set_preset(self, preset_name: str, mode: str | None = None) -> bool:
        state = self.state(mode)
        if is_randomized_preset_name(preset_name):
            # 랜덤 칸은 살아 있는 Prefix · Postfix 를 건드리지 않는다 - 다음 Random 이 풀에서 뽑아 채운다.
            if not self.has_randomized(str(preset_name), mode):
                return False
            state["current_preset"] = randomized_slot_name(randomized_slot_label(preset_name))
            self._remember_randomized(self.mode(mode), state["current_preset"])
            self._dirty_modes.discard(self.mode(mode))
            return True
        name = sanitize_preset_name(preset_name)
        if name not in state["preset_list"]:
            return False
        mode_key = self.mode(mode)
        preset_data = self.read_preset_data(name, mode_key)
        # ⚠️ **앞 프리셋의 살아 있는 값 위에 얹지 않는다.** 그렇게 하면 새 프리셋이
        #    정의하지 않은 키가 앞 프리셋 것으로 남고, 그 뒤 어떤 저장 경로든
        #    `state["settings"]` 를 통째로 파일에 쓰는 순간 **남의 값이 이 프리셋에
        #    영구히 박힌다**(사용자 제보 2026-08-25: "제목만 2번이지 내용물은 1번").
        #    앱을 새로 켰을 때와 같은 자리에서 시작한다 - `_load_state` 와 같은 조립이다.
        base = default_prompt_engineering_settings(save_root=self._save_root)
        base = merge_settings(base, self.load_mode_settings(mode_key))
        state["settings"] = merge_settings(base, preset_data.get("module_settings") or {})
        if is_randomized_preset_name(state.get("current_preset")):
            self._remember_randomized(mode_key, "")      # 랜덤 칸을 떠났다 - 다시 켜면 이 프리셋으로 연다
        state["current_preset"] = name
        self.save_last_used_preset(self.mode(mode), name)
        self._dirty_modes.discard(self.mode(mode))
        return True

    def save_current_preset(
        self,
        mode: str | None = None,
        *,
        main_settings: dict[str, Any] | None = None,
        write_module_settings: bool = True,
    ) -> tuple[bool, str]:
        """현재 프리셋에 쓴다.

        ⚠️ ``write_module_settings=False`` 는 **생성 파라미터만** 반영하는 경로용이다
        (`sync_param_into_current_preset` / `sync_negative_into_current_preset`).
        그 경로가 module_settings 까지 통째로 덮으면, 살아 있는 설정에 잠깐 섞인
        남의 값(스왑 직후 늦게 도착한 편집 등)이 **파일에 영구히 박힌다.**
        한 키를 반영하러 온 요청이 나머지 전부를 갈아치울 이유는 없다.
        """
        mode_key = self.mode(mode)
        state = self.state(mode_key)
        name = state["current_preset"]
        if name in {"", "(프리셋 없음)", "*randomized"}:
            return False, "저장할 현재 프리셋이 없습니다."
        if is_randomized_preset_name(name):
            # 더한 랜덤 칸 - **생성 설정만** 기억한다. 살아 있는 Prefix · Postfix 는 뽑힌 프리셋의 것이라 저장할
            # 것이 아니고, 마지막 프리셋으로도 적지 않는다(랜덤 칸은 다음 실행에 이어지지 않는다 - 기본 칸과 같다).
            if not self.has_randomized(name, mode_key):
                return False, "저장할 현재 프리셋이 없습니다."
            if main_settings is not None:
                self.write_preset_data(name, mode_key, {"main_settings": main_settings})
            return True, name
        data = self.read_preset_data(name, mode_key)
        data["api_mode"] = mode_key
        if write_module_settings:
            data["module_settings"] = copy.deepcopy(state["settings"])
        else:
            data.setdefault("module_settings", copy.deepcopy(state["settings"]))
        if main_settings is not None:
            # Generation params travel with the preset (future01 parity); runtime
            # -state keys are stripped so they stay session-global.
            data["main_settings"] = normalize_preset_main_settings(copy.deepcopy(main_settings))
        self.write_preset_data(name, mode_key, data)
        self.save_last_used_preset(mode_key, name)
        # ⚠️ **쓴 것만 clean 으로 친다.** `discard` 는 "살아 있는 설정을 파일에 다 썼다"
        #    는 뜻인데, `write_module_settings=False` 갈래는 그걸 **안 썼다.** 그런데도
        #    지우면 아직 저장 안 된 Prefix 편집이 미아가 되어, 다음 생성/종료의
        #    `persist_active_settings` 가 clean 으로 보고 넘어가 사라진다
        #    (Codex 리뷰 BLOCK, 재현됨 - 한 데이터 유실을 고치다 다른 하나를 냈다).
        if write_module_settings:
            self._dirty_modes.discard(mode_key)
        return True, name

    def create_preset(
        self,
        preset_name: str,
        mode: str | None = None,
        *,
        main_settings: dict[str, Any] | None = None,
    ) -> tuple[bool, str]:
        mode_key = self.mode(mode)
        name = sanitize_preset_name(preset_name)
        if not name:
            return False, "프리셋 이름이 비어 있습니다."
        data = {
            "api_mode": mode_key,
            "module_settings": copy.deepcopy(self.state(mode_key)["settings"]),
            "main_settings": (
                normalize_preset_main_settings(copy.deepcopy(main_settings))
                if main_settings is not None
                else {}
            ),
        }
        self.write_preset_data(name, mode_key, data)
        self.refresh(mode_key)
        self.set_preset(name, mode_key)
        return True, name

    def export_preset(
        self,
        preset_name: str,
        mode: str | None,
        data: dict[str, Any],
        *,
        overwrite: bool = False,
    ) -> tuple[bool, str]:
        """다른 곳(믹스 조합)에서 만든 프리셋을 **파일로만** 쓴다.

        ⚠️ `create_preset` 을 쓰면 안 된다. 그쪽은 `refresh()` 로 디스크에서 상태를 다시
           조립해 **아직 파일에 안 쓴 편집을 버리고**, 곧바로 `set_preset` 으로 현재
           프리셋을 새것으로 **바꾼다**(사용자 결정 2026-09-21: 내보내도 전환하지 않는다).
           여기서는 파일을 쓰고 이름 목록만 다시 읽는다 - 살아 있는 설정은 그대로다.
        ⚠️ **지금 쓰는 프리셋에는 쓰지 않는다.** 다음 `persist_active_settings` 가 살아
           있는(표식이 박힌) 설정으로 곧바로 되돌려 버린다 - 조용한 되돌림이다.

        반환: (성공, 이름 또는 사유). 같은 이름이 있고 `overwrite` 가 아니면 사유는 "exists".
        """
        mode_key = self.mode(mode)
        name = sanitize_preset_name(preset_name)
        if not name:
            return False, "프리셋 이름이 비어 있습니다."
        if name in {"default", "*randomized"} or name.endswith(".hires"):
            return False, f"이 이름으로는 내보낼 수 없습니다: {name}"
        state = self.state(mode_key)
        if name == state.get("current_preset"):
            return False, "지금 쓰는 프리셋에는 내보낼 수 없습니다 - 다른 이름을 고르세요."
        if name in self.list_preset_names(mode_key) and not overwrite:
            return False, "exists"
        payload = copy.deepcopy(data or {})
        payload["api_mode"] = mode_key
        self.write_preset_data(name, mode_key, payload)
        state["preset_list"] = self.list_preset_names(mode_key)
        return True, name

    def delete_preset(self, preset_name: str, mode: str | None = None) -> tuple[bool, str]:
        mode_key = self.mode(mode)
        # ⚠️ 이름을 다듬기 **전에** 가른다 - `sanitize_preset_name` 은 `*` · `:` 를 지워 랜덤 칸을 엉뚱한 프리셋 이름으로 만든다.
        if is_randomized_preset_name(preset_name):
            return self.delete_randomized_slot(str(preset_name), mode_key)
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

    # ⚠️ 아래 넷은 **지금 보는 랜덤 칸**(`active_randomized_name`)을 고친다. 그 칸을 고른 채로만 관리 화면이
    #    열리므로 화면이 본 칸과 같다 - 랜덤 칸을 고르지 않았으면 기본 칸이다(예전 그대로).
    def add_randomized_preset(self, preset_name: str, mode: str | None = None) -> tuple[bool, str]:
        mode_key = self.mode(mode)
        state = self.state(mode_key)
        target = self.active_randomized_name(mode_key)
        name = sanitize_preset_name(preset_name)
        if name not in self.randomized_available_presets(mode_key):
            return False, "랜덤 풀에 추가할 수 없는 프리셋입니다."
        pool = self._randomized_pool_ref(state, target)
        pool.append(name)
        self.save_randomized_pool(mode_key, pool, slot=randomized_slot_label(target))
        return True, name

    def remove_randomized_preset(self, preset_name: str, mode: str | None = None) -> tuple[bool, str]:
        mode_key = self.mode(mode)
        state = self.state(mode_key)
        target = self.active_randomized_name(mode_key)
        name = sanitize_preset_name(preset_name)
        pool = self._randomized_pool_ref(state, target)
        if name not in pool:
            return False, "랜덤 풀에 없는 프리셋입니다."
        pool.remove(name)
        self.save_randomized_pool(mode_key, pool, slot=randomized_slot_label(target))
        return True, name

    def clear_randomized_presets(self, mode: str | None = None) -> tuple[bool, str]:
        mode_key = self.mode(mode)
        target = self.active_randomized_name(mode_key)
        self._randomized_pool_ref(self.state(mode_key), target).clear()
        self.save_randomized_pool(mode_key, [], slot=randomized_slot_label(target))
        return True, ""

    def set_randomized_wildcard(
        self, front: str, back: str, enabled: bool, mode: str | None = None
    ) -> tuple[bool, str]:
        mode_key = self.mode(mode)
        state = self.state(mode_key)
        label = randomized_slot_label(self.active_randomized_name(mode_key))
        wc_front = str(front or "")
        wc_back = str(back or "")
        en = bool(enabled)
        if label:
            entry = state["randomized_slots"][label]
            entry["wildcard_front"] = wc_front
            entry["wildcard_back"] = wc_back
            entry["wildcard_enabled"] = en
        else:
            state["randomized_wildcard_front"] = wc_front
            state["randomized_wildcard_back"] = wc_back
            state["randomized_wildcard_enabled"] = en
        self.save_randomized_wildcard(mode_key, wc_front, wc_back, en, slot=label)
        return True, ""

    def persist_active_settings(self, mode: str | None = None, *, force: bool = False) -> tuple[bool, str]:
        mode_key = self.mode(mode)
        if mode_key not in self._states:
            return False, ""
        state = self.state(mode_key)
        current = str(state.get("current_preset") or "")
        if not force and mode_key not in self._dirty_modes:
            return False, current

        settings = copy.deepcopy(state["settings"])
        randomized = is_randomized_preset_name(current)
        if current and current != "(프리셋 없음)" and not randomized:
            data = self.read_preset_data(current, mode_key)
            data["api_mode"] = mode_key
            data["module_settings"] = settings
            data.setdefault("main_settings", {})
            self.write_preset_data(current, mode_key, data)
            self.save_last_used_preset(mode_key, current)
        elif not randomized:
            self.save_mode_settings(mode_key, settings)
        # 랜덤 칸은 기본 칸이든 더한 칸이든 여기서 아무것도 쓰지 않는다.
        # *randomized rolls a fresh preset (and an unexpanded Randomized Wildcard token)
        # into state["settings"] every generation; that transient roll must NEVER be
        # written to the durable mode baseline, or it bleeds into unrelated presets on
        # reload. Skip persistence entirely while *randomized is the current preset.
        self._dirty_modes.discard(mode_key)
        return True, current

    def persist_all_dirty(self) -> tuple[bool, str]:
        """지금 모드를 쓰고, 손댄 채 떠나온 다른 모드도 그 모드의 현재 프리셋에 쓴다.

        모드마다 편집이 따로 살아 있다. 지금 모드만 쓰면 떠나온 모드의 편집은 그 모드로 돌아와 생성할
        때까지 메모리에만 있고, 그 전에 끄면 사라진다 - COMFYUI <-> ANIMA 는 엔진만 바꿔도 모드가 바뀐다(09-30).
        반환은 지금 모드의 결과(persist_active_settings 와 같다).
        """
        result = self.persist_active_settings()
        current = self.mode()
        for mode_key in sorted(self._dirty_modes - {current}):
            self.persist_active_settings(mode_key)
        return result


def get_prompt_engineering_store(app_context) -> PromptEngineeringHeadlessStore:
    store = getattr(app_context, "prompt_engineering_headless_store", None)
    if isinstance(store, PromptEngineeringHeadlessStore):
        return store
    mode_getter = getattr(app_context, "get_api_mode", None)
    runtime_paths = getattr(app_context, "runtime_paths", None)
    save_root = getattr(runtime_paths, "save_dir", None)
    # 모드 = 프리셋 색인(관리형 ANIMA 는 "ANIMA" - prompt_engineering_mode_of)
    store = PromptEngineeringHeadlessStore(
        (lambda: prompt_engineering_mode_of(app_context)) if callable(mode_getter) else None,
        save_root=save_root,
    )
    setattr(app_context, "prompt_engineering_headless_store", store)
    return store
