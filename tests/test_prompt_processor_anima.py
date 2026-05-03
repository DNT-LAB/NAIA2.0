from types import SimpleNamespace

from core.prompt_context import PromptContext
from core.prompt_processor import PromptProcessor


class _Radio:
    def __init__(self, checked=False):
        self._checked = checked

    def isChecked(self):
        return self._checked


def _processor_with_main_radio(checked=False):
    processor = PromptProcessor.__new__(PromptProcessor)
    processor.app_context = SimpleNamespace(
        current_api_mode="COMFYUI",
        main_window=SimpleNamespace(anima_radio=_Radio(checked)),
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
