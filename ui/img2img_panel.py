import io
import random
from PIL import Image
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QDoubleSpinBox, QFrame, QSlider, QCheckBox,
                             QMessageBox, QProgressDialog)
from PyQt6.QtGui import QPixmap, QPainter, QColor
from PyQt6.QtCore import Qt, QSize, QThread, pyqtSignal
from PIL.ImageQt import ImageQt
import numpy as np
from .theme import DARK_STYLES, DARK_COLORS
from .inpaint_window import InpaintWindow
from core.context import AppContext
from ui.scaling_manager import get_scaled_font_size

class Img2ImgPanel(QFrame):
    """
    Img2Img UI를 위한 커스텀 패널 (슬라이더 및 이미지 크롭 적용).
    """
    def __init__(self, app_context: AppContext, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        
        # [2단계] 상태 관리 변수 추가
        self.mode = 'img2img'  # 'img2img' 또는 'inpaint'
        self.original_pil_image: Image.Image = None
        self.background_pixmap: QPixmap = None
        self.full_mask_pil: Image.Image = None
        self.small_mask_pil: Image.Image = None
        self._mask_preset = False  # Flag to indicate if mask was preset from sketchbook
        self._mask_from_sketchbook = False  # Additional flag for sketchbook source
        self._outpaint_data = None  # OutpaintWindow에서 설정된 데이터
        
        self.init_ui()
        self.setVisible(False)

    def init_ui(self):
        self.setStyleSheet(f"""
            Img2ImgPanel {{
                background-color: transparent;
                border: 1px solid {DARK_COLORS['border_light']};
                border-radius: 8px;
            }}
        """)
        self.setMinimumHeight(280)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 15, 20, 15)
        main_layout.setSpacing(15)

        # 상단: 타이틀 + 닫기 버튼
        header_layout = QHBoxLayout()
        self.title_label = QLabel("Image2Image & Inpaint")
        self.title_label.setStyleSheet(f"font-size: {get_scaled_font_size(24)}px; font-weight: 600; color: white; background-color: transparent;")

        subtitle_label = QLabel("Transform your image.")
        subtitle_label.setStyleSheet(f"font-size: {get_scaled_font_size(14)}px; color: #CCCCCC; background-color: transparent;")

        title_vbox = QVBoxLayout()
        title_vbox.addWidget(self.title_label)
        title_vbox.addWidget(subtitle_label)

        close_button = QPushButton("X")
        close_button.setFixedSize(48, 24)
        close_button.setStyleSheet("QPushButton { border-radius: 12px; background-color: #555; color: white; font-weight: bold; } QPushButton:hover { background-color: #777; }")
        close_button.clicked.connect(self.hide_panel)

        header_layout.addLayout(title_vbox)
        header_layout.addStretch()
        header_layout.addWidget(close_button, alignment=Qt.AlignmentFlag.AlignTop)
        main_layout.addLayout(header_layout)

        # 중앙: 파라미터 컨트롤 (슬라이더)
        controls_layout = QVBoxLayout()
        controls_layout.setSpacing(15)

        # [수정] 일관된 슬라이더 스타일 정의
        slider_style = f"""
            QSlider::groove:horizontal {{
                background: #22253F;
                height: 12px;
                border-radius: 4px;
            }}
            QSlider::handle:horizontal {{
                background: #F5F3C2;
                width: 18px;  /* 사각 형태를 위해 너비 조정 */
                height: 18px;
                margin: -4px 0;
                border-radius: 2px; /* 모서리가 둥근 사각형 */
            }}
            QSlider::handle:horizontal:hover {{
                background: {DARK_COLORS['accent_blue_hover']};
            }}
            QSlider::sub-page:horizontal {{
                background: #525252;
                border-radius: 4px;
            }}
        """

        # Strength
        strength_group = QWidget()
        strength_hlayout = QHBoxLayout(strength_group)
        strength_hlayout.setContentsMargins(0, 0, 0, 0)
        strength_label = QLabel("Strength:")
        strength_label.setStyleSheet(f"font-size: {get_scaled_font_size(16)}px; color: white; background-color: transparent;")
        self.strength_value_label = QLabel("0.50")
        self.strength_value_label.setStyleSheet(f"font-size: {get_scaled_font_size(16)}px; color: #AAA; min-width: 40px; text-align: right; background-color: transparent;")
        self.strength_slider = QSlider(Qt.Orientation.Horizontal)
        self.strength_slider.setRange(1, 99)
        self.strength_slider.setValue(50)
        self.strength_slider.setStyleSheet(slider_style) # [수정] 스타일 적용
        self.strength_slider.valueChanged.connect(self._update_strength_label)
        strength_hlayout.addWidget(strength_label)
        strength_hlayout.addWidget(self.strength_slider)
        strength_hlayout.addWidget(self.strength_value_label)
        controls_layout.addWidget(strength_group)

        # Noise
        noise_group = QWidget()
        noise_hlayout = QHBoxLayout(noise_group)
        noise_hlayout.setContentsMargins(0, 0, 0, 0)
        noise_label = QLabel("Noise:")
        noise_label.setStyleSheet(f"font-size: {get_scaled_font_size(16)}px; color: white; background-color: transparent;")
        self.noise_value_label = QLabel("0.05")
        self.noise_value_label.setStyleSheet(f"font-size: {get_scaled_font_size(16)}px; color: #AAA; min-width: 40px; text-align: right; background-color: transparent;")
        self.noise_slider = QSlider(Qt.Orientation.Horizontal)
        self.noise_slider.setRange(0, 99)
        self.noise_slider.setValue(5)
        self.noise_slider.setStyleSheet(slider_style) # [수정] 스타일 적용
        self.noise_slider.valueChanged.connect(self._update_noise_label)
        noise_hlayout.addWidget(noise_label)
        noise_hlayout.addWidget(self.noise_slider)
        noise_hlayout.addWidget(self.noise_value_label)
        controls_layout.addWidget(noise_group)

        # Auto-Outpainting checkbox (img2img 모드에서 표시)
        self.auto_outpainting_checkbox = QCheckBox("Auto-Outpainting")
        self.auto_outpainting_checkbox.setStyleSheet(f"""
            QCheckBox {{
                font-size: {get_scaled_font_size(16)}px;
                color: white;
                background-color: transparent;
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border: 2px solid #555;
                border-radius: 3px;
                background-color: #22253F;
            }}
            QCheckBox::indicator:checked {{
                background-color: {DARK_COLORS['accent_blue']};
                border-color: {DARK_COLORS['accent_blue']};
            }}
            QCheckBox::indicator:hover {{
                border-color: {DARK_COLORS['accent_blue_hover']};
            }}
        """)
        self.auto_outpainting_checkbox.setVisible(False)  # Hidden by default
        controls_layout.addWidget(self.auto_outpainting_checkbox)
        
        # Cropped image request checkbox (only visible in inpaint mode)
        self.cropped_image_checkbox = QCheckBox("Get only mask area image (no exif)")
        self.cropped_image_checkbox.setStyleSheet(f"""
            QCheckBox {{
                font-size: {get_scaled_font_size(16)}px;
                color: white;
                background-color: transparent;
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border: 2px solid #555;
                border-radius: 3px;
                background-color: #22253F;
            }}
            QCheckBox::indicator:checked {{
                background-color: {DARK_COLORS['accent_blue']};
                border-color: {DARK_COLORS['accent_blue']};
            }}
            QCheckBox::indicator:hover {{
                border-color: {DARK_COLORS['accent_blue_hover']};
            }}
        """)
        self.cropped_image_checkbox.setVisible(False)  # Hidden by default
        controls_layout.addWidget(self.cropped_image_checkbox)
        
        # Connect mutual exclusion between auto_outpainting and cropped_image
        self.auto_outpainting_checkbox.toggled.connect(self._on_auto_outpainting_toggled)
        self.cropped_image_checkbox.toggled.connect(self._on_cropped_image_toggled)

        main_layout.addLayout(controls_layout)
        main_layout.addStretch(1)

        # 하단: Inpaint 버튼과 Upscale 버튼
        bottom_button_layout = QHBoxLayout()
        bottom_button_layout.addStretch()
        
        self.resize_button = QPushButton("Set 1MP")
        self.resize_button.setStyleSheet(DARK_STYLES['primary_button'])
        self.resize_button.clicked.connect(self._on_resize_button_clicked)
        self.resize_button.setFixedWidth(120)
        self.resize_button.setVisible(False)  # Initially hidden
        bottom_button_layout.addWidget(self.resize_button)
        
        self.upscale_button = QPushButton("Upscale")
        self.upscale_button.setStyleSheet(DARK_STYLES['secondary_button'])
        self.upscale_button.clicked.connect(self._on_upscale_button_clicked)
        self.upscale_button.setFixedWidth(120)
        bottom_button_layout.addWidget(self.upscale_button)
        
        self.outpaint_button = QPushButton("Outpaint")
        self.outpaint_button.setStyleSheet(DARK_STYLES['secondary_button'])
        self.outpaint_button.clicked.connect(self._on_outpaint_button_clicked)
        self.outpaint_button.setFixedWidth(120)
        self.outpaint_button.setVisible(False)  # img2img 모드에서만 표시
        bottom_button_layout.addWidget(self.outpaint_button)

        self.inpaint_button = QPushButton("Inpaint Image")
        self.inpaint_button.setStyleSheet(DARK_STYLES['secondary_button'])
        self.inpaint_button.clicked.connect(self._on_inpaint_button_clicked) # [2단계] 연결 메서드 변경
        self.inpaint_button.setFixedWidth(200)
        bottom_button_layout.addWidget(self.inpaint_button)

        main_layout.addLayout(bottom_button_layout)

    def _on_inpaint_button_clicked(self):
        if not self.original_pil_image:
            return
        
        # Check if mask was preset from sketchbook (only block the first time)
        if self._mask_from_sketchbook and self.mode == 'inpaint' and self.full_mask_pil:
            # Reset the flag so user can edit mask later if they want
            self._mask_from_sketchbook = False
            print("🎨 Using preset mask from Sketchbook (click again to edit)")
            return

        result = InpaintWindow.get_inpaint_data(self.original_pil_image, self.full_mask_pil, self)
        
        if result is None:
            print("Inpaint 작업이 취소되었습니다.")
            return

        if "full_mask_image" in result:
            print("🎨 Inpaint 모드로 전환합니다.")
            self.mode = 'inpaint'
            self.full_mask_pil = result["full_mask_image"]
            self.small_mask_pil = result["small_mask_image"]
            
            # [3단계 수정] Inpaint 결과의 미리보기 이미지로 배경 업데이트
            preview_pil = result["preview_image"]
            q_image = ImageQt(preview_pil.convert("RGBA"))
            self.background_pixmap = QPixmap.fromImage(q_image).scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation
            )
            self.update() # 패널 다시 그리기 요청

            self._update_ui_for_mode()
        else:
            print("🖼️ Img2Img 모드로 전환합니다 (마스크 없음).")
            self.mode = 'img2img'
            self.full_mask_pil = None
            self.small_mask_pil = None
            self._set_cropped_background() # 원본 크롭 이미지로 배경 복원
            self.update() # 패널 다시 그리기 요청
            self._update_ui_for_mode()

    def _on_outpaint_button_clicked(self):
        """Outpaint Setup 윈도우를 열어 사용자가 캔버스/이미지 배치를 설정합니다."""
        if not self.original_pil_image:
            return

        from .outpaint_window import OutpaintWindow
        result = OutpaintWindow.get_outpaint_data(self.original_pil_image, self)

        if result is None:
            return  # 사용자가 취소함

        # 아웃페인트 데이터 저장
        self._outpaint_data = result
        self._apply_outpaint_preview(result)

    def _apply_outpaint_preview(self, result):
        """아웃페인트 결과를 프리뷰에 반영합니다."""
        canvas = result["canvas_image"].convert("RGBA")
        canvas_array = np.array(canvas)
        mask_array = np.array(result["full_mask_image"])
        # 마스크 영역에 파란 오버레이
        mask_indices = mask_array == 255
        canvas_array[mask_indices] = [100, 100, 255, 160]
        preview = Image.fromarray(canvas_array, 'RGBA')

        q_image = ImageQt(preview)
        self.background_pixmap = QPixmap.fromImage(q_image).scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation
        )

        cw, ch = result["canvas_width"], result["canvas_height"]
        self.title_label.setText(f"Outpaint → {cw}x{ch}")
        self.update()
        print(f"🎨 Outpaint 설정 적용: {cw}x{ch}")

    def set_image_with_mask(self, canvas_image: Image.Image, full_mask: Image.Image, small_mask: Image.Image):
        """캔버스 이미지 + 마스크를 받아 인페인트 모드로 직접 설정합니다."""
        self.mode = 'inpaint'
        self.original_pil_image = canvas_image
        self.full_mask_pil = full_mask
        self.small_mask_pil = small_mask
        self._mask_preset = True
        self._outpaint_data = None

        cw, ch = canvas_image.size
        self.title_label.setText(f"Comic Panel → {cw}x{ch}")

        # Strength 0.8, Noise 0.05 초기화
        self.strength_slider.setValue(85)
        self.noise_slider.setValue(5)

        # 마스크 영역을 파란 오버레이로 표시 (프리뷰)
        preview = canvas_image.convert("RGBA")
        preview_array = np.array(preview)
        mask_array = np.array(full_mask)
        mask_indices = mask_array == 255
        preview_array[mask_indices] = [100, 100, 255, 160]
        preview_img = Image.fromarray(preview_array, 'RGBA')

        q_image = ImageQt(preview_img)
        self.background_pixmap = QPixmap.fromImage(q_image).scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation
        )

        # 픽셀 수 체크
        total_pixels = cw * ch
        self.resize_button.setVisible(total_pixels < 921600 or total_pixels > 1048576)
        self.upscale_button.setVisible(True)

        self._update_ui_for_mode()
        self.update()
        self.setVisible(True)
        print(f"Comic Panel 인페인트 모드 설정: {cw}x{ch}")

    # [2단계] 모드에 따라 UI를 업데이트하는 헬퍼 메서드
    def _update_ui_for_mode(self):
        if self.mode == 'inpaint':
            self.inpaint_button.setText("Edit Mask")
            self.inpaint_button.setStyleSheet(DARK_STYLES['primary_button']) # 강조 색상으로 변경
            self.auto_outpainting_checkbox.setVisible(False)  # 인페인트 모드에서는 숨김
            self.auto_outpainting_checkbox.setChecked(False)
            self.cropped_image_checkbox.setVisible(True)  # Show cropped image checkbox in inpaint mode
        else: # 'img2img'
            self.inpaint_button.setText("Inpaint Image")
            self.inpaint_button.setStyleSheet(DARK_STYLES['secondary_button'])
            self.auto_outpainting_checkbox.setVisible(True)  # img2img 모드에서 표시
            self.cropped_image_checkbox.setVisible(False)  # Hide cropped image checkbox in img2img mode
            self.cropped_image_checkbox.setChecked(False)  # Reset checkbox state
        # Outpaint 버튼: img2img 모드에서 항상 표시
        if hasattr(self, 'outpaint_button'):
            self.outpaint_button.setVisible(self.mode != 'inpaint')

    def _update_strength_label(self, value):
        """Strength 슬라이더 값 변경 시 라벨 업데이트"""
        strength_value = value / 100.0
        self.strength_value_label.setText(f"{strength_value:.2f}")
    
    def _on_auto_outpainting_toggled(self, checked):
        """Auto-outpainting 체크박스 토글 시 관련 UI 업데이트"""
        if checked and self.cropped_image_checkbox.isChecked():
            self.cropped_image_checkbox.setChecked(False)
    
    def _on_cropped_image_toggled(self, checked):
        """Cropped image 체크박스 토글 시 auto_outpainting 체크박스 해제"""
        if checked and self.auto_outpainting_checkbox.isChecked():
            self.auto_outpainting_checkbox.setChecked(False)

    def _update_noise_label(self, value):
        """Noise 슬라이더 값 변경 시 라벨 업데이트"""
        noise_value = value / 100.0
        self.noise_value_label.setText(f"{noise_value:.2f}")

    def paintEvent(self, event):
        """배경 이미지를 먼저 그리고, 그 위에 기본 위젯들을 그립니다."""
        painter = QPainter(self)
        if self.background_pixmap:
            painter.drawPixmap(self.rect(), self.background_pixmap)

            # 어두운 오버레이 씌우기
            painter.fillRect(self.rect(), QColor(0, 0, 0, 155))

        # QFrame의 기본 paintEvent를 호출하여 테두리 등을 그리게 함
        super().paintEvent(event)

    def set_image(self, pil_image: Image.Image):
        """외부에서 이미지를 받아 패널을 활성화하고 모든 상태를 초기화합니다."""
        # [3단계 수정] 새 이미지 로드 시, 모드와 마스크 데이터를 초기화
        self.mode = 'img2img'
        self.full_mask_pil = None
        self.small_mask_pil = None
        self._outpaint_data = None  # 아웃페인트 데이터 초기화
        self._update_ui_for_mode()

        # 64배수 리사이징 및 크롭 적용
        processed_image = self._resize_and_crop_to_64_multiple(pil_image)
        self.original_pil_image = processed_image
        
        # 타이틀에 최종 이미지 크기 표시
        final_width, final_height = processed_image.size
        self.title_label.setText(f"Image2Image & Inpaint -> {final_width} x {final_height}")
        
        # 픽셀 수 체크하여 리사이징 버튼 표시 여부 결정
        total_pixels = final_width * final_height
        if total_pixels < 921600 or total_pixels > 1048576:
            self.resize_button.setVisible(True)
        else:
            self.resize_button.setVisible(False)
        
        self._set_cropped_background() # 배경은 원본 크롭 이미지로 설정
        
        # 새 이미지가 로드되면 Upscale 버튼 다시 표시
        self.upscale_button.setVisible(True)
        
        self.update() 
        self.setVisible(True)

    def _resize_and_crop_to_64_multiple(self, pil_image: Image.Image) -> Image.Image:
        """이미지를 64배수 + 1MP 이내 크기로 리사이징합니다."""
        width, height = pil_image.size

        # 이미 64배수이고 1MP 이내면 그대로 반환
        if width % 64 == 0 and height % 64 == 0 and width * height <= 1048576:
            print(f"🖼️ 이미지 리사이징 불필요: {width}x{height} (이미 64배수, ≤1MP)")
            return pil_image

        new_w_str, new_h_str = self.find_max_resolution(width, height, max_pixels=1048576)
        new_w, new_h = int(new_w_str), int(new_h_str)

        final_image = pil_image.resize((new_w, new_h), Image.Resampling.LANCZOS)
        print(f"🖼️ 이미지 리사이징 완료: {width}x{height} → {new_w}x{new_h} (64배수, ≤1MP)")
        return final_image

    def find_max_resolution(self, width, height, max_pixels=1048576, multiple_of=64):
        """주어진 최대 픽셀 수 내에서 최적의 해상도를 찾습니다."""
        ratio = int(width) / int(height)

        max_width = int((max_pixels * ratio)**0.5)
        max_height = int((max_pixels / ratio)**0.5)

        max_width = (max_width // multiple_of) * multiple_of
        max_height = (max_height // multiple_of) * multiple_of

        while max_width * max_height > max_pixels:
            max_width -= multiple_of
            max_height = int(max_width / ratio)
            max_height = (max_height // multiple_of) * multiple_of

        if max_pixels == 1048576:
            attempts = 0  
            max_attempts = 10  
            while (max_width % multiple_of + max_height % multiple_of) < 32 and attempts < max_attempts:
                if random.choice([True, False]):
                    if (max_width + multiple_of) * max_height <= max_pixels:
                        max_width += multiple_of
                else:
                    if max_width * (max_height + multiple_of) <= max_pixels:
                        max_height += multiple_of
                attempts += 1

        return (str(max_width), str(max_height))

    def _on_resize_button_clicked(self):
        """Auto Resize 버튼 클릭 시 처리"""
        if not self.original_pil_image:
            return
            
        current_width, current_height = self.original_pil_image.size
        total_pixels = current_width * current_height
        
        # 픽셀 수에 따라 적절한 max_pixels 설정
        if total_pixels < 921600:
            max_pixels = 1048576  # 작으면 더 큰 해상도로
        else:  # total_pixels > 1048576
            max_pixels = 1048576 # 크면 더 작은 해상도로
            
        # 최적 해상도 계산
        new_width_str, new_height_str = self.find_max_resolution(
            current_width, current_height, max_pixels=max_pixels
        )
        new_width, new_height = int(new_width_str), int(new_height_str)
        
        # 이미지 리사이징
        resized_image = self.original_pil_image.resize(
            (new_width, new_height), Image.Resampling.LANCZOS
        )
        
        # 이미지 업데이트
        self.original_pil_image = resized_image
        
        # 타이틀 업데이트
        self.title_label.setText(f"Image2Image & Inpaint -> {new_width} x {new_height}")
        
        # 배경 이미지 업데이트
        self._set_cropped_background()
        
        # 리사이징 버튼 숨기기
        self.resize_button.setVisible(False)
        
        self.update()
        print(f"🔄 이미지 자동 리사이징: {current_width}x{current_height} → {new_width}x{new_height}")

    def _set_cropped_background(self):
        """원본 이미지의 중앙 상단을 기준으로 크롭하여 배경 이미지 설정."""
        if not self.original_pil_image:
            return

        width, height = self.original_pil_image.size
        panel_width = 832  # 적절한 너비 값 설정
        aspect_ratio = height / width

        crop_width = min(width, panel_width)
        crop_height = int(crop_width * aspect_ratio * 0.55)

        left = (width - crop_width) // 2
        top = max(0, (height // 2) - (crop_height // 2) - (height // 4)) # 중앙보다 살짝 위
        right = left + crop_width
        bottom = top + crop_height

        cropped_image = self.original_pil_image.crop((left, top, right, bottom))
        q_image = ImageQt(cropped_image.convert("RGBA"))
        self.background_pixmap = QPixmap.fromImage(q_image).scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation
        )

    def resizeEvent(self, event):
        """패널 크기 변경 시 배경 이미지 리사이즈"""
        super().resizeEvent(event)
        if self.original_pil_image:
            self._set_cropped_background()
            self.update()

    def hide_panel(self):
        """패널을 숨기고 모든 상태를 초기화합니다."""
        self.setVisible(False)
        self.mode = 'img2img'
        self.original_pil_image = None
        self.background_pixmap = None
        self.full_mask_pil = None
        self.small_mask_pil = None
        self._mask_preset = False  # Reset preset flag
        self._mask_from_sketchbook = False  # Reset sketchbook flag
        self._outpaint_data = None  # Reset outpaint data

        # 타이틀을 원래 상태로 복원
        self.title_label.setText("Image2Image & Inpaint")
        
        # 패널이 숨겨질 때 버튼들도 초기화
        self.upscale_button.setVisible(True)
        self.resize_button.setVisible(False)
        self._update_ui_for_mode() # UI 상태도 초기화

    def get_parameters(self) -> dict | None:
        if not self.isVisible() or not self.original_pil_image:
            return None

        # 공통 파라미터 생성
        byte_arr = io.BytesIO()
        width, height = self.original_pil_image.size
        self.original_pil_image.save(byte_arr, format='PNG')
        params = {
            "image_bytes": byte_arr.getvalue(),
            "strength": self.strength_slider.value() / 100.0,
            "noise": self.noise_slider.value() / 100.0,
            "width" : width,
            "height" : height
        }

        # Inpaint 모드일 경우 마스크 추가
        if self.mode == 'inpaint':
            params["type"] = "inpaint"
            api_mode = self.app_context.get_api_mode()

            # Add cropped_image_request parameter if checkbox is checked
            if self.cropped_image_checkbox.isChecked():
                params["cropped_image_request"] = True
                # Provide full mask for cropped image extraction
                params["full_mask_pil"] = self.full_mask_pil

            mask_to_use = self.small_mask_pil if api_mode == "NAI" else self.full_mask_pil

            # 🔥 수정: 모든 API에 대해 완벽한 이진 PNG 전송
            # Convert to grayscale if needed
            if mask_to_use.mode != 'L':
                mask_to_use = mask_to_use.convert('L')

            mask_array = np.array(mask_to_use)

            # Ensure 2D array (grayscale)
            if len(mask_array.shape) > 2:
                mask_array = mask_array[:, :, 0] if mask_array.shape[2] > 0 else mask_array[:, :]

            # 완벽한 이진화 강제 (혹시 모를 중간값 제거)
            mask_array = np.where(mask_array > 127, 255, 0).astype(np.uint8)

            # 완벽한 이진 마스크를 PNG로 변환
            mask_image_clean = Image.fromarray(mask_array, mode='L')
            mask_byte_arr = io.BytesIO()

            if api_mode == "NAI":
                # NAI: 무압축 PNG로 저장하여 완벽한 품질 보장
                mask_image_clean.save(mask_byte_arr, format='PNG', compress_level=0, optimize=False)
                params["mask_bytes"] = mask_byte_arr.getvalue()
                print(f"✅ 무압축 PNG 마스크 전송 (NAI, Size: {mask_array.shape}, Unique: {np.unique(mask_array)})")
            else:
                # WebUI: 가벼운 압축 허용
                mask_image_clean.save(mask_byte_arr, format='PNG', compress_level=1, optimize=False)
                params["mask_bytes"] = mask_byte_arr.getvalue()
                print(f"✅ PNG 마스크 전송 (WebUI, Size: {mask_array.shape})")
        elif hasattr(self, '_outpaint_data') and self._outpaint_data:
            # Outpaint 버튼으로 설정된 데이터 사용 (우선)
            params["type"] = "auto_outpainting"
            data = self._outpaint_data
            canvas_bytes = io.BytesIO()
            data["canvas_image"].save(canvas_bytes, format='PNG')
            mask_bytes = io.BytesIO()
            data["small_mask_image"].save(mask_bytes, format='PNG', compress_level=0, optimize=False)
            params["outpaint_canvas_bytes"] = canvas_bytes.getvalue()
            params["outpaint_mask_bytes"] = mask_bytes.getvalue()
            params["outpaint_canvas_width"] = data["canvas_width"]
            params["outpaint_canvas_height"] = data["canvas_height"]
        elif self.auto_outpainting_checkbox.isChecked():
            # Auto-Outpainting 모드: 기본 캔버스로 단일 패스 처리
            params["type"] = "auto_outpainting"
        else:
            params["type"] = "img2img"

        return params
    
    def set_mask_from_sketchbook(self, mask_pil: Image.Image):
        """Set mask from sketchbook and process it through InpaintWindow"""
        if not self.original_pil_image:
            print("⚠️ No image loaded to apply mask to")
            return
            
        # Process mask through InpaintWindow with auto_accept
        result = InpaintWindow.get_inpaint_data(
            self.original_pil_image, 
            mask_pil,  # Pass the mask from sketchbook
            self, 
            auto_accept=True  # Auto-accept to process the mask
        )
        
        if result and "full_mask_image" in result:
            print("🎨 Mask from Sketchbook processed successfully")
            self.mode = 'inpaint'
            self.full_mask_pil = result["full_mask_image"]
            self.small_mask_pil = result["small_mask_image"]
            
            # Update preview if available
            if "preview_image" in result:
                preview_pil = result["preview_image"]
                q_image = ImageQt(preview_pil.convert("RGBA"))
                self.background_pixmap = QPixmap.fromImage(q_image).scaled(
                    self.size(),
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.update()
            
            self._update_ui_for_mode()
            self._mask_from_sketchbook = True
            return True
        else:
            print("⚠️ Failed to process mask from Sketchbook")
            return False
    
    def _on_upscale_button_clicked(self):
        """Upscale 버튼 클릭 시 처리"""
        if not self.original_pil_image:
            QMessageBox.warning(self, "경고", "업스케일할 이미지가 없습니다.")
            return
        
        # NAI 모드 확인
        if self.app_context.app_context.current_api_mode != "NAI":
            QMessageBox.warning(self, "경고", "Upscale 기능은 NAI 모드에서만 사용 가능합니다.")
            return
        
        # 원본 크기 저장
        original_width = self.original_pil_image.width
        original_height = self.original_pil_image.height
        
        # Progress dialog
        self.progress_dialog = QProgressDialog("이미지 업스케일 중...", None, 0, 0, self)
        self.progress_dialog.setWindowTitle("업스케일")
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setCancelButton(None)
        self.progress_dialog.show()
        
        # Worker thread 생성
        self.upscale_worker = UpscaleWorker(
            self.app_context,
            self.original_pil_image,
            original_width,
            original_height
        )
        self.upscale_worker.finished.connect(self._on_upscale_finished)
        self.upscale_worker.error.connect(self._on_upscale_error)
        self.upscale_worker.start()
    
    def _on_upscale_finished(self, upscaled_image):
        """업스케일 완료 처리"""
        self.progress_dialog.close()
        
        # 업스케일된 이미지로 교체
        self.original_pil_image = upscaled_image
        
        # 배경 이미지 업데이트
        self._set_cropped_background()
        
        # Upscale 버튼 숨기기 (이미 업스케일 완료)
        self.upscale_button.setVisible(False)
        
        # Anlas 업데이트
        if hasattr(self.app_context, 'main_window') and hasattr(self.app_context.main_window, 'update_anlas_display'):
            self.app_context.main_window.update_anlas_display()
        
        QMessageBox.information(self, "완료", f"이미지가 2배 업스케일 후 원본 크기({upscaled_image.width}x{upscaled_image.height})로 리사이징되었습니다.")
    
    def _on_upscale_error(self, error_msg):
        """업스케일 에러 처리"""
        self.progress_dialog.close()
        QMessageBox.critical(self, "업스케일 실패", f"업스케일 중 오류가 발생했습니다:\n{error_msg}")


class UpscaleWorker(QThread):
    """업스케일 작업을 수행하는 워커 스레드"""
    finished = pyqtSignal(Image.Image)
    error = pyqtSignal(str)
    
    def __init__(self, app_context, pil_image, target_width, target_height):
        super().__init__()
        self.app_context = app_context
        self.pil_image = pil_image
        self.target_width = target_width
        self.target_height = target_height
    
    def run(self):
        try:
            # API service에서 업스케일 수행
            result = self.app_context.app_context.api_service.upscale_NAI_from_inpaint(
                self.pil_image,
                self.target_width,
                self.target_height
            )
            
            if result['status'] == 'success':
                self.finished.emit(result['image'])
            else:
                self.error.emit(result.get('message', 'Unknown error'))
        except Exception as e:
            self.error.emit(str(e))