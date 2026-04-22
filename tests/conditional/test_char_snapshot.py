"""CharStateSnapshot — capture/restore 단위 검증 (Phase P1).

설계 문서: docs/CONDITIONAL_CHAR_ACTION_RESTORATION.md

실행: python tests/conditional/test_char_snapshot.py
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Qt headless setup (모듈이 PyQt6 임포트하지는 않지만 일관성 유지)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

from modules.conditional.runtime_snapshot import (  # noqa: E402
    CharSlotSnapshot,
    CharStateSnapshot,
)


# ============================================================================
# Mock 인프라 — NAID4CharacterInput / CharacterModule 호환 최소 구현
# ============================================================================


class MockCheckbox:
    def __init__(self, checked: bool = True):
        self._checked = checked
        self._signals_blocked = False
        # blockSignals=False 상태에서 setChecked 가 몇 번 호출됐는지 카운트
        self.signal_emit_count = 0

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, v: bool) -> None:
        self._checked = bool(v)
        if not self._signals_blocked:
            self.signal_emit_count += 1

    def blockSignals(self, b: bool) -> bool:
        prev = self._signals_blocked
        self._signals_blocked = bool(b)
        return prev


class MockTextBox:
    def __init__(self, text: str = ""):
        self._text = text
        self._signals_blocked = False
        self.set_call_count = 0

    def toPlainText(self) -> str:
        return self._text

    def setPlainText(self, t: str) -> None:
        self._text = str(t)
        self.set_call_count += 1

    def blockSignals(self, b: bool) -> bool:
        prev = self._signals_blocked
        self._signals_blocked = bool(b)
        return prev


class MockCharWidget:
    def __init__(self, active: bool = True, prompt: str = "1girl", uc: str = ""):
        self.active_checkbox = MockCheckbox(active)
        self.prompt_textbox = MockTextBox(prompt)
        self.uc_textbox = MockTextBox(uc)


class MockCharModule:
    def __init__(self, widgets, clone=None):
        self.character_widgets = widgets
        self.modifiable_clone = (
            clone if clone is not None else {"characters": [], "uc": []}
        )


# ============================================================================
# Assert helpers
# ============================================================================


def assert_eq(actual, expected, label):
    if actual != expected:
        raise AssertionError(
            f"{label}\n    expected={expected!r}\n    actual=  {actual!r}"
        )
    print(f"  [OK] {label}")


def assert_true(cond, label):
    if not cond:
        raise AssertionError(f"{label}: assertion failed")
    print(f"  [OK] {label}")


# ============================================================================
# Tests
# ============================================================================


def test_none_module():
    """char_module=None → capture/restore 모두 no-op (헤드리스 안전)."""
    print("[test_none_module]")
    snap = CharStateSnapshot(None)
    assert_eq(snap.capture(0), False, "capture returns False for None module")
    assert_eq(snap.restore(), 0, "restore returns 0 for None module")
    assert_eq(snap.is_empty(), True, "snapshot empty")


def test_basic_capture_restore():
    """단일 슬롯 capture → 변경 → restore 사이클."""
    print("[test_basic_capture_restore]")
    w0 = MockCharWidget(active=True, prompt="1girl, blue_hair", uc="bad_anatomy")
    cm = MockCharModule([w0])
    snap = CharStateSnapshot(cm)

    snap.capture(0)
    assert_eq(snap.captured_indices, [0], "captured index 0")

    # conditional 액션이 widget 변경한 것을 시뮬레이션
    w0.active_checkbox.setChecked(False)
    w0.prompt_textbox.setPlainText("2girls")
    w0.uc_textbox.setPlainText("low_quality")

    n = snap.restore()
    assert_eq(n, 1, "restored 1 slot")
    assert_eq(w0.active_checkbox.isChecked(), True, "active restored to True")
    assert_eq(w0.prompt_textbox.toPlainText(), "1girl, blue_hair", "prompt restored")
    assert_eq(w0.uc_textbox.toPlainText(), "bad_anatomy", "uc restored")
    assert_eq(snap.is_empty(), True, "post-restore: snapshot cleared")


def test_idempotent_capture():
    """같은 슬롯 2회 capture → 첫 상태만 보존."""
    print("[test_idempotent_capture]")
    w0 = MockCharWidget(active=True, prompt="ORIGINAL")
    cm = MockCharModule([w0])
    snap = CharStateSnapshot(cm)

    snap.capture(0)
    # 두 번째 capture 직전에 상태 변경 — 두 번째 capture 는 무시되어야
    w0.prompt_textbox.setPlainText("CHANGED")
    snap.capture(0)
    snap.restore()
    assert_eq(
        w0.prompt_textbox.toPlainText(), "ORIGINAL",
        "first capture state preserved",
    )


def test_out_of_range_capture():
    """범위 밖 인덱스 capture → False, 항목 미생성."""
    print("[test_out_of_range_capture]")
    cm = MockCharModule([MockCharWidget()])
    snap = CharStateSnapshot(cm)
    assert_eq(snap.capture(5), False, "capture(5) returns False")
    assert_eq(snap.capture(-1), False, "capture(-1) returns False")
    assert_eq(snap.is_empty(), True, "no entry created")


def test_signals_blocked_on_restore():
    """restore 시 widget.blockSignals(True) 적용 — connected slot 미트리거."""
    print("[test_signals_blocked_on_restore]")
    w0 = MockCharWidget(active=True)
    cm = MockCharModule([w0])
    snap = CharStateSnapshot(cm)

    snap.capture(0)
    # 룰이 토글 (signal fire)
    w0.active_checkbox.setChecked(False)
    pre_signals = w0.active_checkbox.signal_emit_count

    snap.restore()
    post_signals = w0.active_checkbox.signal_emit_count
    assert_eq(
        post_signals, pre_signals,
        "restore did not emit signals (blocked)",
    )
    assert_eq(w0.active_checkbox.isChecked(), True, "value still restored")


def test_clone_restore():
    """modifiable_clone['characters'][i] 와 ['uc'][i] 모두 복원."""
    print("[test_clone_restore]")
    w0 = MockCharWidget(active=True, prompt="A")
    clone = {"characters": ["A"], "uc": ["bad_uc"]}
    cm = MockCharModule([w0], clone)
    snap = CharStateSnapshot(cm)

    snap.capture(0)
    cm.modifiable_clone["characters"][0] = "MODIFIED_PROMPT"
    cm.modifiable_clone["uc"][0] = "MODIFIED_UC"

    snap.restore()
    assert_eq(
        cm.modifiable_clone["characters"][0], "A",
        "clone characters[0] restored",
    )
    assert_eq(
        cm.modifiable_clone["uc"][0], "bad_uc",
        "clone uc[0] restored",
    )


def test_slot_removed_after_capture():
    """capture 후 슬롯이 제거된 케이스 → restore 가 해당 슬롯 건너뜀."""
    print("[test_slot_removed_after_capture]")
    w0 = MockCharWidget()
    w1 = MockCharWidget()
    cm = MockCharModule([w0, w1])
    snap = CharStateSnapshot(cm)

    snap.capture(1)
    cm.character_widgets = [w0]  # 슬롯 1 제거 시뮬레이션
    n = snap.restore()
    assert_eq(n, 0, "removed slot not counted as restored")
    assert_eq(snap.is_empty(), True, "snapshot cleared regardless")


def test_multiple_slots():
    """여러 슬롯 capture → 캡처된 슬롯만 복원, 나머지는 무영향."""
    print("[test_multiple_slots]")
    widgets = [
        MockCharWidget(active=True, prompt=f"slot{i}") for i in range(3)
    ]
    cm = MockCharModule(widgets)
    snap = CharStateSnapshot(cm)

    snap.capture(0)
    snap.capture(2)
    # 모든 슬롯 변경
    for w in widgets:
        w.active_checkbox.setChecked(False)
        w.prompt_textbox.setPlainText("MUTATED")

    n = snap.restore()
    assert_eq(n, 2, "restored 2 captured slots")
    assert_eq(widgets[0].active_checkbox.isChecked(), True, "slot 0 active restored")
    assert_eq(widgets[0].prompt_textbox.toPlainText(), "slot0", "slot 0 prompt restored")
    assert_eq(widgets[1].active_checkbox.isChecked(), False, "slot 1 untouched (not captured)")
    assert_eq(widgets[1].prompt_textbox.toPlainText(), "MUTATED", "slot 1 untouched")
    assert_eq(widgets[2].active_checkbox.isChecked(), True, "slot 2 active restored")
    assert_eq(widgets[2].prompt_textbox.toPlainText(), "slot2", "slot 2 prompt restored")


def test_unchanged_text_no_setplaintext():
    """변경 없는 텍스트 복원 시 setPlainText 호출 회피 (불필요한 cursor 점프 방지)."""
    print("[test_unchanged_text_no_setplaintext]")
    w0 = MockCharWidget(prompt="UNCHANGED")
    cm = MockCharModule([w0])
    snap = CharStateSnapshot(cm)

    snap.capture(0)
    pre_count = w0.prompt_textbox.set_call_count  # 0
    snap.restore()
    post_count = w0.prompt_textbox.set_call_count
    assert_eq(post_count, pre_count, "setPlainText skipped when text unchanged")


def test_empty_restore():
    """capture 없이 restore → 0 반환, 안전."""
    print("[test_empty_restore]")
    cm = MockCharModule([MockCharWidget()])
    snap = CharStateSnapshot(cm)
    assert_eq(snap.restore(), 0, "empty restore returns 0")
    assert_eq(snap.is_empty(), True, "still empty")


# ============================================================================
# Runner
# ============================================================================


def main():
    tests = [
        test_none_module,
        test_basic_capture_restore,
        test_idempotent_capture,
        test_out_of_range_capture,
        test_signals_blocked_on_restore,
        test_clone_restore,
        test_slot_removed_after_capture,
        test_multiple_slots,
        test_unchanged_text_no_setplaintext,
        test_empty_restore,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            print(f"  [FAIL] {e}")
            failed += 1
    print("\n" + "=" * 60)
    print(
        f"Total: {len(tests)} | Passed: {len(tests) - failed} | Failed: {failed}"
    )
    sys.exit(failed)


if __name__ == "__main__":
    main()
