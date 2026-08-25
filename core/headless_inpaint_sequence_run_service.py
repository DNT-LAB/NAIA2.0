"""Headless I.Sequence (Inpaint Sequence) continuous-run controller.

⚠️ 이것은 ``HeadlessSequenceRunService`` 의 **복제본**이다(사용자 지정 2026-08-25).
   그쪽은 프레임마다 독립 t2i 로 내고 정체성(freeze)으로만 잉는다. 이쪽은
   직전 이미지를 캔버스에 붙이고 빈 절반을 inpaint 로 메꾸는 **캔버스 연쇄**를
   몹표로 한다(원본 `C:/VNR/NAIA2.0/tabs/turbo_event_sequence` 의 방식).
   이번 단계는 **복제까지**다 - 생성 방식 교체는 다음 단계에서 한다.

이벤트 그룹 검색/다운로드는 `SequencePresetService` 를 **공유**한다 - 같은
데이터셋이라 띄울 이유가 없다. 따로 가지는 것은 런 상태뿐이다.

둘은 동시에 돌 수 없다(공용 EventStreamRuntime · 단일 생성 큐) - `guard_can_start`
가 서로를 교차로 막는다.
"""
from __future__ import annotations

import uuid
from typing import Any


class HeadlessInpaintSequenceRunService:
    def __init__(self, context: Any):
        self.context = context

    # ----------------------------------------------------------------- state
    def _state(self) -> dict[str, Any] | None:
        st = getattr(self.context, "inpaint_sequence_run_state", None)
        return st if isinstance(st, dict) else None

    def state(self) -> dict[str, Any]:
        st = self._state()
        running = bool(st and st.get("is_running"))
        total = int(st.get("total_frames") or 0) if st else 0
        completed = int(st.get("completed_count") or 0) if st else 0
        return self.context._module_state_payload("inpaint_sequence_run", {
            "available": True,
            "runtime": "web",
            "is_running": running,
            "run_id": str(st.get("run_id") or "") if st else "",
            "group_id": int(st.get("group_id") or 0) if st else 0,
            "total_frames": total,
            "completed_count": completed,
            "remaining_count": max(0, total - completed) if running else 0,
            "round_count": int(st.get("round_count") or 0) if st else 0,
            "auto_gen": bool(st.get("auto_gen")) if st else False,
            "status": self._status_text(st),
        })

    def set_param(self, key: str, value: Any) -> dict[str, Any] | None:
        if key == "stop":
            return self.stop()
        return None

    # ----------------------------------------------------------------- guards
    def guard_can_start(self) -> str:
        """빈 문자열=시작 가능, 아니면 거부 사유. 단일 Auto Gen 루프/공유 EventStream 충돌 방지."""
        if self.is_running():
            return "I.Sequence 연속 생성이 이미 실행 중입니다. 정지한 뒤 다시 시도하세요."
        # ⚠️ 일반 Sequence 와 **동시에 못 돌린다.** 둘 다 공용 EventStreamRuntime 을 무장해
        #    freeze 를 뜨고 같은 생성 큐 하나를 쓴다 - 겹치면 서로의 freeze 를 짓밟고
        #    완료 신호를 서로의 것으로 센다. 그쪽의 `is_active` 는 라운드 사이에 꺼져
        #    있어 아래 EventStream 검사로는 안 잡힌다 - 런 상태를 직접 본다.
        if self.context._sequence_run_service().is_running():
            return "Sequence 연속 생성이 실행 중입니다. 정지한 뒤 시도하세요."
        es = getattr(self.context, "event_stream_runtime", None)
        if (es is not None and getattr(es, "is_active", False)) \
                or self.context._storyteller_service().is_running():
            return "Event Stream / Storyteller가 실행 중입니다. 먼저 정지한 뒤 시도하세요."
        if self.context._automation_service().is_running():
            return "Automation이 실행 중입니다. 정지한 뒤 시도하세요."
        if getattr(self.context, "is_generating", False):
            return "생성이 진행 중입니다. 완료된 뒤 시도하세요."
        queue = getattr(self.context, "generation_queue_manager", None)
        if queue is not None and (queue.is_paused() or not queue.is_empty()):
            return "생성 큐가 비어있지 않습니다. 큐를 비운 뒤 시도하세요."
        return ""

    # ----------------------------------------------------------------- lifecycle
    @staticmethod
    def new_run_id() -> str:
        return f"inpaint-sequence-run-{uuid.uuid4().hex}"

    def begin(self, *, run_id: str, query: dict[str, Any], group_id: int, total_frames: int,
              auto_gen: bool, use_vibe: bool = False) -> str:
        """첫 라운드 시작 — run 상태 생성. 호출부(라우트)가 run_id 로 freeze+enqueue 한 뒤 호출.

        ``use_vibe`` (Vibe 사용, NAI 전용): 라운드의 첫 프레임을 인코딩해 나머지 프레임에
        임시 vibe 로 적용하는 의향(공존 시 기존 vibe RS 는 절반으로 감소). 실제 인코딩 문자열은
        라운드마다 첫 이미지 생성 완료 시 러너가 채운다(set_vibe_encoding) — 라운드 경계에서
        리셋돼 매 라운드 새로 인코딩한다."""
        self.context.inpaint_sequence_run_state = {
            "run_id": run_id,
            "is_running": True,
            "auto_gen": bool(auto_gen),
            "query": dict(query) if isinstance(query, dict) else {},
            "group_id": int(group_id),
            "last_group_id": int(group_id),
            "total_frames": int(total_frames),
            "completed_count": 0,
            "round_count": 1,
            "finish_reason": "",
            # Vibe 사용(1회성 라운드 vibe) — 의향 + 현재 라운드 인코딩(첫 이미지 완료 후 채워짐).
            "use_vibe": bool(use_vibe),
            "vibe_encoding": "",
            "vibe_model": "",
        }
        return run_id

    def begin_round(self, run_id: str, *, group_id: int, total_frames: int) -> None:
        """다음 라운드(자동 연속) — 카운터 리셋 + 새 그룹/총프레임. 라운드마다 vibe 인코딩을
        리셋해 새 라운드의 첫 이미지를 다시 인코딩한다(fresh freeze 와 동일한 라운드 경계 규칙)."""
        st = self._runtime_for(run_id)
        if st is None:
            return
        st["group_id"] = int(group_id)
        st["last_group_id"] = int(group_id)
        st["total_frames"] = int(total_frames)
        st["completed_count"] = 0
        st["round_count"] = int(st.get("round_count") or 0) + 1
        st["vibe_encoding"] = ""
        st["vibe_model"] = ""

    def record_generation_completed(self, run_id: str) -> dict[str, Any]:
        """프레임 1장 완료 기록. round_done=이 라운드의 전 프레임 완료."""
        st = self._runtime_for(run_id)
        if st is None:
            return {"round_done": False, "messages": []}
        st["completed_count"] = int(st.get("completed_count") or 0) + 1
        round_done = st["completed_count"] >= int(st.get("total_frames") or 0)
        return {"round_done": round_done, "messages": []}

    def finish(self, run_id: str, *, reason: str = "complete") -> dict[str, Any]:
        st = self._state()
        if st and str(st.get("run_id") or "") == str(run_id or ""):
            st["is_running"] = False
            st["finish_reason"] = reason
        # 방어적 disarm — 정체성은 프레임 params 에 baking 됐으므로 freeze 는 떠 있을 이유 없음.
        es = getattr(self.context, "event_stream_runtime", None)
        if es is not None:
            try:
                es.stop()
            except Exception:
                pass
        messages: list[dict[str, Any]] = []
        toast = getattr(self.context, "_toast", None)
        if callable(toast):
            if reason == "complete":
                messages.append(toast("I.Sequence 연속 생성을 마쳤습니다.", level="success"))
            elif reason == "stopped":
                messages.append(toast("I.Sequence 연속 생성을 정지했습니다.", level="info"))
            elif reason == "error":
                messages.append(toast("I.Sequence 연속 생성이 오류로 정지됐습니다.", level="error"))
        return {"continue": False, "messages": messages}

    def stop(self) -> dict[str, Any]:
        st = self._state()
        if not st or not st.get("is_running"):
            return self.state()
        policy = self.finish(str(st.get("run_id") or ""), reason="stopped")
        state = self.state()
        state["_headless_extra_messages"] = policy.get("messages", [])
        return state

    # ----------------------------------------------------------------- inspectors
    def is_running(self, run_id: str | None = None) -> bool:
        st = self._state()
        if not st or not st.get("is_running"):
            return False
        return not run_id or str(st.get("run_id") or "") == str(run_id)

    def active_run_id(self) -> str:
        st = self._state()
        if not st or not st.get("is_running"):
            return ""
        return str(st.get("run_id") or "")

    def query(self, run_id: str) -> dict[str, Any]:
        st = self._runtime_for(run_id)
        return dict(st.get("query") or {}) if st else {}

    def last_group_id(self, run_id: str):
        st = self._runtime_for(run_id)
        return st.get("last_group_id") if st else None

    def auto_gen(self, run_id: str) -> bool:
        st = self._runtime_for(run_id)
        return bool(st.get("auto_gen")) if st else False

    # --------------------------------------------------------------- Vibe 사용
    def wants_vibe(self, run_id: str) -> bool:
        """이 런이 Vibe 사용 의향이 있는지(체크박스 ON). NAI 게이트는 러너/라우트가 별도로 본다."""
        st = self._runtime_for(run_id)
        return bool(st.get("use_vibe")) if st else False

    def set_vibe_encoding(self, run_id: str, encoding: str, model: str) -> None:
        """현재 라운드의 첫 이미지 인코딩을 보관(러너가 첫 프레임 완료 후 1회 호출)."""
        st = self._runtime_for(run_id)
        if st is None:
            return
        st["vibe_encoding"] = str(encoding or "")
        st["vibe_model"] = str(model or "")

    def vibe_injection(self, run_id: str) -> dict[str, Any] | None:
        """현재 라운드에 적용할 vibe ``{encoding, model}`` (아직 인코딩 전이면 None)."""
        st = self._runtime_for(run_id)
        if not st:
            return None
        encoding = str(st.get("vibe_encoding") or "")
        if not encoding:
            return None
        return {"encoding": encoding, "model": str(st.get("vibe_model") or "")}

    # ----------------------------------------------------------------- helpers
    def _runtime_for(self, run_id: str) -> dict[str, Any] | None:
        st = self._state()
        if not st or not st.get("is_running"):
            return None
        if str(st.get("run_id") or "") != str(run_id or ""):
            return None
        return st

    @staticmethod
    def _status_text(st: dict[str, Any] | None) -> str:
        if st and st.get("is_running"):
            return (f"Running · round {int(st.get('round_count') or 0)} "
                    f"({int(st.get('completed_count') or 0)}/{int(st.get('total_frames') or 0)})")
        reason = str(st.get("finish_reason") or "") if st else ""
        return {"complete": "Complete", "stopped": "Stopped",
                "error": "Stopped after error"}.get(reason, "")
