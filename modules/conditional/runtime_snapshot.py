"""CharStateSnapshot — 조건부 룰 적용 전 캐릭터 슬롯 상태 보존.

설계 문서: `docs/CONDITIONAL_CHAR_ACTION_RESTORATION.md` (Phase P1)

목적
====
조건부 v2 의 char 계열 액션 (`char_set`, `char_replace`, `target=char:N`,
`target=uc:N`) 이 트리거되면 일부는 widget 을 직접 수정하거나 (영구),
일부는 modifiable_clone 만 수정한다 (휘발). 사용자 멘탈 모델은 "이번
generate 에 효과 적용, 다음 generate 부터 원복" 이지만 widget 수정 경로는
영구 변경이라 사이클 간 누수가 발생.

본 클래스는 액션 실행 직전 영향 슬롯의 widget + clone 상태를 캡처하고,
generate 종료 후 복원함으로써 모든 char 계열 액션을 ephemeral 로 통일한다.

사용법
======
    snap = CharStateSnapshot(char_module)
    snap.capture(0)            # 슬롯 0 변경 직전 호출 (idempotent)
    # ... 액션 실행 (widget / clone 변경) ...
    snap.restore()             # generation_finished 시점에 일괄 복원
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class CharSlotSnapshot:
    """단일 캐릭터 슬롯의 변경 전 상태."""
    index: int                          # 0-based widget index
    active: bool                        # active_checkbox.isChecked()
    prompt_text: str                    # widget.prompt_textbox 원본
    uc_text: str                        # widget.uc_textbox 원본
    clone_prompt: Optional[str]         # modifiable_clone['characters'][i]
    clone_uc: Optional[str]             # modifiable_clone['uc'][i]


class CharStateSnapshot:
    """캐릭터 슬롯 상태 스냅샷 — capture(idempotent) + restore(blockSignals).

    `char_module` 가 None 이면 모든 동작이 no-op (테스트/헤드리스 안전).
    """

    def __init__(self, char_module):
        self._cm = char_module
        self._captured: Dict[int, CharSlotSnapshot] = {}

    # ------------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------------

    def is_empty(self) -> bool:
        return not self._captured

    @property
    def captured_indices(self) -> List[int]:
        return sorted(self._captured.keys())

    # ------------------------------------------------------------------
    # capture
    # ------------------------------------------------------------------

    def capture(self, index: int) -> bool:
        """슬롯 index 의 현재 상태를 캡처 (idempotent — 첫 호출만 효력).

        Returns:
            True  — 캡처 성공 또는 이미 캡처됨
            False — char_module None / 인덱스 범위 밖 / widget 접근 실패
        """
        if self._cm is None:
            return False
        if index in self._captured:
            return True  # idempotent — 첫 상태 보존
        widgets = getattr(self._cm, "character_widgets", None) or []
        if index < 0 or index >= len(widgets):
            return False
        w = widgets[index]

        active = self._safe_get_active(w)
        prompt_text = self._safe_get_text(w, "prompt_textbox")
        uc_text = self._safe_get_text(w, "uc_textbox")
        clone_prompt, clone_uc = self._safe_get_clone(index)

        self._captured[index] = CharSlotSnapshot(
            index=index,
            active=active,
            prompt_text=prompt_text,
            uc_text=uc_text,
            clone_prompt=clone_prompt,
            clone_uc=clone_uc,
        )
        return True

    # ------------------------------------------------------------------
    # restore
    # ------------------------------------------------------------------

    def restore(self) -> int:
        """캡처된 모든 슬롯을 원상태로 복원. 복원 시 시그널 차단.

        - 캡처 후 슬롯이 제거됐으면 해당 항목은 건너뜀
        - widget 의 prompt/uc 가 사용자에 의해 변경된 경우도 무조건 원본으로
          되돌림 (R3 — 차후 정책 변경 가능). 현재는 단순 일관성 우선.
        - 호출 후 내부 캡처 dict 는 비워짐 (다음 사이클 깨끗하게 시작)

        Returns:
            실제로 복원된 슬롯 수 (제거된 슬롯 제외)
        """
        if self._cm is None or not self._captured:
            self._captured.clear()
            return 0
        widgets = getattr(self._cm, "character_widgets", None) or []
        restored = 0
        for idx, snap in list(self._captured.items()):
            if idx >= len(widgets):
                continue
            w = widgets[idx]
            self._restore_active(w, snap.active)
            self._restore_text(w, "prompt_textbox", snap.prompt_text)
            self._restore_text(w, "uc_textbox", snap.uc_text)
            self._restore_clone(idx, snap.clone_prompt, snap.clone_uc)
            restored += 1
        self._captured.clear()
        return restored

    # ------------------------------------------------------------------
    # internal — capture helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_get_active(widget) -> bool:
        try:
            chk = getattr(widget, "active_checkbox", None)
            return bool(chk.isChecked()) if chk is not None else False
        except Exception:
            return False

    @staticmethod
    def _safe_get_text(widget, attr: str) -> str:
        try:
            tb = getattr(widget, attr, None)
            if tb is None:
                return ""
            return tb.toPlainText()
        except Exception:
            return ""

    def _safe_get_clone(self, index: int):
        clone = getattr(self._cm, "modifiable_clone", None)
        if not isinstance(clone, dict):
            return None, None
        chars = clone.get("characters") or []
        ucs = clone.get("uc") or []
        cp = chars[index] if 0 <= index < len(chars) else None
        cu = ucs[index] if 0 <= index < len(ucs) else None
        return cp, cu

    # ------------------------------------------------------------------
    # internal — restore helpers (모두 시그널 차단 적용)
    # ------------------------------------------------------------------

    @staticmethod
    def _restore_active(widget, active: bool) -> None:
        chk = getattr(widget, "active_checkbox", None)
        if chk is None:
            return
        try:
            chk.blockSignals(True)
            chk.setChecked(active)
        except Exception:
            pass
        finally:
            try:
                chk.blockSignals(False)
            except Exception:
                pass

    @staticmethod
    def _restore_text(widget, attr: str, text: str) -> None:
        tb = getattr(widget, attr, None)
        if tb is None:
            return
        try:
            tb.blockSignals(True)
            current = tb.toPlainText()
            if current != text:
                tb.setPlainText(text)
        except Exception:
            pass
        finally:
            try:
                tb.blockSignals(False)
            except Exception:
                pass

    def _restore_clone(
        self,
        index: int,
        clone_prompt: Optional[str],
        clone_uc: Optional[str],
    ) -> None:
        clone = getattr(self._cm, "modifiable_clone", None)
        if not isinstance(clone, dict):
            return
        if clone_prompt is not None:
            chars = clone.setdefault("characters", [])
            if 0 <= index < len(chars):
                chars[index] = clone_prompt
        if clone_uc is not None:
            ucs = clone.setdefault("uc", [])
            if 0 <= index < len(ucs):
                ucs[index] = clone_uc
