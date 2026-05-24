from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd

from core.search_result_model import SearchResultModel
from core.prompt_engineering_settings import get_prompt_engineering_store
from core.wildcard_processor import split_tags_smart


def _clean_tags(value: Any) -> list[str]:
    if value is None:
        return []
    try:
        if pd.isna(value):
            return []
    except (TypeError, ValueError):
        pass
    return [tag.strip() for tag in split_tags_smart(str(value)) if tag and tag.strip()]


@dataclass
class LegacyStoryNodeSpec:
    """NAIA 1.5 Storyteller-compatible linear node spec.

    The full Event Tree schema will grow around this, but the MVP only needs a
    current-search bucket and a deterministic carry/freeze boundary.
    """

    node_id: str
    name: str = ""
    source: str = "current_search"
    ratings: Optional[set[str]] = None
    include_tags: tuple[str, ...] = ()
    exclude_tags: tuple[str, ...] = ()
    axis_carry_policy: dict[str, str] = field(default_factory=dict)


@dataclass
class EventStreamPromptRequest:
    active: bool
    settings: dict[str, Any]
    active_ratings: Optional[set[str]] = None
    source_row_override: Optional[pd.Series] = None
    skip_random_prompt_events: bool = False
    status_message: str = ""
    error_message: str = ""


@dataclass
class _FreezeSnapshot:
    sequential_counters: dict[str, int] = field(default_factory=dict)
    wildcard_state: dict[str, dict[str, int]] = field(default_factory=dict)
    wildcard_history: dict[str, list[str]] = field(default_factory=dict)
    wildcard_override: dict[str, Any] = field(default_factory=dict)
    scoped_wildcard: str = ""
    character_params: Optional[dict[str, Any]] = None
    prompt_engineering_options: Optional[dict[str, Any]] = None


@dataclass
class _LinearState:
    run_id: str
    nodes: list[LegacyStoryNodeSpec]
    current_index: int = 0
    frame_index: int = 0
    active: bool = False

    def current_node(self) -> LegacyStoryNodeSpec:
        if not self.nodes:
            raise RuntimeError("Event Stream has no nodes.")
        return self.nodes[self.current_index % len(self.nodes)]

    def advance(self) -> None:
        if not self.nodes:
            return
        self.frame_index += 1
        self.current_index = (self.current_index + 1) % len(self.nodes)


