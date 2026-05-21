"""Compatibility imports for the current headless Remote Web server.

The implementation still lives in ``core`` during the transition. New package
paths should import from here so the later move can be mechanical.
"""

from core.web_session_app import create_headless_app
from core.web_session_context import WebSessionContext

__all__ = ["WebSessionContext", "create_headless_app"]
