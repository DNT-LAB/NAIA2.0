"""Headless Remote Web generation request normalization.

Round 35 keeps generation dispatch PyQt-free by turning the Remote Web payload
into the same queue request shape used by the desktop controller. Actual image
API execution is moved in a later round; this service owns the request contract
and queue handoff only.
"""

from __future__ import annotations

from dataclasses import dataclass
import random
import re
from typing import Any

import pandas as pd

from core.event_stream_vibe import (
    EVENT_STREAM_VIBE_MARKER_KEY,
    strip_event_stream_vibe_params,
)
from core.extension_runtime import ext_lineage_fields
from core.generation_request import (
    GenerationRequest,
    NAICharacterData,
    NAICharacterReferenceData,
    NAIVibeTransferData,
)
from core.headless_result_service import HeadlessStoredResult
from core.resolution_utils import snap_resolution_to_multiple
from core.web_session_context import WebSessionContext


TOKEN_KEYS = {
    "NAI": "nai_token",
    "WEBUI": "webui_url",
    "COMFYUI": "comfyui_url",
}

SCHEMA_ONLY_KEYS = {
    "type",
    "schema_only",
    "options_model",
    "options_sampler",
    "options_scheduler",
    "options_resolution",
    "steps_range",
    "nai_flags_enabled",
}

DERIVED_GENERATION_PARAM_KEYS = (
    "api_mode",
    "model",
    "sampler",
    "scheduler",
    "steps",
    "width",
    "height",
    "resolution",
    "seed",
    "cfg_scale",
    "cfg_rescale",
    "negative_prompt",
)


def _safe_str(value: Any) -> str:
    try:
        return str(value)
    except (SystemExit, Exception):
        return "<unrepresentable>"


def _safe_repr(value: Any) -> str:
    try:
        return repr(value)
    except (SystemExit, Exception):
        return "<unrepresentable>"


def _event_safe_copy(value: Any, _depth: int = 0) -> Any:
    """dispatched 이벤트에 싣는 params 값의 fail-closed **무예외** 재귀 안전 사본.

    dict/list/tuple/set은 새 컨테이너로 재구성하고, 불변 스칼라는 그대로 통과,
    bytes는 불변 사본, 그 외 알 수 없는 타입은 **참조 대신 repr 문자열**로
    대체한다 — deepcopy 실패 폴백으로 원본 컨테이너가 노출되는 구멍을 없앤다
    (구독자가 무엇을 변조해도 실행 대기 중인 GenerationRequest.params에 절대
    닿지 않는다). 전체가 try로 감싸여 있어 적대적 컨테이너(items()/iteration/
    __str__이 예외를 던지는 서브클래스)도 사본 구성을 터뜨리지 못한다 — 요청이
    이미 큐에 들어간 뒤의 publish가 누락되는 split-brain을 차단한다.
    """
    try:
        if _depth > 6:
            return _safe_repr(value)
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            return {
                _safe_str(key): _event_safe_copy(item, _depth + 1)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple, set)):
            return [_event_safe_copy(item, _depth + 1) for item in value]
        if isinstance(value, (bytes, bytearray)):
            return bytes(value)
        return _safe_repr(value)
    except (SystemExit, Exception):
        return "<unrepresentable>"


@dataclass
class HeadlessGenerationDispatch:
    request: GenerationRequest | None
    api_mode: str
    blocked_reason: str = ""

    @property
    def request_id(self) -> str:
        return self.request.request_id if self.request is not None else ""

    @property
    def ok(self) -> bool:
        return self.request is not None and not self.blocked_reason

    def websocket_payload(self) -> dict[str, Any]:
        if not self.ok:
            return {
                "type": "generation_dispatched",
                "ok": False,
                "api_mode": self.api_mode,
                "message": self.blocked_reason,
            }

        params = self.request.params
        prompt_run_id = str(getattr(self.request, "prompt_run_id", "") or params.get("prompt_run_id") or "")
        return {
            "type": "generation_dispatched",
            "ok": True,
            "request_id": self.request.request_id,
            "generation_request_id": self.request.request_id,
            "prompt_run_id": prompt_run_id,
            "api_mode": self.api_mode,
            "priority": self.request.priority,
            "queued": True,
            "params": {
                "width": params.get("width"),
                "height": params.get("height"),
                "model": params.get("model"),
                "sampler": params.get("sampler"),
                "scheduler": params.get("scheduler"),
                "steps": params.get("steps"),
                "cfg_scale": params.get("cfg_scale"),
                "seed": params.get("seed"),
                "has_prompt": bool(params.get("input")),
                "has_negative_prompt": bool(params.get("negative_prompt")),
                "credential_configured": bool(params.get("credential")),
            },
        }


