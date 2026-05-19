"""ChipListWidget — 태그 리스트를 pill chip 으로 표시/편집 (Sub-phase 1.4a).

사용 예:
    w = ChipListWidget()
    w.set_tags(["blush", "smile"])
    w.tags_changed.connect(self._on_tags_changed)
    tags = w.get_tags()

- 중복 태그는 자동 거부 (user-visible X 로 제거만 가능)
- Enter 또는 "+" 버튼으로 추가
- 175 개선: 수평 스크롤 → FlowLayout 줄넘김. Clothes Preset 의 StagedTagChip
  스타일 ([tag | ×] split button) 을 현재 다크 테마 색상으로 차용.
"""

from __future__ import annotations

from typing import List, Optional

from PyQt6.QtCore import QRect, QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLayout,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from legacy_desktop.ui.scaling_manager import get_scaled_font_size, get_scaled_size
from legacy_desktop.ui.theme import DARK_COLORS


# 175 hotfix: condition_editor/rule_panel 과 동일한 입력 팔레트 사용.
# DARK_COLORS['input'] (#2B2B2B) 은 카드 배경(#2D2D2D) 과 거의 같아 입력
# 필드 계층이 사라지므로 같은 편집기 안에서 입력필드 배경 색상이 분열되는
# 문제가 발생한다. 여기서도 _INPUT_BG / _INPUT_BORDER 를 통일해 쓴다.
_INPUT_BG = "#161616"
_INPUT_BORDER = "#444444"


# ---------------------------------------------------------------------------
# FlowLayout (ui/clothes_preset/widgets.py 차용)
# ---------------------------------------------------------------------------


class _FlowLayout(QLayout):
    """수평 배치 후 넘치면 다음 줄로 래핑하는 레이아웃."""

    def __init__(
        self, parent: Optional[QWidget] = None, spacing: int = 4
    ) -> None:
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
        while self.count() > 0:
            item = self.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.deleteLater()


# ---------------------------------------------------------------------------
# _TagChip — [tag | ×] split button 스타일
# ---------------------------------------------------------------------------


