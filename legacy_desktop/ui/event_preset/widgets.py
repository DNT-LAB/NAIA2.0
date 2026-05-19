"""
Event Preset Widgets — FlowLayout, RecommendedTagsPanel, RichComboDelegate, ImagePreviewWidget

viewer_multi.py의 커스텀 위젯을 NAIA 테마로 재작성.
"""
from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap, QTextDocument
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from legacy_desktop.ui.theme import DARK_COLORS
from legacy_desktop.ui.scaling_manager import get_scaled_font_size, get_scaled_size

# HTML 데이터 역할 (RichComboDelegate용)
ROLE_HTML = Qt.ItemDataRole.UserRole + 100


# ---------------------------------------------------------------------------
# FlowLayout — 칩 래핑 레이아웃
# ---------------------------------------------------------------------------

class FlowLayout(QLayout):
    """수평 배치 후 넘치면 다음 줄로 래핑하는 레이아웃 (CSS flexbox wrap과 유사)."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 3) -> None:
        super().__init__(parent)
        self._items: list = []
        self._spacing = spacing

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
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
# 칩 색상 매핑 (카테고리별)
# ---------------------------------------------------------------------------

def _chip_colors(category: str) -> tuple[str, str, str, str]:
    """카테고리별 칩 색상 반환: (on_bg, on_border, off_bg, off_border)."""
    if category == "expression":
        return "#1A2A4A", DARK_COLORS['accent_blue_light'], DARK_COLORS['bg_primary'], DARK_COLORS['border']
    elif category == "clothing":
        return "#1A3A2A", DARK_COLORS['success'], DARK_COLORS['bg_primary'], DARK_COLORS['border']
    else:  # characteristic
        return "#3A2A1A", DARK_COLORS['warning'], DARK_COLORS['bg_primary'], DARK_COLORS['border']


def _category_label_color(category: str) -> str:
    """카테고리별 라벨 색상."""
    if category == "expression":
        return DARK_COLORS['accent_blue_light']
    elif category == "clothing":
        return DARK_COLORS['success']
    else:
        return DARK_COLORS['warning']


# ---------------------------------------------------------------------------
# RecommendedTagsPanel — 추천 태그 칩 패널
# ---------------------------------------------------------------------------

class RecommendedTagsPanel(QFrame):
    """자동 의존성 + Expression/Clothing/Characteristic 칩 행 패널."""

    chip_toggled = pyqtSignal(str, bool)  # (tag_name, checked)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._active_tags: dict[str, bool] = {}
        self._refreshing = False

        self.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
            }}
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(
            get_scaled_size(8), get_scaled_size(6),
            get_scaled_size(8), get_scaled_size(6),
        )
        main_layout.setSpacing(get_scaled_size(4))

        # 헤더 행 (타이틀 + Clear 버튼)
        header_row = QWidget()
        header_row.setStyleSheet("background: transparent; border: none;")
        header_layout = QHBoxLayout(header_row)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(get_scaled_size(6))

        header = QLabel("Recommended Tags")
        header.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(17)}px;
                font-weight: 600;
                border: none;
                background: transparent;
            }}
        """)
        header_layout.addWidget(header)
        header_layout.addStretch()

        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setStyleSheet(f"""
            QPushButton {{
                color: {DARK_COLORS['text_secondary']};
                background: transparent;
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(3)}px;
                padding: {get_scaled_size(1)}px {get_scaled_size(8)}px;
                font-size: {get_scaled_font_size(13)}px;
            }}
            QPushButton:hover {{
                color: {DARK_COLORS['text_primary']};
                background: {DARK_COLORS['bg_hover']};
            }}
        """)
        self._clear_btn.clicked.connect(self._on_clear_clicked)
        header_layout.addWidget(self._clear_btn)

        main_layout.addWidget(header_row)

        # 자동 의존성 라벨
        self._auto_dep_label = QLabel("")
        self._auto_dep_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(16)}px;
                font-style: italic;
                border: none;
                background: transparent;
            }}
        """)
        self._auto_dep_label.setWordWrap(True)
        self._auto_dep_label.setVisible(False)
        main_layout.addWidget(self._auto_dep_label)

        # 카테고리별 칩 행 생성
        self._expr_row, self._expr_chip_layout = self._create_chip_row("Expression", "expression")
        main_layout.addWidget(self._expr_row)

        self._cloth_row, self._cloth_chip_layout = self._create_chip_row("Clothing", "clothing")
        main_layout.addWidget(self._cloth_row)

        self._char_row, self._char_chip_layout = self._create_chip_row("Characteristic", "characteristic")
        main_layout.addWidget(self._char_row)

        # 계층 정보 라벨
        self._hier_label = QLabel("")
        self._hier_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(16)}px;
                font-style: italic;
                border: none;
                background: transparent;
            }}
        """)
        self._hier_label.setWordWrap(True)
        main_layout.addWidget(self._hier_label)

        self.setVisible(False)

    def _create_chip_row(self, label_text: str, category: str) -> tuple[QWidget, FlowLayout]:
        """카테고리 칩 행 위젯 생성."""
        row = QWidget()
        row.setStyleSheet("background: transparent; border: none;")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(get_scaled_size(4))

        label = QLabel(label_text)
        label.setFixedWidth(get_scaled_size(72))
        label.setStyleSheet(f"""
            QLabel {{
                color: {_category_label_color(category)};
                font-size: {get_scaled_font_size(16)}px;
                border: none;
                background: transparent;
            }}
        """)
        row_layout.addWidget(label, alignment=Qt.AlignmentFlag.AlignTop)

        chip_area = QWidget()
        chip_area.setStyleSheet("background: transparent; border: none;")
        chip_layout = FlowLayout(chip_area, spacing=get_scaled_size(3))
        chip_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(chip_area, stretch=1)

        return row, chip_layout

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------

    @property
    def active_tags(self) -> dict[str, bool]:
        return self._active_tags

    def set_auto_deps(self, tags: list[str]) -> None:
        """자동 의존성 태그 표시."""
        if tags:
            self._auto_dep_label.setText("Auto: " + ", ".join(tags))
            self._auto_dep_label.setVisible(True)
        else:
            self._auto_dep_label.setText("")
            self._auto_dep_label.setVisible(False)

    def set_hier_info(self, text: str) -> None:
        """계층 정보 텍스트 설정."""
        self._hier_label.setText(text)
        self._hier_label.setVisible(bool(text))

    def refresh_chips(
        self,
        expr_tags: list[tuple[str, float]],
        cloth_tags: list[tuple[str, float]],
        char_tags: list[tuple[str, float]],
        auto_deps: list[str] | None = None,
    ) -> None:
        """칩 패널 전체 갱신."""
        self._refreshing = True
        try:
            has_any = bool(
                auto_deps or expr_tags or cloth_tags or char_tags
                or self._hier_label.isVisible()
            )
            self.setVisible(has_any)
            if not has_any:
                self._active_tags = {}
                return

            # 자동 의존성
            if auto_deps is not None:
                self.set_auto_deps(auto_deps)

            # 기존 ON 상태 유지, 새 태그는 OFF
            new_active: dict[str, bool] = {}
            for tag, _ in expr_tags + cloth_tags + char_tags:
                new_active[tag] = self._active_tags.get(tag, False)
            self._active_tags = new_active

            # 선택된 태그를 왼쪽으로 우선 배치 (checked first)
            def _sorted(tags: list[tuple[str, float]]) -> list[tuple[str, float]]:
                on = [(t, c) for t, c in tags if self._active_tags.get(t, False)]
                off = [(t, c) for t, c in tags if not self._active_tags.get(t, False)]
                return on + off

            # Expression 칩
            self._expr_chip_layout.clear_widgets()
            if expr_tags:
                for tag, conf in _sorted(expr_tags):
                    self._expr_chip_layout.addWidget(
                        self._make_chip(tag, "expression", conf)
                    )
                self._expr_row.setVisible(True)
            else:
                self._expr_row.setVisible(False)

            # Clothing 칩
            self._cloth_chip_layout.clear_widgets()
            if cloth_tags:
                for tag, conf in _sorted(cloth_tags):
                    self._cloth_chip_layout.addWidget(
                        self._make_chip(tag, "clothing", conf)
                    )
                self._cloth_row.setVisible(True)
            else:
                self._cloth_row.setVisible(False)

            # Characteristic 칩
            self._char_chip_layout.clear_widgets()
            if char_tags:
                for tag, conf in _sorted(char_tags):
                    self._char_chip_layout.addWidget(
                        self._make_chip(tag, "characteristic", conf)
                    )
                self._char_row.setVisible(True)
            else:
                self._char_row.setVisible(False)
        finally:
            self._refreshing = False

    def get_active_tag_list(self) -> list[str]:
        """현재 활성화(체크)된 태그 리스트."""
        return [t for t, on in self._active_tags.items() if on]

    def clear_selections(self) -> None:
        """칩 선택 상태만 초기화 (레이아웃/표시는 유지)."""
        self._active_tags = {t: False for t in self._active_tags}

    def _on_clear_clicked(self) -> None:
        """Clear 버튼 클릭 → 선택 초기화 + 시그널 발행."""
        self.clear_selections()
        # 부모에 알림 (프롬프트 재조립 트리거)
        self.chip_toggled.emit("", False)

    def clear(self) -> None:
        """모든 칩과 상태 초기화."""
        self._active_tags = {}
        self._expr_chip_layout.clear_widgets()
        self._cloth_chip_layout.clear_widgets()
        self._char_chip_layout.clear_widgets()
        self._auto_dep_label.setVisible(False)
        self._hier_label.setVisible(False)
        self.setVisible(False)

    # ------------------------------------------------------------------
    # 내부
    # ------------------------------------------------------------------

    def _make_chip(self, tag: str, category: str, confidence: float = 0.0) -> QPushButton:
        """토글 가능한 태그 칩 생성."""
        chip = QPushButton(tag)
        chip.setCheckable(True)
        chip.setChecked(self._active_tags.get(tag, False))
        chip.setProperty("rec_tag", tag)

        if confidence > 0:
            chip.setToolTip(f"{tag} (confidence: {confidence:.3f})")

        on_bg, on_border, off_bg, off_border = _chip_colors(category)

        chip.setStyleSheet(f"""
            QPushButton {{
                font-size: {get_scaled_font_size(17)}px;
                padding: {get_scaled_size(2)}px {get_scaled_size(7)}px;
                border-radius: {get_scaled_size(3)}px;
                color: {DARK_COLORS['text_primary']};
                background: {on_bg};
                border: 1px solid {on_border};
            }}
            QPushButton:!checked {{
                color: {DARK_COLORS['text_disabled']};
                background: {off_bg};
                border: 1px solid {off_border};
            }}
            QPushButton:hover {{
                color: {DARK_COLORS['text_primary']};
            }}
        """)

        chip.toggled.connect(lambda checked, t=tag: self._on_chip_toggled(t, checked))
        return chip

    def _on_chip_toggled(self, tag: str, checked: bool) -> None:
        self._active_tags[tag] = checked
        if self._refreshing:
            return
        self.chip_toggled.emit(tag, checked)


