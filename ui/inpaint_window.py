import io
from PIL import Image, ImageDraw
from PIL.ImageQt import ImageQt
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
                             QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QSlider, QWidget)
from PyQt6.QtGui import QPixmap, QPainter, QColor, QPen
from PyQt6.QtCore import Qt, QPointF, QEvent, QBuffer, QIODevice, QRectF
import numpy as np
from .theme import DARK_STYLES, DARK_COLORS

class InpaintWindow(QDialog):
    def __init__(self, pil_image: Image.Image, initial_mask: Image.Image = None, parent=None):
        super().__init__(parent)
        self.original_pil_image = pil_image
        self.result = None

        self.background_pixmap = QPixmap.fromImage(ImageQt(self.original_pil_image.convert("RGBA")))

        # 🔥 핵심 수정: 기존과 동일한 격자 시스템 사용
        w, h = self.original_pil_image.size
        self.mirror_width = w // 8
        self.mirror_height = h // 8
        # 2D 정수 배열 (기존 NAIA_old_i2i.py와 완전 동일)
        self.mirror_image = [[0 for _ in range(self.mirror_height)] for _ in range(self.mirror_width)]
        
        # 기존 마스크가 있다면 격자 시스템으로 변환
        if initial_mask:
            self._convert_mask_to_grid(initial_mask)
        
        # 표시용 알파 레이어 (UI 전용)
        self.alpha_layer_image = Image.new("L", (w, h), 0)
        self._update_display_from_grid()  # 격자 → 표시용 이미지 변환

        self.composite_pixmap = QPixmap(self.background_pixmap.size())
        self.composite_pixmap.fill(Qt.GlobalColor.transparent)

        self.brush_size = 50
        self.brush_shape = 'Square'
        self.last_paint_pos: QPointF = None
        
        self.init_ui()
        self._update_composite_display()

    def _convert_mask_to_grid(self, mask_image: Image.Image):
        """기존 마스크를 격자 시스템으로 변환"""
        mask_array = np.array(mask_image.convert("L"))
        h, w = mask_array.shape
        
        for gx in range(self.mirror_width):
            for gy in range(self.mirror_height):
                # 8x8 블록의 평균값 확인
                y1, y2 = gy * 8, min((gy + 1) * 8, h)
                x1, x2 = gx * 8, min((gx + 1) * 8, w)
                
                block_avg = np.mean(mask_array[y1:y2, x1:x2])
                if block_avg > 127:
                    self.mirror_image[gx][gy] = 1

    def _update_display_from_grid(self):
        """격자 데이터를 바탕으로 표시용 이미지 업데이트 (완전 스무싱 방지)"""
        w, h = self.original_pil_image.size
        
        # 🔥 핵심 수정: numpy를 사용하여 완벽한 이진 마스크 생성
        alpha_array = np.zeros((h, w), dtype=np.uint8)
        
        # 격자 데이터를 직접 배열에 복사 (PIL 그리기 함수 사용 안함)
        for gx in range(self.mirror_width):
            for gy in range(self.mirror_height):
                if self.mirror_image[gx][gy] > 0:
                    y1, y2 = gy * 8, min((gy + 1) * 8, h)
                    x1, x2 = gx * 8, min((gx + 1) * 8, w)
                    # 직접 배열 할당으로 완벽한 255 값 보장
                    alpha_array[y1:y2, x1:x2] = 255
        
        # numpy 배열에서 PIL 이미지로 변환
        self.alpha_layer_image = Image.fromarray(alpha_array, mode='L')

    def init_ui(self):
        self.setWindowTitle("Inpaint Image")
        self.setMinimumSize(800, 600)
        self.setStyleSheet(f"background-color: {DARK_COLORS['bg_secondary']};")
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        top_bar = self._create_top_bar()
        main_layout.addWidget(top_bar)
        
        self.scene = QGraphicsScene()
        self.view = QGraphicsView(self.scene)
        self.view.setStyleSheet("border-radius: 4px;")
        main_layout.addWidget(self.view)
        self.view.viewport().installEventFilter(self)
        
        # 배경과 합성 이미지만 표시
        self.bg_item = QGraphicsPixmapItem(self.background_pixmap)
        self.composite_item = QGraphicsPixmapItem()
        self.scene.addItem(self.bg_item)
        self.scene.addItem(self.composite_item)
        
        self.scene.setSceneRect(self.background_pixmap.rect().toRectF())
        self.resize(self.original_pil_image.width + 40, self.original_pil_image.height + 100)

    def _create_top_bar(self) -> QWidget:
        top_widget = QWidget()
        layout = QHBoxLayout(top_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        pen_size_label = QLabel("Pen Size:")
        self.pen_size_value_label = QLabel(f"{self.brush_size}")
        self.pen_size_slider = QSlider(Qt.Orientation.Horizontal)
        self.pen_size_slider.setRange(8, 160)  # 8픽셀 단위로 조정
        self.pen_size_slider.setValue(self.brush_size)
        self.pen_size_slider.valueChanged.connect(self._update_brush_size)
        self.pen_size_slider.setStyleSheet(DARK_STYLES['compact_slider'])
        
        self.shape_button = QPushButton("Square Brush")
        self.shape_button.setCheckable(True)
        self.shape_button.toggled.connect(self._toggle_brush_shape)
        self.shape_button.setStyleSheet(DARK_STYLES['secondary_button'])
        
        layout.addWidget(pen_size_label)
        layout.addWidget(self.pen_size_value_label)
        layout.addWidget(self.pen_size_slider)
        layout.addWidget(self.shape_button)
        layout.addStretch()
        
        save_button = QPushButton("Save Image")
        save_button.setStyleSheet(DARK_STYLES['primary_button'])
        save_button.clicked.connect(self.accept)
        
        close_button = QPushButton("X")
        close_button.setStyleSheet(DARK_STYLES['secondary_button'])
        close_button.clicked.connect(self.reject)
        
        layout.addWidget(save_button)
        layout.addWidget(close_button)
        return top_widget

    def _update_brush_size(self, value):
        # 8의 배수로 정렬
        aligned_value = (value // 8) * 8
        if aligned_value < 8:
            aligned_value = 8
        
        self.brush_size = aligned_value
        self.pen_size_value_label.setText(str(aligned_value))
        self.pen_size_slider.setValue(aligned_value)

    def _toggle_brush_shape(self, checked):
        if checked:
            self.brush_shape = 'Circle'
            self.shape_button.setText("Circle Brush")
        else:
            self.brush_shape = 'Square'
            self.shape_button.setText("Square Brush")

    def eventFilter(self, source, event: QEvent) -> bool:
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
        """🔥 핵심 수정: 기존 격자 시스템과 완전 동일한 페인팅"""
        scene_pos = self.view.mapToScene(pos.toPoint() if isinstance(pos, QPointF) else pos)
        img_x, img_y = int(scene_pos.x()), int(scene_pos.y())
        
        # 🔥 격자 좌표로 변환 (기존과 동일)
        grid_x, grid_y = img_x // 8, img_y // 8
        
        if not (0 <= grid_x < self.mirror_width and 0 <= grid_y < self.mirror_height):
            return
        
        # 브러시 크기를 격자 단위로 변환
        brush_size_grid = max(1, self.brush_size // 8)
        
        # 🔥 기존 paint_on_image 함수와 완전 동일한 로직
        half_brush = brush_size_grid // 2
        
        # 이전 지점과 현재 지점을 연결하여 부드러운 드로잉 (격자 단위)
        if self.last_paint_pos:
            last_scene_pos = self.view.mapToScene(self.last_paint_pos.toPoint() if isinstance(self.last_paint_pos, QPointF) else self.last_paint_pos)
            last_grid_x, last_grid_y = int(last_scene_pos.x()) // 8, int(last_scene_pos.y()) // 8
            
            # 두 점 사이의 격자 점들을 연결
            self._draw_grid_line(last_grid_x, last_grid_y, grid_x, grid_y, half_brush, erase)
        
        # 현재 위치에 브러시 적용
        self._apply_brush_to_grid(grid_x, grid_y, half_brush, erase)
        
        # 표시용 이미지 업데이트
        self._update_display_from_grid()
        self._update_composite_display()
        self.last_paint_pos = pos

    def _draw_grid_line(self, x0: int, y0: int, x1: int, y1: int, brush_radius: int, erase: bool):
        """두 격자 점 사이를 연결하는 선 그리기"""
        # Bresenham's line algorithm (격자 버전)
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
        """격자에 브러시 적용 (기존과 완전 동일)"""
        if self.brush_shape == 'Circle':
            # 원형 브러시 (격자 단위)
            for dx in range(-brush_radius, brush_radius + 1):
                for dy in range(-brush_radius, brush_radius + 1):
                    if dx * dx + dy * dy <= brush_radius * brush_radius:
                        gx, gy = center_x + dx, center_y + dy
                        if 0 <= gx < self.mirror_width and 0 <= gy < self.mirror_height:
                            self.mirror_image[gx][gy] = 0 if erase else 1
        else:
            # 사각형 브러시 (격자 단위)
            for dx in range(-brush_radius, brush_radius + 1):
                for dy in range(-brush_radius, brush_radius + 1):
                    gx, gy = center_x + dx, center_y + dy
                    if 0 <= gx < self.mirror_width and 0 <= gy < self.mirror_height:
                        self.mirror_image[gx][gy] = 0 if erase else 1

    def _update_composite_display(self):
        """🔥 스무싱 방지: composite 대신 직접 픽셀 조작"""
        w, h = self.original_pil_image.size
        
        # 원본 이미지를 RGBA로 변환
        original_rgba = self.original_pil_image.convert('RGBA')
        original_array = np.array(original_rgba)
        
        # 알파 레이어를 마스크로 사용
        alpha_array = np.array(self.alpha_layer_image)
        
        # 직접 픽셀 조작으로 오버레이 적용 (완벽한 이진 처리)
        result_array = original_array.copy()
        mask_indices = alpha_array == 255  # 완벽히 255인 픽셀만 선택
        
        # 마스크 영역을 파란색으로 오버레이 (알파 블렌딩)
        blue_color = np.array([0, 0, 255, 120], dtype=np.uint8)
        original_alpha = result_array[mask_indices, 3].astype(np.float32) / 255.0
        overlay_alpha = 120 / 255.0
        
        # 알파 합성 공식 적용
        combined_alpha = overlay_alpha + original_alpha * (1 - overlay_alpha)
        result_array[mask_indices, 0] = (blue_color[0] * overlay_alpha + 
                                        result_array[mask_indices, 0] * original_alpha * (1 - overlay_alpha)) / combined_alpha
        result_array[mask_indices, 1] = (blue_color[1] * overlay_alpha + 
                                        result_array[mask_indices, 1] * original_alpha * (1 - overlay_alpha)) / combined_alpha
        result_array[mask_indices, 2] = (blue_color[2] * overlay_alpha + 
                                        result_array[mask_indices, 2] * original_alpha * (1 - overlay_alpha)) / combined_alpha
        result_array[mask_indices, 3] = combined_alpha * 255
        
        # 결과를 PIL 이미지로 변환
        composite_image = Image.fromarray(result_array.astype(np.uint8), 'RGBA')
        
        # QPixmap으로 변환하여 화면 아이템 업데이트
        self.composite_pixmap = QPixmap.fromImage(ImageQt(composite_image))
        self.composite_item.setPixmap(self.composite_pixmap)

    def accept(self):
        """🔥 완전 수정: numpy 직접 조작으로 완벽한 이진 마스크 생성"""
        w, h = self.original_pil_image.size
        
        # 🔥 numpy를 사용하여 완벽한 마스크 생성 (PIL 함수 사용 안함)
        full_mask_array = np.zeros((h, w), dtype=np.uint8)
        small_mask_array = np.zeros((self.mirror_height, self.mirror_width), dtype=np.uint8)
        
        # 격자 데이터를 직접 배열에 복사
        for gx in range(self.mirror_width):
            for gy in range(self.mirror_height):
                if self.mirror_image[gx][gy] > 0:
                    # Full mask: 8x8 블록 채우기
                    y1, y2 = gy * 8, min((gy + 1) * 8, h)
                    x1, x2 = gx * 8, min((gx + 1) * 8, w)
                    full_mask_array[y1:y2, x1:x2] = 255
                    
                    # Small mask: 단일 픽셀
                    small_mask_array[gy, gx] = 255
        
        # numpy 배열을 PIL 이미지로 변환
        full_mask_image = Image.fromarray(full_mask_array, mode='L')
        small_mask_image = Image.fromarray(small_mask_array, mode='L')
        
        # 픽셀 수 체크
        painted_pixels_count = sum(sum(row) for row in self.mirror_image)
        
        if painted_pixels_count < 8:
            print("🎨 마스크 블록 수가 8 미만입니다. Img2Img 모드로 전환합니다.")
            self.result = {"original_image": self.original_pil_image}
            super().accept()
            return
        
        # 🔥 스무싱 방지: 직접 픽셀 조작으로 프리뷰 생성
        original_rgba = self.original_pil_image.convert('RGBA')
        original_array = np.array(original_rgba)
        
        # 마스크 영역만 파란색으로 변경
        preview_array = original_array.copy()
        mask_indices = full_mask_array == 255
        preview_array[mask_indices] = [0, 0, 255, 120]  # 완전한 파란색
        
        preview_image = Image.fromarray(preview_array, 'RGBA')
        
        self.result = {
            "full_mask_image": full_mask_image,
            "small_mask_image": small_mask_image,
            "original_image": self.original_pil_image,
            "preview_image": preview_image
        }
        
        print("✅ 완벽한 이진 마스크 생성 완료 (모든 스무싱 제거)")
        print(f"📊 마스크 통계: {painted_pixels_count}개 블록")
        print(f"🔍 마스크 검증: Full={np.sum(full_mask_array > 0)}, Small={np.sum(small_mask_array > 0)}")
        
        # 마스크 순수성 검증
        unique_values = np.unique(full_mask_array)
        print(f"🎯 마스크 값 검증: {unique_values} (0과 255만 있어야 함)")
        
        super().accept()

    def wheelEvent(self, event):
        """마우스 휠 이벤트로 브러시 크기를 조절합니다."""
        delta = event.angleDelta().y()
        
        # 8픽셀 단위로 조정
        if delta > 0:
            new_size = min(160, self.brush_size + 8)
            self.pen_size_slider.setValue(new_size)
        elif delta < 0:
            new_size = max(8, self.brush_size - 8)
            self.pen_size_slider.setValue(new_size)
            
        event.accept()

    @staticmethod
    def get_inpaint_data(pil_image: Image.Image, initial_mask: Image.Image = None, parent=None, auto_accept: bool = False) -> dict | None:
        dialog = InpaintWindow(pil_image, initial_mask, parent)
        
        # If auto_accept is True, immediately accept with the provided mask
        if auto_accept and initial_mask is not None:
            # Directly call accept to process the mask
            dialog.accept()
            return dialog.result
        
        result_code = dialog.exec()

        if result_code == QDialog.DialogCode.Accepted:
            return dialog.result
        return None