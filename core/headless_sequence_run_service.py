"""Headless Sequence continuous-run controller.

Run-policy state machine (mirrors ``HeadlessStorytellerService`` /
``HeadlessAutomationService``) for Auto-Gen-driven continuous Sequence generation.
A "round" = one event group's frames. Pressing Random/Generate starts a run; under
Auto Gen, when a round completes and the queue drains, the generation runner picks the
next random matching group and starts a fresh round (fresh freeze). This controller owns
ONLY the run STATE + guards; the freeze/assemble/enqueue work lives in
``app/backend/server/sequence_preset_routes.py`` (core must not depend on app/).

Sequence does NOT engage/disengage the Auto Gen toggle — it reads the user's live
``auto_generate`` option. With Auto Gen OFF, a Random/Generate is a one-shot round.
"""
from __future__ import annotations

import uuid
from typing import Any


class HeadlessSequenceRunService:
    def __init__(self, context: Any):
        self.context = context

    # ----------------------------------------------------------------- state
    def _state(self) -> dict[str, Any] | None:
        st = getattr(self.context, "sequence_run_state", None)
        return st if isinstance(st, dict) else None

    def state(self) -> dict[str, Any]:
        st = self._state()
        running = bool(st and st.get("is_running"))
        total = int(st.get("total_frames") or 0) if st else 0
        completed = int(st.get("completed_count") or 0) if st else 0
        return self.context._module_state_payload("sequence_run", {
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
            return "시퀀스 연속 생성이 이미 실행 중입니다. 정지한 뒤 다시 시도하세요."
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
        return f"sequence-run-{uuid.uuid4().hex}"

    def begin(self, *, run_id: str, query: dict[str, Any], group_id: int, total_frames: int,
              auto_gen: bool) -> str:
        """첫 라운드 시작 — run 상태 생성. 호출부(라우트)가 run_id 로 freeze+enqueue 한 뒤 호출."""
        self.context.sequence_run_state = {
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
        }
        return run_id

    def begin_round(self, run_id: str, *, group_id: int, total_frames: int) -> None:
        """다음 라운드(자동 연속) — 카운터 리셋 + 새 그룹/총프레임."""
        st = self._runtime_for(run_id)
        if st is None:
            return
        st["group_id"] = int(group_id)
        st["last_group_id"] = int(group_id)
        st["total_frames"] = int(total_frames)
        st["completed_count"] = 0
        st["round_count"] = int(st.get("round_count") or 0) + 1

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
                messages.append(toast("시퀀스 연속 생성을 마쳤습니다.", level="success"))
            elif reason == "stopped":
                messages.append(toast("시퀀스 연속 생성을 정지했습니다.", level="info"))
            elif reason == "error":
                messages.append(toast("시퀀스 연속 생성이 오류로 정지됐습니다.", level="error"))
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
