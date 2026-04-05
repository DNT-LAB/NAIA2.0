import math
import numpy as np
from PIL import Image
from PIL.ImageQt import ImageQt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QWidget, QSpinBox, QGraphicsRectItem, QSlider
)
from PyQt6.QtGui import QPixmap, QColor, QBrush, QPen, QCursor
from PyQt6.QtCore import Qt, QPointF, QRectF, QEvent
from .theme import DARK_STYLES, DARK_COLORS
from .scaling_manager import get_scaled_font_size, get_scaled_size


class ComicPanelWindow(QDialog):
    """
    코믹 패널(2koma) 생성을 위한 아웃페인팅 설정 다이얼로그.
    원본 이미지를 좌측/위쪽 정렬로 배치하고, 크롭 기능을 지원합니다.
    """

    MAX_PIXELS = 1048576  # NAI 1MP 제한

    # 모드 상수
    MODE_NORMAL = 'normal'
    MODE_CROP = 'crop'

    def __init__(self, pil_image: Image.Image, parent=None):
        super().__init__(parent)
        self.source_image = pil_image.convert('RGB')
        self._original_uncropped = self.source_image.copy()  # 크롭 전 원본 보관
        self.src_w, self.src_h = self.source_image.size
        self.result = None
        self._interaction_mode = self.MODE_NORMAL

        # 캔버스 기본값: 소스 비율 기반 동적 계산
        self.canvas_width, self.canvas_height = self._calculate_default_canvas()

        # 이미지 변환 상태
        self.img_scale = 1.0
        self.img_rotation = 0.0
        self.img_x = 0
        self.img_y = 0

        # 드래그 상태
        self._dragging = False
        self._drag_start_pos = QPointF()
        self._drag_start_img_x = 0
        self._drag_start_img_y = 0

        # 리사이즈 핸들 상태
        self._resizing = False
        self._resize_corner = None
        self._resize_start_pos = QPointF()
        self._resize_start_scale = 1.0
        self._resize_anchor = QPointF()

        # 캐시된 변환 이미지
        self._image_item = None
        self._transformed_image = None
        self._transformed_w = 0
        self._transformed_h = 0
        self._cache_dirty = True
        self._rotated_alpha = None

        # 크롭 상태
        self._crop_dragging = False
        self._crop_start = QPointF()
        self._crop_rect = QRectF()  # 현재 선택 영역 (이미지 좌표)
        self._is_cropped = False  # 크롭이 적용된 상태인지

        self._init_ui()
        self._fit_and_align()

    # ── 유틸리티 ──────────────────────────────────────────────

    def _calculate_default_canvas(self) -> tuple[int, int]:
        """소스 이미지 비율 기반으로 2koma 캔버스 크기를 동적 계산합니다.
        이미지가 캔버스 절반을 차지하도록 비율을 결정하고, 1MP + 64배수 조건을 충족합니다."""
        if self.src_w > self.src_h:
            # 가로 이미지 → 세로 캔버스 (위아래 2koma)
            ratio_w = self.src_w
            ratio_h = self.src_h * 2
        else:
            # 세로 이미지 → 가로 캔버스 (좌우 2koma)
            ratio_w = self.src_w * 2
            ratio_h = self.src_h

        # 1MP 이내로 스케일
        total = ratio_w * ratio_h
        if total > self.MAX_PIXELS:
            scale = (self.MAX_PIXELS / total) ** 0.5
            ratio_w = ratio_w * scale
            ratio_h = ratio_h * scale

        # floor/ceil 4조합 중 1MP 이내 최대 픽셀 선택
        floor_w = max(64, (int(ratio_w) // 64) * 64)
        floor_h = max(64, (int(ratio_h) // 64) * 64)
        ceil_w = floor_w + 64
        ceil_h = floor_h + 64

        candidates = []
        for w in [floor_w, ceil_w]:
            for h in [floor_h, ceil_h]:
                if w * h <= self.MAX_PIXELS:
                    candidates.append((w, h))

        return max(candidates, key=lambda x: x[0] * x[1])

    @staticmethod
    def _snap_to_grid(value: int, grid: int = 8) -> int:
        return (value // grid) * grid

    @staticmethod
    def _round_to_64(value: int) -> int:
        return max(64, (value // 64) * 64)

    def _align_image(self):
        """가로 이미지 → 위쪽 정렬 (세로 캔버스), 세로 이미지 → 좌측 정렬 (가로 캔버스)"""
        tw, th = self._get_transformed_size()
        if self.src_w > self.src_h:
            # 가로 이미지 + 세로 캔버스: 위쪽 정렬, 가로 중앙
            self.img_x = self._snap_to_grid((self.canvas_width - tw) // 2)
            self.img_y = 0
        else:
            # 세로 이미지 + 가로 캔버스: 좌측 정렬, 세로 중앙
            self.img_x = 0
            self.img_y = self._snap_to_grid((self.canvas_height - th) // 2)

    def _get_transformed_size(self) -> tuple[int, int]:
        sw = int(self.src_w * self.img_scale)
        sh = int(self.src_h * self.img_scale)
        if abs(self.img_rotation) < 0.01:
            return sw, sh
        rad = math.radians(abs(self.img_rotation))
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        bw = int(math.ceil(sw * cos_a + sh * sin_a))
        bh = int(math.ceil(sw * sin_a + sh * cos_a))
        return bw, bh

    def _get_transformed_image(self) -> Image.Image:
        if not self._cache_dirty and self._transformed_image is not None:
            return self._transformed_image

        img = self.source_image
        sw = int(self.src_w * self.img_scale)
        sh = int(self.src_h * self.img_scale)
        if sw < 8:
            sw = 8
        if sh < 8:
            sh = 8
        img = img.resize((sw, sh), Image.LANCZOS)

        if abs(self.img_rotation) >= 0.01:
            img_rgba = img.convert('RGBA')
            img_rgba = img_rgba.rotate(-self.img_rotation, resample=Image.BICUBIC,
                                       expand=True, fillcolor=(0, 0, 0, 0))
            self._rotated_alpha = np.array(img_rgba)[:, :, 3]
            img = img_rgba
        else:
            self._rotated_alpha = None

        self._transformed_image = img
        self._transformed_w, self._transformed_h = img.size
        self._cache_dirty = False
        return img

    def _invalidate_cache(self):
        self._cache_dirty = True

    # ── UI 초기화 ────────────────────────────────────────────

    def _init_ui(self):
        self.setWindowTitle("Comic Panel Setup")
        self.setMinimumSize(900, 700)
        self.resize(1000, 750)
        self.setStyleSheet(f"background-color: {DARK_COLORS['bg_secondary']};")
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 10, 12, 10)
        main_layout.setSpacing(6)

        # Row 1: 캔버스 크기 + 프리셋
        main_layout.addWidget(self._create_size_bar())

        # Row 2: 이미지 스케일 + 회전 + 크롭
        main_layout.addWidget(self._create_transform_bar())

        # 캔버스 프리뷰
        self.scene = QGraphicsScene()
        self.view = QGraphicsView(self.scene)
        self.view.setStyleSheet(f"""
            QGraphicsView {{
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                background-color: #1a1a2e;
            }}
        """)
        self.view.setRenderHints(self.view.renderHints())
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        main_layout.addWidget(self.view, 1)
        self.view.viewport().installEventFilter(self)

        # 하단 바
        main_layout.addWidget(self._create_bottom_bar())

    # ── 상단 바: 캔버스 크기 ────────────────────────────────

    def _create_size_bar(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        lbl_style = f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(13)}px;"
        spinbox_style = f"""
            QSpinBox {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 3px;
                padding: 3px 6px;
                font-size: {get_scaled_font_size(13)}px;
                min-width: 70px;
            }}
            QSpinBox::up-button, QSpinBox::down-button {{
                width: 14px;
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
            }}
        """

        lbl = QLabel("Canvas:")
        lbl.setStyleSheet(lbl_style)
        layout.addWidget(lbl)

        self.width_spinbox = QSpinBox()
        self.width_spinbox.setRange(64, 2048)
        self.width_spinbox.setSingleStep(64)
        self.width_spinbox.setValue(self.canvas_width)
        self.width_spinbox.setStyleSheet(spinbox_style)
        self.width_spinbox.valueChanged.connect(self._on_size_changed)
        layout.addWidget(self.width_spinbox)

        layout.addWidget(self._styled_label("x", lbl_style))

        self.height_spinbox = QSpinBox()
        self.height_spinbox.setRange(64, 2048)
        self.height_spinbox.setSingleStep(64)
        self.height_spinbox.setValue(self.canvas_height)
        self.height_spinbox.setStyleSheet(spinbox_style)
        self.height_spinbox.valueChanged.connect(self._on_size_changed)
        layout.addWidget(self.height_spinbox)

        self.pixel_label = QLabel()
        self.pixel_label.setStyleSheet(
            f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(12)}px;")
        self._update_pixel_label()
        layout.addWidget(self.pixel_label)

        layout.addStretch()

        # 프리셋 버튼 (코믹 패널용)
        presets = [
            ("2:1", 1408, 704),
            ("1:2", 704, 1408),
            ("3:2", 1216, 832),
            ("2:3", 832, 1216),
            ("1:1", 1024, 1024),
        ]
        for name, pw, ph in presets:
            btn = QPushButton(name)
            btn.setStyleSheet(DARK_STYLES['secondary_button'])
            btn.setMinimumWidth(get_scaled_size(45))
            btn.clicked.connect(lambda _, w=pw, h=ph: self._apply_preset(w, h))
            layout.addWidget(btn)

        return widget

    def _styled_label(self, text: str, style: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(style)
        return lbl

    # ── 변환 바: 스케일 + 회전 + 크롭 ──────────────────────

    def _create_transform_bar(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        lbl_style = f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(13)}px;"
        slider_style = DARK_STYLES.get('compact_slider', '')

        # ── Scale 슬라이더 ──
        layout.addWidget(self._styled_label("Scale:", lbl_style))

        self.scale_slider = QSlider(Qt.Orientation.Horizontal)
        self.scale_slider.setRange(10, 200)
        self.scale_slider.setValue(100)
        self.scale_slider.setStyleSheet(slider_style)
        self.scale_slider.setFixedWidth(get_scaled_size(160))
        self.scale_slider.valueChanged.connect(self._on_scale_changed)
        layout.addWidget(self.scale_slider)

        self.scale_value_label = QLabel("100%")
        self.scale_value_label.setStyleSheet(lbl_style)
        self.scale_value_label.setFixedWidth(get_scaled_size(45))
        layout.addWidget(self.scale_value_label)

        # Fit 버튼
        fit_btn = QPushButton("Fit")
        fit_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        fit_btn.setFixedWidth(get_scaled_size(45))
        fit_btn.clicked.connect(self._fit_to_canvas)
        layout.addWidget(fit_btn)

        layout.addWidget(self._styled_label("  ", lbl_style))

        # ── Rotation 슬라이더 ──
        layout.addWidget(self._styled_label("Rotate:", lbl_style))

        self.rotation_slider = QSlider(Qt.Orientation.Horizontal)
        self.rotation_slider.setRange(-180, 180)
        self.rotation_slider.setValue(0)
        self.rotation_slider.setStyleSheet(slider_style)
        self.rotation_slider.setFixedWidth(get_scaled_size(140))
        self.rotation_slider.valueChanged.connect(self._on_rotation_changed)
        layout.addWidget(self.rotation_slider)

        self.rotation_value_label = QLabel("0°")
        self.rotation_value_label.setStyleSheet(lbl_style)
        self.rotation_value_label.setFixedWidth(get_scaled_size(40))
        layout.addWidget(self.rotation_value_label)

        reset_btn = QPushButton("0°")
        reset_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        reset_btn.setFixedWidth(get_scaled_size(35))
        reset_btn.clicked.connect(lambda: self.rotation_slider.setValue(0))
        layout.addWidget(reset_btn)

        layout.addStretch()

        # ── Crop 버튼 ──
        self.crop_btn = QPushButton("Crop")
        self.crop_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.crop_btn.setFixedWidth(get_scaled_size(55))
        self.crop_btn.clicked.connect(self._toggle_crop_mode)
        layout.addWidget(self.crop_btn)

        self.reset_crop_btn = QPushButton("Reset Crop")
        self.reset_crop_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.reset_crop_btn.setFixedWidth(get_scaled_size(85))
        self.reset_crop_btn.clicked.connect(self._reset_crop)
        self.reset_crop_btn.setEnabled(False)
        layout.addWidget(self.reset_crop_btn)

        return widget

    # ── 하단 바: 위치 + 버튼 ────────────────────────────────

    def _create_bottom_bar(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(8)

        info_style = f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(12)}px;"
        self.position_label = QLabel()
        self.position_label.setStyleSheet(info_style)
        self._update_position_label()
        layout.addWidget(self.position_label)

        layout.addStretch()

        btn_min_w = get_scaled_size(80)

        center_btn = QPushButton("Center")
        center_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        center_btn.setMinimumWidth(btn_min_w)
        center_btn.clicked.connect(self._center_image)
        layout.addWidget(center_btn)

        align_btn = QPushButton("Align")
        align_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        align_btn.setMinimumWidth(btn_min_w)
        align_btn.clicked.connect(self._align_and_update)
        layout.addWidget(align_btn)

        accept_btn = QPushButton("Accept")
        accept_btn.setStyleSheet(DARK_STYLES['primary_button'])
        accept_btn.setMinimumWidth(btn_min_w)
        accept_btn.clicked.connect(self.accept)
        layout.addWidget(accept_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        cancel_btn.setMinimumWidth(btn_min_w)
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(cancel_btn)

        return widget

    # ── 상태 업데이트 ─────────────────────────────────────

    def _update_pixel_label(self):
        total = self.canvas_width * self.canvas_height
        mp = total / 1_000_000
        color = "#ff6666" if total > self.MAX_PIXELS else DARK_COLORS['text_secondary']
        self.pixel_label.setText(f"({mp:.2f}MP)")
        self.pixel_label.setStyleSheet(
            f"color: {color}; font-size: {get_scaled_font_size(12)}px;")

    def _update_position_label(self):
        tw, th = self._get_transformed_size()
        mode_text = "[CROP]" if self._interaction_mode == self.MODE_CROP else ""
        self.position_label.setText(
            f"{mode_text}  Pos: ({self.img_x}, {self.img_y})  |  "
            f"Image: {tw}x{th}  |  "
            f"Scale: {self.img_scale:.0%}  Rot: {self.img_rotation:.0f}°")

    # ── 이벤트 핸들러 ──────────────────────────────────────

    def _on_size_changed(self):
        w = self._round_to_64(self.width_spinbox.value())
        h = self._round_to_64(self.height_spinbox.value())
        self.width_spinbox.blockSignals(True)
        self.height_spinbox.blockSignals(True)
        self.width_spinbox.setValue(w)
        self.height_spinbox.setValue(h)
        self.width_spinbox.blockSignals(False)
        self.height_spinbox.blockSignals(False)
        self.canvas_width = w
        self.canvas_height = h
        self._update_pixel_label()
        self._fit_and_align()

    def _apply_preset(self, width: int, height: int):
        self.width_spinbox.setValue(width)
        self.height_spinbox.setValue(height)

    def _on_scale_changed(self, value: int):
        self.img_scale = value / 100.0
        self.scale_value_label.setText(f"{value}%")
        self._invalidate_cache()
        self._clamp_image_position()
        self._update_canvas_preview()

    def _on_rotation_changed(self, value: int):
        self.img_rotation = float(value)
        self.rotation_value_label.setText(f"{value}°")
        self._invalidate_cache()
        self._clamp_image_position()
        self._update_canvas_preview()

    def _fit_and_align(self):
        """이미지를 캔버스에 맞게 스케일 조정하고 좌측/위쪽 정렬합니다."""
        # 이미지가 캔버스의 연속면을 완전히 채우도록 스케일 계산
        # (2koma: 세로 캔버스 → 너비 일치, 가로 캔버스 → 높이 일치)
        if self.src_w > self.src_h:
            # 가로 이미지 + 세로 캔버스: 너비를 캔버스에 맞춤
            fit_scale = self.canvas_width / self.src_w
        else:
            # 세로 이미지 + 가로 캔버스: 높이를 캔버스에 맞춤
            fit_scale = self.canvas_height / self.src_h
        # ceil로 올림하여 빈 공간 방지 (미세한 오버플로우는 클리핑)
        pct = max(10, min(200, math.ceil(fit_scale * 100)))
        self.scale_slider.setValue(pct)
        self._align_image()
        self._update_position_label()
        self._update_canvas_preview()

    def _fit_to_canvas(self):
        self._fit_and_align()

    def _center_image(self):
        tw, th = self._get_transformed_size()
        self.img_x = self._snap_to_grid((self.canvas_width - tw) // 2)
        self.img_y = self._snap_to_grid((self.canvas_height - th) // 2)
        self._update_position_label()
        self._update_canvas_preview()

    def _align_and_update(self):
        """Align 버튼: 좌측/위쪽 정렬로 재배치"""
        self._align_image()
        self._update_position_label()
        self._update_canvas_preview()

    def _clamp_image_position(self):
        tw, th = self._get_transformed_size()
        min_vis = 32
        self.img_x = max(-tw + min_vis, min(self.canvas_width - min_vis, self.img_x))
        self.img_y = max(-th + min_vis, min(self.canvas_height - min_vis, self.img_y))
        self.img_x = self._snap_to_grid(self.img_x)
        self.img_y = self._snap_to_grid(self.img_y)

    # ── 크롭 기능 ─────────────────────────────────────────

    def _toggle_crop_mode(self):
        if self._interaction_mode == self.MODE_CROP:
            self._exit_crop_mode()
        else:
            self._enter_crop_mode()

    def _enter_crop_mode(self):
        self._interaction_mode = self.MODE_CROP
        self._crop_rect = QRectF()
        self.crop_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.crop_btn.setText("Apply Crop")
        self._update_crop_preview()

    def _exit_crop_mode(self):
        """크롭 모드 종료: 선택 영역이 있으면 적용"""
        if not self._crop_rect.isNull() and self._crop_rect.width() > 10 and self._crop_rect.height() > 10:
            self._apply_crop()
        self._interaction_mode = self.MODE_NORMAL
        self.crop_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.crop_btn.setText("Crop")
        self._update_canvas_preview()

    def _apply_crop(self):
        """선택된 크롭 영역을 적용합니다."""
        if self._crop_rect.isNull():
            return

        # scene 좌표 → 이미지 픽셀 좌표 변환
        x = max(0, int(self._crop_rect.x()))
        y = max(0, int(self._crop_rect.y()))
        r = min(self._original_uncropped.width, int(self._crop_rect.x() + self._crop_rect.width()))
        b = min(self._original_uncropped.height, int(self._crop_rect.y() + self._crop_rect.height()))

        if r - x < 16 or b - y < 16:
            return  # 너무 작은 크롭 무시

        self.source_image = self._original_uncropped.crop((x, y, r, b)).convert('RGB')
        self.src_w, self.src_h = self.source_image.size
        self._is_cropped = True
        self.reset_crop_btn.setEnabled(True)
        self._invalidate_cache()
        self._crop_rect = QRectF()
        self._fit_and_align()

    def _reset_crop(self):
        """원본 이미지로 복원합니다."""
        if not self._is_cropped:
            return
        self.source_image = self._original_uncropped.copy()
        self.src_w, self.src_h = self.source_image.size
        self._is_cropped = False
        self.reset_crop_btn.setEnabled(False)
        self._invalidate_cache()
        self._fit_and_align()

    # ── 크롭 프리뷰 ───────────────────────────────────────

    def _update_crop_preview(self):
        """크롭 모드: 원본 이미지 전체 + 선택 영역 표시"""
        self.scene.clear()
        self._update_position_label()

        img = self._original_uncropped
        iw, ih = img.size

        # 원본 이미지 표시
        qimage = ImageQt(img.convert("RGBA"))
        pixmap = QPixmap.fromImage(qimage)
        self.scene.addItem(QGraphicsPixmapItem(pixmap))

        # 어두운 오버레이 (전체)
        overlay = QGraphicsRectItem(0, 0, iw, ih)
        overlay.setBrush(QBrush(QColor(0, 0, 0, 120)))
        overlay.setPen(QPen(Qt.PenStyle.NoPen))
        self.scene.addItem(overlay)

        # 선택 영역 (밝게 표시)
        if not self._crop_rect.isNull() and self._crop_rect.width() > 0:
            # 선택 영역 내 이미지를 다시 밝게 표시
            sel = QGraphicsRectItem(self._crop_rect)
            sel.setBrush(QBrush(QColor(255, 255, 255, 120)))
            sel.setPen(QPen(QColor(255, 200, 50), 2, Qt.PenStyle.SolidLine))
            self.scene.addItem(sel)

            # 크롭 영역 크기 라벨
            cw = int(self._crop_rect.width())
            ch = int(self._crop_rect.height())
            size_text = self.scene.addText(f"{cw}x{ch}")
            size_text.setDefaultTextColor(QColor(255, 200, 50))
            size_text.setPos(self._crop_rect.x(), self._crop_rect.y() - 20)

        self.scene.setSceneRect(-20, -20, iw + 40, ih + 40)
        self.view.fitInView(QRectF(-20, -20, iw + 40, ih + 40),
                            Qt.AspectRatioMode.KeepAspectRatio)

    # ── 캔버스 프리뷰 ──────────────────────────────────────

    HANDLE_SIZE = 10

    def _update_canvas_preview(self):
        if self._interaction_mode == self.MODE_CROP:
            self._update_crop_preview()
            return

        self.scene.clear()
        self._update_position_label()

        tw, th = self._get_transformed_size()

        # 1. 흰 캔버스 배경
        canvas_rect = QGraphicsRectItem(0, 0, self.canvas_width, self.canvas_height)
        canvas_rect.setBrush(QBrush(QColor(255, 255, 255)))
        canvas_rect.setPen(QPen(QColor(100, 100, 100), 1))
        self.scene.addItem(canvas_rect)

        # 2. 마스크 오버레이 (파란 반투명)
        mask_overlay = QGraphicsRectItem(0, 0, self.canvas_width, self.canvas_height)
        mask_overlay.setBrush(QBrush(QColor(60, 80, 200, 80)))
        mask_overlay.setPen(QPen(Qt.PenStyle.NoPen))
        self.scene.addItem(mask_overlay)

        # 3. 변환된 이미지 표시
        transformed = self._get_transformed_image()
        qimage = ImageQt(transformed.convert("RGBA"))
        pixmap = QPixmap.fromImage(qimage)
        self._image_item = QGraphicsPixmapItem(pixmap)
        self._image_item.setPos(self.img_x, self.img_y)
        self.scene.addItem(self._image_item)

        # 4. 이미지 바운딩 박스 (노란 점선)
        border_rect = QGraphicsRectItem(self.img_x, self.img_y, tw, th)
        border_rect.setPen(QPen(QColor(255, 200, 50), 2, Qt.PenStyle.DashLine))
        border_rect.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        self.scene.addItem(border_rect)

        # 5. 리사이즈 핸들 (4 코너)
        hs = self.HANDLE_SIZE
        handle_corners = [
            (self.img_x, self.img_y),
            (self.img_x + tw, self.img_y),
            (self.img_x, self.img_y + th),
            (self.img_x + tw, self.img_y + th),
        ]
        for cx, cy in handle_corners:
            handle = QGraphicsRectItem(cx - hs / 2, cy - hs / 2, hs, hs)
            handle.setBrush(QBrush(QColor(255, 200, 50)))
            handle.setPen(QPen(QColor(200, 160, 30), 1))
            self.scene.addItem(handle)

        # Scene rect
        scene_margin = max(self.canvas_width, self.canvas_height) * 2
        self.scene.setSceneRect(
            -scene_margin, -scene_margin,
            self.canvas_width + scene_margin * 2,
            self.canvas_height + scene_margin * 2
        )

        view_margin = 40
        canvas_view_rect = QRectF(
            -view_margin, -view_margin,
            self.canvas_width + view_margin * 2,
            self.canvas_height + view_margin * 2
        )
        self.view.fitInView(canvas_view_rect, Qt.AspectRatioMode.KeepAspectRatio)

    # ── 핸들 히트 테스트 ──────────────────────────────────

    def _get_handle_at(self, scene_pos: QPointF) -> str | None:
        tw, th = self._get_transformed_size()
        corners = {
            'tl': QPointF(self.img_x, self.img_y),
            'tr': QPointF(self.img_x + tw, self.img_y),
            'bl': QPointF(self.img_x, self.img_y + th),
            'br': QPointF(self.img_x + tw, self.img_y + th),
        }
        hit_radius = self.HANDLE_SIZE + 4
        for name, corner in corners.items():
            diff = scene_pos - corner
            if abs(diff.x()) + abs(diff.y()) < hit_radius:
                return name
        return None

    # ── 마우스 이벤트 ─────────────────────────────────────

    def eventFilter(self, source, event: QEvent) -> bool:
        if source is not self.view.viewport():
            return super().eventFilter(source, event)

        # 크롭 모드 이벤트
        if self._interaction_mode == self.MODE_CROP:
            return self._handle_crop_event(event)

        # 노멀 모드 이벤트
        return self._handle_normal_event(event)

    def _handle_crop_event(self, event: QEvent) -> bool:
        """크롭 모드 마우스 이벤트 처리"""
        if event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                scene_pos = self.view.mapToScene(event.pos())
                self._crop_dragging = True
                self._crop_start = scene_pos
                self._crop_rect = QRectF(scene_pos, scene_pos)
                return True

        elif event.type() == QEvent.Type.MouseMove:
            if self._crop_dragging:
                scene_pos = self.view.mapToScene(event.pos())
                iw = self._original_uncropped.width
                ih = self._original_uncropped.height
                # 이미지 범위 내로 클램프
                sx = max(0, min(iw, self._crop_start.x()))
                sy = max(0, min(ih, self._crop_start.y()))
                ex = max(0, min(iw, scene_pos.x()))
                ey = max(0, min(ih, scene_pos.y()))
                x1, x2 = min(sx, ex), max(sx, ex)
                y1, y2 = min(sy, ey), max(sy, ey)
                self._crop_rect = QRectF(x1, y1, x2 - x1, y2 - y1)
                self._update_crop_preview()
                return True

        elif event.type() == QEvent.Type.MouseButtonRelease:
            if self._crop_dragging:
                self._crop_dragging = False
                return True

        return False

    def _handle_normal_event(self, event: QEvent) -> bool:
        """노멀 모드 마우스 이벤트 처리 (OutpaintWindow 동일)"""
        tw, th = self._get_transformed_size()
        img_rect = QRectF(self.img_x, self.img_y, tw, th)

        if event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                scene_pos = self.view.mapToScene(event.pos())

                handle = self._get_handle_at(scene_pos)
                if handle:
                    self._resizing = True
                    self._resize_corner = handle
                    self._resize_start_pos = scene_pos
                    self._resize_start_scale = self.img_scale
                    opposite = {'tl': 'br', 'tr': 'bl', 'bl': 'tr', 'br': 'tl'}
                    anchor_map = {
                        'tl': QPointF(self.img_x, self.img_y),
                        'tr': QPointF(self.img_x + tw, self.img_y),
                        'bl': QPointF(self.img_x, self.img_y + th),
                        'br': QPointF(self.img_x + tw, self.img_y + th),
                    }
                    self._resize_anchor = anchor_map[opposite[handle]]
                    cursor = (Qt.CursorShape.SizeFDiagCursor if handle in ('tl', 'br')
                              else Qt.CursorShape.SizeBDiagCursor)
                    self.view.setCursor(QCursor(cursor))
                    return True

                if img_rect.contains(scene_pos):
                    self._dragging = True
                    self._drag_start_pos = scene_pos
                    self._drag_start_img_x = self.img_x
                    self._drag_start_img_y = self.img_y
                    self.view.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
                    return True

        elif event.type() == QEvent.Type.MouseMove:
            scene_pos = self.view.mapToScene(event.pos())

            if self._resizing:
                start_dx = self._resize_start_pos.x() - self._resize_anchor.x()
                start_dy = self._resize_start_pos.y() - self._resize_anchor.y()
                start_dist = abs(start_dx) + abs(start_dy)
                cur_dx = scene_pos.x() - self._resize_anchor.x()
                cur_dy = scene_pos.y() - self._resize_anchor.y()
                cur_dist = abs(cur_dx) + abs(cur_dy)
                if start_dist > 1:
                    ratio = cur_dist / start_dist
                    new_scale = max(0.1, min(2.0, self._resize_start_scale * ratio))
                    pct = max(10, min(200, int(new_scale * 100)))
                    self.scale_slider.setValue(pct)
                return True

            if self._dragging:
                dx = scene_pos.x() - self._drag_start_pos.x()
                dy = scene_pos.y() - self._drag_start_pos.y()
                self.img_x = self._snap_to_grid(int(self._drag_start_img_x + dx))
                self.img_y = self._snap_to_grid(int(self._drag_start_img_y + dy))
                self._clamp_image_position()
                self._update_canvas_preview()
                return True

            handle = self._get_handle_at(scene_pos)
            if handle:
                cursor = (Qt.CursorShape.SizeFDiagCursor if handle in ('tl', 'br')
                          else Qt.CursorShape.SizeBDiagCursor)
                self.view.setCursor(QCursor(cursor))
            elif img_rect.contains(scene_pos):
                self.view.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
            else:
                self.view.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

        elif event.type() == QEvent.Type.MouseButtonRelease:
            if self._resizing:
                self._resizing = False
                self._resize_corner = None
                self.view.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
                return True
            if self._dragging:
                self._dragging = False
                self.view.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
                return True

        elif event.type() == QEvent.Type.Wheel:
            delta = event.angleDelta().y()
            step = 5 if delta > 0 else -5
            new_val = max(10, min(200, self.scale_slider.value() + step))
            self.scale_slider.setValue(new_val)
            return True

        return False

    # ── Accept: 캔버스/마스크 생성 ──────────────────────────

    def accept(self):
        # 크롭 모드라면 먼저 적용
        if self._interaction_mode == self.MODE_CROP:
            self._exit_crop_mode()

        total_pixels = self.canvas_width * self.canvas_height
        if total_pixels > self.MAX_PIXELS:
            print(f"Comic Panel: canvas {self.canvas_width}x{self.canvas_height} "
                  f"({total_pixels}px) exceeds 1MP")

        transformed = self._get_transformed_image()
        tw, th = transformed.size

        # 1. 캔버스 생성
        canvas = Image.new('RGB', (self.canvas_width, self.canvas_height), (255, 255, 255))
        if transformed.mode == 'RGBA':
            canvas.paste(transformed, (self.img_x, self.img_y), transformed)
        else:
            canvas.paste(transformed, (self.img_x, self.img_y))

        # 2. 풀사이즈 마스크 (흰=채움, 검=보존)
        mask_array = np.full((self.canvas_height, self.canvas_width), 255, dtype=np.uint8)

        if abs(self.img_rotation) >= 0.01 and self._rotated_alpha is not None:
            alpha = self._rotated_alpha
            x_start = max(0, self.img_x)
            y_start = max(0, self.img_y)
            x_end = min(self.canvas_width, self.img_x + tw)
            y_end = min(self.canvas_height, self.img_y + th)

            if x_end > x_start and y_end > y_start:
                crop_x = x_start - self.img_x
                crop_y = y_start - self.img_y
                alpha_crop = alpha[crop_y:crop_y + (y_end - y_start),
                                   crop_x:crop_x + (x_end - x_start)]
                mask_array[y_start:y_end, x_start:x_end] = np.where(
                    alpha_crop > 127, 0, 255).astype(np.uint8)
        else:
            x_start = max(0, self.img_x)
            y_start = max(0, self.img_y)
            x_end = min(self.canvas_width, self.img_x + tw)
            y_end = min(self.canvas_height, self.img_y + th)

            if x_end > x_start and y_end > y_start:
                mask_array[y_start:y_end, x_start:x_end] = 0

        # 블렌딩 보더
        border = 8
        try:
            from scipy import ndimage
            kernel = np.ones((border * 2 + 1, border * 2 + 1), dtype=np.uint8)
            dilated = ndimage.binary_dilation(
                mask_array == 255, kernel).astype(np.uint8) * 255
            mask_array = dilated
        except ImportError:
            pass

        full_mask = Image.fromarray(mask_array, mode='L')

        # 3. 1/8 축소 마스크
        small_w = self.canvas_width // 8
        small_h = self.canvas_height // 8
        small_mask = full_mask.resize((small_w, small_h), Image.NEAREST)
        small_arr = np.array(small_mask)
        small_arr = np.where(small_arr > 127, 255, 0).astype(np.uint8)
        small_mask = Image.fromarray(small_arr, mode='L')

        self.result = {
            "canvas_image": canvas,
            "full_mask_image": full_mask,
            "small_mask_image": small_mask,
            "canvas_width": self.canvas_width,
            "canvas_height": self.canvas_height,
        }

        print(f"Comic Panel: {self.canvas_width}x{self.canvas_height}, "
              f"pos=({self.img_x},{self.img_y}), "
              f"scale={self.img_scale:.0%}, rot={self.img_rotation:.0f}°")

        super().accept()

    # ── 정적 팩토리 ──────────────────────────────────────────

    @staticmethod
    def get_comic_panel_data(pil_image: Image.Image, parent=None) -> dict | None:
        dialog = ComicPanelWindow(pil_image, parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.result
        return None
