"""RuleListPanel — 규칙 목록 패널 (3-pane 중앙).

기존 PresetPanel 의 규칙 목록 섹션을 분리. 규칙 CRUD / 켜기끄기 / 위아래 이동
버튼만 소유한다. 엔진 옵션은 더 이상 UI 에 없고, 고급 옵션(kind/priority)은
RulePanel 에서도 제거되어 내부 필드로만 관리된다.

공개 API:
    set_rulebook(Optional[RuleBook])
    set_selected_rule(int)
    get_selected_rule_index() -> int  # -1 = 선택 없음

시그널:
    rule_selected(int)                   # -1 = 선택 없음
    rule_add_requested()
    rule_delete_requested(int)
    rule_enabled_toggle_requested(int)
    rule_move_up_requested(int)
    rule_move_down_requested(int)
"""

from __future__ import annotations

from typing import Optional, Set

from PyQt6.QtCore import Qt, QRect, QSize, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from modules.conditional.block_model import Rule, RuleBook
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from ui.theme import DARK_COLORS


# 규칙 종류 배지 팔레트. DARK_COLORS 의 accent/warning 계열을 그대로 활용한다.
_KIND_PALETTE = {
    "leaf":  ("#42A5F5", "단일"),
    "group": ("#AB47BC", "묶음"),
    "raw":   ("#FF9800", "고급"),
}

_ACTION_PALETTE = {
    "append_list":  ("#4CAF50", "추가"),
    "append":       ("#26A69A", "끝추가"),
    "replace":      ("#FF7043", "교체"),
    "char_set":     ("#EC407A", "캐릭터"),
    "char_append":  ("#5C6BC0", "캐추가"),
    "char_replace": ("#AB47BC", "캐교체"),
    "raw":          ("#FF9800", "DSL"),
}


