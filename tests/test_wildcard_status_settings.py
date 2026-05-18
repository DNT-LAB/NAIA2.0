import json
from types import SimpleNamespace

from core.wildcard_status_settings import (
    apply_wildcard_status_settings,
    load_wildcard_status_settings,
    save_wildcard_status_settings,
)


def test_load_wildcard_status_settings_defaults_when_file_missing(tmp_path):
    settings = load_wildcard_status_settings(tmp_path / "missing.json")

    assert settings == {
        "prompt_squeeze_enabled": True,
        "scoped_wildcard": "",
    }


def test_load_wildcard_status_settings_reads_current_file(tmp_path):
    path = tmp_path / "wildcard_status_settings.json"
    path.write_text(
        json.dumps(
            {
                "prompt_squeeze_enabled": False,
                "scoped_wildcard": "hair",
            }
        ),
        encoding="utf-8",
    )

    assert load_wildcard_status_settings(path) == {
        "prompt_squeeze_enabled": False,
        "scoped_wildcard": "hair",
    }


def test_load_wildcard_status_settings_migrates_legacy_scope(tmp_path):
    path = tmp_path / "wildcard_status_settings.json"
    path.write_text(
        json.dumps(
            {
                "prompt_squeeze_enabled": "false",
                "scoped_wildcards": ["eyes", "hair"],
            }
        ),
        encoding="utf-8",
    )

    assert load_wildcard_status_settings(path) == {
        "prompt_squeeze_enabled": False,
        "scoped_wildcard": "eyes",
    }


def test_apply_wildcard_status_settings_sets_headless_context(tmp_path):
    path = tmp_path / "wildcard_status_settings.json"
    path.write_text(
        json.dumps(
            {
                "prompt_squeeze_enabled": True,
                "scoped_wildcard": "outfit",
            }
        ),
        encoding="utf-8",
    )
    context = SimpleNamespace(prompt_squeeze_enabled=False, scoped_wildcard="")

    settings = apply_wildcard_status_settings(context, path)

    assert settings["scoped_wildcard"] == "outfit"
    assert context.prompt_squeeze_enabled is True
    assert context.scoped_wildcard == "outfit"


def test_save_wildcard_status_settings_normalizes_payload(tmp_path):
    path = tmp_path / "save" / "wildcard_status_settings.json"

    saved = save_wildcard_status_settings(
        {
            "prompt_squeeze_enabled": "false",
            "scoped_wildcard": "hair",
        },
        path,
    )

    assert saved == {"prompt_squeeze_enabled": False, "scoped_wildcard": "hair"}
    assert json.loads(path.read_text(encoding="utf-8")) == saved
