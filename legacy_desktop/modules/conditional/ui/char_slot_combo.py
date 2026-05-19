"""캐릭터 슬롯 선택용 콤보박스.

규칙 액션 (`char:N`/`uc:N` 타겟, `char_set`/`char_replace`) 에서 단순한
QSpinBox 대신 사용한다. 드롭다운을 열 때마다 CharacterModule 의 현재
슬롯 상태를 조회해 각 항목에 1줄 요약(첫 태그 또는 "(비어있음)") 을
표시한다.

저장된 슬롯 번호가 현재 슬롯 범위를 벗어나면 (예: 캐릭터를 줄인 뒤
규칙을 불러옴) 해당 번호를 임시 항목으로 유지해 round-trip data loss
를 막는다.
"""

from __future__ import annotations

from typing import Callable, List, Optional, Tuple

from PyQt6.QtWidgets import QComboBox, QWidget

from legacy_desktop.ui.scaling_manager import get_scaled_size

# 각 항목: (slot_n_1based, summary_text, is_active)
SlotInfo = Tuple[int, str, bool]


def get_character_slots(app_context) -> List[SlotInfo]:
    """CharacterModule 에서 현재 슬롯 상태를 추출.

    실패 시 빈 리스트 반환 (콤보 측에서 fallback 처리).
    """
    if app_context is None:
        return []
    controller = getattr(app_context, "middle_section_controller", None)
    if controller is None:
        return []
    try:
        cm = controller.get_module_instance("CharacterModule")
    except Exception:
        cm = None
    if cm is None:
        return []
    widgets = getattr(cm, "character_widgets", None) or []

    out: List[SlotInfo] = []
    for i, w in enumerate(widgets):
        slot_n = i + 1
        # active_checkbox 가 없거나 호출 실패해도 죽지 않게 방어.
        active = False
        try:
            chk = getattr(w, "active_checkbox", None)
            if chk is not None:
                active = bool(chk.isChecked())
        except Exception:
            active = False

        prompt_text = ""
        try:
            tb = getattr(w, "prompt_textbox", None)
            if tb is not None:
                prompt_text = tb.toPlainText().strip()
        except Exception:
            prompt_text = ""

        if not prompt_text:
            summary = "(비어있음)"
        else:
            first = prompt_text.split(",")[0].strip()
            summary = first if len(first) <= 28 else first[:25] + "..."

        out.append((slot_n, summary, active))
    return out


class CharSlotComboBox(QComboBox):
    """캐릭터 슬롯 1-based 인덱스 콤보.

    Args:
        get_slots: () -> List[SlotInfo]. 드롭다운 열기 직전마다 호출.
    """

    def __init__(
        self,
        get_slots: Callable[[], List[SlotInfo]],
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._get_slots = get_slots
        # 프로젝트 관례: 콤보는 휠 스크롤로 값 변경 차단.
        self.wheelEvent = lambda e: e.ignore()
        # 슬롯 요약 최소폭 — 선택된 항목은 좁을 수 있지만 드롭다운을 열면
        # showPopup 이 view 폭을 자동 확장해 전체 텍스트가 표시된다.
        # 220px 은 부모 row 에서 타 레이블/체크박스를 밀어내는 문제가 있어 축소.
        self.setMinimumWidth(get_scaled_size(110))
        self.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContentsOnFirstShow
        )
        # 최소한 한 번 채워두어 sizing/initial value 가 안전하게 잡히도록.
        self._refresh_items(initial=True)

    # ------------------------------------------------------------------
    # 외부 API — 기존 spinbox 와 호환되는 정수 read/write
    # ------------------------------------------------------------------

    def value(self) -> int:
        v = self.currentData()
        try:
            return int(v) if v is not None else 0
        except (TypeError, ValueError):
            return 0

    def setValue(self, n: int) -> None:
        try:
            n_int = max(1, int(n))
        except (TypeError, ValueError):
            n_int = 1
        idx = self.findData(n_int)
        if idx < 0:
            # 저장된 값이 현재 슬롯 범위 밖 → 보존용 임시 항목 추가
            self.addItem(f"{n_int}: (슬롯 없음)", userData=n_int)
            idx = self.findData(n_int)
        if idx >= 0:
            self.setCurrentIndex(idx)

    # ------------------------------------------------------------------
    # 내부 — 항목 갱신
    # ------------------------------------------------------------------

    def showPopup(self):  # noqa: N802 (Qt API name)
        self._refresh_items(initial=False)
        # 가장 긴 항목 텍스트에 맞춰 popup view 폭을 자동 조정.
        # 콤보 본체 폭(setMinimumWidth 220px) 은 그대로 두고, 펼쳤을 때만
        # 슬롯 미리보기가 elide 되지 않도록 view 만 넓힌다.
        fm = self.fontMetrics()
        max_w = 0
        for i in range(self.count()):
            w = fm.horizontalAdvance(self.itemText(i))
            if w > max_w:
                max_w = w
        if max_w > 0:
            # padding + 스크롤바 여유
            self.view().setMinimumWidth(max_w + get_scaled_size(40))
        super().showPopup()

    def _refresh_items(self, *, initial: bool) -> None:
        keep = self.value() if not initial else 0
        self.blockSignals(True)
        try:
            self.clear()
            slots = self._get_slots() or []
            for n, summary, active in slots:
                marker = "" if active else "  · 비활성"
                self.addItem(f"{n}: {summary}{marker}", userData=int(n))
            if not slots:
                # CharacterModule 미연결 (테스트/헤드리스) → 1~10 fallback
                for n in range(1, 11):
                    self.addItem(f"{n}: (캐릭터 모듈 없음)", userData=n)
            # 저장된 값이 사라진 슬롯이면 보존용 항목으로 다시 추가
            if keep and self.findData(keep) < 0:
                self.addItem(f"{keep}: (슬롯 없음)", userData=int(keep))
            # 선택 복원
            if keep:
                idx = self.findData(keep)
                if idx >= 0:
                    self.setCurrentIndex(idx)
            elif self.count() > 0:
                self.setCurrentIndex(0)
        finally:
            self.blockSignals(False)
