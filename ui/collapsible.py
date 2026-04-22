# ui/collapsible.py
# CollapsibleBox / FixedBox — QScrollArea를 사용하지 않는 순수 QWidget 기반
# 부모 QScrollArea(left_panel_scroll_area)가 전체 스크롤을 담당

from ui.theme import DARK_STYLES, DARK_COLORS
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSizePolicy, QToolButton, QMenu, QFrame, QLabel
)
from PyQt6.QtCore import Qt, pyqtSignal, QPoint
from PyQt6.QtGui import QAction, QMouseEvent


class EnhancedCollapsibleBox(QWidget):
    """우클릭 컨텍스트 메뉴가 있는 향상된 접고 펼 수 있는 위젯.
    내부에 QScrollArea 없이 콘텐츠를 완전히 펼침."""

    module_detach_requested = pyqtSignal(str, object)
    toggled = pyqtSignal(str, bool)

    def __init__(self, title="", parent=None, detachable=True, start_expanded=False):
        super().__init__(parent)
        self.title = title
        self.detachable = detachable
        self.content_widget = None
        self.is_detached = False
        self._start_expanded = start_expanded

        # 174 hotfix: stylesheet 의 `QWidget#collapsibleBox` 셀렉터와 매칭시키기
        # 위한 objectName. 이 이름이 없으면 border/bg 가 적용되지 않는다.
        self.setObjectName("collapsibleBox")
        self.setStyleSheet(DARK_STYLES['collapsible_box'])
        self.init_ui()

    def init_ui(self):
        """UI 초기화"""
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setSpacing(0)
        m = get_scaled_size(8)
        self.main_layout.setContentsMargins(m, get_scaled_size(6), m, m)

        # 제목 버튼
        self.toggle_button = QToolButton(text=f" {self.title}", checkable=True, checked=False)
        self.toggle_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle_button.setArrowType(Qt.ArrowType.RightArrow)
        self.toggle_button.toggled.connect(self.on_toggled)

        # Anlas 표시용 레이블
        self.anlas_label = QLabel("")
        self.anlas_label.setStyleSheet(f"color: #FFFF97; font-size: {get_scaled_font_size(19)}px; font-weight: bold; padding: 0 10px;")
        self.anlas_label.setVisible(False)

        if self.detachable:
            self.toggle_button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.toggle_button.customContextMenuRequested.connect(self.show_context_menu)

        # 콘텐츠 영역: 순수 QWidget (QScrollArea 아님)
        self.content_area = QWidget()
        self.content_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.content_area.setMaximumHeight(0)
        self.content_area.setMinimumHeight(0)
        self.content_area.setStyleSheet("background-color: transparent;")
        self._content_layout = QVBoxLayout(self.content_area)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(0)

        # 헤더 레이아웃
        header_layout = QHBoxLayout()
        header_layout.setSpacing(0)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.addWidget(self.toggle_button)
        header_layout.addWidget(self.anlas_label)
        header_layout.addStretch()

        self.main_layout.addLayout(header_layout)
        self.main_layout.addWidget(self.content_area)

        if self._start_expanded:
            self.toggle_button.setChecked(True)

    def show_context_menu(self, position: QPoint):
        if self.is_detached:
            return
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px; padding: 5px;
            }}
            QMenu::item {{ padding: 8px 20px; border-radius: 4px; }}
            QMenu::item:selected {{ background-color: {DARK_COLORS['accent_blue']}; }}
        """)
        detach_action = QAction("🔗 외부 창에서 열기", self)
        detach_action.triggered.connect(self.request_detach)
        menu.addAction(detach_action)
        menu.exec(self.toggle_button.mapToGlobal(position))

    def on_toggled(self, checked):
        if self.is_detached:
            return
        self.toggle_button.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        if checked:
            self.content_area.setMaximumHeight(16777215)
        else:
            self.content_area.setMaximumHeight(0)
        self.toggled.emit(self.title, checked)

    def update_anlas(self, anlas_value):
        if anlas_value is not None:
            self.anlas_label.setText(f"[Anlas: {anlas_value}]")
            self.anlas_label.setVisible(True)
        else:
            self.anlas_label.setVisible(False)

    def setContentLayout(self, layout):
        """콘텐츠 레이아웃 설정"""
        if layout is None:
            print(f"⚠️ 모듈 '{self.title}': 레이아웃이 None입니다.")
            return

        content_widget = QWidget()
        content_widget.setStyleSheet("background-color: transparent;")
        content_widget.setLayout(layout)
        content_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self.content_widget = content_widget
        self._content_layout.addWidget(content_widget)
        print(f"[OK] '{self.title}': content setup complete")

    def request_detach(self):
        if self.content_widget and not self.is_detached:
            try:
                _ = self.content_widget.isVisible()
                self.module_detach_requested.emit(self.title, self.content_widget)
            except RuntimeError:
                print(f"❌ 모듈 '{self.title}'의 위젯이 이미 삭제되었습니다.")
        else:
            print(f"[WARNING] Module '{self.title}': content_widget is None or already detached")

    def set_detached_state(self, is_detached: bool):
        self.is_detached = is_detached
        if is_detached:
            # 플레이스홀더로 교체
            placeholder = self.create_placeholder()
            self._content_layout.addWidget(placeholder)

            self.toggle_button.setText(f" 🔗 {self.title} (외부 창)")
            self.toggle_button.setStyleSheet(f"QToolButton {{ color: {DARK_COLORS['accent_blue']}; }}")
            self.toggle_button.setChecked(True)
            self.toggle_button.setEnabled(False)
            self.content_area.setMaximumHeight(150)
        else:
            self.toggle_button.setText(f" {self.title}")
            self.toggle_button.setStyleSheet("")
            self.toggle_button.setEnabled(True)
            self.toggle_button.setChecked(False)
            self.content_area.setMaximumHeight(0)

    def create_placeholder(self) -> QWidget:
        placeholder = QFrame()
        placeholder.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 2px dashed {DARK_COLORS['border_light']};
                border-radius: 8px; margin: 4px;
            }}
        """)
        layout = QVBoxLayout(placeholder)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(8)
        layout.setContentsMargins(16, 16, 16, 16)

        icon_label = QLabel("🔗")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet(f"QLabel {{ font-size: {get_scaled_font_size(24)}px; color: {DARK_COLORS['text_secondary']}; }}")

        message_label = QLabel(f"'{self.title}' 모듈이\n외부 창에서 열려있습니다")
        message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message_label.setStyleSheet(f"QLabel {{ font-size: {get_scaled_font_size(12)}px; color: {DARK_COLORS['text_secondary']}; font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif; }}")

        layout.addWidget(icon_label)
        layout.addWidget(message_label)
        return placeholder

    def get_content_widget(self):
        return self.content_widget

    # 상태 추적 및 제어

    def is_expanded(self) -> bool:
        return self.toggle_button.isChecked() and not self.is_detached

    def set_expanded(self, expanded: bool, emit_signal: bool = True):
        if self.is_detached:
            return
        if not emit_signal:
            self.toggle_button.blockSignals(True)
        self.toggle_button.setChecked(expanded)
        if not emit_signal:
            self.toggle_button.blockSignals(False)
            self.toggle_button.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
            if expanded:
                self.content_area.setMaximumHeight(16777215)
            else:
                self.content_area.setMaximumHeight(0)

    def collapse(self, emit_signal: bool = True):
        self.set_expanded(False, emit_signal)

    def expand(self, emit_signal: bool = True):
        self.set_expanded(True, emit_signal)

    # 레거시 호환 (스크롤 위치 — 이제 부모 스크롤이 담당하므로 no-op)
    def _save_scroll_position(self):
        pass

    def _restore_scroll_position(self):
        pass

    def get_scroll_position(self) -> int:
        return 0

    def set_scroll_position(self, position: int):
        pass


