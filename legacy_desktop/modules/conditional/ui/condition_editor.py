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

from legacy_desktop.modules.conditional.block_model import ConditionNode, make_tag_leaf
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from ui.theme import DARK_COLORS


_KIND_ITEMS = (
    ("단일 조건", "leaf"),
    ("조건 묶음", "group"),
)
_LEAF_KIND_ITEMS = (
    ("태그 확인", "tag"),
    ("등급 확인", "rating"),
    ("캐릭터 안 태그", "char_in"),
    ("캐릭터 활성 여부", "char_on"),
)
_TAG_MOD_ITEMS = (
    ("포함", "contains"),
    ("정확히 일치", "exact"),
    ("포함하지 않음", "not_contains"),
    ("정확히 일치하지 않음", "not_exact"),
)
_RATING_VAL_ITEMS = (
    ("E", "e"),
    ("Q", "q"),
    ("S", "s"),
    ("G", "g"),
)
_RATING_SOURCE_ITEMS = (
    ("자동 판단", "auto"),
    ("원본 행 값", "row"),
    ("강제 지정", "override"),
    ("Bayes 결과", "bayes"),
)
_LOGICAL_ITEMS = (
    ("모두 만족", "AND"),
    ("하나라도 만족", "OR"),
)

# 175: rule_panel 과 동기화된 로컬 팔레트. DARK_COLORS 의 bg_secondary/
# bg_tertiary 가 동일하여 카드/입력 레이어가 평평해지는 문제를 회피한다.
_CARD_BG = "#2D2D2D"          # 조건 카드 공통 배경
_INPUT_BG = "#161616"          # 입력 필드 배경
_CARD_BORDER = "#555555"
_INPUT_BORDER = "#444444"
# 조건 묶음 좌측 accent — 중첩 깊이마다 다른 색을 부여해 "내가 지금 어느 레벨
# 안에 있는지" 를 좌측 바 색으로 즉시 읽어낼 수 있게 한다. 단일 색(파랑/연두)
# 은 깊은 중첩에서 모든 바가 같은 색이 되어 계층 감이 사라짐. 색은 dark UI
# 에서 선명하게 분리되는 Material 600~700 계열 + 원색 차이 큰 순으로 배치.
_GROUP_ACCENT_PALETTE = (
    "#689F38",  # depth 0 — Light Green 700 (연두)
    "#FB8C00",  # depth 1 — Orange 600 (주황)
    "#8E24AA",  # depth 2 — Purple 600 (보라)
    "#00ACC1",  # depth 3 — Cyan 600 (시안)
    "#C62828",  # depth 4 — Red 800 (빨강)
)


def _group_accent_for_depth(depth: int) -> str:
    if depth < 0:
        depth = 0
    return _GROUP_ACCENT_PALETTE[depth % len(_GROUP_ACCENT_PALETTE)]


def _add_combo_items(combo: QComboBox, items) -> None:
    for text, value in items:
        combo.addItem(text, userData=value)


def _set_combo_value(combo: QComboBox, value: str, fallback: str) -> None:
    idx = combo.findData(value)
    if idx < 0:
        idx = combo.findData(fallback)
    if idx >= 0:
        combo.setCurrentIndex(idx)


