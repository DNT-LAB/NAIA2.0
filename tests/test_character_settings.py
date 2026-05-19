import json
from types import SimpleNamespace

from core.character_settings import (
    character_params_from_settings,
    character_state_from_settings,
    load_character_settings,
    loaded_character_module_has_widget_state,
    loaded_character_module_is_active,
    loaded_character_module_reroll_on_generate,
)
from core.prompt_context import PromptContext
from modules.character_module import CharacterModule


class _WildcardManager:
    wildcard_dict_tree = {"pose": [(1, "standing"), (1, "sitting")]}
    instant_wildcard_tree = {}
    instant_wildcard_dict = {}


def test_load_character_settings_reads_mode_aware_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_dir = tmp_path / "save"
    save_dir.mkdir()
    (save_dir / "CharacterModule_NAI.json").write_text(
        json.dumps({
            "NAI": {
                "is_active": True,
                "reroll_on_generate": True,
                "character_frames": [
                    {
                        "prompt": "girl, blue eyes",
                        "uc": "bad anatomy",
                        "slot_state": "active",
                    },
                    {
                        "prompt": "unused",
                        "uc": "",
                        "slot_state": "cold",
                    },
                ],
            },
        }),
        encoding="utf-8",
    )

    settings = load_character_settings("NAI")

    assert settings["is_active"] is True
    assert settings["reroll_on_generate"] is True
    assert settings["character_frames"][0]["slot_state"] == "active"
    assert settings["character_frames"][1]["slot_state"] == "cold"


def test_character_params_from_settings_preserves_active_saved_character():
    ctx = SimpleNamespace(
        wildcard_manager=_WildcardManager(),
        current_prompt_context=None,
        current_source_row=None,
    )
    settings = {
        "is_active": True,
        "character_frames": [
            {"prompt": "girl, blue eyes", "uc": "bad anatomy", "slot_state": "active"},
            {"prompt": "unused", "uc": "", "slot_state": "cold"},
        ],
    }

    params = character_params_from_settings(ctx, settings=settings)

    assert params == {
        "characters": ["girl, blue eyes"],
        "uc": ["bad anatomy"],
    }


def test_character_state_from_settings_reports_badge_counts():
    settings = {
        "is_active": True,
        "reroll_on_generate": False,
        "character_frames": [
            {"prompt": "girl", "uc": "", "slot_state": "active"},
            {"prompt": "saved", "uc": "", "slot_state": "cold"},
            {"prompt": "", "uc": "", "slot_state": "inactive"},
        ],
    }

    state = character_state_from_settings(settings)

    assert state["module_id"] == "character"
    assert state["activated"] is True
    assert state["active_count"] == 1
    assert state["cold_count"] == 1
    assert state["character_count"] == 3


def test_character_state_preview_does_not_advance_existing_context():
    current_context = PromptContext(source_row={"general": "base"}, settings={})
    current_context.sequential_counters["pose"] = 1
    ctx = SimpleNamespace(
        wildcard_manager=_WildcardManager(),
        current_prompt_context=current_context,
        current_source_row=None,
    )
    settings = {
        "is_active": True,
        "character_frames": [
            {"prompt": "<*pose>", "uc": "", "slot_state": "active"},
        ],
    }

    state = character_state_from_settings(settings, app_context=ctx)

    assert state["processed_characters"] == ["standing"]
    assert current_context.sequential_counters["pose"] == 1


def test_loaded_character_module_helpers_treat_headless_module_as_inactive():
    module = SimpleNamespace(
        activate_checkbox=None,
        reroll_on_generate_checkbox=None,
    )

    assert loaded_character_module_has_widget_state(module) is False
    assert loaded_character_module_is_active(module) is False
    assert loaded_character_module_reroll_on_generate(module) is False


def test_character_random_prompt_event_ignores_headless_module():
    module = CharacterModule()
    module.app_context = SimpleNamespace(event_stream_runtime=None)
    called = []
    module.process_and_update_view = lambda: called.append(True)

    module.on_random_prompt_triggered()

    assert called == []
