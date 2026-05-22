"""Autocomplete runtime status payload for the headless Remote Web session."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class AutocompleteRuntimeState:
    kr_tags_loaded: bool = False
    metadata_fallback_ready: bool = False
    translation_cache_size: int = 0
    result_cache_size: int = 0

    def to_payload(self) -> dict[str, Any]:
        return {
            "kr_tags_loaded": bool(self.kr_tags_loaded),
            "metadata_fallback": {
                "ready": bool(self.metadata_fallback_ready),
                "live_path_allows_build": False,
            },
            "translation_cache_size": int(self.translation_cache_size),
            "result_cache_size": int(self.result_cache_size),
        }
