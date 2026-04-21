"""PresetPanel — 좌측 pane: 프리셋 관리 + engine 옵션 + 규칙 리스트 (1.4d).

뷰 컴포넌트. 실제 파일 I/O / RuleBook 소유는 상위(1.4e 편집기 창)에서 담당.
패널은 상태를 받아 표시하고, 사용자 인터랙션을 시그널로 전달.

공개 API:
    set_presets(List[PresetInfo])
    set_rulebook(RuleBook)
    set_selected_rule(int)
    set_engine_options(dict)
    get_engine_options() -> dict

시그널:
    preset_load_requested(str)
    preset_save_requested(str)        # 이름만, 덮어쓰기는 외부 처리
    preset_delete_requested(str)
    rule_selected(int)                # -1 = 선택 없음
    rule_add_requested()
    rule_delete_requested(int)
    engine_options_changed(dict)      # {max_passes, stop_on_match}
"""

from __future__ import annotations

from typing import List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from modules.conditional.block_model import Rule, RuleBook
from modules.conditional.dsl_serializer import serialize_rule
from modules.conditional.preset_io import PresetInfo
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from ui.theme import DARK_COLORS


class PresetPanel(QWidget):
    preset_load_requested = pyqtSignal(str)
    preset_save_requested = pyqtSignal(str)
    preset_delete_requested = pyqtSignal(str)
    rule_selected = pyqtSignal(int)
    rule_add_requested = pyqtSignal()
    rule_delete_requested = pyqtSignal(int)
    engine_options_changed = pyqtSignal(dict)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._presets: List[PresetInfo] = []
        self._rulebook: Optional[RuleBook] = None
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
            self._preset_list.addItem(item)

    def set_rulebook(self, book: Optional[RuleBook]) -> None:
        self._rulebook = book
        self._rule_list.clear()
        if book is None:
            self._update_preset_button_state()
            return
        for r in book.sorted_rules():
            self._rule_list.addItem(QListWidgetItem(self._rule_summary(r)))
        self._update_preset_button_state()
        self._sync_engine_options_from_book(book)

    def set_selected_rule(self, idx: int) -> None:
        self._rule_list.blockSignals(True)
        try:
            if 0 <= idx < self._rule_list.count():
                self._rule_list.setCurrentRow(idx)
            else:
                self._rule_list.clearSelection()
        finally:
            self._rule_list.blockSignals(False)

    def set_engine_options(self, opts: dict) -> None:
        self._opts_mute(True)
        try:
            self._max_passes_spin.setValue(
                max(1, int(opts.get("max_passes", 1) or 1))
            )
            self._stop_on_match_chk.setChecked(
                bool(opts.get("stop_on_match", False))
            )
        finally:
            self._opts_mute(False)

    def get_engine_options(self) -> dict:
        return {
            "max_passes": int(self._max_passes_spin.value()),
            "stop_on_match": self._stop_on_match_chk.isChecked(),
        }

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

        root.addWidget(self._build_preset_section(), stretch=2)
        root.addWidget(self._build_engine_options_section())
        root.addWidget(self._build_rule_list_section(), stretch=3)

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

        self._preset_list = QListWidget()
        self._preset_list.currentRowChanged.connect(
            self._on_preset_row_changed
        )
        self._preset_list.itemDoubleClicked.connect(
            self._on_preset_double_clicked
        )
        layout.addWidget(self._preset_list)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(get_scaled_size(4))
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

    def _build_engine_options_section(self) -> QWidget:
        w = QFrame()
        w.setStyleSheet(self._section_style())
        layout = QVBoxLayout(w)
        layout.setContentsMargins(
            get_scaled_size(6), get_scaled_size(6),
            get_scaled_size(6), get_scaled_size(6),
        )
        layout.setSpacing(get_scaled_size(4))

        layout.addWidget(self._section_label("엔진 옵션"))

        row = QHBoxLayout()
        row.setSpacing(get_scaled_size(6))
        row.addWidget(QLabel("max_passes:"))
        self._max_passes_spin = QSpinBox()
        self._max_passes_spin.setRange(1, 99)
        self._max_passes_spin.setValue(1)
        self._max_passes_spin.valueChanged.connect(self._on_opts_changed)
        row.addWidget(self._max_passes_spin)

        self._stop_on_match_chk = QCheckBox("stop_on_match")
        self._stop_on_match_chk.stateChanged.connect(self._on_opts_changed)
        row.addWidget(self._stop_on_match_chk)
        row.addStretch()
        layout.addLayout(row)
        return w

    def _build_rule_list_section(self) -> QWidget:
        w = QFrame()
        w.setStyleSheet(self._section_style())
        layout = QVBoxLayout(w)
        layout.setContentsMargins(
            get_scaled_size(6), get_scaled_size(6),
            get_scaled_size(6), get_scaled_size(6),
        )
        layout.setSpacing(get_scaled_size(4))

        layout.addWidget(self._section_label("규칙 (priority 정렬)"))

        self._rule_list = QListWidget()
        self._rule_list.currentRowChanged.connect(
            self._on_rule_row_changed
        )
        layout.addWidget(self._rule_list)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(get_scaled_size(4))
        add_btn = QPushButton("+ 새 규칙")
        add_btn.clicked.connect(lambda: self.rule_add_requested.emit())
        btn_row.addWidget(add_btn)
        del_btn = QPushButton("− 선택 제거")
        del_btn.clicked.connect(self._on_rule_delete_clicked)
        btn_row.addWidget(del_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        return w

    # ------------------------------------------------------------------
    # 내부 상태/헬퍼
    # ------------------------------------------------------------------

    def _rule_summary(self, rule: Rule) -> str:
        body = serialize_rule(rule) or "(빈 규칙)"
        if len(body) > 80:
            body = body[:77] + "..."
        name = f" — {rule.name}" if rule.name else ""
        return f"[{rule.priority:04d}] {body}{name}"

    def _sync_engine_options_from_book(self, book: RuleBook) -> None:
        self.set_engine_options(
            {
                "max_passes": int(book.max_passes),
                "stop_on_match": bool(book.stop_on_match),
            }
        )

    def _update_preset_button_state(self) -> None:
        bundled = self.is_selected_preset_bundled()
        # 번들 프리셋은 저장/삭제 비활성 (read-only)
        self._save_btn.setEnabled(True)  # 저장은 새 이름 가능
        self._delete_btn.setEnabled(
            self.get_selected_preset_name() is not None and not bundled
        )

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

    def _on_save_clicked(self) -> None:
        name = self.get_selected_preset_name() or ""
        self.preset_save_requested.emit(name)

    def _on_delete_clicked(self) -> None:
        name = self.get_selected_preset_name()
        if name and not self.is_selected_preset_bundled():
            self.preset_delete_requested.emit(name)

    def _on_rule_row_changed(self, idx: int) -> None:
        self.rule_selected.emit(int(idx))

    def _on_rule_delete_clicked(self) -> None:
        idx = self._rule_list.currentRow()
        if idx >= 0:
            self.rule_delete_requested.emit(int(idx))

    def _on_opts_changed(self, *_args) -> None:
        self.engine_options_changed.emit(self.get_engine_options())

    def _opts_mute(self, muted: bool) -> None:
        for w in (self._max_passes_spin, self._stop_on_match_chk):
            w.blockSignals(muted)

    # ------------------------------------------------------------------
    # 스타일
    # ------------------------------------------------------------------

    def _panel_style(self) -> str:
        return (
            f"QWidget {{"
            f"  background-color: {DARK_COLORS['bg_primary']};"
            f"  color: {DARK_COLORS['text_primary']};"
            f"  font-size: {get_scaled_font_size(12)}px;"
            f"}}"
            f"QListWidget {{"
            f"  background-color: {DARK_COLORS['bg_tertiary']};"
            f"  border: 1px solid {DARK_COLORS['border']};"
            f"  border-radius: {get_scaled_size(3)}px;"
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
            f" font-size: {get_scaled_font_size(13)}px;"
            f" font-weight: bold;"
        )
        return label
