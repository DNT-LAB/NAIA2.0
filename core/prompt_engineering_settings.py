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
    options = {key: False for key in PREPROCESSING_OPTION_KEYS}
    options["closed_eyes_sync"] = True
    return options


# Ollama Boost — 자연어 보강 프롬프트 설정(영속). e621_settings 와 동일한 저장/로드/병합
# 패턴을 따른다. nl_weight 는 [0.75, 3.0] 으로 clamp, effort 는 concise/standard/rich 중
# 하나로 강제(기본 rich), include/style 플래그는 bool 로 강제.
OLLAMA_BOOST_EFFORTS = ("concise", "standard", "rich")
OLLAMA_BOOST_NL_WEIGHT_MIN = 0.75
OLLAMA_BOOST_NL_WEIGHT_MAX = 3.0
OLLAMA_BOOST_DEFAULTS: dict[str, Any] = {
    "nl_weight": 1.0,
    "effort": "rich",
    "include_prefix": False,
    "include_postfix": False,
    "include_e621": False,
    "allow_scent_style": True,
    "allow_material_style": True,
    "allow_light_style": True,
    # close-up 강화(옵트인) — ON이면 자연어 본문이 카메라 샷/앵글(close-up·low angle)을
    # 명명하도록 허용해 기존 사양에 가까운 프레이밍-중심 보강을 낸다(기본 OFF=다양성 우선).
    "emphasize_framing": False,
}


def normalize_ollama_boost_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    """Coerce raw Ollama Boost settings to the canonical schema/defaults.

    nl_weight → float clamped to [0.75, 3.0]; effort → one of concise/standard/rich
    (fallback rich); include_prefix/postfix/e621 and style options → bool. Unknown keys are dropped."""
    source = settings if isinstance(settings, dict) else {}
    try:
        nl_weight = float(source.get("nl_weight", OLLAMA_BOOST_DEFAULTS["nl_weight"]))
    except (TypeError, ValueError):
        nl_weight = OLLAMA_BOOST_DEFAULTS["nl_weight"]
    if nl_weight != nl_weight:  # NaN guard
        nl_weight = OLLAMA_BOOST_DEFAULTS["nl_weight"]
    nl_weight = max(OLLAMA_BOOST_NL_WEIGHT_MIN, min(OLLAMA_BOOST_NL_WEIGHT_MAX, nl_weight))
    effort = str(source.get("effort", OLLAMA_BOOST_DEFAULTS["effort"]) or "").strip().lower()
    if effort not in OLLAMA_BOOST_EFFORTS:
        effort = OLLAMA_BOOST_DEFAULTS["effort"]
    return {
        "nl_weight": round(nl_weight, 4),
        "effort": effort,
        "include_prefix": bool(source.get("include_prefix", False)),
        "include_postfix": bool(source.get("include_postfix", False)),
        "include_e621": bool(source.get("include_e621", False)),
        "allow_scent_style": bool(source.get("allow_scent_style", OLLAMA_BOOST_DEFAULTS["allow_scent_style"])),
        "allow_material_style": bool(
            source.get("allow_material_style", OLLAMA_BOOST_DEFAULTS["allow_material_style"])
        ),
        "allow_light_style": bool(source.get("allow_light_style", OLLAMA_BOOST_DEFAULTS["allow_light_style"])),
        "emphasize_framing": bool(source.get("emphasize_framing", OLLAMA_BOOST_DEFAULTS["emphasize_framing"])),
    }


