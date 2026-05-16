from types import SimpleNamespace

import pandas as pd

from core.event_tree import EventStreamRuntime, LegacyStoryNodeSpec
from core.prompt_context import PromptContext
from core.search_result_model import SearchResultModel


class _Check:
    def __init__(self, checked=True):
        self._checked = checked

    def isChecked(self):
        return self._checked


class _CharacterModule:
    def __init__(self):
        self.activate_checkbox = _Check(True)
        self.reroll_on_generate_checkbox = _Check(False)
        self.params = {"characters": ["c1 frozen"], "uc": ["uc frozen"]}
        self.process_calls = 0

    def process_and_update_view(self):
        self.process_calls += 1
        return None

    def get_parameters(self):
        return dict(self.params)


class _PromptEngineeringModule:
    def __init__(self):
        self.params = {
            "pre_prompt": ["best quality"],
            "post_prompt": ["solo focus"],
            "auto_hide": [],
            "preprocessing_options": {"remove_author": False},
        }

    def get_parameters(self):
        return dict(self.params)


class _Middle:
    def __init__(self, char=None, pe=None):
        self.char = char
        self.pe = pe

    def get_module_instance(self, name):
        if name == "CharacterModule":
            return self.char
        if name == "PromptEngineeringModule":
            return self.pe
        return None


class _Context:
    def __init__(self):
        self.current_prompt_context = None
        self.wildcard_override = {}
        self.scoped_wildcard = ""
        self.middle_section_controller = _Middle()
        self.published = []

    def publish(self, event_name, *args, **kwargs):
        self.published.append((event_name, args, kwargs))


def test_event_stream_allocates_current_search_node_by_axis_like_bucket():
    ctx = _Context()
    runtime = EventStreamRuntime(ctx)
    runtime.start_linear([
        LegacyStoryNodeSpec(
            node_id="node.sitting",
            ratings={"s"},
            include_tags=("sitting",),
            exclude_tags=("standing",),
        )
    ])
    model = SearchResultModel(pd.DataFrame([
        {"general": "1girl, standing", "rating": "s"},
        {"general": "1girl, sitting, smile", "rating": "s"},
    ]))

    req = runtime.prepare_random_prompt_request(model, {"auto_generate": False})

    assert req.active is True
    assert req.skip_random_prompt_events is True
    assert req.source_row_override is not None
    assert "sitting" in req.source_row_override["general"]
    assert model.get_count() == 1
    assert req.settings["event_stream"]["node_id"] == "node.sitting"


def test_event_stream_freezes_character_and_wildcard_context():
    char = _CharacterModule()
    pe = _PromptEngineeringModule()
    ctx = _Context()
    ctx.middle_section_controller = _Middle(char=char, pe=pe)
    ctx.current_prompt_context = PromptContext(
        source_row=pd.Series({"general": "1girl"}),
        settings={},
        sequential_counters={"outfit": 3},
        wildcard_state={"outfit": {"current": 4, "total": 10}},
        wildcard_history={"outfit": ["dress"]},
    )
    runtime = EventStreamRuntime(ctx)
    runtime.start_linear()

    runtime.ensure_freeze_snapshot()
    char.params = {"characters": ["changed"], "uc": ["changed uc"]}

    assert runtime.get_frozen_character_params() == {
        "characters": ["c1 frozen"],
        "uc": ["uc frozen"],
    }

    new_context = PromptContext(source_row=pd.Series({"general": "1girl"}), settings={})
    runtime.apply_context_freeze(new_context)

    assert new_context.sequential_counters == {"outfit": 3}
    assert new_context.wildcard_state == {"outfit": {"current": 4, "total": 10}}
    assert new_context.wildcard_history == {"outfit": ["dress"]}


def test_event_stream_freezes_prompt_engineering_options():
    pe = _PromptEngineeringModule()
    ctx = _Context()
    ctx.middle_section_controller = _Middle(pe=pe)
    runtime = EventStreamRuntime(ctx)
    runtime.start_linear()

    runtime.ensure_freeze_snapshot()
    pe.params = {
        "pre_prompt": ["changed"],
        "post_prompt": [],
        "auto_hide": [],
        "preprocessing_options": {},
    }

    assert runtime.get_frozen_prompt_engineering_options()["pre_prompt"] == ["best quality"]
