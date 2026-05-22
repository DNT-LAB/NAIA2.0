from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LegacyWidgetModule(Protocol):
    app_context: Any

    def initialize_with_context(self, app_context: Any) -> None:
        ...

    def create_widget(self, parent: Any) -> Any:
        ...


@runtime_checkable
class LegacyMiddleWidgetModule(LegacyWidgetModule, Protocol):
    NAI_compatibility: bool
    WEBUI_compatibility: bool
    COMFYUI_compatibility: bool

    def get_title(self) -> str:
        ...


@runtime_checkable
class LegacyTabWidgetModule(LegacyWidgetModule, Protocol):
    tab_id: str

    def get_tab_title(self) -> str:
        ...
