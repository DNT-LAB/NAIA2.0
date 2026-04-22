"""캐릭터 슬롯 복원 통합 검증 (Phase P5).

P2/P3/P4 통합: char_set / char_replace / target=char:N 액션이 트리거되면
snapshot 에 캡처되고, generation_finished 이벤트 시 복원됨을 검증.

설계: docs/CONDITIONAL_CHAR_ACTION_RESTORATION.md
실행: python tests/conditional/test_char_action_restore.py
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

from modules.conditional_prompt_module import (  # noqa: E402
    PromptListModifierModule,
)
from core.prompt_context import PromptContext  # noqa: E402


# ============================================================================
# Mock 인프라 — test_engine_headless 와 호환, 추가로 subscribe + textbox 지원
# ============================================================================


class MockCheckbox:
    def __init__(self, checked=True):
        self._checked = bool(checked)
        self._blocked = False

    def isChecked(self):
        return self._checked

    def setChecked(self, v):
        self._checked = bool(v)

    def blockSignals(self, b):
        prev = self._blocked
        self._blocked = bool(b)
        return prev


class MockTextBox:
    def __init__(self, text=""):
        self._text = text
        self._blocked = False

    def toPlainText(self):
        return self._text

    def setPlainText(self, t):
        self._text = str(t)

    def blockSignals(self, b):
        prev = self._blocked
        self._blocked = bool(b)
        return prev


class MockCharacterWidget:
    def __init__(self, active=True, prompt="", uc=""):
        self.active_checkbox = MockCheckbox(active)
        self.prompt_textbox = MockTextBox(prompt)
        self.uc_textbox = MockTextBox(uc)


class MockCharacterModule:
    def __init__(self, char_widgets, clone_chars=None, clone_uc=None):
        self.character_widgets = char_widgets
        self.modifiable_clone = {
            "characters": list(clone_chars or []),
            "uc": list(clone_uc or []),
        }
        self.hooker_update_called = False

    def get_character_modifiable_clone(self):
        return self.modifiable_clone

    def set_character_active(self, index, active):
        if 0 <= index < len(self.character_widgets):
            self.character_widgets[index].active_checkbox.setChecked(active)
            return True
        return False

    def hooker_update_prompt(self):
        self.hooker_update_called = True


class MockNegativeWidget:
    def __init__(self, text=""):
        self._text = text

    def toPlainText(self):
        return self._text

    def setPlainText(self, t):
        self._text = t


class MockModelCombo:
    def __init__(self, text="NAID4"):
        self._text = text

    def currentText(self):
        return self._text


class MockMainWindow:
    def __init__(self, naid4=True):
        self.negative_prompt_textedit = MockNegativeWidget()
        self.model_combo = MockModelCombo("NAID4" if naid4 else "Other")
        self.search_results = None


class MockMiddleSectionController:
    def __init__(self, char_module):
        self._char_module = char_module

    def get_module_instance(self, name):
        if name == "CharacterModule":
            return self._char_module
        return None


class MockAppContext:
    """publish/subscribe 동작하는 mock context."""

    def __init__(self, char_module):
        self._api_mode = "NAI"
        self.main_window = MockMainWindow(naid4=True)
        self.current_source_row = None
        self.current_prompt_context = None
        self.rating_override = None
        self.middle_section_controller = MockMiddleSectionController(char_module)
        self.published = []
        self._subscribers = {}  # event → list of callbacks

    def get_api_mode(self):
        return self._api_mode

    def publish(self, event, data):
        self.published.append((event, data))
        for cb in self._subscribers.get(event, []):
            try:
                cb(data)
            except Exception as e:
                print(f"  [warn] subscriber raised: {e}")

    def subscribe(self, event, cb):
        self._subscribers.setdefault(event, []).append(cb)


def make_module_with_chars(char_widgets, clone_chars=None, clone_uc=None):
    char_mod = MockCharacterModule(char_widgets, clone_chars, clone_uc)
    ctx = MockAppContext(char_mod)
    mod = PromptListModifierModule()
    mod.initialize_with_context(ctx)  # subscribe 동작 트리거
    return mod, ctx, char_mod


def make_context(prefix=None, main=None, postfix=None):
    return PromptContext(
        source_row=None,
        settings={},
        prefix_tags=list(prefix or []),
        main_tags=list(main or ["1girl"]),
        postfix_tags=list(postfix or []),
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
# Tests — char_set 복원
# ============================================================================


def test_char_set_capture_then_restore():
    """char_set 트리거 → snapshot capture → publish generation_finished → 복원."""
    print("[test_char_set_capture_then_restore]")
    widgets = [
        MockCharacterWidget(active=True, prompt="1girl"),
        MockCharacterWidget(active=True, prompt="1boy"),
    ]
    mod, ctx, cm = make_module_with_chars(widgets)

    rules = "():char_set(2, disabled)"
    pctx = make_context()
    logs = []
    mod._apply_rules(pctx, rules, logs)

    # 액션 결과: 슬롯 2 (idx 1) 비활성화됨
    assert_eq(widgets[1].active_checkbox.isChecked(), False, "after rule: slot 2 disabled")
    # snapshot 에 캡처됨
    assert_true(mod._char_snapshot is not None, "snapshot exists")
    assert_eq(mod._char_snapshot.captured_indices, [1], "captured slot 1 (0-based)")

    # generation_finished 발행 → 복원
    ctx.publish("generation_finished", {"success": True})
    assert_eq(widgets[1].active_checkbox.isChecked(), True, "after restore: slot 2 active again")
    assert_true(mod._char_snapshot is None, "snapshot cleared")


def test_char_set_restore_on_error():
    """generation_error 도 복원 트리거."""
    print("[test_char_set_restore_on_error]")
    widgets = [MockCharacterWidget(active=True), MockCharacterWidget(active=True)]
    mod, ctx, cm = make_module_with_chars(widgets)

    mod._apply_rules(make_context(), "():char_set(1, disabled)", [])
    assert_eq(widgets[0].active_checkbox.isChecked(), False, "slot 1 disabled")

    ctx.publish("generation_error", {"message": "API timeout"})
    assert_eq(widgets[0].active_checkbox.isChecked(), True, "restored on error")


def test_multi_pass_idempotent_capture():
    """같은 슬롯에 여러 char_set → 첫 상태만 보존, 마지막 적용 후 원본으로 복원."""
    print("[test_multi_pass_idempotent_capture]")
    widgets = [MockCharacterWidget(active=True)]
    mod, ctx, cm = make_module_with_chars(widgets)

    # 같은 슬롯을 여러 번 토글하는 룰 (single pass 내)
    rules = (
        "():char_set(1, disabled)\n"
        "():char_set(1, enabled)\n"
        "():char_set(1, disabled)"
    )
    mod._apply_rules(make_context(), rules, [])
    assert_eq(widgets[0].active_checkbox.isChecked(), False, "final state: disabled")

    ctx.publish("generation_finished", {})
    assert_eq(widgets[0].active_checkbox.isChecked(), True, "restored to ORIGINAL active=True")


# ============================================================================
# Tests — char_replace 복원
# ============================================================================


def test_char_replace_clone_restored():
    """char_replace → modifiable_clone 변경 → 복원 시 clone 도 원상."""
    print("[test_char_replace_clone_restored]")
    widgets = [MockCharacterWidget(active=True, prompt="1girl, smile")]
    mod, ctx, cm = make_module_with_chars(
        widgets, clone_chars=["1girl, smile"]
    )

    mod._apply_rules(
        make_context(), "():char_replace(1, smile, grin)", []
    )
    assert_eq(
        cm.modifiable_clone["characters"][0], "1girl, grin",
        "after rule: clone reflects replace",
    )

    ctx.publish("generation_finished", {})
    assert_eq(
        cm.modifiable_clone["characters"][0], "1girl, smile",
        "after restore: clone original",
    )


# ============================================================================
# Tests — target=char:N (write_char_uc_target)
# ============================================================================


def test_target_char_append_restored():
    """target=char:1 + append → clone 변경 → 복원."""
    print("[test_target_char_append_restored]")
    widgets = [MockCharacterWidget(active=True, prompt="1girl")]
    mod, ctx, cm = make_module_with_chars(
        widgets, clone_chars=["1girl"]
    )

    mod._apply_rules(make_context(), "():char:1+=blushing", [])
    assert_eq(
        cm.modifiable_clone["characters"][0], "1girl, blushing",
        "after rule: append applied",
    )

    ctx.publish("generation_finished", {})
    assert_eq(
        cm.modifiable_clone["characters"][0], "1girl",
        "restored to original",
    )


def test_target_uc_replace_restored():
    """target=uc:1 + replace → uc clone 변경 → 복원."""
    print("[test_target_uc_replace_restored]")
    widgets = [MockCharacterWidget(active=True, uc="bad_anatomy")]
    mod, ctx, cm = make_module_with_chars(
        widgets, clone_chars=["1girl"], clone_uc=["bad_anatomy"]
    )

    mod._apply_rules(make_context(), "():uc:1=low_quality", [])
    assert_eq(
        cm.modifiable_clone["uc"][0], "low_quality",
        "after rule: uc replaced",
    )

    ctx.publish("generation_finished", {})
    assert_eq(
        cm.modifiable_clone["uc"][0], "bad_anatomy",
        "restored to original uc",
    )


def test_target_char_wildcard_all_restored():
    """target=char:* → 모든 활성 슬롯 변경 → 모두 복원."""
    print("[test_target_char_wildcard_all_restored]")
    widgets = [
        MockCharacterWidget(active=True, prompt="A"),
        MockCharacterWidget(active=True, prompt="B"),
        MockCharacterWidget(active=False, prompt="C"),  # 비활성
    ]
    mod, ctx, cm = make_module_with_chars(
        widgets, clone_chars=["A", "B", "C"]
    )

    mod._apply_rules(make_context(), "():char:*+=tag", [])
    # 활성 슬롯만 변경됨
    assert_eq(cm.modifiable_clone["characters"][0], "A, tag", "slot 1 appended")
    assert_eq(cm.modifiable_clone["characters"][1], "B, tag", "slot 2 appended")
    assert_eq(cm.modifiable_clone["characters"][2], "C", "slot 3 (inactive) untouched")

    ctx.publish("generation_finished", {})
    assert_eq(cm.modifiable_clone["characters"][0], "A", "slot 1 restored")
    assert_eq(cm.modifiable_clone["characters"][1], "B", "slot 2 restored")
    assert_eq(cm.modifiable_clone["characters"][2], "C", "slot 3 still untouched")


# ============================================================================
# Tests — fallback / leak prevention (R1)
# ============================================================================


def test_leak_recovery_on_next_cycle():
    """generation_finished 누락 시 다음 사이클 진입에서 강제 복원 (R1 fallback).

    슬롯 두 개를 분리 사용해 누수 복원과 새 캡처를 명확히 구분.
    """
    print("[test_leak_recovery_on_next_cycle]")
    widgets = [
        MockCharacterWidget(active=True),  # 슬롯 1 — 사이클 1 대상
        MockCharacterWidget(active=True),  # 슬롯 2 — 사이클 2 대상
    ]
    mod, ctx, cm = make_module_with_chars(widgets)

    # 사이클 1: 슬롯 1 비활성화
    mod._apply_rules(make_context(), "():char_set(1, disabled)", [])
    assert_eq(widgets[0].active_checkbox.isChecked(), False, "C1: slot 1 disabled")
    # generation_finished 발행 안 함 → snapshot 누수
    assert_eq(
        mod._char_snapshot.captured_indices, [0],
        "C1 leaked: snapshot still has slot 0 (idx)",
    )

    # 사이클 2 진입 — 다른 슬롯 (2) 대상. R1 fallback 으로 사이클 1 누수 자동 복원.
    mod._apply_rules(make_context(), "():char_set(2, disabled)", [])
    assert_eq(
        widgets[0].active_checkbox.isChecked(), True,
        "C2 진입: 사이클 1 누수 복원 → 슬롯 1 active 회복",
    )
    assert_eq(
        widgets[1].active_checkbox.isChecked(), False,
        "C2 룰 적용: 슬롯 2 disabled",
    )
    # 사이클 2 의 새 snapshot 은 슬롯 1 (idx) 만 캡처
    assert_eq(
        mod._char_snapshot.captured_indices, [1],
        "C2 fresh snapshot has slot 1 (idx) only",
    )


def test_no_action_no_capture():
    """char 액션 없는 룰 → snapshot 은 빈 채로 fresh 시작."""
    print("[test_no_action_no_capture]")
    widgets = [MockCharacterWidget()]
    mod, ctx, cm = make_module_with_chars(widgets)

    mod._apply_rules(make_context(), "():main+=tag", [])
    assert_true(mod._char_snapshot is not None, "snapshot exists (fresh)")
    assert_eq(mod._char_snapshot.captured_indices, [], "no slots captured")

    ctx.publish("generation_finished", {})
    assert_true(mod._char_snapshot is None, "snapshot cleared after event")


def test_publish_finished_with_empty_snapshot():
    """빈 snapshot 상태에서 generation_finished → 안전하게 no-op."""
    print("[test_publish_finished_with_empty_snapshot]")
    mod, ctx, cm = make_module_with_chars([MockCharacterWidget()])
    # 어떠한 _apply_rules 도 호출 안 됨 → snapshot is None
    ctx.publish("generation_finished", {})
    assert_true(mod._char_snapshot is None, "still None")


# ============================================================================
# Runner
# ============================================================================


def main():
    tests = [
        test_char_set_capture_then_restore,
        test_char_set_restore_on_error,
        test_multi_pass_idempotent_capture,
        test_char_replace_clone_restored,
        test_target_char_append_restored,
        test_target_uc_replace_restored,
        test_target_char_wildcard_all_restored,
        test_leak_recovery_on_next_cycle,
        test_no_action_no_capture,
        test_publish_finished_with_empty_snapshot,
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
