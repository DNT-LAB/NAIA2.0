"""ChipListWidget — 태그 리스트를 개별 chip 으로 표시/편집 (Sub-phase 1.4a).

사용 예:
    w = ChipListWidget()
    w.set_tags(["blush", "smile"])
    w.tags_changed.connect(self._on_tags_changed)
    tags = w.get_tags()

- 중복 태그는 자동 거부 (user-visible X 로 제거만 가능)
- Enter 또는 "+" 버튼으로 추가
- chip 은 DARK_COLORS 토큰 + get_scaled_size 준수 (R-40 / R-41)
"""

from __future__ import annotations

from typing import List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from ui.theme import DARK_COLORS


class ChipListWidget(QWidget):
    """태그 리스트를 chip UI 로 편집하는 위젯.

    공개 API:
        set_tags(tags: List[str]) -> None
        get_tags() -> List[str]
        add_tag(tag: str) -> bool     # 중복/공백이면 False
        clear() -> None

    시그널:
        tags_changed(List[str])  # 변경 시 현재 스냅샷
    """

    tags_changed = pyqtSignal(list)

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        placeholder: str = "태그 입력 후 Enter",
    ):
        super().__init__(parent)
        self._tags: List[str] = []
        self._build_ui(placeholder)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_tags(self, tags: List[str]) -> None:
        cleaned: List[str] = []
        seen: set = set()
        for t in tags or []:
            if not isinstance(t, str):
                continue
            t = t.strip()
            if t and t not in seen:
                cleaned.append(t)
                seen.add(t)
        self._tags = cleaned
        self._refresh_chips()
        self.tags_changed.emit(list(self._tags))

    def get_tags(self) -> List[str]:
        return list(self._tags)

    def add_tag(self, tag: str) -> bool:
        t = (tag or "").strip()
        if not t or t in self._tags:
            return False
        self._tags.append(t)
        self._refresh_chips()
        self.tags_changed.emit(list(self._tags))
        return True

    def clear(self) -> None:
        if not self._tags:
            return
        self._tags = []
        self._refresh_chips()
        self.tags_changed.emit([])

    # ------------------------------------------------------------------
    # UI 구성
    # ------------------------------------------------------------------

    def _build_ui(self, placeholder: str) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(get_scaled_size(4))

        # chip 영역 — 가로 스크롤 가능
        self._chip_scroll = QScrollArea()
        self._chip_scroll.setWidgetResizable(True)
        self._chip_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._chip_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._chip_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._chip_scroll.setMinimumHeight(get_scaled_size(40))

        self._chip_container = QWidget()
        self._chip_layout = QHBoxLayout(self._chip_container)
        self._chip_layout.setContentsMargins(0, 0, 0, 0)
        self._chip_layout.setSpacing(get_scaled_size(6))
        self._chip_scroll.setWidget(self._chip_container)
        root.addWidget(self._chip_scroll)

        # 입력 행
        input_row = QHBoxLayout()
        input_row.setContentsMargins(0, 0, 0, 0)
        input_row.setSpacing(get_scaled_size(4))

        self._input = QLineEdit()
        self._input.setPlaceholderText(placeholder)
        self._input.setStyleSheet(self._input_style())
        self._input.returnPressed.connect(self._on_add_clicked)
        input_row.addWidget(self._input)

        add_btn = QPushButton("+")
        add_btn.setFixedWidth(get_scaled_size(32))
        add_btn.setStyleSheet(self._add_btn_style())
        add_btn.clicked.connect(self._on_add_clicked)
        input_row.addWidget(add_btn)

        root.addLayout(input_row)
        self._refresh_chips()

    def _refresh_chips(self) -> None:
        # 기존 chip 제거
        while self._chip_layout.count():
            item = self._chip_layout.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.deleteLater()

        for idx, tag in enumerate(self._tags):
            self._chip_layout.addWidget(self._create_chip(idx, tag))
        self._chip_layout.addStretch()

    def _create_chip(self, idx: int, tag: str) -> QFrame:
        chip = QFrame()
        chip.setStyleSheet(self._chip_style())
        layout = QHBoxLayout(chip)
        layout.setContentsMargins(
            get_scaled_size(8), get_scaled_size(3),
            get_scaled_size(4), get_scaled_size(3),
        )
        layout.setSpacing(get_scaled_size(4))

        label = QLabel(tag)
        label.setStyleSheet(
            f"color: {DARK_COLORS['text_primary']};"
            f" font-size: {get_scaled_font_size(12)}px;"
        )
        layout.addWidget(label)

        x_btn = QPushButton("×")
        x_btn.setFixedSize(get_scaled_size(18), get_scaled_size(18))
        x_btn.setStyleSheet(self._chip_x_style())
        # lambda closure 이슈 회피 — default arg 로 idx 캡처
        x_btn.clicked.connect(lambda _=False, i=idx: self._remove_at(i))
        layout.addWidget(x_btn)
        return chip

    def _remove_at(self, idx: int) -> None:
        if 0 <= idx < len(self._tags):
            del self._tags[idx]
            self._refresh_chips()
            self.tags_changed.emit(list(self._tags))

    def _on_add_clicked(self) -> None:
        text = self._input.text().strip()
        if self.add_tag(text):
            self._input.clear()
        else:
            # 공백이거나 중복 — 입력창 비우기만
            self._input.clear()

    # ------------------------------------------------------------------
    # 스타일 (모두 DARK_COLORS 토큰 + 스케일)
    # ------------------------------------------------------------------

    def _chip_style(self) -> str:
        return (
            f"QFrame {{"
            f"  background-color: {DARK_COLORS['bg_secondary']};"
            f"  border: 1px solid {DARK_COLORS['border']};"
            f"  border-radius: {get_scaled_size(10)}px;"
            f"}}"
        )

    def _chip_x_style(self) -> str:
        return (
            f"QPushButton {{"
            f"  background-color: transparent;"
            f"  color: {DARK_COLORS['text_secondary']};"
            f"  border: none;"
            f"  font-size: {get_scaled_font_size(14)}px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  color: {DARK_COLORS['text_primary']};"
            f"  background-color: {DARK_COLORS['bg_hover']};"
            f"  border-radius: {get_scaled_size(9)}px;"
            f"}}"
        )

    def _input_style(self) -> str:
        return (
            f"QLineEdit {{"
            f"  background-color: {DARK_COLORS['input']};"
            f"  color: {DARK_COLORS['text_primary']};"
            f"  border: 1px solid {DARK_COLORS['border']};"
            f"  border-radius: {get_scaled_size(4)}px;"
            f"  padding: {get_scaled_size(4)}px {get_scaled_size(8)}px;"
            f"  font-size: {get_scaled_font_size(12)}px;"
            f"}}"
            f"QLineEdit:focus {{"
            f"  border-color: {DARK_COLORS['accent_blue']};"
            f"}}"
        )

    def _add_btn_style(self) -> str:
        return (
            f"QPushButton {{"
            f"  background-color: {DARK_COLORS['bg_secondary']};"
            f"  color: {DARK_COLORS['text_primary']};"
            f"  border: 1px solid {DARK_COLORS['border']};"
            f"  border-radius: {get_scaled_size(4)}px;"
            f"  font-size: {get_scaled_font_size(14)}px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background-color: {DARK_COLORS['bg_hover']};"
            f"}}"
        )
