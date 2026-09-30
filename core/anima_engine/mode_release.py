"""ANIMA 모드를 떠나면 RELEASE_DELAY 초 뒤 관리형 엔진(내장 ComfyUI)을 내려 GPU · 메모리를 돌려준다(사용자 지정 09-30).

ANIMA 모드 = 생성 모드 COMFYUI + 엔진 선택 managed. 떠나는 길은 셋이다 - 모드 전환(NAI · WEBUI, api_mode_changed) ·
엔진 전환(메인 셀렉트의 COMFYUI, AnimaEngineService.select) · COMFYUI 연결 해제(엔진 선택도 지운다, clear_api).
기다리는 동안 ANIMA 로 돌아오면 취소한다.

때가 되면 켜진 엔진만 내리고, 쓰는 중이면 다 쓸 때까지 기다린다: 켜는 중 · ComfyUI 큐에 일이 있다 · NAIA 큐에 ANIMA
요청이 남았다(요청은 넣을 때의 엔진을 쥔다 - 모드를 바꿔도 관리형 엔진으로 돈다) · 보내고 받는 중(runtime.in_use) ·
마지막으로 쓴 뒤 RELEASE_DELAY 초가 안 지났다. 마지막 판정과 내리기는 runtime.stop_if_unused 가 in_use 와 같은
자물쇠 안에서 한다 - 그 사이 들어온 생성은 내린 뒤에 들어가 엔진을 다시 켠다(쓰는 중에 내리지 않는다).

내렸으면 RELEASED_EVENT 를 알린다 - headless_routes 의 브릿지가 화면 토스트로 보낸다. 엔진을 켜지는 않는다.
"""
from __future__ import annotations

from pathlib import Path
from threading import Event, Lock, Thread

from . import integration
from .runtime import REGISTRY, REGISTRY_LOCK
from .settings import load_settings

RELEASE_DELAY = 10.0     # 떠난 뒤(쓰는 중이었으면 다 쓴 뒤) 기다리는 초 - 사용자 지정
BUSY_POLL = 2.0          # 쓰는 중이면 이만큼씩 다시 본다
RELEASED_EVENT = "anima_engine_released"
RELEASED_MESSAGE = "ANIMA 엔진을 종료해 GPU · 메모리를 반환했습니다 (다음 ANIMA 생성 때 다시 켭니다)."

_LOCK = Lock()


def anima_active(context):
    """지금 ANIMA 모드인가 - 생성 모드 COMFYUI + 엔진 선택 managed. 못 읽으면 아니다(부르는 쪽을 막지 않는다)."""
    try:
        getter = getattr(context, "get_api_mode", None)
        mode = getter() if callable(getter) else getattr(context, "current_api_mode", "")
        return str(mode or "").strip().upper() == "COMFYUI" and integration.managed_selected(context)
    except Exception:
        return False


def _registered_runtime(context):
    """이 NAIA 가 만든 런타임 - 찾기만 한다(없으면 켠 엔진이 없다)."""
    settings = load_settings(integration.save_root_of(context))
    if not settings.engine_root:
        return None
    with REGISTRY_LOCK:
        return REGISTRY.get(str(Path(settings.engine_root).resolve()))


def _queued_managed(context):
    """NAIA 큐에 ANIMA(관리형 엔진) 요청이 남았나."""
    requests = getattr(getattr(context, "generation_queue_manager", None), "get_all_requests", None)
    if not callable(requests):
        return False
    return any(integration.is_managed_credential((getattr(request, "params", None) or {}).get("credential"))
               for request in requests())


class ModeRelease:
    """NAIA 하나(context)의 반환 예약 - 모드 · 엔진 전환이 changed(떠나기 전 ANIMA 였나, 지금 ANIMA 인가) 로 알린다."""

    def __init__(self, context, *, delay=RELEASE_DELAY, poll=BUSY_POLL):
        self.context, self.delay, self.poll = context, delay, poll
        self._lock = Lock()
        self._cancel = None          # 기다리는 예약의 Event - 없으면 예약 없음

    def changed(self, was_active, now_active):
        if now_active:
            self.cancel()            # 돌아왔다
        elif was_active:
            self.schedule()          # 떠났다

    def schedule(self):
        with self._lock:
            if self._cancel is not None:
                self._cancel.set()   # 앞 예약은 거두고 새로 센다
            cancel = self._cancel = Event()
        Thread(target=self._run, args=(cancel,), daemon=True, name="anima-mode-release").start()

    def cancel(self):
        with self._lock:
            if self._cancel is not None:
                self._cancel.set()
                self._cancel = None

    def pending(self):
        with self._lock:
            return self._cancel is not None

    def _run(self, cancel):
        try:
            if not cancel.wait(self.delay):
                self._release(cancel)
        except Exception as exc:     # 못 내려도 서버는 그대로 - 쉬는 동안 타이머(idle_minutes)가 뒤를 맡는다
            print(f"ANIMA: mode release failed - {ascii(str(exc))}", flush=True)
        finally:
            with self._lock:
                if self._cancel is cancel:
                    self._cancel = None

    def _release(self, cancel):
        while not cancel.is_set() and not anima_active(self.context):
            rt = _registered_runtime(self.context)
            state = rt.status()["state"] if rt is not None else "stopped"
            if state not in ("running", "starting"):
                return               # 켜진 엔진이 없다 - 돌려줄 것도 알릴 것도 없다
            busy = state == "starting" or _queued_managed(self.context) or rt.queue_busy()
            if not busy and not cancel.is_set() and rt.stop_if_unused(quiet=self.delay):
                print("ANIMA: engine released after leaving ANIMA mode", flush=True)
                publish = getattr(self.context, "publish", None)
                if callable(publish):
                    publish(RELEASED_EVENT, {"message": RELEASED_MESSAGE, "level": "info"})
                return
            cancel.wait(self.poll)


def release_for(context):
    with _LOCK:
        release = getattr(context, "_anima_mode_release", None)
        if release is None:
            release = context._anima_mode_release = ModeRelease(context)
        return release


def note(context, was_active):
    """모드 전환 밖에서 ANIMA 가 꺼지고 켜지는 곳(엔진 선택 · COMFYUI 연결 해제)이 부른다 - was_active = 바꾸기 전의
    anima_active. 예약이 실패해도 부른 일(엔진 선택 · 연결 해제)은 그대로 끝난다."""
    try:
        release_for(context).changed(was_active, anima_active(context))
    except Exception as exc:
        print(f"ANIMA: mode release note failed - {ascii(str(exc))}", flush=True)


def watch(context):
    """모드 전환(api_mode_changed)을 듣는다 - 서버를 만들 때 한 번(anima_engine_routes)."""
    subscribe = getattr(context, "subscribe", None)
    if not callable(subscribe) or getattr(context, "_anima_mode_release_watching", False):
        return
    context._anima_mode_release_watching = True

    def on_mode_changed(data):
        try:
            data = data if isinstance(data, dict) else {}
            managed = integration.managed_selected(context)      # 모드만 바뀌었다 - 엔진 선택은 그대로
            was = str(data.get("old_mode") or "").strip().upper() == "COMFYUI" and managed
            now = str(data.get("new_mode") or "").strip().upper() == "COMFYUI" and managed
            release_for(context).changed(was, now)
        except Exception as exc:  # 모드 전환은 막지 않는다
            print(f"ANIMA: mode release watch failed - {ascii(str(exc))}", flush=True)

    subscribe("api_mode_changed", on_mode_changed)
