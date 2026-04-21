"""RulePanel 테스트 (Sub-phase 1.4c).

검증:
- block/raw Rule 왕복
- 5 action kind (append_list / append / replace / char_set / char_replace)
- target fixed / char:N / uc:N / char:* / uc:*
- priority / name / enabled / kind 필드 왕복
- visibility 토글이 action kind / target kind 변화에 따라 정확
- changed 시그널 (사용자 편집 시만)
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
    ConditionNode,
    Rule,
    make_and_group,
    make_char_in_leaf,
    make_rating_leaf,
    make_tag_leaf,
)
from modules.conditional.ui.rule_panel import RulePanel  # noqa: E402


class _Counter:
    def __init__(self):
        self.count = 0

    def __call__(self, *_):
        self.count += 1


# ============================================================================
# 메타 필드 왕복
# ============================================================================


class TestMetaRoundtrip:
    def test_default(self):
        p = RulePanel()
        r = p.get_rule()
        assert r.enabled is True  # Rule 기본값
        assert r.priority == 100
        assert r.name == ""
        assert r.kind == "block"

    def test_disabled(self):
        p = RulePanel(Rule(enabled=False, name="off"))
        r = p.get_rule()
        assert r.enabled is False
        assert r.name == "off"

    def test_priority(self):
        p = RulePanel(Rule(priority=42))
        assert p.get_rule().priority == 42

    def test_name_strip(self):
        p = RulePanel()
        p._name_edit.setText("  spaced  ")
        assert p.get_rule().name == "spaced"


# ============================================================================
# Block action 왕복 — 5 종
# ============================================================================


class TestAppendList:
    def test_main_simple(self):
        rule = Rule(
            kind="block",
            condition=make_tag_leaf("blush"),
            action=Action(
                kind="append_list", target="main", tags=["smile", "happy"]
            ),
        )
        p = RulePanel(rule)
        r = p.get_rule()
        assert r.action.kind == "append_list"
        assert r.action.target == "main"
        assert r.action.tags == ["smile", "happy"]

    def test_char_n_target(self):
        rule = Rule(
            kind="block",
            condition=make_tag_leaf("a"),
            action=Action(
                kind="append_list", target="char:2", tags=["blue_hair"]
            ),
        )
        p = RulePanel(rule)
        r = p.get_rule()
        assert r.action.target == "char:2"
        assert r.action.tags == ["blue_hair"]

    def test_uc_n_target(self):
        rule = Rule(
            kind="block",
            action=Action(kind="append_list", target="uc:3", tags=["x"]),
        )
        p = RulePanel(rule)
        assert p.get_rule().action.target == "uc:3"

    def test_char_wildcard_target(self):
        rule = Rule(
            kind="block",
            action=Action(kind="append_list", target="char:*", tags=["z"]),
        )
        p = RulePanel(rule)
        assert p.get_rule().action.target == "char:*"

    def test_neg_target(self):
        rule = Rule(
            kind="block",
            action=Action(kind="append_list", target="neg", tags=["bad"]),
        )
        p = RulePanel(rule)
        assert p.get_rule().action.target == "neg"

    def test_global_uc_target(self):
        rule = Rule(
            kind="block",
            action=Action(
                kind="append_list", target="global_uc", tags=["lowres"]
            ),
        )
        p = RulePanel(rule)
        assert p.get_rule().action.target == "global_uc"


class TestOtherActions:
    def test_append(self):
        rule = Rule(
            kind="block",
            action=Action(kind="append", target="postfix", tags=["q"]),
        )
        p = RulePanel(rule)
        r = p.get_rule()
        assert r.action.kind == "append"
        assert r.action.target == "postfix"
        assert r.action.tags == ["q"]

    def test_replace(self):
        rule = Rule(
            kind="block",
            action=Action(
                kind="replace", old_tag="__bad__", new_tags=["clean"]
            ),
        )
        p = RulePanel(rule)
        r = p.get_rule()
        assert r.action.kind == "replace"
        assert r.action.old_tag == "__bad__"
        assert r.action.new_tags == ["clean"]

    def test_char_set(self):
        rule = Rule(
            kind="block",
            action=Action(
                kind="char_set", char_index=2, char_state="disabled"
            ),
        )
        p = RulePanel(rule)
        r = p.get_rule()
        assert r.action.kind == "char_set"
        assert r.action.char_index == 2
        assert r.action.char_state == "disabled"

    def test_char_replace(self):
        rule = Rule(
            kind="block",
            action=Action(
                kind="char_replace", char_index=1,
                char_old_tag="old", char_new_tag="new",
            ),
        )
        p = RulePanel(rule)
        r = p.get_rule()
        assert r.action.kind == "char_replace"
        assert r.action.char_index == 1
        assert r.action.char_old_tag == "old"
        assert r.action.char_new_tag == "new"


# ============================================================================
# Raw kind
# ============================================================================


class TestRawKind:
    def test_raw_roundtrip(self):
        rule = Rule(kind="raw", raw_dsl="(a):existing_tag+=new")
        p = RulePanel(rule)
        r = p.get_rule()
        assert r.kind == "raw"
        assert r.raw_dsl == "(a):existing_tag+=new"
        assert r.condition is None
        assert r.action is None

    def test_switch_raw_to_block(self):
        p = RulePanel(Rule(kind="raw", raw_dsl="(x):y=z"))
        # block 으로 전환 → UI 상 block 기본값 (condition=tag leaf, action=append_list/main)
        p._kind_combo.setCurrentText("block")
        r = p.get_rule()
        assert r.kind == "block"
        assert r.condition is not None
        assert r.action is not None


# ============================================================================
# Condition 통합 (재귀 편집)
# ============================================================================


class TestConditionIntegration:
    def test_and_group_condition(self):
        rule = Rule(
            kind="block",
            condition=make_and_group(
                make_tag_leaf("a"), make_rating_leaf("s")
            ),
            action=Action(kind="append_list", target="main", tags=["t"]),
        )
        p = RulePanel(rule)
        r = p.get_rule()
        assert r.condition.kind == "group"
        assert r.condition.logical == "AND"
        assert len(r.condition.children) == 2

    def test_char_in_condition(self):
        rule = Rule(
            kind="block",
            condition=make_char_in_leaf(2, "smile"),
            action=Action(kind="append_list", target="main", tags=["t"]),
        )
        p = RulePanel(rule)
        r = p.get_rule()
        assert r.condition.leaf_kind == "char_in"
        assert r.condition.char_index == 2
        assert r.condition.char_tag_value == "smile"


# ============================================================================
# Visibility
# ============================================================================


class TestVisibility:
    def test_block_hides_raw(self):
        p = RulePanel(Rule(kind="block"))
        assert p._block_container.isVisibleTo(p)
        assert not p._raw_container.isVisibleTo(p)

    def test_raw_hides_block(self):
        p = RulePanel(Rule(kind="raw", raw_dsl=""))
        assert not p._block_container.isVisibleTo(p)
        assert p._raw_container.isVisibleTo(p)

    def test_append_shows_target_and_tags(self):
        p = RulePanel(Rule(
            kind="block",
            action=Action(kind="append", target="main", tags=[])
        ))
        assert p._target_row.isVisibleTo(p)
        assert p._tags_row.isVisibleTo(p)
        assert not p._replace_row.isVisibleTo(p)
        assert not p._func_char_row.isVisibleTo(p)

    def test_replace_shows_replace_row_only(self):
        p = RulePanel(Rule(
            kind="block",
            action=Action(kind="replace", old_tag="a", new_tags=["b"])
        ))
        assert not p._target_row.isVisibleTo(p)
        assert not p._tags_row.isVisibleTo(p)
        assert p._replace_row.isVisibleTo(p)
        assert not p._func_char_row.isVisibleTo(p)

    def test_char_set_shows_state_not_old_new(self):
        p = RulePanel(Rule(
            kind="block",
            action=Action(kind="char_set", char_index=1, char_state="enabled")
        ))
        assert p._func_char_row.isVisibleTo(p)
        assert p._char_state_combo.isVisibleTo(p)
        assert not p._char_old_edit.isVisibleTo(p)
        assert not p._char_new_edit.isVisibleTo(p)

    def test_char_replace_shows_old_new_not_state(self):
        p = RulePanel(Rule(
            kind="block",
            action=Action(
                kind="char_replace", char_index=1,
                char_old_tag="a", char_new_tag="b",
            )
        ))
        assert p._char_old_edit.isVisibleTo(p)
        assert p._char_new_edit.isVisibleTo(p)
        assert not p._char_state_combo.isVisibleTo(p)

    def test_target_char_shows_n_and_wildcard(self):
        p = RulePanel(Rule(
            kind="block",
            action=Action(kind="append_list", target="char:1", tags=[])
        ))
        assert p._target_n_spin.isVisibleTo(p)
        assert p._target_wildcard_chk.isVisibleTo(p)

    def test_target_fixed_hides_n_and_wildcard(self):
        p = RulePanel(Rule(
            kind="block",
            action=Action(kind="append_list", target="main", tags=[])
        ))
        assert not p._target_n_spin.isVisibleTo(p)
        assert not p._target_wildcard_chk.isVisibleTo(p)


# ============================================================================
# Changed signal
# ============================================================================


class TestChangedSignal:
    def test_set_rule_is_silent(self):
        p = RulePanel()
        c = _Counter()
        p.changed.connect(c)
        p.set_rule(Rule(
            kind="block",
            condition=make_tag_leaf("foo"),
            action=Action(kind="append_list", target="main", tags=["bar"]),
        ))
        assert c.count == 0

    def test_name_edit_emits(self):
        p = RulePanel()
        c = _Counter()
        p.changed.connect(c)
        p._name_edit.setText("hello")
        assert c.count >= 1

    def test_priority_change_emits(self):
        p = RulePanel()
        c = _Counter()
        p.changed.connect(c)
        p._priority_spin.setValue(50)
        assert c.count >= 1

    def test_action_kind_emits(self):
        p = RulePanel()
        c = _Counter()
        p.changed.connect(c)
        p._action_kind_combo.setCurrentText("replace")
        assert c.count >= 1

    def test_chip_add_emits(self):
        p = RulePanel()
        c = _Counter()
        p.changed.connect(c)
        p._tags_chip.add_tag("new")
        assert c.count >= 1

    def test_condition_edit_relays(self):
        p = RulePanel(Rule(
            kind="block",
            condition=make_tag_leaf("a"),
            action=Action(kind="append_list", target="main", tags=[]),
        ))
        c = _Counter()
        p.changed.connect(c)
        p._condition_editor._tag_value_edit.setText("b")
        assert c.count >= 1


# ============================================================================
# 왕복 (serialize 류 아닌 순수 dataclass 왕복)
# ============================================================================


class TestFullRoundtrip:
    def test_complex_rule(self):
        src = Rule(
            kind="block",
            enabled=True,
            priority=42,
            name="복합",
            condition=make_and_group(
                make_tag_leaf("blush", modifier="exact"),
                make_rating_leaf("q", source="override", negated=True),
            ),
            action=Action(
                kind="append_list",
                target="char:*",
                tags=["a", "b", "c"],
            ),
        )
        p = RulePanel(src)
        r = p.get_rule()
        assert r.kind == "block"
        assert r.priority == 42
        assert r.name == "복합"
        assert r.condition.logical == "AND"
        assert r.condition.children[0].tag_modifier == "exact"
        assert r.condition.children[1].negated is True
        assert r.action.target == "char:*"
        assert r.action.tags == ["a", "b", "c"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
