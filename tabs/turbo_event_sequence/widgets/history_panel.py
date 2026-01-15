"""
History Panel Widget

생성된 이미지 시퀀스 히스토리 표시
"""

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QFrame,
    QLabel, QPushButton, QScrollArea, QFileDialog,
    QMessageBox, QCheckBox, QApplication
)
from PyQt6.QtCore import Qt, pyqtSignal, QMimeData, QPoint
from PyQt6.QtGui import QPixmap, QImage, QDrag

from ui.theme import DARK_STYLES, DARK_COLORS
from ui.scaling_manager import get_scaled_font_size, get_scaled_size

from PIL import Image
from PIL.ImageQt import ImageQt
from pathlib import Path
import os
import io
from datetime import datetime


class ThumbnailWidget(QFrame):
    """썸네일 위젯"""

    clicked = pyqtSignal(int, object)  # index, image
    skip_toggled = pyqtSignal(int, bool)  # index, is_skipped
    drag_started = pyqtSignal(int)  # index - 드래그 시작 시그널
    dropped = pyqtSignal(int, int)  # from_index, to_index - 드롭 시그널

    def __init__(self, index: int, image, parent=None, is_placeholder: bool = False):
        super().__init__(parent)
        self.index = index
        self.image = image  # PIL Image
        self._selected = False
        self._is_placeholder = is_placeholder  # 플레이스홀더 여부
        self._is_skipped = False  # Skip 상태
        self._drag_start_pos = None  # 드래그 시작 위치
        self._is_dragging = False  # 드래그 중 여부

        # 드래그 앤 드롭 활성화
        self.setAcceptDrops(True)

        self._init_ui()

    def _init_ui(self):
        """UI 초기화"""
        self.setFixedSize(get_scaled_size(110), get_scaled_size(130))
        if not self._is_placeholder:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_style()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # 썸네일 컨테이너 (이미지 + Skip 버튼 오버레이)
        thumb_container = QWidget()
        thumb_container.setFixedSize(get_scaled_size(102), get_scaled_size(102))

        # 썸네일 이미지
        self.thumb_label = QLabel(thumb_container)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setFixedSize(get_scaled_size(102), get_scaled_size(102))
        self.thumb_label.setStyleSheet(f"background-color: {DARK_COLORS['bg_primary']};")
        self.thumb_label.move(0, 0)

        # Skip 체크박스 (오른쪽 상단 오버레이) - index 0(Parent)이 아닌 경우만
        self.skip_checkbox = QCheckBox(thumb_container)
        self.skip_checkbox.setFixedSize(get_scaled_size(20), get_scaled_size(20))
        self.skip_checkbox.move(get_scaled_size(102) - get_scaled_size(22), get_scaled_size(2))
        self.skip_checkbox.setStyleSheet(f"""
            QCheckBox {{
                background-color: transparent;
            }}
            QCheckBox::indicator {{
                width: {get_scaled_size(16)}px;
                height: {get_scaled_size(16)}px;
            }}
            QCheckBox::indicator:unchecked {{
                border: 2px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(3)}px;
                background-color: #FFFFFF;
            }}
            QCheckBox::indicator:checked {{
                border: 2px solid #F44336;
                border-radius: {get_scaled_size(3)}px;
                background-color: #F44336;
            }}
            QCheckBox::indicator:unchecked:hover {{
                border-color: {DARK_COLORS['accent_blue']};
            }}
            QToolTip {{
                color: white;
                background-color: {DARK_COLORS['bg_tertiary']};
                border: 1px solid {DARK_COLORS['border']};
            }}
        """)
        self.skip_checkbox.setToolTip("Skip (생성/그리드에서 제외)")
        self.skip_checkbox.toggled.connect(self._on_skip_toggled)
        # index 0(Parent)이면 숨김
        if self.index == 0:
            self.skip_checkbox.hide()

        if self.image:
            self._set_thumbnail()
        elif self._is_placeholder:
            # 플레이스홀더 표시
            self.thumb_label.setText("⏳")
            self.thumb_label.setStyleSheet(f"""
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(24)}px;
            """)
            self.skip_checkbox.hide()  # 플레이스홀더에는 숨김

        layout.addWidget(thumb_container)

        # 인덱스 라벨
        self.index_label = QLabel(f"#{self.index}")
        self.index_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.index_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(11) + 3}px;
            color: {DARK_COLORS['text_secondary']};
            background-color: transparent;
        """)
        layout.addWidget(self.index_label)

    def _on_skip_toggled(self, checked: bool):
        """Skip 체크박스 토글"""
        self._is_skipped = checked
        self._update_style()
        self.skip_toggled.emit(self.index, checked)

    def _set_thumbnail(self):
        """썸네일 설정"""
        if self.image is None:
            return

        try:
            # 🔥 이미지 데이터 완전 로드 확보 (lazy loading 방지)
            if hasattr(self.image, 'load'):
                self.image.load()

            # PIL Image를 썸네일로 변환
            thumb = self.image.copy()
            thumb.thumbnail((get_scaled_size(98), get_scaled_size(98)), Image.Resampling.LANCZOS)

            # PNG 버퍼로 저장 후 다시 열기 (WEBP 등 비표준 형식 문제 해결)
            png_buffer = io.BytesIO()
            thumb.save(png_buffer, format='PNG')
            png_buffer.seek(0)
            clean_thumb = Image.open(png_buffer)
            clean_thumb.load()

            if clean_thumb.mode != 'RGBA':
                clean_thumb = clean_thumb.convert('RGBA')

            qimage = ImageQt(clean_thumb)
            pixmap = QPixmap.fromImage(qimage)
            self.thumb_label.setPixmap(pixmap)
            png_buffer.close()
        except Exception as e:
            print(f"[ThumbnailWidget] 썸네일 설정 오류: {e}")

    def _update_style(self):
        """스타일 업데이트"""
        if self._is_placeholder:
            # 플레이스홀더 스타일 (점선 테두리, 어두운 배경)
            self.setStyleSheet(f"""
                QFrame {{
                    background-color: {DARK_COLORS['bg_primary']};
                    border: 2px dashed {DARK_COLORS['border']};
                    border-radius: {get_scaled_size(4)}px;
                }}
            """)
        else:
            border_color = DARK_COLORS['accent_blue'] if self._selected else DARK_COLORS['border']
            self.setStyleSheet(f"""
                QFrame {{
                    background-color: {DARK_COLORS['bg_secondary']};
                    border: 2px solid {border_color};
                    border-radius: {get_scaled_size(4)}px;
                }}
                QFrame:hover {{
                    border-color: {DARK_COLORS['accent_blue']};
                }}
            """)

    def update_image(self, image):
        """이미지 업데이트 (플레이스홀더 → 실제 이미지)"""
        self.image = image
        self._is_placeholder = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._set_thumbnail()
        self._update_style()
        # Skip 체크박스 표시 (index 0은 제외)
        if self.index > 0:
            self.skip_checkbox.show()

    def set_selected(self, selected: bool):
        """선택 상태 설정"""
        self._selected = selected
        self._update_style()

    def mousePressEvent(self, event):
        """클릭 이벤트 (드래그 시작 감지)"""
        if event.button() == Qt.MouseButton.LeftButton:
            # 드래그 시작 위치 저장 (플레이스홀더가 아니고 index > 0인 경우만)
            if not self._is_placeholder and self.index > 0 and self.image is not None:
                self._drag_start_pos = event.pos()
            self.clicked.emit(self.index, self.image)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """마우스 이동 이벤트 (드래그 감지)"""
        if self._drag_start_pos is None:
            return

        # 드래그 시작 조건 확인 (최소 이동 거리)
        if (event.pos() - self._drag_start_pos).manhattanLength() < QApplication.startDragDistance():
            return

        # 드래그 시작
        self._is_dragging = True
        self.drag_started.emit(self.index)

        drag = QDrag(self)
        mime_data = QMimeData()
        mime_data.setText(str(self.index))  # 인덱스를 텍스트로 저장
        drag.setMimeData(mime_data)

        # 드래그 중인 썸네일 미리보기 생성
        if self.thumb_label.pixmap():
            drag.setPixmap(self.thumb_label.pixmap().scaled(
                get_scaled_size(80), get_scaled_size(80),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            ))
            drag.setHotSpot(QPoint(get_scaled_size(40), get_scaled_size(40)))

        # 드래그 실행
        drag.exec(Qt.DropAction.MoveAction)

        # 드래그 종료
        self._drag_start_pos = None
        self._is_dragging = False

    def mouseReleaseEvent(self, event):
        """마우스 릴리즈 이벤트"""
        self._drag_start_pos = None
        self._is_dragging = False
        super().mouseReleaseEvent(event)

    def dragEnterEvent(self, event):
        """드래그 진입 이벤트"""
        if event.mimeData().hasText():
            try:
                from_index = int(event.mimeData().text())
                # 자기 자신이 아니고, 인덱스 0(그리드)이 아닌 경우만 허용
                if from_index != self.index and self.index > 0:
                    event.acceptProposedAction()
                    return
            except ValueError:
                pass
        event.ignore()

    def dragMoveEvent(self, event):
        """드래그 이동 이벤트"""
        if event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        """드롭 이벤트"""
        if event.mimeData().hasText():
            try:
                from_index = int(event.mimeData().text())
                if from_index != self.index and self.index > 0:
                    self.dropped.emit(from_index, self.index)
                    event.acceptProposedAction()
                    return
            except ValueError:
                pass
        event.ignore()


class GridThumbnailWidget(QFrame):
    """그리드 썸네일 위젯 (0번 인덱스용)"""

    clicked = pyqtSignal(int, object)  # index, image

    def __init__(self, index: int, image, parent=None):
        super().__init__(parent)
        self.index = index
        self.image = image  # PIL Image
        self._selected = False

        self._init_ui()

    def _init_ui(self):
        """UI 초기화"""
        self.setFixedSize(get_scaled_size(110), get_scaled_size(130))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_style()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # 썸네일 이미지
        self.thumb_label = QLabel()
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setFixedSize(get_scaled_size(102), get_scaled_size(102))
        self.thumb_label.setStyleSheet(f"background-color: {DARK_COLORS['bg_primary']};")

        if self.image:
            self._set_thumbnail()

        layout.addWidget(self.thumb_label)

        # 그리드 라벨
        grid_label = QLabel("🖼️ Grid")
        grid_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grid_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(11) + 3}px;
            color: {DARK_COLORS['accent_blue']};
            font-weight: bold;
            background-color: transparent;
        """)
        layout.addWidget(grid_label)

    def _set_thumbnail(self):
        """썸네일 설정"""
        if self.image is None:
            return

        try:
            if hasattr(self.image, 'load'):
                self.image.load()

            thumb = self.image.copy()
            thumb.thumbnail((get_scaled_size(98), get_scaled_size(98)), Image.Resampling.LANCZOS)

            png_buffer = io.BytesIO()
            thumb.save(png_buffer, format='PNG')
            png_buffer.seek(0)
            clean_thumb = Image.open(png_buffer)
            clean_thumb.load()

            if clean_thumb.mode != 'RGBA':
                clean_thumb = clean_thumb.convert('RGBA')

            qimage = ImageQt(clean_thumb)
            pixmap = QPixmap.fromImage(qimage)
            self.thumb_label.setPixmap(pixmap)
            png_buffer.close()
        except Exception as e:
            print(f"[GridThumbnailWidget] 썸네일 설정 오류: {e}")

    def _update_style(self):
        """스타일 업데이트"""
        # 🔧 선택 상태에 따라 border 색상 구분 (항상 포커스 문제 수정)
        border_color = DARK_COLORS['accent_blue'] if self._selected else DARK_COLORS['border']
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border: 2px solid {border_color};
                border-radius: {get_scaled_size(4)}px;
            }}
            QFrame:hover {{
                border-color: {DARK_COLORS['accent_blue']};
                background-color: {DARK_COLORS['bg_secondary']};
            }}
        """)

    def set_selected(self, selected: bool):
        """선택 상태 설정"""
        self._selected = selected
        self._update_style()

    def mousePressEvent(self, event):
        """클릭 이벤트"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.index, self.image)
        super().mousePressEvent(event)