class _ResizeHandle(QFrame):
    """FixedBox 하단 리사이즈 핸들"""

    def __init__(self, parent_box, parent=None):
        super().__init__(parent)
        self._parent_box = parent_box
        self._dragging = False
        self._start_y = 0
        self._start_height = 0
        self.setFixedHeight(get_scaled_size(4))
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['border_light']};
                border-radius: {get_scaled_size(2)}px;
                margin: 0 {get_scaled_size(40)}px;
            }}
            QFrame:hover {{
                background-color: {DARK_COLORS['accent_blue']};
            }}
        """)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._start_y = event.globalPosition().y()
            self._start_height = self._parent_box._current_height
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging:
            delta = int(event.globalPosition().y() - self._start_y)
            new_h = max(self._parent_box._min_height, self._start_height + delta)
            self._parent_box.set_height(new_h)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._dragging:
                self._dragging = False
                # 드래그 완료 시 높이 변경 시그널 발행
                self._parent_box.height_changed.emit(self._parent_box._current_height)
            event.accept()


class FixedBox(QWidget):
    """헤더 없이 콘텐츠만 표시 + 높이 조절 가능한 박스"""

    module_detach_requested = pyqtSignal(str, object)
    toggled = pyqtSignal(str, bool)
    height_changed = pyqtSignal(int)  # 리사이즈 완료 시 새 높이 전달

    def __init__(self, title="", parent=None, detachable=True, min_height=200, default_height=400):
        super().__init__(parent)
        self.title = title
        self.detachable = detachable
        self.is_detached = False
        self.content_widget = None
        self._min_height = get_scaled_size(min_height)
        self._current_height = get_scaled_size(default_height)

        self._init_ui()

    def _init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setSpacing(0)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        # 콘텐츠 영역: 순수 QWidget + 고정 높이
        self.content_area = QWidget()
        self.content_area.setFixedHeight(self._current_height)
        self.content_area.setStyleSheet("background-color: transparent;")
        self._content_layout = QVBoxLayout(self.content_area)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(0)
        self.main_layout.addWidget(self.content_area)

        # 리사이즈 핸들
        self._resize_handle = _ResizeHandle(self, self)
        self.main_layout.addWidget(self._resize_handle)

    def setContentLayout(self, layout):
        if layout is None:
            return
        content_widget = QWidget()
        content_widget.setStyleSheet("background-color: transparent;")
        content_widget.setLayout(layout)
        content_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.content_widget = content_widget
        self._content_layout.addWidget(content_widget)

    def set_height(self, h: int):
        h = max(self._min_height, h)
        self._current_height = h
        self.content_area.setFixedHeight(h)

    def get_height(self) -> int:
        return self._current_height

    def get_content_widget(self):
        return self.content_widget

    def set_detached_state(self, is_detached: bool):
        self.is_detached = is_detached
        if is_detached:
            self.content_area.setFixedHeight(get_scaled_size(150))
            self._resize_handle.setVisible(False)
        else:
            self.content_area.setFixedHeight(self._current_height)
            self._resize_handle.setVisible(True)

    def is_expanded(self) -> bool:
        return True

    def set_expanded(self, expanded: bool, emit_signal: bool = True):
        pass

    def collapse(self, emit_signal: bool = True):
        pass

    def expand(self, emit_signal: bool = True):
        pass


# 기존 CollapsibleBox는 호환성을 위해 유지
class CollapsibleBox(EnhancedCollapsibleBox):
    """기존 CollapsibleBox (호환성 유지)"""
    def __init__(self, title="", parent=None):
        super().__init__(title, parent, detachable=False)