# modules/filter_debug_window.py
"""전처리 필터 디버깅 윈도우."""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QGridLayout,
    QScrollArea, QWidget, QTextEdit, QSizePolicy,
)
from PyQt6.QtCore import Qt
from ui.theme import DARK_COLORS
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from typing import List, Dict, Any


_TAG_FONT = lambda: get_scaled_font_size(19)
_ROUND_FONT = lambda: get_scaled_font_size(16)
_MAX_ROUNDS = 14


class _RoundWidget(QWidget):
    """라운드 하나: 헤더 QLabel + 태그 QTextEdit."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(get_scaled_size(2))

        self.header = QLabel()
        self.header.setStyleSheet(
            f"font-size: {_ROUND_FONT()}px; font-weight: bold;"
        )
        layout.addWidget(self.header)

        self.tags_edit = QTextEdit()
        self.tags_edit.setReadOnly(True)
        self.tags_edit.setAcceptRichText(False)
        self.tags_edit.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.tags_edit.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.tags_edit.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )
        self.tags_edit.setStyleSheet(f"""
            QTextEdit {{
                font-size: {_TAG_FONT()}px;
                color: {DARK_COLORS['text_secondary']};
                background-color: transparent;
                border: none;
                padding-left: {get_scaled_size(10)}px;
            }}
        """)
        self.tags_edit.document().documentLayout().documentSizeChanged.connect(
            self._adjust_height
        )
        self.tags_edit.hide()
        layout.addWidget(self.tags_edit)

    def _adjust_height(self):
        doc_height = int(self.tags_edit.document().size().height())
        margin = self.tags_edit.contentsMargins()
        self.tags_edit.setFixedHeight(
            doc_height + margin.top() + margin.bottom() + 2
        )

    def update_round(self, name: str, enabled: bool, removed: List[str]):
        if not enabled:
            dot_color = "#666666"
            status = "OFF"
        elif removed:
            dot_color = "#ff9800"
            status = f"ON — {len(removed)}개 제거"
        else:
            dot_color = "#4caf50"
            status = "ON"

        self.header.setText(f"● {name} [{status}]")
        self.header.setStyleSheet(
            f"font-size: {_ROUND_FONT()}px; color: {dot_color}; font-weight: bold;"
        )

        if removed:
            self.tags_edit.setPlainText("  " + ", ".join(removed))
            self.tags_edit.show()
        else:
            self.tags_edit.hide()

        self.show()


class FilterDebugWindow(QDialog):
    """전처리 필터 라운드별 제거 내역 디버깅 윈도우 (최근 1건만 표시)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.Tool)
        self.setWindowTitle("전처리 디버깅 윈도우")
        self.setMinimumSize(get_scaled_size(675), get_scaled_size(525))
        self.resize(get_scaled_size(780), get_scaled_size(900))
        self._entry_count = 0
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        m = get_scaled_size(8)
        layout.setContentsMargins(m, m, m, m)
        layout.setSpacing(get_scaled_size(6))

        # 헤더
        header_row = QHBoxLayout()
        header_row.addStretch()

        self._counter_label = QLabel("#0")
        self._counter_label.setStyleSheet(
            f"font-size: {get_scaled_font_size(17)}px; color: {DARK_COLORS['text_secondary']};"
        )
        header_row.addWidget(self._counter_label)
        layout.addLayout(header_row)

        # 스크롤 영역
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(f"""
            QScrollArea {{
                border: 1px solid {DARK_COLORS['border']};
                background-color: {DARK_COLORS['bg_primary']};
            }}
        """)

        self._content = QWidget()
        self._content.setStyleSheet(f"background-color: {DARK_COLORS['bg_primary']};")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._content_layout.setSpacing(get_scaled_size(6))

        # 소스 정보 (2x2 그리드: Character/Copyright/Artist/ID)
        self._src_grid = QWidget()
        src_grid_layout = QGridLayout(self._src_grid)
        src_grid_layout.setContentsMargins(0, 0, 0, 0)
        src_grid_layout.setSpacing(get_scaled_size(4))

        src_label_style = (
            f"font-size: {get_scaled_font_size(14)}px; "
            f"color: {DARK_COLORS['text_secondary']}; font-weight: bold;"
        )
        src_edit_style = f"""
            QTextEdit {{
                font-size: {get_scaled_font_size(14)}px;
                color: {DARK_COLORS['text_primary']};
                background-color: transparent;
                border: none;
            }}
        """
        self._src_fields: Dict[str, QTextEdit] = {}
        field_names = [
            ('character', 'Character'),
            ('copyright', 'Copyright'),
            ('artist', 'Artist'),
            ('id', 'ID'),
        ]
        for idx, (key, display) in enumerate(field_names):
            row, col = divmod(idx, 2)
            lbl = QLabel(f"{display}:")
            lbl.setStyleSheet(src_label_style)
            lbl.setAlignment(Qt.AlignmentFlag.AlignTop)
            src_grid_layout.addWidget(lbl, row, col * 2)

            edit = QTextEdit()
            edit.setReadOnly(True)
            edit.setAcceptRichText(False)
            edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            edit.setStyleSheet(src_edit_style)
            edit.setFixedHeight(get_scaled_size(24))
            edit.document().documentLayout().documentSizeChanged.connect(
                lambda _, e=edit: self._adjust_src_height(e)
            )
            src_grid_layout.addWidget(edit, row, col * 2 + 1)
            self._src_fields[key] = edit

        # 열 비율: label 고정, value 확장
        src_grid_layout.setColumnStretch(1, 1)
        src_grid_layout.setColumnStretch(3, 1)

        self._src_grid.hide()
        self._content_layout.addWidget(self._src_grid)

        # 구분선 1
        self._sep1 = self._make_separator()
        self._sep1.hide()
        self._content_layout.addWidget(self._sep1)

        # 라운드 위젯 풀
        self._round_widgets: List[_RoundWidget] = []
        for _ in range(_MAX_ROUNDS):
            rw = _RoundWidget()
            rw.hide()
            self._round_widgets.append(rw)
            self._content_layout.addWidget(rw)

        # 구분선 2
        self._sep2 = self._make_separator()
        self._sep2.hide()
        self._content_layout.addWidget(self._sep2)

        # 요약
        self._summary_label = QLabel()
        self._summary_label.setStyleSheet(
            f"font-size: {get_scaled_font_size(15)}px; color: #aaaaaa;"
        )
        self._summary_label.hide()
        self._content_layout.addWidget(self._summary_label)

        self._scroll.setWidget(self._content)
        layout.addWidget(self._scroll)

        # 다크 테마
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
            }}
        """)

    def _adjust_src_height(self, edit: QTextEdit):
        doc_height = int(edit.document().size().height())
        margin = edit.contentsMargins()
        edit.setFixedHeight(
            max(get_scaled_size(24), doc_height + margin.top() + margin.bottom() + 2)
        )

    def _make_separator(self) -> QWidget:
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {DARK_COLORS['border']};")
        return sep

    # ------------------------------------------------------------------
    def add_entry(
        self,
        source_info: Dict[str, Any],
        filter_log: List[Dict[str, Any]],
        original_count: int,
        remaining_count: int,
    ):
        """최근 1건의 디버그 정보로 교체한다."""
        self._entry_count += 1
        self._counter_label.setText(f"#{self._entry_count}")

        # -- 소스 정보 (2x2 그리드)
        has_src = False
        for key, edit in self._src_fields.items():
            val = source_info.get(key, '')
            if val:
                edit.setPlainText(str(val))
                has_src = True
            else:
                edit.setPlainText('')

        if has_src:
            self._src_grid.show()
            self._sep1.show()
        else:
            self._src_grid.hide()
            self._sep1.hide()

        # -- 라운드별 로그
        for i, rw in enumerate(self._round_widgets):
            if i < len(filter_log):
                entry = filter_log[i]
                rw.update_round(
                    entry.get('name', f'Round {i}'),
                    entry.get('enabled', False),
                    entry.get('removed', []),
                )
            else:
                rw.hide()

        # -- 요약
        self._sep2.show()
        total_removed = original_count - remaining_count
        self._summary_label.setText(
            f"원본: {original_count}개 → 남은: {remaining_count}개 (제거: {total_removed}개)"
        )
        self._summary_label.show()

        # 스크롤 맨 위로
        self._scroll.verticalScrollBar().setValue(0)

    def clear(self):
        """표시 내용 초기화."""
        self._src_grid.hide()
        self._sep1.hide()
        for rw in self._round_widgets:
            rw.hide()
        self._sep2.hide()
        self._summary_label.hide()
        self._entry_count = 0
        self._counter_label.setText("#0")
