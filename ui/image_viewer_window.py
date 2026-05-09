# ui/image_viewer_window.py
"""
NAIA 전용 이미지 뷰어 — Honeyview 스타일 전체화면 뷰어

기능:
- 현재 세션 폴더의 전체 이미지 탐색
- 마우스 휠로 이전/다음 페이지 탐색
- Fit-to-window / 원본 크기 토글 + 줌
- 상단/하단 플로팅 오버레이 (마우스 호버 시 표시, 고정 가능)
- 하단: 페이지 슬라이더 + 네비게이션 + 줌/회전
- 상단: 파일 정보 + 창 제어 버튼
- 전후 10/20장 pixmap 프리로드 캐시
- 사용자 정의 키/마우스 바인딩 → 복사/이동/삭제 액션
"""

import json
import shutil
import os
from collections import OrderedDict
from pathlib import Path
from typing import Optional, List, Dict, Tuple

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QSlider, QFrame, QApplication,
    QDialog, QComboBox, QMenu, QLineEdit, QCheckBox, QFileDialog
)
from PyQt6.QtCore import Qt, QTimer, QPointF, QRectF, pyqtSignal, QSize, QThread, pyqtSlot, QEvent
from PyQt6.QtGui import (
    QPixmap, QImage, QKeyEvent, QWheelEvent, QMouseEvent,
    QPainter, QColor, QCursor
)

from ui.theme import DARK_COLORS
from utils.clipboard_image import qimage_to_png_bytes, set_png_clipboard_bytes
from ui.scaling_manager import get_scaled_font_size, get_scaled_size


IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif'}

_EDGE_TRIGGER_PX = 100
_HIDE_DELAY_MS = 500
_CACHE_BEHIND = 10
_CACHE_AHEAD = 20
_CACHE_MAX = _CACHE_BEHIND + _CACHE_AHEAD + 1

_SETTINGS_PATH = Path("save/app_settings.json")

# 액션 타입
ACTION_COPY = "copy"
ACTION_MOVE = "move"
ACTION_DELETE = "delete"

ACTION_LABELS = {
    ACTION_COPY: "복사",
    ACTION_MOVE: "이동",
    ACTION_DELETE: "삭제 (휴지통)",
}


# ================================================================
# 입력 식별 유틸
# ================================================================

def _input_id_from_mouse(button: Qt.MouseButton) -> str:
    """Qt.MouseButton → 저장 가능한 문자열 ID"""
    mapping = {
        Qt.MouseButton.ForwardButton: "mouse:forward",
        Qt.MouseButton.BackButton: "mouse:back",
        Qt.MouseButton.MiddleButton: "mouse:middle",
        Qt.MouseButton.ExtraButton3: "mouse:extra3",
        Qt.MouseButton.ExtraButton4: "mouse:extra4",
        Qt.MouseButton.ExtraButton5: "mouse:extra5",
        Qt.MouseButton.ExtraButton6: "mouse:extra6",
        Qt.MouseButton.ExtraButton7: "mouse:extra7",
        Qt.MouseButton.ExtraButton8: "mouse:extra8",
        Qt.MouseButton.ExtraButton9: "mouse:extra9",
        Qt.MouseButton.ExtraButton10: "mouse:extra10",
    }
    return mapping.get(button, f"mouse:{button.value}")


def _input_id_from_key(key: int) -> str:
    """Qt.Key int → 저장 가능한 문자열 ID"""
    return f"key:{key}"


def _input_display_name(input_id: str) -> str:
    """input_id → 사람이 읽을 수 있는 이름"""
    if input_id.startswith("mouse:"):
        name = input_id.split(":", 1)[1]
        mouse_names = {
            "forward": "Mouse Forward",
            "back": "Mouse Back",
            "middle": "Mouse Middle",
        }
        return mouse_names.get(name, f"Mouse {name.title()}")
    elif input_id.startswith("key:"):
        key_int = int(input_id.split(":", 1)[1])
        from PyQt6.QtGui import QKeySequence
        text = QKeySequence(key_int).toString()
        return text if text else f"Key({key_int})"
    return input_id


# ================================================================
# 바인딩 설정 다이얼로그
# ================================================================

class _InputCaptureButton(QPushButton):
    """클릭 후 다음 키보드/마우스 입력을 캡처하는 버튼"""

    input_captured = pyqtSignal(str)  # input_id

    def __init__(self, current_id: str = "", parent=None):
        super().__init__(parent)
        self._input_id = current_id
        self._capturing = False
        self._is_duplicate_fn = None  # 외부에서 주입: (input_id, self) -> bool
        self._update_text()
        self.clicked.connect(self._start_capture)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _update_text(self):
        if self._capturing:
            self.setText("[ 입력 대기중... ]")
        elif self._input_id:
            self.setText(_input_display_name(self._input_id))
        else:
            self.setText("(미설정)")

    def _start_capture(self):
        self._capturing = True
        self._update_text()
        self.grabKeyboard()
        self.grabMouse()

    def _release_grab(self):
        """grab 상태를 안전하게 해제"""
        try:
            self.releaseKeyboard()
        except RuntimeError:
            pass
        try:
            self.releaseMouse()
        except RuntimeError:
            pass

    def _finish_capture(self, input_id: str):
        self._capturing = False
        self._release_grab()

        # 중복 체크
        if self._is_duplicate_fn and self._is_duplicate_fn(input_id, self):
            # 중복 → 이전 값 유지
            self._update_text()
            return

        self._input_id = input_id
        self._update_text()
        self.input_captured.emit(input_id)

    def get_input_id(self) -> str:
        return self._input_id

    def keyPressEvent(self, event: QKeyEvent):
        if self._capturing:
            if event.key() == Qt.Key.Key_Escape:
                self._capturing = False
                self._release_grab()
                self._update_text()
                return
            self._finish_capture(_input_id_from_key(event.key()))
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        if self._capturing:
            btn = event.button()
            # 좌클릭은 캡처 시작 트리거이므로 무시
            if btn == Qt.MouseButton.LeftButton:
                event.accept()
                return
            self._finish_capture(_input_id_from_mouse(btn))
        else:
            super().mousePressEvent(event)