class _TagChip(QWidget):
    """태그 하나를 표현하는 pill chip. ×→remove 시그널."""

    remove_requested = pyqtSignal(str)

    def __init__(self, tag: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._tag = tag

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        fs = get_scaled_font_size
        ss = get_scaled_size
        bc = DARK_COLORS['accent_blue_light']

        self._label_btn = QPushButton(tag)
        self._label_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self._label_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._label_btn.setStyleSheet(f"""
            QPushButton {{
                font-size: {fs(16)}px;
                padding: {ss(3)}px {ss(8)}px;
                border-top-left-radius: {ss(4)}px;
                border-bottom-left-radius: {ss(4)}px;
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
        layout.addWidget(self._label_btn)

        self._remove_btn = QPushButton("×")
        self._remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._remove_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._remove_btn.setFixedWidth(ss(24))
        self._remove_btn.setStyleSheet(f"""
            QPushButton {{
                font-size: {fs(16)}px;
                padding: {ss(3)}px {ss(2)}px;
                border-top-left-radius: 0px;
                border-bottom-left-radius: 0px;
                border-top-right-radius: {ss(4)}px;
                border-bottom-right-radius: {ss(4)}px;
                color: {DARK_COLORS['text_secondary']};
                background: {DARK_COLORS['bg_secondary']};
                border: 1px solid {bc};
                border-left: none;
                font-weight: bold;
            }}
            QPushButton:hover {{
                color: #FFFFFF;
                background: #5A2020;
            }}
        """)
        self._remove_btn.clicked.connect(
            lambda: self.remove_requested.emit(self._tag)
        )
        layout.addWidget(self._remove_btn)

        self.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )

    @property
    def tag(self) -> str:
        return self._tag


# ---------------------------------------------------------------------------
# ChipListWidget
# ---------------------------------------------------------------------------


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
        # 175 hotfix: chip 컨테이너와 입력 row 사이에 공백을 두면 부모 카드
        # 배경(#2D2D2D)이 가로 띠로 보여 "배경색 이 다르다"는 인상을 준다.
        # 2px 로 두면 두 입력 박스가 거의 flush 하게 붙어 한 섹션처럼 읽힌다.
        root.setSpacing(get_scaled_size(2))

        # chip 컨테이너 — FlowLayout 으로 줄넘김.
        # QWidget 은 기본적으로 배경을 그리지 않으므로 WA_StyledBackground 를
        # 켜 stylesheet 의 background-color 가 화면에 적용되게 한다.
        self._chip_container = QWidget()
        self._chip_container.setObjectName("chipContainer")
        self._chip_container.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground, True
        )
        self._chip_container.setStyleSheet(
            f"QWidget#chipContainer {{"
            f"  background-color: {_INPUT_BG};"
            f"  border: 1px solid {_INPUT_BORDER};"
            f"  border-radius: {get_scaled_size(4)}px;"
            f"}}"
        )
        self._chip_layout = _FlowLayout(
            self._chip_container, spacing=get_scaled_size(4)
        )
        self._chip_layout.setContentsMargins(
            get_scaled_size(6), get_scaled_size(6),
            get_scaled_size(6), get_scaled_size(6),
        )
        self._chip_container.setMinimumHeight(get_scaled_size(44))
        root.addWidget(self._chip_container)

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
        add_btn.setFixedWidth(get_scaled_size(36))
        add_btn.setStyleSheet(self._add_btn_style())
        add_btn.clicked.connect(self._on_add_clicked)
        input_row.addWidget(add_btn)

        root.addLayout(input_row)
        self._refresh_chips()

    def _refresh_chips(self) -> None:
        # 기존 chip 제거
        self._chip_layout.clear_widgets()

        for tag in self._tags:
            chip = _TagChip(tag)
            chip.remove_requested.connect(self._on_remove_requested)
            self._chip_layout.addWidget(chip)

    def _on_remove_requested(self, tag: str) -> None:
        if tag in self._tags:
            self._tags.remove(tag)
            self._refresh_chips()
            self.tags_changed.emit(list(self._tags))

    def _remove_at(self, idx: int) -> None:
        """인덱스 기반 제거 (테스트 호환 API)."""
        if 0 <= idx < len(self._tags):
            del self._tags[idx]
            self._refresh_chips()
            self.tags_changed.emit(list(self._tags))

    def _on_add_clicked(self) -> None:
        text = self._input.text().strip()
        self.add_tag(text)
        self._input.clear()

    # ------------------------------------------------------------------
    # 스타일 — 입력 행
    # ------------------------------------------------------------------

    def _input_style(self) -> str:
        return (
            f"QLineEdit {{"
            f"  background-color: {_INPUT_BG};"
            f"  color: {DARK_COLORS['text_primary']};"
            f"  border: 1px solid {_INPUT_BORDER};"
            f"  border-radius: {get_scaled_size(4)}px;"
            f"  padding: {get_scaled_size(6)}px {get_scaled_size(10)}px;"
            f"  font-size: {get_scaled_font_size(17)}px;"
            f"  selection-background-color: {DARK_COLORS['accent_blue']};"
            f"}}"
            f"QLineEdit:focus {{"
            f"  border-color: {DARK_COLORS['accent_blue']};"
            f"}}"
        )

    def _add_btn_style(self) -> str:
        return (
            f"QPushButton {{"
            f"  background-color: {DARK_COLORS['accent_blue']};"
            f"  color: #FFFFFF;"
            f"  border: none;"
            f"  border-radius: {get_scaled_size(4)}px;"
            f"  font-size: {get_scaled_font_size(19)}px;"
            f"  font-weight: bold;"
            f"  padding: {get_scaled_size(6)}px 0;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background-color: {DARK_COLORS['accent_blue_hover']};"
            f"}}"
            f"QPushButton:pressed {{"
            f"  background-color: #0D47A1;"
            f"}}"
        )
