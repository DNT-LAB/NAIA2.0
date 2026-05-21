"""Server entrypoints for the staged headless backend package."""

from .headless import WebSessionContext, create_headless_app

__all__ = ["WebSessionContext", "create_headless_app"]
