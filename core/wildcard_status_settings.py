import json
from pathlib import Path


DEFAULT_WILDCARD_STATUS_SETTINGS_PATH = Path("save") / "wildcard_status_settings.json"
DEFAULT_WILDCARD_STATUS_SETTINGS = {
    "prompt_squeeze_enabled": True,
    "scoped_wildcard": "",
}


def _coerce_bool(value, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    if value is None:
        return default
    return bool(value)


def load_wildcard_status_settings(path=DEFAULT_WILDCARD_STATUS_SETTINGS_PATH) -> dict:
    settings = dict(DEFAULT_WILDCARD_STATUS_SETTINGS)
    target = Path(path)
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return settings

    if not isinstance(raw, dict):
        return settings

    settings["prompt_squeeze_enabled"] = _coerce_bool(
        raw.get("prompt_squeeze_enabled"),
        DEFAULT_WILDCARD_STATUS_SETTINGS["prompt_squeeze_enabled"],
    )

    scoped = raw.get("scoped_wildcard", "")
    if not scoped and isinstance(raw.get("scoped_wildcards"), list):
        legacy_scopes = raw.get("scoped_wildcards") or []
        scoped = legacy_scopes[0] if legacy_scopes else ""
    settings["scoped_wildcard"] = scoped if isinstance(scoped, str) else ""
    return settings


def apply_wildcard_status_settings(context, path=DEFAULT_WILDCARD_STATUS_SETTINGS_PATH) -> dict:
    settings = load_wildcard_status_settings(path)
    context.prompt_squeeze_enabled = settings["prompt_squeeze_enabled"]
    context.scoped_wildcard = settings["scoped_wildcard"]
    return settings


def save_wildcard_status_settings(settings: dict, path=DEFAULT_WILDCARD_STATUS_SETTINGS_PATH) -> dict:
    payload = dict(DEFAULT_WILDCARD_STATUS_SETTINGS)
    payload["prompt_squeeze_enabled"] = _coerce_bool(
        settings.get("prompt_squeeze_enabled"),
        DEFAULT_WILDCARD_STATUS_SETTINGS["prompt_squeeze_enabled"],
    )
    scoped = settings.get("scoped_wildcard", "")
    payload["scoped_wildcard"] = scoped if isinstance(scoped, str) else ""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
