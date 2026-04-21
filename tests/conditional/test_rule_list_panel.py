"""RuleListPanel 테스트 (3-pane 중앙 패널).

검증:
- set_rulebook 이 priority 순으로 렌더 + "N. ● [단일][추가] ..." 포맷
- set_selected_rule 프로그램 호출 시 시그널 억제 + 요약 라벨 갱신
- 시그널: rule_selected / rule_add / rule_delete / rule_enabled_toggle /
  rule_move_up / rule_move_down
- 버튼 상태: 선택 없음 / 첫 행 / 마지막 행 / 활성 상태별 텍스트
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from modules.conditional.block_model import (  # noqa: E402
    Action,
    Rule,
    RuleBook,
    make_tag_leaf,
)
from modules.conditional.ui.rule_list_panel import RuleListPanel  # noqa: E402


def _rule(priority: int, *, name: str = "", enabled: bool = True) -> Rule:
    return Rule(
        kind="block",
        enabled=enabled,
        priority=priority,
        name=name,
        condition=make_tag_leaf("x"),
        action=Action(kind="append_list", target="main", tags=["y"]),
    )


class _Spy:
    def __init__(self):
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args if len(args) != 1 else args[0])


# ============================================================================
# 렌더링
# ============================================================================


class TestRuleListRender:
    def test_renders_rules_sorted_by_priority(self):
        p = RuleListPanel()
        book = RuleBook(rules=[
            _rule(30, name="c"),
            _rule(10, name="a"),
            _rule(20, name="b"),
        ])
        p.set_rulebook(book)
        assert p._rule_list.count() == 3
        assert p._rule_list.item(0).text().startswith("1. ● [단일][추가]")
        assert p._rule_list.item(1).text().startswith("2. ● [단일][추가]")
        assert p._rule_list.item(2).text().startswith("3. ● [단일][추가]")

    def test_summary_uses_order_prefix(self):
        p = RuleListPanel()
        p.set_rulebook(RuleBook(rules=[_rule(42, name="foo")]))
        text = p._rule_list.item(0).text()
        assert text.startswith("1. ● [단일][추가]")
        assert "[0042]" not in text

    def test_summary_truncates_long_tag(self):
        long_tag = "x" * 200
        r = Rule(
            kind="block",
            priority=0,
            condition=make_tag_leaf(long_tag),
            action=Action(kind="append_list", target="main", tags=["y"]),
        )
        p = RuleListPanel()
        p.set_rulebook(RuleBook(rules=[r]))
        text = p._rule_list.item(0).text()
        assert "..." in text

    def test_disabled_rule_shows_circle(self):
        p = RuleListPanel()
        p.set_rulebook(RuleBook(rules=[_rule(10, enabled=False)]))
        text = p._rule_list.item(0).text()
        assert text.startswith("1. ○")

    def test_raw_rule_badge(self):
        p = RuleListPanel()
        r = Rule(kind="raw", priority=10, raw_dsl="(x):y=z")
        p.set_rulebook(RuleBook(rules=[r]))
        text = p._rule_list.item(0).text()
        assert "[고급][DSL]" in text

    def test_empty_rulebook(self):
        p = RuleListPanel()
        p.set_rulebook(RuleBook())
        assert p._rule_list.count() == 0

    def test_none_rulebook(self):
        p = RuleListPanel()
        p.set_rulebook(None)
        assert p._rule_list.count() == 0


# ============================================================================
# 시그널
# ============================================================================


class TestRuleListSignals:
    def test_rule_selected_emits_index(self):
        p = RuleListPanel()
        p.set_rulebook(RuleBook(rules=[_rule(10), _rule(20)]))
        spy = _Spy()
        p.rule_selected.connect(spy)
        p._rule_list.setCurrentRow(1)
        assert 1 in spy.calls

    def test_rule_add_requested(self):
        p = RuleListPanel()
        spy = _Spy()
        p.rule_add_requested.connect(lambda: spy())
        p.rule_add_requested.emit()
        assert len(spy.calls) == 1

    def test_rule_delete_requested(self):
        p = RuleListPanel()
        p.set_rulebook(RuleBook(rules=[_rule(10), _rule(20)]))
        p._rule_list.setCurrentRow(0)
        spy = _Spy()
        p.rule_delete_requested.connect(spy)
        p._on_rule_delete_clicked()
        assert spy.calls == [0]

    def test_rule_delete_ignored_without_selection(self):
        p = RuleListPanel()
        p.set_rulebook(RuleBook(rules=[_rule(10)]))
        p._rule_list.clearSelection()
        p._rule_list.setCurrentRow(-1)
        spy = _Spy()
        p.rule_delete_requested.connect(spy)
        p._on_rule_delete_clicked()
        assert spy.calls == []

    def test_rule_toggle_requested(self):
        p = RuleListPanel()
        p.set_rulebook(RuleBook(rules=[_rule(10), _rule(20, enabled=False)]))
        p._rule_list.setCurrentRow(1)
        spy = _Spy()
        p.rule_enabled_toggle_requested.connect(spy)
        p._on_rule_toggle_enabled_clicked()
        assert spy.calls == [1]

    def test_rule_move_up_requested(self):
        p = RuleListPanel()
        p.set_rulebook(RuleBook(rules=[_rule(10), _rule(20)]))
        p._rule_list.setCurrentRow(1)
        spy = _Spy()
        p.rule_move_up_requested.connect(spy)
        p._on_rule_move_up_clicked()
        assert spy.calls == [1]

    def test_rule_move_down_requested(self):
        p = RuleListPanel()
        p.set_rulebook(RuleBook(rules=[_rule(10), _rule(20)]))
        p._rule_list.setCurrentRow(0)
        spy = _Spy()
        p.rule_move_down_requested.connect(spy)
        p._on_rule_move_down_clicked()
        assert spy.calls == [0]

    def test_rule_move_up_ignored_on_first_row(self):
        p = RuleListPanel()
        p.set_rulebook(RuleBook(rules=[_rule(10), _rule(20)]))
        p._rule_list.setCurrentRow(0)
        spy = _Spy()
        p.rule_move_up_requested.connect(spy)
        p._on_rule_move_up_clicked()
        assert spy.calls == []

    def test_rule_move_down_ignored_on_last_row(self):
        p = RuleListPanel()
        p.set_rulebook(RuleBook(rules=[_rule(10), _rule(20)]))
        p._rule_list.setCurrentRow(1)
        spy = _Spy()
        p.rule_move_down_requested.connect(spy)
        p._on_rule_move_down_clicked()
        assert spy.calls == []


# ============================================================================
# 버튼 상태
# ============================================================================


class TestRuleButtonState:
    def test_no_selection_disables_all(self):
        p = RuleListPanel()
        p.set_rulebook(RuleBook(rules=[_rule(10), _rule(20)]))
        # 초기 상태 (QListWidget 선택 없음)
        p._rule_list.clearSelection()
        p._rule_list.setCurrentRow(-1)
        assert p._toggle_enabled_btn.isEnabled() is False
        assert p._move_up_btn.isEnabled() is False
        assert p._move_down_btn.isEnabled() is False

    def test_first_row_disables_move_up(self):
        p = RuleListPanel()
        p.set_rulebook(RuleBook(rules=[_rule(10), _rule(20), _rule(30)]))
        p._rule_list.setCurrentRow(0)
        assert p._move_up_btn.isEnabled() is False
        assert p._move_down_btn.isEnabled() is True

    def test_last_row_disables_move_down(self):
        p = RuleListPanel()
        p.set_rulebook(RuleBook(rules=[_rule(10), _rule(20), _rule(30)]))
        p._rule_list.setCurrentRow(2)
        assert p._move_up_btn.isEnabled() is True
        assert p._move_down_btn.isEnabled() is False

    def test_toggle_text_reflects_enabled_state(self):
        p = RuleListPanel()
        p.set_rulebook(RuleBook(rules=[_rule(10, enabled=True)]))
        p._rule_list.setCurrentRow(0)
        assert p._toggle_enabled_btn.text() == "선택 규칙 끄기"
        p.set_rulebook(RuleBook(rules=[_rule(10, enabled=False)]))
        p._rule_list.setCurrentRow(0)
        assert p._toggle_enabled_btn.text() == "선택 규칙 켜기"


# ============================================================================
# set_selected_rule
# ============================================================================


class TestSetSelectedRule:
    def test_programmatic_select_does_not_emit(self):
        p = RuleListPanel()
        p.set_rulebook(RuleBook(rules=[_rule(10), _rule(20)]))
        spy = _Spy()
        p.rule_selected.connect(spy)
        p.set_selected_rule(1)
        assert spy.calls == []
        assert p._rule_list.currentRow() == 1
        assert p._rule_list.item(1).isSelected() is True
        assert p._toggle_enabled_btn.text() == "선택 규칙 끄기"

    def test_out_of_range_clears(self):
        p = RuleListPanel()
        p.set_rulebook(RuleBook(rules=[_rule(10)]))
        p.set_selected_rule(99)
        assert p._rule_list.selectedItems() == []

    def test_get_selected_rule_index(self):
        p = RuleListPanel()
        p.set_rulebook(RuleBook(rules=[_rule(10), _rule(20)]))
        p._rule_list.setCurrentRow(1)
        assert p.get_selected_rule_index() == 1


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