class ViewerBindingsDialog(QDialog):
    """뷰어 키/마우스 바인딩 설정 다이얼로그"""

    _MAX_BINDINGS = 3

    def __init__(self, bindings: List[Dict], dest_path: str = "", use_session_folder: bool = True, parent=None):
        super().__init__(parent)
        self.setWindowTitle("뷰어 입력 설정")
        self.setMinimumWidth(get_scaled_size(520))
        self._dest_path = dest_path
        self._use_session_folder = use_session_folder
        self.setStyleSheet(f"""
            QDialog {{
                color: {DARK_COLORS['text_primary']};
            }}
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(16)}px;
            }}
            QComboBox {{
                background-color: #FFFFFF;
                color: #222222;
                border: 1px solid {DARK_COLORS['border']};
                padding: {get_scaled_size(6)}px;
                font-size: {get_scaled_font_size(16)}px;
                border-radius: {get_scaled_size(3)}px;
            }}
            QComboBox QAbstractItemView {{
                background-color: #FFFFFF;
                color: #222222;
                selection-background-color: {DARK_COLORS['accent_blue']};
                selection-color: white;
            }}
            QPushButton {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                padding: {get_scaled_size(8)}px {get_scaled_size(14)}px;
                font-size: {get_scaled_font_size(16)}px;
                border-radius: {get_scaled_size(3)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
        """)

        self._rows: List[Tuple[_InputCaptureButton, QComboBox]] = []
        self._init_ui(bindings)

    def _init_ui(self, bindings: List[Dict]):
        layout = QVBoxLayout(self)
        layout.setSpacing(get_scaled_size(12))

        # 설명
        desc = QLabel("입력 버튼을 클릭 후 키보드 또는 마우스 버튼을 눌러 바인딩합니다.\nESC = 캡처 취소")
        desc.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(14)}px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # 바인딩 행들
        self._rows_layout = QVBoxLayout()
        self._rows_layout.setSpacing(get_scaled_size(8))
        layout.addLayout(self._rows_layout)

        for b in bindings:
            self._add_row(b.get("input_id", ""), b.get("action", ACTION_COPY))

        # 빈 행이 없으면 하나 추가
        if not bindings:
            self._add_row("mouse:forward", ACTION_COPY)

        # === 대상 경로 설정 ===
        layout.addWidget(self._make_section_separator())

        path_title = QLabel("복사/이동 대상 경로")
        path_title.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(15)}px; font-weight: bold;")
        layout.addWidget(path_title)

        path_row = QHBoxLayout()
        path_row.setSpacing(get_scaled_size(6))

        self._path_edit = QLineEdit(self._dest_path)
        self._path_edit.setPlaceholderText(str(Path.home() / "Pictures" / "꿀뷰" / "NAIA"))
        self._path_edit.setStyleSheet(f"""
            QLineEdit {{
                background-color: #FFFFFF;
                color: #222222;
                border: 1px solid {DARK_COLORS['border']};
                padding: {get_scaled_size(6)}px;
                font-size: {get_scaled_font_size(14)}px;
                border-radius: {get_scaled_size(3)}px;
            }}
        """)
        path_row.addWidget(self._path_edit, 1)

        btn_browse = QPushButton("찾아보기")
        btn_browse.clicked.connect(self._browse_dest_path)
        path_row.addWidget(btn_browse)

        layout.addLayout(path_row)

        self._session_checkbox = QCheckBox("세션명 폴더 사용 (경로 하위에 세션 폴더 자동 생성)")
        self._session_checkbox.setChecked(self._use_session_folder)
        self._session_checkbox.setStyleSheet(f"""
            QCheckBox {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(13)}px;
                spacing: {get_scaled_size(6)}px;
            }}
        """)
        layout.addWidget(self._session_checkbox)

        # === 추가/확인 버튼 ===
        btn_row = QHBoxLayout()

        self._btn_add = QPushButton("+ 바인딩 추가")
        self._btn_add.clicked.connect(self._on_add_clicked)
        btn_row.addWidget(self._btn_add)
        self._update_add_button()

        btn_row.addStretch()

        btn_ok = QPushButton("확인")
        btn_ok.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['accent_blue']};
                color: white;
                border: none;
                padding: {get_scaled_size(8)}px {get_scaled_size(20)}px;
                font-size: {get_scaled_font_size(16)}px;
                border-radius: {get_scaled_size(4)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['accent_blue_hover']};
            }}
        """)
        btn_ok.clicked.connect(self.accept)
        btn_row.addWidget(btn_ok)

        btn_cancel = QPushButton("취소")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        layout.addLayout(btn_row)

    def _get_used_actions(self) -> set:
        """현재 행에서 사용 중인 액션 set"""
        return {combo.currentData() for _, combo in self._rows}

    def _get_available_action(self) -> Optional[str]:
        """아직 사용되지 않은 첫 번째 액션 반환"""
        used = self._get_used_actions()
        for action_key in ACTION_LABELS:
            if action_key not in used:
                return action_key
        return None

    def _update_add_button(self):
        """추가 버튼 활성/비활성 업데이트"""
        if not hasattr(self, '_btn_add'):
            return
        can_add = len(self._rows) < self._MAX_BINDINGS and self._get_available_action() is not None
        self._btn_add.setEnabled(can_add)

    def _on_add_clicked(self):
        available = self._get_available_action()
        if available and len(self._rows) < self._MAX_BINDINGS:
            self._add_row("", available)
            self._update_add_button()

    def _add_row(self, input_id: str, action: str):
        row = QHBoxLayout()
        row.setSpacing(get_scaled_size(8))

        # 입력 캡처 버튼
        capture_btn = _InputCaptureButton(input_id)
        capture_btn.setFixedWidth(get_scaled_size(200))
        capture_btn._is_duplicate_fn = self._is_input_duplicate
        row.addWidget(capture_btn)

        # 액션 콤보박스 — 사용 중인 액션 제외
        combo = QComboBox()
        used = self._get_used_actions()
        for action_key, label in ACTION_LABELS.items():
            if action_key == action or action_key not in used:
                combo.addItem(label, action_key)
        # 지정된 액션을 선택
        for i in range(combo.count()):
            if combo.itemData(i) == action:
                combo.setCurrentIndex(i)
                break
        combo.currentIndexChanged.connect(lambda: self._update_add_button())
        row.addWidget(combo)

        # 삭제 버튼
        btn_del = QPushButton("✕")
        btn_del.setFixedSize(get_scaled_size(32), get_scaled_size(32))
        btn_del.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {DARK_COLORS['error']};
                border: none;
                font-size: {get_scaled_font_size(18)}px;
            }}
            QPushButton:hover {{
                background-color: rgba(244, 67, 54, 40);
                border-radius: {get_scaled_size(4)}px;
            }}
        """)
        btn_del.clicked.connect(lambda _, r=row, cap=capture_btn, cmb=combo: self._remove_row(r, cap, cmb))
        row.addWidget(btn_del)

        self._rows.append((capture_btn, combo))
        self._rows_layout.addLayout(row)

    def _is_input_duplicate(self, input_id: str, source_btn: _InputCaptureButton) -> bool:
        """다른 행에서 이미 같은 input_id를 사용 중인지 확인"""
        for capture_btn, _ in self._rows:
            if capture_btn is source_btn:
                continue
            if capture_btn.get_input_id() == input_id:
                return True
        return False

    def _remove_row(self, row_layout, capture_btn, combo):
        if (capture_btn, combo) in self._rows:
            self._rows.remove((capture_btn, combo))
        while row_layout.count():
            item = row_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._rows_layout.removeItem(row_layout)
        self._update_add_button()

    def get_bindings(self) -> List[Dict]:
        result = []
        for capture_btn, combo in self._rows:
            input_id = capture_btn.get_input_id()
            action = combo.currentData()
            if input_id:
                result.append({"input_id": input_id, "action": action})
        return result

    def get_dest_path(self) -> str:
        return self._path_edit.text().strip()

    def get_use_session_folder(self) -> bool:
        return self._session_checkbox.isChecked()

    def _browse_dest_path(self):
        current = self._path_edit.text().strip()
        if not current:
            current = str(Path.home() / "Pictures")
        folder = QFileDialog.getExistingDirectory(self, "대상 폴더 선택", current)
        if folder:
            self._path_edit.setText(folder)

    @staticmethod
    def _make_section_separator() -> QFrame:
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {DARK_COLORS['border']};")
        return sep


