import sys
import types
from types import SimpleNamespace

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


class _WildcardManager:
    wildcard_dict_tree = {}
    instant_wildcard_tree = {}
    instant_wildcard_dict = {}


class _PresetBridge:
    def __init__(self):
        self.tokens = []

    def resolve_prompt_token(self, token):
        self.tokens.append(token)
        return {
            "ok": True,
            "applied": True,
            "token": token,
            "tags": ["looking back", "sitting", "wariza"],
        }


def test_generation_wildcard_pass_expands_preset_tokens_before_api_prompt():
    controller = GenerationController.__new__(GenerationController)
    controller.context = SimpleNamespace(
        current_prompt_context=None,
        wildcard_manager=_WildcardManager(),
    )
    controller._preset_input_bridge = _PresetBridge()

    prompt, negative = controller._expand_wildcards_in_input(
        "best quality, preset:events/gaze/gaze_direction/looking_back/combo-16, -bad hands",
        "lowres",
    )

    assert prompt == "best quality, looking back, sitting, wariza"
    assert negative == "lowres, bad hands"
    assert controller._preset_input_bridge.tokens == [
        "preset:events/gaze/gaze_direction/looking_back/combo-16"
    ]
    metadata = controller.context.current_prompt_context.metadata
    assert metadata["preset_prompt_resolutions"][0]["applied"] is True


def test_generation_wildcard_pass_keeps_unresolved_preset_token():
    class UnresolvedBridge:
        def resolve_prompt_token(self, token):
            return {"ok": True, "applied": False, "token": token, "reason": "not_ready"}

    controller = GenerationController.__new__(GenerationController)
    controller.context = SimpleNamespace(
        current_prompt_context=None,
        wildcard_manager=_WildcardManager(),
    )
    controller._preset_input_bridge = UnresolvedBridge()

    prompt, negative = controller._expand_wildcards_in_input(
        "preset:events/gaze",
        "",
    )

    assert prompt == "preset:events/gaze"
    assert negative == ""
