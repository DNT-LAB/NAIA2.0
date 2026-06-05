from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd

from core.search_result_model import SearchResultModel
from core.prompt_engineering_settings import get_prompt_engineering_store
from core.wildcard_processor import split_tags_smart


def _normalize_carry_tag(tag: str) -> str:
    """최종 프롬프트의 가중치 래퍼를 벗겨 사전 exact-match가 되도록 정규화.
    예: ``(school uniform:1.2)``→``school uniform``, ``{skirt}``→``skirt``,
    ``1.2::beach::``→``beach``. 일반 태그(``artist:foo`` 등)는 그대로 둔다."""
    text = str(tag or "").strip()
    while text and text[0] in "([{":
        text = text[1:].lstrip()
    while text and text[-1] in ")]}":
        text = text[:-1].rstrip()
    if text.endswith("::"):
        text = text[:-2].rstrip()
    if "::" in text:
        head, _, rest = text.partition("::")
        try:
            float(head)
            text = rest.strip()
        except ValueError:
            pass
    if ":" in text:
        head, _, tail = text.rpartition(":")
        try:
            float(tail)
            text = head.rstrip()
        except ValueError:
            pass
    return text.strip()


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
        # Storyteller per-page carry (1.5 의상/배경 유지): extra pre_prompt literals +
        # per-page preprocessing flags merged into the frozen PE options for the NEXT
        # prompt build only. prepare_random_prompt_request가 이전 노드의 carry policy로
        # 자체 계산한다(수동 진행/자동 사이클 공통). cleared on stop.
        self._carry_overlay: Optional[dict[str, Any]] = None
        # 직전 스트림 생성의 최종 프롬프트에서 추출한 의상/배경 태그(다음 페이지 주입 재료).
        self._carry_clothes: list[str] = []
        self._carry_background: list[str] = []

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
        self._carry_overlay = None
        self._carry_clothes = []
        self._carry_background = []
        self._trace.clear()
        self.app_context.publish("event_stream_started", {"run_id": self._state.run_id})
        return self._state.run_id

    def stop(self) -> None:
        if not self._state:
            return
        run_id = self._state.run_id
        self._state.active = False
        self._freeze_snapshot = None
        self._carry_overlay = None
        self._carry_clothes = []
        self._carry_background = []
        self.app_context.publish("event_stream_stopped", {"run_id": run_id})

    def set_carry_overlay(self, overlay: Optional[dict[str, Any]]) -> None:
        """Storyteller 페이지별 carry(의상/배경 유지): 다음 프롬프트 빌드에 한해 frozen
        PE options에 병합할 ``{"pre_prompt_extra": [...], "preprocessing_flags": {...}}``."""
        self._carry_overlay = dict(overlay) if overlay else None

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

        # 라운드 경계(시퀀스가 한 바퀴 돌아 스텝 1로 돌아온 시점)마다 freeze를 재캡처한다.
        # 한 라운드 안에서는 캐릭터/PE/롤이 일관되고, 다음 라운드에는 사용자의 현재
        # 설정과 새 롤이 반영된다 — 수동 진행(라운드 반복)과 자동 사이클(1라운드) 공통.
        if self._state.nodes and self._state.frame_index % len(self._state.nodes) == 0:
            self._freeze_snapshot = None
        self.ensure_freeze_snapshot()
        # carry(의상/배경 유지)는 이전 노드의 policy + 직전 생성에서 추출한 태그로 매
        # 페이지 자체 계산한다 — 수동 진행/자동 사이클 공통(과거엔 자동 전용 배선이라
        # 수동 모드에서 전혀 동작하지 않던 버그).
        self._apply_carry_for_current_node()
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
        saved_override = getattr(self.app_context, "wildcard_override", None)
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
            snapshot.wildcard_override = copy.deepcopy(saved_override or {})
            snapshot.scoped_wildcard = str(getattr(self.app_context, "scoped_wildcard", "") or "")
            # Capturing character + PE expands wildcards, and WildcardProcessor pops
            # list-type overrides from the LIVE app_context.wildcard_override. Expand
            # against a COPY so freeze capture never consumes the user's live override
            # queue; the original is restored in the finally below.
            if isinstance(saved_override, dict):
                self.app_context.wildcard_override = copy.deepcopy(saved_override)
            snapshot.character_params = self._capture_character_params()
            snapshot.prompt_engineering_options = self._capture_prompt_engineering_options()
            self._freeze_snapshot = snapshot
            return snapshot
        finally:
            if isinstance(saved_override, dict):
                self.app_context.wildcard_override = saved_override
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
        # 모든 스트림 생성의 최종 프롬프트에서 의상/배경 태그를 추출해 다음 페이지의
        # carry 재료로 보관한다(수동/자동 공통 단일 추출 지점). 빈/전부 필터링된
        # 프롬프트는 carry를 비운다 — 더 오래된 페이지의 stale 의상/배경이 다음 페이지에
        # 주입되는 것 방지(Codex 리뷰 F2).
        final_prompt = getattr(context, "final_prompt", None)
        clothes, background = self._extract_carry_tags(final_prompt or "")
        self._carry_clothes = clothes
        self._carry_background = background

    def _apply_carry_for_current_node(self) -> None:
        """이전 노드의 axis_carry_policy(keep_clothes/keep_background)에 따라 이번
        페이지의 carry 오버레이를 설정한다. 라운드 시작(frame % N == 0)은 1.5의 step 0
        규칙대로 carry 없음."""
        state = self._state
        if not state or not state.nodes:
            self._carry_overlay = None
            return
        node_count = len(state.nodes)
        if state.frame_index % node_count == 0:
            self._carry_overlay = None
            return
        previous = state.nodes[(state.current_index - 1) % node_count]
        policy = previous.axis_carry_policy or {}
        inject: list[str] = []
        flags: dict[str, bool] = {}
        if policy.get("keep_clothes"):
            inject.extend(self._carry_clothes)
            flags["remove_clothes"] = True
        if policy.get("keep_background"):
            inject.extend(self._carry_background)
            flags["remove_location_and_background_color"] = True
        if not flags:
            self._carry_overlay = None
            return
        deduped: list[str] = []
        for tag in inject:
            if tag and tag not in deduped:
                deduped.append(tag)
        self._carry_overlay = {
            "pre_prompt_extra": deduped,
            "preprocessing_flags": flags,
        }

    def _extract_carry_tags(self, prompt: Any) -> tuple[list[str], list[str]]:
        """최종 프롬프트에서 의상/배경 태그 추출 — remove_clothes/remove_location 필터와
        동일한 사전(FilterDataManager.clothes_list / _location_set). 가중치 래퍼는 벗긴다."""
        manager = getattr(self.app_context, "filter_data_manager", None)
        if manager is None:
            return ([], [])
        tags = [tag.strip() for tag in split_tags_smart(str(prompt or "")) if tag and tag.strip()]
        clothes_list = getattr(manager, "clothes_list", None) or set()
        location_set = getattr(manager, "_location_set", None) or set()
        clothes: list[str] = []
        background: list[str] = []
        for raw_tag in tags:
            tag = _normalize_carry_tag(raw_tag)
            if not tag:
                continue
            if tag in clothes_list and tag not in clothes:
                clothes.append(tag)
            if tag in location_set and tag not in background:
                background.append(tag)
        return (clothes, background)

    def get_frozen_character_params(self) -> Optional[dict[str, Any]]:
        if not self.should_freeze_character_prompts():
            return None
        snapshot = self.ensure_freeze_snapshot()
        return copy.deepcopy(snapshot.character_params) if snapshot.character_params is not None else None

    def get_frozen_prompt_engineering_options(self) -> Optional[dict[str, Any]]:
        if not self.should_freeze_prompt_engineering():
            return None
        snapshot = self.ensure_freeze_snapshot()
        if snapshot.prompt_engineering_options is None:
            return None
        options = copy.deepcopy(snapshot.prompt_engineering_options)
        # Storyteller carry(1.5 의상/배경 유지): 이번 페이지에 한해 이전 페이지에서 추출한
        # 의상/배경 리터럴을 prefix에 더하고, 새 행의 해당 카테고리 태그는 제거 플래그로 거른다.
        overlay = self._carry_overlay
        if overlay:
            extra = [str(tag) for tag in (overlay.get("pre_prompt_extra") or []) if str(tag).strip()]
            if extra:
                pre = list(options.get("pre_prompt") or [])
                pre.extend(tag for tag in extra if tag not in pre)
                options["pre_prompt"] = pre
            flags = overlay.get("preprocessing_flags")
            if isinstance(flags, dict) and flags:
                preprocessing = dict(options.get("preprocessing_options") or {})
                preprocessing.update(flags)
                options["preprocessing_options"] = preprocessing
        return options

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
        if controller:
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
        # Headless runtime has no middle_section_controller (desktop CharacterModule is
        # gone). Capture the EXPANDED character params (post-wildcard literals) straight
        # from the saved character settings so the character/artist stays identical on
        # every page of the cycle. reuse_current_context=False forces the pristine
        # frame base + a fresh wildcard roll that we then freeze.
        try:
            from core.character_settings import character_params_from_settings

            params = character_params_from_settings(
                self.app_context,
                mode=str(self.app_context.get_api_mode() or "NAI"),
                reuse_current_context=False,
            )
            if params and params.get("characters"):
                return copy.deepcopy(params)
        except Exception as exc:
            print(f"[EventStream] 헤드리스 캐릭터 freeze 캡처 실패: {exc}")
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
            # Expand pre/post wildcards to literals ONCE here so a random token like
            # __artist__ resolves to a single value that every page reuses (freeze). The
            # PE hook returns these literals, so the later wildcard step is a no-op on them.
            pre_tags = self._expand_tags_literal(split_tags_smart(settings.get("pre_prompt", "")))
            post_tags = self._expand_tags_literal(split_tags_smart(settings.get("post_prompt", "")))
            preprocessing = dict(settings.get("preprocessing_options") or {})
            # Storyteller axis policy: the source row changes per page, so suppress the
            # row's own artist/copyright/character injection — identity stays fixed via the
            # frozen PE prefix + frozen Character module instead of drifting per page.
            preprocessing.update({
                "remove_work_title": True,
                "remove_author": True,
                "remove_character_name": True,
                # Tag Implication 압축은 스트림 중 강제 OFF — 새 행의 'bikini pull' 등이
                # carry로 주입/유지해야 할 'bikini' 같은 의상 태그를 소거해 의상 전이를
                # 깨뜨린다(사용자 결정).
                "tag_implication_compression": False,
            })
            return {
                "pre_prompt": pre_tags,
                "post_prompt": post_tags,
                "auto_hide": split_tags_smart(settings.get("auto_hide_prompt", "")),
                "preprocessing_options": preprocessing,
            }
        try:
            return copy.deepcopy(module.get_parameters())
        except Exception as exc:
            print(f"[EventStream] PromptEngineering freeze 캡처 실패: {exc}")
            return None

    def _expand_tags_literal(self, tags: list[str]) -> list[str]:
        """Expand any wildcard tokens in ``tags`` to literals using a throwaway context
        so the live prompt context's counters are not mutated. Plain tags pass through."""
        if not tags:
            return []
        wildcard_manager = getattr(self.app_context, "wildcard_manager", None)
        if wildcard_manager is None:
            return list(tags)
        try:
            from core.prompt_context import PromptContext
            from core.wildcard_processor import WildcardProcessor

            source_row = getattr(self.app_context, "current_source_row", None)
            if source_row is None:
                source_row = pd.Series({}, name="event_stream_freeze")
            processor = WildcardProcessor(wildcard_manager)
            context = PromptContext(source_row=source_row, settings={})
            return list(processor.expand_tags(list(tags), context))
        except Exception as exc:
            print(f"[EventStream] PE freeze 전개 실패: {exc}")
            return list(tags)

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

        # 벡터화 경로: 행별 predicate apply는 수십만 행에서 분 단위로 걸리며 GIL로
        # 이벤트 루프까지 굳힌다(Storyteller 페이지 할당의 성능 핵심).
        popper = getattr(search_results, "pop_random_row_matching_tags", None)
        if callable(popper):
            return popper(
                rating_filter,
                include_tags=sorted(include_tags),
                exclude_tags=sorted(exclude_tags),
            )

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
