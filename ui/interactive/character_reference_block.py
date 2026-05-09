
import io
import base64
from PIL import Image
from dataclasses import dataclass
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QSlider, 
    QDoubleSpinBox, QPushButton, QFileDialog, QFrame, QMenu
)
from PyQt6.QtCore import Qt, pyqtSignal, QBuffer, QSize
from PyQt6.QtGui import QPixmap, QImage, QIcon, QAction, QGuiApplication

from ui.interactive.block_widget import BlockWidget
from ui.theme import DARK_COLORS
from ui.interactive.interactive_theme import (
    COMMON_STYLES, 
    get_checkbox_style, 
    get_input_field_style, 
    get_slider_style,
    get_button_style
)
from ui.scaling_manager import get_scaled_size, get_scaled_font_size
from utils.clipboard_image import qimage_from_clipboard

@dataclass
class CharacterReferenceData:
    """Character reference data for NAID4.5"""
    image_base64: str  # Base64 encoded image
    style_aware: bool = True  # Include style from reference
    fidelity: float = 0.4  # How closely to follow the reference (0.0-1.0)


def process_reference_image(file_path: str = None, pil_image: Image.Image = None) -> str:
    """
    Process reference image for character reference API.
    Normalizes aspect ratio and encodes to base64.
    Accepts either file_path or pil_image object.
    """
    try:
        if pil_image:
            original_image = pil_image
        elif file_path:
            original_image = Image.open(file_path)
        else:
            raise ValueError("No image source provided")

        width, height = original_image.size
        aspect_ratio = width / height

        # Standard aspect ratios (ratio, canvas_width, canvas_height)
        ratios = {
            '2:3': (2/3, 1024, 1536),
            '3:2': (3/2, 1536, 1024),
            '1:1': (1/1, 1472, 1472)
        }

        # Find closest standard ratio
        closest_ratio = min(ratios.keys(), key=lambda k: abs(aspect_ratio - ratios[k][0]))
        target_ratio, canvas_width, canvas_height = ratios[closest_ratio]

        print(f"NAIA-WEB: Reference image {width}x{height} ({aspect_ratio:.2f}) → {closest_ratio} ({canvas_width}x{canvas_height})")

        # Create black canvas
        canvas = Image.new('RGB', (canvas_width, canvas_height), (0, 0, 0))

        # Resize to fit canvas (preserve aspect ratio)
        if width / canvas_width > height / canvas_height:
            new_width = canvas_width
            new_height = int(height * (canvas_width / width))
        else:
            new_height = canvas_height
            new_width = int(width * (canvas_height / height))

        resized_image = original_image.resize((new_width, new_height), Image.Resampling.LANCZOS)

        # Center on canvas
        x_offset = (canvas_width - new_width) // 2
        y_offset = (canvas_height - new_height) // 2

        # Handle RGBA transparency
        if resized_image.mode == 'RGBA':
            canvas = canvas.convert('RGBA')
            canvas.paste(resized_image, (x_offset, y_offset), resized_image)
            rgb_canvas = Image.new('RGB', (canvas_width, canvas_height), (0, 0, 0))
            rgb_canvas.paste(canvas, (0, 0), canvas)
            canvas = rgb_canvas
        else:
            canvas.paste(resized_image, (x_offset, y_offset))

        # Encode to base64
        buffer = io.BytesIO()
        canvas.save(buffer, format="PNG", optimize=False)
        return base64.b64encode(buffer.getvalue()).decode("utf-8")

    except Exception as e:
        print(f"NAIA-WEB: Failed to process reference image: {e}")
        # Fallback: use original file bytes if available via path
        if file_path:
            with open(file_path, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
        return ""


class ClickableFrame(QFrame):
    clicked = pyqtSignal()
    paste_requested = pyqtSignal()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.matches(QAction.StandardKey.Paste) or (event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_V):
            self.paste_requested.emit()
        super().keyPressEvent(event)


class CharacterReferenceBlock(BlockWidget):
    """
    캐릭터 레퍼런스 이미지 업로드 및 설정을 위한 블록
    NAI 전용 - COMFYUI 모드에서는 숨김 처리됨
    """
    def __init__(self, parent=None, app_context=None):
        super().__init__(title="Character Reference", parent=parent)

        self.app_context = app_context
        self.current_image_path = None
        self.current_pil_image = None
        self.char_ref_data = None

        self._init_content()

    def _init_content(self):
        # 메인 설명
        desc_label = QLabel("Upload reference image for character (NAID4.5 only)")
        desc_label.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(14)}px; margin-bottom: 8px;")
        self.content_layout.addWidget(desc_label)

        # === 설정 영역 (Style Aware, Fidelity) ===
        settings_frame = QFrame()
        settings_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 8px;
            }}
        """)
        settings_layout = QVBoxLayout(settings_frame)
        settings_layout.setContentsMargins(12, 12, 12, 12)
        settings_layout.setSpacing(12)

        # Style Aware & Fidelity Row
        row1_layout = QHBoxLayout()
        row1_layout.setSpacing(20)

        # 1. Style Aware
        style_layout = QVBoxLayout()
        style_layout.setSpacing(4)
        style_layout.setAlignment(Qt.AlignmentFlag.AlignTop) # 상단 정렬
        
        self.chk_style_aware = QCheckBox("Style Aware")
        self.chk_style_aware.setChecked(True)
        self.chk_style_aware.setStyleSheet(get_checkbox_style())
        
        # 설명 라벨 제거 요청 반영
        # style_desc = QLabel("Include style from reference") ...
        
        style_layout.addWidget(self.chk_style_aware)
        
        # 2. Fidelity
        fidelity_layout = QVBoxLayout()
        fidelity_layout.setSpacing(8) # 간격 조정
        
        fid_header_layout = QHBoxLayout()
        fid_label = QLabel("Fidelity")
        fid_label.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(14)}px;")
        
        # 스핀박스 대신 단순 라벨로 변경
        self.lbl_fidelity_value = QLabel("0.40")
        self.lbl_fidelity_value.setStyleSheet(f"color: {DARK_COLORS['accent_blue_light']}; font-weight: bold; font-size: {get_scaled_font_size(14)}px;")
        
        # Reset Button (작은 아이콘)
        btn_reset = QPushButton("↺")
        btn_reset.setFixedSize(get_scaled_size(24), get_scaled_size(24))
        btn_reset.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                color: {DARK_COLORS['text_secondary']};
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
                color: {DARK_COLORS['text_primary']};
            }}
        """)
        btn_reset.setToolTip("Reset Fidelity (0.4)")
        btn_reset.clicked.connect(lambda: self.slider_fidelity.setValue(40)) # 0.40

        fid_header_layout.addWidget(fid_label)
        fid_header_layout.addStretch()
        fid_header_layout.addWidget(self.lbl_fidelity_value)
        fid_header_layout.addWidget(btn_reset)
        
        # "How closely..." 설명 라벨도 제거하여 심플하게 (요청사항엔 없었지만 공간 확보 위해)
        # fid_desc = QLabel("How closely to follow the reference") ...

        # Slider (네모 핸들 스타일)
        slider_layout = QHBoxLayout()
        self.slider_fidelity = QSlider(Qt.Orientation.Horizontal)
        self.slider_fidelity.setRange(0, 100)
        self.slider_fidelity.setValue(40) # Default 0.40
        
        # 네모난 핸들 스타일
        slider_qss = f"""
            QSlider::groove:horizontal {{
                background: {DARK_COLORS['bg_primary']};
                height: {get_scaled_size(8)}px;
                border-radius: {get_scaled_size(2)}px;
            }}
            QSlider::sub-page:horizontal {{
                background: {DARK_COLORS['accent_blue']};
                height: {get_scaled_size(8)}px;
                border-radius: {get_scaled_size(2)}px;
            }}
            QSlider::add-page:horizontal {{
                background: {DARK_COLORS['bg_primary']};
                height: {get_scaled_size(8)}px;
                border-radius: {get_scaled_size(2)}px;
            }}
            QSlider::handle:horizontal {{
                background: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                width: {get_scaled_size(12)}px;
                height: {get_scaled_size(16)}px;
                margin: -{get_scaled_size(4)}px 0;
                border-radius: 2px; /* 네모난 모양 (약간의 둥글기) */
            }}
            QSlider::handle:horizontal:hover {{
                background: white;
                border: 1px solid {DARK_COLORS['accent_blue']};
            }}
        """
        self.slider_fidelity.setStyleSheet(slider_qss)
        
        slider_layout.addWidget(self.slider_fidelity)

        fidelity_layout.addLayout(fid_header_layout)
        fidelity_layout.addLayout(slider_layout)

        # 연동 (슬라이더 -> 라벨)
        self.slider_fidelity.valueChanged.connect(self._on_slider_changed)

        # 레이아웃 배치 (Style Aware: 3, Fidelity: 7 비율로 Fidelity 확장)
        row1_layout.addLayout(style_layout, 3) 
        row1_layout.addLayout(fidelity_layout, 7)

        settings_layout.addLayout(row1_layout)
        self.content_layout.addWidget(settings_frame)

        # === 이미지 업로드 영역 ===
        img_title_layout = QHBoxLayout()
        img_icon = QLabel("🖼️") # 아이콘 대체
        img_label = QLabel("Reference Image")
        img_label.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-weight: bold;")
        img_title_layout.addWidget(img_icon)
        img_title_layout.addWidget(img_label)
        img_title_layout.addStretch()
        
        self.content_layout.addLayout(img_title_layout)

        # 클릭 가능한 프레임 (업로드 영역)
        self.upload_frame = ClickableFrame()
        self.upload_frame.setFocusPolicy(Qt.FocusPolicy.StrongFocus) # 키 이벤트 받기 위해
        self.upload_frame.setCursor(Qt.CursorShape.PointingHandCursor)
        self.upload_frame.setMinimumHeight(get_scaled_size(200))
        self.upload_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 2px dashed {DARK_COLORS['border']};
                border-radius: 8px;
            }}
            QFrame:hover {{
                background-color: {DARK_COLORS['bg_hover']};
                border: 2px dashed {DARK_COLORS['accent_blue']};
            }}
        """)
        
        self.upload_frame.clicked.connect(self._open_file_dialog)
        self.upload_frame.paste_requested.connect(self._paste_from_clipboard)

        # 내부 레이아웃 (Stack 처럼 사용: Empty State / Image State)
        self.upload_layout = QVBoxLayout(self.upload_frame)
        self.upload_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 1. Empty State 위젯들
        self.empty_widget = QWidget()
        empty_layout = QVBoxLayout(self.empty_widget)
        
        icon_lbl = QLabel("⬆️") # 아이콘 대체
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet("font-size: 32px;")
        
        text_lbl = QLabel("이미지를\n\n클릭하여 업로드")
        text_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text_lbl.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(14)}px;")
        
        empty_layout.addWidget(icon_lbl)
        empty_layout.addWidget(text_lbl)

        # 2. Image State 위젯 (라벨)
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setScaledContents(True) # 비율은 resizeEvent 로 제어 권장하지만 간단히
        self.preview_label.hide()

        # 이미지 상태에서 보일 오버레이 버튼들 (우측 상단 닫기, 확대 등)
        # 이는 Frame 위에 절대 좌표로 그리는게 좋으나, 간단히 Layout에 추가
        
        self.upload_layout.addWidget(self.empty_widget)
        self.upload_layout.addWidget(self.preview_label)

        # 오버레이 버튼 컨테이너 (우측 상단)
        self.overlay_container = QWidget(self.upload_frame)
        self.overlay_container.setStyleSheet("background: transparent;")
        overlay_layout = QHBoxLayout(self.overlay_container)
        overlay_layout.setContentsMargins(0, 5, 5, 0)
        overlay_layout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)

        btn_clear = QPushButton("❌")
        btn_clear.setFixedSize(30, 30)
        btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_clear.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(0, 0, 0, 0.6);
                border-radius: 4px;
                color: white;
                border: none;
            }}
            QPushButton:hover {{ background-color: rgba(255, 0, 0, 0.8); }}
        """)
        btn_clear.clicked.connect(self.clear_image)
        
        self.btn_clear = btn_clear
        overlay_layout.addWidget(btn_clear)
        self.overlay_container.hide() # 초기 숨김

        self.content_layout.addWidget(self.upload_frame)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 오버레이 버튼 위치 조정 (Top-Right)
        if hasattr(self, 'overlay_container') and hasattr(self, 'upload_frame'):
            self.overlay_container.setGeometry(0, 0, self.upload_frame.width(), 40)
            self.overlay_container.raise_()

    def _on_slider_changed(self, value):
        # 라벨 업데이트
        self.lbl_fidelity_value.setText(f"{value / 100.0:.2f}")

    # _on_spinbox_changed 메서드는 삭제 (스핀박스 제거됨)

    def _open_file_dialog(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Reference Image", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)"
        )
        if file_path:
            self._load_image(file_path)

    def _paste_from_clipboard(self):
        clipboard = QGuiApplication.clipboard()
        mime_data = clipboard.mimeData()

        image = qimage_from_clipboard(clipboard)
        if not image.isNull():
            self._load_qimage(image)
        elif mime_data.hasUrls(): # 파일 복사 후 붙여넣기
            for url in mime_data.urls():
                if url.isLocalFile():
                    path = url.toLocalFile()
                    if path.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.bmp')):
                        self._load_image(path)
                        break # 하나만 로드

    def _load_image(self, file_path):
        self.current_image_path = file_path
        try:
            # PIL 로드 검증
            pil_img = Image.open(file_path)
            self.current_pil_image = pil_img
            
            # 미리보기 표시
            pixmap = QPixmap(file_path)
            self._update_preview(pixmap)
        except Exception as e:
            print(f"이미지 로드 실패: {e}")

    def _load_qimage(self, qimage):
        self.current_image_path = None # 클립보드라 경로 없음
        try:
            # QImage -> PIL Image 변환
            buffer = QBuffer()
            buffer.open(QBuffer.OpenModeFlag.ReadWrite)
            qimage.save(buffer, "PNG")
            pil_img = Image.open(io.BytesIO(buffer.data()))
            self.current_pil_image = pil_img
            
            self._update_preview(QPixmap.fromImage(qimage))
        except Exception as e:
            print(f"클립보드 이미지 변환 실패: {e}")

    def _update_preview(self, pixmap):
        if pixmap.isNull(): return

        # UI 업데이트
        self.empty_widget.hide()
        self.preview_label.show()
        self.overlay_container.show()
        self.upload_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 8px;
            }}
        """)

        # 비율 맞춰 표시 (최대 높이 제한 내에서)
        w, h = pixmap.width(), pixmap.height()
        target_h = get_scaled_size(300)
        
        if h > target_h:
            pixmap = pixmap.scaledToHeight(target_h, Qt.TransformationMode.SmoothTransformation)
        elif w > self.upload_frame.width():
            pixmap = pixmap.scaledToWidth(self.upload_frame.width() - 20, Qt.TransformationMode.SmoothTransformation)
            
        self.preview_label.setPixmap(pixmap)
        self.preview_label.setFixedHeight(pixmap.height())
        self.upload_frame.setMinimumHeight(pixmap.height() + 20)

    def clear_image(self):
        self.current_image_path = None
        self.current_pil_image = None
        self.preview_label.clear()
        self.preview_label.hide()
        self.empty_widget.show()
        self.overlay_container.hide()
        self.upload_frame.setMinimumHeight(get_scaled_size(200))
        self.upload_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 2px dashed {DARK_COLORS['border']};
                border-radius: 8px;
            }}
            QFrame:hover {{
                background-color: {DARK_COLORS['bg_hover']};
                border: 2px dashed {DARK_COLORS['accent_blue']};
            }}
        """)

    def get_data(self) -> CharacterReferenceData:
        """
        설정된 데이터를 CharacterReferenceData 객체로 반환
        이미지가 없으면 None 반환
        """
        if self.current_pil_image is None:
            return None
        
        try:
            # 전처리 및 Base64 인코딩
            image_base64 = process_reference_image(pil_image=self.current_pil_image)
            
            return CharacterReferenceData(
                image_base64=image_base64,
                style_aware=self.chk_style_aware.isChecked(),
                fidelity=self.slider_fidelity.value() / 100.0
            )
        except Exception as e:
            print(f"데이터 생성 중 오류: {e}")
            return None