# ---------------------------------------------------------------------------
# RichComboDelegate — HTML 렌더링 콤보박스 아이템
# ---------------------------------------------------------------------------

class RichComboDelegate(QStyledItemDelegate):
    """QComboBox 팝업에서 HTML 텍스트를 렌더링하는 아이템 델리게이트."""

    def paint(self, painter, option, index):  # noqa: N802
        self.initStyleOption(option, index)
        style = option.widget.style() if option.widget else QApplication.style()

        # 기본 텍스트 그리기 억제 → HTML 렌더링
        option.text = ""
        style.drawControl(
            QStyle.ControlElement.CE_ItemViewItem, option, painter, option.widget,
        )

        html = index.data(ROLE_HTML)
        if not html:
            # 폴백: 일반 텍스트
            painter.save()
            painter.setPen(option.palette.text().color())
            painter.drawText(
                option.rect.adjusted(get_scaled_size(4), 0, 0, 0),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                index.data(Qt.ItemDataRole.DisplayRole) or "",
            )
            painter.restore()
            return

        doc = QTextDocument()
        doc.setDefaultFont(option.font)
        doc.setHtml(html)

        painter.save()
        y_offset = max(0, (option.rect.height() - doc.size().height()) / 2)
        painter.translate(
            option.rect.left() + get_scaled_size(4),
            option.rect.top() + y_offset,
        )
        doc.drawContents(painter)
        painter.restore()

    def sizeHint(self, option, index):  # noqa: N802
        hint = super().sizeHint(option, index)
        return QSize(hint.width(), max(hint.height(), get_scaled_size(20)))


