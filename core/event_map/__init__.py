"""Event map -- pin observed feature tags and follow what actually co-occurs.

The index is built by `tools/build_event_map_index.py` from the observed scene
corpus. It answers one question: given everything currently pinned, which tags
appear together with all of them in the same post, and how unusual is that.
"""
from .index import EventMapIndex, load_index
from .policy import POLICY_VERSION, color_exclusion_reason, is_color_only

__all__ = ["EventMapIndex", "load_index", "POLICY_VERSION",
           "color_exclusion_reason", "is_color_only"]