def default_prompt_engineering_settings(save_root: str | Path | None = None) -> dict[str, Any]:
    return {
        "pre_prompt": "",
        "post_prompt": "",
        "auto_hide_prompt": "",
        "preprocessing_options": default_preprocessing_options(),
        "e621_settings": load_e621_settings(save_root=save_root),
        "danbooru_weight_settings": load_danbooru_weight_settings(save_root=save_root),
        "ollama_boost_settings": load_ollama_boost_settings(save_root=save_root),
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


def load_ollama_boost_settings(*, save_root: str | Path | None = None) -> dict[str, Any]:
    path = _existing_save_file("ollama_boost_user.json", save_root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return dict(OLLAMA_BOOST_DEFAULTS)
    return normalize_ollama_boost_settings(data if isinstance(data, dict) else {})


def save_ollama_boost_settings(settings: dict[str, Any], *, save_root: str | Path | None = None) -> None:
    path = _coerce_save_root(save_root) / "ollama_boost_user.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(normalize_ollama_boost_settings(settings), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# 카테고리별 랜덤 프롬프트 전처리 필터 커스터마이즈 — 전역(모드 무관) 디스크 SSOT.
# 각 전처리 카테고리(remove_* 체크박스)마다 exclude(자동 제거에서 보호할 태그)/
# include(해당 카테고리 ON일 때 함께 제거할 추가 태그)를 사용자가 지정한다.
# Auto Hide 라운드는 자체 문법(~/__..__)을 가지므로 여기서 제외한다.
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
    맨 {option_key: {...}} 형태를 모두 받아 화이트리스트 키만, exclude/include 가
    하나라도 있는 카테고리만 남긴다(파일 청결 유지)."""
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
        if exclude or include:
            result[key] = {"exclude": exclude, "include": include}
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


# 고급 연결 설정 — 셀프호스팅(cloudflared 등) 사용자가 NAIA 백엔드가 프록시할 Ollama
# 엔드포인트/모델을 직접 지정하기 위한 전역(모드 무관) 설정. 빈 endpoint/model은
# "기본값 사용"을 뜻한다(env NAIA_OLLAMA_URL → 코드 기본 localhost / 코드 기본 모델).
OLLAMA_CONNECTION_DEFAULTS: dict[str, str] = {"endpoint": "", "model": ""}


def normalize_ollama_connection_settings(settings: dict[str, Any] | None) -> dict[str, str]:
    """{endpoint, model} 위생화. endpoint는 http/https만 허용하고 trailing slash와
    실수로 붙인 OpenAI 호환 접미사(``/v1``)를 제거한다(네이티브 API는 ``/api/...``를
    직접 붙이므로 ``/v1``이 들어오면 깨진다). 스킴이 없으면 ``http://``를 보충하고,
    여전히 유효하지 않으면 빈 문자열(=기본값 사용)로 떨어뜨린다 — 호출부(라우트)가
    '입력은 있었지만 무효'를 구분해 거부할 수 있도록 빈 입력과 무효 입력 모두 ''가 된다."""
    data = settings if isinstance(settings, dict) else {}
    endpoint = str(data.get("endpoint") or "").strip()
    if endpoint:
        if "://" not in endpoint:
            endpoint = "http://" + endpoint
        endpoint = endpoint.rstrip("/")
        if endpoint.lower().endswith("/v1"):
            endpoint = endpoint[:-3].rstrip("/")
        from urllib.parse import urlparse

        parsed = urlparse(endpoint)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            endpoint = ""
    model = str(data.get("model") or "").strip()
    return {"endpoint": endpoint, "model": model}


def load_ollama_connection_settings(*, save_root: str | Path | None = None) -> dict[str, str]:
    path = _existing_save_file("ollama_connection_user.json", save_root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return dict(OLLAMA_CONNECTION_DEFAULTS)
    return normalize_ollama_connection_settings(data if isinstance(data, dict) else {})


def save_ollama_connection_settings(settings: dict[str, Any], *, save_root: str | Path | None = None) -> None:
    path = _coerce_save_root(save_root) / "ollama_connection_user.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(normalize_ollama_connection_settings(settings), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


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


def _randomized_pool_entry(data: dict[str, Any], mode_key: str) -> tuple[list, str, str, bool]:
    """Extract (pool, wildcard_front, wildcard_back, wildcard_enabled) for a mode.

    Accepts the legacy list format (``data[mode] = [...]``) and the dict format
    (``{"pool": [...], "wildcard_front": str, "wildcard_back": str, "wildcard_enabled": bool}``).
    The earlier single-slot ``"wildcard"`` key is migrated into ``wildcard_back``."""
    raw = data.get(mode_key) if isinstance(data, dict) else None
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


def load_randomized_pool(
    mode: str | None,
    preset_names: list[str] | None = None,
    *,
    save_root: str | Path | None = None,
) -> list[str]:
    mode_key = normalize_prompt_engineering_mode(mode)
    data = _read_randomized_pool_data(save_root)
    pool, _front, _back, _enabled = _randomized_pool_entry(data, mode_key)
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


def _randomized_entry_dict(pool, front, back, enabled) -> dict[str, Any]:
    return {
        "pool": list(pool or []),
        "wildcard_front": str(front or ""),
        "wildcard_back": str(back or ""),
        "wildcard_enabled": bool(enabled),
    }


def save_randomized_pool(mode: str | None, pool: list[str], *, save_root: str | Path | None = None) -> None:
    mode_key = normalize_prompt_engineering_mode(mode)
    data = _read_randomized_pool_data(save_root)
    _pool, front, back, enabled = _randomized_pool_entry(data, mode_key)
    data[mode_key] = _randomized_entry_dict(pool, front, back, enabled)
    _write_randomized_pool_data(data, save_root)


def load_randomized_wildcard(mode: str | None, *, save_root: str | Path | None = None) -> tuple[str, str, bool]:
    mode_key = normalize_prompt_engineering_mode(mode)
    data = _read_randomized_pool_data(save_root)
    _pool, front, back, enabled = _randomized_pool_entry(data, mode_key)
    return front, back, enabled


def save_randomized_wildcard(
    mode: str | None, front: str, back: str, enabled: bool, *, save_root: str | Path | None = None
) -> None:
    mode_key = normalize_prompt_engineering_mode(mode)
    data = _read_randomized_pool_data(save_root)
    pool, _front, _back, _enabled = _randomized_pool_entry(data, mode_key)
    data[mode_key] = _randomized_entry_dict(pool, front, back, enabled)
    _write_randomized_pool_data(data, save_root)


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
        if key == "ollama_boost_settings" and isinstance(value, dict):
            merged[key] = normalize_ollama_boost_settings(value)
        elif key in {"e621_settings", "danbooru_weight_settings"} and isinstance(value, dict):
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
        return {
            "settings": settings,
            "preset_list": preset_names,
            "current_preset": current_preset,
            "randomized_preset_list": randomized_pool,
            "randomized_wildcard_front": wc_front,
            "randomized_wildcard_back": wc_back,
            "randomized_wildcard_enabled": wc_enabled,
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

    def load_randomized_wildcard(self, mode: str | None = None) -> tuple[str, str, bool]:
        return load_randomized_wildcard(mode, save_root=self._save_root)

    def save_randomized_wildcard(self, mode: str | None, front: str, back: str, enabled: bool) -> None:
        save_randomized_wildcard(mode, front, back, enabled, save_root=self._save_root)

    def save_e621_settings(self, settings: dict[str, Any]) -> None:
        save_e621_settings(settings, save_root=self._save_root)

    def save_danbooru_weight_settings(self, settings: dict[str, Any]) -> None:
        save_danbooru_weight_settings(settings, save_root=self._save_root)

    def save_ollama_boost_settings(self, settings: dict[str, Any]) -> None:
        save_ollama_boost_settings(settings, save_root=self._save_root)

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
        return [*names, "*randomized"]

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
            self._dirty_modes.discard(self.mode(mode))
            return True
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

    def set_randomized_wildcard(
        self, front: str, back: str, enabled: bool, mode: str | None = None
    ) -> tuple[bool, str]:
        mode_key = self.mode(mode)
        state = self.state(mode_key)
        wc_front = str(front or "")
        wc_back = str(back or "")
        en = bool(enabled)
        state["randomized_wildcard_front"] = wc_front
        state["randomized_wildcard_back"] = wc_back
        state["randomized_wildcard_enabled"] = en
        self.save_randomized_wildcard(mode_key, wc_front, wc_back, en)
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
        if current and current not in {"(프리셋 없음)", "*randomized"}:
            data = self.read_preset_data(current, mode_key)
            data["api_mode"] = mode_key
            data["module_settings"] = settings
            data.setdefault("main_settings", {})
            self.write_preset_data(current, mode_key, data)
            self.save_last_used_preset(mode_key, current)
        elif current != "*randomized":
            self.save_mode_settings(mode_key, settings)
        # *randomized rolls a fresh preset (and an unexpanded Randomized Wildcard token)
        # into state["settings"] every generation; that transient roll must NEVER be
        # written to the durable mode baseline, or it bleeds into unrelated presets on
        # reload. Skip persistence entirely while *randomized is the current preset.
        self._dirty_modes.discard(mode_key)
        return True, current


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
