from __future__ import annotations

import json
from pathlib import Path
from typing import Any


AUTOMATION_SETTINGS_PATH = Path("save") / "AutomationModule.json"
AUTOMATION_TYPE_TO_ID = {"unlimited": 0, "timer": 1, "count": 2}
AUTOMATION_ID_TO_TYPE = {value: key for key, value in AUTOMATION_TYPE_TO_ID.items()}


def default_automation_settings() -> dict:
    return {
        "delay_seconds": 2.0,
        "random_delay": False,
        "timer_minutes": 60,
        "count_limit": 100,
        "shutdown_on_finish": False,
        "notify_on_finish": True,
        "automation_type": "unlimited",
    }


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _coerce_float(value: Any, default: float, minimum: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= minimum else default


def _coerce_int(value: Any, default: int, minimum: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= minimum else default


def normalize_automation_type(value: Any) -> str:
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in AUTOMATION_TYPE_TO_ID:
            return lowered
        try:
            return AUTOMATION_ID_TO_TYPE.get(int(lowered), "unlimited")
        except ValueError:
            return "unlimited"
    if isinstance(value, (int, float)):
        return AUTOMATION_ID_TO_TYPE.get(int(value), "unlimited")
    return "unlimited"


def normalize_automation_settings(raw: dict | None) -> dict:
    settings = default_automation_settings()
    data = raw if isinstance(raw, dict) else {}
    settings["delay_seconds"] = _coerce_float(data.get("delay_seconds"), settings["delay_seconds"])
    settings["random_delay"] = _coerce_bool(data.get("random_delay"), settings["random_delay"])
    settings["timer_minutes"] = _coerce_int(data.get("timer_minutes"), settings["timer_minutes"], minimum=1)
    settings["count_limit"] = _coerce_int(data.get("count_limit"), settings["count_limit"], minimum=1)
    settings["shutdown_on_finish"] = _coerce_bool(
        data.get("shutdown_on_finish"),
        settings["shutdown_on_finish"],
    )
    settings["notify_on_finish"] = _coerce_bool(
        data.get("notify_on_finish"),
        settings["notify_on_finish"],
    )
    settings["automation_type"] = normalize_automation_type(
        data.get("automation_type", settings["automation_type"])
    )
    return settings


def load_automation_settings(path: Path | str = AUTOMATION_SETTINGS_PATH) -> dict:
    target = Path(path)
    try:
        if target.exists():
            with target.open("r", encoding="utf-8") as handle:
                return normalize_automation_settings(json.load(handle))
    except Exception as exc:
        print(f"[ERROR] Automation settings load failed: {exc}")
    return default_automation_settings()


def save_automation_settings(settings: dict, path: Path | str = AUTOMATION_SETTINGS_PATH) -> bool:
    normalized = normalize_automation_settings(settings)
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            json.dump(normalized, handle, indent=4, ensure_ascii=False)
        return True
    except Exception as exc:
        print(f"[ERROR] Automation settings save failed: {exc}")
        return False


def automation_state_from_settings(settings: dict | None) -> dict:
    normalized = normalize_automation_settings(settings)
    auto_type = normalize_automation_type(normalized["automation_type"])
    return {
        "type": "module_state",
        "module_id": "automation",
        "delay": str(normalized["delay_seconds"]),
        "random_delay": bool(normalized["random_delay"]),
        "repeat": "1",
        "auto_type": AUTOMATION_TYPE_TO_ID.get(auto_type, 0),
        "timer_minutes": str(normalized["timer_minutes"]),
        "count_limit": str(normalized["count_limit"]),
        "notify": bool(normalized["notify_on_finish"]),
        "is_running": False,
        "status": "",
        "repeat_info": "",
        "delay_info": "",
    }


def settings_from_automation_state(state: dict | None) -> dict:
    data = state if isinstance(state, dict) else {}
    settings = default_automation_settings()
    settings["delay_seconds"] = _coerce_float(data.get("delay"), settings["delay_seconds"])
    settings["random_delay"] = _coerce_bool(data.get("random_delay"), settings["random_delay"])
    settings["timer_minutes"] = _coerce_int(data.get("timer_minutes"), settings["timer_minutes"], minimum=1)
    settings["count_limit"] = _coerce_int(data.get("count_limit"), settings["count_limit"], minimum=1)
    settings["notify_on_finish"] = _coerce_bool(data.get("notify"), settings["notify_on_finish"])
    settings["automation_type"] = normalize_automation_type(data.get("auto_type", 0))
    return settings
