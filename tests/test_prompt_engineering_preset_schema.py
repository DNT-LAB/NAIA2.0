from legacy_desktop.modules.prompt_engineering_module import PromptEngineeringModule


def test_preset_main_settings_strip_runtime_state_keys():
    settings = {
        "prompt": "example",
        "resolution": "832 x 1216",
        "seed_fixed": True,
        "random_resolution": True,
        "auto_fit_resolution": False,
    }

    normalized = PromptEngineeringModule._normalize_preset_main_settings(settings)

    assert normalized == {
        "prompt": "example",
        "resolution": "832 x 1216",
        "seed_fixed": True,
    }
    assert settings["random_resolution"] is True
    assert settings["auto_fit_resolution"] is False