def _combo_value(combo: QComboBox, fallback: str) -> str:
    value = combo.currentData()
    return value if isinstance(value, str) and value else fallback


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
        depth: int = 0,
    ):
        super().__init__(parent)
        self._child_editors: List["ConditionNodeEditor"] = []
        self._removable = removable
        # 내 children_container 에 적용될 accent 색을 고르기 위한 깊이.
        # 루트=0, 중첩될수록 +1. `_build_group_container` 에서 참조.
        self._depth = max(0, int(depth))
        self._build_ui()
        self.set_node(node or make_tag_leaf(""))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_node(self, node: ConditionNode) -> None:
        """dataclass → UI 동기화. 시그널 일괄 차단 후 재개."""
        # 루트 에디터는 editor_window 생명주기 동안 단일 인스턴스로 재사용되므로
        # 이전 rule 에서 사용자가 접어둔 상태가 다음 rule 로 새면 안 된다. 새 rule
        # 로드 시 항상 펼친 상태로 시작.
        self._group_collapsed = False
        self._mute(True)
        try:
            kind = node.kind if node.kind in ("leaf", "group") else "leaf"
            self._set_kind_value(kind)

            if kind == "leaf":
                self._sync_leaf(node)
                self._clear_children()
            else:
                _set_combo_value(
                    self._logical_combo, node.logical or "AND", "AND"
                )
                self._clear_children()
                for child in (node.children or []):
                    self._append_child(child)
        finally:
            self._mute(False)
        self._update_visibility()

    def get_node(self) -> ConditionNode:
        kind = _combo_value(self._kind_combo, "leaf")
        if kind == "leaf":
            return self._read_leaf()
        return ConditionNode(
            kind="group",
            logical=_combo_value(self._logical_combo, "AND"),
            children=[e.get_node() for e in self._child_editors],
        )

    # ------------------------------------------------------------------
    # UI 구성 — 전부 선생성, visibility 로 토글
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.setObjectName("conditionCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        # 175 hotfix: 입력 스타일 (QComboBox/QLineEdit/QSpinBox) 을 root 에
        # 한꺼번에 건다. individual widget.setStyleSheet 방식은 WindowsVista
        # 네이티브 스타일이 QComboBox body 를 overlay 로 그려 배경이 연해지는
        # 증상이 있어, 부모 stylesheet 로 cascade 시키는 쪽이 안정적.
        self.setStyleSheet(
            self._frame_style()
            + self._input_style()
            + (
                f"QLabel {{"
                f"  border: none;"
                f"  background: transparent;"
                f"  font-size: {get_scaled_font_size(17)}px;"
                f"}}"
                f"QPushButton {{"
                f"  background-color: {DARK_COLORS['bg_tertiary']};"
                f"  color: {DARK_COLORS['text_primary']};"
                f"  border: 1px solid {_CARD_BORDER};"
                f"  border-radius: {get_scaled_size(4)}px;"
                f"  font-size: {get_scaled_font_size(17)}px;"
                f"  padding: {get_scaled_size(5)}px {get_scaled_size(11)}px;"
                f"}}"
                f"QPushButton:hover {{"
                f"  background-color: {DARK_COLORS['bg_hover']};"
                f"  border-color: {DARK_COLORS['border_light']};"
                f"}}"
                f"QPushButton:pressed {{"
                f"  background-color: {DARK_COLORS['bg_pressed']};"
                f"}}"
                f"QCheckBox {{"
                f"  font-size: {get_scaled_font_size(17)}px;"
                f"  spacing: {get_scaled_size(6)}px;"
                f"  color: {DARK_COLORS['text_primary']};"
                f"  background: transparent;"
                f"}}"
            )
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(
            get_scaled_size(10), get_scaled_size(10),
            get_scaled_size(10), get_scaled_size(10),
        )
        root.setSpacing(get_scaled_size(8))

        root.addLayout(self._build_header_row())
        self._leaf_container = self._build_leaf_container()
        root.addWidget(self._leaf_container)
        self._group_container = self._build_group_container()
        root.addWidget(self._group_container)

    def _build_header_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(get_scaled_size(6))

        self._kind_combo = QComboBox()
        _add_combo_items(self._kind_combo, _KIND_ITEMS)
        self._kind_combo.wheelEvent = lambda e: e.ignore()
        self._kind_combo.currentTextChanged.connect(self._on_kind_changed)
        row.addWidget(QLabel("조건 형태:"))
        row.addWidget(self._kind_combo)
        row.addStretch()

        # 조건 묶음 접기/펼치기 — group kind 에서만 표시. 깊은 중첩을 리스트에서
        # 일시적으로 축소해 세로 공간을 확보하기 위함. 휴지통과 동일 행에 배치.
        self._group_collapsed: bool = False
        self._collapse_btn = QPushButton("▼")
        self._collapse_btn.setFixedWidth(get_scaled_size(32))
        self._collapse_btn.setToolTip("자식 조건 접기/펼치기")
        self._collapse_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: transparent;"
            f"  border: 1px solid {_CARD_BORDER};"
            f"  border-radius: {get_scaled_size(4)}px;"
            f"  padding: {get_scaled_size(4)}px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background-color: {DARK_COLORS['bg_hover']};"
            f"  border-color: {DARK_COLORS['border_light']};"
            f"}}"
        )
        self._collapse_btn.clicked.connect(self._on_toggle_collapse)
        row.addWidget(self._collapse_btn)

        if self._removable:
            delete_btn = QPushButton("🗑")
            delete_btn.setFixedWidth(get_scaled_size(32))
            delete_btn.setToolTip("이 조건 제거")
            delete_btn.setStyleSheet(
                f"QPushButton {{"
                f"  background-color: transparent;"
                f"  border: 1px solid {_CARD_BORDER};"
                f"  border-radius: {get_scaled_size(4)}px;"
                f"  padding: {get_scaled_size(4)}px;"
                f"}}"
                f"QPushButton:hover {{"
                f"  background-color: {DARK_COLORS['error']};"
                f"  border-color: {DARK_COLORS['error']};"
                f"  color: white;"
                f"}}"
            )
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
        top.addWidget(QLabel("판단 기준:"))
        self._leaf_kind_combo = QComboBox()
        _add_combo_items(self._leaf_kind_combo, _LEAF_KIND_ITEMS)
        self._leaf_kind_combo.wheelEvent = lambda e: e.ignore()
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
        row.addWidget(QLabel("찾을 태그:"))
        self._tag_value_edit = QLineEdit()
        self._tag_value_edit.setPlaceholderText("예: blue_hair")
        self._tag_value_edit.textChanged.connect(self._emit_changed)
        row.addWidget(self._tag_value_edit, 1)
        self._tag_modifier_combo = QComboBox()
        _add_combo_items(self._tag_modifier_combo, _TAG_MOD_ITEMS)
        self._tag_modifier_combo.wheelEvent = lambda e: e.ignore()
        self._tag_modifier_combo.currentTextChanged.connect(self._emit_changed)
        row.addWidget(self._tag_modifier_combo)
        return w

    def _build_rating_params(self) -> QWidget:
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(get_scaled_size(6))
        row.addWidget(QLabel("등급:"))
        self._rating_value_combo = QComboBox()
        _add_combo_items(self._rating_value_combo, _RATING_VAL_ITEMS)
        self._rating_value_combo.wheelEvent = lambda e: e.ignore()
        self._rating_value_combo.currentTextChanged.connect(self._emit_changed)
        row.addWidget(self._rating_value_combo)
        row.addWidget(QLabel("판단 기준:"))
        self._rating_source_combo = QComboBox()
        _add_combo_items(
            self._rating_source_combo, _RATING_SOURCE_ITEMS
        )
        self._rating_source_combo.wheelEvent = lambda e: e.ignore()
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
        idx_row.addWidget(QLabel("캐릭터 슬롯"))
        self._char_index_spin = QSpinBox()
        self._char_index_spin.setRange(1, 10)
        self._char_index_spin.wheelEvent = lambda e: e.ignore()
        self._char_index_spin.valueChanged.connect(self._emit_changed)
        idx_row.addWidget(self._char_index_spin)
        idx_row.addStretch()
        layout.addLayout(idx_row)

        # char_in 전용: tag + modifier
        self._char_tag_row = QWidget()
        tag_row = QHBoxLayout(self._char_tag_row)
        tag_row.setContentsMargins(0, 0, 0, 0)
        tag_row.setSpacing(get_scaled_size(6))
        tag_row.addWidget(QLabel("캐릭터 안 태그:"))
        self._char_tag_value_edit = QLineEdit()
        self._char_tag_value_edit.setPlaceholderText("예: smile")
        self._char_tag_value_edit.textChanged.connect(self._emit_changed)
        tag_row.addWidget(self._char_tag_value_edit, 1)
        self._char_tag_modifier_combo = QComboBox()
        _add_combo_items(
            self._char_tag_modifier_combo, _TAG_MOD_ITEMS
        )
        self._char_tag_modifier_combo.wheelEvent = lambda e: e.ignore()
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
        top.addWidget(QLabel("묶음 방식:"))
        self._logical_combo = QComboBox()
        _add_combo_items(self._logical_combo, _LOGICAL_ITEMS)
        self._logical_combo.wheelEvent = lambda e: e.ignore()
        self._logical_combo.currentTextChanged.connect(self._emit_changed)
        top.addWidget(self._logical_combo)
        top.addStretch()
        primary_btn_style = (
            f"QPushButton {{"
            f"  background-color: {DARK_COLORS['accent_blue']};"
            f"  color: {DARK_COLORS['text_primary']};"
            f"  border: none;"
            f"  border-radius: {get_scaled_size(4)}px;"
            f"  padding: {get_scaled_size(5)}px {get_scaled_size(12)}px;"
            f"  font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background-color: {DARK_COLORS['accent_blue_hover']};"
            f"}}"
            f"QPushButton:pressed {{"
            f"  background-color: #0D47A1;"
            f"}}"
        )
        add_leaf_btn = QPushButton("+ 조건")
        add_leaf_btn.setStyleSheet(primary_btn_style)
        add_leaf_btn.clicked.connect(self._on_add_leaf)
        top.addWidget(add_leaf_btn)
        add_group_btn = QPushButton("+ 묶음")
        add_group_btn.setStyleSheet(primary_btn_style)
        add_group_btn.clicked.connect(self._on_add_group)
        top.addWidget(add_group_btn)
        layout.addLayout(top)

        self._children_container = QWidget()
        self._children_container.setObjectName("childrenBand")
        # 중첩 자식 영역은 좌측 accent 바로 부모와 연결되어 있음을 시각화.
        # objectName 으로 범위 한정 → 자식 위젯으로 스타일 전파 방지.
        # children_container 의 좌측 바는 "이 그룹에 속하는 바" — 자기 자신
        # 의 depth 로 색상을 선택해야 루트(depth 0)가 팔레트[0]=연두, 다음
        # 중첩(depth 1)이 [1]=주황 순으로 자연 전개된다.
        self._children_container.setStyleSheet(
            f"QWidget#childrenBand {{"
            f"  border-left: {get_scaled_size(3)}px solid"
            f"    {_group_accent_for_depth(self._depth)};"
            f"  background: transparent;"
            f"}}"
        )
        self._children_layout = QVBoxLayout(self._children_container)
        self._children_layout.setContentsMargins(
            get_scaled_size(14), get_scaled_size(4),
            0, get_scaled_size(4),
        )
        self._children_layout.setSpacing(get_scaled_size(8))
        layout.addWidget(self._children_container)
        return container

    # ------------------------------------------------------------------
    # 내부 — sync/read/event
    # ------------------------------------------------------------------

    def _sync_leaf(self, node: ConditionNode) -> None:
        self._set_leaf_kind_value(node.leaf_kind or "tag")
        self._negated_chk.setChecked(bool(node.negated))
        self._tag_value_edit.setText(node.tag_value or "")
        _set_combo_value(
            self._tag_modifier_combo,
            node.tag_modifier or "contains",
            "contains",
        )
        _set_combo_value(
            self._rating_value_combo, node.rating_value or "e", "e"
        )
        _set_combo_value(
            self._rating_source_combo,
            node.rating_source or "auto",
            "auto",
        )
        self._char_index_spin.setValue(max(1, int(node.char_index or 1)))
        self._char_tag_value_edit.setText(node.char_tag_value or "")
        _set_combo_value(
            self._char_tag_modifier_combo,
            node.char_tag_modifier or "contains",
            "contains",
        )

    def _read_leaf(self) -> ConditionNode:
        leaf_kind = _combo_value(self._leaf_kind_combo, "tag")
        # NOT 체크박스는 rating / char_on 에만 노출되므로, 그 외 kind 에서는
        # 숨겨진 상태의 체크값이 모델로 새어나가지 않게 False 로 고정.
        negated_applicable = leaf_kind in ("rating", "char_on")
        n = ConditionNode(
            kind="leaf",
            leaf_kind=leaf_kind,
            negated=(
                self._negated_chk.isChecked() if negated_applicable else False
            ),
        )
        if leaf_kind == "tag":
            n.tag_value = self._tag_value_edit.text().strip()
            n.tag_modifier = _combo_value(
                self._tag_modifier_combo, "contains"
            )
        elif leaf_kind == "rating":
            n.rating_value = _combo_value(self._rating_value_combo, "e")
            n.rating_source = _combo_value(
                self._rating_source_combo, "auto"
            )
        elif leaf_kind == "char_in":
            n.char_index = int(self._char_index_spin.value())
            n.char_tag_value = self._char_tag_value_edit.text().strip()
            n.char_tag_modifier = _combo_value(
                self._char_tag_modifier_combo, "contains"
            )
        elif leaf_kind == "char_on":
            n.char_index = int(self._char_index_spin.value())
        return n

    def _update_visibility(self) -> None:
        is_leaf = _combo_value(self._kind_combo, "leaf") == "leaf"
        self._leaf_container.setVisible(is_leaf)
        self._group_container.setVisible(not is_leaf)
        # 접기 버튼은 group 에서만 의미 — leaf 로 전환되면 숨기고 펼친 상태로 초기화.
        self._collapse_btn.setVisible(not is_leaf)
        if is_leaf:
            lk = _combo_value(self._leaf_kind_combo, "tag")
            self._tag_params.setVisible(lk == "tag")
            self._rating_params.setVisible(lk == "rating")
            self._char_params.setVisible(lk in ("char_in", "char_on"))
            self._char_tag_row.setVisible(lk == "char_in")
            # NOT 은 rating / char_on 에만 유효. tag / char_in 은
            # tag_modifier 에 부정형이 이미 있어 중복 → 숨김.
            self._negated_chk.setVisible(lk in ("rating", "char_on"))
        else:
            self._apply_collapse_state()

    def _on_toggle_collapse(self) -> None:
        self._group_collapsed = not self._group_collapsed
        self._apply_collapse_state()

    def _apply_collapse_state(self) -> None:
        """접힘/펼침 상태를 자식 컨테이너 가시성과 버튼 글리프에 반영.

        묶음 방식(AND/OR) 행과 `+ 조건 / + 묶음` 버튼은 유지하고 자식 목록만 접는다.
        구조적 맥락은 남기면서 길어진 자식 리스트만 시야에서 제거하기 위함.
        """
        expanded = not self._group_collapsed
        self._children_container.setVisible(expanded)
        self._collapse_btn.setText("▼" if expanded else "▶")

    def _on_kind_changed(self, new_kind: str) -> None:
        self._update_visibility()
        self._emit_changed()

    def _on_leaf_kind_changed(self, _text: str) -> None:
        self._update_visibility()
        self._emit_changed()

    def _on_add_leaf(self) -> None:
        self._ensure_expanded_on_add()
        self._append_child(make_tag_leaf(""))
        self._emit_changed()

    def _on_add_group(self) -> None:
        self._ensure_expanded_on_add()
        self._append_child(
            ConditionNode(kind="group", logical="AND", children=[])
        )
        self._emit_changed()

    def _ensure_expanded_on_add(self) -> None:
        """접힌 상태에서 자식 추가 시 시각 피드백이 사라지는 것을 방지.

        사용자가 "+ 조건"/"+ 묶음" 을 눌렀는데 _children_container 가 여전히
        hidden 이면 버튼이 먹통처럼 보인다. 추가 전에 강제로 펼친다.
        """
        if self._group_collapsed:
            self._group_collapsed = False
            self._apply_collapse_state()

    def _append_child(self, node: ConditionNode) -> None:
        editor = ConditionNodeEditor(
            node, removable=True, depth=self._depth + 1,
        )
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

    def _set_kind_value(self, value: str) -> None:
        _set_combo_value(self._kind_combo, value, "leaf")

    def _set_leaf_kind_value(self, value: str) -> None:
        _set_combo_value(self._leaf_kind_combo, value, "tag")

    # ------------------------------------------------------------------
    # 스타일
    # ------------------------------------------------------------------

    def _frame_style(self) -> str:
        # 176 UI hotfix:
        # 중첩 child 카드만 더 밝게 칠하면 같은 입력 필드가 섹션마다 다른
        # 명도 위에 올라가 보여 사용자가 "판단 기준/찾을 태그" 영역만 배경이
        # 다르다고 느끼게 된다. 계층은 삭제 버튼/좌측 band/간격으로 표현하고,
        # 카드 바탕은 전부 동일하게 유지한다.
        return (
            f"QFrame#conditionCard {{"
            f"  background-color: {_CARD_BG};"
            f"  border: 1px solid {_CARD_BORDER};"
            f"  border-radius: {get_scaled_size(6)}px;"
            f"}}"
        )

    def _input_style(self) -> str:
        """QLineEdit / QComboBox / QSpinBox 공용 입력 스타일.

        각 위젯에 attach 되면 해당 widget class 에 매칭되는 selector 만 적용.
        QComboBox::drop-down 과 QComboBox QAbstractItemView 를 명시해 Windows
        네이티브 그레이가 arrow 영역/팝업 리스트에 새어들지 않게 한다.
        """
        base = (
            f"  background-color: {_INPUT_BG};"
            f"  color: {DARK_COLORS['text_primary']};"
            f"  border: 1px solid {_INPUT_BORDER};"
            f"  border-radius: {get_scaled_size(4)}px;"
            f"  padding: {get_scaled_size(6)}px {get_scaled_size(8)}px;"
            f"  font-size: {get_scaled_font_size(17)}px;"
            f"  selection-background-color: {DARK_COLORS['accent_blue']};"
        )
        return (
            f"QLineEdit {{{base}}}"
            f"QComboBox {{{base}}}"
            f"QComboBox:hover {{ border-color: {DARK_COLORS['border_light']}; }}"
            f"QComboBox::drop-down {{"
            f"  subcontrol-origin: padding;"
            f"  subcontrol-position: right center;"
            f"  width: {get_scaled_size(20)}px;"
            f"  border: none;"
            f"  background: transparent;"
            f"}}"
            f"QComboBox QAbstractItemView {{"
            f"  background-color: {_INPUT_BG};"
            f"  color: {DARK_COLORS['text_primary']};"
            f"  border: 1px solid {_INPUT_BORDER};"
            f"  selection-background-color: {DARK_COLORS['accent_blue']};"
            f"  outline: 0;"
            f"}}"
            f"QSpinBox {{{base}}}"
            f"QSpinBox::up-button, QSpinBox::down-button {{"
            f"  background: transparent;"
            f"  border: none;"
            f"  width: {get_scaled_size(14)}px;"
            f"}}"
        )
