from types import SimpleNamespace

from core.prompt_context import PromptContext
from core.prompt_processor import PromptProcessor


class _Radio:
    def __init__(self, checked=False):
        self._checked = checked

    def isChecked(self):
        return self._checked


class _LineEdit:
    def __init__(self, text=""):
        self._text = text

    def text(self):
        return self._text


def _processor_with_main_radio(checked=False, current_api_mode="COMFYUI", prompt_weight=None):
    processor = PromptProcessor.__new__(PromptProcessor)
    main_window = SimpleNamespace(anima_radio=_Radio(checked))
    if prompt_weight is not None:
        main_window.anima_weight_edit = _LineEdit(prompt_weight)
    processor.app_context = SimpleNamespace(
        current_api_mode=current_api_mode,
        main_window=main_window,
    )
    return processor


def test_anima_prompt_formatting_uses_context_sampling_mode_before_main_radio():
    processor = _processor_with_main_radio(checked=False)
    context = PromptContext(
        source_row={},
        settings={
            "comfyui_sampling_mode": "anima",
            "anima_weight": "0.5",
        },
        prefix_tags=["quality", "@artist_anchor"],
        main_tags=["1girl", "blue sky", "solo"],
    )

    processor._step_final_format(context)

    assert context.prefix_tags[:3] == ["quality", "1girl", "@artist_anchor"]
    assert context.main_tags[1:3] == ["(blue sky", "solo:0.5)"]


def test_anima_prompt_formatting_uses_workflow_type_for_param_only_contexts():
    processor = _processor_with_main_radio(checked=False)
    context = PromptContext(
        source_row={},
        settings={
            "workflow_type": "unet",
            "anima_weight": "1",
        },
        prefix_tags=[],
        main_tags=["1girl", "blue sky"],
    )

    processor._step_final_format(context)

    assert context.prefix_tags[0] == "1girl"
    assert context.main_tags[1] == "blue sky"


def test_anima_prompt_formatting_defaults_to_weight_one_without_wrapping():
    processor = _processor_with_main_radio(checked=False)
    context = PromptContext(
        source_row={},
        settings={
            "comfyui_sampling_mode": "anima",
        },
        prefix_tags=[],
        main_tags=["1girl", "blue sky"],
    )

    processor._step_final_format(context)

    assert context.prefix_tags[0] == "1girl"
    assert context.main_tags[1] == "blue sky"


def test_anima_prompt_formatting_invalid_weight_falls_back_to_one():
    processor = _processor_with_main_radio(checked=False)
    context = PromptContext(
        source_row={},
        settings={
            "comfyui_sampling_mode": "anima",
            "anima_weight": "not-a-number",
        },
        prefix_tags=[],
        main_tags=["1girl", "blue sky"],
    )

    processor._step_final_format(context)

    assert context.prefix_tags[0] == "1girl"
    assert context.main_tags[1] == "blue sky"


def test_webui_prompt_formatting_applies_random_prompt_weight_without_anima_mode():
    processor = _processor_with_main_radio(checked=False, current_api_mode="WEBUI")
    context = PromptContext(
        source_row={},
        settings={
            "api_mode": "WEBUI",
            "anima_weight": "0.85",
        },
        prefix_tags=["quality"],
        main_tags=["1girl", "blue sky", "solo"],
    )

    processor._step_final_format(context)

    assert context.prefix_tags[:2] == ["1girl", "quality"]
    assert context.main_tags[1:3] == ["(blue sky", "solo:0.85)"]


def test_comfyui_prompt_weight_applies_without_anima_sampling_mode():
    processor = _processor_with_main_radio(checked=False, current_api_mode="COMFYUI")
    context = PromptContext(
        source_row={},
        settings={
            "api_mode": "COMFYUI",
            "comfyui_sampling_mode": "eps",
            "anima_weight": "0.85",
        },
        prefix_tags=["quality"],
        main_tags=["1girl", "blue sky", "solo"],
    )

    processor._step_final_format(context)

    assert context.prefix_tags[:2] == ["1girl", "quality"]
    assert context.main_tags[1:3] == ["(blue sky", "solo:0.85)"]


def test_comfyui_explicit_non_anima_mode_ignores_checked_main_radio():
    processor = _processor_with_main_radio(checked=True, current_api_mode="COMFYUI")
    context = PromptContext(
        source_row={},
        settings={
            "api_mode": "COMFYUI",
            "comfyui_sampling_mode": "eps",
            "anima_weight": "0.85",
        },
        prefix_tags=["quality"],
        main_tags=["1girl", "blue sky", "solo"],
    )

    processor._step_final_format(context)

    assert context.prefix_tags[:2] == ["1girl", "quality"]
    assert context.main_tags[1:3] == ["(blue sky", "solo:0.85)"]


def test_comfyui_bypass_mode_ignores_checked_main_radio():
    processor = _processor_with_main_radio(checked=True, current_api_mode="COMFYUI")
    context = PromptContext(
        source_row={},
        settings={
            "api_mode": "COMFYUI",
            "workflow_type": "bypass",
            "anima_weight": "0.85",
        },
        prefix_tags=["quality"],
        main_tags=["1girl", "blue sky", "solo"],
    )

    processor._step_final_format(context)

    assert context.prefix_tags[:2] == ["1girl", "quality"]
    assert context.main_tags[1:3] == ["(blue sky", "solo:0.85)"]


def test_webui_prompt_formatting_uses_window_weight_when_auto_generate_settings_omit_it():
    processor = _processor_with_main_radio(
        checked=False,
        current_api_mode="WEBUI",
        prompt_weight="0.85",
    )
    context = PromptContext(
        source_row={},
        settings={
            "api_mode": "WEBUI",
            "auto_generate": True,
        },
        prefix_tags=["quality"],
        main_tags=["1girl", "blue sky", "solo"],
    )

    processor._step_final_format(context)

    assert context.prefix_tags[:2] == ["1girl", "quality"]
    assert context.main_tags[1:3] == ["(blue sky", "solo:0.85)"]


def test_webui_prompt_formatting_keeps_existing_weighted_tags_outside_group():
    processor = _processor_with_main_radio(checked=False, current_api_mode="WEBUI")
    context = PromptContext(
        source_row={},
        settings={
            "api_mode": "WEBUI",
            "anima_weight": "0.85",
        },
        prefix_tags=[],
        main_tags=["1girl", "(red hair:1.2)", "blue sky", "solo"],
    )

    processor._step_final_format(context)

    assert context.main_tags[1] == "(red hair:1.2)"
    assert context.main_tags[2:4] == ["(blue sky", "solo:0.85)"]
