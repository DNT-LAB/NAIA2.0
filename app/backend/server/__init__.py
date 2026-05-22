"""Server entrypoints for the staged headless backend package."""

from __future__ import annotations

from typing import Any


def __getattr__(name: str) -> Any:
    if name in {"WebSessionContext", "create_headless_app"}:
        from .headless import WebSessionContext, create_headless_app

        return {
            "WebSessionContext": WebSessionContext,
            "create_headless_app": create_headless_app,
        }[name]
    raise AttributeError(name)

__all__ = ["WebSessionContext", "create_headless_app"]