# ---------------------------------------------------------------------------
# ComboTagDelegate — Observed Combo 셀의 태그 색상 하이라이팅
# ---------------------------------------------------------------------------

# 태그 색상 (선택 이벤트: 연노랑, 의존성: 연녹색)
_CLR_EVENT = "#F5E6A3"
_CLR_DEP = "#A8D5BA"


class ComboTagDelegate(QStyledItemDelegate):
    """Observed Event Combo 열의 태그를 색상으로 구분하는 델리게이트.

    - 선택된 이벤트 태그 → 연노랑
    - [dependency] 태그 → 연녹색
    - 나머지 → 기본 텍스트 색
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._event_tags: set[str] = set()

    def set_event_tags(self, tags: set[str]) -> None:
        """현재 선택/스테이징된 이벤트 태그 설정."""
        self._event_tags = tags

    # ---- paint -----------------------------------------------------------

    def paint(self, painter, option, index):  # noqa: N802
        if index.column() != 0:
            super().paint(painter, option, index)
            return

        self.initStyleOption(option, index)
        style = option.widget.style() if option.widget else QApplication.style()

        # 기본 배경/선택 그리기 (텍스트는 직접 렌더)
        option.text = ""
        style.drawControl(
            QStyle.ControlElement.CE_ItemViewItem, option, painter, option.widget,
        )

        raw = index.data(Qt.ItemDataRole.DisplayRole) or ""
        if not raw:
            return

        html = self._colorize(raw)
        doc = QTextDocument()
        doc.setDefaultFont(option.font)
        doc.setHtml(html)
        doc.setTextWidth(option.rect.width() - get_scaled_size(4))

        painter.save()
        painter.translate(
            option.rect.left() + get_scaled_size(4),
            option.rect.top(),
        )
        doc.drawContents(painter)
        painter.restore()

    def sizeHint(self, option, index):  # noqa: N802
        if index.column() != 0:
            return super().sizeHint(option, index)

        raw = index.data(Qt.ItemDataRole.DisplayRole) or ""
        if not raw:
            return super().sizeHint(option, index)

        doc = QTextDocument()
        doc.setDefaultFont(option.font)
        doc.setHtml(self._colorize(raw))

        # 테이블 뷰포트 너비 기준 word-wrap 계산
        widget = option.widget
        if widget:
            col_w = widget.columnWidth(0) - get_scaled_size(4)
            if col_w > 0:
                doc.setTextWidth(col_w)

        return QSize(int(doc.idealWidth()), int(doc.size().height()))

    # ---- internal --------------------------------------------------------

    def _colorize(self, text: str) -> str:
        """콤마 구분 태그를 HTML 색상 스팬으로 변환."""
        default_color = DARK_COLORS['text_primary']
        parts: list[str] = []
        for token in text.split(","):
            token = token.strip()
            if not token:
                continue
            if token.startswith("[") and token.endswith("]"):
                # 의존성 태그
                parts.append(f'<span style="color:{_CLR_DEP}">{token}</span>')
            elif token in self._event_tags:
                # 선택된 이벤트 태그
                parts.append(f'<span style="color:{_CLR_EVENT}">{token}</span>')
            else:
                parts.append(f'<span style="color:{default_color}">{token}</span>')
        sep = f'<span style="color:{default_color}">, </span>'
        return sep.join(parts)


# ---------------------------------------------------------------------------
# ImagePreviewWidget — PIL Image → QPixmap 표시
# ---------------------------------------------------------------------------

class ImagePreviewWidget(QLabel):
    """PIL Image를 QPixmap으로 변환하여 표시하는 위젯.

    QImage 참조를 유지하여 SEGFAULT를 방지 (ImageQt 패턴).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._qimage: QImage | None = None  # GC 방지용 참조 유지

        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(get_scaled_size(256), get_scaled_size(256))
        self.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        )
        self._apply_placeholder_style()
        self.setText("No Preview")

    def _apply_placeholder_style(self) -> None:
        self.setStyleSheet(f"""
            QLabel {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
                color: {DARK_COLORS['text_disabled']};
                font-size: {get_scaled_font_size(19)}px;
            }}
        """)

    def display_image(self, pil_image) -> None:
        """PIL Image를 표시. BytesIO 변환으로 SEGFAULT 방지."""
        import io
        try:
            buf = io.BytesIO()
            pil_image.save(buf, format="PNG")
            buf.seek(0)

            qimage = QImage()
            qimage.loadFromData(buf.getvalue())
            self._qimage = qimage  # 참조 유지

            pixmap = QPixmap.fromImage(qimage)
            scaled = pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.setPixmap(scaled)
        except Exception as e:
            self.clear_image()
            print(f"[EventPreset] 이미지 표시 오류: {e}")

    def display_base64(self, b64_string: str) -> None:
        """base64 인코딩된 JPEG를 표시."""
        import base64
        try:
            img_bytes = base64.b64decode(b64_string)
            qimage = QImage()
            qimage.loadFromData(img_bytes)
            self._qimage = qimage  # GC 방지
            pixmap = QPixmap.fromImage(qimage)
            scaled = pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.setPixmap(scaled)
        except Exception:
            self.clear_image()

    def clear_image(self) -> None:
        """이미지 초기화."""
        self._qimage = None
        self.clear()
        self.setText("No Preview")

    def resizeEvent(self, event) -> None:  # noqa: N802
        """리사이즈 시 이미지 재스케일링."""
        super().resizeEvent(event)
        if self._qimage is not None:
            pixmap = QPixmap.fromImage(self._qimage)
            scaled = pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.setPixmap(scaled)


