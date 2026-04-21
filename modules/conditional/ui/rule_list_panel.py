"""RuleListPanel — 규칙 목록 패널 (3-pane 중앙).

기존 PresetPanel 의 규칙 목록 섹션을 분리. 규칙 CRUD / 켜기끄기 / 위아래 이동
버튼만 소유한다. 엔진 옵션은 더 이상 UI 에 없고, 고급 옵션(kind/priority)은
RulePanel 에서도 제거되어 내부 필드로만 관리된다.

공개 API:
    set_rulebook(Optional[RuleBook])
    set_selected_rule(int)
    get_selected_rule_index() -> int  # -1 = 선택 없음
    set_rule_summary_text(str)

시그널:
    rule_selected(int)                   # -1 = 선택 없음
    rule_add_requested()
    rule_delete_requested(int)
    rule_enabled_toggle_requested(int)
    rule_move_up_requested(int)
    rule_move_down_requested(int)
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from modules.conditional.block_model import Rule, RuleBook
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from ui.theme import DARK_COLORS


class RuleListPanel(QWidget):
    rule_selected = pyqtSignal(int)
    rule_add_requested = pyqtSignal()
    rule_delete_requested = pyqtSignal(int)
    rule_enabled_toggle_requested = pyqtSignal(int)
    rule_move_up_requested = pyqtSignal(int)
    rule_move_down_requested = pyqtSignal(int)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._rulebook: Optional[RuleBook] = None
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_rulebook(self, book: Optional[RuleBook]) -> None:
        self._rulebook = book
        self._rule_list.clear()
        if book is None:
            self._update_rule_button_state()
            return
        for idx, r in enumerate(book.sorted_rules(), start=1):
            item = QListWidgetItem(self._rule_summary(r, idx))
            item.setForeground(QColor(DARK_COLORS['text_primary']))
            self._rule_list.addItem(item)
        self._update_rule_button_state()

    def set_selected_rule(self, idx: int) -> None:
        self._rule_list.blockSignals(True)
        try:
            if 0 <= idx < self._rule_list.count():
                self._rule_list.clearSelection()
                self._rule_list.setCurrentRow(idx)
                item = self._rule_list.item(idx)
                if item is not None:
                    item.setSelected(True)
                if self._rulebook is not None:
                    self._rule_summary_label.setText(
                        self._rule_summary(
                            self._rulebook.sorted_rules()[idx], idx + 1
                        )
                    )
            else:
                self._rule_list.clearSelection()
                self._rule_summary_label.setText(
                    "선택한 규칙 요약이 여기에 표시됩니다."
                )
        finally:
            self._rule_list.blockSignals(False)
        self._update_rule_button_state()

    def get_selected_rule_index(self) -> int:
        return int(self._rule_list.currentRow())

    def set_rule_summary_text(self, text: str) -> None:
        self._rule_summary_label.setText(
            text or "선택한 규칙 요약이 여기에 표시됩니다."
        )

    # ------------------------------------------------------------------
    # UI 구성
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.setStyleSheet(self._panel_style())
        root = QVBoxLayout(self)
        root.setContentsMargins(
            get_scaled_size(8), get_scaled_size(8),
            get_scaled_size(8), get_scaled_size(8),
        )
        root.setSpacing(get_scaled_size(8))
        root.addWidget(self._build_list_section(), stretch=1)

    def _build_list_section(self) -> QWidget:
        w = QFrame()
        w.setStyleSheet(self._section_style())
        layout = QVBoxLayout(w)
        layout.setContentsMargins(
            get_scaled_size(6), get_scaled_size(6),
            get_scaled_size(6), get_scaled_size(6),
        )
        layout.setSpacing(get_scaled_size(4))

        layout.addWidget(self._section_label("규칙 목록"))
        self._rule_summary_label = QLabel("선택한 규칙 요약이 여기에 표시됩니다.")
        self._rule_summary_label.setWordWrap(True)
        self._rule_summary_label.setStyleSheet(
            f"color: {DARK_COLORS['text_secondary']};"
            f" font-size: {get_scaled_font_size(16)}px;"
        )
        layout.addWidget(self._rule_summary_label)

        self._rule_list = QListWidget()
        self._rule_list.currentRowChanged.connect(
            self._on_rule_row_changed
        )
        layout.addWidget(self._rule_list, stretch=1)

        # CRUD 버튼
        crud_row = QHBoxLayout()
        crud_row.setSpacing(get_scaled_size(4))
        self._toggle_enabled_btn = QPushButton("켜기/끄기")
        self._toggle_enabled_btn.clicked.connect(
            self._on_rule_toggle_enabled_clicked
        )
        crud_row.addWidget(self._toggle_enabled_btn)
        add_btn = QPushButton("+ 새 규칙")
        add_btn.clicked.connect(lambda: self.rule_add_requested.emit())
        crud_row.addWidget(add_btn)
        del_btn = QPushButton("− 선택 제거")
        del_btn.clicked.connect(self._on_rule_delete_clicked)
        crud_row.addWidget(del_btn)
        crud_row.addStretch()
        layout.addLayout(crud_row)

        # 이동 버튼
        move_row = QHBoxLayout()
        move_row.setSpacing(get_scaled_size(4))
        self._move_up_btn = QPushButton("↑ 위로")
        self._move_up_btn.clicked.connect(self._on_rule_move_up_clicked)
        move_row.addWidget(self._move_up_btn)
        self._move_down_btn = QPushButton("↓ 아래로")
        self._move_down_btn.clicked.connect(self._on_rule_move_down_clicked)
        move_row.addWidget(self._move_down_btn)
        move_row.addStretch()
        layout.addLayout(move_row)
        return w

    # ------------------------------------------------------------------
    # 내부 — 상태/이벤트
    # ------------------------------------------------------------------

    def _rule_summary(self, rule: Rule, order: int) -> str:
        status = "●" if rule.enabled else "○"
        badge = self._rule_badges(rule)
        detail = self._rule_detail(rule)
        return f"{order}. {status} {badge} {detail}"

    def _rule_badges(self, rule: Rule) -> str:
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
        action = action_map.get(
            rule.action.kind if rule.action else "", "[규칙]"
        )
        return f"{cond}{action}"

    def _rule_detail(self, rule: Rule) -> str:
        if rule.kind == "raw":
            return "직접 DSL 편집"
        node = rule.condition
        if node is None:
            return "(조건 없음)"
        if node.kind == "group":
            return "조건 묶음"
        if node.leaf_kind == "tag":
            value = node.tag_value or "(태그 없음)"
            return value if len(value) <= 20 else value[:17] + "..."
        if node.leaf_kind == "rating":
            return f"등급 {node.rating_value or 'e'}"
        if node.leaf_kind == "char_in":
            return f"캐릭터 {node.char_index or 1} 태그"
        if node.leaf_kind == "char_on":
            return f"캐릭터 {node.char_index or 1} 사용"
        return "규칙"

    def _update_rule_button_state(self) -> None:
        idx = self._rule_list.currentRow()
        count = self._rule_list.count()
        has_selection = 0 <= idx < count
        self._toggle_enabled_btn.setEnabled(has_selection)
        self._move_up_btn.setEnabled(has_selection and idx > 0)
        self._move_down_btn.setEnabled(has_selection and idx < count - 1)
        if has_selection and self._rulebook is not None:
            rule = self._rulebook.sorted_rules()[idx]
            self._toggle_enabled_btn.setText(
                "선택 규칙 끄기" if rule.enabled else "선택 규칙 켜기"
            )
        else:
            self._toggle_enabled_btn.setText("켜기/끄기")

    def _on_rule_row_changed(self, idx: int) -> None:
        self._update_rule_button_state()
        if 0 <= idx < self._rule_list.count() and self._rulebook is not None:
            self._rule_summary_label.setText(
                self._rule_summary(self._rulebook.sorted_rules()[idx], idx + 1)
            )
        else:
            self._rule_summary_label.setText(
                "선택한 규칙 요약이 여기에 표시됩니다."
            )
        self.rule_selected.emit(int(idx))

    def _on_rule_delete_clicked(self) -> None:
        idx = self._rule_list.currentRow()
        if idx >= 0:
            self.rule_delete_requested.emit(int(idx))

    def _on_rule_toggle_enabled_clicked(self) -> None:
        idx = self._rule_list.currentRow()
        if idx >= 0:
            self.rule_enabled_toggle_requested.emit(int(idx))

    def _on_rule_move_up_clicked(self) -> None:
        idx = self._rule_list.currentRow()
        if idx > 0:
            self.rule_move_up_requested.emit(int(idx))

    def _on_rule_move_down_clicked(self) -> None:
        idx = self._rule_list.currentRow()
        if 0 <= idx < self._rule_list.count() - 1:
            self.rule_move_down_requested.emit(int(idx))

    # ------------------------------------------------------------------
    # 스타일
    # ------------------------------------------------------------------

    def _panel_style(self) -> str:
        return (
            f"QWidget {{"
            f"  background-color: {DARK_COLORS['bg_primary']};"
            f"  color: {DARK_COLORS['text_primary']};"
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
            f"QListWidget {{"
            f"  background-color: {DARK_COLORS['bg_tertiary']};"
            f"  color: {DARK_COLORS['text_primary']};"
            f"  border: 1px solid {DARK_COLORS['border']};"
            f"  border-radius: {get_scaled_size(3)}px;"
            f"  font-size: {get_scaled_font_size(17)}px;"
            f"}}"
            f"QListWidget::item:selected {{"
            f"  background-color: {DARK_COLORS['accent_blue']};"
            f"  color: {DARK_COLORS['text_primary']};"
            f"}}"
        )

    def _section_style(self) -> str:
        return (
            f"QFrame {{"
            f"  background-color: {DARK_COLORS['bg_secondary']};"
            f"  border: 1px solid {DARK_COLORS['border']};"
            f"  border-radius: {get_scaled_size(4)}px;"
            f"}}"
        )

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(
            f"color: {DARK_COLORS['text_primary']};"
            f" font-size: {get_scaled_font_size(18)}px;"
            f" font-weight: bold;"
        )
        return label
