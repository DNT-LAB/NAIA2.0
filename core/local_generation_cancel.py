"""로컬 생성(외부 ComfyUI · 내장 ANIMA) 중단 — 지금 도는 생성 **한 장만** 멈춘다(사용자 제보 2026-11-10).

흐름
  1. 러너가 요청 하나를 실행할 때 손잡이(:class:`CancelHandle`)를 만들고(:meth:`LocalGenerationCancelRegistry.begin`)
     그 실행 스레드에 묶는다(:func:`run_bound`).
  2. ``POST /api/generation/cancel`` → :func:`cancel_local_generation` 이 손잡이의 Event 를 세운다.
  3. ComfyUIService 는 기다리는 동안 그 Event 를 보고, 세워지면 **자기 prompt_id 만** 정리한다
     (돌고 있으면 interrupt · 큐에서 기다리는 중이면 삭제). 남의 작업 · 큐에 쌓인 다른 Generate 는 건드리지 않는다.
  4. 결과는 오류가 아니라 ``{'status': 'cancelled'}`` 다 → execute_request 가 :class:`GenerationCancelled` 로 올리고
     러너가 '중단' 으로 처리한다(오류 토스트 · 자동 재시도 · Auto Gen 연속 실패 수에 넣지 않는다).

손잡이는 요청마다 새로 만든다 — 늦게 온 중단이 **다음** 장을 멈추지 않는다.
멈출 수 있는 모드는 COMFYUI(내장 ANIMA 도 credential 만 다른 COMFYUI)뿐이다. NAI 는 보낸 요청을 서버에서 되돌릴 길이 없고,
WebUI 의 /sdapi/v1/interrupt 는 남의 작업까지 멈추는 전역 중단이라 넣지 않았다 — 둘 다 '못 멈춘다' 고 답만 한다.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

CANCELLABLE_MODES = frozenset({"COMFYUI"})
CANCELLED_MESSAGE = "생성을 중단했습니다"


class GenerationCancelled(Exception):
    """사용자가 지금 도는 로컬 생성을 멈췄다 — 실패가 아니다(러너가 오류와 따로 처리한다)."""


class CancelHandle:
    """요청 하나의 중단 손잡이. ``event`` 는 실행 스레드가 기다리는 동안 본다."""

    def __init__(self, request_id: str, api_mode: str, request: Any = None):
        self.request_id = str(request_id or "")
        self.api_mode = str(api_mode or "").upper()
        self.request = request          # queue_state 의 active 요약을 만든다(headless_session_state_service)
        self.event = threading.Event()

    @property
    def cancellable(self) -> bool:
        return self.api_mode in CANCELLABLE_MODES

    @property
    def cancelled(self) -> bool:
        return self.event.is_set()

    def wait(self, seconds: float) -> bool:
        """seconds 만큼 쉬되 중단되면 곧바로 깬다. 중단됐으면 True."""
        return self.event.wait(max(0.0, float(seconds)))


_bound = threading.local()


def current_handle() -> CancelHandle | None:
    """이 스레드가 실행 중인 러너 요청의 손잡이. 러너 밖(스튜디오 · 확장 · 프리플라이트 등)에서 부른 생성이면 None."""
    return getattr(_bound, "handle", None)


def run_bound(handle: CancelHandle | None, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """``func`` 를 이 스레드에 손잡이를 묶은 채 실행한다(러너가 asyncio.to_thread 로 부른다)."""
    previous = getattr(_bound, "handle", None)
    _bound.handle = handle
    try:
        return func(*args, **kwargs)
    finally:
        _bound.handle = previous


class LocalGenerationCancelRegistry:
    """세션 하나에 하나 — 러너가 지금 실행 중인 요청의 손잡이를 쥔다(러너는 한 번에 한 장만 돈다).

    '지금 도는 장' 의 단일 출처이기도 하다 — queue_state 의 ``active`` (Queue 패널 · 이 장을 멈출 수 있는가)가 여기서 나온다."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: CancelHandle | None = None

    def begin(self, request_id: str, api_mode: str, request: Any = None) -> CancelHandle:
        handle = CancelHandle(request_id, api_mode, request)
        with self._lock:
            self._active = handle
        return handle

    def end(self, handle: CancelHandle | None) -> None:
        with self._lock:
            if self._active is handle:
                self._active = None

    def reset(self) -> None:
        """러너가 끝날 때 — 남은 손잡이를 비운다(손잡이를 세운 뒤 실행 전에 넘어진 경우)."""
        with self._lock:
            self._active = None

    def active(self) -> CancelHandle | None:
        with self._lock:
            return self._active

    def cancel(self, request_id: str | None = None) -> dict[str, Any]:
        """지금 도는 장을 멈추라고 표시한다. 도는 것이 없거나 멈출 수 없는 모드면 아무것도 하지 않는다.

        ``request_id`` 를 주면 **그 장이 지금 도는 장일 때만** 멈춘다(reason ``not_running`` 으로 거절) — A 가 끝나고 B 가
        막 시작된 순간의 누름이 B 를 멈추지 않게(Queue 패널의 Stop 은 자기가 그린 장의 id 를 싣는다). 없으면 지금 도는 장을
        멈춘다(하위 호환)."""
        wanted = str(request_id or "").strip()
        with self._lock:
            handle = self._active
            if handle is None:
                return {"ok": True, "accepted": False, "reason": "idle",
                        "message": "지금 도는 생성이 없습니다."}
            if wanted and handle.request_id != wanted:
                return {"ok": True, "accepted": False, "reason": "not_running", "request_id": wanted,
                        "message": "그 생성은 이미 끝났습니다."}
            if not handle.cancellable:
                return {"ok": True, "accepted": False, "reason": "unsupported_mode",
                        "api_mode": handle.api_mode, "request_id": handle.request_id,
                        "message": _unsupported_message(handle.api_mode)}
            already = handle.cancelled
            handle.event.set()
        if not already:
            print(f"[CANCEL] local generation stop requested id={handle.request_id[:8]} mode={handle.api_mode}",
                  flush=True)
        return {"ok": True, "accepted": True, "reason": "already_requested" if already else "requested",
                "api_mode": handle.api_mode, "request_id": handle.request_id,
                "message": "중단을 요청했습니다."}


