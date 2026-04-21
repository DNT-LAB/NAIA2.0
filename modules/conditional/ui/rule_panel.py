"""RulePanel — 선택된 Rule 전체 편집 패널.

조건/액션 편집만 담당. 고급 옵션(kind / priority / name / enabled)은 UI 에서
제거되고 내부 필드로 왕복만 유지. raw kind 규칙은 레거시 DSL 형태로 로드될 때만
raw 편집기로 자동 스위칭.

공개 API:
    set_rule(Rule)
    get_rule() -> Rule
    set_rule_position(index, total)  # 요약 카드에 표시용
    set_rule_enabled(bool) / is_rule_enabled()
    get_summary_text() / get_brief_label()
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


_ACTION_KIND_ITEMS = (
    ("태그 추가", "append_list"),
    ("문장 끝에 붙이기", "append"),
    ("태그 교체", "replace"),
    ("캐릭터 사용 여부", "char_set"),
    ("캐릭터 태그 교체", "char_replace"),
)
_FIXED_TARGETS = ("prefix", "main", "postfix", "global_uc", "neg")
_CHAR_TARGET_KINDS = ("char", "uc")
_TARGET_ITEMS = (
    ("프롬프트 앞", "prefix"),
    ("메인 프롬프트", "main"),
    ("프롬프트 뒤", "postfix"),
    ("공용 UC", "global_uc"),
    ("네거티브", "neg"),
    ("캐릭터 프롬프트", "char"),
    ("캐릭터 UC", "uc"),
)
_CHAR_STATE_ITEMS = (
    ("사용", "enabled"),
    ("사용 안 함", "disabled"),
)
_VALID_KINDS = ("block", "raw")
_VALID_ACTION_KINDS = (
    "append_list", "append", "replace", "char_set", "char_replace"
)


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


class RulePanel(QWidget):
    """Rule 조건/액션 편집 패널. 3-pane 구조의 우측 pane."""

    changed = pyqtSignal()

    def __init__(
        self,
        rule: Optional[Rule] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        # 숨김 필드 (UI 없이 roundtrip 만 유지)
        self._rule_kind: str = "block"
        self._rule_priority: int = 100
        self._rule_enabled: bool = True
        self._rule_name: str = ""
        self._rule_position: Optional[tuple[int, int]] = None
        self._build_ui()
        self.set_rule(rule or Rule())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_rule(self, rule: Rule) -> None:
        self._mute(True)
        try:
            self._rule_enabled = bool(rule.enabled)
            self._rule_name = rule.name or ""
            self._rule_priority = int(rule.priority)
            kind = rule.kind if rule.kind in _VALID_KINDS else "block"
            self._rule_kind = kind

            if kind == "raw":
                self._raw_edit.setPlainText(rule.raw_dsl or "")
            else:
                self._condition_editor.set_node(
                    rule.condition or make_tag_leaf("")
                )
                self._sync_action(rule.action or Action())
        finally:
            self._mute(False)
        self._update_visibility()
        self._update_summary()

    def get_rule(self) -> Rule:
        kind = self._rule_kind if self._rule_kind in _VALID_KINDS else "block"
        rule = Rule(
            kind=kind,
            name=self._rule_name,
            enabled=self._rule_enabled,
            priority=int(self._rule_priority),
        )
        if rule.kind == "raw":
            rule.raw_dsl = self._raw_edit.toPlainText()
            rule.condition = None
            rule.action = None
        else:
            rule.condition = self._condition_editor.get_node()
            rule.action = self._read_action()
        return rule

    def set_rule_position(self, index: Optional[int], total: int) -> None:
        self._rule_position = None if index is None else (index, total)
        self._update_summary()

    def set_rule_enabled(self, enabled: bool) -> None:
        self._rule_enabled = bool(enabled)
        self._update_summary()

    def is_rule_enabled(self) -> bool:
        return self._rule_enabled

    def get_summary_text(self) -> str:
        return self._summary_label.text().strip()

    def get_brief_label(self) -> str:
        rule = self.get_rule()
        if rule.kind == "raw":
            return "[고급][DSL]"
        cond = (
            "[묶음]"
            if rule.condition and rule.condition.kind == "group"
            else "[단일]"
        )
        action_map = {
            "append_list": "[추가]",
            "append": "[끝추가]",
            "replace": "[교체]",
            "char_set": "[캐릭터]",
            "char_replace": "[캐릭터교체]",
        }
        status = "[꺼짐] " if not rule.enabled else ""
        return (
            f"{status}{cond}"
            f"{action_map.get(rule.action.kind if rule.action else '', '[규칙]')}"
        )

    # ------------------------------------------------------------------
    # UI 구성
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.setStyleSheet(
            f"QWidget {{"
            f"  color: {DARK_COLORS['text_primary']}; "
            f"  font-size: {get_scaled_font_size(17)}px;"
            f"}}"
            f"QLabel {{"
            f"  border: none;"
            f"  background: transparent;"
            f"  font-size: {get_scaled_font_size(17)}px;"
            f"}}"
            f"QPushButton {{"
            f"  font-size: {get_scaled_font_size(17)}px;"
            f"  padding: {get_scaled_size(5)}px {get_scaled_size(10)}px;"
            f"}}"
            f"QCheckBox {{"
            f"  font-size: {get_scaled_font_size(17)}px;"
            f"}}"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(
            get_scaled_size(8), get_scaled_size(8),
            get_scaled_size(8), get_scaled_size(8),
        )
        root.setSpacing(get_scaled_size(8))

        root.addWidget(self._build_summary_card())

        self._block_container = self._build_block_container()
        root.addWidget(self._block_container)

        self._raw_container = self._build_raw_container()
        root.addWidget(self._raw_container)

        root.addStretch()

    def _build_summary_card(self) -> QWidget:
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{"
            f"  background-color: {DARK_COLORS['bg_secondary']};"
            f"  border: 1px solid {DARK_COLORS['border_light']};"
            f"  border-radius: {get_scaled_size(6)}px;"
            f"}}"
            f"QLabel {{ border: none; background: transparent; }}"
        )
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(
            get_scaled_size(10), get_scaled_size(8),
            get_scaled_size(10), get_scaled_size(8),
        )
        layout.setSpacing(get_scaled_size(4))
        title = QLabel("한 줄 요약")
        title.setStyleSheet(
            f"color: {DARK_COLORS['text_primary']};"
            f" font-weight: bold;"
            f" font-size: {get_scaled_font_size(16)}px;"
        )
        layout.addWidget(title)
        self._summary_label = QLabel("")
        self._summary_label.setWordWrap(True)
        self._summary_label.setStyleSheet(
            f"color: {DARK_COLORS['text_secondary']};"
            f" font-size: {get_scaled_font_size(16)}px;"
        )
        layout.addWidget(self._summary_label)
        return frame

    def _build_block_container(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(get_scaled_size(6))

        layout.addWidget(QLabel("이 조건이 맞으면"))
        self._condition_editor = ConditionNodeEditor()
        self._condition_editor.changed.connect(self._emit_changed)
        layout.addWidget(self._condition_editor)

        layout.addWidget(QLabel("이렇게 바꾸기"))
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
        top.addWidget(QLabel("변경 방식:"))
        self._action_kind_combo = QComboBox()
        _add_combo_items(self._action_kind_combo, _ACTION_KIND_ITEMS)
        self._action_kind_combo.setStyleSheet(self._input_style())
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
        row.addWidget(QLabel("적용 위치:"))
        self._target_kind_combo = QComboBox()
        _add_combo_items(self._target_kind_combo, _TARGET_ITEMS)
        self._target_kind_combo.setStyleSheet(self._input_style())
        self._target_kind_combo.currentTextChanged.connect(
            self._on_target_kind_changed
        )
        row.addWidget(self._target_kind_combo)

        self._target_n_spin = QSpinBox()
        self._target_n_spin.setRange(1, 10)
        self._target_n_spin.setValue(1)
        self._target_n_spin.setStyleSheet(self._input_style())
        self._target_n_spin.valueChanged.connect(self._emit_changed)
        row.addWidget(self._target_n_spin)

        self._target_wildcard_chk = QCheckBox("모든 활성 캐릭터")
        self._target_wildcard_chk.stateChanged.connect(self._emit_changed)
        row.addWidget(self._target_wildcard_chk)
        row.addStretch()
        return w

    def _build_tags_row(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(get_scaled_size(2))
        layout.addWidget(QLabel("추가할 태그:"))
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
        old_row.addWidget(QLabel("찾을 태그:"))
        self._replace_old_edit = QLineEdit()
        self._replace_old_edit.setPlaceholderText("예: __bad_tag__")
        self._replace_old_edit.setStyleSheet(self._input_style())
        self._replace_old_edit.textChanged.connect(self._emit_changed)
        old_row.addWidget(self._replace_old_edit, 1)
        layout.addLayout(old_row)

        layout.addWidget(QLabel("바꿀 태그:"))
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
        top.addWidget(QLabel("대상 캐릭터"))
        self._func_char_index_spin = QSpinBox()
        self._func_char_index_spin.setRange(1, 10)
        self._func_char_index_spin.setStyleSheet(self._input_style())
        self._func_char_index_spin.valueChanged.connect(self._emit_changed)
        top.addWidget(self._func_char_index_spin)

        top.addWidget(QLabel("상태:"))
        self._char_state_combo = QComboBox()
        _add_combo_items(self._char_state_combo, _CHAR_STATE_ITEMS)
        self._char_state_combo.setStyleSheet(self._input_style())
        self._char_state_combo.currentTextChanged.connect(self._emit_changed)
        top.addWidget(self._char_state_combo)
        top.addStretch()
        layout.addLayout(top)

        repl_row = QHBoxLayout()
        repl_row.setSpacing(get_scaled_size(6))
        repl_row.addWidget(QLabel("기존 태그:"))
        self._char_old_edit = QLineEdit()
        self._char_old_edit.setStyleSheet(self._input_style())
        self._char_old_edit.textChanged.connect(self._emit_changed)
        repl_row.addWidget(self._char_old_edit, 1)
        repl_row.addWidget(QLabel("새 태그:"))
        self._char_new_edit = QLineEdit()
        self._char_new_edit.setStyleSheet(self._input_style())
        self._char_new_edit.textChanged.connect(self._emit_changed)
        repl_row.addWidget(self._char_new_edit, 1)
        layout.addLayout(repl_row)
        return w

    def _build_raw_container(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(get_scaled_size(4))
        layout.addWidget(QLabel("고급 DSL 직접 편집"))
        self._raw_edit = QTextEdit()
        self._raw_edit.setAcceptRichText(False)
        self._raw_edit.setPlaceholderText("(cond):action")
        self._raw_edit.setStyleSheet(self._input_style())
        self._raw_edit.textChanged.connect(self._emit_changed)
        self._raw_edit.setMinimumHeight(get_scaled_size(80))
        layout.addWidget(self._raw_edit)
        return w

    # ------------------------------------------------------------------
    # 내부 — sync/read/events
    # ------------------------------------------------------------------

    def _sync_action(self, action: Action) -> None:
        _set_combo_value(
            self._action_kind_combo,
            action.kind if action.kind in _VALID_ACTION_KINDS else "append_list",
            "append_list",
        )
        self._apply_target(action.target or "main")
        self._tags_chip.set_tags(list(action.tags or []))
        self._replace_old_edit.setText(action.old_tag or "")
        self._replace_new_chip.set_tags(list(action.new_tags or []))
        self._func_char_index_spin.setValue(
            max(1, int(action.char_index or 1))
        )
        _set_combo_value(
            self._char_state_combo,
            action.char_state if action.char_state in ("enabled", "disabled") else "enabled",
            "enabled",
        )
        self._char_old_edit.setText(action.char_old_tag or "")
        self._char_new_edit.setText(action.char_new_tag or "")

    def _apply_target(self, target: str) -> None:
        if target in _FIXED_TARGETS:
            _set_combo_value(self._target_kind_combo, target, "main")
            self._target_wildcard_chk.setChecked(False)
            self._target_n_spin.setValue(1)
            return
        if ":" in target:
            kind, _, rest = target.partition(":")
            if kind in _CHAR_TARGET_KINDS:
                _set_combo_value(self._target_kind_combo, kind, "main")
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
        _set_combo_value(self._target_kind_combo, "main", "main")
        self._target_wildcard_chk.setChecked(False)
        self._target_n_spin.setValue(1)

    def _compose_target(self) -> str:
        kind = _combo_value(self._target_kind_combo, "main")
        if kind in _FIXED_TARGETS:
            return kind
        if kind in _CHAR_TARGET_KINDS:
            if self._target_wildcard_chk.isChecked():
                return f"{kind}:*"
            return f"{kind}:{int(self._target_n_spin.value())}"
        return "main"

    def _read_action(self) -> Action:
        kind = _combo_value(self._action_kind_combo, "append_list")
        a = Action(
            kind=kind if kind in _VALID_ACTION_KINDS else "append_list"
        )
        if kind in ("append_list", "append"):
            a.target = self._compose_target()
            a.tags = self._tags_chip.get_tags()
        elif kind == "replace":
            a.old_tag = self._replace_old_edit.text().strip()
            a.new_tags = self._replace_new_chip.get_tags()
        elif kind == "char_set":
            a.char_index = int(self._func_char_index_spin.value())
            a.char_state = _combo_value(self._char_state_combo, "enabled")
        elif kind == "char_replace":
            a.char_index = int(self._func_char_index_spin.value())
            a.char_old_tag = self._char_old_edit.text().strip()
            a.char_new_tag = self._char_new_edit.text().strip()
        return a

    def _update_visibility(self) -> None:
        is_block = self._rule_kind == "block"
        self._block_container.setVisible(is_block)
        self._raw_container.setVisible(not is_block)
        if not is_block:
            return
        ak = _combo_value(self._action_kind_combo, "append_list")
        self._target_row.setVisible(ak in ("append_list", "append"))
        self._tags_row.setVisible(ak in ("append_list", "append"))
        self._replace_row.setVisible(ak == "replace")
        self._func_char_row.setVisible(ak in ("char_set", "char_replace"))
        # target kind 에 따라 spinbox/wildcard 표시
        tk = _combo_value(self._target_kind_combo, "main")
        allow_char = tk in _CHAR_TARGET_KINDS
        self._target_n_spin.setVisible(allow_char)
        self._target_wildcard_chk.setVisible(allow_char)
        # char_set 은 old/new 숨김, char_replace 는 state 숨김
        self._char_state_combo.setVisible(ak == "char_set")
        self._char_old_edit.setVisible(ak == "char_replace")
        self._char_new_edit.setVisible(ak == "char_replace")

    def _on_action_kind_changed(self, _text: str) -> None:
        self._update_visibility()
        self._emit_changed()

    def _on_target_kind_changed(self, _text: str) -> None:
        self._update_visibility()
        self._emit_changed()

    def _emit_changed(self, *_args) -> None:
        self._update_summary()
        self.changed.emit()

    def _mute(self, muted: bool) -> None:
        widgets = [
            self._action_kind_combo,
            self._target_kind_combo, self._target_n_spin,
            self._target_wildcard_chk,
            self._tags_chip, self._replace_old_edit, self._replace_new_chip,
            self._func_char_index_spin, self._char_state_combo,
            self._char_old_edit, self._char_new_edit, self._raw_edit,
        ]
        for w in widgets:
            w.blockSignals(muted)

    def _set_kind_value(self, value: str) -> None:
        """외부/테스트 용 kind 전환. UI 위젯은 없으므로 내부 필드와 visibility 만 갱신."""
        if value not in _VALID_KINDS:
            value = "block"
        self._rule_kind = value
        self._update_visibility()
        self._update_summary()

    def _describe_target(self, target: str) -> str:
        mapping = {
            "prefix": "프롬프트 앞",
            "main": "메인 프롬프트",
            "postfix": "프롬프트 뒤",
            "global_uc": "공용 UC",
            "neg": "네거티브",
        }
        if target in mapping:
            return mapping[target]
        if target == "char:*":
            return "모든 활성 캐릭터 프롬프트"
        if target == "uc:*":
            return "모든 활성 캐릭터 UC"
        if ":" in target:
            kind, _, index = target.partition(":")
            if kind == "char":
                return f"캐릭터 {index} 프롬프트"
            if kind == "uc":
                return f"캐릭터 {index} UC"
        return target or "메인 프롬프트"

    def _describe_condition(self, node: Optional[ConditionNode]) -> str:
        if node is None:
            return "조건 없음"
        if node.kind == "group":
            joiner = " 그리고 " if node.logical == "AND" else " 또는 "
            parts = [
                self._describe_condition(child)
                for child in (node.children or [])
            ]
            parts = [p for p in parts if p]
            if not parts:
                return "비어 있는 조건 묶음"
            return "(" + joiner.join(parts) + ")"
        if node.leaf_kind == "rating":
            text = f"등급이 {node.rating_value or 'e'}"
        elif node.leaf_kind == "char_in":
            mod = "포함"
            if node.char_tag_modifier == "exact":
                mod = "정확히 일치"
            elif node.char_tag_modifier == "not_contains":
                mod = "포함하지 않음"
            elif node.char_tag_modifier == "not_exact":
                mod = "정확히 일치하지 않음"
            text = (
                f"캐릭터 {node.char_index or 1} 안에 "
                f"'{node.char_tag_value or ''}' {mod}"
            )
        elif node.leaf_kind == "char_on":
            text = f"캐릭터 {node.char_index or 1} 슬롯이 켜져 있음"
        else:
            mod = "포함"
            if node.tag_modifier == "exact":
                mod = "정확히 일치"
            elif node.tag_modifier == "not_contains":
                mod = "포함하지 않음"
            elif node.tag_modifier == "not_exact":
                mod = "정확히 일치하지 않음"
            text = f"'{node.tag_value or ''}' {mod}"
        if node.negated:
            return f"{text} 아님"
        return text

    def _describe_action(self, action: Optional[Action]) -> str:
        if action is None:
            return "변경 없음"
        if action.kind in ("append_list", "append"):
            tags = ", ".join(action.tags or []) or "(태그 없음)"
            return f"{self._describe_target(action.target or 'main')}에 {tags} 추가"
        if action.kind == "replace":
            tags = ", ".join(action.new_tags or []) or "(태그 없음)"
            return f"'{action.old_tag or ''}'를 {tags}로 교체"
        if action.kind == "char_set":
            state = "사용" if action.char_state == "enabled" else "사용 안 함"
            return f"캐릭터 {action.char_index or 1}을 {state}"
        if action.kind == "char_replace":
            return (
                f"캐릭터 {action.char_index or 1}의 "
                f"'{action.char_old_tag or ''}'를 "
                f"'{action.char_new_tag or ''}'로 교체"
            )
        return action.kind or "변경 없음"

    def _update_summary(self) -> None:
        rule = self.get_rule()
        order_prefix = ""
        if self._rule_position is not None:
            index, total = self._rule_position
            order_prefix = f"[{index + 1}/{max(total, 1)}] "
        if not rule.enabled:
            self._summary_label.setText(
                f"{order_prefix}이 규칙은 현재 꺼져 있습니다."
            )
            return
        if rule.kind == "raw":
            text = rule.raw_dsl.strip() or "직접 입력할 DSL 이 비어 있습니다."
            self._summary_label.setText(
                f"{order_prefix}고급 DSL 직접 실행: {text}"
            )
            return
        condition_text = self._describe_condition(rule.condition)
        action_text = self._describe_action(rule.action)
        self._summary_label.setText(
            f"{order_prefix}{condition_text}일 때 {action_text}"
        )

    def _input_style(self) -> str:
        return (
            f"background-color: {DARK_COLORS['bg_tertiary']};"
            f" color: {DARK_COLORS['text_primary']};"
            f" border: 1px solid {DARK_COLORS['border']};"
            f" border-radius: {get_scaled_size(4)}px;"
            f" padding: {get_scaled_size(6)}px {get_scaled_size(8)}px;"
            f" font-size: {get_scaled_font_size(17)}px;"
        )
