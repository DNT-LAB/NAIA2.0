"""
Event Preset — NAIA 2.0 이벤트 프리셋 패키지

Danbooru 이벤트 택소노미 + 멀티 이벤트 콤보 브라우저.
"""

__all__ = ["EventPresetWindow"]


def __getattr__(name: str):
    if name == "EventPresetWindow":
        from .event_preset_window import EventPresetWindow

        return EventPresetWindow
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