class EventStreamRuntime:
    """Internal entrypoint for linear Event Stream prompt assignment.

    It is intentionally UI-agnostic. A future tab/dialog can call start_linear()
    with real node specs; until then this runtime gives the random prompt path a
    safe flag, allocator, and prompt-side freeze contract.
    """

    def __init__(self, app_context):
        self.app_context = app_context
        self._state: Optional[_LinearState] = None
        self._freeze_snapshot: Optional[_FreezeSnapshot] = None
        self._trace: list[dict[str, Any]] = []
        self._capturing_freeze = False

    @property
    def is_active(self) -> bool:
        return bool(self._state and self._state.active)

    @property
    def run_id(self) -> Optional[str]:
        return self._state.run_id if self._state else None

    def start_linear(
        self,
        nodes: Optional[list[LegacyStoryNodeSpec]] = None,
        *,
        run_id: Optional[str] = None,
    ) -> str:
        if not nodes:
            nodes = [
                LegacyStoryNodeSpec(
                    node_id="node.default",
                    name="Current Search",
                )
            ]
        self._state = _LinearState(
            run_id=run_id or f"event-stream-{uuid.uuid4().hex[:12]}",
            nodes=list(nodes),
            active=True,
        )
        self._freeze_snapshot = None
        self._trace.clear()
        self.app_context.publish("event_stream_started", {"run_id": self._state.run_id})
        return self._state.run_id

    def stop(self) -> None:
        if not self._state:
            return
        run_id = self._state.run_id
        self._state.active = False
        self._freeze_snapshot = None
        self.app_context.publish("event_stream_stopped", {"run_id": run_id})

    def configure_linear_nodes(self, nodes: list[LegacyStoryNodeSpec]) -> None:
        if not self._state:
            self.start_linear(nodes)
            return
        self._state.nodes = list(nodes)
        self._state.current_index = 0
        self._state.frame_index = 0
        self._freeze_snapshot = None

    def should_freeze_random_prompt_side_effects(self) -> bool:
        return self.is_active

    def should_freeze_character_prompts(self) -> bool:
        return self.is_active and not self._capturing_freeze

    def should_freeze_prompt_engineering(self) -> bool:
        return self.is_active and not self._capturing_freeze

    def has_freeze_snapshot(self) -> bool:
        return self._freeze_snapshot is not None

    def prepare_random_prompt_request(
        self,
        search_results: SearchResultModel,
        settings: dict[str, Any],
        *,
        active_ratings: Optional[set[str]] = None,
        source_row_override: Optional[pd.Series] = None,
    ) -> EventStreamPromptRequest:
        if not self.is_active or not self._state:
            return EventStreamPromptRequest(
                active=False,
                settings=settings,
                active_ratings=active_ratings,
                source_row_override=source_row_override,
            )

        self.ensure_freeze_snapshot()
        node = self._state.current_node()
        selected_row = source_row_override

        if selected_row is None and not settings.get("wildcard_standalone", False):
            selected_row = self._pop_node_row(search_results, node, active_ratings)
            if selected_row is None:
                return EventStreamPromptRequest(
                    active=True,
                    settings=dict(settings),
                    active_ratings=active_ratings,
                    source_row_override=None,
                    skip_random_prompt_events=True,
                    error_message=f"Event Stream node '{node.node_id}'에 할당할 프롬프트가 없습니다.",
                )

        event_settings = dict(settings)
        event_settings["event_stream"] = {
            "active": True,
            "run_id": self._state.run_id,
            "frame_index": self._state.frame_index,
            "node_id": node.node_id,
            "node_name": node.name or node.node_id,
            "freeze_wildcards": True,
            "freeze_character_prompts": True,
        }
        event_settings["event_stream_active"] = True

        self._trace.append({
            "phase": "assign",
            "run_id": self._state.run_id,
            "frame_index": self._state.frame_index,
            "node_id": node.node_id,
            "source_row_name": getattr(selected_row, "name", None) if selected_row is not None else None,
        })

        self._state.advance()
        return EventStreamPromptRequest(
            active=True,
            settings=event_settings,
            active_ratings=active_ratings,
            source_row_override=selected_row,
            skip_random_prompt_events=True,
            status_message=f"Event Stream: {node.name or node.node_id} 노드 할당",
        )

    def ensure_freeze_snapshot(self) -> _FreezeSnapshot:
        if self._freeze_snapshot is not None:
            return self._freeze_snapshot

        self._capturing_freeze = True
        try:
            current_context = getattr(self.app_context, "current_prompt_context", None)
            snapshot = _FreezeSnapshot()
            if current_context is not None:
                snapshot.sequential_counters = copy.deepcopy(
                    getattr(current_context, "sequential_counters", {}) or {}
                )
                snapshot.wildcard_state = copy.deepcopy(
                    getattr(current_context, "wildcard_state", {}) or {}
                )
                snapshot.wildcard_history = copy.deepcopy(
                    getattr(current_context, "wildcard_history", {}) or {}
                )
            snapshot.wildcard_override = copy.deepcopy(
                getattr(self.app_context, "wildcard_override", {}) or {}
            )
            snapshot.scoped_wildcard = str(getattr(self.app_context, "scoped_wildcard", "") or "")
            snapshot.character_params = self._capture_character_params()
            snapshot.prompt_engineering_options = self._capture_prompt_engineering_options()
            self._freeze_snapshot = snapshot
            return snapshot
        finally:
            self._capturing_freeze = False

    def apply_context_freeze(self, context) -> None:
        if not self.is_active:
            return
        snapshot = self.ensure_freeze_snapshot()
        context.sequential_counters = copy.deepcopy(snapshot.sequential_counters)
        context.wildcard_state = copy.deepcopy(snapshot.wildcard_state)
        context.wildcard_history = copy.deepcopy(snapshot.wildcard_history)
        context.metadata["event_stream"] = copy.deepcopy(
            context.settings.get("event_stream") or self._current_metadata()
        )

    def record_generated_context(self, context) -> None:
        if not self.is_active or not self._state:
            return
        meta = dict(getattr(context, "metadata", {}).get("event_stream") or self._current_metadata())
        self._trace.append({
            "phase": "prompt_generated",
            "run_id": self._state.run_id,
            "frame_index": meta.get("frame_index"),
            "node_id": meta.get("node_id"),
            "final_prompt": getattr(context, "final_prompt", None),
        })

    def get_frozen_character_params(self) -> Optional[dict[str, Any]]:
        if not self.should_freeze_character_prompts():
            return None
        snapshot = self.ensure_freeze_snapshot()
        return copy.deepcopy(snapshot.character_params) if snapshot.character_params is not None else None

    def get_frozen_prompt_engineering_options(self) -> Optional[dict[str, Any]]:
        if not self.should_freeze_prompt_engineering():
            return None
        snapshot = self.ensure_freeze_snapshot()
        return copy.deepcopy(snapshot.prompt_engineering_options) if snapshot.prompt_engineering_options is not None else None

    def get_trace(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self._trace)

    def get_state(self) -> dict[str, Any]:
        if not self._state:
            return {
                "active": False,
                "run_id": None,
                "frame_index": 0,
                "current_index": 0,
                "node_count": 0,
                "current_node": None,
                "nodes": [],
                "has_freeze_snapshot": False,
                "freeze_wildcards": True,
                "freeze_character_prompts": True,
                "freeze_prompt_engineering": True,
                "trace_count": 0,
                "last_trace": None,
            }
        node = self._state.current_node() if self._state.nodes else None
        nodes = [
            {
                "node_id": item.node_id,
                "name": item.name or item.node_id,
                "source": item.source,
                "ratings": sorted(item.ratings) if item.ratings else [],
                "include_tags": list(item.include_tags),
                "exclude_tags": list(item.exclude_tags),
            }
            for item in self._state.nodes
        ]
        return {
            "active": self.is_active,
            "run_id": self._state.run_id,
            "frame_index": self._state.frame_index,
            "current_index": self._state.current_index,
            "node_count": len(self._state.nodes),
            "current_node": {
                "node_id": node.node_id,
                "name": node.name or node.node_id,
                "source": node.source,
            } if node else None,
            "nodes": nodes,
            "has_freeze_snapshot": self._freeze_snapshot is not None,
            "freeze_wildcards": True,
            "freeze_character_prompts": True,
            "freeze_prompt_engineering": True,
            "trace_count": len(self._trace),
            "last_trace": copy.deepcopy(self._trace[-1]) if self._trace else None,
        }

    def _current_metadata(self) -> dict[str, Any]:
        if not self._state:
            return {"active": False}
        node = self._state.current_node() if self._state.nodes else None
        return {
            "active": True,
            "run_id": self._state.run_id,
            "frame_index": self._state.frame_index,
            "node_id": node.node_id if node else None,
            "node_name": (node.name or node.node_id) if node else None,
            "freeze_wildcards": True,
            "freeze_character_prompts": True,
        }

    def _capture_character_params(self) -> Optional[dict[str, Any]]:
        controller = getattr(self.app_context, "middle_section_controller", None)
        if not controller:
            return None
        char_module = controller.get_module_instance("CharacterModule")
        if not char_module:
            return None
        try:
            if getattr(char_module, "activate_checkbox", None) and char_module.activate_checkbox.isChecked():
                if hasattr(char_module, "process_and_update_view"):
                    char_module.process_and_update_view()
                params = char_module.get_parameters()
                return copy.deepcopy(params)
        except Exception as exc:
            print(f"[EventStream] 캐릭터 프롬프트 freeze 캡처 실패: {exc}")
        return None

    def _capture_prompt_engineering_options(self) -> Optional[dict[str, Any]]:
        controller = getattr(self.app_context, "middle_section_controller", None)
        module = None
        if controller:
            if hasattr(controller, "get_loaded_module_instance"):
                module = controller.get_loaded_module_instance("PromptEngineeringModule")
            elif hasattr(controller, "get_module_instance"):
                module = controller.get_module_instance("PromptEngineeringModule")
        if not module or not hasattr(module, "get_parameters"):
            settings = get_prompt_engineering_store(self.app_context).collect_settings()
            return {
                "pre_prompt": split_tags_smart(settings.get("pre_prompt", "")),
                "post_prompt": split_tags_smart(settings.get("post_prompt", "")),
                "auto_hide": split_tags_smart(settings.get("auto_hide_prompt", "")),
                "preprocessing_options": dict(settings.get("preprocessing_options") or {}),
            }
        try:
            return copy.deepcopy(module.get_parameters())
        except Exception as exc:
            print(f"[EventStream] PromptEngineering freeze 캡처 실패: {exc}")
            return None

    def _pop_node_row(
        self,
        search_results: SearchResultModel,
        node: LegacyStoryNodeSpec,
        active_ratings: Optional[set[str]],
    ) -> Optional[pd.Series]:
        if node.source != "current_search":
            return None
        if search_results is None or search_results.is_empty():
            return None

        rating_filter = node.ratings if node.ratings else active_ratings

        include_tags = {tag.strip() for tag in node.include_tags if str(tag).strip()}
        exclude_tags = {tag.strip() for tag in node.exclude_tags if str(tag).strip()}
        if include_tags or exclude_tags:
            return search_results.pop_random_row_matching(
                rating_filter,
                lambda row: self._matches_node_tags(row, include_tags, exclude_tags),
            )

        return search_results.pop_random_row_matching(
            rating_filter,
            lambda row: bool(_clean_tags(row.get("general", ""))) if "general" in row.index else True,
        )

    @staticmethod
    def _matches_node_tags(row, include_tags: set[str], exclude_tags: set[str]) -> bool:
        tag_set = set(_clean_tags(row.get("general", "")))
        if include_tags and not include_tags.issubset(tag_set):
            return False
        if exclude_tags and exclude_tags.intersection(tag_set):
            return False
        return bool(tag_set)
