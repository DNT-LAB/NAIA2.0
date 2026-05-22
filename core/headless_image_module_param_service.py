"""NAI image-module parameter assembly for the headless generation path."""

from __future__ import annotations

from typing import Any


class HeadlessImageModuleParamService:
    def __init__(self, context: Any):
        self.context = context

    def active_character_reference_params(self) -> dict[str, Any]:
        return self.context._character_reference_service().active_params()

    def active_vibe_transfer_params(self) -> dict[str, Any]:
        return self.context._vibe_transfer_service().active_params()

    def apply(self, params: dict[str, Any], api_mode: str) -> None:
        if str(api_mode or "").upper() != "NAI":
            return
        if not params.get("director_reference_descriptions"):
            params.update(self.active_character_reference_params())
        if params.get("_skip_vibe_transfer_late_binding"):
            return
        if not params.get("reference_image_multiple"):
            params.update(self.active_vibe_transfer_params())
