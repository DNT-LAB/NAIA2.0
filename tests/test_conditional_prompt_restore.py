import sys
from types import ModuleType, SimpleNamespace

import pandas as pd

_piexif = ModuleType("piexif")
_piexif_helper = ModuleType("piexif.helper")
_piexif.helper = _piexif_helper
sys.modules.setdefault("piexif", _piexif)
sys.modules.setdefault("piexif.helper", _piexif_helper)

from core.generation_controller import GenerationController
from core.prompt_context import PromptContext
from modules.conditional_prompt_module import PromptListModifierModule


class _TextEdit:
    def __init__(self, text=""):
        self.text = text
        self.blocked = False

    def toPlainText(self):
        return self.text

    def setPlainText(self, text):
        self.text = text

    def blockSignals(self, blocked):
        self.blocked = bool(blocked)


class _Button:
    def setEnabled(self, _enabled):
        pass

    def setText(self, _text):
        pass


class _StatusBar:
    def showMessage(self, _message):
        pass


class _CharacterModule:
    def __init__(self, prompt):
        self.prompt = prompt

    def get_character_modifiable_clone(self):
        return {"characters": [self.prompt], "uc": [""]}


class _MiddleSection:
    def __init__(self, module):
        self.module = module

    def get_module_instance(self, name):
        if name == "CharacterModule":
            return self.module
        return None


def _conditional_module(negative="base negative"):
    row = pd.Series({"rating": "e", "general": "1girl"})
    neg_edit = _TextEdit(negative)
    module = PromptListModifierModule()
    module.app_context = SimpleNamespace(
        current_source_row=row,
        middle_section_controller=None,
        main_window=SimpleNamespace(negative_prompt_textedit=neg_edit),
    )
    return module, row, neg_edit


def test_conditional_negative_restores_on_generation_finished():
    module, row, neg_edit = _conditional_module()
    context = PromptContext(source_row=row, settings={}, main_tags=["1girl"])

    module._apply_rules(
        context,
        "(e):neg+=nsfw^rating:explicit",
        [],
        max_passes=1,
        stop_on_match=False,
    )

    assert neg_edit.toPlainText() == "base negative, nsfw, rating:explicit"

    module._on_generate_done({})

    assert neg_edit.toPlainText() == "base negative"
    assert module._negative_snapshot is None


def test_conditional_negative_fallback_restores_before_next_cycle():
    module, row, neg_edit = _conditional_module()
    rules = "(e):neg+=nsfw^rating:explicit"

    module._apply_rules(
        PromptContext(source_row=row, settings={}, main_tags=["1girl"]),
        rules,
        [],
        max_passes=1,
        stop_on_match=False,
    )
    module._apply_rules(
        PromptContext(source_row=row, settings={}, main_tags=["1girl"]),
        rules,
        [],
        max_passes=1,
        stop_on_match=False,
    )

    assert neg_edit.toPlainText() == "base negative, nsfw, rating:explicit"


def test_conditional_anima_metadata_tags_are_visible_to_conditions():
    module, row, _neg_edit = _conditional_module()
    context = PromptContext(source_row=row, settings={}, main_tags=["1girl", "blue sky"])
    context.metadata["anima_character"] = "hatsune miku, kagamine rin"
    context.metadata["anima_copyright"] = "vocaloid"

    module._apply_rules(
        context,
        (
            "(*1girl):postfix+=person_hit, "
            "(*hatsune miku):prefix+=character_hit, "
            "(*vocaloid):main+=copyright_hit"
        ),
        [],
        max_passes=1,
        stop_on_match=False,
    )

    assert "character_hit" in context.prefix_tags
    assert "copyright_hit" in context.main_tags
    assert "person_hit" in context.postfix_tags


def test_conditional_anima_artist_metadata_matches_artist_group_aliases():
    module, row, _neg_edit = _conditional_module()
    context = PromptContext(source_row=row, settings={}, main_tags=["1girl"])
    context.metadata["anima_artist"] = "mika pikazo"

    module._apply_rules(
        context,
        (
            "(*mika pikazo):prefix+=raw_artist_hit, "
            "(*@mika pikazo):main+=anima_artist_hit, "
            "(*artist:mika pikazo):postfix+=group_artist_hit, "
            "(*@artist:mika pikazo):postfix+=anima_group_artist_hit"
        ),
        [],
        max_passes=1,
        stop_on_match=False,
    )

    assert "raw_artist_hit" in context.prefix_tags
    assert "anima_artist_hit" in context.main_tags
    assert "group_artist_hit" in context.postfix_tags
    assert "anima_group_artist_hit" in context.postfix_tags