# ---------------------------------------------------------------------------
# StagingBar — 스테이징 상태 표시 바
# ---------------------------------------------------------------------------

class StagingBar(QWidget):
    """이벤트 스테이징 상태 + Clear 버튼 바."""

    clear_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, get_scaled_size(2), 0, get_scaled_size(2))
        layout.setSpacing(get_scaled_size(8))

        self._label = QLabel("Staged: (none)")
        self._label.setWordWrap(True)
        self._label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_disabled']};
                font-size: {get_scaled_font_size(18)}px;
                border: none;
                background: transparent;
            }}
        """)

        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setFixedWidth(get_scaled_size(60))
        self._clear_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(3)}px;
                padding: {get_scaled_size(2)}px {get_scaled_size(8)}px;
                font-size: {get_scaled_font_size(17)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
        """)
        self._clear_btn.clicked.connect(self.clear_requested.emit)
        self._clear_btn.setVisible(False)

        layout.addWidget(self._label)
        layout.addWidget(self._clear_btn)
        layout.addStretch()

    def update_staging(self, staged_events: list[str]) -> None:
        """스테이징 상태 업데이트."""
        if staged_events:
            names = ", ".join(staged_events)
            self._label.setText(f"Staged: {names}")
            self._label.setStyleSheet(f"""
                QLabel {{
                    color: {DARK_COLORS['accent_blue_light']};
                    font-size: {get_scaled_font_size(18)}px;
                    border: none;
                    background: transparent;
                }}
            """)
            self._clear_btn.setVisible(True)
        else:
            self._label.setText("Staged: (none)")
            self._label.setStyleSheet(f"""
                QLabel {{
                    color: {DARK_COLORS['text_disabled']};
                    font-size: {get_scaled_font_size(18)}px;
                    border: none;
                    background: transparent;
                }}
            """)
            self._clear_btn.setVisible(False)