# ================================================================
# 휴지통 삭제 (Windows)
# ================================================================

def _send_to_recycle_bin(file_path: str) -> bool:
    """파일을 휴지통으로 보냄 (Windows SHFileOperationW)"""
    if os.name != 'nt':
        os.remove(file_path)
        return True
    try:
        import ctypes
        from ctypes import windll, Structure, c_uint, POINTER
        from ctypes.wintypes import HWND, UINT, LPCWSTR, WORD

        class SHFILEOPSTRUCTW(Structure):
            _fields_ = [
                ("hwnd", HWND),
                ("wFunc", UINT),
                ("pFrom", LPCWSTR),
                ("pTo", LPCWSTR),
                ("fFlags", WORD),
                ("fAnyOperationsAborted", c_uint),
                ("hNameMappings", c_uint),
                ("lpszProgressTitle", LPCWSTR),
            ]

        FO_DELETE = 3
        FOF_ALLOWUNDO = 0x0040
        FOF_NOCONFIRMATION = 0x0010
        FOF_SILENT = 0x0004

        # pFrom은 더블 null-terminated 이어야 함
        path_buf = file_path + '\0\0'
        op = SHFILEOPSTRUCTW()
        op.hwnd = 0
        op.wFunc = FO_DELETE
        op.pFrom = path_buf
        op.pTo = None
        op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT

        result = windll.shell32.SHFileOperationW(ctypes.byref(op))
        return result == 0
    except Exception as e:
        print(f"[Viewer] recycle bin failed: {e}")
        # fallback: 직접 삭제 시도 (복구 불가)
        try:
            os.remove(file_path)
            return True
        except OSError:
            return False


# ================================================================
# Pixmap 캐시 프리로더
# ================================================================

class _PixmapCacheWorker(QThread):
    """백그라운드에서 QImage를 로드하는 워커 (QPixmap은 GUI 스레드 전용)"""
    loaded = pyqtSignal(str, QImage)  # GUI 스레드에서 QPixmap으로 변환

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue: List[Path] = []
        self._pending: List[Path] = []  # enqueue 중 실행중이면 pending에 저장
        self._running = True

    def enqueue(self, paths: List[Path]):
        """GUI 스레드에서만 호출할 것 — _pending/_queue는 동기화 없음"""
        if self.isRunning():
            self._pending = list(paths)
        else:
            self._queue = list(paths)
            self._running = True
            self.start()

    def run(self):
        while True:
            for p in self._queue:
                if not self._running:
                    return
                qimg = self._load_qimage(p)
                if qimg and not qimg.isNull():
                    self.loaded.emit(str(p), qimg)

            # pending이 있으면 이어서 처리
            if self._pending:
                self._queue = self._pending
                self._pending = []
            else:
                break

    def stop(self):
        self._running = False
        self.quit()
        self.wait(2000)

    @staticmethod
    def _load_qimage(file_path: Path) -> Optional[QImage]:
        """비GUI 스레드 안전: QImage만 생성"""
        qimg = QImage(str(file_path))
        if not qimg.isNull():
            return qimg
        try:
            from PIL import Image
            img = Image.open(str(file_path))
            img = img.convert("RGBA")
            data = img.tobytes("raw", "RGBA")
            return QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888).copy()
        except Exception:
            return None


class PixmapCache:
    def __init__(self):
        self._cache: OrderedDict[str, QPixmap] = OrderedDict()

    def get(self, key: str) -> Optional[QPixmap]:
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def put(self, key: str, pixmap: QPixmap):
        self._cache[key] = pixmap
        self._cache.move_to_end(key)
        if len(self._cache) > _CACHE_MAX:
            self._cache.popitem(last=False)

    def clear(self):
        self._cache.clear()

    def remove(self, key: str):
        self._cache.pop(key, None)


# ================================================================
# GraphicsView
# ================================================================

class ImageViewerGraphicsView(QGraphicsView):
    mouse_moved = pyqtSignal(float, float)
    wheel_navigate = pyqtSignal(int)
    wheel_zoom = pyqtSignal(int)  # +1=zoom in, -1=zoom out
    mouse_button_pressed = pyqtSignal(str)  # input_id
    context_menu_requested = pyqtSignal(QPointF)  # global pos

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setBackgroundBrush(QColor("#000000"))
        self.setStyleSheet("border: none; background: #000000;")
        self.setMouseTracking(True)

        self._is_panning = False
        self._pan_start = QPointF()
        self._current_zoom = 1.0
        self._fit_mode = True

    def fit_in_view_proper(self):
        scene = self.scene()
        if not scene or not scene.items():
            return
        self.resetTransform()
        rect = scene.itemsBoundingRect()
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        self._current_zoom = self.transform().m11()
        self._fit_mode = True

    def set_original_size(self):
        self.resetTransform()
        self._current_zoom = 1.0
        self._fit_mode = False

    def zoom_to(self, factor: float):
        self.resetTransform()
        self.scale(factor, factor)
        self._current_zoom = factor
        self._fit_mode = False

    def wheelEvent(self, event: QWheelEvent):
        delta = event.angleDelta().y()
        if not delta:
            event.accept()
            return

        # 좌클릭 누른 상태 → 줌
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.wheel_zoom.emit(1 if delta > 0 else -1)
        else:
            # 일반 휠 → 페이지 네비게이션
            self.wheel_navigate.emit(-1 if delta > 0 else 1)
        event.accept()

    def mousePressEvent(self, event: QMouseEvent):
        btn = event.button()

        if btn == Qt.MouseButton.RightButton:
            self.context_menu_requested.emit(event.globalPosition())
            event.accept()
            return

        # 바인딩 가능한 버튼: Left 이외의 모든 버튼
        if btn != Qt.MouseButton.LeftButton:
            input_id = _input_id_from_mouse(btn)
            self.mouse_button_pressed.emit(input_id)
            event.accept()
            return

        self._is_panning = True
        self._pan_start = event.position()
        self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        h = self.height()
        if h > 0:
            self.mouse_moved.emit(
                event.position().x() / max(self.width(), 1),
                event.position().y() / h
            )
        if self._is_panning:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta.x())
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta.y())
            )
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self._is_panning:
            self._is_panning = False
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._fit_mode:
            self.fit_in_view_proper()


# ================================================================
# 메인 뷰어
# ================================================================

