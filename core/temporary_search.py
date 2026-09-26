"""One temporary search workspace, with the normal workspace retained by identity.

Only search-owned data is cloned. Providers, prompts, generated images, files and
saved filter presets remain shared. Callers drain in-flight operations before
switching; pool/revision tokens deliberately keep increasing across a switch.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import uuid4


WORKSPACE_FIELDS = (
    "search_results", "search_results_snapshot", "search_results_master_base_snapshot",
    "search_results_scope", "search_pool_provenance", "search_pool_base_provenance",
    "search_query_ratings", "remote_active_ratings", "search_filter_state",
    "active_tag_filter_ids", "active_tag_filter_snapshot", "active_tag_filter",
    "active_tag_filter_frame", "active_tag_filter_frame_for", "active_tag_filter_frame_snapshot",
    "depth_state",
)


class TemporarySearch:
    def __init__(self, context: Any):
        self.context = context
        self.original: dict[str, Any] | None = None
        self.owner = ""
        self.workspace_id = "normal"
        self.transition = False
        self.operations = 0
        self.history: list[dict[str, Any]] = []
        self.task = None
        self.normal_stop_on_exhaust = False
        self.upload_token = ""

    @property
    def active(self) -> bool:
        return self.original is not None

    def permits(self, owner: str, workspace_id: str | None) -> bool:
        if self.transition:
            return False
        if self.active and owner != self.owner:
            return False
        return workspace_id in (None, self.workspace_id) if not self.active else workspace_id == self.workspace_id

    def busy(self) -> bool:
        ctx = self.context
        return bool(self.operations or getattr(ctx, "is_generating", False)
                    or getattr(ctx, "_search_warmup_active", False)
                    or getattr(ctx, "headless_generation_runner_active", False)
                    or getattr(ctx, "manual_random_inflight", "")
                    or (getattr(ctx, "_search_pool_loading", None) or {}).get("active"))

    def begin(self, owner: str) -> None:
        if self.active:
            return
        from core.search_history import load_history

        ctx = self.context
        with ctx.search_pool_state_guard():
            # One deepcopy preserves aliases (e.g. frame_for is active_ids).
            original = {key: getattr(ctx, key, None) for key in WORKSPACE_FIELDS}
            cloned = deepcopy(original)
            history = deepcopy(load_history(ctx))
            original["_tag_filter_cache"] = getattr(ctx, "_tag_filter_cache", None)
            self.normal_stop_on_exhaust = bool(ctx.remote_options.get("stop_autogen_on_tag_exhaust", False))
            self.original = original
            self.owner = owner
            self.history = history
            self.workspace_id = uuid4().hex
            self.upload_token = uuid4().hex
            for key, value in cloned.items():
                setattr(ctx, key, value)
            self._invalidate()

    def end(self) -> None:
        if not self.active:
            return
        ctx = self.context
        with ctx.search_pool_state_guard():
            for key, value in self.original.items():
                setattr(ctx, key, value)
            ctx.remote_options["stop_autogen_on_tag_exhaust"] = self.normal_stop_on_exhaust
            self.original = None
            self.owner = ""
            self.workspace_id = "normal-" + uuid4().hex
            self.upload_token = ""
            self.history = []
            self._invalidate(keep_cache=True)

    def _invalidate(self, *, keep_cache: bool = False) -> None:
        ctx = self.context
        ctx.pending_tag_filter = None
        ctx.pending_tag_filters = {}
        if not keep_cache:
            ctx._tag_filter_cache = None
        ctx.mark_search_pool_replaced()
        ctx.mark_tag_filter_changed()

    def payload(self, owner: str = "") -> dict[str, Any]:
        return {"type": "temporary_search_state", "active": self.active,
                "pending": self.transition, "owned": bool(self.active and owner == self.owner),
                "workspace_id": self.workspace_id,
                "upload_token": self.upload_token if self.active and owner == self.owner else ""}


def temporary_search(context: Any) -> TemporarySearch:
    manager = getattr(context, "_temporary_search", None)
    if manager is None:
        manager = TemporarySearch(context)
        context._temporary_search = manager
    return manager


def is_temporary_search(context: Any) -> bool:
    manager = getattr(context, "_temporary_search", None)
    return bool(manager and manager.active)


def search_transition_pending(context: Any) -> bool:
    manager = getattr(context, "_temporary_search", None)
    return bool(manager and manager.transition)
