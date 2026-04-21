"""RulePanel — 선택된 Rule 전체 편집 패널 (Sub-phase 1.4c).

필드: enabled / name / priority / kind (block|raw) + condition(1.4b) + action.
block action 은 5 kind (append_list / append / replace / char_set /
char_replace) 를 visibility 토글로 전환. target 은 fixed 7종 + char/uc[N|*]
구성.

공개 API:
    set_rule(Rule)
    get_rule() -> Rule
    changed  # pyqtSignal
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from modules.conditional.block_model import (
    Action,
    ConditionNode,
    Rule,
    make_tag_leaf,
)
from modules.conditional.ui.chip_list_widget import ChipListWidget
from modules.conditional.ui.condition_editor import ConditionNodeEditor
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from ui.theme import DARK_COLORS


_KIND_CHOICES = ("block", "raw")
_ACTION_KINDS = (
    "append_list", "append", "replace", "char_set", "char_replace"
)
_FIXED_TARGETS = ("prefix", "main", "postfix", "global_uc", "neg")
_CHAR_TARGET_KINDS = ("char", "uc")
_TARGET_CHOICES = _FIXED_TARGETS + _CHAR_TARGET_KINDS
_CHAR_STATES = ("enabled", "disabled")


class RulePanel(QWidget):
    """Rule 편집 패널 (우측 pane 담당)."""

    changed = pyqtSignal()

    def __init__(
        self,
        rule: Optional[Rule] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._build_ui()
        self.set_rule(rule or Rule())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_rule(self, rule: Rule) -> None:
        self._mute(True)
        try:
            self._enabled_chk.setChecked(bool(rule.enabled))
            self._name_edit.setText(rule.name or "")
            self._priority_spin.setValue(int(rule.priority))
            self._kind_combo.setCurrentText(rule.kind or "block")

            if (rule.kind or "block") == "raw":
                self._raw_edit.setPlainText(rule.raw_dsl or "")
            else:
                self._condition_editor.set_node(
                    rule.condition or make_tag_leaf("")
                )
                self._sync_action(rule.action or Action())
        finally:
            self._mute(False)
        self._update_visibility()

    def get_rule(self) -> Rule:
        kind = self._kind_combo.currentText()
        rule = Rule(
            kind=kind if kind in _KIND_CHOICES else "block",
            name=self._name_edit.text().strip(),
            enabled=self._enabled_chk.isChecked(),
            priority=int(self._priority_spin.value()),
        )
        if rule.kind == "raw":
            rule.raw_dsl = self._raw_edit.toPlainText()
            rule.condition = None
            rule.action = None
        else:
            rule.condition = self._condition_editor.get_node()
            rule.action = self._read_action()
        return rule

    # ------------------------------------------------------------------
    # UI 구성
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.setStyleSheet(
            f"QWidget {{ color: {DARK_COLORS['text_primary']}; "
            f"font-size: {get_scaled_font_size(12)}px; }}"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(
            get_scaled_size(8), get_scaled_size(8),
            get_scaled_size(8), get_scaled_size(8),
        )
        root.setSpacing(get_scaled_size(8))

        root.addLayout(self._build_meta_row())

        self._block_container = self._build_block_container()
        root.addWidget(self._block_container)

        self._raw_container = self._build_raw_container()
        root.addWidget(self._raw_container)

        root.addStretch()

    def _build_meta_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(get_scaled_size(6))
        self._enabled_chk = QCheckBox("활성")
        self._enabled_chk.stateChanged.connect(self._emit_changed)
        row.addWidget(self._enabled_chk)

        row.addWidget(QLabel("이름:"))
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("(선택)")
        self._name_edit.textChanged.connect(self._emit_changed)
        row.addWidget(self._name_edit, 1)

        row.addWidget(QLabel("priority:"))
        self._priority_spin = QSpinBox()
        self._priority_spin.setRange(0, 9999)
        self._priority_spin.setValue(100)
        self._priority_spin.valueChanged.connect(self._emit_changed)
        row.addWidget(self._priority_spin)

        row.addWidget(QLabel("kind:"))
        self._kind_combo = QComboBox()
        self._kind_combo.addItems(list(_KIND_CHOICES))
        self._kind_combo.currentTextChanged.connect(self._on_kind_changed)
        row.addWidget(self._kind_combo)
        return row

    def _build_block_container(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(get_scaled_size(6))

        layout.addWidget(QLabel("조건:"))
        self._condition_editor = ConditionNodeEditor()
        self._condition_editor.changed.connect(self._emit_changed)
        layout.addWidget(self._condition_editor)

        layout.addWidget(QLabel("액션:"))
        layout.addWidget(self._build_action_panel())
        return w

    def _build_action_panel(self) -> QWidget:
        container = QFrame()
        container.setFrameShape(QFrame.Shape.StyledPanel)
        container.setStyleSheet(
            f"QFrame {{"
            f"  background-color: {DARK_COLORS['bg_secondary']};"
            f"  border: 1px solid {DARK_COLORS['border']};"
            f"  border-radius: {get_scaled_size(4)}px;"
            f"}}"
        )
        layout = QVBoxLayout(container)
        layout.setContentsMargins(
            get_scaled_size(6), get_scaled_size(6),
            get_scaled_size(6), get_scaled_size(6),
        )
        layout.setSpacing(get_scaled_size(4))

        top = QHBoxLayout()
        top.setSpacing(get_scaled_size(6))
        top.addWidget(QLabel("종류:"))
        self._action_kind_combo = QComboBox()
        self._action_kind_combo.addItems(list(_ACTION_KINDS))
        self._action_kind_combo.currentTextChanged.connect(
            self._on_action_kind_changed
        )
        top.addWidget(self._action_kind_combo)
        top.addStretch()
        layout.addLayout(top)

        self._target_row = self._build_target_row()
        layout.addWidget(self._target_row)
        self._tags_row = self._build_tags_row()
        layout.addWidget(self._tags_row)
        self._replace_row = self._build_replace_row()
        layout.addWidget(self._replace_row)
        self._func_char_row = self._build_func_char_row()
        layout.addWidget(self._func_char_row)
        return container

    def _build_target_row(self) -> QWidget:
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(get_scaled_size(6))
        row.addWidget(QLabel("target:"))
        self._target_kind_combo = QComboBox()
        self._target_kind_combo.addItems(list(_TARGET_CHOICES))
        self._target_kind_combo.currentTextChanged.connect(
            self._on_target_kind_changed
        )
        row.addWidget(self._target_kind_combo)

        self._target_n_spin = QSpinBox()
        self._target_n_spin.setRange(1, 10)
        self._target_n_spin.setValue(1)
        self._target_n_spin.valueChanged.connect(self._emit_changed)
        row.addWidget(self._target_n_spin)

        self._target_wildcard_chk = QCheckBox("* (all)")
        self._target_wildcard_chk.stateChanged.connect(self._emit_changed)
        row.addWidget(self._target_wildcard_chk)
        row.addStretch()
        return w

    def _build_tags_row(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(get_scaled_size(2))
        layout.addWidget(QLabel("tags:"))
        self._tags_chip = ChipListWidget(placeholder="태그 추가 (Enter)")
        self._tags_chip.tags_changed.connect(self._emit_changed)
        layout.addWidget(self._tags_chip)
        return w

    def _build_replace_row(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(get_scaled_size(4))

        old_row = QHBoxLayout()
        old_row.setSpacing(get_scaled_size(6))
        old_row.addWidget(QLabel("old_tag:"))
        self._replace_old_edit = QLineEdit()
        self._replace_old_edit.setPlaceholderText(
            "교체 대상 (타겟명 전체 or 패턴 __tag__)"
        )
        self._replace_old_edit.textChanged.connect(self._emit_changed)
        old_row.addWidget(self._replace_old_edit, 1)
        layout.addLayout(old_row)

        layout.addWidget(QLabel("new_tags:"))
        self._replace_new_chip = ChipListWidget(
            placeholder="교체 후 태그 추가"
        )
        self._replace_new_chip.tags_changed.connect(self._emit_changed)
        layout.addWidget(self._replace_new_chip)
        return w

    def _build_func_char_row(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(get_scaled_size(4))

        top = QHBoxLayout()
        top.setSpacing(get_scaled_size(6))
        top.addWidget(QLabel("char #"))
        self._func_char_index_spin = QSpinBox()
        self._func_char_index_spin.setRange(1, 10)
        self._func_char_index_spin.valueChanged.connect(self._emit_changed)
        top.addWidget(self._func_char_index_spin)

        top.addWidget(QLabel("state:"))
        self._char_state_combo = QComboBox()
        self._char_state_combo.addItems(list(_CHAR_STATES))
        self._char_state_combo.currentTextChanged.connect(self._emit_changed)
        top.addWidget(self._char_state_combo)
        top.addStretch()
        layout.addLayout(top)

        repl_row = QHBoxLayout()
        repl_row.setSpacing(get_scaled_size(6))
        repl_row.addWidget(QLabel("old:"))
        self._char_old_edit = QLineEdit()
        self._char_old_edit.textChanged.connect(self._emit_changed)
        repl_row.addWidget(self._char_old_edit, 1)
        repl_row.addWidget(QLabel("new:"))
        self._char_new_edit = QLineEdit()
        self._char_new_edit.textChanged.connect(self._emit_changed)
        repl_row.addWidget(self._char_new_edit, 1)
        layout.addLayout(repl_row)
        return w

    def _build_raw_container(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(get_scaled_size(4))
        layout.addWidget(QLabel("raw DSL (블록 미지원 레거시 보존용):"))
        self._raw_edit = QTextEdit()
        self._raw_edit.setAcceptRichText(False)
        self._raw_edit.setPlaceholderText("(cond):action")
        self._raw_edit.textChanged.connect(self._emit_changed)
        self._raw_edit.setMinimumHeight(get_scaled_size(80))
        layout.addWidget(self._raw_edit)
        return w

    # ------------------------------------------------------------------
    # 내부 — sync/read/events
    # ------------------------------------------------------------------

    def _sync_action(self, action: Action) -> None:
        self._action_kind_combo.setCurrentText(
            action.kind if action.kind in _ACTION_KINDS else "append_list"
        )
        self._apply_target(action.target or "main")
        self._tags_chip.set_tags(list(action.tags or []))
        self._replace_old_edit.setText(action.old_tag or "")
        self._replace_new_chip.set_tags(list(action.new_tags or []))
        self._func_char_index_spin.setValue(
            max(1, int(action.char_index or 1))
        )
        self._char_state_combo.setCurrentText(
            action.char_state if action.char_state in _CHAR_STATES else "enabled"
        )
        self._char_old_edit.setText(action.char_old_tag or "")
        self._char_new_edit.setText(action.char_new_tag or "")

    def _apply_target(self, target: str) -> None:
        if target in _FIXED_TARGETS:
            self._target_kind_combo.setCurrentText(target)
            self._target_wildcard_chk.setChecked(False)
            self._target_n_spin.setValue(1)
            return
        if ":" in target:
            kind, _, rest = target.partition(":")
            if kind in _CHAR_TARGET_KINDS:
                self._target_kind_combo.setCurrentText(kind)
                if rest == "*":
                    self._target_wildcard_chk.setChecked(True)
                    self._target_n_spin.setValue(1)
                    return
                try:
                    self._target_n_spin.setValue(max(1, int(rest)))
                    self._target_wildcard_chk.setChecked(False)
                    return
                except ValueError:
                    pass
        # fallback
        self._target_kind_combo.setCurrentText("main")
        self._target_wildcard_chk.setChecked(False)
        self._target_n_spin.setValue(1)

    def _compose_target(self) -> str:
        kind = self._target_kind_combo.currentText()
        if kind in _FIXED_TARGETS:
            return kind
        if kind in _CHAR_TARGET_KINDS:
            if self._target_wildcard_chk.isChecked():
                return f"{kind}:*"
            return f"{kind}:{int(self._target_n_spin.value())}"
        return "main"

    def _read_action(self) -> Action:
        kind = self._action_kind_combo.currentText()
        a = Action(kind=kind if kind in _ACTION_KINDS else "append_list")
        if kind in ("append_list", "append"):
            a.target = self._compose_target()
            a.tags = self._tags_chip.get_tags()
        elif kind == "replace":
            a.old_tag = self._replace_old_edit.text().strip()
            a.new_tags = self._replace_new_chip.get_tags()
        elif kind == "char_set":
            a.char_index = int(self._func_char_index_spin.value())
            a.char_state = self._char_state_combo.currentText()
        elif kind == "char_replace":
            a.char_index = int(self._func_char_index_spin.value())
            a.char_old_tag = self._char_old_edit.text().strip()
            a.char_new_tag = self._char_new_edit.text().strip()
        return a

    def _update_visibility(self) -> None:
        is_block = self._kind_combo.currentText() == "block"
        self._block_container.setVisible(is_block)
        self._raw_container.setVisible(not is_block)
        if not is_block:
            return
        ak = self._action_kind_combo.currentText()
        self._target_row.setVisible(ak in ("append_list", "append"))
        self._tags_row.setVisible(ak in ("append_list", "append"))
        self._replace_row.setVisible(ak == "replace")
        self._func_char_row.setVisible(ak in ("char_set", "char_replace"))
        # target kind 에 따라 spinbox/wildcard 표시
        tk = self._target_kind_combo.currentText()
        allow_char = tk in _CHAR_TARGET_KINDS
        self._target_n_spin.setVisible(allow_char)
        self._target_wildcard_chk.setVisible(allow_char)
        # char_set 은 old/new 숨김, char_replace 는 state 숨김
        self._char_state_combo.setVisible(ak == "char_set")
        self._char_old_edit.setVisible(ak == "char_replace")
        self._char_new_edit.setVisible(ak == "char_replace")

    def _on_kind_changed(self, _text: str) -> None:
        self._update_visibility()
        self._emit_changed()

    def _on_action_kind_changed(self, _text: str) -> None:
        self._update_visibility()
        self._emit_changed()

    def _on_target_kind_changed(self, _text: str) -> None:
        self._update_visibility()
        self._emit_changed()

    def _emit_changed(self, *_args) -> None:
        self.changed.emit()

    def _mute(self, muted: bool) -> None:
        widgets = [
            self._enabled_chk, self._name_edit, self._priority_spin,
            self._kind_combo, self._action_kind_combo,
            self._target_kind_combo, self._target_n_spin,
            self._target_wildcard_chk,
            self._tags_chip, self._replace_old_edit, self._replace_new_chip,
            self._func_char_index_spin, self._char_state_combo,
            self._char_old_edit, self._char_new_edit, self._raw_edit,
        ]
        for w in widgets:
            w.blockSignals(muted)