class DropIndicator(QFrame):
    """드롭 위치 인디케이터 (흰색 막대)"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(get_scaled_size(4))
        self.setStyleSheet(f"""
            QFrame {{
                background-color: #FFFFFF;
                border-radius: {get_scaled_size(2)}px;
            }}
        """)
        self.hide()


class HistoryPanel(QWidget):
    """히스토리 패널

    인덱스 구조:
    - 0번: 결합된 그리드 이미지 (🖼️ Grid)
    - 1번~: 개별 생성 결과 이미지 (#1, #2, ...)
    """

    # 시그널
    image_selected = pyqtSignal(int, object)  # index, image
    grid_auto_saved = pyqtSignal(str)  # 자동 저장 완료 시 경로 전달
    skip_toggled = pyqtSignal(int, bool)  # 썸네일 Skip 토글 시 (history_index, is_skipped)
    order_changed = pyqtSignal()  # 위젯 순서 변경 시
    clear_and_reconfirm = pyqtSignal()  # 클리어 후 시퀀스 재확정 요청
    request_grid_update = pyqtSignal()  # 🆕 그리드 업데이트 요청 (순서 변경 시)
    inpaint_requested = pyqtSignal(int, object, str, bool, object)  # 🆕 인페인트 요청 (history_index, image, direction, is_parent, prev_image)

    def __init__(self, app_context=None, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.images = []  # 0번: grid, 1번~: 개별 이미지
        self.thumbnails = []
        self.selected_index = -1
        self.grid_image = None  # 그리드 이미지 별도 저장
        self.auto_save_enabled = False  # 자동 저장 상태

        # 위치 매핑: visual_index -> original_index
        # 예: {1: 3, 2: 1, 3: 2} 는 화면상 1번 위치에 원래 3번 이미지가 있음을 의미
        self._position_mapping = {}  # 위치 매핑 (순서 변경 추적)
        self._order_changed = False  # 순서 변경 여부 플래그
        self._dragging_index = None  # 드래그 중인 위젯 인덱스

        self._init_ui()

    def _init_ui(self):
        """UI 초기화"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 메인 프레임
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border-radius: {get_scaled_size(4)}px;
            }}
        """)

        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(8, 6, 8, 6)
        frame_layout.setSpacing(4)

        # 헤더
        header_layout = QHBoxLayout()

        title = QLabel("📷 생성 히스토리")
        title.setStyleSheet(f"""
            font-size: {get_scaled_font_size(14) + 3}px;
            font-weight: bold;
            color: {DARK_COLORS['text_primary']};
        """)
        header_layout.addWidget(title)

        self.count_label = QLabel("0개")
        self.count_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(13) + 3}px;
            color: {DARK_COLORS['text_secondary']};
        """)
        header_layout.addWidget(self.count_label)

        header_layout.addStretch()

        # 버튼들
        # 그리드 자동 저장 체크박스
        self.auto_save_checkbox = QCheckBox("그리드 자동 저장")
        self.auto_save_checkbox.setStyleSheet(f"""
            QCheckBox {{
                font-size: {get_scaled_font_size(12) + 6}px;
                color: {DARK_COLORS['text_primary']};
                spacing: {get_scaled_size(4)}px;
            }}
            QCheckBox::indicator {{
                width: {get_scaled_size(17)}px;
                height: {get_scaled_size(17)}px;
            }}
            QCheckBox::indicator:unchecked {{
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(3)}px;
                background-color: {DARK_COLORS['bg_tertiary']};
            }}
            QCheckBox::indicator:checked {{
                border: 1px solid {DARK_COLORS['accent_blue']};
                border-radius: {get_scaled_size(3)}px;
                background-color: {DARK_COLORS['accent_blue']};
            }}
        """)
        self.auto_save_checkbox.toggled.connect(self._on_auto_save_toggled)
        header_layout.addWidget(self.auto_save_checkbox)

        # 컴팩트 버튼 스타일
        compact_button_style = f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(4)}px {get_scaled_size(8)}px;
                font-size: {get_scaled_font_size(12) + 6}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
                border-color: {DARK_COLORS['accent_blue']};
            }}
            QPushButton:pressed {{
                background-color: {DARK_COLORS['bg_primary']};
            }}
            QPushButton:disabled {{
                color: {DARK_COLORS['text_secondary']};
                background-color: {DARK_COLORS['bg_primary']};
            }}
        """

        # 저장 버튼
        self.save_grid_btn = QPushButton("💾")
        self.save_grid_btn.setStyleSheet(compact_button_style)
        self.save_grid_btn.setToolTip("그리드 저장")
        self.save_grid_btn.clicked.connect(self._on_save_grid_clicked)
        self.save_grid_btn.setEnabled(False)
        header_layout.addWidget(self.save_grid_btn)

        # 클립보드 버튼
        self.clipboard_btn = QPushButton("📋")
        self.clipboard_btn.setStyleSheet(compact_button_style)
        self.clipboard_btn.setToolTip("클립보드에 복사")
        self.clipboard_btn.clicked.connect(self._on_clipboard_clicked)
        self.clipboard_btn.setEnabled(False)
        header_layout.addWidget(self.clipboard_btn)

        # 🆕 인페인트 버튼
        self.inpaint_btn = QPushButton("🎨")
        self.inpaint_btn.setStyleSheet(compact_button_style)
        self.inpaint_btn.setToolTip("인페인트 (선택 이미지 수정)")
        self.inpaint_btn.clicked.connect(self._on_inpaint_clicked)
        self.inpaint_btn.setEnabled(False)
        header_layout.addWidget(self.inpaint_btn)

        # 버튼 스타일 (3px 더 큰 폰트)
        button_style = f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(6)}px {get_scaled_size(12)}px;
                font-size: {get_scaled_font_size(12) + 6}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
                border-color: {DARK_COLORS['accent_blue']};
            }}
            QPushButton:pressed {{
                background-color: {DARK_COLORS['bg_primary']};
            }}
            QPushButton:disabled {{
                color: {DARK_COLORS['text_secondary']};
                background-color: {DARK_COLORS['bg_primary']};
            }}
        """

        # 그리드 열기 버튼
        self.open_grid_btn = QPushButton("🖼️ 그리드 열기")
        self.open_grid_btn.setStyleSheet(button_style)
        self.open_grid_btn.clicked.connect(self._on_open_grid_clicked)
        self.open_grid_btn.setEnabled(False)
        header_layout.addWidget(self.open_grid_btn)

        self.clear_btn = QPushButton("🗑️ 클리어")
        self.clear_btn.setStyleSheet(button_style)
        self.clear_btn.clicked.connect(self._on_clear_clicked)
        header_layout.addWidget(self.clear_btn)

        frame_layout.addLayout(header_layout)

        # 썸네일 스크롤 영역
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFixedHeight(get_scaled_size(145))
        scroll.setStyleSheet(f"""
            QScrollArea {{
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                background-color: {DARK_COLORS['bg_primary']};
            }}
            QScrollBar:horizontal {{
                background-color: {DARK_COLORS['bg_primary']};
                height: 10px;
                border-radius: 5px;
            }}
            QScrollBar::handle:horizontal {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border-radius: 5px;
                min-width: 20px;
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0px;
            }}
        """)

        self.thumb_container = QWidget()
        self.thumb_container.setStyleSheet(f"background-color: {DARK_COLORS['bg_primary']};")
        self.thumb_container.setAcceptDrops(True)  # 드롭 활성화
        self.thumb_layout = QHBoxLayout(self.thumb_container)
        self.thumb_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.thumb_layout.setContentsMargins(4, 4, 4, 4)
        self.thumb_layout.setSpacing(4)

        # 드롭 인디케이터 (흰색 막대)
        self.drop_indicator = DropIndicator(self.thumb_container)
        self.drop_indicator.setFixedHeight(get_scaled_size(120))

        # 플레이스홀더
        self.placeholder = QLabel("시퀀스 생성 후 이미지가 여기에 표시됩니다")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setStyleSheet(f"""
            color: {DARK_COLORS['text_secondary']};
            font-size: {get_scaled_font_size(13) + 3}px;
            background-color: {DARK_COLORS['bg_primary']};
        """)
        self.thumb_layout.addWidget(self.placeholder)

        scroll.setWidget(self.thumb_container)
        self.scroll_area = scroll  # 참조 저장
        frame_layout.addWidget(scroll)

        # 🆕 순서 변경 경고 라벨 (하단, 숨김 상태로 시작)
        self.order_warning_label = QLabel("* 위치 변경 후에는 클리어/새 이벤트 전까지 재생성을 할 수 없습니다.")
        self.order_warning_label.setStyleSheet(f"""
            color: #FF9800;
            font-size: {get_scaled_font_size(11) + 3}px;
            padding: {get_scaled_size(2)}px {get_scaled_size(4)}px;
        """)
        self.order_warning_label.hide()
        frame_layout.addWidget(self.order_warning_label)

        # 컨테이너 드래그 앤 드롭 이벤트 오버라이드
        self.thumb_container.dragEnterEvent = self._container_drag_enter
        self.thumb_container.dragMoveEvent = self._container_drag_move
        self.thumb_container.dragLeaveEvent = self._container_drag_leave
        self.thumb_container.dropEvent = self._container_drop

        layout.addWidget(frame)

    def prepare_placeholders(self, count: int):
        """플레이스홀더 위젯 미리 생성 (고정 위치 보장)

        Args:
            count: 생성할 이미지 개수 (그리드 제외)
        """
        # 기존 위젯 정리
        self.clear()

        # 플레이스홀더 제거
        if self.placeholder.isVisible():
            self.placeholder.hide()

        # 0번은 그리드용, 1~count는 개별 이미지용
        total_slots = count + 1

        # 이미지 및 썸네일 리스트 초기화
        self.images = [None] * total_slots
        self.thumbnails = [None] * total_slots

        # 0번: 그리드 플레이스홀더 (GridThumbnailWidget 대신 ThumbnailWidget 사용)
        grid_placeholder = GridThumbnailWidget(0, None)
        grid_placeholder.thumb_label.setText("🖼️")
        grid_placeholder.thumb_label.setStyleSheet(f"""
            background-color: {DARK_COLORS['bg_primary']};
            color: {DARK_COLORS['text_secondary']};
            font-size: {get_scaled_font_size(24)}px;
        """)
        grid_placeholder.clicked.connect(self._on_thumbnail_clicked)
        self.thumbnails[0] = grid_placeholder
        self.thumb_layout.addWidget(grid_placeholder)

        # 1~count: 개별 이미지 플레이스홀더
        for i in range(1, total_slots):
            placeholder_widget = ThumbnailWidget(i, None, is_placeholder=True)
            self._connect_thumbnail_signals(placeholder_widget)
            self.thumbnails[i] = placeholder_widget
            self.thumb_layout.addWidget(placeholder_widget)

        # 순서 변경 플래그 초기화
        self._order_changed = False

        print(f"[HistoryPanel] 플레이스홀더 {total_slots}개 생성 (그리드 + {count}개)")

    def add_image(self, original_index: int, image):
        """이미지 추가 (고정 위치 방식)

        Args:
            original_index: 원본 생성 인덱스 (0부터 시작)
            image: PIL Image

        Note:
            히스토리에서는 1번부터 저장됨 (0번은 그리드용)
            original_index 0 → 히스토리 index 1
        """
        # 히스토리 인덱스는 원본+1 (0번은 그리드용)
        history_index = original_index + 1

        # 플레이스홀더 제거 (기본 플레이스홀더)
        if self.placeholder.isVisible():
            self.placeholder.hide()

        # 이미지 리스트 확장 (플레이스홀더 미생성 시)
        while len(self.images) <= history_index:
            self.images.append(None)
        self.images[history_index] = image

        # 썸네일 리스트 확장 (플레이스홀더 미생성 시)
        while len(self.thumbnails) <= history_index:
            self.thumbnails.append(None)

        # 기존 위젯이 있으면 이미지만 업데이트 (고정 위치 유지)
        if self.thumbnails[history_index]:
            existing_widget = self.thumbnails[history_index]
            if isinstance(existing_widget, ThumbnailWidget):
                existing_widget.update_image(image)
                print(f"[HistoryPanel] #{history_index} 이미지 업데이트 (고정 위치)")
            else:
                # 그리드 위젯이면 새로 생성
                self._replace_thumbnail(history_index, image)
        else:
            # 새 위젯 생성 및 추가 (플레이스홀더 없이 직접 추가된 경우)
            thumb_widget = ThumbnailWidget(history_index, image)
            self._connect_thumbnail_signals(thumb_widget)
            self.thumbnails[history_index] = thumb_widget
            self.thumb_layout.addWidget(thumb_widget)
            print(f"[HistoryPanel] #{history_index} 새 위젯 생성")

        # 카운트 업데이트 (그리드 제외, 실제 이미지만)
        valid_count = sum(1 for i, img in enumerate(self.images) if img is not None and i > 0)
        self.count_label.setText(f"{valid_count}개")
        self._update_grid_buttons_state()

    def _replace_thumbnail(self, index: int, image):
        """썸네일 위젯 교체"""
        if self.thumbnails[index]:
            old_widget = self.thumbnails[index]
            # 레이아웃에서 위치 찾기
            layout_index = self.thumb_layout.indexOf(old_widget)
            self.thumb_layout.removeWidget(old_widget)
            old_widget.deleteLater()

            # 새 위젯 생성
            thumb_widget = ThumbnailWidget(index, image)
            self._connect_thumbnail_signals(thumb_widget)
            self.thumbnails[index] = thumb_widget

            # 같은 위치에 삽입
            if layout_index >= 0:
                self.thumb_layout.insertWidget(layout_index, thumb_widget)
            else:
                self.thumb_layout.addWidget(thumb_widget)

    def update_grid_image(self, grid_image, trigger_auto_save: bool = False):
        """그리드 이미지 업데이트 (0번 인덱스, 고정 위치 방식)

        Args:
            grid_image: 결합된 PIL Image
            trigger_auto_save: 자동 저장 트리거 여부 (시퀀스 완료 시에만 True)
        """
        self.grid_image = grid_image

        # 플레이스홀더 제거
        if self.placeholder.isVisible():
            self.placeholder.hide()

        # 0번에 그리드 이미지 저장
        if len(self.images) == 0:
            self.images.append(grid_image)
        else:
            self.images[0] = grid_image

        # 썸네일 리스트 초기화
        while len(self.thumbnails) == 0:
            self.thumbnails.append(None)

        # 기존 위젯이 있으면 교체 (위치 유지)
        if self.thumbnails[0]:
            old_widget = self.thumbnails[0]
            layout_index = self.thumb_layout.indexOf(old_widget)
            self.thumb_layout.removeWidget(old_widget)
            old_widget.deleteLater()

            # 새 그리드 위젯 생성
            grid_thumb = GridThumbnailWidget(0, grid_image)
            grid_thumb.clicked.connect(self._on_thumbnail_clicked)
            self.thumbnails[0] = grid_thumb

            # 같은 위치에 삽입 (항상 0번)
            self.thumb_layout.insertWidget(max(0, layout_index), grid_thumb)
            print(f"[HistoryPanel] 그리드 이미지 업데이트 (고정 위치 0)")
        else:
            # 새 그리드 위젯 생성 및 추가
            grid_thumb = GridThumbnailWidget(0, grid_image)
            grid_thumb.clicked.connect(self._on_thumbnail_clicked)
            self.thumbnails[0] = grid_thumb
            self.thumb_layout.insertWidget(0, grid_thumb)

        # 버튼 상태 업데이트
        self._update_grid_buttons_state()

        # 자동 저장 활성화 시 저장 (시퀀스 완료 시에만)
        if trigger_auto_save and self.auto_save_enabled and grid_image:
            self._auto_save_grid(grid_image)

    def get_grid_image(self):
        """그리드 이미지 반환"""
        return self.grid_image

    def clear(self):
        """히스토리 클리어"""
        self.images = []
        self.thumbnails = []
        self.selected_index = -1
        self.grid_image = None  # 그리드 이미지도 초기화
        self._order_changed = False  # 순서 변경 플래그 초기화
        self._dragging_index = None  # 드래그 상태 초기화

        # 썸네일 위젯 제거
        while self.thumb_layout.count():
            item = self.thumb_layout.takeAt(0)
            if item.widget() and item.widget() != self.placeholder:
                item.widget().deleteLater()

        # 플레이스홀더 재표시
        self.placeholder.show()
        self.thumb_layout.addWidget(self.placeholder)

        # 🆕 경고 라벨 숨기기
        self.order_warning_label.hide()

        # UI 업데이트
        self.count_label.setText("0개")
        self._update_grid_buttons_state()

    def _update_grid_buttons_state(self):
        """그리드 관련 버튼 활성화 상태 업데이트"""
        has_grid = self.grid_image is not None
        self.save_grid_btn.setEnabled(has_grid)
        self.clipboard_btn.setEnabled(has_grid)
        self.open_grid_btn.setEnabled(has_grid)

    def _on_thumbnail_clicked(self, index: int, image):
        """썸네일 클릭"""
        # 선택 상태 업데이트
        for i, thumb in enumerate(self.thumbnails):
            if thumb:
                thumb.set_selected(i == index)

        self.selected_index = index

        # 🐛 수정: 썸네일 위젯의 image 대신 히스토리 패널의 images 리스트에서 가져옴
        # (인페인트 등으로 이미지가 교체된 경우 최신 이미지 반영)
        actual_image = self.images[index] if index < len(self.images) else image
        self.image_selected.emit(index, actual_image)

        # 🆕 인페인트 버튼 활성화 (index 0은 Grid이므로 제외, index 1 이상만)
        self.inpaint_btn.setEnabled(index >= 1 and actual_image is not None)

    def _on_skip_toggled(self, index: int, is_skipped: bool):
        """썸네일 Skip 토글 (시그널 전달)"""
        # history_index를 그대로 전달 (1부터 시작, sequence_edit_widget에서 변환)
        self.skip_toggled.emit(index, is_skipped)

    def _on_auto_save_toggled(self, checked: bool):
        """자동 저장 토글"""
        self.auto_save_enabled = checked
        print(f"🖼️ 그리드 자동 저장: {'활성화' if checked else '비활성화'}")

    def _on_save_grid_clicked(self):
        """그리드 저장 버튼 클릭 - 기본 경로에 저장"""
        if self.grid_image:
            try:
                file_path = self._save_grid_to_default_path(self.grid_image)
                if file_path:
                    print(f"💾 그리드 저장 완료: {file_path}")
            except Exception as e:
                print(f"❌ 그리드 저장 오류: {e}")

    def _on_clipboard_clicked(self):
        """클립보드 복사 버튼 클릭"""
        if self.grid_image:
            try:
                from PyQt6.QtWidgets import QApplication
                from PyQt6.QtGui import QImage

                # PIL Image → bytes → QImage (더 안전한 방식)
                img = self.grid_image
                if img.mode != 'RGB':
                    img = img.convert('RGB')

                # 이미지 데이터를 바이트로 변환
                data = img.tobytes('raw', 'RGB')
                qimage = QImage(data, img.width, img.height, img.width * 3, QImage.Format.Format_RGB888)

                # QImage 복사본 생성 (원본 데이터 참조 문제 방지)
                qimage_copy = qimage.copy()

                QApplication.clipboard().setImage(qimage_copy)
                print("📋 그리드가 클립보드에 복사되었습니다")
            except Exception as e:
                print(f"❌ 클립보드 복사 오류: {e}")
                import traceback
                traceback.print_exc()

    def _on_open_grid_clicked(self):
        """그리드 열기 - 저장 후 파일 열기"""
        if self.grid_image:
            try:
                # 먼저 저장
                file_path = self._save_grid_to_default_path(self.grid_image)
                if file_path:
                    # 저장된 파일 열기
                    import subprocess
                    import sys
                    if sys.platform == 'win32':
                        os.startfile(str(file_path))
                    elif sys.platform == 'darwin':  # macOS
                        subprocess.call(['open', str(file_path)])
                    else:  # Linux
                        subprocess.call(['xdg-open', str(file_path)])
                    print(f"🖼️ 그리드 열기: {file_path}")
            except Exception as e:
                print(f"❌ 그리드 열기 오류: {e}")

    def _save_grid_to_default_path(self, grid_image) -> Path:
        """그리드 이미지를 기본 경로에 저장

        Args:
            grid_image: PIL Image

        Returns:
            저장된 파일 경로 (Path) 또는 None
        """
        try:
            # 저장 경로 결정
            if self.app_context and hasattr(self.app_context, 'image_crud_controller'):
                base_dir = self.app_context.image_crud_controller.get_save_directory()
            else:
                base_dir = Path("output")

            # /grid 하위 폴더 생성
            grid_dir = base_dir / "grid"
            grid_dir.mkdir(parents=True, exist_ok=True)

            # 파일명 생성 (타임스탬프)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"sequence_grid_{timestamp}.webp"
            file_path = grid_dir / filename

            # WEBP로 저장
            grid_image.save(str(file_path), format='WEBP', quality=95, method=6)
            return file_path

        except Exception as e:
            print(f"❌ 그리드 저장 오류: {e}")
            return None

    def _auto_save_grid(self, grid_image):
        """그리드 이미지 자동 저장 (WEBP 형식, /grid 폴더)

        Args:
            grid_image: PIL Image
        """
        file_path = self._save_grid_to_default_path(grid_image)
        if file_path:
            print(f"✅ 그리드 자동 저장: {file_path}")
            # 시그널 발생
            self.grid_auto_saved.emit(str(file_path))

    def _create_grid_image(self, images: list) -> Image.Image:
        """그리드 이미지 생성"""
        if not images:
            return None

        # 이미지 크기 (첫 번째 이미지 기준)
        img_w, img_h = images[0].size
        count = len(images)

        # 가로 배치 (한 줄)
        cols = count
        rows = 1

        # 그리드 생성
        grid_w = img_w * cols
        grid_h = img_h * rows

        # 다크 배경으로 변경
        grid = Image.new('RGB', (grid_w, grid_h), (30, 30, 30))

        for i, img in enumerate(images):
            x = (i % cols) * img_w
            y = (i // cols) * img_h

            # 크기 맞추기
            if img.size != (img_w, img_h):
                img = img.resize((img_w, img_h), Image.Resampling.LANCZOS)

            grid.paste(img, (x, y))

        return grid

    def _on_clear_clicked(self):
        """클리어 버튼 클릭 - 클리어 후 시퀀스 재확정 요청"""
        if self.images:
            reply = QMessageBox.question(
                self,
                "히스토리 클리어",
                "모든 생성된 이미지를 삭제하고 시퀀스를 재확정하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.Yes:
                self.clear()
                # 🆕 시퀀스 재확정 요청 시그널 발생
                self.clear_and_reconfirm.emit()

    def get_images(self) -> list:
        """모든 이미지 반환"""
        return [img for img in self.images if img is not None]

    def get_count(self) -> int:
        """유효한 이미지 수 반환"""
        return sum(1 for img in self.images if img is not None)

    # ===== 순서 관련 메서드 =====

    def get_ordered_images(self) -> list:
        """순서대로 이미지 반환 (그리드 및 Skip 제외)"""
        ordered = []
        for i in range(1, len(self.thumbnails)):
            if i < len(self.images) and self.images[i] is not None:
                # Skip 상태 확인
                if i < len(self.thumbnails) and self.thumbnails[i] is not None:
                    thumb = self.thumbnails[i]
                    if hasattr(thumb, '_is_skipped') and thumb._is_skipped:
                        continue  # Skip된 이미지 제외
                ordered.append(self.images[i])
        return ordered

    # ===== 드래그 앤 드롭 관련 메서드 =====

    def _container_drag_enter(self, event):
        """컨테이너 드래그 진입"""
        if event.mimeData().hasText():
            try:
                from_index = int(event.mimeData().text())
                if from_index > 0:  # 그리드(0번)가 아닌 경우
                    self._dragging_index = from_index
                    event.acceptProposedAction()
                    return
            except ValueError:
                pass
        event.ignore()

    def _container_drag_move(self, event):
        """컨테이너 드래그 이동 - 드롭 인디케이터 표시"""
        if event.mimeData().hasText():
            try:
                from_index = int(event.mimeData().text())
                if from_index > 0:
                    # 드롭 위치 계산
                    drop_pos = event.position().toPoint()
                    target_index = self._get_drop_target_index(drop_pos)

                    if target_index is not None and target_index > 0:
                        self._show_drop_indicator(target_index)
                    else:
                        self.drop_indicator.hide()

                    event.acceptProposedAction()
                    return
            except ValueError:
                pass
        self.drop_indicator.hide()
        event.ignore()

    def _container_drag_leave(self, event):
        """컨테이너 드래그 나감"""
        self.drop_indicator.hide()
        self._dragging_index = None

    def _container_drop(self, event):
        """컨테이너 드롭 처리"""
        self.drop_indicator.hide()

        if event.mimeData().hasText():
            try:
                from_index = int(event.mimeData().text())
                if from_index > 0:
                    drop_pos = event.position().toPoint()
                    target_index = self._get_drop_target_index(drop_pos)

                    if target_index is not None and target_index > 0 and from_index != target_index:
                        self._reorder_widgets(from_index, target_index)
                        event.acceptProposedAction()
                        return
            except ValueError:
                pass
        event.ignore()

    def _get_drop_target_index(self, pos: QPoint) -> int:
        """드롭 위치에 해당하는 타겟 인덱스 계산"""
        # 썸네일 위젯들의 위치를 기반으로 타겟 인덱스 결정
        for i, thumb in enumerate(self.thumbnails):
            if thumb is None or i == 0:  # 그리드(0번) 제외
                continue

            widget_pos = thumb.pos()
            widget_width = thumb.width()
            widget_center = widget_pos.x() + widget_width // 2

            # 마우스 위치가 위젯의 왼쪽 절반에 있으면 해당 위치 앞에 삽입
            if pos.x() < widget_center:
                return i

        # 모든 위젯보다 오른쪽에 있으면 마지막 위치
        return len(self.thumbnails) - 1 if self.thumbnails else 1

    def _show_drop_indicator(self, target_index: int):
        """드롭 인디케이터 표시"""
        if target_index <= 0 or target_index >= len(self.thumbnails):
            self.drop_indicator.hide()
            return

        target_widget = self.thumbnails[target_index]
        if target_widget is None:
            self.drop_indicator.hide()
            return

        # 타겟 위젯의 왼쪽에 인디케이터 표시
        indicator_x = target_widget.pos().x() - get_scaled_size(4)
        indicator_y = target_widget.pos().y()

        self.drop_indicator.move(indicator_x, indicator_y)
        self.drop_indicator.raise_()
        self.drop_indicator.show()

    def _reorder_widgets(self, from_index: int, to_index: int):
        """위젯 순서 변경

        Args:
            from_index: 이동할 위젯의 현재 인덱스
            to_index: 이동할 목표 인덱스
        """
        if from_index == to_index or from_index <= 0 or to_index <= 0:
            return

        print(f"🔄 위젯 순서 변경: #{from_index} → #{to_index}")

        # 이동할 위젯
        widget = self.thumbnails[from_index]
        if widget is None:
            return

        # 레이아웃에서 위젯 제거
        self.thumb_layout.removeWidget(widget)

        # 삽입 위치 계산:
        # - to_index는 드롭 시점의 "이 위치 앞에 삽입" 의미
        # - from < to: pop하면 to 이후 인덱스가 1씩 감소하므로 to-1에 삽입
        # - from > to: pop해도 to에 영향 없으므로 to에 삽입
        insert_pos = to_index - 1 if from_index < to_index else to_index

        # 레이아웃 삽입
        self.thumb_layout.insertWidget(insert_pos, widget)

        # 썸네일 리스트 재정렬
        thumb = self.thumbnails.pop(from_index)
        self.thumbnails.insert(insert_pos, thumb)

        # 이미지 리스트 재정렬
        if from_index < len(self.images) and self.images[from_index] is not None:
            img = self.images.pop(from_index)
            self.images.insert(insert_pos, img)

        # 인덱스 라벨 업데이트
        self._update_index_labels()

        # 위치 매핑 업데이트
        self._update_position_mapping()

        # 순서 변경 플래그 설정
        self._order_changed = True

        # 🆕 경고 라벨 표시
        self.order_warning_label.show()

        # 시그널 발생
        self.order_changed.emit()

        # 🆕 그리드 업데이트 요청
        self.request_grid_update.emit()

        print(f"✅ 순서 변경 완료. 순서 변경됨: {self._order_changed}")

    def _update_index_labels(self):
        """모든 썸네일의 인덱스 라벨 업데이트"""
        for i, thumb in enumerate(self.thumbnails):
            if thumb is None or i == 0:  # 그리드(0번) 제외
                continue

            if isinstance(thumb, ThumbnailWidget):
                thumb.index = i
                if hasattr(thumb, 'index_label'):
                    thumb.index_label.setText(f"#{i}")

    def _update_position_mapping(self):
        """위치 매핑 업데이트 (원래 인덱스 추적)

        이 매핑은 재생성 시 원본 데이터와의 매칭에 사용됩니다.
        """
        # 현재는 순서 변경 여부만 추적
        # 필요시 원본 인덱스 매핑 추가 가능
        pass

    def is_order_changed(self) -> bool:
        """순서 변경 여부 반환"""
        return self._order_changed

    def reset_order_changed(self):
        """순서 변경 플래그 초기화"""
        self._order_changed = False

    def _connect_thumbnail_signals(self, thumb_widget: ThumbnailWidget):
        """썸네일 위젯 시그널 연결"""
        thumb_widget.clicked.connect(self._on_thumbnail_clicked)
        thumb_widget.skip_toggled.connect(self._on_skip_toggled)
        thumb_widget.drag_started.connect(self._on_drag_started)
        thumb_widget.dropped.connect(self._on_widget_dropped)

    def _on_drag_started(self, index: int):
        """드래그 시작 이벤트"""
        self._dragging_index = index
        print(f"🎯 드래그 시작: #{index}")

    def _on_widget_dropped(self, from_index: int, to_index: int):
        """위젯 드롭 이벤트"""
        self._reorder_widgets(from_index, to_index)

    def _on_inpaint_clicked(self):
        """🆕 인페인트 버튼 클릭 - 시그널 발행"""
        if self.selected_index < 1 or self.selected_index >= len(self.images):
            return

        image = self.images[self.selected_index]
        if image is None:
            return

        # Parent 여부 결정 (index 1 = Parent)
        is_parent = (self.selected_index == 1)

        # 방향 결정 (이미지 크기로 추론)
        w, h = image.size
        if is_parent:
            # Parent: 1152x832 (horizontal) 또는 832x1152 (vertical)
            direction = 'horizontal' if w > h else 'vertical'
        else:
            # Child: 832x608 (horizontal) 또는 608x832 (vertical)
            direction = 'horizontal' if w > h else 'vertical'

        # 🐛 수정: 이전 이미지 가져오기 - 항상 Parent(index 1) 이미지 사용
        # (Child 인페인트 시 캔버스 상단/좌측에 배치할 참조 이미지)
        prev_image = None
        if not is_parent and len(self.images) > 1 and self.images[1]:
            prev_image = self.images[1]  # 항상 Parent(index 1) 사용

        # 🆕 시그널 발행 (TurboEventSequenceTab에서 다이얼로그 열기)
        self.inpaint_requested.emit(self.selected_index, image, direction, is_parent, prev_image)
        print(f"🎨 인페인트 요청: #{self.selected_index}, is_parent={is_parent}, direction={direction}, prev_image={'있음' if prev_image else '없음'}")

    def _on_inpaint_confirmed(self, index: int, new_image: Image.Image):
        """🆕 인페인트 결과 적용"""
        if 0 <= index < len(self.images):
            # 이미지 교체
            self.images[index] = new_image

            # 썸네일 업데이트
            if index < len(self.thumbnails) and self.thumbnails[index]:
                self.thumbnails[index].image = new_image
                self.thumbnails[index]._set_thumbnail()

            # 🐛 수정: 인페인트는 순서 변경이 아니라 이미지 내용 수정이므로
            # _order_changed 플래그를 설정하지 않음 (재생성 기능 유지)
            # self._order_changed = True  # ← 제거됨
            # self.order_warning_label.show()  # ← 제거됨

            # 그리드 업데이트 요청 (이미지 내용이 변경되었으므로)
            self.request_grid_update.emit()

            print(f"✅ 인페인트 결과 적용: #{index}")
