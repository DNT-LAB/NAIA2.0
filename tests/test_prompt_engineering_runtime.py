from types import SimpleNamespace

import pandas as pd

from core.prompt_context import PromptContext
from core.prompt_engineering_settings import get_prompt_engineering_store
from core.prompt_engineering_runtime import (
    PromptEngineeringAdvancedAfterWildcardHook,
    PromptEngineeringClosedEyesHeadlessHook,
    PromptEngineeringHeadlessPostHook,
)


class _AppContext:
    def __init__(self):
        self.filter_data_manager = None
        self.middle_section_controller = None
        self.session_p_eng_override = None
        self.skip_prompt_engineering_hook = False
        self.skip_prompt_engineering_auto_hide = False
        self.event_stream_runtime = None
        self._mode = "NAI"

    def get_api_mode(self):
        return self._mode


def _context():
    return PromptContext(
        source_row=pd.Series({
            "artist": "artist:demo",
            "copyright": "work demo",
            "character": "char demo",
            "id": 7,
        }),
        settings={"api_mode": "NAI"},
        main_tags=["1girl", "blue eyes", "signature"],
    )


def test_prompt_engineering_headless_post_hook_applies_store_settings(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app_context = _AppContext()
    store = get_prompt_engineering_store(app_context)
    store.apply_settings({
        "pre_prompt": "best quality",
        "post_prompt": "highres",
        "auto_hide_prompt": "signature",
        "preprocessing_options": {"remove_author": True},
    })
    hook = PromptEngineeringHeadlessPostHook(app_context)
    context = _context()

    result = hook.execute_pipeline_hook(context)

    assert result is context
    assert "artist:demo" not in context.prefix_tags
    assert context.prefix_tags[:2] == ["char demo", "work demo"]
    assert "best quality" in context.prefix_tags
    assert context.postfix_tags == ["highres"]
    assert "signature" not in context.main_tags
    assert "signature" in context.removed_tags


def test_prompt_engineering_headless_post_hook_empty_session_override_blocks_store_fallback(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app_context = _AppContext()
    store = get_prompt_engineering_store(app_context)
    store.apply_settings({"pre_prompt": "store prefix", "post_prompt": "store postfix"})
    app_context.session_p_eng_override = {}
    hook = PromptEngineeringHeadlessPostHook(app_context)
    context = _context()

    hook.execute_pipeline_hook(context)

    assert "store prefix" not in context.prefix_tags
    assert "store postfix" not in context.postfix_tags


def test_prompt_engineering_headless_post_hook_prefers_frozen_event_stream_options(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app_context = _AppContext()
    get_prompt_engineering_store(app_context).apply_settings({"pre_prompt": "store prefix"})
    app_context.event_stream_runtime = SimpleNamespace(
        should_freeze_prompt_engineering=lambda: True,
        get_frozen_prompt_engineering_options=lambda: {
            "pre_prompt": ["frozen prefix"],
            "post_prompt": ["frozen postfix"],
            "auto_hide": [],
            "preprocessing_options": {"remove_author": True, "remove_work_title": True, "remove_character_name": True},
        },
    )
    hook = PromptEngineeringHeadlessPostHook(app_context)
    context = _context()

    hook.execute_pipeline_hook(context)

    assert "frozen prefix" in context.prefix_tags
    assert "frozen postfix" in context.postfix_tags
    assert "store prefix" not in context.prefix_tags
    assert "artist:demo" not in context.prefix_tags


def test_prompt_engineering_headless_post_hook_prefers_loaded_module_before_store(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app_context = _AppContext()
    get_prompt_engineering_store(app_context).apply_settings({"pre_prompt": "store prefix"})
    module = SimpleNamespace(
        get_parameters=lambda: {
            "pre_prompt": ["module prefix"],
            "post_prompt": ["module postfix"],
            "auto_hide": [],
            "preprocessing_options": {"remove_author": True, "remove_work_title": True, "remove_character_name": True},
        },
    )
    app_context.middle_section_controller = SimpleNamespace(
        get_loaded_module_instance=lambda class_name: module if class_name == "PromptEngineeringModule" else None,
    )
    hook = PromptEngineeringHeadlessPostHook(app_context)
    context = _context()

    hook.execute_pipeline_hook(context)

    assert "module prefix" in context.prefix_tags
    assert "module postfix" in context.postfix_tags
    assert "store prefix" not in context.prefix_tags


def test_prompt_engineering_advanced_after_wildcard_does_not_wake_module_without_metadata():
    loaded = []
    app_context = _AppContext()
    app_context.middle_section_controller = SimpleNamespace(
        get_module_instance=lambda class_name: loaded.append(class_name),
    )
    hook = PromptEngineeringAdvancedAfterWildcardHook(
        app_context,
        "_execute_e621_after_wildcard",
        "e621 Auto-Boost Headless",
        lambda context: "_e621_source_tags" in context.metadata,
    )
    context = _context()

    result = hook.execute_pipeline_hook(context)

    assert result is context
    assert loaded == []


def test_prompt_engineering_closed_eyes_sync_updates_loaded_character_module_only():
    synced = []
    char_module = SimpleNamespace(
        activate_checkbox=SimpleNamespace(isChecked=lambda: True),
        modifiable_clone={"characters": ["girl, blue eyes, closed mouth"]},
        sync_external_prompt_edits=lambda: synced.append(True),
    )
    app_context = _AppContext()
    app_context.middle_section_controller = SimpleNamespace(
        get_loaded_module_instance=lambda class_name: char_module if class_name == "CharacterModule" else None,
    )
    hook = PromptEngineeringClosedEyesHeadlessHook(app_context)
    context = PromptContext(
        source_row=pd.Series({}),
        settings={"api_mode": "NAI"},
        main_tags=["closed eyes"],
        metadata={"_closed_eyes_sync_enabled": True},
    )

    hook.execute_pipeline_hook(context)

    assert char_module.modifiable_clone["characters"] == ["girl, closed mouth"]
    assert synced == [True]
    assert context.metadata["closed_eyes_sync"]["character_removed"] == [
        {"index": 0, "removed": ["blue eyes"]}
    ]
