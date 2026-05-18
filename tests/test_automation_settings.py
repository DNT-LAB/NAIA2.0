import json

from core.automation_settings import (
    automation_state_from_settings,
    load_automation_settings,
    save_automation_settings,
    settings_from_automation_state,
)


def test_automation_settings_defaults_when_file_missing(tmp_path):
    settings = load_automation_settings(tmp_path / "missing.json")

    assert settings["delay_seconds"] == 2.0
    assert settings["random_delay"] is False
    assert settings["timer_minutes"] == 60
    assert settings["count_limit"] == 100
    assert settings["automation_type"] == "unlimited"


def test_automation_settings_normalizes_file_values(tmp_path):
    path = tmp_path / "AutomationModule.json"
    path.write_text(
        json.dumps({
            "delay_seconds": "3.5",
            "random_delay": "true",
            "timer_minutes": "12",
            "count_limit": "7",
            "notify_on_finish": "false",
            "automation_type": "count",
        }),
        encoding="utf-8",
    )

    settings = load_automation_settings(path)

    assert settings["delay_seconds"] == 3.5
    assert settings["random_delay"] is True
    assert settings["timer_minutes"] == 12
    assert settings["count_limit"] == 7
    assert settings["notify_on_finish"] is False
    assert settings["automation_type"] == "count"


def test_automation_state_round_trips_to_saved_settings(tmp_path):
    state = {
        "delay": "4.25",
        "random_delay": True,
        "timer_minutes": "9",
        "count_limit": "11",
        "notify": False,
        "auto_type": 1,
    }
    path = tmp_path / "AutomationModule.json"

    assert save_automation_settings(settings_from_automation_state(state), path) is True
    restored = load_automation_settings(path)
    payload = automation_state_from_settings(restored)

    assert payload["delay"] == "4.25"
    assert payload["random_delay"] is True
    assert payload["timer_minutes"] == "9"
    assert payload["count_limit"] == "11"
    assert payload["notify"] is False
    assert payload["auto_type"] == 1
