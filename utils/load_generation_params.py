"""Compatibility shim for the legacy desktop generation-parameter manager.

Headless Web runtime code must not import this module. The implementation lives
under legacy_desktop.utils.load_generation_params so packaged/headless code can
classify it as desktop-only. This shim remains for older imports until legacy
desktop callers are fully rewritten.
"""

from __future__ import annotations

from typing import Any


def __getattr__(name: str) -> Any:
    if name != "GenerationParamsManager":
        raise AttributeError(name)
    from legacy_desktop.utils.load_generation_params import GenerationParamsManager

    return GenerationParamsManager


__all__ = ["GenerationParamsManager"]
