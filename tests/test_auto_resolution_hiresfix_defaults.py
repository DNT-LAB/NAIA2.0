import sys
import types
from types import SimpleNamespace

import pandas as pd

if "piexif" not in sys.modules:
    piexif_stub = types.ModuleType("piexif")
    piexif_stub.ExifIFD = SimpleNamespace(UserComment=0)
    piexif_stub.load = lambda _data: {}
    piexif_helper_stub = types.ModuleType("piexif.helper")
    piexif_helper_stub.UserComment = SimpleNamespace(load=lambda _value: "")
    piexif_stub.helper = piexif_helper_stub
    sys.modules["piexif"] = piexif_stub
    sys.modules["piexif.helper"] = piexif_helper_stub

from core.generation_controller import GenerationController
from core.prompt_context import PromptContext
from core.prompt_processor import PromptProcessor


def _controller_with_remote_swap(*, remote_auto_generate=False):
    controller = GenerationController.__new__(GenerationController)
    controller.context = SimpleNamespace(
        current_prompt_context=None,
        remote_bridge=SimpleNamespace(
            get_webui_hiresfix_assist_params=lambda: {
                "webui_hiresfix_assist": True,
                "webui_hiresfix_assist_target": 768,
            },
            get_webui_hires_preset_swap_params=lambda: {
                "hires_preset_swap": "prev5",
            },
            is_remote_auto_generate_enabled=lambda: remote_auto_generate,
        ),
    )
    return controller


def test_auto_fit_resolution_clamps_high_source_to_standard_1mp():
    processor = PromptProcessor.__new__(PromptProcessor)
    context = PromptContext(
        source_row=pd.Series({"image_width": 2496, "image_height": 3648}),
        settings={"auto_fit_resolution": True},
    )

    processor._step_2_fit_resolution(context)

    assert context.metadata["detected_resolution"] == (832, 1216)


def test_auto_fit_resolution_keeps_source_when_within_1mp():
    processor = PromptProcessor.__new__(PromptProcessor)
    context = PromptContext(
        source_row=pd.Series({"image_width": 768, "image_height": 768}),
        settings={"auto_fit_resolution": True},
    )

    processor._step_2_fit_resolution(context)

    assert context.metadata["detected_resolution"] == (768, 768)


def test_webui_hiresfix_assist_defaults_are_injected_from_remote_bridge():
    controller = _controller_with_remote_swap()
    params = {"api_mode": "WEBUI", "enable_hr": True}

    controller._apply_webui_hiresfix_assist_defaults(params)

    assert params["webui_hiresfix_assist"] is True
    assert params["webui_hiresfix_assist_target"] == 768
    assert "hires_preset_swap" not in params


def test_webui_hiresfix_assist_defaults_do_not_override_explicit_request():
    controller = _controller_with_remote_swap()
    params = {
        "api_mode": "WEBUI",
        "webui_hiresfix_assist": False,
        "webui_hiresfix_assist_target": 512,
    }

    controller._apply_webui_hiresfix_assist_defaults(params)

    assert params["webui_hiresfix_assist"] is False
    assert params["webui_hiresfix_assist_target"] == 512


def test_remote_web_hires_preset_swap_default_applies_to_remote_request():
    controller = _controller_with_remote_swap()
    params = {"api_mode": "WEBUI", "_remote_web_session_params": True}

    controller._apply_remote_web_hires_preset_swap_default(params)

    assert params["hires_preset_swap"] == "prev5"


def test_remote_web_hires_preset_swap_default_applies_to_remote_autogen():
    controller = _controller_with_remote_swap(remote_auto_generate=True)
    controller.context.current_prompt_context = SimpleNamespace(
        settings={"auto_generate": True}
    )
    params = {"api_mode": "WEBUI"}

    controller._apply_remote_web_hires_preset_swap_default(params)

    assert params["hires_preset_swap"] == "prev5"


def test_remote_web_hires_preset_swap_default_does_not_affect_desktop_request():
    controller = _controller_with_remote_swap(remote_auto_generate=False)
    controller.context.current_prompt_context = SimpleNamespace(
        settings={"auto_generate": True}
    )
    params = {"api_mode": "WEBUI"}

    controller._apply_remote_web_hires_preset_swap_default(params)

    assert "hires_preset_swap" not in params


def test_remote_web_hires_preset_swap_default_does_not_override_explicit_request():
    controller = _controller_with_remote_swap(remote_auto_generate=True)
    params = {
        "api_mode": "WEBUI",
        "_remote_web_session_params": True,
        "hires_preset_swap": "fast1",
    }

    controller._apply_remote_web_hires_preset_swap_default(params)

    assert params["hires_preset_swap"] == "fast1"