class NAIAImageViewer(QWidget):
    closed = pyqtSignal()

    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self._image_list: List[Path] = []
        self._current_index: int = -1
        self._slider_updating = False
        self._current_folder: Optional[Path] = None
        self._folder_mtime: float = 0.0
        self._edge_pending: Optional[str] = None  # "first" | "last" | None

        # 오버레이 고정
        self._top_pinned = False
        self._bottom_pinned = False

        # 바인딩: [{input_id: str, action: str}, ...]
        self._bindings: List[Dict] = []
        self._dest_path: str = ""  # 빈 문자열 = 기본값
        self._use_session_folder: bool = True
        self._load_bindings()

        # 캐시
        self._cache = PixmapCache()
        self._cache_worker = _PixmapCacheWorker(self)
        self._cache_worker.loaded.connect(self._on_cache_loaded)

        # 숨김 타이머
        self._top_hide_timer = QTimer(self)
        self._top_hide_timer.setSingleShot(True)
        self._top_hide_timer.setInterval(_HIDE_DELAY_MS)
        self._top_hide_timer.timeout.connect(lambda: self._auto_hide(self._top_bar, self._top_pinned))

        self._bottom_hide_timer = QTimer(self)
        self._bottom_hide_timer.setSingleShot(True)
        self._bottom_hide_timer.setInterval(_HIDE_DELAY_MS)
        self._bottom_hide_timer.timeout.connect(lambda: self._auto_hide(self._bottom_bar, self._bottom_pinned))

        self._init_ui()

        # NAIA 이벤트 구독
        self.app_context.subscribe("image_counter_changed", self._on_naia_image_saved)

    # ================================================================
    # 바인딩 영속화
    # ================================================================

    def _load_bindings(self):
        try:
            if _SETTINGS_PATH.exists():
                with open(_SETTINGS_PATH, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                self._bindings = settings.get("viewer.bindings", [])
                self._dest_path = settings.get("viewer.dest_path", "")
                self._use_session_folder = settings.get("viewer.use_session_folder", True)
        except Exception:
            self._bindings = []

        # 기본 바인딩: Forward → 복사
        if not self._bindings:
            self._bindings = [{"input_id": "mouse:forward", "action": ACTION_COPY}]

    def _save_bindings(self):
        try:
            _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            settings = {}
            if _SETTINGS_PATH.exists():
                try:
                    with open(_SETTINGS_PATH, 'r', encoding='utf-8') as f:
                        settings = json.load(f)
                except (json.JSONDecodeError, ValueError):
                    # 파일 손상 시 기존 설정을 읽지 못하면 바인딩만 기록
                    print("[Viewer] settings file corrupt, writing bindings only")
                    settings = {}
            settings["viewer.bindings"] = self._bindings
            settings["viewer.dest_path"] = self._dest_path
            settings["viewer.use_session_folder"] = self._use_session_folder
            with open(_SETTINGS_PATH, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[Viewer] save bindings failed: {e}")

    def _get_action_for_input(self, input_id: str) -> Optional[str]:
        for b in self._bindings:
            if b.get("input_id") == input_id:
                return b.get("action")
        return None

    # ================================================================
    # UI 구성
    # ================================================================

    def _init_ui(self):
        self.setWindowTitle("NAIA Image Viewer")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setStyleSheet("background-color: #000000;")
        self.setMinimumSize(800, 600)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._scene = QGraphicsScene(self)
        self._pixmap_item = QGraphicsPixmapItem()
        self._pixmap_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self._scene.addItem(self._pixmap_item)

        self._view = ImageViewerGraphicsView(self)
        self._view.setScene(self._scene)
        self._view.mouse_moved.connect(self._on_view_mouse_moved)
        self._view.wheel_navigate.connect(self._on_wheel_navigate)
        self._view.wheel_zoom.connect(self._on_wheel_zoom)
        self._view.mouse_button_pressed.connect(self._on_bound_input)
        self._view.context_menu_requested.connect(self._show_context_menu)
        layout.addWidget(self._view, 1)

        self._top_bar = self._build_top_bar()
        self._top_bar.setVisible(False)
        self._bottom_bar = self._build_bottom_bar()
        self._bottom_bar.setVisible(False)

    def _overlay_btn_style(self) -> str:
        return f"""
            QPushButton {{
                background: transparent;
                color: {DARK_COLORS['text_primary']};
                border: none;
                font-size: {get_scaled_font_size(17)}px;
                padding: {get_scaled_size(4)}px {get_scaled_size(10)}px;
                border-radius: {get_scaled_size(4)}px;
            }}
            QPushButton:hover {{
                background-color: rgba(255, 255, 255, 30);
            }}
            QPushButton:pressed {{
                background-color: rgba(255, 255, 255, 50);
            }}
        """

    def _pin_btn_style(self, pinned: bool) -> str:
        color = DARK_COLORS['accent_blue'] if pinned else DARK_COLORS['text_secondary']
        return f"""
            QPushButton {{
                background: transparent;
                color: {color};
                border: none;
                font-size: {get_scaled_font_size(14)}px;
                padding: {get_scaled_size(2)}px {get_scaled_size(6)}px;
                border-radius: {get_scaled_size(3)}px;
            }}
            QPushButton:hover {{
                background-color: rgba(255, 255, 255, 30);
            }}
        """

    def _make_separator(self) -> QFrame:
        sep = QFrame()
        sep.setFixedSize(1, get_scaled_size(24))
        sep.setStyleSheet("background-color: rgba(255, 255, 255, 40);")
        return sep

    def _build_top_bar(self) -> QFrame:
        bar = QFrame(self)
        bar.setFixedHeight(get_scaled_size(40))
        bar.setStyleSheet("""
            QFrame {
                background-color: rgba(20, 20, 20, 220);
                border-bottom: 1px solid rgba(255, 255, 255, 30);
            }
        """)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(get_scaled_size(16), 0, get_scaled_size(8), 0)
        layout.setSpacing(get_scaled_size(8))

        self._path_label = QLabel("")
        self._path_label.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(14)}px; background: transparent;")
        layout.addWidget(self._path_label)
        layout.addStretch()

        self._index_label = QLabel("")
        self._index_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(14)}px; font-weight: bold; background: transparent;")
        layout.addWidget(self._index_label)
        layout.addStretch()

        self._top_pin_btn = QPushButton("Pin")
        self._top_pin_btn.setStyleSheet(self._pin_btn_style(False))
        self._top_pin_btn.setFixedSize(get_scaled_size(40), get_scaled_size(28))
        self._top_pin_btn.clicked.connect(self._toggle_top_pin)
        layout.addWidget(self._top_pin_btn)
        layout.addWidget(self._make_separator())

        win_btn_style = f"""
            QPushButton {{ background: transparent; color: {DARK_COLORS['text_secondary']}; border: none;
                font-size: {get_scaled_font_size(16)}px; padding: {get_scaled_size(4)}px {get_scaled_size(10)}px; border-radius: {get_scaled_size(3)}px; }}
            QPushButton:hover {{ background-color: rgba(255, 255, 255, 40); color: {DARK_COLORS['text_primary']}; }}
        """
        close_btn_style = f"""
            QPushButton {{ background: transparent; color: {DARK_COLORS['text_secondary']}; border: none;
                font-size: {get_scaled_font_size(16)}px; padding: {get_scaled_size(4)}px {get_scaled_size(10)}px; border-radius: {get_scaled_size(3)}px; }}
            QPushButton:hover {{ background-color: {DARK_COLORS['error']}; color: {DARK_COLORS['text_primary']}; }}
        """
        btn_sz = QSize(get_scaled_size(36), get_scaled_size(28))

        btn_minimize = QPushButton("─")
        btn_minimize.setStyleSheet(win_btn_style)
        btn_minimize.setFixedSize(btn_sz)
        btn_minimize.clicked.connect(self.showMinimized)
        layout.addWidget(btn_minimize)

        self._btn_restore = QPushButton("❐")
        self._btn_restore.setStyleSheet(win_btn_style)
        self._btn_restore.setFixedSize(btn_sz)
        self._btn_restore.clicked.connect(self._toggle_fullscreen)
        layout.addWidget(self._btn_restore)

        btn_close = QPushButton("✕")
        btn_close.setStyleSheet(close_btn_style)
        btn_close.setFixedSize(btn_sz)
        btn_close.clicked.connect(self.close)
        layout.addWidget(btn_close)

        return bar

    def _build_bottom_bar(self) -> QFrame:
        bar = QFrame(self)
        bar.setFixedHeight(get_scaled_size(80))
        bar.setStyleSheet("""
            QFrame {
                background-color: rgba(20, 20, 20, 220);
                border-top: 1px solid rgba(255, 255, 255, 30);
            }
        """)
        outer = QVBoxLayout(bar)
        outer.setContentsMargins(get_scaled_size(20), get_scaled_size(4), get_scaled_size(20), get_scaled_size(6))
        outer.setSpacing(get_scaled_size(2))

        # 슬라이더 행
        slider_row = QHBoxLayout()
        slider_row.setSpacing(get_scaled_size(8))

        self._page_label_left = QLabel("1")
        self._page_label_left.setFixedWidth(get_scaled_size(40))
        self._page_label_left.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._page_label_left.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(12)}px; background: transparent;")
        slider_row.addWidget(self._page_label_left)

        self._page_slider = QSlider(Qt.Orientation.Horizontal)
        self._page_slider.setMinimum(1)
        self._page_slider.setMaximum(1)
        self._page_slider.setValue(1)
        self._page_slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{ background: rgba(255, 255, 255, 30); height: {get_scaled_size(4)}px; border-radius: {get_scaled_size(2)}px; }}
            QSlider::handle:horizontal {{ background: {DARK_COLORS['accent_blue']}; width: {get_scaled_size(14)}px; height: {get_scaled_size(14)}px; margin: -{get_scaled_size(5)}px 0; border-radius: {get_scaled_size(7)}px; }}
            QSlider::handle:horizontal:hover {{ background: {DARK_COLORS['accent_blue_light']}; }}
            QSlider::sub-page:horizontal {{ background: {DARK_COLORS['accent_blue']}; border-radius: {get_scaled_size(2)}px; }}
        """)
        self._page_slider.valueChanged.connect(self._on_slider_changed)
        slider_row.addWidget(self._page_slider, 1)

        self._page_label_right = QLabel("/ 1")
        self._page_label_right.setFixedWidth(get_scaled_size(50))
        self._page_label_right.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._page_label_right.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(12)}px; background: transparent;")
        slider_row.addWidget(self._page_label_right)

        outer.addLayout(slider_row)

        # 버튼 행
        btn_row = QHBoxLayout()
        btn_row.setSpacing(get_scaled_size(6))
        btn_style = self._overlay_btn_style()

        btn_row.addStretch()

        for text, slot in [("◀", self.go_previous)]:
            b = QPushButton(text); b.setStyleSheet(btn_style); b.clicked.connect(slot); btn_row.addWidget(b)

        btn_row.addWidget(self._make_separator())

        self._btn_fit = QPushButton("맞춤")
        self._btn_fit.setStyleSheet(btn_style)
        self._btn_fit.clicked.connect(self._toggle_fit)
        btn_row.addWidget(self._btn_fit)

        btn_row.addWidget(self._make_separator())

        b = QPushButton("−"); b.setStyleSheet(btn_style); b.clicked.connect(lambda: self._zoom_step(-1)); btn_row.addWidget(b)
        self._zoom_label = QLabel("100%")
        self._zoom_label.setFixedWidth(get_scaled_size(56))
        self._zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._zoom_label.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(13)}px; background: transparent;")
        btn_row.addWidget(self._zoom_label)
        b = QPushButton("+"); b.setStyleSheet(btn_style); b.clicked.connect(lambda: self._zoom_step(1)); btn_row.addWidget(b)

        btn_row.addWidget(self._make_separator())

        b = QPushButton("↺"); b.setStyleSheet(btn_style); b.clicked.connect(lambda: self._rotate(-90)); btn_row.addWidget(b)
        b = QPushButton("↻"); b.setStyleSheet(btn_style); b.clicked.connect(lambda: self._rotate(90)); btn_row.addWidget(b)

        btn_row.addWidget(self._make_separator())

        b = QPushButton("▶"); b.setStyleSheet(btn_style); b.clicked.connect(self.go_next); btn_row.addWidget(b)

        btn_row.addWidget(self._make_separator())

        # Pin
        self._bottom_pin_btn = QPushButton("Pin")
        self._bottom_pin_btn.setStyleSheet(self._pin_btn_style(False))
        self._bottom_pin_btn.setFixedSize(get_scaled_size(40), get_scaled_size(28))
        self._bottom_pin_btn.clicked.connect(self._toggle_bottom_pin)
        btn_row.addWidget(self._bottom_pin_btn)

        # 설정
        btn_settings = QPushButton("설정")
        btn_settings.setStyleSheet(self._pin_btn_style(False))
        btn_settings.setFixedSize(get_scaled_size(40), get_scaled_size(28))
        btn_settings.clicked.connect(self._open_bindings_dialog)
        btn_row.addWidget(btn_settings)

        btn_row.addStretch()
        outer.addLayout(btn_row)
        return bar

    # ================================================================
    # 오버레이 표시/숨김
    # ================================================================

    def _position_overlays(self):
        w = self.width()
        self._top_bar.setGeometry(0, 0, w, self._top_bar.height())
        self._top_bar.raise_()
        bh = self._bottom_bar.height()
        self._bottom_bar.setGeometry(0, self.height() - bh, w, bh)
        self._bottom_bar.raise_()

    def _auto_hide(self, overlay: QFrame, pinned: bool):
        if not pinned:
            overlay.setVisible(False)

    def _on_view_mouse_moved(self, x_ratio: float, y_ratio: float):
        view_h = self._view.height()
        if view_h <= 0:
            return
        top_thresh = _EDGE_TRIGGER_PX / view_h
        bottom_thresh = 1.0 - (_EDGE_TRIGGER_PX / view_h)

        if y_ratio < top_thresh:
            self._top_bar.setVisible(True)
            self._top_hide_timer.stop()
        elif self._top_bar.isVisible() and not self._top_pinned:
            self._top_hide_timer.start()

        if y_ratio > bottom_thresh:
            self._bottom_bar.setVisible(True)
            self._bottom_hide_timer.stop()
        elif self._bottom_bar.isVisible() and not self._bottom_pinned:
            self._bottom_hide_timer.start()

    def _toggle_top_pin(self):
        self._top_pinned = not self._top_pinned
        self._top_pin_btn.setStyleSheet(self._pin_btn_style(self._top_pinned))
        if self._top_pinned:
            self._top_hide_timer.stop()
            self._top_bar.setVisible(True)

    def _toggle_bottom_pin(self):
        self._bottom_pinned = not self._bottom_pinned
        self._bottom_pin_btn.setStyleSheet(self._pin_btn_style(self._bottom_pinned))
        if self._bottom_pinned:
            self._bottom_hide_timer.stop()
            self._bottom_bar.setVisible(True)

    # ================================================================
    # 설정 다이얼로그
    # ================================================================

    def _open_bindings_dialog(self):
        """TODO(web-dialog): 원래 ViewerBindingsDialog.exec() — Web Shell 패널로 재구현 필요."""
        print("[Dialog/SKIPPED] ViewerBindingsDialog 차단 — Web Shell 재구현 예정")

    # ================================================================
    # 컨텍스트 메뉴
    # ================================================================

    def _show_context_menu(self, global_pos: QPointF):
        if not self._image_list or self._current_index < 0:
            return

        # 메뉴 열리는 시점의 인덱스/파일을 고정 (클로저 캡처 안전)
        snapshot_index = self._current_index
        snapshot_path = Path(self._image_list[snapshot_index])

        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                padding: {get_scaled_size(6)}px;
                font-size: {get_scaled_font_size(16)}px;
            }}
            QMenu::item {{
                padding: {get_scaled_size(8)}px {get_scaled_size(32)}px;
                border-radius: {get_scaled_size(3)}px;
            }}
            QMenu::item:selected {{
                background-color: {DARK_COLORS['accent_blue']};
            }}
            QMenu::separator {{
                height: 1px;
                background: {DARK_COLORS['border']};
                margin: {get_scaled_size(4)}px {get_scaled_size(8)}px;
            }}
        """)

        act_clip = menu.addAction("클립보드에 복사 (PNG)")
        act_clip.triggered.connect(lambda _, p=snapshot_path: self._copy_to_clipboard(p))

        menu.addSeparator()

        act_copy = menu.addAction("복사")
        act_copy.triggered.connect(lambda _, p=snapshot_path: self._execute_action_on(ACTION_COPY, p))

        act_move = menu.addAction("이동")
        act_move.triggered.connect(lambda _, p=snapshot_path: self._execute_action_on(ACTION_MOVE, p))

        act_delete = menu.addAction("삭제 (휴지통)")
        act_delete.triggered.connect(lambda _, p=snapshot_path: self._execute_action_on(ACTION_DELETE, p))

        menu.addSeparator()

        act_open = menu.addAction("파일 위치 열기")
        act_open.triggered.connect(lambda _, p=snapshot_path: self._open_file_location(p))

        menu.addSeparator()

        act_bindings = menu.addAction("키 바인딩 설정")
        act_bindings.triggered.connect(self._open_bindings_dialog)

        act_close = menu.addAction("창 닫기")
        act_close.triggered.connect(self.close)

        menu.exec(global_pos.toPoint())

    def _copy_to_clipboard(self, file_path: Path):
        """현재 이미지를 클립보드에 PNG로 복사"""
        try:
            if file_path.suffix.lower() == ".png":
                set_png_clipboard_bytes(file_path.read_bytes(), file_path.name)
                self._show_toast(file_path.name, "clipboard copied", "blue")
                return

            pixmap = self._cache.get(str(file_path))
            if pixmap is None:
                pixmap = self._load_pixmap_sync(file_path)
            if pixmap and not pixmap.isNull():
                png_bytes = qimage_to_png_bytes(pixmap.toImage())
                if not png_bytes:
                    raise ValueError("QPixmap could not be encoded as PNG")
                set_png_clipboard_bytes(png_bytes, file_path.name)
                self._show_toast(file_path.name, "clipboard copied", "blue")
            else:
                self._show_toast(file_path.name, "clipboard failed", "red")
        except Exception as e:
            print(f"[Viewer] clipboard copy failed: {e}")
            self._show_toast(file_path.name, "clipboard failed", "red")

    def _open_file_location(self, file_path: Path):
        """파일 탐색기에서 해당 파일 선택하여 열기"""
        import subprocess
        import sys
        try:
            if sys.platform == 'win32':
                subprocess.Popen(['explorer', '/select,', str(file_path)])
            elif sys.platform == 'darwin':
                subprocess.run(['open', '-R', str(file_path)])
            else:
                subprocess.run(['xdg-open', str(file_path.parent)])
        except Exception as e:
            print(f"[Viewer] open file location failed: {e}")

    # ================================================================
    # 액션 디스패치
    # ================================================================

    def _on_bound_input(self, input_id: str):
        """마우스 버튼 바인딩 → 액션 실행"""
        action = self._get_action_for_input(input_id)
        if action:
            self._execute_action(action)

    def _on_bound_key(self, key: int):
        """키보드 바인딩 → 액션 실행"""
        input_id = _input_id_from_key(key)
        action = self._get_action_for_input(input_id)
        if action:
            self._execute_action(action)
            return True
        return False

    def _execute_action(self, action: str):
        """바인딩에서 호출: 현재 인덱스의 파일에 액션 실행"""
        if not self._image_list or self._current_index < 0:
            return
        file_path = self._image_list[self._current_index]
        self._execute_action_on(action, file_path)

    def _execute_action_on(self, action: str, file_path: Path):
        """지정된 파일에 액션 실행 (컨텍스트 메뉴/바인딩 공용)"""
        if not file_path.exists():
            return

        if action == ACTION_COPY:
            self._action_copy(file_path)
        elif action == ACTION_MOVE:
            self._action_move(file_path)
        elif action == ACTION_DELETE:
            self._action_delete(file_path)

    def _get_dest_dir(self, file_path: Path) -> Path:
        """대상 폴더 결정 (설정 기반)"""
        if self._dest_path:
            base = Path(self._dest_path)
        else:
            base = Path.home() / "Pictures" / "꿀뷰" / "NAIA"

        if self._use_session_folder:
            session_name = getattr(self.app_context, 'session_timestamp', None)
            if session_name:
                dest_dir = base / session_name
            else:
                dest_dir = base
        else:
            dest_dir = base

        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            print(f"[Viewer] dest dir create failed: {e}")
            self._show_toast("", f"폴더 생성 실패: {dest_dir}", "red")
            return None
        return dest_dir

    def _action_copy(self, file_path: Path):
        dest_dir = self._get_dest_dir(file_path)
        if dest_dir is None:
            return
        dest_file = dest_dir / file_path.name
        if dest_file.exists():
            self._show_toast(file_path.name, "already saved", "gray")
            return
        try:
            shutil.copy2(str(file_path), str(dest_file))
            self._show_toast(file_path.name, "copied", "blue")
        except Exception as e:
            print(f"[Viewer] copy failed: {e}")
            self._show_toast(file_path.name, "copy failed", "red")

    def _action_move(self, file_path: Path):
        dest_dir = self._get_dest_dir(file_path)
        if dest_dir is None:
            return
        dest_file = dest_dir / file_path.name
        if dest_file.exists():
            self._show_toast(file_path.name, "already exists", "gray")
            return
        try:
            shutil.move(str(file_path), str(dest_file))
            self._cache.remove(str(file_path))
            self._show_toast(file_path.name, "moved", "blue")
            self._remove_file_from_list(file_path)
        except Exception as e:
            print(f"[Viewer] move failed: {e}")
            self._show_toast(file_path.name, "move failed", "red")

    def _action_delete(self, file_path: Path):
        try:
            success = _send_to_recycle_bin(str(file_path))
            if not success:
                self._show_toast(file_path.name, "delete failed", "red")
                return
            self._cache.remove(str(file_path))
            self._show_toast(file_path.name, "deleted", "red")
            self._remove_file_from_list(file_path)
        except Exception as e:
            print(f"[Viewer] delete failed: {e}")
            self._show_toast(file_path.name, "delete failed", "red")

    def _remove_file_from_list(self, file_path: Path):
        """지정된 파일을 목록에서 제거하고 인접 인덱스로 이동"""
        try:
            removed_index = self._image_list.index(file_path)
        except ValueError:
            return  # 이미 없음

        self._image_list.pop(removed_index)

        if not self._image_list:
            self.close()
            return

        # 삭제된 인덱스가 현재 이하이면 인덱스 보정
        if self._current_index >= len(self._image_list):
            self._current_index = len(self._image_list) - 1
        elif self._current_index > removed_index:
            self._current_index -= 1

        self._page_slider.setMaximum(max(len(self._image_list), 1))
        self._display_current()

    # ================================================================
    # 토스트 피드백
    # ================================================================

    _TOAST_COLORS = {
        "blue": "rgba(25, 118, 210, 200)",
        "gray": "rgba(100, 100, 100, 200)",
        "red": "rgba(211, 47, 47, 200)",
    }

    def _show_toast(self, filename: str, status: str, color: str, duration_ms: int = 1200):
        if not hasattr(self, '_toast_label'):
            self._toast_label = QLabel(self)
            self._toast_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._toast_timer = QTimer(self)
            self._toast_timer.setSingleShot(True)
            self._toast_timer.timeout.connect(lambda: self._toast_label.setVisible(False))

        bg = self._TOAST_COLORS.get(color, self._TOAST_COLORS["blue"])
        self._toast_label.setStyleSheet(f"""
            background-color: {bg}; color: white;
            font-size: {get_scaled_font_size(16)}px;
            padding: {get_scaled_size(12)}px {get_scaled_size(24)}px;
            border-radius: {get_scaled_size(8)}px;
        """)
        text = f"{filename}  —  {status}" if filename else status
        self._toast_label.setText(text)
        self._toast_label.adjustSize()
        x = self.width() - self._toast_label.width() - get_scaled_size(24)
        y = get_scaled_size(60)
        self._toast_label.move(x, y)
        self._toast_label.setVisible(True)
        self._toast_label.raise_()
        self._toast_timer.start(duration_ms)

    # ================================================================
    # Public API
    # ================================================================

    def open_viewer(self, start_file: Optional[str] = None):
        folder = self._get_current_folder()
        if not folder or not folder.exists():
            print(f"[Viewer] folder not found: {folder}")
            return
        self._load_images_from_folder(folder)
        if not self._image_list:
            print(f"[Viewer] no images in: {folder}")
            return

        if start_file:
            start_path = Path(start_file)
            for i, p in enumerate(self._image_list):
                if p == start_path or p.name == start_path.name:
                    self._current_index = i
                    break
            else:
                self._current_index = 0
        else:
            self._current_index = len(self._image_list) - 1

        self._page_slider.setMaximum(max(len(self._image_list), 1))
        self._display_current()
        self.showFullScreen()

        # 진입 안내 (첫 진입 시에만)
        if not hasattr(self, '_guide_shown') or not self._guide_shown:
            self._guide_shown = True
            QTimer.singleShot(300, lambda: self._show_toast(
                "", "우클릭 또는 하단 설정 메뉴에서 키 바인딩이 가능합니다.", "gray", 2500
            ))

    def go_next(self):
        if not self._image_list:
            return
        if self._current_index >= len(self._image_list) - 1:
            if self._edge_pending == "last":
                # 두 번째 시도 → 첫 이미지로 순환
                self._edge_pending = None
                self._current_index = 0
                self._display_current()
            else:
                self._edge_pending = "last"
                self._show_toast("", "마지막 이미지입니다.", "gray", 1000)
            return
        self._edge_pending = None
        self._current_index += 1
        self._display_current()

    def go_previous(self):
        if not self._image_list:
            return
        if self._current_index <= 0:
            if self._edge_pending == "first":
                # 두 번째 시도 → 마지막 이미지로 순환
                self._edge_pending = None
                self._current_index = len(self._image_list) - 1
                self._display_current()
            else:
                self._edge_pending = "first"
                self._show_toast("", "첫번째 이미지입니다.", "gray", 1000)
            return
        self._edge_pending = None
        self._current_index -= 1
        self._display_current()

    def go_to_index(self, index: int):
        if 0 <= index < len(self._image_list):
            self._edge_pending = None
            self._current_index = index
            self._display_current()

    # ================================================================
    # Internal
    # ================================================================

    def _get_current_folder(self) -> Optional[Path]:
        if hasattr(self.app_context, 'image_crud_controller'):
            return self.app_context.image_crud_controller.get_save_directory()
        return getattr(self.app_context, 'session_save_path', None)

    def _load_images_from_folder(self, folder: Path):
        self._image_list = []
        self._cache.clear()
        self._current_folder = folder
        try:
            # os.scandir: Windows에서 stat 없이 디렉토리 엔트리에서 mtime 직접 획득
            entries = []
            with os.scandir(folder) as it:
                for entry in it:
                    if entry.is_file(follow_symlinks=False):
                        suffix = os.path.splitext(entry.name)[1].lower()
                        if suffix in IMAGE_EXTENSIONS:
                            entries.append((entry.path, entry.stat(follow_symlinks=False).st_mtime))
            entries.sort(key=lambda x: x[1])
            self._image_list = [Path(p) for p, _ in entries]
            self._folder_mtime = folder.stat().st_mtime
        except Exception as e:
            print(f"[Viewer] folder read error: {e}")

    def _refresh_if_changed(self):
        if not self._current_folder or not self._current_folder.exists():
            return False
        try:
            current_mtime = self._current_folder.stat().st_mtime
        except OSError:
            return False
        if current_mtime == self._folder_mtime:
            return False

        self._folder_mtime = current_mtime
        old_set = {p.name for p in self._image_list}
        old_index = self._current_index
        old_current_name = (
            self._image_list[old_index].name if 0 <= old_index < len(self._image_list) else None
        )
        try:
            entries = []
            with os.scandir(self._current_folder) as it:
                for entry in it:
                    if entry.is_file(follow_symlinks=False):
                        suffix = os.path.splitext(entry.name)[1].lower()
                        if suffix in IMAGE_EXTENSIONS:
                            entries.append((entry.name, entry.path, entry.stat(follow_symlinks=False).st_mtime))
        except OSError:
            return False

        new_set = {name for name, _, _ in entries}
        if new_set == old_set:
            return False

        entries.sort(key=lambda x: x[2])
        self._image_list = [Path(p) for _, p, _ in entries]
        if old_current_name:
            for i, p in enumerate(self._image_list):
                if p.name == old_current_name:
                    self._current_index = i
                    break
            else:
                self._current_index = min(old_index, len(self._image_list) - 1)
                self._current_index = max(0, self._current_index)
        else:
            self._current_index = max(0, len(self._image_list) - 1)

        self._page_slider.setMaximum(max(len(self._image_list), 1))
        self._display_current()
        return True

    def _on_naia_image_saved(self, data: dict):
        if not self.isVisible():
            return
        was_at_last = (self._current_index >= len(self._image_list) - 1)
        changed = self._refresh_if_changed()
        if changed and was_at_last and self._image_list:
            self._current_index = len(self._image_list) - 1
            self._display_current()

    def _display_current(self):
        if not self._image_list or self._current_index < 0:
            return
        file_path = self._image_list[self._current_index]
        key = str(file_path)

        pixmap = self._cache.get(key)
        if pixmap is None:
            pixmap = self._load_pixmap_sync(file_path)
            if pixmap and not pixmap.isNull():
                self._cache.put(key, pixmap)
        if pixmap is None or pixmap.isNull():
            return

        self._pixmap_item.setPixmap(pixmap)
        self._scene.setSceneRect(QRectF(pixmap.rect().toRectF()))
        self._view.fit_in_view_proper()

        folder_name = file_path.parent.name
        total = len(self._image_list)
        cur = self._current_index + 1
        self._path_label.setText(f"{folder_name}  >  {file_path.name}")
        self._index_label.setText(f"[{cur}/{total}]")

        self._slider_updating = True
        self._page_slider.setValue(cur)
        self._slider_updating = False
        self._page_label_left.setText(str(cur))
        self._page_label_right.setText(f"/ {total}")

        self._on_zoom_changed(self._view._current_zoom)
        self.setWindowTitle(f"{file_path.name} [{cur}/{total}] - NAIA Viewer")
        self._schedule_preload()

    def _schedule_preload(self):
        if not self._image_list:
            return
        total = len(self._image_list)
        to_load = []
        for offset in range(-_CACHE_BEHIND, _CACHE_AHEAD + 1):
            if offset == 0:
                continue
            idx = (self._current_index + offset) % total
            p = self._image_list[idx]
            if self._cache.get(str(p)) is None:
                to_load.append(p)
        if to_load:
            self._cache_worker.enqueue(to_load)

    @pyqtSlot(str, QImage)
    def _on_cache_loaded(self, path_str: str, qimage: QImage):
        """GUI 스레드에서 QImage → QPixmap 변환 후 캐시"""
        pixmap = QPixmap.fromImage(qimage)
        if not pixmap.isNull():
            self._cache.put(path_str, pixmap)

    @staticmethod
    def _load_pixmap_sync(file_path: Path) -> Optional[QPixmap]:
        pixmap = QPixmap(str(file_path))
        if not pixmap.isNull():
            return pixmap
        try:
            from PIL import Image
            img = Image.open(str(file_path))
            img = img.convert("RGBA")
            data = img.tobytes("raw", "RGBA")
            qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
            # .copy()로 data 해제 후에도 안전한 독립 QImage 확보
            return QPixmap.fromImage(qimg.copy())
        except Exception:
            return None

    def _on_wheel_zoom(self, direction: int):
        """좌클릭 + 휠 → 줌"""
        self._zoom_step(direction)

    def _on_wheel_navigate(self, direction: int):
        if direction > 0:
            self.go_next()
        else:
            self.go_previous()

    def _on_slider_changed(self, value: int):
        if self._slider_updating:
            return
        self.go_to_index(value - 1)

    def _on_zoom_changed(self, zoom: float):
        self._zoom_label.setText(f"{int(zoom * 100)}%")
        self._btn_fit.setText("맞춤" if self._view._fit_mode else "원본")

    def _toggle_fit(self):
        if self._view._fit_mode:
            self._view.set_original_size()
        else:
            self._view.fit_in_view_proper()
        self._on_zoom_changed(self._view._current_zoom)

    def _zoom_step(self, direction: int):
        factor = 1.25 if direction > 0 else 1 / 1.25
        new_zoom = self._view._current_zoom * factor
        if 0.05 < new_zoom < 50.0:
            self._view.zoom_to(new_zoom)
            self._on_zoom_changed(new_zoom)

    def _rotate(self, angle: int):
        self._view.rotate(angle)

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            # 윈도우 모드: 일반 Windows 프레임 복원
            self.setWindowFlags(Qt.WindowType.Window)

            if hasattr(self, '_saved_windowed_geometry'):
                self.setGeometry(self._saved_windowed_geometry)
            else:
                # 첫 창모드 전환: 화면의 70% 크기로 중앙 배치
                screen = QApplication.primaryScreen()
                if screen:
                    sg = screen.availableGeometry()
                    w = int(sg.width() * 0.7)
                    h = int(sg.height() * 0.7)
                    x = sg.x() + (sg.width() - w) // 2
                    y = sg.y() + (sg.height() - h) // 2
                    self.setGeometry(x, y, w, h)

            self.showNormal()
            self._btn_restore.setText("☐")
        else:
            # 전체화면 전환 전 현재 geometry 저장
            self._saved_windowed_geometry = self.geometry()
            self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
            self.showFullScreen()
            self._btn_restore.setText("❐")

    # ================================================================
    # Events
    # ================================================================

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_overlays()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            self._refresh_if_changed()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_if_changed()

    def keyPressEvent(self, event: QKeyEvent):
        # 바인딩 체크 우선
        if self._on_bound_key(event.key()):
            return

        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.close()
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_Space):
            self.go_next()
        elif key == Qt.Key.Key_Left:
            self.go_previous()
        elif key == Qt.Key.Key_Home:
            self.go_to_index(0)
        elif key == Qt.Key.Key_End:
            self.go_to_index(len(self._image_list) - 1)
        elif key in (Qt.Key.Key_F, Qt.Key.Key_F11):
            self._toggle_fullscreen()
        elif key == Qt.Key.Key_1:
            self._view.set_original_size()
            self._on_zoom_changed(1.0)
        elif key == Qt.Key.Key_0:
            self._view.fit_in_view_proper()
            self._on_zoom_changed(self._view._current_zoom)
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self._cache_worker.stop()
        self._cache.clear()
        self.closed.emit()
        super().closeEvent(event)
