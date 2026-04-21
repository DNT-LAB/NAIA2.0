"""PresetPanel 테스트 (Sub-phase 1.4d).

검증:
- set_presets / set_rulebook / set_selected_rule / engine_options 왕복
- 시그널 발행: load / save / delete / rule_selected / rule_add / rule_delete /
  engine_options_changed
- 번들 프리셋 선택 시 delete 버튼 비활성
- 더블클릭 → 로드 시그널
- Rule 리스트 표시 (priority 정렬 + summary)
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
from modules.conditional.preset_io import PresetInfo  # noqa: E402
from modules.conditional.ui.preset_panel import PresetPanel  # noqa: E402


def _pi(name: str, *, bundled: bool = False, rule_count: int = 0):
    return PresetInfo(
        name=name,
        path=Path(f"/tmp/{name}.json"),
        description=f"desc {name}",
        is_bundled=bundled,
        rule_count=rule_count,
    )


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
# 프리셋 리스트
# ============================================================================


class TestPresetList:
    def test_renders_bundled_and_user(self):
        p = PresetPanel()
        p.set_presets(
            [
                _pi("b1", bundled=True, rule_count=3),
                _pi("u1", bundled=False, rule_count=2),
            ]
        )
        assert p._preset_list.count() == 2
        assert "📦" in p._preset_list.item(0).text()
        assert "b1" in p._preset_list.item(0).text()
        assert "📄" in p._preset_list.item(1).text()

    def test_tooltip_from_description(self):
        p = PresetPanel()
        p.set_presets([_pi("x", bundled=False)])
        assert "desc x" in p._preset_list.item(0).toolTip()

    def test_empty(self):
        p = PresetPanel()
        p.set_presets([])
        assert p._preset_list.count() == 0
        assert p.get_selected_preset_name() is None


class TestPresetSignals:
    def _setup(self):
        p = PresetPanel()
        p.set_presets([
            _pi("bundle", bundled=True),
            _pi("mypreset", bundled=False),
        ])
        return p

    def test_load_by_button(self):
        p = self._setup()
        spy = _Spy()
        p.preset_load_requested.connect(spy)
        p._preset_list.setCurrentRow(1)  # mypreset
        p._on_load_clicked()
        assert spy.calls == ["mypreset"]

    def test_load_by_double_click(self):
        p = self._setup()
        spy = _Spy()
        p.preset_load_requested.connect(spy)
        p._preset_list.setCurrentRow(0)
        p._on_preset_double_clicked(None)
        assert spy.calls == ["bundle"]

    def test_save_emits_selected_name(self):
        p = self._setup()
        spy = _Spy()
        p.preset_save_requested.connect(spy)
        p._preset_list.setCurrentRow(1)
        p._on_save_clicked()
        assert spy.calls == ["mypreset"]

    def test_save_empty_when_no_selection(self):
        p = self._setup()
        spy = _Spy()
        p.preset_save_requested.connect(spy)
        p._preset_list.clearSelection()
        p._preset_list.setCurrentRow(-1)
        p._on_save_clicked()
        # 미선택 → 빈 이름 발행 (상위에서 다이얼로그로 처리)
        assert spy.calls == [""]

    def test_delete_user_preset(self):
        p = self._setup()
        spy = _Spy()
        p.preset_delete_requested.connect(spy)
        p._preset_list.setCurrentRow(1)  # user
        p._on_delete_clicked()
        assert spy.calls == ["mypreset"]

    def test_delete_bundled_ignored(self):
        p = self._setup()
        spy = _Spy()
        p.preset_delete_requested.connect(spy)
        p._preset_list.setCurrentRow(0)  # bundle
        p._on_delete_clicked()
        # 번들은 삭제 시그널 발행 안함 (방어)
        assert spy.calls == []

    def test_delete_button_disabled_for_bundle(self):
        p = self._setup()
        p._preset_list.setCurrentRow(0)
        assert not p._delete_btn.isEnabled()
        p._preset_list.setCurrentRow(1)
        assert p._delete_btn.isEnabled()


# ============================================================================
# Rule 리스트
# ============================================================================


class TestRuleList:
    def test_renders_rules_sorted_by_priority(self):
        p = PresetPanel()
        book = RuleBook(rules=[
            _rule(30, name="c"),
            _rule(10, name="a"),
            _rule(20, name="b"),
        ])
        p.set_rulebook(book)
        assert p._rule_list.count() == 3
        # sorted_rules 로 정렬되므로 a/b/c 순
        assert "a" in p._rule_list.item(0).text()
        assert "b" in p._rule_list.item(1).text()
        assert "c" in p._rule_list.item(2).text()

    def test_summary_includes_priority_prefix(self):
        p = PresetPanel()
        p.set_rulebook(RuleBook(rules=[_rule(42, name="foo")]))
        text = p._rule_list.item(0).text()
        assert "[0042]" in text  # zero-padded

    def test_summary_truncates_long_dsl(self):
        long_tag = "x" * 200
        r = Rule(
            kind="block",
            priority=0,
            condition=make_tag_leaf(long_tag),
            action=Action(kind="append_list", target="main", tags=["y"]),
        )
        p = PresetPanel()
        p.set_rulebook(RuleBook(rules=[r]))
        text = p._rule_list.item(0).text()
        assert "..." in text

    def test_empty_rulebook(self):
        p = PresetPanel()
        p.set_rulebook(RuleBook())
        assert p._rule_list.count() == 0

    def test_none_rulebook(self):
        p = PresetPanel()
        p.set_rulebook(None)
        assert p._rule_list.count() == 0


class TestRuleSignals:
    def test_rule_selected_emits_index(self):
        p = PresetPanel()
        p.set_rulebook(RuleBook(rules=[_rule(10), _rule(20)]))
        spy = _Spy()
        p.rule_selected.connect(spy)
        p._rule_list.setCurrentRow(1)
        assert 1 in spy.calls

    def test_rule_add_requested(self):
        p = PresetPanel()
        spy = _Spy()
        p.rule_add_requested.connect(lambda: spy())
        p.rule_add_requested.emit()
        assert len(spy.calls) == 1

    def test_rule_delete_requested(self):
        p = PresetPanel()
        p.set_rulebook(RuleBook(rules=[_rule(10), _rule(20)]))
        p._rule_list.setCurrentRow(0)
        spy = _Spy()
        p.rule_delete_requested.connect(spy)
        p._on_rule_delete_clicked()
        assert spy.calls == [0]

    def test_rule_delete_ignored_without_selection(self):
        p = PresetPanel()
        p.set_rulebook(RuleBook(rules=[_rule(10)]))
        p._rule_list.clearSelection()
        p._rule_list.setCurrentRow(-1)
        spy = _Spy()
        p.rule_delete_requested.connect(spy)
        p._on_rule_delete_clicked()
        assert spy.calls == []


# ============================================================================
# Engine options
# ============================================================================


class TestEngineOptions:
    def test_defaults(self):
        p = PresetPanel()
        opts = p.get_engine_options()
        assert opts == {"max_passes": 1, "stop_on_match": False}

    def test_set_and_get(self):
        p = PresetPanel()
        p.set_engine_options({"max_passes": 5, "stop_on_match": True})
        assert p.get_engine_options() == {
            "max_passes": 5, "stop_on_match": True,
        }

    def test_set_clamps_min(self):
        p = PresetPanel()
        p.set_engine_options({"max_passes": 0, "stop_on_match": False})
        assert p.get_engine_options()["max_passes"] == 1

    def test_set_rulebook_syncs_options(self):
        p = PresetPanel()
        book = RuleBook(max_passes=7, stop_on_match=True)
        p.set_rulebook(book)
        assert p.get_engine_options() == {
            "max_passes": 7, "stop_on_match": True,
        }

    def test_change_emits_signal(self):
        p = PresetPanel()
        spy = _Spy()
        p.engine_options_changed.connect(spy)
        p._max_passes_spin.setValue(3)
        assert spy.calls  # dict 객체
        last = spy.calls[-1]
        assert last["max_passes"] == 3

    def test_set_engine_options_is_silent(self):
        p = PresetPanel()
        spy = _Spy()
        p.engine_options_changed.connect(spy)
        p.set_engine_options({"max_passes": 2, "stop_on_match": True})
        assert spy.calls == []


# ============================================================================
# set_selected_rule
# ============================================================================


class TestSetSelectedRule:
    def test_programmatic_select_does_not_emit(self):
        p = PresetPanel()
        p.set_rulebook(RuleBook(rules=[_rule(10), _rule(20)]))
        spy = _Spy()
        p.rule_selected.connect(spy)
        p.set_selected_rule(1)
        # set_selected_rule 은 시그널 억제 (프로그램 호출)
        assert spy.calls == []
        assert p._rule_list.currentRow() == 1

    def test_out_of_range_clears(self):
        p = PresetPanel()
        p.set_rulebook(RuleBook(rules=[_rule(10)]))
        p.set_selected_rule(99)
        assert p._rule_list.currentRow() == -1 or not p._rule_list.selectedItems()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
