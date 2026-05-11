"""PresetPanel — 프리셋 전용 패널 (3-pane 좌측).

3-pane 재설계 이후 이 패널은 프리셋 목록 + CRUD 버튼만 소유한다. 규칙 목록
섹션은 `RuleListPanel` 로, 엔진 옵션 영역은 제거되었다.

공개 API:
    set_presets(List[PresetInfo])
    get_selected_preset_name() -> Optional[str]
    is_selected_preset_bundled() -> bool
    is_name_bundled(str) -> bool

시그널:
    preset_load_requested(str)
    preset_save_requested(str)      # 이름만, 덮어쓰기는 외부 처리
    preset_delete_requested(str)
"""

from __future__ import annotations

from typing import List, Optional

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

from modules.conditional.preset_io import PresetInfo
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from ui.theme import DARK_COLORS


class PresetPanel(QWidget):
    preset_load_requested = pyqtSignal(str)
    preset_save_requested = pyqtSignal(str)
    preset_delete_requested = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._presets: List[PresetInfo] = []
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_presets(self, presets: List[PresetInfo]) -> None:
        self._presets = list(presets)
        self._preset_list.clear()
        for p in self._presets:
            icon = "📦" if p.is_bundled else "📄"
            item = QListWidgetItem(f"{icon} {p.name}  ({p.rule_count}개)")
            if p.description:
                item.setToolTip(p.description)
            item.setForeground(QColor(DARK_COLORS['text_primary']))
            self._preset_list.addItem(item)
        self._update_preset_button_state()

    def get_selected_preset_name(self) -> Optional[str]:
        idx = self._preset_list.currentRow()
        if idx < 0 or idx >= len(self._presets):
            return None
        return self._presets[idx].name

    def is_selected_preset_bundled(self) -> bool:
        idx = self._preset_list.currentRow()
        if idx < 0 or idx >= len(self._presets):
            return False
        return self._presets[idx].is_bundled

    def is_name_bundled(self, name: str) -> bool:
        """이름이 번들 프리셋과 겹치는지."""
        if not name:
            return False
        needle = name.strip()
        return any(
            p.is_bundled and p.name == needle for p in self._presets
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
        root.addWidget(self._build_preset_section(), stretch=1)

    def _build_preset_section(self) -> QWidget:
        w = QFrame()
        w.setStyleSheet(self._section_style())
        layout = QVBoxLayout(w)
        layout.setContentsMargins(
            get_scaled_size(6), get_scaled_size(6),
            get_scaled_size(6), get_scaled_size(6),
        )
        layout.setSpacing(get_scaled_size(4))

        layout.addWidget(self._section_label("프리셋"))
        helper = QLabel("왼쪽 목록은 템플릿입니다. 불러온 뒤 규칙을 수정하세요.")
        helper.setWordWrap(True)
        helper.setStyleSheet(
            f"color: {DARK_COLORS['text_secondary']};"
            f" font-size: {get_scaled_font_size(16)}px;"
        )
        layout.addWidget(helper)

        self._preset_list = QListWidget()
        self._preset_list.currentRowChanged.connect(
            self._on_preset_row_changed
        )
        self._preset_list.itemDoubleClicked.connect(
            self._on_preset_double_clicked
        )
        layout.addWidget(self._preset_list, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(get_scaled_size(4))
        self._new_btn = QPushButton("새 프리셋")
        self._new_btn.clicked.connect(self._on_new_clicked)
        btn_row.addWidget(self._new_btn)
        self._load_btn = QPushButton("불러오기")
        self._load_btn.clicked.connect(self._on_load_clicked)
        btn_row.addWidget(self._load_btn)
        self._save_btn = QPushButton("저장")
        self._save_btn.clicked.connect(self._on_save_clicked)
        btn_row.addWidget(self._save_btn)
        self._delete_btn = QPushButton("삭제")
        self._delete_btn.clicked.connect(self._on_delete_clicked)
        btn_row.addWidget(self._delete_btn)
        layout.addLayout(btn_row)
        return w

    # ------------------------------------------------------------------
    # 내부 — 버튼 상태/이벤트
    # ------------------------------------------------------------------

    def _update_preset_button_state(self) -> None:
        bundled = self.is_selected_preset_bundled()
        has_selection = self.get_selected_preset_name() is not None
        self._new_btn.setEnabled(True)
        self._load_btn.setEnabled(has_selection)
        # 저장은 새 이름으로도 가능
        self._save_btn.setEnabled(True)
        self._delete_btn.setEnabled(has_selection and not bundled)

    def _on_preset_row_changed(self, _idx: int) -> None:
        self._update_preset_button_state()

    def _on_preset_double_clicked(self, _item) -> None:
        name = self.get_selected_preset_name()
        if name:
            self.preset_load_requested.emit(name)

    def _on_load_clicked(self) -> None:
        name = self.get_selected_preset_name()
        if name:
            self.preset_load_requested.emit(name)

    def _on_new_clicked(self) -> None:
        self.preset_save_requested.emit("")

    def _on_save_clicked(self) -> None:
        name = self.get_selected_preset_name() or ""
        self.preset_save_requested.emit(name)

    def _on_delete_clicked(self) -> None:
        name = self.get_selected_preset_name()
        if name and not self.is_selected_preset_bundled():
            self.preset_delete_requested.emit(name)

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