def test_conditional_plain_at_tag_does_not_create_artist_group_alias():
    module, row, _neg_edit = _conditional_module()
    context = PromptContext(source_row=row, settings={}, main_tags=["@mika pikazo"])

    module._apply_rules(
        context,
        "(*artist:mika pikazo):prefix+=unexpected_artist_group_hit",
        [],
        max_passes=1,
        stop_on_match=False,
    )

    assert "unexpected_artist_group_hit" not in context.prefix_tags


def test_conditional_anima_metadata_matches_character_and_copyright_group_aliases():
    module, row, _neg_edit = _conditional_module()
    context = PromptContext(source_row=row, settings={}, main_tags=["1girl"])
    context.metadata["anima_character"] = "shiroko sunaookami"
    context.metadata["anima_copyright"] = r"\(blue archive\)"

    module._apply_rules(
        context,
        (
            "(*character:shiroko sunaookami):prefix+=character_group_hit, "
            "(*copyright:blue archive):main+=copyright_group_hit, "
            "(*worktitle:blue archive):postfix+=worktitle_group_hit"
        ),
        [],
        max_passes=1,
        stop_on_match=False,
    )

    assert "character_group_hit" in context.prefix_tags
    assert "copyright_group_hit" in context.main_tags
    assert "worktitle_group_hit" in context.postfix_tags


def test_conditional_exact_condition_matches_weighted_tag_raw_name():
    module, row, _neg_edit = _conditional_module()
    context = PromptContext(
        source_row=row,
        settings={},
        main_tags=["0.85::1girl ::", "(blue sky:1.2)"],
    )

    module._apply_rules(
        context,
        "(*1girl):prefix+=person_hit, (*blue sky):postfix+=sky_hit",
        [],
        max_passes=1,
        stop_on_match=False,
    )

    assert "person_hit" in context.prefix_tags
    assert "sky_hit" in context.postfix_tags


def test_conditional_exact_condition_matches_escaped_parentheses_semantic_tag():
    module, row, _neg_edit = _conditional_module()
    context = PromptContext(
        source_row=row,
        settings={},
        main_tags=[r"\(blue archive\)"],
    )

    module._apply_rules(
        context,
        "(*blue archive):prefix+=copyright_hit",
        [],
        max_passes=1,
        stop_on_match=False,
    )

    assert "copyright_hit" in context.prefix_tags


def test_conditional_char_in_matches_escaped_parentheses_semantic_tag():
    module, row, _neg_edit = _conditional_module()
    module.app_context.middle_section_controller = _MiddleSection(
        _CharacterModule(r"\(blue archive\), 1girl")
    )
    context = PromptContext(source_row=row, settings={}, main_tags=["solo"])

    module._apply_rules(
        context,
        "(char_in(1, *blue archive)):prefix+=character_hit",
        [],
        max_passes=1,
        stop_on_match=False,
    )

    assert "character_hit" in context.prefix_tags


def test_generation_controller_publishes_generation_finished_event():
    events = []

    class _Queue:
        def is_empty(self):
            return True

        def is_paused(self):
            return False

    class _MainWindow:
        def update_ui_with_result(self, result):
            events.append(("ui", result))

    context = SimpleNamespace(
        main_window=_MainWindow(),
        generation_queue_manager=_Queue(),
        publish=lambda name, payload: events.append((name, payload)),
    )
    controller = GenerationController.__new__(GenerationController)
    controller.context = context
    controller.auto_retry_count = 1
    controller.current_generation_params = None
    controller._update_button_with_queue_size = lambda: None

    result = {"image": object(), "generation_params": {}}
    controller._on_generation_finished(result)

    assert ("generation_finished", result) in events
    assert events.index(("generation_finished", result)) < events.index(("ui", result))


def test_generation_controller_publishes_generation_failed_event():
    events = []

    class _Queue:
        def is_empty(self):
            return True

        def is_paused(self):
            return False

    context = SimpleNamespace(
        main_window=SimpleNamespace(
            generation_checkboxes={},
            generate_button_main=_Button(),
            status_bar=_StatusBar(),
        ),
        generation_queue_manager=_Queue(),
        publish=lambda name, payload: events.append((name, payload)),
    )
    controller = GenerationController.__new__(GenerationController)
    controller.context = context
    controller.current_generation_params = None
    controller.auto_retry_count = 0
    controller.max_auto_retries = 0

    controller._on_generation_error("boom")

    assert ("generation_failed", {"message": "boom"}) in events
    assert ("generation_error", {"message": "boom"}) in events
