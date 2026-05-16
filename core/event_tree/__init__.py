"""Event Tree runtime primitives.

This package starts narrow: linear NAIA 1.5-style node assignment plus frozen
prompt-side state for future Event Stream work.
"""

from .runtime import (
    EventStreamPromptRequest,
    EventStreamRuntime,
    LegacyStoryNodeSpec,
)

__all__ = [
    "EventStreamPromptRequest",
    "EventStreamRuntime",
    "LegacyStoryNodeSpec",
]
