"""
Clothes Preset Widgets — 커스텀 위젯

ComboTableModel: 3000행 콤보 테이블 최적화 모델 (QAbstractTableModel)
FlowLayout: CSS flexbox wrap 유사 레이아웃
StagedTagChip: [tag ×] 칩 위젯

소스 참조: viewer_clothes.py L147-197, ui/event_preset/widgets.py FlowLayout
"""
from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QLayout, QPushButton, QSizePolicy, QWidget,
)

from ui.theme import DARK_COLORS
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from .data_manager import ComboSummary, fmt_k_count


# ---------------------------------------------------------------------------
# FlowLayout (event_preset/widgets.py에서 복사)
# ---------------------------------------------------------------------------

class FlowLayout(QLayout):
    """수평 배치 후 넘치면 다음 줄로 래핑하는 레이아웃."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 3) -> None:
        super().__init__(parent)
        self._items: list = []
        self._spacing = spacing

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, apply=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        w = h = 0
        for item in self._items:
            s = item.minimumSize()
            w = max(w, s.width())
            h = max(h, s.height())
        return QSize(w, h)

    def _do_layout(self, rect: QRect, apply: bool) -> int:
        x = rect.x()
        y = rect.y()
        row_h = 0
        for item in self._items:
            sz = item.sizeHint()
            if x + sz.width() > rect.right() + 1 and x > rect.x():
                x = rect.x()
                y += row_h + self._spacing
                row_h = 0
            if apply:
                item.setGeometry(QRect(x, y, sz.width(), sz.height()))
            x += sz.width() + self._spacing
            row_h = max(row_h, sz.height())
        return y + row_h - rect.y()

    def clear_widgets(self) -> None:
        """모든 위젯 제거."""
        while self.count() > 0:
            item = self.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()


# ---------------------------------------------------------------------------
# StagedTagChip — [tag ×] 칩 위젯
# ---------------------------------------------------------------------------

class StagedTagChip(QWidget):
    """Staged 태그 하나를 표현하는 칩. 클릭→tag_clicked, ×→remove_clicked."""

    tag_clicked = pyqtSignal(str)
    remove_clicked = pyqtSignal(str)

    def __init__(self, tag: str, border_color: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tag = tag

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        fs = get_scaled_font_size
        ss = get_scaled_size
        bc = border_color or DARK_COLORS['accent_blue_light']

        self._label_btn = QPushButton(tag)
        self._label_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._label_btn.setStyleSheet(f"""
            QPushButton {{
                font-size: {fs(15)}px;
                padding: {ss(2)}px {ss(6)}px;
                border-top-left-radius: {ss(3)}px;
                border-bottom-left-radius: {ss(3)}px;
                border-top-right-radius: 0px;
                border-bottom-right-radius: 0px;
                color: {DARK_COLORS['text_primary']};
                background: {DARK_COLORS['bg_secondary']};
                border: 1px solid {bc};
                border-right: none;
            }}
            QPushButton:hover {{
                background: {DARK_COLORS['bg_hover']};
            }}
        """)
        self._label_btn.clicked.connect(lambda: self.tag_clicked.emit(self._tag))
        layout.addWidget(self._label_btn)

        self._remove_btn = QPushButton("×")
        self._remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._remove_btn.setFixedWidth(ss(22))
        self._remove_btn.setStyleSheet(f"""
            QPushButton {{
                font-size: {fs(15)}px;
                padding: {ss(2)}px {ss(2)}px;
                border-top-left-radius: 0px;
                border-bottom-left-radius: 0px;
                border-top-right-radius: {ss(3)}px;
                border-bottom-right-radius: {ss(3)}px;
                color: {DARK_COLORS['text_secondary']};
                background: {DARK_COLORS['bg_secondary']};
                border: 1px solid {bc};
                border-left: none;
            }}
            QPushButton:hover {{
                color: {DARK_COLORS['text_primary']};
                background: #5a2020;
            }}
        """)
        self._remove_btn.clicked.connect(lambda: self.remove_clicked.emit(self._tag))
        layout.addWidget(self._remove_btn)

        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    @property
    def tag(self) -> str:
        return self._tag


class ComboTableModel(QAbstractTableModel):
    """의류 콤보 테이블용 최적화 모델.

    3000행 이상을 QTableWidget 대신 QAbstractTableModel로 처리하여
    visible rows만 렌더링 (lazy-load).
    """

    _HEADERS = ["Observed Clothing Combo", "Count"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[ComboSummary] = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 2

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        row = index.row()
        col = index.column()
        if row < 0 or row >= len(self._rows):
            return None

        item = self._rows[row]

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return item.clothing_combo
            if col == 1:
                return fmt_k_count(item.post_count)
            return None

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col == 1:
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            return None

        if role == Qt.ItemDataRole.ToolTipRole:
            if col == 0:
                return ", ".join(item.tags)
            return None

        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if 0 <= section < len(self._HEADERS):
                return self._HEADERS[section]
        return None

    def replace(self, rows: list[ComboSummary]) -> None:
        """테이블 데이터 원자적 교체."""
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def get_row(self, index: int) -> ComboSummary | None:
        """인덱스로 행 데이터 조회."""
        if 0 <= index < len(self._rows):
            return self._rows[index]
        return None

    def row_count(self) -> int:
        return len(self._rows)
