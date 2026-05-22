from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class HeadlessPipelineHook(Protocol):
    def get_pipeline_hook_info(self) -> dict[str, Any]:
        ...

    def execute_pipeline_hook(self, context: Any) -> Any:
        ...


@runtime_checkable
class HeadlessMiddleModule(Protocol):
    NAI_compatibility: bool
    WEBUI_compatibility: bool
    COMFYUI_compatibility: bool

    def get_title(self) -> str:
        ...

    def initialize_with_context(self, app_context: Any) -> None:
        ...

    def get_parameters(self) -> dict[str, Any]:
        ...


@runtime_checkable
class HeadlessTabModule(Protocol):
    tab_id: str

    def get_tab_title(self) -> str:
        ...

    def initialize_with_context(self, app_context: Any) -> None:
        ...

    def on_tab_activated(self) -> None:
        ...

    def cleanup(self) -> None:
        ...