class HeadlessGenerationService:
    """Create queue-ready generation requests without desktop widgets."""

    def __init__(self, context: WebSessionContext):
        self.context = context

    def enqueue_remote_request(
        self,
        command: dict[str, Any] | None = None,
        *,
        enqueue: bool = True,
    ) -> HeadlessGenerationDispatch:
        command = command if isinstance(command, dict) else {}
        api_mode = self._normalize_mode(command)
        credential = self._credential_for_mode(api_mode)
        if not credential:
            return HeadlessGenerationDispatch(
                request=None,
                api_mode=api_mode,
                blocked_reason=f"{api_mode} credential is not configured.",
            )

        params = self._normalized_params(command, api_mode, credential)
        source_row = self._source_row(params)
        params.pop("_source_row_data", None)
        params.pop("_source_name", None)
        prompt_run_id = self._prompt_run_id_for_command(command, params)
        if not prompt_run_id:
            prompt_run_id = self._create_direct_prompt_run(command, params, source_row)
        if prompt_run_id:
            params["prompt_run_id"] = prompt_run_id
            # 조건부 규칙(neg 타겟)이 이 프롬프트 런에 기록한 네거티브 조작을 병합한다.
            # 직접 생성 런(_create_direct_prompt_run)은 조작이 없으므로 자연 no-op.
            self._apply_conditional_negative(params, prompt_run_id)
        priority = self._priority(command)
        nai_characters, nai_vibe_transfer, nai_character_reference = self._extract_nai_data(params, api_mode)
        request = GenerationRequest(
            params=params,
            source_row=source_row,
            priority=priority,
            max_retries=0,
            nai_characters=nai_characters,
            nai_vibe_transfer=nai_vibe_transfer,
            nai_character_reference=nai_character_reference,
            prompt_run_id=prompt_run_id,
        )
        params["generation_request_id"] = request.request_id
        if params.get("result_enhance_request"):
            params["result_enhance_request_id"] = request.request_id

        queue_manager = self.context.generation_queue_manager
        if enqueue:
            if priority > 0:
                queue_manager.enqueue_with_priority(request)
            else:
                queue_manager.enqueue_request(request)

        self.context.last_generation_request = request
        self.context.last_generation_params = params
        if prompt_run_id:
            # 큐 삽입 이후~dispatched 발행 이전의 비치명 부수효과(런 연결/파생 기록)는
            # 격리한다 — 여기서 예외가 새면 요청은 큐에 있는데 dispatched 이벤트만
            # 누락되는 split-brain이 된다(이벤트를 계약으로 쓰는 확장이 요청을 영영
            # 못 보고, 호출자 재시도 시 중복 enqueue 위험).
            try:
                linker = getattr(self.context, "link_generation_to_prompt_run", None)
                if callable(linker):
                    linker(prompt_run_id, request.request_id)
                derived_recorder = getattr(self.context, "record_prompt_run_derived", None)
                if callable(derived_recorder):
                    derived_recorder(
                        prompt_run_id,
                        {
                            "generation_request_id": request.request_id,
                            "generation_params": self._derived_generation_params(params),
                        },
                    )
            except Exception as exc:
                print(
                    "Headless Remote: prompt run linkage failed (request still queued) - "
                    f"{_safe_repr(exc)}",
                    flush=True,
                )
        # Extension 표면(v1): source=명령 type(버튼 generate/depth_generate/프리셋 경로
        # 구분), ext_origin=확장이 enqueue_generation으로 만든 파생 요청 식별(재귀 가드),
        # params=자격증명·내부(_*) 키를 제외한 읽기 전용 스냅샷(값은 원본 참조 공유 —
        # 구독자는 변조 금지).
        # 구독자(확장)가 중첩 컨테이너를 변조해 실행 대기 중인 요청 params를
        # 오염시키지 못하도록 fail-closed 안전 사본을 발행한다(원본 컨테이너
        # 참조는 어떤 경우에도 이벤트에 실리지 않는다). 키 문자열화도 무예외
        # 경로(_safe_str)로 — __str__이 던지는 적대적 키가 스냅샷 구성을 터뜨려
        # enqueue 이후의 publish를 누락시키지 않게 한다.
        event_params = {}
        for key, value in params.items():
            safe_key = _safe_str(key)
            if safe_key == "credential" or safe_key.startswith("_"):
                continue
            event_params[safe_key] = _event_safe_copy(value)
        # source도 무예외 경로로 — 적대적 command type(__str__/__bool__ raising)이
        # enqueue 이후의 publish를 누락시키지 않게 한다.
        raw_source = command.get("type")
        self.context.publish("generation_request_dispatched", {
            "request_id": request.request_id,
            "generation_request_id": request.request_id,
            "prompt_run_id": prompt_run_id,
            "api_mode": api_mode,
            "priority": priority,
            "source": _safe_str(raw_source) if raw_source is not None else "",
            **ext_lineage_fields(params),
            "params": event_params,
        })
        print(
            "Headless Remote: generation request queued "
            f"id={request.request_id[:8]} mode={api_mode} "
            f"size={params.get('width')}x{params.get('height')}",
            flush=True,
        )
        return HeadlessGenerationDispatch(request=request, api_mode=api_mode)

    @staticmethod
    def _derived_generation_params(params: dict[str, Any]) -> dict[str, Any]:
        return {
            key: params.get(key)
            for key in DERIVED_GENERATION_PARAM_KEYS
            if key in params
        }

    def execute_request(self, request: GenerationRequest, preview_callback=None, progress_callback=None) -> HeadlessStoredResult:
        """Execute one queued request and store its result in server state.

        preview_callback/progress_callback: NAI 스트리밍 미리보기용 콜백.
        제너레이션 러너(asyncio.to_thread)에서 워커 스레드로 호출되므로,
        콜백 내부에서 이벤트 루프 접근은 스레드 안전하게 처리해야 한다.
        """

        params = dict(request.params or {})
        params["_generation_request"] = request
        # 실행본 기록 키는 이번 실행에서 다시 계산된다 — 리플레이된 params에 남은 직전
        # 실행의 값이 이번 결과 메타데이터로 둔갑하지 않게 항상 비우고 시작한다
        # (NAI가 아니거나 캐릭터가 꺼진 실행에서 stale 캐릭터 표시 방지).
        params.pop("_executed_characters", None)
        params.pop("_executed_characters_uc", None)
        # Storyteller Use Vibe: 정지 후 실행되는 큐 잔존 페이지가 휘발성 스트림 vibe를
        # 보내지 않도록 실행 시점 검증 — 마커의 run_id가 활성 스트림과 다르면 스트림
        # 발급분만 제거한다(일반 vibe 불변; Codex 설계검수 #4).
        marker = params.get(EVENT_STREAM_VIBE_MARKER_KEY)
        if isinstance(marker, dict):
            runtime = getattr(self.context, "event_stream_runtime", None)
            active_run = (
                str(getattr(runtime, "run_id", "") or "")
                if runtime is not None and getattr(runtime, "is_active", False)
                else ""
            )
            if str(marker.get("run_id") or "") != active_run:
                strip_event_stream_vibe_params(params)
        # 프롬프트 입력창에 직접 친 와일드카드를 생성 시점에 전개한다(desktop
        # generation_controller 패리티). request.params 원본은 건드리지 않으므로
        # prompt_fixed Auto Gen 반복마다 여기서 새로 전개 = 매 생성 재롤.
        self._expand_input_wildcards(params)
        request.mark_processing()
        api_service = self._api_service()
        api_result = api_service.call_generation_api(
            params,
            progress_callback=progress_callback,
            preview_callback=preview_callback,
        )
        if api_result.get("status") == "error":
            error_message = str(api_result.get("message") or "Unknown API error")
            request.mark_failed(error_message)
            raise RuntimeError(error_message)
        api_result["generation_params"] = params
        api_result["source_row"] = request.source_row
        # 읽기 전용 생성 추적(파이프라인 단계 델타 + 적용된 와일드카드)을 이 이미지에 붙인다.
        # current_prompt_context 는 process()와 _expand_input_wildcards를 거친 직후라 권위본.
        trace_payload = self._build_generation_trace(request)
        if trace_payload:
            api_result["naia_generation_trace"] = trace_payload
        stored = self.context.result_store.add_api_result(api_result, request)
        request.mark_completed()
        # ext_origin/ext_chain_depth: dispatched와 동일한 lineage를 결과 이벤트에도
        # 싣는다 — 확장이 자기 파생 요청의 "결과"를 구독해 재-enqueue하는 경로가
        # 깊이 추적을 우회(매번 depth 1로 초기화)해 무한 연쇄가 되는 것을 막는다.
        self.context.publish("generation_result_available", {
            "request_id": request.request_id,
            "generation_request_id": request.request_id,
            "prompt_run_id": str(getattr(request, "prompt_run_id", "") or params.get("prompt_run_id") or ""),
            "api_mode": params.get("api_mode", ""),
            **ext_lineage_fields(params),
        })
        print(
            "Headless Remote: generation completed "
            f"id={request.request_id[:8]} mode={params.get('api_mode', '')} "
            f"size={stored.item.image.width}x{stored.item.image.height}",
            flush=True,
        )
        return stored

    def _build_generation_trace(self, request=None) -> dict[str, Any]:
        """직전 파이프라인 실행(current_prompt_context)에서 읽기 전용 생성 추적을 수집한다.

        - ``pipeline_trace``: 각 파이프라인 단계가 프롬프트에 한 일(added/removed/note) — Hooker 대체.
          prompt_processor 가 ``context.metadata['pipeline_trace']`` 에 누적해 둔다.
        - ``wildcards``: ``{history:[{name,value}], state:[{name,current,total,...}]}`` —
          이 이미지에 실제 적용된 와일드카드(Wildcard Watch). 셰이프는 headless_wildcard_service.
          _collect_runtime_state 와 동일해 프론트 렌더를 재사용한다.

        JSON-safe(문자열/정수/리스트/딕트)만 담는다 — 매 PNG ``naia_prompt_context`` 청크와 모든
        메타데이터 페이로드에 임베드되므로 raw bytes/Series 는 절대 넣지 않는다. 실패해도 절대
        raise 하지 않는다(결과 저장을 막지 않음)."""
        trace: dict[str, Any] = {}
        try:
            ctx = getattr(self.context, "current_prompt_context", None)
            if ctx is None:
                return trace

            meta = getattr(ctx, "metadata", None)
            # 리플레이 안전: 이 요청이 명시적으로 *다른* prompt run 에 속하면(예: '원본 유지' 큐
            # 리플레이가 과거 run_id 를 실어오면) current_prompt_context 는 이 이미지의 것이 아니다
            # → 추적을 붙이지 않는다. 둘 중 하나라도 비어 있으면(일반 경로) 억제하지 않는다.
            ctx_run = str((meta or {}).get("prompt_run_id") or "")
            req_run = str(getattr(request, "prompt_run_id", "") or "")
            if req_run and ctx_run and req_run != ctx_run:
                return trace

            # 매 저장 PNG(naia_prompt_context 청크)와 모든 메타데이터 페이로드에 임베드되므로
            # 항목 수·문자열 길이를 캡해 비정상적으로 긴 프롬프트/다수 와일드카드에서도 바운드한다
            # (pipeline_trace 는 prompt_processor 에서 이미 캡됨).
            _MAX_ITEMS = 60
            _MAX_LEN = 200
            _cap = lambda s: (s[:_MAX_LEN] + "…") if len(s) > _MAX_LEN else s

            if isinstance(meta, dict):
                stages = meta.get("pipeline_trace")
                if isinstance(stages, list) and stages:
                    trace["pipeline_trace"] = list(stages)

            history: list[dict[str, Any]] = []
            rolls = getattr(ctx, "wildcard_rolls", None)
            if isinstance(rolls, list) and rolls:
                # 위치 인식 롤(블록별 뷰/위치 스코핑 freeze). (location, key, slot) 단위로 마지막
                # 값을 유지해 같은 키가 prefix·postfix 등 다른 블록에 있어도 따로 표시된다.
                seen: dict = {}
                for roll in rolls:
                    if not isinstance(roll, dict):
                        continue
                    key = str(roll.get("key", ""))
                    if not key:
                        continue
                    seen[(roll.get("location"), key, roll.get("slot"))] = roll
                for (loc, key, slot), roll in seen.items():
                    entry = {"name": _cap(key), "value": _cap(str(roll.get("value", "")))}
                    if loc is not None:
                        entry["location"] = str(loc)
                    if slot is not None:
                        entry["slot"] = slot
                    history.append(entry)
                    if len(history) >= _MAX_ITEMS:
                        break
            else:
                # 폴백: 위치 인식 롤이 없으면(구 경로/캐릭터 스냅샷 재사용) 키-only 히스토리.
                wc_history = getattr(ctx, "wildcard_history", None)
                if isinstance(wc_history, dict):
                    for name, values in wc_history.items():
                        if not values:
                            continue
                        chosen = values[-1] if isinstance(values, (list, tuple)) else values
                        history.append({"name": _cap(str(name)), "value": _cap(str(chosen))})
                        if len(history) >= _MAX_ITEMS:
                            break

            state: list[dict[str, Any]] = []
            wc_state = getattr(ctx, "wildcard_state", None)
            if isinstance(wc_state, dict):
                for name, info in wc_state.items():
                    if not isinstance(info, dict):
                        continue
                    entry: dict[str, Any] = {
                        "name": _cap(str(name)),
                        "current": int(info.get("current", 0) or 0),
                        "total": int(info.get("total", 0) or 0),
                    }
                    if "master_name" in info:
                        entry["dependent"] = True
                    master = info.get("master_name")
                    if master and str(master) not in {"", "unknown"}:
                        entry["master"] = _cap(str(master))
                    state.append(entry)
                    if len(state) >= _MAX_ITEMS:
                        break

            if history or state:
                trace["wildcards"] = {"history": history, "state": state}
        except Exception:
            pass
        return trace

    def _expand_input_wildcards(self, params: dict[str, Any]) -> None:
        """프롬프트 입력창의 와일드카드(__wc__/__*wc__/__$m:s__/$wc/<wc>)를 생성 직전에
        전개한다 — future01 ``generation_controller._expand_wildcards_in_input`` 패리티.

        함께 처리(desktop 동일): 주석(#)/개행 제거, ``-태그``(`::` 없는 경우)를 네거티브로
        이동, 와일드카드 라인의 global append 소비. 랜덤 경로 산출물처럼 토큰이 없는
        프롬프트는 빠르게 통과한다. ``params``는 execute_request의 로컬 복사본이므로
        요청 원본에는 토큰이 남아 반복 생성 시 매번 재전개(재롤)된다."""
        text = params.get("input")
        if not isinstance(text, str) or not text.strip():
            return
        # 빠른 통과: 와일드카드 문법 후보가 전혀 없으면 손대지 않는다.
        if "__" not in text and "<" not in text and "$" not in text:
            return
        try:
            import weakref

            from core.prompt_context import PromptContext
            from core.wildcard_processor import WildcardProcessor, split_tags_smart

            prompt_context = getattr(self.context, "current_prompt_context", None)
            if prompt_context is None:
                # 순차(__*wc__) 카운터 공유를 위해 AppContext에 보관한다(desktop 동일).
                prompt_context = PromptContext(
                    source_row=pd.Series(dtype=object), settings={}
                )
                self.context.current_prompt_context = prompt_context

            wildcard_manager = getattr(self.context, "wildcard_manager", None)
            if wildcard_manager is None:
                from core.wildcard_manager import WildcardManager

                wildcard_manager = WildcardManager()
                self.context.wildcard_manager = wildcard_manager
            if getattr(wildcard_manager, "_app_context_ref", None) is None:
                try:
                    wildcard_manager._app_context_ref = weakref.ref(self.context)
                except TypeError:
                    pass

            processor = WildcardProcessor(wildcard_manager)

            negative = str(params.get("negative_prompt") or "")
            cleaned_tags: list[str] = []
            for tag in split_tags_smart(text):
                processed = tag.replace("\n", "").strip()
                if not processed or processed.startswith("#"):
                    continue
                if processed.startswith("-") and "::" not in processed:
                    negative_tag = processed[1:].strip()
                    if negative_tag:
                        negative = f"{negative}, {negative_tag}" if negative else negative_tag
                    continue
                cleaned_tags.append(processed)

            # 입력창 와일드카드는 메인 프롬프트로 취급(location='main')해 위치 인식 롤에 기록.
            expanded_tags = processor.expand_tags(cleaned_tags, prompt_context, location='main')
            result_parts = list(expanded_tags)
            if prompt_context.global_append_tags:
                result_parts.extend(prompt_context.global_append_tags)
                prompt_context.global_append_tags.clear()

            expanded_text = ", ".join(result_parts) if result_parts else text
            if expanded_text != text:
                params["input"] = expanded_text
            params["negative_prompt"] = negative
        except Exception as exc:  # pragma: no cover - defensive
            print(f"⚠️ 입력 와일드카드 전개 실패(원본 사용): {exc}")

    def _api_service(self):
        service = getattr(self.context, "api_service", None)
        if service is None:
            from core.api_service import APIService

            service = APIService(self.context)
            self.context.api_service = service
        return service

    def _normalize_mode(self, command: dict[str, Any]) -> str:
        overrides = command.get("overrides") if isinstance(command.get("overrides"), dict) else {}
        requested = str(command.get("api_mode") or overrides.get("api_mode") or self.context.get_api_mode() or "NAI")
        normalized = requested.strip().upper()
        return normalized if normalized in TOKEN_KEYS else "NAI"

    def _credential_for_mode(self, api_mode: str) -> str:
        token_key = TOKEN_KEYS.get(api_mode, "nai_token")
        return str(self.context.secure_token_manager.get_token(token_key) or "")

    def _normalized_params(self, command: dict[str, Any], api_mode: str, credential: str) -> dict[str, Any]:
        schema = self.context.generation_param_schema_payload()
        params = {
            key: value
            for key, value in schema.items()
            if key not in SCHEMA_ONLY_KEYS and not key.startswith("options_")
        }
        params.update(self.context.get_options())
        params.update(self.context.remote_params)

        overrides = command.get("overrides") if isinstance(command.get("overrides"), dict) else {}
        params.update(overrides)

        # 확장 lineage 키의 신뢰된 발급자는 ExtensionContext.enqueue_generation뿐이다.
        # 다른 ingress(프론트/외부 브릿지)가 보낸 _ext_* 값은 여기서 안전 형태로
        # 강제 변환해, 이후 publish/체인 캡 로직이 예외나 캡 우회를 겪지 않게 한다
        # (형식이 깨진 깊이는 상한으로 간주 = fail-closed).
        if "_ext_origin" in params or "_ext_chain_depth" in params:
            lineage = ext_lineage_fields(params)
            params["_ext_origin"] = lineage["ext_origin"]
            params["_ext_chain_depth"] = lineage["ext_chain_depth"]

        # Seed Fix가 꺼져 있으면, 이 요청(overrides)이 시드를 명시하지 않는 한 직전
        # 생성이 remote_params/스키마에 남긴 구체 시드를 재사용하지 않도록 리셋한다 —
        # 프리셋 탭 Generate·Event/Sequence Preset·Refine 등 시드를 안 보내는 경로가
        # 같은 시드로 반복 생성되는 버그 방지(-1은 _normalize_numbers가 NAI면 재추첨,
        # WEBUI/COMFYUI면 백엔드 랜덤화에 위임). 시드 재현 경로(Enhance replay)는
        # seed_fixed=True와 함께 시드를 명시하므로 영향 없다(result_commands.py).
        if "seed" not in overrides and not self._to_bool(params.get("seed_fixed")):
            params["seed"] = -1

        prompt = command.get("prompt")
        negative = command.get("negative_prompt")
        if prompt is not None:
            params["input"] = str(prompt)
            params["_raw_input"] = str(prompt)
        elif "input" not in params:
            params["input"] = str(self.context.prompt_text or "")
            params["_raw_input"] = params["input"]
        if negative is not None:
            params["negative_prompt"] = str(negative)
        elif "negative_prompt" not in params:
            params["negative_prompt"] = str(self.context.negative_prompt_text or "")

        params["api_mode"] = api_mode
        params["credential"] = credential
        params["_remote_web_session_params"] = True
        params["_remote_queue_source"] = str(params.get("_remote_queue_source") or "Web")

        self._normalize_booleans(params)
        self._normalize_resolution(params)
        self._normalize_numbers(params, api_mode)
        self._normalize_comfyui_workflow_type(params, api_mode)
        apply_image_modules = getattr(self.context, "apply_headless_image_module_params", None)
        if callable(apply_image_modules):
            apply_image_modules(params, api_mode)
        return params

    @staticmethod
    def _normalize_comfyui_workflow_type(params: dict[str, Any], api_mode: str) -> None:
        """Derive the COMFYUI ``workflow_type`` discriminator when it is missing.

        The web UI computes ``workflow_type`` (``unet`` for ANIMA, ``checkpoint``
        otherwise) at generate time in ``_collectCurrentParams`` and only ships it
        with frontend-issued generate commands. Server-initiated generations
        (Automation, Auto Generate continuation) only see the persisted
        ``sampling_mode`` and would otherwise fall back to the ``checkpoint``
        default in ``ComfyUIWorkflowManager.apply_params_to_workflow`` — building
        the wrong base workflow and getting rejected at ComfyUI ``/prompt``.
        Mirror the frontend mapping so every server path builds the same workflow.
        """
        if str(api_mode or "").strip().upper() != "COMFYUI":
            return
        existing = str(params.get("workflow_type") or "").strip().lower()
        if existing in {"unet", "checkpoint", "bypass", "free", "locked"}:
            return
        sampling_mode = str(
            params.get("comfyui_sampling_mode")
            or params.get("sampling_mode")
            or ""
        ).strip().lower()
        if sampling_mode == "bypass":
            params["workflow_type"] = "bypass"
        elif sampling_mode == "anima":
            params["workflow_type"] = "unet"
        elif sampling_mode:
            # An explicit non-ANIMA choice (eps/v_prediction) maps to checkpoint.
            params["workflow_type"] = "checkpoint"
        else:
            # No sampling_mode persisted: ANIMA is the default COMFYUI model, so
            # build the unet (ANIMA) workflow rather than checkpoint.
            params["workflow_type"] = "unet"

    def _normalize_resolution(self, params: dict[str, Any]) -> None:
        width = self._to_int(params.get("width"))
        height = self._to_int(params.get("height"))
        if width is None or height is None:
            parsed = self._parse_resolution(params.get("resolution"))
            if parsed:
                width, height = parsed
        if width is None or height is None or width <= 0 or height <= 0:
            width, height = 832, 1216
        # NAI rejects any width/height that is not a multiple of 64 (HTTP 500).
        # This is the single chokepoint every headless generation request flows
        # through (AutoRes overrides, manual entry, preset restore, automation,
        # inline fix:WxH), so snap here as a backstop regardless of the source.
        # WEBUI/COMFYUI allow finer steps, so only normalize for NAI.
        if str(params.get("api_mode") or "").strip().upper() == "NAI":
            width, height = snap_resolution_to_multiple(width, height, 64)
        params["width"] = width
        params["height"] = height
        params["resolution"] = f"{width} x {height}"

    def _normalize_numbers(self, params: dict[str, Any], api_mode: str) -> None:
        int_defaults = {
            "steps": 28,
            "width": 832,
            "height": 1216,
        }
        for key, default in int_defaults.items():
            params[key] = self._to_int(params.get(key), default)

        float_defaults = {
            "cfg_scale": 5.0,
            "cfg_rescale": 0.0,
            "hr_scale": 2.0,
            "denoising_strength": 0.5,
            "hr_cfg": 7.0,
        }
        for key, default in float_defaults.items():
            if key in params:
                params[key] = self._to_float(params.get(key), default)

        if params.get("seed_fixed"):
            params["seed"] = self._to_int(params.get("seed"), 0)
        elif api_mode == "NAI":
            params["seed"] = self._to_int(params.get("seed"), None)
            if params["seed"] is None or params["seed"] < 0:
                params["seed"] = random.randint(0, 9_999_999_999)
        elif "seed" in params:
            params["seed"] = self._to_int(params.get("seed"), -1)

    def _normalize_booleans(self, params: dict[str, Any]) -> None:
        for key in (
            "seed_fixed",
            "random_resolution",
            "auto_fit_resolution",
            "prompt_fixed",
            "auto_generate",
            "wildcard_standalone",
            "enable_hr",
            "webui_hiresfix_assist",
            "webui_custom_payload_enabled",
        ):
            if key in params:
                params[key] = self._to_bool(params.get(key))

    def _source_row(self, params: dict[str, Any]) -> pd.Series:
        source_row_data = params.get("_source_row_data")
        if isinstance(source_row_data, dict):
            return pd.Series(
                source_row_data,
                name=str(params.get("_source_name") or "web_headless"),
            )
        if params.get("wildcard_standalone"):
            return pd.Series({
                "general": None,
                "character": None,
                "copyright": None,
                "artist": None,
                "meta": None,
            }, name="wildcard_standalone")
        source_row = self.context.current_source_row
        if isinstance(source_row, pd.Series):
            return source_row
        if isinstance(source_row, dict):
            return pd.Series(source_row)
        return pd.Series({
            "general": None,
            "character": None,
            "copyright": None,
            "artist": None,
            "meta": None,
        }, name="web_headless")

    def _prompt_run_id_for_command(self, command: dict[str, Any], params: dict[str, Any]) -> str:
        explicit = (
            command.get("prompt_run_id")
            or command.get("promptRunId")
            or params.get("prompt_run_id")
            or params.get("promptRunId")
        )
        if explicit:
            return str(explicit)

        current_context = getattr(self.context, "current_prompt_context", None)
        metadata = getattr(current_context, "metadata", {}) if current_context is not None else {}
        current_prompt_run_id = str(metadata.get("prompt_run_id") or "") if isinstance(metadata, dict) else ""
        if not current_prompt_run_id:
            return ""

        current_prompt = str(getattr(current_context, "final_prompt", "") or self.context.prompt_text or "")
        request_prompt = str(params.get("input") or params.get("_raw_input") or "")
        if current_prompt.strip() and current_prompt.strip() == request_prompt.strip():
            return current_prompt_run_id
        return ""

    def merge_conditional_negative(self, negative: str, prompt_run_id: str) -> str:
        """조건부 규칙(neg 타겟)이 프롬프트 런에 기록한 네거티브 조작을 base 네거티브에
        병합한 **문자열**을 반환한다(컨텍스트/네거티브 박스 비오염 — 사본만 다룬다).

        enqueue 합류점(`_apply_conditional_negative`)을 지나지 않고 random 응답의
        네거티브를 직접 소비하는 경로(외부 NAIA Bridge ComfyUI 클라이언트가 자기
        서버에서 생성하는 경우)가 NAIA 자체 생성과 **동일한** 조건부 네거티브를 받도록
        하는 공개 진입점. 내부적으로 `_apply_conditional_negative`와 같은 로직을 재사용해
        set/append 의미·중복 제거·레지스트리 트림 폴백이 한 곳에서만 정의되게 한다.
        조작이 없으면 base 네거티브를 그대로 반환한다(자연 no-op)."""
        params: dict[str, Any] = {"negative_prompt": str(negative or "")}
        self._apply_conditional_negative(params, str(prompt_run_id or ""))
        return str(params.get("negative_prompt") or "")

    def _apply_conditional_negative(self, params: dict[str, Any], prompt_run_id: str) -> None:
        """조건부 규칙(neg 타겟)이 프롬프트 런에 기록한 네거티브 조작을 이 생성에 병합한다.

        desktop(future01)은 네거티브 위젯을 직접 수정 후 생성 완료 시 스냅샷 복원했지만,
        헤드리스는 위젯이 없다. 엔진이 PromptContext.metadata['conditional_negative_ops']에
        기록 → complete_prompt_run이 런 레코드로 승계 → 여기(수동 Generate/Auto Gen/시퀀스·
        이벤트 프리셋/Refine 모두가 지나는 단일 합류점)에서 prompt_run_id 바인딩으로 병합.

        append는 기존 네거티브에 없는 태그만 추가(같은 런 재생성 시 중복 방지), set은 전체
        교체(future01 `neg=` 패리티). 런에 조작이 없으면 no-op. 요청 params 사본에만 반영
        하므로 프론트 네거티브 박스/컨텍스트 상태는 오염되지 않는다.
        """
        ops = self._conditional_negative_ops(prompt_run_id)
        if not ops:
            return
        negative = str(params.get("negative_prompt") or "")
        for op in ops:
            kind = str(op.get("op") or "")
            tags = [str(tag).strip() for tag in (op.get("tags") or []) if str(tag).strip()]
            if kind == "set":
                negative = ", ".join(tags)
            elif kind == "append" and tags:
                existing = {tag.strip() for tag in negative.split(",") if tag.strip()}
                fresh = [tag for tag in tags if tag not in existing]
                if fresh:
                    joined = ", ".join(fresh)
                    negative = f"{negative}, {joined}" if negative.strip() else joined
        params["negative_prompt"] = negative
        params["_conditional_negative_applied"] = True

    def _conditional_negative_ops(self, prompt_run_id: str) -> list[dict[str, Any]]:
        if not prompt_run_id:
            return []
        registry = getattr(self.context, "pipeline_run_registry", None)
        run = registry.get_prompt_run(prompt_run_id) if registry is not None else None
        metadata = getattr(run, "metadata", None)
        if isinstance(metadata, dict):
            ops = metadata.get("conditional_negative_ops")
            if isinstance(ops, list):
                return [op for op in ops if isinstance(op, dict)]
        # 방어: 레지스트리가 없거나 런이 트림된 경우, 현재 컨텍스트가 같은 런이면 직접 읽는다.
        current = getattr(self.context, "current_prompt_context", None)
        current_meta = getattr(current, "metadata", None)
        if isinstance(current_meta, dict) and str(current_meta.get("prompt_run_id") or "") == prompt_run_id:
            ops = current_meta.get("conditional_negative_ops")
            if isinstance(ops, list):
                return [op for op in ops if isinstance(op, dict)]
        return []

    def _create_direct_prompt_run(
        self,
        command: dict[str, Any],
        params: dict[str, Any],
        source_row: pd.Series,
    ) -> str:
        starter = getattr(self.context, "start_prompt_run", None)
        completer = getattr(self.context, "complete_prompt_run", None)
        if not callable(starter) or not callable(completer):
            return ""
        settings = {
            key: value
            for key, value in params.items()
            if key != "credential" and not str(key).startswith("_")
        }
        external_request_id = str(
            command.get("request_id")
            or command.get("requestId")
            or params.get("request_id")
            or params.get("requestId")
            or ""
        )
        run = starter(
            source="direct_generation",
            source_row=source_row,
            settings=settings,
            external_request_id=external_request_id,
            metadata={"direct_generation": True},
        )
        completer(
            run.prompt_run_id,
            final_prompt=str(params.get("input") or ""),
            metadata={
                "prompt_source": "direct_generation",
                "api_mode": params.get("api_mode", ""),
            },
        )
        return run.prompt_run_id

    def _priority(self, command: dict[str, Any]) -> int:
        if self._to_bool(command.get("urgent")):
            return 100
        priority = self._to_int(command.get("priority"), 0)
        return max(0, priority)

    def _extract_nai_data(
        self,
        params: dict[str, Any],
        api_mode: str,
    ) -> tuple[NAICharacterData | None, NAIVibeTransferData | None, NAICharacterReferenceData | None]:
        if api_mode != "NAI":
            return None, None, None
        nai_characters = None
        nai_vibe_transfer = None
        nai_character_reference = None
        try:
            nai_characters = NAICharacterData.from_params(params)
        except Exception:
            nai_characters = None
        try:
            nai_vibe_transfer = NAIVibeTransferData.from_params(params)
        except Exception:
            nai_vibe_transfer = None
        try:
            nai_character_reference = NAICharacterReferenceData.from_params(params)
        except Exception:
            nai_character_reference = None
        return nai_characters, nai_vibe_transfer, nai_character_reference

    @staticmethod
    def _parse_resolution(value: Any) -> tuple[int, int] | None:
        match = re.search(r"(\d+)\s*x\s*(\d+)", str(value or ""), re.IGNORECASE)
        if not match:
            return None
        width = int(match.group(1))
        height = int(match.group(2))
        if width <= 0 or height <= 0:
            return None
        return width, height

    @staticmethod
    def _to_int(value: Any, default: int | None = None) -> int | None:
        try:
            if value is None or value == "":
                return default
            return int(float(value))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_float(value: Any, default: float) -> float:
        try:
            if value is None or value == "":
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off", ""}:
                return False
        return bool(value)


__all__ = ["HeadlessGenerationDispatch", "HeadlessGenerationService"]