def _unsupported_message(api_mode: str) -> str:
    if api_mode == "NAI":
        return "NAI 생성은 중단할 수 없습니다 - 이미 보낸 요청은 서버에서 끝까지 갑니다."
    if api_mode == "WEBUI":
        return "WebUI 생성은 아직 중단을 지원하지 않습니다."
    return f"{api_mode or '이'} 모드의 생성은 중단할 수 없습니다."


_registry_lock = threading.Lock()


def registry_for(context: Any) -> LocalGenerationCancelRegistry:
    """세션 컨텍스트에 붙은 레지스트리(처음 부를 때 만든다)."""
    registry = getattr(context, "_local_generation_cancel", None)
    if isinstance(registry, LocalGenerationCancelRegistry):
        return registry
    with _registry_lock:
        registry = getattr(context, "_local_generation_cancel", None)
        if not isinstance(registry, LocalGenerationCancelRegistry):
            registry = LocalGenerationCancelRegistry()
            setattr(context, "_local_generation_cancel", registry)
        return registry


def cancel_local_generation(context: Any, request_id: str | None = None) -> dict[str, Any]:
    """``POST /api/generation/cancel`` 의 본체. 결과(중단 처리 · 다음 큐 진행)는 러너가 WS 로 알린다.
    ``request_id`` 가 있으면 그 장이 지금 도는 장일 때만 멈춘다(LocalGenerationCancelRegistry.cancel)."""
    return registry_for(context).cancel(request_id)
