"""ConditionNodeEditor 테스트 (Sub-phase 1.4b).

검증:
- leaf set_node/get_node 왕복 (4 leaf_kind)
- group 왕복 + 재귀 children
- kind 토글 (leaf ↔ group) 이 UI visibility 전환
- leaf_kind 전환이 파라미터 가시성 교체
- changed 시그널이 모든 편집에서 발행
- request_delete 시그널이 removable 에만 적용
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
    ConditionNode,
    make_and_group,
    make_char_in_leaf,
    make_char_on_leaf,
    make_or_group,
    make_rating_leaf,
    make_tag_leaf,
)
from modules.conditional.ui.condition_editor import (  # noqa: E402
    ConditionNodeEditor,
)


class _Counter:
    def __init__(self):
        self.count = 0

    def __call__(self, *args):
        self.count += 1


# ============================================================================
# Leaf 왕복
# ============================================================================


class TestLeafRoundtrip:
    def test_default_empty_tag(self):
        e = ConditionNodeEditor()
        n = e.get_node()
        assert n.kind == "leaf"
        assert n.leaf_kind == "tag"
        assert n.tag_value == ""
        assert n.tag_modifier == "contains"
        assert n.negated is False

    def test_tag_contains(self):
        e = ConditionNodeEditor(make_tag_leaf("blush"))
        n = e.get_node()
        assert n.leaf_kind == "tag"
        assert n.tag_value == "blush"
        assert n.tag_modifier == "contains"

    def test_tag_exact_negated(self):
        src = make_tag_leaf("hair", modifier="exact", negated=True)
        e = ConditionNodeEditor(src)
        n = e.get_node()
        assert n.tag_modifier == "exact"
        assert n.negated is True

    def test_tag_not_contains(self):
        e = ConditionNodeEditor(make_tag_leaf("x", modifier="not_contains"))
        assert e.get_node().tag_modifier == "not_contains"

    def test_rating(self):
        e = ConditionNodeEditor(make_rating_leaf("q", source="override"))
        n = e.get_node()
        assert n.leaf_kind == "rating"
        assert n.rating_value == "q"
        assert n.rating_source == "override"

    def test_rating_negated(self):
        e = ConditionNodeEditor(
            make_rating_leaf("e", source="row", negated=True)
        )
        assert e.get_node().negated is True

    def test_char_in(self):
        e = ConditionNodeEditor(
            make_char_in_leaf(2, "smile", modifier="exact")
        )
        n = e.get_node()
        assert n.leaf_kind == "char_in"
        assert n.char_index == 2
        assert n.char_tag_value == "smile"
        assert n.char_tag_modifier == "exact"

    def test_char_on(self):
        e = ConditionNodeEditor(make_char_on_leaf(3))
        n = e.get_node()
        assert n.leaf_kind == "char_on"
        assert n.char_index == 3


# ============================================================================
# Group 왕복 + 재귀
# ============================================================================


class TestGroupRoundtrip:
    def test_empty_group(self):
        src = ConditionNode(kind="group", logical="AND", children=[])
        e = ConditionNodeEditor(src)
        n = e.get_node()
        assert n.kind == "group"
        assert n.logical == "AND"
        assert n.children == []

    def test_and_two_leaves(self):
        src = make_and_group(make_tag_leaf("a"), make_tag_leaf("b"))
        e = ConditionNodeEditor(src)
        n = e.get_node()
        assert n.logical == "AND"
        assert len(n.children) == 2
        assert n.children[0].tag_value == "a"
        assert n.children[1].tag_value == "b"

    def test_or_mixed(self):
        src = make_or_group(
            make_tag_leaf("foo", modifier="exact"),
            make_rating_leaf("s"),
        )
        e = ConditionNodeEditor(src)
        n = e.get_node()
        assert n.logical == "OR"
        assert n.children[0].leaf_kind == "tag"
        assert n.children[0].tag_modifier == "exact"
        assert n.children[1].leaf_kind == "rating"
        assert n.children[1].rating_value == "s"

    def test_nested_groups(self):
        inner = make_or_group(make_tag_leaf("x"), make_tag_leaf("y"))
        src = make_and_group(make_tag_leaf("a"), inner)
        e = ConditionNodeEditor(src)
        n = e.get_node()
        assert n.logical == "AND"
        assert n.children[1].kind == "group"
        assert n.children[1].logical == "OR"
        assert n.children[1].children[0].tag_value == "x"
        assert n.children[1].children[1].tag_value == "y"


# ============================================================================
# Visibility 토글
# ============================================================================


class TestVisibility:
    def test_leaf_mode_hides_group_container(self):
        e = ConditionNodeEditor(make_tag_leaf("x"))
        assert e._leaf_container.isVisibleTo(e)
        assert not e._group_container.isVisibleTo(e)

    def test_group_mode_hides_leaf_container(self):
        e = ConditionNodeEditor(make_and_group(make_tag_leaf("a")))
        # QWidget.isVisible() 은 show() 전까지 False → widgetvisibility state 직접 조회
        # 대신 내부 상태 (leaf_container.isVisibleTo(group_container) 대용)
        # show 상태는 container 가 부모가 없을 때 False 일 수 있으므로 속성으로 확인
        assert not e._leaf_container.isVisibleTo(e)
        assert e._group_container.isVisibleTo(e)

    def test_tag_params_only_for_tag_kind(self):
        e = ConditionNodeEditor(make_tag_leaf("x"))
        assert e._tag_params.isVisibleTo(e)
        assert not e._rating_params.isVisibleTo(e)
        assert not e._char_params.isVisibleTo(e)

    def test_rating_params_only_for_rating_kind(self):
        e = ConditionNodeEditor(make_rating_leaf("e"))
        assert not e._tag_params.isVisibleTo(e)
        assert e._rating_params.isVisibleTo(e)
        assert not e._char_params.isVisibleTo(e)

    def test_char_in_shows_char_tag_row(self):
        e = ConditionNodeEditor(make_char_in_leaf(1, "foo"))
        assert e._char_params.isVisibleTo(e)
        assert e._char_tag_row.isVisibleTo(e)

    def test_char_on_hides_char_tag_row(self):
        e = ConditionNodeEditor(make_char_on_leaf(1))
        assert e._char_params.isVisibleTo(e)
        assert not e._char_tag_row.isVisibleTo(e)


# ============================================================================
# kind/leaf_kind 전환
# ============================================================================


class TestKindSwitch:
    def test_switch_leaf_to_group_via_setter(self):
        e = ConditionNodeEditor(make_tag_leaf("foo"))
        e.set_node(make_and_group(make_tag_leaf("a")))
        n = e.get_node()
        assert n.kind == "group"
        assert len(n.children) == 1

    def test_switch_group_to_leaf_via_setter(self):
        e = ConditionNodeEditor(make_and_group(make_tag_leaf("a")))
        e.set_node(make_tag_leaf("new"))
        n = e.get_node()
        assert n.kind == "leaf"
        assert n.tag_value == "new"
        assert len(e._child_editors) == 0

    def test_ui_leaf_kind_change_emits_signal(self):
        e = ConditionNodeEditor(make_tag_leaf("x"))
        counter = _Counter()
        e.changed.connect(counter)
        e._leaf_kind_combo.setCurrentText("rating")
        # setCurrentText 는 값이 이전과 달라야 시그널 발행 → 실제 변경
        assert counter.count >= 1


# ============================================================================
# changed 시그널
# ============================================================================


class TestChangedSignal:
    def test_tag_text_edit_emits(self):
        e = ConditionNodeEditor(make_tag_leaf("foo"))
        counter = _Counter()
        e.changed.connect(counter)
        e._tag_value_edit.setText("bar")
        assert counter.count >= 1

    def test_set_node_does_not_emit(self):
        """set_node 는 외부 소스 → 사용자 편집 아님 → 시그널 억제."""
        e = ConditionNodeEditor(make_tag_leaf("foo"))
        counter = _Counter()
        e.changed.connect(counter)
        e.set_node(make_tag_leaf("bar"))
        assert counter.count == 0

    def test_add_leaf_button_emits(self):
        e = ConditionNodeEditor(make_and_group(make_tag_leaf("a")))
        counter = _Counter()
        e.changed.connect(counter)
        e._on_add_leaf()
        assert counter.count >= 1

    def test_child_change_relays_to_parent(self):
        e = ConditionNodeEditor(make_and_group(make_tag_leaf("a")))
        counter = _Counter()
        e.changed.connect(counter)
        child = e._child_editors[0]
        child._tag_value_edit.setText("modified")
        assert counter.count >= 1


# ============================================================================
# Delete 버튼 (removable)
# ============================================================================


class TestRequestDelete:
    def test_child_delete_removes_from_parent(self):
        e = ConditionNodeEditor(
            make_and_group(make_tag_leaf("a"), make_tag_leaf("b"))
        )
        assert len(e._child_editors) == 2
        # 첫 번째 child 가 self 를 emit
        first = e._child_editors[0]
        first.request_delete.emit(first)
        # parent 가 받아 제거
        assert len(e._child_editors) == 1
        assert e._child_editors[0].get_node().tag_value == "b"

    def test_toplevel_has_no_delete_button(self):
        e = ConditionNodeEditor(make_tag_leaf("x"))
        # removable=False (기본) → 버튼 없음. 간접 확인 — request_delete.emit
        # 해도 외부 수신자 없으면 아무 동작 없음. removable 플래그 자체 검증.
        assert e._removable is False

    def test_child_is_removable(self):
        e = ConditionNodeEditor(make_and_group(make_tag_leaf("a")))
        assert e._child_editors[0]._removable is True


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