class RuleItemDelegate(QStyledItemDelegate):
    """규칙 리스트 커스텀 페인터.

    아이템 데이터 (UserRole) 형식:
        {
            "enabled": bool,
            "rule_id": str,
            "kind_color": "#RRGGBB", "kind_label": str,
            "action_color": "#RRGGBB", "action_label": str,
            "detail": str,
            "order": int,
        }

    panel 을 옵션 인자로 받아 시뮬레이션 하이라이트 상태를 조회한다.
    """

    def __init__(self, parent, panel=None):
        super().__init__(parent)
        self._panel = panel  # RuleListPanel; get_highlighted_ids() 조회용

    def sizeHint(self, option, index):
        return QSize(0, get_scaled_size(36))

    def paint(self, painter: QPainter, option, index):
        data = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict):
            super().paint(painter, option, index)
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        enabled = bool(data.get("enabled", True))

        # 시뮬레이션 매칭 하이라이트 — 선택/호버 배경 위에 연노랑 overlay.
        # panel 이 없거나 하이라이트 set 이 비었으면 no-op.
        highlighted = False
        if self._panel is not None:
            rid = data.get("rule_id")
            if rid and rid in self._panel.get_highlighted_ids():
                highlighted = True

        # 선택/호버 배경 — 기본 QListWidget::item:selected 규칙을 대체
        if selected:
            painter.fillRect(option.rect, QColor(DARK_COLORS["accent_blue"]))
        elif hovered:
            painter.fillRect(option.rect, QColor(DARK_COLORS["bg_hover"]))

        # 하이라이트 overlay — 선택 상태여도 시각적으로 구분되도록 alpha 혼합.
        if highlighted:
            overlay = QColor("#FFF59D")  # 연노랑 (Material Yellow 200)
            overlay.setAlpha(110 if selected else 160)
            painter.fillRect(option.rect, overlay)

        pad_x = get_scaled_size(10)
        pad_y = get_scaled_size(6)
        rect = option.rect.adjusted(pad_x, pad_y, -pad_x, -pad_y)
        cy = rect.center().y()
        x = rect.left()
        gap = get_scaled_size(6)

        # 상태 점
        dot_r = get_scaled_size(4)
        dot_color = QColor(
            DARK_COLORS["success"] if enabled else DARK_COLORS["text_disabled"]
        )
        painter.setBrush(QBrush(dot_color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(
            QRect(x, cy - dot_r, dot_r * 2, dot_r * 2)
        )
        x += dot_r * 2 + gap

        # 종류/액션 배지
        badge_font = QFont(painter.font())
        badge_font.setPointSize(max(7, badge_font.pointSize() - 1))
        badge_font.setBold(True)
        x = self._draw_badge(
            painter, badge_font, x, rect,
            data.get("kind_label", ""), data.get("kind_color", "#666"),
            enabled,
        )
        x += gap
        x = self._draw_badge(
            painter, badge_font, x, rect,
            data.get("action_label", ""), data.get("action_color", "#666"),
            enabled,
        )
        x += gap * 2

        # 인덱스 (우측 정렬, 작게, 뮤트)
        idx_font = QFont(painter.font())
        idx_font.setPointSize(max(8, idx_font.pointSize() - 2))
        painter.setFont(idx_font)
        idx_str = f"#{int(data.get('order', index.row() + 1))}"
        idx_fm = QFontMetrics(idx_font)
        idx_w = idx_fm.horizontalAdvance(idx_str)
        idx_color = QColor(
            DARK_COLORS["text_secondary"]
            if enabled else DARK_COLORS["text_disabled"]
        )
        if selected:
            idx_color = QColor("#E3F2FD")
        painter.setPen(idx_color)
        painter.drawText(
            QRect(rect.right() - idx_w, rect.top(), idx_w, rect.height()),
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            idx_str,
        )

        # 상세 텍스트
        detail_font = QFont(painter.font())
        detail_font.setPointSize(idx_font.pointSize() + 2)
        painter.setFont(detail_font)
        detail_color = (
            QColor(DARK_COLORS["text_primary"])
            if enabled else QColor(DARK_COLORS["text_disabled"])
        )
        if selected:
            detail_color = QColor("#FFFFFF")
        painter.setPen(detail_color)
        detail_rect = QRect(
            x, rect.top(),
            rect.right() - idx_w - x - gap, rect.height(),
        )
        elided = QFontMetrics(detail_font).elidedText(
            str(data.get("detail", "")),
            Qt.TextElideMode.ElideRight,
            max(detail_rect.width(), 0),
        )
        painter.drawText(
            detail_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            elided,
        )

        painter.restore()

    def _draw_badge(
        self,
        painter: QPainter,
        font: QFont,
        x: int,
        row_rect: QRect,
        label: str,
        color_hex: str,
        enabled: bool,
    ) -> int:
        if not label:
            return x
        painter.setFont(font)
        fm = QFontMetrics(font)
        pad_x = get_scaled_size(7)
        pad_y = get_scaled_size(2)
        text_w = fm.horizontalAdvance(label)
        badge_w = text_w + pad_x * 2
        badge_h = fm.height() + pad_y * 2
        y = row_rect.center().y() - badge_h // 2

        color = QColor(color_hex)
        if not enabled:
            # 비활성 규칙은 배지 채도 낮춤 (hsv value ↓ + alpha)
            color.setAlpha(140)

        painter.setBrush(QBrush(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(
            QRect(x, y, badge_w, badge_h),
            get_scaled_size(3), get_scaled_size(3),
        )
        painter.setPen(QColor("#FFFFFF") if enabled else QColor("#DDDDDD"))
        painter.drawText(
            QRect(x, y, badge_w, badge_h),
            int(Qt.AlignmentFlag.AlignCenter),
            label,
        )
        return x + badge_w


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
        # 시뮬레이션 매칭 하이라이트 — 규칙 id 집합. 델리게이트가 조회해서
        # 연노랑 overlay 를 그린다. 사용자가 다른 규칙을 선택할 때 자동 해제
        # (`_on_rule_row_changed` 에서 `clear_highlights()` 호출).
        self._highlighted_ids: Set[str] = set()
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_rulebook(self, book: Optional[RuleBook]) -> None:
        self._rulebook = book
        # 175: 프로그래밍적 리빌드 중 QListWidget.clear() 가 currentRowChanged(-1)
        # 를 스퍼리어스하게 발행 → 상위 편집기가 선택 해제로 오해하여 RulePanel
        # 을 empty 로 리셋하는 문제 방지. 리빌드 동안 시그널 차단.
        self._rule_list.blockSignals(True)
        try:
            self._rule_list.clear()
            if book is None:
                return
            for idx, r in enumerate(book.sorted_rules(), start=1):
                # 델리게이트 렌더용 dict. 접근성 fallback 으로 DisplayRole 도
                # 평문 요약을 유지한다 (스크린리더 / 기본 스타일).
                item = QListWidgetItem(self._rule_summary(r, idx))
                item.setData(
                    Qt.ItemDataRole.UserRole, self._rule_to_item_data(r, idx)
                )
                self._rule_list.addItem(item)
        finally:
            self._rule_list.blockSignals(False)
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
            else:
                self._rule_list.clearSelection()
        finally:
            self._rule_list.blockSignals(False)
        self._update_rule_button_state()

    def get_selected_rule_index(self) -> int:
        return int(self._rule_list.currentRow())

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

        self._rule_list = QListWidget()
        self._rule_list.setMouseTracking(True)
        self._rule_list.setUniformItemSizes(True)
        # 델리게이트에 panel 참조를 주입 — 시뮬레이션 매칭 id 집합 조회용.
        self._rule_list.setItemDelegate(
            RuleItemDelegate(self._rule_list, panel=self)
        )
        self._rule_list.currentRowChanged.connect(
            self._on_rule_row_changed
        )
        layout.addWidget(self._rule_list, stretch=1)

        # CRUD 버튼 — 각 버튼 stretch=1 로 row 전체 폭을 균등 분할.
        # addStretch() 제거: 남는 공간을 trailing 빈 자리가 아니라 버튼이 흡수.
        crud_row = QHBoxLayout()
        crud_row.setSpacing(get_scaled_size(4))
        self._toggle_enabled_btn = QPushButton("켜기/끄기")
        self._toggle_enabled_btn.setStyleSheet(self._toggle_btn_style())
        self._toggle_enabled_btn.clicked.connect(
            self._on_rule_toggle_enabled_clicked
        )
        crud_row.addWidget(self._toggle_enabled_btn, 1)
        add_btn = QPushButton("+ 새 규칙")
        add_btn.clicked.connect(lambda: self.rule_add_requested.emit())
        crud_row.addWidget(add_btn, 1)
        del_btn = QPushButton("− 선택 제거")
        # H1: 파괴적 액션 시각 구분 — 평상시 중립, hover/pressed 시 빨간 강조.
        del_btn.setStyleSheet(self._danger_btn_style())
        del_btn.clicked.connect(self._on_rule_delete_clicked)
        crud_row.addWidget(del_btn, 1)
        layout.addLayout(crud_row)

        # 이동 버튼
        move_row = QHBoxLayout()
        move_row.setSpacing(get_scaled_size(4))
        self._move_up_btn = QPushButton("↑ 위로")
        self._move_up_btn.clicked.connect(self._on_rule_move_up_clicked)
        move_row.addWidget(self._move_up_btn, 1)
        self._move_down_btn = QPushButton("↓ 아래로")
        self._move_down_btn.clicked.connect(self._on_rule_move_down_clicked)
        move_row.addWidget(self._move_down_btn, 1)
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

    def _rule_to_item_data(self, rule: Rule, order: int) -> dict:
        """델리게이트 렌더용 평탄화 dict."""
        if rule.kind == "raw":
            k_color, k_label = _KIND_PALETTE["raw"]
            a_color, a_label = _ACTION_PALETTE["raw"]
        else:
            if rule.condition and rule.condition.kind == "group":
                k_color, k_label = _KIND_PALETTE["group"]
            else:
                k_color, k_label = _KIND_PALETTE["leaf"]
            akind = rule.action.kind if rule.action else ""
            a_color, a_label = _ACTION_PALETTE.get(
                akind, ("#666666", "규칙")
            )
        return {
            "enabled": bool(rule.enabled),
            "rule_id": rule.id,  # 시뮬 하이라이트 매칭 키
            "kind_color": k_color,
            "kind_label": k_label,
            "action_color": a_color,
            "action_label": a_label,
            "detail": self._rule_detail(rule),
            "order": int(order),
        }

    # ------------------------------------------------------------------
    # 시뮬레이션 하이라이트
    # ------------------------------------------------------------------

    def get_highlighted_ids(self) -> Set[str]:
        """델리게이트가 paint 중 조회. 편집기가 직접 mutate 하지 않도록 copy."""
        return set(self._highlighted_ids)

    def set_highlighted_ids(self, ids) -> None:
        """매칭된 규칙 id 집합 설정 → 델리게이트가 연노랑 overlay 로 렌더.

        Persistent: 사용자가 다른 규칙을 선택하면 `_on_rule_row_changed` 가
        `clear_highlights()` 를 호출하여 자동 해제. 타이머 없음.
        """
        self._highlighted_ids = set(ids) if ids else set()
        viewport = self._rule_list.viewport()
        if viewport is not None:
            viewport.update()

    def clear_highlights(self) -> None:
        self._highlighted_ids = set()
        viewport = self._rule_list.viewport()
        if viewport is not None:
            viewport.update()

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
            "char_append": "[캐릭터추가]",
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
        # 사용자가 규칙을 선택/전환하면 시뮬 하이라이트 해제. 프로그래밍적
        # 호출(set_selected_rule)은 blockSignals 로 이 핸들러가 발동하지 않으므로
        # 편집기가 규칙 추가/삭제/이동 후에 복원하는 선택은 하이라이트를
        # 보존한다.
        if self._highlighted_ids:
            self.clear_highlights()
        self._update_rule_button_state()
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
            f"  outline: 0;"
            f"}}"
            # 선택/호버 배경은 RuleItemDelegate 가 직접 페인팅한다.
            # 여기서 ::item:selected 를 지정하면 델리게이트 paint 전에
            # 기본 selection highlight 가 덧칠돼 배지 색을 가린다.
            f"QListWidget::item {{"
            f"  border: none;"
            f"  padding: 0px;"
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

    def _danger_btn_style(self) -> str:
        """파괴적 액션(선택 제거) — 평상시 중립, hover 시 빨간 강조.
        실수로 누르는 것을 막기 위해 hover 에서만 경고 색상을 표출한다.
        """
        return (
            f"QPushButton {{"
            f"  background-color: {DARK_COLORS['bg_tertiary']};"
            f"  color: {DARK_COLORS['text_primary']};"
            f"  border: 1px solid {DARK_COLORS['border']};"
            f"  border-radius: {get_scaled_size(3)}px;"
            f"  font-size: {get_scaled_font_size(17)}px;"
            f"  padding: {get_scaled_size(5)}px {get_scaled_size(10)}px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background-color: {DARK_COLORS['error']};"
            f"  color: #FFFFFF;"
            f"  border-color: {DARK_COLORS['error']};"
            f"}}"
            f"QPushButton:pressed {{ background-color: #B71C1C; }}"
            f"QPushButton:disabled {{"
            f"  background-color: {DARK_COLORS['bg_tertiary']};"
            f"  color: {DARK_COLORS['text_disabled']};"
            f"}}"
        )

    def _toggle_btn_style(self) -> str:
        """켜기/끄기 버튼 — 상태 전환 액션을 시각적으로 구분하는 앰버 계열.
        + 새 규칙(추가) / − 선택 제거(파괴) 와 나란히 놓일 때 역할 구분.
        비활성화 상태(disabled)에서도 기본 회색 팔레트로 자동 전환.
        """
        return (
            f"QPushButton {{"
            f"  background-color: #F57C00;"
            f"  color: #FFFFFF;"
            f"  border: none;"
            f"  border-radius: {get_scaled_size(3)}px;"
            f"  font-size: {get_scaled_font_size(17)}px;"
            f"  font-weight: 600;"
            f"  padding: {get_scaled_size(5)}px {get_scaled_size(10)}px;"
            f"}}"
            f"QPushButton:hover {{ background-color: #FB8C00; }}"
            f"QPushButton:pressed {{ background-color: #E65100; }}"
            f"QPushButton:disabled {{"
            f"  background-color: {DARK_COLORS['bg_tertiary']};"
            f"  color: {DARK_COLORS['text_disabled']};"
            f"}}"
        )
