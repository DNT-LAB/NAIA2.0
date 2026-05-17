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
            get_resolution_preset_params=lambda mode=None: {
                "resolution_preset_enabled": True,
                "resolution_preset": "quality",
            },
            is_remote_auto_generate_enabled=lambda: remote_auto_generate,
        ),
    )
    return controller


class _ResolutionCombo:
    def __init__(self):
        self.set_current_index_calls = []

    def count(self):
        return 1

    def setCurrentIndex(self, index):
        self.set_current_index_calls.append(index)

    def currentText(self):
        return "1024 x 1024"

    def findText(self, _text):
        return -1


def _controller_with_resolution_combo():
    combo = _ResolutionCombo()
    controller = GenerationController.__new__(GenerationController)
    controller.context = SimpleNamespace(
        main_window=SimpleNamespace(
            resolution_is_detected=False,
            resolution_combo=combo,
        )
    )
    return controller, combo


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


def test_webui_resolution_preset_auto_fit_uses_selected_preset():
    processor = PromptProcessor.__new__(PromptProcessor)
    context = PromptContext(
        source_row=pd.Series({"image_width": 2496, "image_height": 3648}),
        settings={
            "auto_fit_resolution": True,
            "api_mode": "WEBUI",
            "resolution_preset_enabled": True,
            "resolution_preset": "max",
        },
    )

    processor._step_2_fit_resolution(context)

    assert context.metadata["detected_resolution"] == (1216, 1792)


def test_webui_resolution_preset_draft_auto_fit_uses_square_only():
    processor = PromptProcessor.__new__(PromptProcessor)
    context = PromptContext(
        source_row=pd.Series({"image_width": 640, "image_height": 960}),
        settings={
            "auto_fit_resolution": True,
            "api_mode": "WEBUI",
            "resolution_preset_enabled": True,
            "resolution_preset": "draft",
        },
    )

    processor._step_2_fit_resolution(context)

    assert context.metadata["detected_resolution"] == (512, 512)


def test_webui_resolution_preset_default_uses_square_without_touching_main_combo():
    controller, combo = _controller_with_resolution_combo()
    params = {
        "api_mode": "WEBUI",
        "resolution_preset_enabled": True,
        "resolution_preset": "quality",
        "random_resolution": False,
    }

    controller._apply_resolution_preset_default(params)

    assert params["resolution"] == "1344 x 1344"
    assert params["width"] == 1344
    assert params["height"] == 1344
    assert combo.set_current_index_calls == []


def test_webui_resolution_preset_default_keeps_selected_preset_candidate():
    controller, combo = _controller_with_resolution_combo()
    params = {
        "api_mode": "WEBUI",
        "resolution": "1088 x 1600",
        "resolution_preset_enabled": True,
        "resolution_preset": "quality",
        "random_resolution": False,
    }

    controller._apply_resolution_preset_default(params)

    assert params["resolution"] == "1088 x 1600"
    assert params["width"] == 1088
    assert params["height"] == 1600
    assert combo.set_current_index_calls == []


def test_webui_resolution_preset_random_res_uses_selected_preset(monkeypatch):
    controller, combo = _controller_with_resolution_combo()
    monkeypatch.setattr(
        "core.generation_controller.random.choice",
        lambda values: "1088 x 1600",
    )
    params = {
        "api_mode": "WEBUI",
        "resolution_preset_enabled": True,
        "resolution_preset": "quality",
        "random_resolution": True,
    }

    controller._apply_random_resolution(params)

    assert params["resolution"] == "1088 x 1600"
    assert params["width"] == 1088
    assert params["height"] == 1600
    assert combo.set_current_index_calls == []


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


def test_remote_web_resolution_preset_default_applies_to_remote_autogen():
    controller = _controller_with_remote_swap(remote_auto_generate=True)
    controller.context.current_prompt_context = SimpleNamespace(
        settings={"auto_generate": True}
    )
    params = {"api_mode": "WEBUI"}

    controller._apply_remote_web_resolution_preset_default(params)

    assert params["resolution_preset_enabled"] is True
    assert params["resolution_preset"] == "quality"


def test_remote_web_resolution_preset_default_does_not_affect_desktop_request():
    controller = _controller_with_remote_swap(remote_auto_generate=False)
    controller.context.current_prompt_context = SimpleNamespace(
        settings={"auto_generate": True}
    )
    params = {"api_mode": "WEBUI"}

    controller._apply_remote_web_resolution_preset_default(params)

    assert "resolution_preset_enabled" not in params
    assert "resolution_preset" not in params


def test_remote_web_resolution_preset_default_does_not_override_explicit_request():
    controller = _controller_with_remote_swap(remote_auto_generate=True)
    params = {
        "api_mode": "WEBUI",
        "_remote_web_session_params": True,
        "resolution_preset_enabled": False,
        "resolution_preset": "standard",
    }

    controller._apply_remote_web_resolution_preset_default(params)

    assert params["resolution_preset_enabled"] is False
    assert params["resolution_preset"] == "standard"
