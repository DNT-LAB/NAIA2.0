"""
Sequence Inpaint Dialog

Turbo Event Sequence용 인페인트 편집 다이얼로그.
History Panel에서 개별 이미지 수정 시 사용.
"""

import io
import numpy as np
from PIL import Image, ImageDraw
from PIL.ImageQt import ImageQt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QLabel, QPushButton, QSlider, QFrame, QGraphicsView,
    QGraphicsScene, QGraphicsPixmapItem, QProgressBar, QSplitter,
    QSizePolicy, QScrollArea
)
from typing import List
from PyQt6.QtGui import QPixmap, QPainter, QColor, QPen
from PyQt6.QtCore import Qt, QPointF, QEvent, pyqtSignal, QTimer

from ui.theme import DARK_STYLES, DARK_COLORS
from ui.scaling_manager import get_scaled_font_size, get_scaled_size

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.context import AppContext


class MaskEditWidget(QWidget):
    """마스크 편집 위젯 (InpaintWindow 로직 재사용)"""

    # 시그널
    generate_requested = pyqtSignal(dict)  # mask_data

    def __init__(self, pil_image: Image.Image, initial_mask: Image.Image = None, parent=None):
        super().__init__(parent)
        self.original_pil_image = pil_image
        self.background_pixmap = QPixmap.fromImage(ImageQt(self.original_pil_image.convert("RGBA")))

        # 8x8 격자 시스템
        w, h = self.original_pil_image.size
        self.mirror_width = w // 8
        self.mirror_height = h // 8
        self.mirror_image = [[0 for _ in range(self.mirror_height)] for _ in range(self.mirror_width)]

        # 기존 마스크가 있다면 격자로 변환
        if initial_mask:
            self._convert_mask_to_grid(initial_mask)

        # 표시용 알파 레이어
        self.alpha_layer_image = Image.new("L", (w, h), 0)
        self._update_display_from_grid()

        self.composite_pixmap = QPixmap(self.background_pixmap.size())
        self.composite_pixmap.fill(Qt.GlobalColor.transparent)

        self.brush_size = 50
        self.brush_shape = 'Square'
        self.strength = 0.7  # 🆕 Strength 기본값
        self.last_paint_pos: QPointF = None

        self._init_ui()
        self._update_composite_display()

    def _convert_mask_to_grid(self, mask_image: Image.Image):
        """마스크를 격자 시스템으로 변환"""
        mask_array = np.array(mask_image.convert("L"))
        h, w = mask_array.shape

        for gx in range(self.mirror_width):
            for gy in range(self.mirror_height):
                y1, y2 = gy * 8, min((gy + 1) * 8, h)
                x1, x2 = gx * 8, min((gx + 1) * 8, w)

                block_avg = np.mean(mask_array[y1:y2, x1:x2])
                if block_avg > 127:
                    self.mirror_image[gx][gy] = 1

    def _update_display_from_grid(self):
        """격자 데이터 기반 표시용 이미지 업데이트"""
        w, h = self.original_pil_image.size
        alpha_array = np.zeros((h, w), dtype=np.uint8)

        for gx in range(self.mirror_width):
            for gy in range(self.mirror_height):
                if self.mirror_image[gx][gy] > 0:
                    y1, y2 = gy * 8, min((gy + 1) * 8, h)
                    x1, x2 = gx * 8, min((gx + 1) * 8, w)
                    alpha_array[y1:y2, x1:x2] = 255

        self.alpha_layer_image = Image.fromarray(alpha_array, mode='L')

    def _init_ui(self):
        """UI 초기화"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # 상단 툴바
        toolbar = self._create_toolbar()
        layout.addWidget(toolbar)

        # 캔버스 영역
        self.scene = QGraphicsScene()
        self.view = QGraphicsView(self.scene)
        self.view.setStyleSheet(f"""
            QGraphicsView {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
            }}
        """)
        # 스크롤바 비활성화 (마우스 휠은 브러시 크기 조절에 사용)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.view)
        self.view.viewport().installEventFilter(self)

        # 배경과 합성 이미지
        self.bg_item = QGraphicsPixmapItem(self.background_pixmap)
        self.composite_item = QGraphicsPixmapItem()
        self.scene.addItem(self.bg_item)
        self.scene.addItem(self.composite_item)
        self.scene.setSceneRect(self.background_pixmap.rect().toRectF())

        # 하단 버튼
        bottom_layout = QHBoxLayout()
        bottom_layout.addStretch()

        self.generate_btn = QPushButton("🎨 생성하기")
        self.generate_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.generate_btn.clicked.connect(self._on_generate_clicked)
        bottom_layout.addWidget(self.generate_btn)

        self.clear_btn = QPushButton("🗑️ 마스크 초기화")
        self.clear_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.clear_btn.clicked.connect(self._on_clear_mask)
        bottom_layout.addWidget(self.clear_btn)

        layout.addLayout(bottom_layout)

    def _create_toolbar(self) -> QWidget:
        """툴바 생성"""
        toolbar = QWidget()
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 브러시 크기
        size_label = QLabel("브러시 크기:")
        size_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']};")
        layout.addWidget(size_label)

        self.size_value_label = QLabel(f"{self.brush_size}")
        self.size_value_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; min-width: 30px;")
        layout.addWidget(self.size_value_label)

        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(8, 160)
        self.size_slider.setValue(self.brush_size)
        self.size_slider.valueChanged.connect(self._update_brush_size)
        self.size_slider.setStyleSheet(DARK_STYLES['compact_slider'])
        self.size_slider.setFixedWidth(150)
        layout.addWidget(self.size_slider)

        # 브러시 모양
        self.shape_btn = QPushButton("■ 사각형")
        self.shape_btn.setCheckable(True)
        self.shape_btn.toggled.connect(self._toggle_brush_shape)
        self.shape_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        layout.addWidget(self.shape_btn)

        # 구분선
        separator = QLabel("|")
        separator.setStyleSheet(f"color: {DARK_COLORS['text_secondary']};")
        layout.addWidget(separator)

        # 🆕 Strength 슬라이더
        strength_label = QLabel("Strength:")
        strength_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']};")
        layout.addWidget(strength_label)

        self.strength_value_label = QLabel(f"{self.strength:.2f}")
        self.strength_value_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; min-width: 35px;")
        layout.addWidget(self.strength_value_label)

        self.strength_slider = QSlider(Qt.Orientation.Horizontal)
        self.strength_slider.setRange(1, 100)  # 0.01 ~ 1.00
        self.strength_slider.setValue(int(self.strength * 100))
        self.strength_slider.valueChanged.connect(self._update_strength)
        self.strength_slider.setStyleSheet(DARK_STYLES['compact_slider'])
        self.strength_slider.setFixedWidth(120)
        layout.addWidget(self.strength_slider)

        layout.addStretch()

        # 안내 텍스트
        hint = QLabel("좌클릭: 그리기 | 우클릭: 지우기 | 휠: 크기 조절")
        hint.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(11)}px;")
        layout.addWidget(hint)

        return toolbar

    def _update_brush_size(self, value):
        """브러시 크기 업데이트 (8의 배수)"""
        aligned_value = (value // 8) * 8
        if aligned_value < 8:
            aligned_value = 8

        self.brush_size = aligned_value
        self.size_value_label.setText(str(aligned_value))
        self.size_slider.setValue(aligned_value)

    def _toggle_brush_shape(self, checked):
        """브러시 모양 토글"""
        if checked:
            self.brush_shape = 'Circle'
            self.shape_btn.setText("● 원형")
        else:
            self.brush_shape = 'Square'
            self.shape_btn.setText("■ 사각형")

    def _update_strength(self, value):
        """🆕 Strength 업데이트"""
        self.strength = value / 100.0
        self.strength_value_label.setText(f"{self.strength:.2f}")

    def eventFilter(self, source, event: QEvent) -> bool:
        """이벤트 필터"""
        if source is self.view.viewport():
            if event.type() == QEvent.Type.MouseButtonPress:
                self.last_paint_pos = event.pos()
                erase_mode = event.buttons() == Qt.MouseButton.RightButton
                self._paint_at(event.pos(), erase_mode)
                return True
            elif event.type() == QEvent.Type.MouseMove and self.last_paint_pos and event.buttons():
                erase_mode = event.buttons() == Qt.MouseButton.RightButton
                self._paint_at(event.pos(), erase_mode)
                return True
            elif event.type() == QEvent.Type.MouseButtonRelease:
                self.last_paint_pos = None
                return True
        return super().eventFilter(source, event)

    def _paint_at(self, pos: QPointF, erase: bool):
        """격자 기반 페인팅"""
        scene_pos = self.view.mapToScene(pos.toPoint() if isinstance(pos, QPointF) else pos)
        img_x, img_y = int(scene_pos.x()), int(scene_pos.y())

        grid_x, grid_y = img_x // 8, img_y // 8

        if not (0 <= grid_x < self.mirror_width and 0 <= grid_y < self.mirror_height):
            return

        brush_size_grid = max(1, self.brush_size // 8)
        half_brush = brush_size_grid // 2

        if self.last_paint_pos:
            last_scene_pos = self.view.mapToScene(
                self.last_paint_pos.toPoint() if isinstance(self.last_paint_pos, QPointF) else self.last_paint_pos
            )
            last_grid_x, last_grid_y = int(last_scene_pos.x()) // 8, int(last_scene_pos.y()) // 8
            self._draw_grid_line(last_grid_x, last_grid_y, grid_x, grid_y, half_brush, erase)

        self._apply_brush_to_grid(grid_x, grid_y, half_brush, erase)
        self._update_display_from_grid()
        self._update_composite_display()
        self.last_paint_pos = pos

    def _draw_grid_line(self, x0: int, y0: int, x1: int, y1: int, brush_radius: int, erase: bool):
        """Bresenham 라인 알고리즘"""
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy

        x, y = x0, y0

        while True:
            self._apply_brush_to_grid(x, y, brush_radius, erase)

            if x == x1 and y == y1:
                break

            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x += sx
            if e2 < dx:
                err += dx
                y += sy

    def _apply_brush_to_grid(self, center_x: int, center_y: int, brush_radius: int, erase: bool):
        """격자에 브러시 적용"""
        if self.brush_shape == 'Circle':
            for dx in range(-brush_radius, brush_radius + 1):
                for dy in range(-brush_radius, brush_radius + 1):
                    if dx * dx + dy * dy <= brush_radius * brush_radius:
                        gx, gy = center_x + dx, center_y + dy
                        if 0 <= gx < self.mirror_width and 0 <= gy < self.mirror_height:
                            self.mirror_image[gx][gy] = 0 if erase else 1
        else:
            for dx in range(-brush_radius, brush_radius + 1):
                for dy in range(-brush_radius, brush_radius + 1):
                    gx, gy = center_x + dx, center_y + dy
                    if 0 <= gx < self.mirror_width and 0 <= gy < self.mirror_height:
                        self.mirror_image[gx][gy] = 0 if erase else 1

    def _update_composite_display(self):
        """합성 이미지 업데이트"""
        w, h = self.original_pil_image.size

        original_rgba = self.original_pil_image.convert('RGBA')
        original_array = np.array(original_rgba)
        alpha_array = np.array(self.alpha_layer_image)

        result_array = original_array.copy()
        mask_indices = alpha_array == 255

        # 파란색 오버레이
        blue_color = np.array([0, 0, 255, 120], dtype=np.uint8)
        original_alpha = result_array[mask_indices, 3].astype(np.float32) / 255.0
        overlay_alpha = 120 / 255.0

        combined_alpha = overlay_alpha + original_alpha * (1 - overlay_alpha)
        result_array[mask_indices, 0] = (blue_color[0] * overlay_alpha +
                                         result_array[mask_indices, 0] * original_alpha * (1 - overlay_alpha)) / combined_alpha
        result_array[mask_indices, 1] = (blue_color[1] * overlay_alpha +
                                         result_array[mask_indices, 1] * original_alpha * (1 - overlay_alpha)) / combined_alpha
        result_array[mask_indices, 2] = (blue_color[2] * overlay_alpha +
                                         result_array[mask_indices, 2] * original_alpha * (1 - overlay_alpha)) / combined_alpha
        result_array[mask_indices, 3] = combined_alpha * 255

        composite_image = Image.fromarray(result_array.astype(np.uint8), 'RGBA')
        self.composite_pixmap = QPixmap.fromImage(ImageQt(composite_image))
        self.composite_item.setPixmap(self.composite_pixmap)

    def _on_clear_mask(self):
        """마스크 초기화"""
        for gx in range(self.mirror_width):
            for gy in range(self.mirror_height):
                self.mirror_image[gx][gy] = 0

        self._update_display_from_grid()
        self._update_composite_display()

    def _on_generate_clicked(self):
        """생성 버튼 클릭"""
        mask_data = self._create_mask_data()

        if mask_data is None:
            return

        self.generate_requested.emit(mask_data)

    def _create_mask_data(self) -> Optional[dict]:
        """마스크 데이터 생성"""
        w, h = self.original_pil_image.size

        full_mask_array = np.zeros((h, w), dtype=np.uint8)
        small_mask_array = np.zeros((self.mirror_height, self.mirror_width), dtype=np.uint8)

        for gx in range(self.mirror_width):
            for gy in range(self.mirror_height):
                if self.mirror_image[gx][gy] > 0:
                    y1, y2 = gy * 8, min((gy + 1) * 8, h)
                    x1, x2 = gx * 8, min((gx + 1) * 8, w)
                    full_mask_array[y1:y2, x1:x2] = 255
                    small_mask_array[gy, gx] = 255

        full_mask_image = Image.fromarray(full_mask_array, mode='L')
        small_mask_image = Image.fromarray(small_mask_array, mode='L')

        painted_pixels_count = sum(sum(row) for row in self.mirror_image)

        if painted_pixels_count < 8:
            print("🎨 마스크 블록 수가 8 미만입니다.")
            return None

        return {
            "full_mask_image": full_mask_image,
            "small_mask_image": small_mask_image,
            "original_image": self.original_pil_image,
            "strength": self.strength  # 🆕 Strength 값 포함
        }

    def wheelEvent(self, event):
        """마우스 휠 - 브러시 크기 조절"""
        delta = event.angleDelta().y()

        if delta > 0:
            new_size = min(160, self.brush_size + 8)
            self.size_slider.setValue(new_size)
        elif delta < 0:
            new_size = max(8, self.brush_size - 8)
            self.size_slider.setValue(new_size)

        event.accept()


class ResultThumbnail(QLabel):
    """결과 히스토리 썸네일"""
    clicked = pyqtSignal(int)  # index

    THUMB_SIZE = 60  # 60x60 px

    def __init__(self, image: Image.Image, index: int, parent=None):
        super().__init__(parent)
        self.index = index
        self.is_selected = False

        self.setFixedSize(self.THUMB_SIZE, self.THUMB_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._set_thumbnail(image)
        self._update_style()

    def _set_thumbnail(self, image: Image.Image):
        """썸네일 설정"""
        thumb = image.copy()
        thumb.thumbnail((self.THUMB_SIZE, self.THUMB_SIZE), Image.Resampling.LANCZOS)
        pixmap = QPixmap.fromImage(ImageQt(thumb.convert("RGBA")))
        self.setPixmap(pixmap.scaled(
            self.THUMB_SIZE, self.THUMB_SIZE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        ))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def set_selected(self, selected: bool):
        self.is_selected = selected
        self._update_style()

    def _update_style(self):
        border_color = DARK_COLORS['accent_blue'] if self.is_selected else DARK_COLORS['border']
        border_width = 3 if self.is_selected else 1
        self.setStyleSheet(f"""
            QLabel {{
                border: {border_width}px solid {border_color};
                border-radius: 4px;
                background-color: {DARK_COLORS['bg_primary']};
            }}
        """)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.index)
        super().mousePressEvent(event)


class ResultWidget(QWidget):
    """결과 확인 위젯 (히스토리 기능 포함)"""

    # 시그널
    regenerate_requested = pyqtSignal()
    edit_mask_requested = pyqtSignal()
    cancel_requested = pyqtSignal()
    confirm_requested = pyqtSignal()

    # 히스토리 상수
    MAX_HISTORY = 10

    def __init__(self, image_size: tuple = (832, 608), parent=None):
        """
        Args:
            image_size: 원본 이미지 크기 (width, height)
        """
        super().__init__(parent)
        self.original_image: Optional[Image.Image] = None
        self.result_image: Optional[Image.Image] = None
        self.image_size = image_size  # 원본 이미지 크기

        # 🆕 히스토리 관련
        self.result_history: List[Image.Image] = []
        self.selected_index: int = -1
        self.thumbnail_widgets: List[ResultThumbnail] = []

        self._init_ui()

    def _init_ui(self):
        """UI 초기화"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # 이미지 비교 영역
        self.splitter = QSplitter(Qt.Orientation.Horizontal)

        # 원본 이미지
        original_frame = QFrame()
        original_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
            }}
        """)
        original_layout = QVBoxLayout(original_frame)
        original_layout.setContentsMargins(4, 4, 4, 4)

        original_title = QLabel("📷 원본")
        original_title.setStyleSheet(f"""
            font-size: {get_scaled_font_size(13)}px;
            font-weight: bold;
            color: {DARK_COLORS['text_primary']};
        """)
        original_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        original_layout.addWidget(original_title)

        self.original_label = QLabel()
        self.original_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.original_label.setMinimumSize(self.image_size[0] // 2, self.image_size[1] // 2)
        self.original_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        original_layout.addWidget(self.original_label)

        self.splitter.addWidget(original_frame)

        # 결과 이미지
        result_frame = QFrame()
        result_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
            }}
        """)
        result_layout = QVBoxLayout(result_frame)
        result_layout.setContentsMargins(4, 4, 4, 4)

        result_title = QLabel("🎨 인페인트 결과")
        result_title.setStyleSheet(f"""
            font-size: {get_scaled_font_size(13)}px;
            font-weight: bold;
            color: {DARK_COLORS['text_primary']};
        """)
        result_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        result_layout.addWidget(result_title)

        self.result_label = QLabel()
        self.result_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.result_label.setMinimumSize(self.image_size[0] // 2, self.image_size[1] // 2)
        self.result_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        result_layout.addWidget(self.result_label)

        self.splitter.addWidget(result_frame)

        layout.addWidget(self.splitter)

        # 🆕 히스토리 스트립
        history_strip = self._create_history_strip()
        layout.addWidget(history_strip)

        # 프로그레스 바
        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                text-align: center;
            }}
            QProgressBar::chunk {{
                background-color: {DARK_COLORS['accent_blue']};
            }}
        """)
        self.progress_bar.setRange(0, 0)  # 불확정 프로그레스
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        # 상태 라벨
        self.status_label = QLabel("마스크를 그리고 '생성하기' 버튼을 클릭하세요")
        self.status_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(12)}px;
            color: {DARK_COLORS['text_secondary']};
        """)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        # 버튼 영역
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.regenerate_btn = QPushButton("🔄 재생성")
        self.regenerate_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.regenerate_btn.clicked.connect(self.regenerate_requested.emit)
        self.regenerate_btn.setEnabled(False)
        btn_layout.addWidget(self.regenerate_btn)

        self.edit_btn = QPushButton("✏️ 마스크 편집")
        self.edit_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.edit_btn.clicked.connect(self.edit_mask_requested.emit)
        btn_layout.addWidget(self.edit_btn)

        self.cancel_btn = QPushButton("↩️ 수정 취소")
        self.cancel_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.cancel_btn.clicked.connect(self.cancel_requested.emit)
        btn_layout.addWidget(self.cancel_btn)

        self.confirm_btn = QPushButton("✅ 이미지 결정")
        self.confirm_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.confirm_btn.clicked.connect(self.confirm_requested.emit)
        self.confirm_btn.setEnabled(False)
        btn_layout.addWidget(self.confirm_btn)

        layout.addLayout(btn_layout)

        # 🆕 결과창 초기화: #212121 색상의 빈 이미지
        self._init_empty_result_image()

    def _init_empty_result_image(self):
        """빈 결과 이미지 초기화 (#212121 색상)"""
        empty_image = Image.new('RGB', self.image_size, (0x21, 0x21, 0x21))
        self._update_image_display(self.result_label, empty_image)

    def set_original_image(self, image: Image.Image):
        """원본 이미지 설정"""
        self.original_image = image
        self._update_image_display(self.original_label, image)

    def set_result_image(self, image: Image.Image):
        """결과 이미지 설정 (단일 이미지 - 하위 호환성)"""
        self.add_result_image(image)

    def add_result_image(self, image: Image.Image):
        """🆕 결과 이미지를 히스토리에 추가"""
        # 최대 개수 제한 (FIFO)
        if len(self.result_history) >= self.MAX_HISTORY:
            self.result_history.pop(0)
            # 첫 번째 썸네일 제거
            if self.thumbnail_widgets:
                old_thumb = self.thumbnail_widgets.pop(0)
                old_thumb.setParent(None)
                old_thumb.deleteLater()
                # 인덱스 재조정
                for i, thumb in enumerate(self.thumbnail_widgets):
                    thumb.index = i

        # 히스토리에 추가
        self.result_history.append(image)
        self.selected_index = len(self.result_history) - 1

        # 썸네일 추가
        self._add_thumbnail(image, self.selected_index)

        # UI 업데이트
        self._update_history_label()
        self._update_thumbnail_selection()
        self._show_selected_result()

        # 버튼 활성화
        self.regenerate_btn.setEnabled(True)
        self.confirm_btn.setEnabled(True)

    def _create_history_strip(self) -> QWidget:
        """🆕 히스토리 썸네일 스트립 생성"""
        strip = QFrame()
        strip.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
            }}
        """)
        strip.setFixedHeight(90)

        strip_layout = QHBoxLayout(strip)
        strip_layout.setContentsMargins(8, 4, 8, 4)
        strip_layout.setSpacing(8)

        # 라벨
        self.history_label = QLabel("📚 히스토리 (0/10)")
        self.history_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(11)}px;
            color: {DARK_COLORS['text_secondary']};
            border: none;
        """)
        self.history_label.setFixedWidth(100)
        strip_layout.addWidget(self.history_label)

        # 썸네일 스크롤 영역
        self.history_scroll = QScrollArea()
        self.history_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.history_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.history_scroll.setWidgetResizable(True)
        self.history_scroll.setStyleSheet(f"""
            QScrollArea {{
                background-color: transparent;
                border: none;
            }}
        """)

        # 썸네일 컨테이너
        self.history_container = QWidget()
        self.history_container.setStyleSheet("background-color: transparent;")
        self.history_layout = QHBoxLayout(self.history_container)
        self.history_layout.setContentsMargins(0, 0, 0, 0)
        self.history_layout.setSpacing(6)
        self.history_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self.history_scroll.setWidget(self.history_container)
        strip_layout.addWidget(self.history_scroll)

        return strip

    def _add_thumbnail(self, image: Image.Image, index: int):
        """🆕 썸네일 추가"""
        thumb = ResultThumbnail(image, index, self.history_container)
        thumb.clicked.connect(self._on_thumbnail_clicked)
        self.thumbnail_widgets.append(thumb)
        self.history_layout.addWidget(thumb)

    def _on_thumbnail_clicked(self, index: int):
        """🆕 썸네일 클릭"""
        self.select_result(index)

    def select_result(self, index: int):
        """🆕 히스토리에서 결과 선택"""
        if 0 <= index < len(self.result_history):
            self.selected_index = index
            self._update_thumbnail_selection()
            self._show_selected_result()

    def _update_thumbnail_selection(self):
        """🆕 썸네일 선택 상태 업데이트"""
        for i, thumb in enumerate(self.thumbnail_widgets):
            thumb.set_selected(i == self.selected_index)

    def _show_selected_result(self):
        """🆕 선택된 결과 이미지 표시"""
        if 0 <= self.selected_index < len(self.result_history):
            self.result_image = self.result_history[self.selected_index]
            self._update_image_display(self.result_label, self.result_image)

    def _update_history_label(self):
        """🆕 히스토리 라벨 업데이트"""
        count = len(self.result_history)
        self.history_label.setText(f"📚 히스토리 ({count}/{self.MAX_HISTORY})")

    def get_selected_result(self) -> Optional[Image.Image]:
        """🆕 선택된 결과 반환"""
        if 0 <= self.selected_index < len(self.result_history):
            return self.result_history[self.selected_index]
        return None

    def clear_history(self):
        """🆕 히스토리 초기화"""
        self.result_history.clear()
        self.selected_index = -1

        # 썸네일 제거
        for thumb in self.thumbnail_widgets:
            thumb.setParent(None)
            thumb.deleteLater()
        self.thumbnail_widgets.clear()

        self._update_history_label()
        self._init_empty_result_image()

    def _update_image_display(self, label: QLabel, image: Image.Image):
        """이미지 디스플레이 업데이트"""
        if image is None:
            label.clear()
            return

        # 라벨 크기에 맞게 리사이즈
        label_size = label.size()
        max_w, max_h = label_size.width() - 10, label_size.height() - 10

        img_w, img_h = image.size
        scale = min(max_w / img_w, max_h / img_h)
        new_w, new_h = int(img_w * scale), int(img_h * scale)

        resized = image.resize((new_w, new_h), Image.Resampling.LANCZOS)
        pixmap = QPixmap.fromImage(ImageQt(resized.convert("RGBA")))
        label.setPixmap(pixmap)

    def show_generating(self):
        """생성 중 상태 표시"""
        self.progress_bar.show()
        self.status_label.setText("🎨 인페인트 생성 중...")
        self.regenerate_btn.setEnabled(False)
        self.confirm_btn.setEnabled(False)

    def hide_generating(self):
        """생성 완료 상태"""
        self.progress_bar.hide()
        self.status_label.setText("✅ 생성 완료! 결과를 확인하세요.")

    def show_error(self, message: str):
        """오류 표시"""
        self.progress_bar.hide()
        self.status_label.setText(f"❌ 오류: {message}")


