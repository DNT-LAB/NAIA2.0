from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd

from core.search_result_model import SearchResultModel
from core.prompt_engineering_settings import get_prompt_engineering_store
from core.event_stream_vibe import EVENT_STREAM_VIBE_IE, EVENT_STREAM_VIBE_STRENGTH
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
        # Storyteller "Use Vibe"(1회성, Storage 미저장): use_vibe 스텝의 완료 이미지
        # bytes를 보관했다가(Anlas 0) 다음 스텝 전진 시 encode-vibe(IE 1.0)로 1회 인코딩,
        # 이후 스트림 페이지에 단일 vibe(RS 0.6, 공존 기존 vibe RS는 절반)로 주입한다. start_linear/stop/라운드
        # 경계에서 전부 클리어 — 어떤 종료 경로로도 잔존하지 않는다.
        self._vibe_source: Optional[dict[str, Any]] = None
        self._stream_vibe: Optional[dict[str, Any]] = None
        self._issued_stream_encodings: set[str] = set()
        self._pending_vibe_policy = False
        self._vibe_warned: set[str] = set()
        self._vibe_messages: list[dict[str, Any]] = []
        # 캡처 stamp 단조 시퀀스(Codex 구현리뷰 F2): 같은 스텝 재생성/Random 연타로 완료가
        # 역순 도착해도 '가장 나중에 시작한' 생성의 이미지가 이긴다. 라운드 경계는 배리어
        # (_vibe_seq_accepted = 발급분+1)로 이전 라운드의 in-flight 캡처를 전부 거부한다.
        self._vibe_stamp_seq = 0
        self._vibe_seq_accepted = 0
        # 인코딩(2 Anlas) 직후 잔액 pill 즉시 갱신용 1회성 플래그 — 인코딩을 일으킨
        # 랜덤/생성 경로가 consume 후 anlas_update를 브로드캐스트한다.
        self._anlas_refresh_pending = False

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
        self._reset_stream_vibe(full=True)
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
        self._reset_stream_vibe(full=True)
        self.app_context.publish("event_stream_stopped", {"run_id": run_id})

    def set_carry_overlay(self, overlay: Optional[dict[str, Any]]) -> None:
        """Storyteller 페이지별 carry(의상/배경 유지): 다음 프롬프트 빌드에 한해 frozen
        PE options에 병합할 ``{"pre_prompt_extra": [...], "preprocessing_flags": {...}}``."""
        self._carry_overlay = dict(overlay) if overlay else None

    # ------------------------------------------------- Storyteller "Use Vibe"
    def _reset_stream_vibe(self, *, full: bool = False) -> None:
        """라운드 경계(1.5 step-0 규칙)는 소스/vibe만, start/stop은 발급 이력·경고·메시지까지
        전부 클리어한다."""
        self._vibe_source = None
        self._stream_vibe = None
        self._pending_vibe_policy = False
        if full:
            self._issued_stream_encodings = set()
            self._vibe_warned = set()
            self._vibe_messages = []
            self._vibe_stamp_seq = 0
            self._vibe_seq_accepted = 0
            self._anlas_refresh_pending = False

    def store_vibe_source(self, image_bytes: Any, *, run_id: str, seq: Any = None) -> bool:
        """use_vibe 스텝의 완료 이미지 보관(Anlas 0). 같은 스텝 재생성은 교체 — 전진 시
        마지막 1장만 인코딩된다. stamp의 run_id가 활성 런과 다르면 거부(stale/특수 완료가
        엉뚱한 이미지를 vibe로 만드는 오캡처 방지 — stamp-only 바인딩). ``seq``가 있으면
        단조 게이트: 이미 더 새 stamp가 수락됐거나 라운드 경계 배리어를 지났으면 거부
        (완료 역순 도착·이전 라운드 in-flight 캡처 차단, Codex 구현리뷰 F2)."""
        if not isinstance(image_bytes, (bytes, bytearray)) or not image_bytes:
            return False
        if not self.is_active or not self._state or str(run_id or "") != self._state.run_id:
            return False
        if seq is not None:
            try:
                seq_value = int(seq)
            except (TypeError, ValueError):
                return False
            if seq_value < self._vibe_seq_accepted:
                return False
            self._vibe_seq_accepted = seq_value
        self._vibe_source = {"bytes": bytes(image_bytes)}
        return True

    def should_stamp_vibe_capture(self) -> bool:
        """현재 노드가 use_vibe 스텝이면 True — params 빌드 시 캡처 stamp 게이트."""
        return self.is_active and self._pending_vibe_policy

    def issue_vibe_capture_stamp(self) -> Optional[dict[str, Any]]:
        """params 빌드 시 호출: use_vibe 스텝이면 ``{"run_id", "seq"}`` stamp를 발급한다.
        seq는 발급 순서 단조 증가 — 완료가 역순으로 도착해도 '가장 나중에 시작한' 생성의
        이미지가 vibe 소스로 남는다."""
        if not self.should_stamp_vibe_capture() or not self._state:
            return None
        self._vibe_stamp_seq += 1
        return {"run_id": self._state.run_id, "seq": self._vibe_stamp_seq}

    def get_stream_vibe(self) -> Optional[dict[str, Any]]:
        """주입용 단일 스트림 vibe ``{encoding, strength, model}`` (없으면/비활성이면 None)."""
        if not self.is_active or not self._stream_vibe:
            return None
        return dict(self._stream_vibe)

    def issued_stream_encodings(self) -> set[str]:
        """이번 런이 발급한 모든 인코딩 — 주입부가 carried/stale 리스트에서 걷어낼 때 사용."""
        return set(self._issued_stream_encodings)

    def consume_vibe_messages(self) -> list[dict[str, Any]]:
        """인코딩 성공/실패 토스트(런타임은 직접 브로드캐스트 불가 → 랜덤 경로가 플러시)."""
        messages = self._vibe_messages
        self._vibe_messages = []
        return messages

    def consume_anlas_refresh(self) -> bool:
        """인코딩(2 Anlas)이 방금 일어났으면 True를 1회 반환 — 호출자가 Anlas 잔액을
        재조회·브로드캐스트해 차감을 즉시 확인할 수 있게 한다(5분 폴링 대기 없이)."""
        pending = self._anlas_refresh_pending
        self._anlas_refresh_pending = False
        return pending

    def _queue_vibe_message(self, message: str, *, level: str = "info") -> None:
        self._vibe_messages.append({"type": "toast", "level": level, "message": message})

    def _encode_pending_vibe_source(self) -> None:
        """전진 시점 lazy 인코딩(Use Vibe): 직전 use_vibe 페이지가 남긴 원본 이미지를
        encode-vibe(IE EVENT_STREAM_VIBE_IE=1.0)로 1회 인코딩해 단일 스트림 vibe로 교체한다. 같은 스텝을 여러 번
        재생성해도 마지막 1장만 인코딩(스텝당 2 Anlas). 실패는 런당 1회 경고 후 vibe 없이
        계속(사용자 확정) — 성공/실패 무관 소스는 소비한다(재시도 폭주 방지). 호출 컨텍스트는
        prepare(수동 Random·자동 continuation 모두 ``asyncio.to_thread``)라 이벤트 루프 비차단."""
        source = self._vibe_source
        if not source:
            return
        self._vibe_source = None
        try:
            from core.headless_vibe_transfer_service import encode_vibe_bytes

            encoding = encode_vibe_bytes(
                self.app_context, source.get("bytes") or b"", EVENT_STREAM_VIBE_IE
            )
            try:
                model_key = str(self.app_context._current_model_key() or "")
            except Exception:
                model_key = ""
            self._stream_vibe = {
                "encoding": encoding,
                "strength": EVENT_STREAM_VIBE_STRENGTH,
                "model": model_key,
            }
            self._issued_stream_encodings.add(encoding)
            self._anlas_refresh_pending = True
            self._queue_vibe_message(
                f"Use Vibe: 스텝 결과 인코딩 완료 — IE {EVENT_STREAM_VIBE_IE:.1f}, "
                f"RS {EVENT_STREAM_VIBE_STRENGTH:.1f} (2 Anlas). 다음 스텝부터 적용됩니다.",
                level="success",
            )
        except Exception as exc:
            if "encode_failed" not in self._vibe_warned:
                self._vibe_warned.add("encode_failed")
                self._queue_vibe_message(
                    f"Use Vibe 인코딩 실패 — vibe 없이 계속합니다: {exc}", level="warning"
                )

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
            # 라운드 경계: Use Vibe도 1.5 step-0 규칙으로 리셋 — 이전 라운드 vibe가 새
            # freeze 롤(새 캐릭터)에 묻는 드리프트 방지(사용자 확정). 마지막 스텝의 미인코딩
            # 소스도 여기서 폐기되므로 Anlas를 쓰지 않는다. 배리어로 이전 라운드의
            # in-flight 캡처(아직 완료 전인 stamped 생성)도 도착 시 거부된다.
            self._vibe_source = None
            self._stream_vibe = None
            self._vibe_seq_accepted = self._vibe_stamp_seq + 1
        self.ensure_freeze_snapshot()
        # carry(의상/배경 유지)는 이전 노드의 policy + 직전 생성에서 추출한 태그로 매
        # 페이지 자체 계산한다 — 수동 진행/자동 사이클 공통(과거엔 자동 전용 배선이라
        # 수동 모드에서 전혀 동작하지 않던 버그).
        self._apply_carry_for_current_node()
        # Use Vibe: 직전 use_vibe 페이지가 남긴 이미지를 여기서(스텝 전진 시점) 1회
        # 인코딩한다 — carry처럼 수동 진행/자동 사이클 공통 단일 경로.
        self._encode_pending_vibe_source()
        node = self._state.current_node()
        # 캡처 의향(pending)은 이 prepare가 '성공'했을 때만 남긴다 — 행 할당 실패 후
        # 잔존 pending이 무관한 일반 생성(스트림은 여전히 활성)을 stamp해 엉뚱한 이미지를
        # vibe로 만드는 오캡처 방지(Codex 구현리뷰 F1). 성공 경로 말미에서 설정한다.
        self._pending_vibe_policy = False
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
        # use_vibe 스텝: 이 페이지의 생성 결과를 다음 전진 때 vibe 소스로 캡처한다
        # (params 빌드 시 issue_vibe_capture_stamp → 완료 시 store_vibe_source).
        # 비NAI 모드에서는 작업 자체를 수행하지 않는다(사용자 요청) — stamp 발급의
        # apply() NAI 게이트에 더해 의향 단계에서도 차단(이중 방어).
        use_vibe_policy = bool((node.axis_carry_policy or {}).get("use_vibe"))
        if use_vibe_policy:
            try:
                use_vibe_policy = str(self.app_context.get_api_mode() or "").upper() == "NAI"
            except Exception:
                use_vibe_policy = False
        self._pending_vibe_policy = use_vibe_policy
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
                "stream_vibe_active": False,
                "vibe_capture_pending": False,
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
            "stream_vibe_active": self._stream_vibe is not None,
            "vibe_capture_pending": self._vibe_source is not None,
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