# ---------------------------------------------------------------------------
# SwitchPartitionBar — 파티션 전환 바
# ---------------------------------------------------------------------------

class SwitchPartitionBar(QWidget):
    """Switch-to 파티션 콤보 바."""

    RATING_COLORS = {"g": "#4CAF50", "s": "#FF9800", "q": "#9C27B0", "e": "#F44336"}

    partition_selected = pyqtSignal(str)  # partition_name

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, get_scaled_size(2))
        layout.setSpacing(get_scaled_size(6))

        self._label = QLabel("Switch")
        self._label.setFixedWidth(get_scaled_size(80))
        self._label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(17)}px;
                border: none;
                background: transparent;
            }}
        """)
        layout.addWidget(self._label)

        self._combo = QComboBox()
        self._combo.setMaxVisibleItems(20)
        self._combo.setItemDelegate(RichComboDelegate(self._combo))
        self._combo.setStyleSheet(f"""
            QComboBox {{
                font-size: {get_scaled_font_size(17)}px;
                padding: {get_scaled_size(2)}px {get_scaled_size(4)}px;
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(3)}px;
            }}
            QComboBox::drop-down {{
                border: none;
            }}
            QComboBox QAbstractItemView {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                selection-background-color: {DARK_COLORS['accent_blue']};
                border: 1px solid {DARK_COLORS['border']};
            }}
        """)
        self._combo.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        )
        self._combo.currentIndexChanged.connect(self._on_index_changed)
        layout.addWidget(self._combo)

        self.setVisible(False)

    @property
    def combo(self):
        return self._combo

    def _on_index_changed(self, index: int) -> None:
        if index >= 0:
            data = self._combo.itemData(index)
            if data:
                self.partition_selected.emit(data)

    def populate(
        self, items: list[tuple[str, str, str]], current_label: str = "",
    ) -> None:
        """콤보 아이템 설정. items = [(display_text, partition_name, html)]"""
        self._combo.blockSignals(True)
        self._combo.clear()
        for display, partition, html in items:
            self._combo.addItem(display, partition)
            idx = self._combo.count() - 1
            if html:
                self._combo.setItemData(idx, html, ROLE_HTML)
        # 현재 활성 파티션을 placeholder로 표시, 선택 대기 상태
        if current_label:
            self._combo.setPlaceholderText(current_label)
        self._combo.setCurrentIndex(-1)
        self._combo.blockSignals(False)
        self.setVisible(len(items) > 0)

    def set_current_rating(self, prefix: str) -> None:
        """현재 활성 파티션의 rating prefix 배지 표시. prefix: 'g','s','q','e'"""
        color = self.RATING_COLORS.get(prefix, DARK_COLORS['text_secondary'])
        self._label.setText(f'Switch <span style="color:{color}; font-weight:700">[{prefix.upper()}]</span>')
        self._label.setTextFormat(Qt.TextFormat.RichText)