class SequenceInpaintDialog(QDialog):
    """Turbo Event Sequence용 인페인트 다이얼로그"""

    # 시그널
    image_confirmed = pyqtSignal(int, object)  # history_index, PIL.Image

    # 캔버스 크기 상수
    CANVAS_SIZE_H = (832, 1216)   # 가로 방향
    CANVAS_SIZE_V = (1216, 832)   # 세로 방향
    PASTE_SIZE_H = (832, 608)     # 가로 방향 Child 크기
    PASTE_SIZE_V = (608, 832)     # 세로 방향 Child 크기
    PARENT_SIZE_H = (1152, 832)   # 가로 방향 Parent 크기
    PARENT_SIZE_V = (832, 1152)   # 세로 방향 Parent 크기

    def __init__(
        self,
        image: Image.Image,
        history_index: int,
        direction: str,
        is_parent: bool,
        prompt: str,
        negative_prompt: str,
        app_context: 'AppContext',
        prev_image: Optional[Image.Image] = None,  # 🆕 이전 이미지 (Child 인페인트 시 상단에 사용)
        parent=None
    ):
        super().__init__(parent)
        self.original_image = image
        self.history_index = history_index
        self.direction = direction
        self.is_parent = is_parent
        self.prompt = prompt
        self.negative_prompt = negative_prompt
        self.app_context = app_context
        self.prev_image = prev_image  # 🆕 이전 이미지 저장

        self.result_image: Optional[Image.Image] = None
        self._current_mask_data: Optional[dict] = None
        self._waiting_for_result = False
        self._request_id: Optional[str] = None  # 요청 ID (응답 매칭용)

        self._init_ui()
        self._connect_signals()

    def _init_ui(self):
        """UI 초기화"""
        self.setWindowTitle(f"🎨 인페인트 편집 - #{self.history_index}")
        # 🆕 윈도우 최소 크기 1.5배로 증가 (900x700 → 1350x1050)
        self.setMinimumSize(1350, 1050)
        self.setStyleSheet(f"background-color: {DARK_COLORS['bg_secondary']};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # 헤더
        header = self._create_header()
        layout.addWidget(header)

        # 탭 위젯
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet(DARK_STYLES['dark_tabs'])

        # 마스크 편집 탭
        self.mask_edit_widget = MaskEditWidget(self.original_image)
        self.tab_widget.addTab(self.mask_edit_widget, "✏️ 마스크 편집")

        # 결과 탭 - 원본 이미지 크기 전달
        w, h = self.original_image.size
        self.result_widget = ResultWidget(image_size=(w, h))
        self.result_widget.set_original_image(self.original_image)
        self.tab_widget.addTab(self.result_widget, "🖼️ 결과")

        layout.addWidget(self.tab_widget)

        # 🆕 크기 조정: 원본 크기의 1.5배 기반
        self.resize(max(1350, int(w * 1.5) + 100), max(1050, int(h * 1.5) + 200))

    def _create_header(self) -> QWidget:
        """헤더 생성"""
        header = QFrame()
        header.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border-radius: 4px;
                padding: 4px;
            }}
        """)

        layout = QHBoxLayout(header)
        layout.setContentsMargins(8, 4, 8, 4)

        # 정보 라벨
        img_type = "Parent" if self.is_parent else "Child"
        direction_text = "가로" if self.direction == 'horizontal' else "세로"
        w, h = self.original_image.size

        info_label = QLabel(f"📷 이미지 #{self.history_index} | {img_type} | {direction_text} | {w}x{h}")
        info_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(13)}px;
            color: {DARK_COLORS['text_primary']};
        """)
        layout.addWidget(info_label)

        layout.addStretch()

        # 닫기 버튼
        close_btn = QPushButton("✕")
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {DARK_COLORS['text_secondary']};
                border: none;
                font-size: 16px;
                padding: 4px 8px;
            }}
            QPushButton:hover {{
                color: {DARK_COLORS['text_primary']};
                background-color: {DARK_COLORS['bg_primary']};
            }}
        """)
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

        return header

    def _connect_signals(self):
        """시그널 연결"""
        # 마스크 편집 위젯
        self.mask_edit_widget.generate_requested.connect(self._on_generate_requested)

        # 결과 위젯
        self.result_widget.regenerate_requested.connect(self._on_regenerate_requested)
        self.result_widget.edit_mask_requested.connect(self._on_edit_mask_requested)
        self.result_widget.cancel_requested.connect(self.close)
        self.result_widget.confirm_requested.connect(self._on_confirm_requested)

        # 생성 이벤트 구독
        if self.app_context:
            self.app_context.subscribe("generation_completed", self._on_generation_completed)
            self.app_context.subscribe("generation_error", self._on_generation_error)

    def _on_generate_requested(self, mask_data: dict):
        """생성 요청"""
        self._current_mask_data = mask_data
        self._request_inpaint()

    def _on_regenerate_requested(self):
        """재생성 요청"""
        if self._current_mask_data:
            self._request_inpaint()

    def _on_edit_mask_requested(self):
        """마스크 편집 탭으로 전환"""
        self.tab_widget.setCurrentIndex(0)

    def _on_confirm_requested(self):
        """이미지 결정"""
        # 🆕 히스토리에서 선택된 결과 가져오기
        selected = self.result_widget.get_selected_result()
        if selected:
            self.image_confirmed.emit(self.history_index, selected)
            self.close()

    def _request_inpaint(self):
        """인페인트 요청"""
        if self._current_mask_data is None:
            return

        self._waiting_for_result = True
        self.result_widget.show_generating()
        self.tab_widget.setCurrentIndex(1)  # 결과 탭으로 전환

        # 캔버스 및 마스크 준비
        canvas, mask = self._prepare_canvas_and_mask()

        # GenerationController 호출
        self._execute_inpaint(canvas, mask)

    def _prepare_canvas_and_mask(self):
        """캔버스 및 마스크 준비"""
        small_mask = self._current_mask_data['small_mask_image']

        if self.is_parent:
            # Parent 이미지: 그대로 사용
            canvas = self.original_image
            mask = small_mask
        else:
            # Child 이미지: 캔버스 확장 필요
            canvas = self._expand_child_to_canvas(self.original_image)
            mask = self._reposition_mask_for_canvas(small_mask)

        return canvas, mask

    def _expand_child_to_canvas(self, child_image: Image.Image) -> Image.Image:
        """
        Child 이미지를 NAI 캔버스 크기로 확장.

        🆕 상단/좌측에는 이전 시퀀스 이미지(prev_image), 하단/우측에는 현재 child 이미지 배치.
        prev_image가 없으면 현재 child 이미지를 상단/좌측에도 사용.
        """
        if self.direction == 'horizontal':
            canvas_w, canvas_h = self.CANVAS_SIZE_H  # 832 x 1216
            canvas = Image.new('RGB', (canvas_w, canvas_h), (0, 0, 0))

            # 🆕 상단에 이전 이미지 배치 (없으면 현재 이미지)
            top_image = self._prepare_prev_image_for_canvas(child_image.size) if self.prev_image else child_image
            canvas.paste(top_image, (0, 0))

            # 하단에 현재 child 이미지 배치
            canvas.paste(child_image, (0, 608))

            # 경계 검정띠
            draw = ImageDraw.Draw(canvas)
            draw.rectangle([(0, 600), (canvas_w, 616)], fill=(0, 0, 0))

        else:  # vertical
            canvas_w, canvas_h = self.CANVAS_SIZE_V  # 1216 x 832
            canvas = Image.new('RGB', (canvas_w, canvas_h), (0, 0, 0))

            # 🆕 좌측에 이전 이미지 배치 (없으면 현재 이미지)
            left_image = self._prepare_prev_image_for_canvas(child_image.size) if self.prev_image else child_image
            canvas.paste(left_image, (0, 0))

            # 우측에 현재 child 이미지 배치
            canvas.paste(child_image, (608, 0))

            # 경계 검정띠
            draw = ImageDraw.Draw(canvas)
            draw.rectangle([(600, 0), (616, canvas_h)], fill=(0, 0, 0))

        return canvas

    def _prepare_prev_image_for_canvas(self, target_size: tuple) -> Image.Image:
        """
        🆕 이전 이미지를 캔버스에 맞게 리사이즈 및 크롭.

        Args:
            target_size: 목표 크기 (width, height)

        Returns:
            리사이즈된 이미지
        """
        if self.prev_image is None:
            return None

        target_w, target_h = target_size
        prev_w, prev_h = self.prev_image.size

        # 비율 유지 리사이즈 (목표 영역을 완전히 채우도록)
        scale_w = target_w / prev_w
        scale_h = target_h / prev_h
        scale = max(scale_w, scale_h)

        new_w = int(prev_w * scale)
        new_h = int(prev_h * scale)

        resized = self.prev_image.resize((new_w, new_h), Image.Resampling.LANCZOS)

        # 중앙 크롭
        left = (new_w - target_w) // 2
        top = (new_h - target_h) // 2
        cropped = resized.crop((left, top, left + target_w, top + target_h))

        return cropped

    def _reposition_mask_for_canvas(self, small_mask: Image.Image) -> Image.Image:
        """
        마스크를 캔버스 좌표계로 재배치.

        🆕 이전 이미지가 있으면 상단/좌측은 보존 영역(검정), 하단/우측에만 마스크 배치.
        이전 이미지가 없으면 양쪽에 동일한 마스크 배치 (기존 동작).
        """
        if self.direction == 'horizontal':
            # 마스크 크기: 104 x 76 (Child) → 104 x 152 (Canvas)
            mask_w = self.CANVAS_SIZE_H[0] // 8  # 104
            mask_h = self.CANVAS_SIZE_H[1] // 8  # 152
            half_h = 76  # 608 // 8

            new_mask = Image.new('L', (mask_w, mask_h), 0)

            if self.prev_image is not None:
                # 🆕 이전 이미지가 있으면: 상단은 보존(검정), 하단에만 마스크
                new_mask.paste(small_mask, (0, half_h))
            else:
                # 이전 이미지가 없으면: 양쪽에 동일 마스크
                new_mask.paste(small_mask, (0, 0))
                new_mask.paste(small_mask, (0, half_h))

        else:  # vertical
            # 마스크 크기: 76 x 104 (Child) → 152 x 104 (Canvas)
            mask_w = self.CANVAS_SIZE_V[0] // 8  # 152
            mask_h = self.CANVAS_SIZE_V[1] // 8  # 104
            half_w = 76  # 608 // 8

            new_mask = Image.new('L', (mask_w, mask_h), 0)

            if self.prev_image is not None:
                # 🆕 이전 이미지가 있으면: 좌측은 보존(검정), 우측에만 마스크
                new_mask.paste(small_mask, (half_w, 0))
            else:
                # 이전 이미지가 없으면: 양쪽에 동일 마스크
                new_mask.paste(small_mask, (0, 0))
                new_mask.paste(small_mask, (half_w, 0))

        return new_mask

    def _show_debug_preview(self, canvas: Image.Image, mask: Image.Image):
        """🔧 디버그용 캔버스 및 마스크 미리보기"""
        try:
            # 마스크를 캔버스 크기로 확대
            mask_enlarged = mask.resize((canvas.width, canvas.height), Image.Resampling.NEAREST)
            mask_rgb = mask_enlarged.convert('RGB')

            # 캔버스와 마스크를 나란히 붙임
            debug_width = canvas.width * 2 + 20
            debug_height = canvas.height
            debug_image = Image.new('RGB', (debug_width, debug_height), (50, 50, 50))

            # 캔버스 붙이기
            debug_image.paste(canvas, (0, 0))

            # 마스크 붙이기
            debug_image.paste(mask_rgb, (canvas.width + 20, 0))

            # 디버그 이미지 표시
            img_type = "Parent" if self.is_parent else "Child"
            print(f"🔧 [Debug] SequenceInpaintDialog: {img_type}, Canvas ({canvas.width}x{canvas.height}), Mask ({mask.width}x{mask.height})")
            print(f"🔧 [Debug] prev_image: {'있음' if self.prev_image else '없음'}")
            debug_image.show()
        except Exception as e:
            print(f"🔧 [Debug] Preview error: {e}")

    def _execute_inpaint(self, canvas: Image.Image, mask: Image.Image):
        """GenerationController를 통한 인페인트 실행 (SequenceGenerationWorker와 동일한 형식)"""
        try:
            import uuid

            # 🔧 디버그: 캔버스와 마스크 미리보기
            # self._show_debug_preview(canvas, mask)  # 디버그 비활성화

            # 요청 ID 생성 (응답 매칭용)
            self._request_id = str(uuid.uuid4())[:8]

            # 이미지를 bytes로 변환
            canvas_bytes = io.BytesIO()
            canvas.save(canvas_bytes, format='PNG')
            canvas_bytes.seek(0)

            mask_bytes = io.BytesIO()
            mask.save(mask_bytes, format='PNG')
            mask_bytes.seek(0)

            # 🆕 Strength 값 가져오기 (mask_data에서)
            strength = self._current_mask_data.get('strength', 0.7) if self._current_mask_data else 0.7

            # override 파라미터 (SequenceGenerationWorker._request_inpaint_generation과 동일한 형식)
            override_params = {
                'type': 'inpaint',
                'input': self.prompt,  # 프롬프트 직접 전달
                'negative_prompt': self.negative_prompt,
                'image_bytes': canvas_bytes.getvalue(),
                'mask_bytes': mask_bytes.getvalue(),
                'width': canvas.width,
                'height': canvas.height,
                'strength': strength,  # 🆕 동적 strength 값
                'noise': 0.0,
                'random_resolution': False,
                'turbo_sequence_request': True,  # 시퀀스 요청 식별자
                'sequence_inpaint_dialog': True,  # 인페인트 다이얼로그 식별자
                'sequence_inpaint_request_id': self._request_id,  # 요청 ID
            }

            print(f"[SequenceInpaintDialog] Inpaint 요청 (ID: {self._request_id})")
            print(f"   - canvas: {canvas.width}x{canvas.height}, strength: {strength}")
            print(f"   - prompt: {self.prompt[:50]}..." if len(self.prompt) > 50 else f"   - prompt: {self.prompt}")

            # GenerationController 호출
            main_window = self.app_context.main_window
            if hasattr(main_window, 'generation_controller'):
                gen_controller = main_window.generation_controller
                gen_controller.execute_generation_pipeline(overrides=override_params)
            else:
                self.result_widget.show_error("GenerationController를 찾을 수 없습니다.")
                self._waiting_for_result = False

        except Exception as e:
            print(f"[SequenceInpaintDialog] Error executing inpaint: {e}")
            import traceback
            traceback.print_exc()
            self.result_widget.show_error(str(e))
            self._waiting_for_result = False

    def _on_generation_completed(self, data: dict):
        """생성 완료 이벤트"""
        # 대기 중이 아니면 무시
        if not self._waiting_for_result:
            return

        # 이 다이얼로그의 요청인지 확인
        if not data.get('sequence_inpaint_dialog'):
            return

        # 요청 ID가 다르면 무시 (다른 인페인트 다이얼로그의 요청일 수 있음)
        request_id = data.get('sequence_inpaint_request_id')
        if request_id and self._request_id and request_id != self._request_id:
            return

        self._waiting_for_result = False

        try:
            result_image = data.get('image')
            if result_image is None:
                self.result_widget.show_error("결과 이미지가 없습니다.")
                return

            print(f"[SequenceInpaintDialog] 결과 수신 (ID: {self._request_id}): {result_image.size}")

            # 결과 영역 추출
            extracted = self._extract_result_region(result_image)

            self.result_image = extracted
            self.result_widget.set_result_image(extracted)
            self.result_widget.hide_generating()

        except Exception as e:
            print(f"[SequenceInpaintDialog] Error processing result: {e}")
            self.result_widget.show_error(str(e))

    def _on_generation_error(self, data: dict):
        """생성 오류 이벤트"""
        if not self._waiting_for_result:
            return

        # 이 다이얼로그의 요청인지 확인
        if not data.get('sequence_inpaint_dialog'):
            return

        # 요청 ID가 다르면 무시
        request_id = data.get('sequence_inpaint_request_id')
        if request_id and self._request_id and request_id != self._request_id:
            return

        self._waiting_for_result = False
        error_msg = data.get('message', 'Unknown error')
        self.result_widget.show_error(error_msg)

    def _extract_result_region(self, inpaint_result: Image.Image) -> Image.Image:
        """인페인트 결과에서 원본 영역 추출"""
        if self.is_parent:
            # Parent: 전체 이미지 반환
            return inpaint_result

        # 🐛 수정: Child는 하단/우측 절반을 추출 (인페인트된 영역)
        # 캔버스 구성: 상단/좌측에 prev_image, 하단/우측에 현재 child 이미지
        if self.direction == 'horizontal':
            # 832x1216 캔버스에서 하단 608픽셀 추출
            return inpaint_result.crop((0, 608, 832, 1216))
        else:
            # 1216x832 캔버스에서 우측 608픽셀 추출
            return inpaint_result.crop((608, 0, 1216, 832))

    def closeEvent(self, event):
        """다이얼로그 닫기"""
        # 이벤트 구독 해제
        if self.app_context:
            try:
                self.app_context.unsubscribe("generation_completed", self._on_generation_completed)
                self.app_context.unsubscribe("generation_error", self._on_generation_error)
            except:
                pass

        super().closeEvent(event)

    def keyPressEvent(self, event):
        """키보드 이벤트"""
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)
