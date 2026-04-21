"""ConditionNodeEditor — 조건 노드(ConditionNode) 편집 위젯 (Sub-phase 1.4b).

leaf / group 재귀 편집. 위젯은 생성 시 전부 만들고 visibility 로 토글 →
set_node / get_node 왕복이 안정적 (rebuild 없음).

공개 API:
    set_node(ConditionNode)
    get_node() -> ConditionNode
    changed              # pyqtSignal — 모든 편집에서 발행

group 의 경우 자식 editor 를 재귀 생성 (depth 무제한). 자식 editor 의
changed 는 relay, request_delete 로 삭제 요청 수신.
"""

from __future__ import annotations

from typing import List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from modules.conditional.block_model import ConditionNode, make_tag_leaf
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from ui.theme import DARK_COLORS


_LEAF_KINDS = ("tag", "rating", "char_in", "char_on")
_TAG_MODS = ("contains", "exact", "not_contains", "not_exact")
_RATING_VALS = ("e", "q", "s", "g")
_RATING_SOURCES = ("auto", "row", "override", "bayes")
_LOGICAL_OPS = ("AND", "OR")


class ConditionNodeEditor(QFrame):
    """재귀 ConditionNode 편집 위젯.

    시그널:
        changed: 내용이 변경될 때마다 발행 (값 인자 없음).
        request_delete(ConditionNodeEditor): 자식이 스스로 삭제 요청.
    """

    changed = pyqtSignal()
    request_delete = pyqtSignal(object)

    def __init__(
        self,
        node: Optional[ConditionNode] = None,
        parent: Optional[QWidget] = None,
        *,
        removable: bool = False,
    ):
        super().__init__(parent)
        self._child_editors: List["ConditionNodeEditor"] = []
        self._removable = removable
        self._build_ui()
        self.set_node(node or make_tag_leaf(""))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_node(self, node: ConditionNode) -> None:
        """dataclass → UI 동기화. 시그널 일괄 차단 후 재개."""
        self._mute(True)
        try:
            kind = node.kind if node.kind in ("leaf", "group") else "leaf"
            self._kind_combo.setCurrentText(kind)

            if kind == "leaf":
                self._sync_leaf(node)
                self._clear_children()
            else:
                self._logical_combo.setCurrentText(node.logical or "AND")
                self._clear_children()
                for child in (node.children or []):
                    self._append_child(child)
        finally:
            self._mute(False)
        self._update_visibility()

    def get_node(self) -> ConditionNode:
        kind = self._kind_combo.currentText()
        if kind == "leaf":
            return self._read_leaf()
        return ConditionNode(
            kind="group",
            logical=self._logical_combo.currentText(),
            children=[e.get_node() for e in self._child_editors],
        )

    # ------------------------------------------------------------------
    # UI 구성 — 전부 선생성, visibility 로 토글
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(self._frame_style())
        root = QVBoxLayout(self)
        root.setContentsMargins(
            get_scaled_size(6), get_scaled_size(6),
            get_scaled_size(6), get_scaled_size(6),
        )
        root.setSpacing(get_scaled_size(4))

        root.addLayout(self._build_header_row())
        self._leaf_container = self._build_leaf_container()
        root.addWidget(self._leaf_container)
        self._group_container = self._build_group_container()
        root.addWidget(self._group_container)

    def _build_header_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(get_scaled_size(6))

        self._kind_combo = QComboBox()
        self._kind_combo.addItems(["leaf", "group"])
        self._kind_combo.currentTextChanged.connect(self._on_kind_changed)
        row.addWidget(QLabel("종류:"))
        row.addWidget(self._kind_combo)
        row.addStretch()

        if self._removable:
            delete_btn = QPushButton("🗑")
            delete_btn.setFixedWidth(get_scaled_size(28))
            delete_btn.setToolTip("이 조건 제거")
            delete_btn.clicked.connect(
                lambda: self.request_delete.emit(self)
            )
            row.addWidget(delete_btn)
        return row

    def _build_leaf_container(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(get_scaled_size(4))

        # leaf_kind + negated
        top = QHBoxLayout()
        top.setSpacing(get_scaled_size(6))
        top.addWidget(QLabel("leaf:"))
        self._leaf_kind_combo = QComboBox()
        self._leaf_kind_combo.addItems(list(_LEAF_KINDS))
        self._leaf_kind_combo.currentTextChanged.connect(
            self._on_leaf_kind_changed
        )
        top.addWidget(self._leaf_kind_combo)
        self._negated_chk = QCheckBox("NOT")
        self._negated_chk.stateChanged.connect(self._emit_changed)
        top.addWidget(self._negated_chk)
        top.addStretch()
        layout.addLayout(top)

        self._tag_params = self._build_tag_params()
        layout.addWidget(self._tag_params)
        self._rating_params = self._build_rating_params()
        layout.addWidget(self._rating_params)
        self._char_params = self._build_char_params()
        layout.addWidget(self._char_params)
        return container

    def _build_tag_params(self) -> QWidget:
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(get_scaled_size(6))
        row.addWidget(QLabel("태그:"))
        self._tag_value_edit = QLineEdit()
        self._tag_value_edit.setPlaceholderText("예: blue_hair")
        self._tag_value_edit.textChanged.connect(self._emit_changed)
        row.addWidget(self._tag_value_edit, 1)
        self._tag_modifier_combo = QComboBox()
        self._tag_modifier_combo.addItems(list(_TAG_MODS))
        self._tag_modifier_combo.currentTextChanged.connect(self._emit_changed)
        row.addWidget(self._tag_modifier_combo)
        return w

    def _build_rating_params(self) -> QWidget:
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(get_scaled_size(6))
        row.addWidget(QLabel("rating:"))
        self._rating_value_combo = QComboBox()
        self._rating_value_combo.addItems(list(_RATING_VALS))
        self._rating_value_combo.currentTextChanged.connect(self._emit_changed)
        row.addWidget(self._rating_value_combo)
        row.addWidget(QLabel("source:"))
        self._rating_source_combo = QComboBox()
        self._rating_source_combo.addItems(list(_RATING_SOURCES))
        self._rating_source_combo.currentTextChanged.connect(self._emit_changed)
        row.addWidget(self._rating_source_combo)
        row.addStretch()
        return w

    def _build_char_params(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(get_scaled_size(4))

        idx_row = QHBoxLayout()
        idx_row.setSpacing(get_scaled_size(6))
        idx_row.addWidget(QLabel("char #"))
        self._char_index_spin = QSpinBox()
        self._char_index_spin.setRange(1, 10)
        self._char_index_spin.valueChanged.connect(self._emit_changed)
        idx_row.addWidget(self._char_index_spin)
        idx_row.addStretch()
        layout.addLayout(idx_row)

        # char_in 전용: tag + modifier
        self._char_tag_row = QWidget()
        tag_row = QHBoxLayout(self._char_tag_row)
        tag_row.setContentsMargins(0, 0, 0, 0)
        tag_row.setSpacing(get_scaled_size(6))
        tag_row.addWidget(QLabel("내부 태그:"))
        self._char_tag_value_edit = QLineEdit()
        self._char_tag_value_edit.setPlaceholderText("예: smile")
        self._char_tag_value_edit.textChanged.connect(self._emit_changed)
        tag_row.addWidget(self._char_tag_value_edit, 1)
        self._char_tag_modifier_combo = QComboBox()
        self._char_tag_modifier_combo.addItems(list(_TAG_MODS))
        self._char_tag_modifier_combo.currentTextChanged.connect(
            self._emit_changed
        )
        tag_row.addWidget(self._char_tag_modifier_combo)
        layout.addWidget(self._char_tag_row)
        return w

    def _build_group_container(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(get_scaled_size(4))

        top = QHBoxLayout()
        top.setSpacing(get_scaled_size(6))
        top.addWidget(QLabel("그룹 연산:"))
        self._logical_combo = QComboBox()
        self._logical_combo.addItems(list(_LOGICAL_OPS))
        self._logical_combo.currentTextChanged.connect(self._emit_changed)
        top.addWidget(self._logical_combo)
        top.addStretch()
        add_leaf_btn = QPushButton("+ leaf")
        add_leaf_btn.clicked.connect(self._on_add_leaf)
        top.addWidget(add_leaf_btn)
        add_group_btn = QPushButton("+ group")
        add_group_btn.clicked.connect(self._on_add_group)
        top.addWidget(add_group_btn)
        layout.addLayout(top)

        self._children_container = QWidget()
        self._children_layout = QVBoxLayout(self._children_container)
        self._children_layout.setContentsMargins(
            get_scaled_size(12), 0, 0, 0
        )
        self._children_layout.setSpacing(get_scaled_size(4))
        layout.addWidget(self._children_container)
        return container

    # ------------------------------------------------------------------
    # 내부 — sync/read/event
    # ------------------------------------------------------------------

    def _sync_leaf(self, node: ConditionNode) -> None:
        self._leaf_kind_combo.setCurrentText(node.leaf_kind or "tag")
        self._negated_chk.setChecked(bool(node.negated))
        self._tag_value_edit.setText(node.tag_value or "")
        self._tag_modifier_combo.setCurrentText(
            node.tag_modifier or "contains"
        )
        self._rating_value_combo.setCurrentText(node.rating_value or "e")
        self._rating_source_combo.setCurrentText(node.rating_source or "auto")
        self._char_index_spin.setValue(max(1, int(node.char_index or 1)))
        self._char_tag_value_edit.setText(node.char_tag_value or "")
        self._char_tag_modifier_combo.setCurrentText(
            node.char_tag_modifier or "contains"
        )

    def _read_leaf(self) -> ConditionNode:
        leaf_kind = self._leaf_kind_combo.currentText()
        n = ConditionNode(
            kind="leaf",
            leaf_kind=leaf_kind,
            negated=self._negated_chk.isChecked(),
        )
        if leaf_kind == "tag":
            n.tag_value = self._tag_value_edit.text().strip()
            n.tag_modifier = self._tag_modifier_combo.currentText()
        elif leaf_kind == "rating":
            n.rating_value = self._rating_value_combo.currentText()
            n.rating_source = self._rating_source_combo.currentText()
        elif leaf_kind == "char_in":
            n.char_index = int(self._char_index_spin.value())
            n.char_tag_value = self._char_tag_value_edit.text().strip()
            n.char_tag_modifier = self._char_tag_modifier_combo.currentText()
        elif leaf_kind == "char_on":
            n.char_index = int(self._char_index_spin.value())
        return n

    def _update_visibility(self) -> None:
        is_leaf = self._kind_combo.currentText() == "leaf"
        self._leaf_container.setVisible(is_leaf)
        self._group_container.setVisible(not is_leaf)
        if is_leaf:
            lk = self._leaf_kind_combo.currentText()
            self._tag_params.setVisible(lk == "tag")
            self._rating_params.setVisible(lk == "rating")
            self._char_params.setVisible(lk in ("char_in", "char_on"))
            self._char_tag_row.setVisible(lk == "char_in")

    def _on_kind_changed(self, new_kind: str) -> None:
        self._update_visibility()
        self._emit_changed()

    def _on_leaf_kind_changed(self, _text: str) -> None:
        self._update_visibility()
        self._emit_changed()

    def _on_add_leaf(self) -> None:
        self._append_child(make_tag_leaf(""))
        self._emit_changed()

    def _on_add_group(self) -> None:
        self._append_child(
            ConditionNode(kind="group", logical="AND", children=[])
        )
        self._emit_changed()

    def _append_child(self, node: ConditionNode) -> None:
        editor = ConditionNodeEditor(node, removable=True)
        editor.changed.connect(self._emit_changed)
        editor.request_delete.connect(self._on_child_delete_requested)
        self._child_editors.append(editor)
        self._children_layout.addWidget(editor)

    def _clear_children(self) -> None:
        for e in self._child_editors:
            e.setParent(None)
            e.deleteLater()
        self._child_editors = []

    def _on_child_delete_requested(self, editor) -> None:
        if editor in self._child_editors:
            self._child_editors.remove(editor)
            editor.setParent(None)
            editor.deleteLater()
            self._emit_changed()

    def _emit_changed(self, *_args) -> None:
        self.changed.emit()

    def _mute(self, muted: bool) -> None:
        """모든 입력 위젯의 시그널 일시 차단/복구."""
        widgets = [
            self._kind_combo, self._leaf_kind_combo, self._negated_chk,
            self._tag_value_edit, self._tag_modifier_combo,
            self._rating_value_combo, self._rating_source_combo,
            self._char_index_spin,
            self._char_tag_value_edit, self._char_tag_modifier_combo,
            self._logical_combo,
        ]
        for w in widgets:
            w.blockSignals(muted)

    # ------------------------------------------------------------------
    # 스타일
    # ------------------------------------------------------------------

    def _frame_style(self) -> str:
        return (
            f"QFrame {{"
            f"  background-color: {DARK_COLORS['bg_secondary']};"
            f"  border: 1px solid {DARK_COLORS['border']};"
            f"  border-radius: {get_scaled_size(4)}px;"
            f"}}"
        )
