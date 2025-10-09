import os
import hashlib
import base64
import io
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import json
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QScrollArea, QCheckBox, QFileDialog,
    QMessageBox, QApplication, QDialog, QTabWidget, QGridLayout,
    QMenu, QInputDialog, QSizePolicy, QTextEdit, QLineEdit, QSlider
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QPixmap, QImage, QAction
from PIL import Image
from PIL.ImageQt import ImageQt
from interfaces.base_module import BaseMiddleModule
from interfaces.mode_aware_module import ModeAwareModule
from core.context import AppContext
from ui.theme import get_dynamic_styles
from ui.scaling_manager import get_scaled_font_size, get_scaled_size


# VibeEncodingWorker 클래스 제거됨 - Character Reference에서는 인코딩 불필요


class NoScrollSlider(QSlider):
    """QSlider that ignores mouse wheel events"""
    def wheelEvent(self, event):
        event.ignore()


class CharacterReferenceFrame(QFrame):
    """Individual character reference frame widget"""
    
    removed = pyqtSignal(object)  # Signal when frame is removed
    
    def __init__(self, file_path: str, app_context: AppContext, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.file_path = file_path
        self.file_name = os.path.basename(file_path)
        
        # Calculate hash and load image
        self.file_hash = self._calculate_file_hash(file_path)
        self.image = Image.open(file_path)
        self.image_data = self._file_to_base64(file_path)
        
        # Character reference data (simplified from vibe transfer)
        self.style_aware = True    # Style Aware 체크박스 상태 (기본값: True)
        self.fidelity = 1       # Fidelity 슬라이더 값 (기본값: 0.75)
        self.is_enabled = False    # 단일 선택을 위한 활성화 상태
        
        # Setup UI
        self._setup_ui()
        
    def _calculate_file_hash(self, file_path: str) -> str:
        """Calculate SHA-256 hash of file"""
        hash_sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_sha256.update(chunk)
        return hash_sha256.hexdigest()[:16]  # Use first 16 characters
        
    def _file_to_base64(self, file_path: str) -> str:
        """Convert image file to base64 with aspect ratio normalization"""
        try:
            # 원본 이미지 로드
            original_image = Image.open(file_path)
            
            # 이미지 비율 계산
            width, height = original_image.size
            aspect_ratio = width / height
            
            # 가장 가까운 표준 비율 결정
            ratios = {
                '2:3': (2/3, 1024, 1536),  # (비율, 너비, 높이)
                '3:2': (3/2, 1536, 1024),
                '1:1': (1/1, 1472, 1472)
            }
            
            # 현재 비율과 가장 가까운 표준 비율 찾기
            closest_ratio = min(ratios.keys(), key=lambda k: abs(aspect_ratio - ratios[k][0]))
            target_ratio, canvas_width, canvas_height = ratios[closest_ratio]
            
            print(f"  - 원본 비율: {width}x{height} ({aspect_ratio:.2f}) → 표준 비율: {closest_ratio} ({canvas_width}x{canvas_height})")
            
            # 검은색 배경 생성
            canvas = Image.new('RGB', (canvas_width, canvas_height), (0, 0, 0))
            
            # 이미지를 캔버스에 맞게 리사이징 (비율 유지)
            if width / canvas_width > height / canvas_height:
                # 너비 기준으로 리사이징
                new_width = canvas_width
                new_height = int(height * (canvas_width / width))
            else:
                # 높이 기준으로 리사이징
                new_height = canvas_height
                new_width = int(width * (canvas_height / height))
            
            # LANCZOS 리사이징
            resized_image = original_image.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # 중앙에 배치
            x_offset = (canvas_width - new_width) // 2
            y_offset = (canvas_height - new_height) // 2
            
            # RGBA 모드인 경우 투명도 처리
            if resized_image.mode == 'RGBA':
                canvas = canvas.convert('RGBA')
                canvas.paste(resized_image, (x_offset, y_offset), resized_image)
                # 다시 RGB로 변환 (검은 배경과 합성)
                rgb_canvas = Image.new('RGB', (canvas_width, canvas_height), (0, 0, 0))
                rgb_canvas.paste(canvas, (0, 0), canvas)
                canvas = rgb_canvas
            else:
                canvas.paste(resized_image, (x_offset, y_offset))
            
            # PNG로 인코딩 후 base64 변환
            buffer = io.BytesIO()
            canvas.save(buffer, format="PNG", optimize=False)
            return base64.b64encode(buffer.getvalue()).decode("utf-8")
            
        except Exception as e:
            print(f"Failed to process image with aspect ratio normalization, using original file: {e}")
            # 폴백: 원본 파일 바이트 그대로 사용
            with open(file_path, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
        
    def _get_current_model(self) -> str:
        """Get the current model from main window's model combo"""
        try:
            if hasattr(self.app_context, 'main_window') and hasattr(self.app_context.main_window, 'model_combo'):
                current_text = self.app_context.main_window.model_combo.currentText()
                sanitized = current_text.replace("/", "_").replace("\\", "_").replace(":", "").replace("*", "").replace("?", "").replace('"', "").replace("<", "").replace(">", "").replace("|", "")
                return sanitized
        except Exception as e:
            print(f"Failed to get current model: {e}")
        return "default"
    
    def _is_naid45_model(self) -> bool:
        """Check if current model is NAID4.5F or NAID4.5C"""
        model = self._get_current_model()
        return "NAID4.5F" in model or "NAID4.5C" in model
    
    def _setup_ui(self):
        """Setup the UI for this frame"""
        dynamic_styles = get_dynamic_styles()
        
        self.setFrameStyle(QFrame.Shape.Box)
        self.setStyleSheet(f"""
            QFrame {{
                border: 1px solid #444;
                border-radius: 4px;
                background-color: #2a2a2a;
                padding: {get_scaled_size(8)}px;
            }}
        """)
        
        # Fixed size for the frame
        self.setFixedHeight(get_scaled_size(260))  # Slightly smaller than vibe transfer
        
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(get_scaled_size(4))
        main_layout.setContentsMargins(get_scaled_size(6), get_scaled_size(6), get_scaled_size(6), get_scaled_size(6))
        
        # Top row: Controls
        top_row = QHBoxLayout()
        top_row.setSpacing(get_scaled_size(4))
        
        # Delete button
        delete_btn = QPushButton("❌닫기")
        delete_btn.setFixedSize(get_scaled_size(90), get_scaled_size(40))
        delete_btn.setStyleSheet(dynamic_styles['compact_button'])
        delete_btn.clicked.connect(lambda: self.removed.emit(self))
        top_row.addWidget(delete_btn)
        
        # File name label
        name_label = QLabel(self.file_name[:20] + "..." if len(self.file_name) > 20 else self.file_name)
        name_label.setStyleSheet(f"color: white; font-size: {get_scaled_font_size(16)}px;")
        top_row.addWidget(name_label)
        
        top_row.addStretch()
        
        # Enable checkbox (single selection behavior)
        self.enable_check = QCheckBox("Enable")
        self.enable_check.setChecked(self.is_enabled)
        self.enable_check.setStyleSheet(dynamic_styles['dark_checkbox'])
        self.enable_check.toggled.connect(self._on_enabled_changed)
        top_row.addWidget(self.enable_check)
        
        main_layout.addLayout(top_row)
        
        # Content frame
        content_frame = QFrame()
        content_frame.setStyleSheet("QFrame { border: none; background: transparent; }")
        
        content_row = QHBoxLayout(content_frame)
        content_row.setSpacing(get_scaled_size(8))
        content_row.setContentsMargins(0, 0, 0, 0)
        
        # Image preview
        self.image_label = QLabel()
        self.image_label.setFixedSize(164, 198)
        self.image_label.setStyleSheet("QLabel { border: 1px solid #666; background: #1a1a1a; }")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Resize image to fit 164x198 while maintaining aspect ratio
        thumbnail = self.image.copy()
        thumbnail.thumbnail((164, 198), Image.Resampling.LANCZOS)
        
        # Convert to QPixmap using proper method
        qimage = self._pil_to_qimage(thumbnail)
        pixmap = QPixmap.fromImage(qimage)
        
        # Store original for enabled/disabled states
        self.original_pixmap = pixmap
        
        # Scale pixmap to fit label exactly
        scaled_pixmap = pixmap.scaled(164, 198, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.image_label.setPixmap(scaled_pixmap)
        
        content_row.addWidget(self.image_label)
        
        # Controls column (simplified from vibe transfer)
        controls_container = QFrame()
        controls_container.setStyleSheet("QFrame { border: none; background: transparent; }")
        controls_container.setMinimumWidth(get_scaled_size(300))
        controls_container.setMaximumWidth(get_scaled_size(400))
        
        controls_layout = QVBoxLayout(controls_container)
        controls_layout.setSpacing(get_scaled_size(8))
        controls_layout.setContentsMargins(0, 0, 0, 0)

        self.style_aware_check = QCheckBox("Style Aware")
        self.style_aware_check.setChecked(self.style_aware)
        self.style_aware_check.setStyleSheet(dynamic_styles['dark_checkbox'])
        self.style_aware_check.toggled.connect(self._on_style_aware_changed)
        controls_layout.addWidget(self.style_aware_check)

        # Fidelity value label and slider container
        fidelity_value_layout = QHBoxLayout()
        fidelity_value_layout.setSpacing(get_scaled_size(8))

        self.fidelity_value_label = QLabel(f"Fidelity: {self.fidelity:.2f}")
        self.fidelity_value_label.setStyleSheet(f"color: #4a9eff; font-size: {get_scaled_font_size(16)}px; font-weight: bold;")
        fidelity_value_layout.addWidget(self.fidelity_value_label)
        fidelity_value_layout.addStretch()

        controls_layout.addLayout(fidelity_value_layout)

        # Fidelity slider (0.0 to 1.0, step 0.05)
        self.fidelity_slider = NoScrollSlider(Qt.Orientation.Horizontal)
        self.fidelity_slider.setMinimum(0)
        self.fidelity_slider.setMaximum(20)  # 0 to 1.0 in 0.05 steps = 20 steps
        self.fidelity_slider.setValue(int(self.fidelity * 20))  # 0.75 * 20 = 15
        self.fidelity_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.fidelity_slider.setTickInterval(1)
        self.fidelity_slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                background: #2a2a2a;
                height: {get_scaled_size(8)}px;
                border-radius: {get_scaled_size(4)}px;
            }}
            QSlider::handle:horizontal {{
                background: #4a9eff;
                width: {get_scaled_size(16)}px;
                height: {get_scaled_size(20)}px;
                margin: -{get_scaled_size(6)}px 0;
                border-radius: {get_scaled_size(3)}px;
            }}
            QSlider::handle:horizontal:hover {{
                background: #6ab9ff;
            }}
        """)
        self.fidelity_slider.valueChanged.connect(self._on_fidelity_changed)
        controls_layout.addWidget(self.fidelity_slider)

        # Add spacing to push controls to top
        controls_layout.addStretch()
        
        content_row.addWidget(controls_container)
        main_layout.addWidget(content_frame)
        
        # Update the enabled state display
        self._update_enabled_display()
    
    def _pil_to_qimage(self, pil_image: Image.Image) -> QImage:
        """Convert PIL Image to QImage using PIL.ImageQt for proper color handling"""
        # Convert to RGBA for consistent handling
        if pil_image.mode != "RGBA":
            pil_image = pil_image.convert("RGBA")
        
        # Use PIL.ImageQt for proper conversion without color inversion
        return ImageQt(pil_image)
    
    def _on_enabled_changed(self, checked: bool):
        """Handle enable checkbox change - implement single selection logic"""
        if checked:
            # 단일 선택 로직: 다른 모든 프레임 비활성화
            parent_module = self._get_parent_module()
            if parent_module:
                for other_frame in parent_module.character_frames:
                    if other_frame != self and other_frame.is_enabled:
                        other_frame.enable_check.setChecked(False)
                        other_frame.is_enabled = False
                        other_frame._update_enabled_display()
        
        self.is_enabled = checked
        self._update_enabled_display()
        # Save image to storage when first enabled
        if checked:
            self._save_image_to_storage()
    
    def _on_style_aware_changed(self, checked: bool):
        """Handle style aware checkbox change"""
        self.style_aware = checked
        # No need to save settings - user controls this each time

    def _on_fidelity_changed(self, value: int):
        """Handle fidelity slider change"""
        self.fidelity = value / 20.0  # Convert 0-20 to 0.0-1.0
        self.fidelity_value_label.setText(f"Fidelity: {self.fidelity:.2f}")
    
    def _get_parent_module(self):
        """Get the parent CharacterReferenceModule instance"""
        # The frame is added to frames_container, so we need to find the module
        # by searching through the widget hierarchy
        parent = self.parent()
        while parent:
            # Look for the main widget that has the layout with our frames
            if hasattr(parent, 'parent') and parent.parent():
                grandparent = parent.parent()
                # Check if grandparent has the module reference
                if hasattr(grandparent, 'character_frames'):
                    return grandparent
            parent = parent.parent()
        
        # Alternative: Search through the app context
        if hasattr(self, 'app_context') and self.app_context:
            try:
                # Get the module from middle section controller
                if hasattr(self.app_context, 'middle_section_controller'):
                    module = self.app_context.middle_section_controller.get_module_instance("CharacterReferenceModule")
                    return module
            except:
                pass
        
        return None
    
    def _update_enabled_display(self):
        """Update the visual state based on enabled status"""
        if hasattr(self, 'image_label'):
            if self.is_enabled:
                self.image_label.setPixmap(self.original_pixmap.scaled(164, 198, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            else:
                # Create darkened version
                darkened_pixmap = self._create_darkened_pixmap(self.original_pixmap)
                self.image_label.setPixmap(darkened_pixmap.scaled(164, 198, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
    
    def _create_darkened_pixmap(self, pixmap: QPixmap) -> QPixmap:
        """Create a darkened version of the pixmap"""
        darkened = QPixmap(pixmap.size())
        darkened.fill(Qt.GlobalColor.transparent)
        
        from PyQt6.QtGui import QPainter
        painter = QPainter(darkened)
        painter.setOpacity(0.3)
        painter.drawPixmap(0, 0, pixmap)
        painter.end()
        
        return darkened
    
    def _save_image_to_storage(self):
        """Save image to character reference storage"""
        # Create character_reference/images directory
        char_ref_folder = Path("save/character_reference/images")
        char_ref_folder.mkdir(parents=True, exist_ok=True)
        
        # Save image with hash name
        storage_image_path = char_ref_folder / f"{self.file_hash}.png"
        
        try:
            # Copy image to storage if not from temp or if different
            if not storage_image_path.exists() or storage_image_path.stat().st_size != Path(self.file_path).stat().st_size:
                import shutil
                shutil.copy2(self.file_path, storage_image_path)
                print(f"✅ Character reference image saved: {storage_image_path}")
        except Exception as e:
            print(f"Failed to save character reference image: {e}")
    
    def get_character_data(self) -> Optional[Dict[str, Any]]:
        """Get character reference data if enabled"""
        if not self.is_enabled or not self._is_naid45_model():
            return None

        # Calculate fidelity with rounding and 0.05 step alignment
        inverted_fidelity = 1.0 - self.fidelity
        # Round to 0.05 steps and clamp to [0.0, 1.0]
        fidelity_value = round(inverted_fidelity * 20) / 20.0
        fidelity_value = max(0.0, min(1.0, fidelity_value))

        return {
            "image_data": self.image_data,
            "style_aware": self.style_aware,
            "fidelity": fidelity_value,
            "file_path": self.file_path,
            "file_hash": self.file_hash
        }


class CharacterStorageItem(QFrame):
    """Storage item widget for character reference display"""
    apply_requested = pyqtSignal(str, str, str)  # file_hash, file_name, image_path
    
    def __init__(self, file_hash: str, file_name: str, image_path: Path, app_context=None, parent=None):
        super().__init__(parent)
        self.file_hash = file_hash
        self.file_name = file_name
        self.image_path = image_path
        self.app_context = app_context
        
        # Fixed size matching VibeStorageItem
        self.setFixedSize(QSize(270, 380))
        self.setFrameStyle(QFrame.Shape.Box)
        self.setStyleSheet("""
            QFrame {
                border: 1px solid #333;
                border-radius: 4px;
                background-color: #1a1a1a;
                padding: 4px;
            }
            QFrame:hover {
                border-color: #4a9eff;
                background-color: #222;
                border-width: 2px;
            }
        """)
        
        self._setup_ui()
        
        # Install event filter for context menu
        self.installEventFilter(self)
    
    def _setup_ui(self):
        """Setup the UI for this storage item"""
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(4, 4, 4, 4)
        
        # File name label at top
        self.name_label = QLabel()
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setWordWrap(True)
        self.name_label.setMaximumHeight(get_scaled_size(40))
        self._update_name_label()  # Set initial text and color
        layout.addWidget(self.name_label)
        
        # Image display (same size as VibeStorageItem)
        self.image_label = QLabel()
        self.image_label.setFixedSize(256, 334)
        self.image_label.setStyleSheet("QLabel { border: 1px solid #444; background: #1a1a1a; }")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setScaledContents(False)
        
        # Load and display image
        self._load_image()
        layout.addWidget(self.image_label)
    
    def _update_name_label(self):
        """Update name label based on character metadata"""
        metadata = self._load_metadata()
        character_name = metadata.get("character_name", "").strip()
        
        if character_name:
            # Show character name in yellow color
            display_text = character_name[:30] + "..." if len(character_name) > 30 else character_name
            self.name_label.setText(display_text)
            self.name_label.setStyleSheet(f"color: #FFD700; font-size: {get_scaled_font_size(14)}px; font-weight: bold;")
        else:
            # Show file name in white color
            display_text = self.file_name[:30] + "..." if len(self.file_name) > 30 else self.file_name
            self.name_label.setText(display_text)
            self.name_label.setStyleSheet(f"color: white; font-size: {get_scaled_font_size(14)}px;")
    
    def _load_image(self):
        """Load and display the image with proper cropping"""
        try:
            if self.image_path.exists():
                # Open image with PIL
                img = Image.open(self.image_path)
                
                # Target size
                target_width = 256
                target_height = 334
                
                # Calculate aspect ratios
                img_ratio = img.width / img.height
                target_ratio = target_width / target_height
                
                # Determine crop dimensions
                if img_ratio > target_ratio:
                    # Image is wider - crop sides
                    new_height = img.height
                    new_width = int(img.height * target_ratio)
                    left = (img.width - new_width) // 2
                    top = 0
                    right = left + new_width
                    bottom = img.height
                else:
                    # Image is taller - crop top/bottom
                    new_width = img.width
                    new_height = int(img.width / target_ratio)
                    left = 0
                    top = (img.height - new_height) // 2
                    right = img.width
                    bottom = top + new_height
                
                # Crop and resize
                img_cropped = img.crop((left, top, right, bottom))
                img_resized = img_cropped.resize((target_width, target_height), Image.Resampling.LANCZOS)
                
                # Convert to QPixmap
                if img_resized.mode != "RGBA":
                    img_resized = img_resized.convert("RGBA")
                qimage = ImageQt(img_resized)
                pixmap = QPixmap.fromImage(qimage)
                
                self.image_label.setPixmap(pixmap)
            else:
                self.image_label.setText("Image not found")
                self.image_label.setStyleSheet("QLabel { border: 1px solid #444; background: #1a1a1a; color: #888; }")
        except Exception as e:
            print(f"Failed to load image {self.image_path}: {e}")
            self.image_label.setText("Failed to load")
            self.image_label.setStyleSheet("QLabel { border: 1px solid #444; background: #1a1a1a; color: #ff4444; }")
    
    def eventFilter(self, obj, event):
        """Handle mouse events for context menu"""
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.ContextMenu:
            self.show_context_menu(event.globalPos())
            return True
        return super().eventFilter(obj, event)
        
    def mouseDoubleClickEvent(self, event):
        """Handle double-click to apply character reference"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_apply_character()
        super().mouseDoubleClickEvent(event)
    
    def show_context_menu(self, pos):
        """Show context menu for item actions"""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #2a2a2a;
                border: 1px solid #555;
                color: white;
            }
            QMenu::item:selected {
                background-color: #4a9eff;
            }
        """)
        
        # Apply action
        apply_action = QAction("✨ Character 적용", self)
        apply_action.triggered.connect(self._on_apply_character)
        menu.addAction(apply_action)
        
        # Check if character_prompt exists in JSON for C1 assignment
        metadata = self._load_metadata()
        character_prompt = metadata.get("character_prompt", "").strip()
        
        if character_prompt:
            assign_c1_action = QAction("👤 캐릭터 프롬프트 C1 할당", self)
            assign_c1_action.triggered.connect(self._on_assign_c1)
            menu.addAction(assign_c1_action)
        
        menu.addSeparator()
        
        # Metadata editing action
        edit_metadata_action = QAction("📝 메타데이터 편집", self)
        edit_metadata_action.triggered.connect(self._on_edit_metadata)
        menu.addAction(edit_metadata_action)
        
        menu.addSeparator()
        
        delete_action = QAction("🗑️ 파일 삭제", self)
        delete_action.triggered.connect(self._on_delete)
        menu.addAction(delete_action)
        
        menu.exec(pos)
        
    def _on_apply_character(self):
        """Handle apply character action"""
        self.apply_requested.emit(self.file_hash, self.file_name, str(self.image_path))
    
    def _on_assign_c1(self):
        """Handle C1 assignment action"""
        try:
            # Load metadata
            metadata = self._load_metadata()
            character_prompt = metadata.get("character_prompt", "").strip()
            character_uc = metadata.get("character_uc", "").strip()
            
            if not character_prompt:
                # Error message
                msg_box = QMessageBox(self)
                msg_box.setIcon(QMessageBox.Icon.Warning)
                msg_box.setWindowTitle("오류")
                msg_box.setText("Character Prompt가 설정되지 않았습니다.")
                msg_box.setStyleSheet(self._get_messagebox_style())
                msg_box.exec()
                return
            
            # Get CharacterModule from app_context
            character_module = None
            if hasattr(self, 'app_context') and self.app_context:
                try:
                    character_module = self.app_context.middle_section_controller.get_module_instance("CharacterModule")
                except Exception as e:
                    print(f"Failed to get CharacterModule: {e}")
            
            if not character_module:
                # Error message
                msg_box = QMessageBox(self)
                msg_box.setIcon(QMessageBox.Icon.Critical)
                msg_box.setWindowTitle("오류")
                msg_box.setText("CharacterModule을 찾을 수 없습니다.")
                msg_box.setStyleSheet(self._get_messagebox_style())
                msg_box.exec()
                return
            
            # Assign to C1
            character_module.assign_c1(character_prompt, character_uc)
            
            # Check if this image exists in CharacterReferenceModule.character_frames
            character_ref_module = None
            try:
                character_ref_module = self.app_context.middle_section_controller.get_module_instance("CharacterReferenceModule")
            except Exception as e:
                print(f"Failed to get CharacterReferenceModule: {e}")
            
            if character_ref_module:
                # Check if this image is already in character_frames
                image_exists = False
                for frame in character_ref_module.character_frames:
                    if frame.file_hash == self.file_hash:
                        image_exists = True
                        break
                
                # If not exists, add it
                if not image_exists:
                    try:
                        frame = character_ref_module._add_character_frame(str(self.image_path))
                        if frame:
                            # Enable this frame
                            frame.enable_check.setChecked(True)
                            frame.is_enabled = True
                            frame._update_enabled_display()
                    except Exception as e:
                        print(f"Failed to add character frame: {e}")
            
            # Close the storage window
            self._close_storage_window()
            
            # Success message
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Icon.Information)
            msg_box.setWindowTitle("완료")
            msg_box.setText("이미지 및 캐릭터 프롬프트가 적용되었습니다.")
            msg_box.setStyleSheet(self._get_messagebox_style())
            msg_box.exec()
            
        except Exception as e:
            print(f"Error in _on_assign_c1: {e}")
            # Error message
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Icon.Critical)
            msg_box.setWindowTitle("오류")
            msg_box.setText(f"C1 할당 중 오류가 발생했습니다: {str(e)}")
            msg_box.setStyleSheet(self._get_messagebox_style())
            msg_box.exec()
    
    def _close_storage_window(self):
        """Close the parent CharacterStorageWindow"""
        # Find parent CharacterStorageWindow and close it
        parent = self.parent()
        while parent:
            if isinstance(parent, CharacterStorageWindow):
                parent.close()
                break
            parent = parent.parent()
    
    def _get_metadata_path(self) -> Path:
        """Get the JSON metadata file path for this character"""
        metadata_folder = Path("save/character_reference/metadata")
        metadata_folder.mkdir(parents=True, exist_ok=True)
        return metadata_folder / f"{self.file_hash}.json"
    
    def _load_metadata(self) -> Dict[str, str]:
        """Load metadata from JSON file"""
        metadata_path = self._get_metadata_path()
        if metadata_path.exists():
            try:
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Failed to load metadata: {e}")
        return {
            "character_name": "",
            "character_prompt": "",
            "character_uc": "",
            "file_name": self.file_name,
            "file_hash": self.file_hash
        }
    
    def _save_metadata(self, metadata: Dict[str, str]):
        """Save metadata to JSON file"""
        metadata_path = self._get_metadata_path()
        try:
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            print(f"✅ Metadata saved: {metadata_path}")
        except Exception as e:
            print(f"Failed to save metadata: {e}")
    
    def _on_edit_metadata(self):
        """Handle edit metadata action - opens non-modal window"""
        # Create metadata editing window
        edit_window = QDialog(self)
        edit_window.setWindowTitle(f"메타데이터 편집 - {self.file_name}")
        edit_window.setModal(False)  # Non-modal
        edit_window.setFixedSize(600, 750)
        edit_window.setStyleSheet(self._get_dialog_style())
        
        layout = QVBoxLayout(edit_window)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Load existing metadata
        metadata = self._load_metadata()
        
        # Title
        title_label = QLabel("📝 Character 메타데이터 편집")
        title_label.setStyleSheet("color: #FFD700; font-size: 18px; font-weight: bold; margin-bottom: 15px;")
        layout.addWidget(title_label)
        
        # Character Name
        name_label = QLabel("📛 Character Name:")
        name_label.setStyleSheet("color: white; font-weight: bold; margin-bottom: 5px;")
        layout.addWidget(name_label)
        
        name_edit = QLineEdit()
        name_edit.setText(metadata.get("character_name", ""))
        name_edit.setStyleSheet("""
            QLineEdit {
                background-color: #2a2a2a;
                color: white;
                border: 1px solid #444;
                padding: 8px;
                font-size: 14px;
                border-radius: 4px;
            }
            QLineEdit:focus {
                border-color: #4a9eff;
            }
        """)
        name_edit.setPlaceholderText("캐릭터 이름을 입력하세요...")
        name_edit.setProperty("autocomplete_ignore", True)
        layout.addWidget(name_edit)
        
        # Character Prompt
        prompt_label = QLabel("💬 Character Prompt:")
        prompt_label.setStyleSheet("color: white; font-weight: bold; margin-bottom: 5px; margin-top: 10px;")
        layout.addWidget(prompt_label)
        
        prompt_edit = QTextEdit()
        prompt_edit.setPlainText(metadata.get("character_prompt", ""))
        prompt_edit.setStyleSheet("""
            QTextEdit {
                background-color: #2a2a2a;
                color: white;
                border: 1px solid #444;
                padding: 8px;
                font-size: 14px;
                border-radius: 4px;
            }
            QTextEdit:focus {
                border-color: #4a9eff;
            }
        """)
        prompt_edit.setPlaceholderText("girl, blonde hair, blue eyes...")
        prompt_edit.setMinimumHeight(100)
        layout.addWidget(prompt_edit)
        
        # Character UC
        uc_label = QLabel("🚫 Undesired Content:")
        uc_label.setStyleSheet("color: white; font-weight: bold; margin-bottom: 5px; margin-top: 10px;")
        layout.addWidget(uc_label)
        
        uc_edit = QTextEdit()
        uc_edit.setPlainText(metadata.get("character_uc", ""))
        uc_edit.setStyleSheet("""
            QTextEdit {
                background-color: #2a2a2a;
                color: white;
                border: 1px solid #444;
                padding: 8px;
                font-size: 14px;
                border-radius: 4px;
            }
            QTextEdit:focus {
                border-color: #4a9eff;
            }
        """)
        uc_edit.setPlaceholderText("lowres, huge breasts, wide hips, ...")
        uc_edit.setMinimumHeight(50)
        layout.addWidget(uc_edit)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        
        button_layout.addStretch()
        
        # Save button
        save_btn = QPushButton("💾 수정")
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #2d5aa0;
                color: white;
                border: 1px solid #4a7bc8;
                padding: 10px 20px;
                font-weight: bold;
                border-radius: 4px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #3d6bb0;
            }
            QPushButton:pressed {
                background-color: #1d4a90;
            }
        """)
        
        def on_save():
            # Update metadata
            updated_metadata = {
                "character_name": name_edit.text().strip(),
                "character_prompt": prompt_edit.toPlainText().strip(),
                "character_uc": uc_edit.toPlainText().strip(),
                "file_name": self.file_name,
                "file_hash": self.file_hash
            }
            self._save_metadata(updated_metadata)
            
            # Update UI immediately
            self._update_name_label()
            
            # Success message
            msg_box = QMessageBox(edit_window)
            msg_box.setIcon(QMessageBox.Icon.Information)
            msg_box.setWindowTitle("저장 완료")
            msg_box.setText("메타데이터가 성공적으로 저장되었습니다.")
            msg_box.setStyleSheet(self._get_messagebox_style())
            msg_box.exec()
        
        save_btn.clicked.connect(on_save)
        button_layout.addWidget(save_btn)
        
        # Close button
        close_btn = QPushButton("❌ 닫기")
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #3a3a3a;
                color: white;
                border: 1px solid #555;
                padding: 10px 20px;
                border-radius: 4px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #4a4a4a;
            }
            QPushButton:pressed {
                background-color: #2a2a2a;
            }
        """)
        close_btn.clicked.connect(edit_window.close)
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)
        
        # Show window (non-modal)
        edit_window.show()
        edit_window.raise_()
        edit_window.activateWindow()
    
    def _get_dialog_style(self) -> str:
        """Get consistent dialog styling"""
        return """
            QDialog {
                background-color: #1a1a1a;
                color: white;
            }
            QLabel {
                color: white;
            }
            QLineEdit {
                background-color: #2a2a2a;
                color: white;
                border: 1px solid #444;
                padding: 5px;
            }
            QPushButton {
                background-color: #3a3a3a;
                color: white;
                border: 1px solid #555;
                padding: 5px 10px;
            }
            QPushButton:hover {
                background-color: #4a4a4a;
            }
        """
    
    def _get_messagebox_style(self) -> str:
        """Get consistent message box styling"""
        return """
            QMessageBox {
                background-color: #1a1a1a;
                color: white;
            }
            QMessageBox QLabel {
                color: white;
            }
            QMessageBox QPushButton {
                background-color: #3a3a3a;
                color: white;
                border: 1px solid #555;
                padding: 5px 15px;
                min-width: 60px;
            }
            QMessageBox QPushButton:hover {
                background-color: #4a4a4a;
            }
        """
                    
    def _on_delete(self):
        """Handle delete action"""
        # Delete without confirmation (like VibeStorageItem)
        try:
            # Delete image file
            if self.image_path.exists():
                self.image_path.unlink()
                print(f"✅ Deleted character reference image: {self.image_path}")
            
            # Remove widget and refresh parent window
            self._refresh_parent_window()
            self.deleteLater()
            
        except Exception as e:
            print(f"Failed to delete file: {e}")
    
    def _refresh_parent_window(self):
        """Refresh the parent CharacterStorageWindow to reorganize grid"""
        # Find parent CharacterStorageWindow
        parent = self.parent()
        while parent:
            if isinstance(parent, CharacterStorageWindow):
                parent.load_storage_items()  # This will reorganize the grid
                break
            parent = parent.parent()


class CharacterStorageWindow(QDialog):
    """Storage window for managing saved character references"""
    
    apply_character = pyqtSignal(str, str, str)  # file_hash, file_name, image_path
    
    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.setWindowTitle("📦 Character Reference Storage")
        self.setModal(False)
        
        # Fixed window size (same as vibe transfer)
        window_width = 1420  # 270*5 + padding
        window_height = 700
        self.setFixedSize(window_width, window_height)
        
        # Apply dark theme
        self.setStyleSheet("""
            QDialog {
                background-color: #0a0a0a;
            }
            QScrollArea {
                background-color: #0a0a0a;
                border: none;
            }
            QScrollBar:vertical {
                width: 12px;
                background: #1a1a1a;
            }
            QScrollBar::handle:vertical {
                background: #444;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical:hover {
                background: #555;
            }
        """)
        
        self.setup_ui()
        self.load_storage_items()
    
    def setup_ui(self):
        """Setup the UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(get_scaled_size(10))
        layout.setContentsMargins(get_scaled_size(10), get_scaled_size(10), get_scaled_size(10), get_scaled_size(10))
        
        # Title and folder button layout
        title_layout = QHBoxLayout()
        title_layout.setSpacing(get_scaled_size(10))
        
        title_label = QLabel("📦 Character Reference Storage")
        title_label.setStyleSheet(f"color: #FFD700; font-size: {get_scaled_font_size(24)}px; font-weight: bold;")
        title_layout.addWidget(title_label)
        
        title_layout.addStretch()
        
        # Folder open button
        folder_btn = QPushButton("📁 폴더 열기")
        folder_btn.setFixedHeight(get_scaled_size(40))
        folder_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #2d5aa0;
                color: white;
                border: 1px solid #4a7bc8;
                padding: {get_scaled_size(8)}px {get_scaled_size(16)}px;
                font-weight: bold;
                border-radius: {get_scaled_size(4)}px;
                font-size: {get_scaled_font_size(16)}px;
            }}
            QPushButton:hover {{
                background-color: #3d6bb0;
            }}
            QPushButton:pressed {{
                background-color: #1d4a90;
            }}
        """)
        folder_btn.clicked.connect(self._open_storage_folder)
        title_layout.addWidget(folder_btn)
        
        layout.addLayout(title_layout)
        
        # Scroll area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        
        # Container for grid
        self.container_widget = QWidget()
        self.container_widget.setStyleSheet("QWidget { background-color: #0a0a0a; }")
        self.grid_layout = QGridLayout(self.container_widget)
        self.grid_layout.setSpacing(get_scaled_size(10))
        self.grid_layout.setContentsMargins(get_scaled_size(10), get_scaled_size(10), get_scaled_size(10), get_scaled_size(10))
        self.grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        
        scroll_area.setWidget(self.container_widget)
        layout.addWidget(scroll_area)
    
    def load_storage_items(self):
        """Load character reference items from storage"""
        # Clear existing items
        for i in reversed(range(self.grid_layout.count())):
            child = self.grid_layout.itemAt(i).widget()
            if child:
                child.deleteLater()
        
        # Load images from storage folder
        images_folder = Path("save/character_reference/images")
        if not images_folder.exists():
            return
        
        # Get all image files
        image_files = []
        for ext in ['*.png', '*.jpg', '*.jpeg', '*.bmp', '*.gif', '*.webp']:
            image_files.extend(images_folder.glob(ext))
        
        col = 0
        row = 0
        max_cols = 5  # 5 columns like vibe transfer
        
        for image_file in sorted(image_files, key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                file_hash = image_file.stem
                file_name = image_file.name
                
                # Create storage item
                item = CharacterStorageItem(file_hash, file_name, image_file, self.app_context)
                item.apply_requested.connect(self.apply_character.emit)
                
                self.grid_layout.addWidget(item, row, col)
                
                col += 1
                if col >= max_cols:
                    col = 0
                    row += 1
                    
            except Exception as e:
                print(f"Failed to load character reference {image_file}: {e}")
    
    def _open_storage_folder(self):
        """Open the character reference storage folder in file explorer"""
        import os
        import subprocess
        import platform
        
        try:
            # Get the storage folder path
            images_folder = Path("save/character_reference/images")
            
            # Create folder if it doesn't exist
            images_folder.mkdir(parents=True, exist_ok=True)
            
            # Convert to absolute path
            folder_path = images_folder.resolve()
            
            # Open folder based on operating system
            system = platform.system()
            if system == "Windows":
                os.startfile(folder_path)
            elif system == "Darwin":  # macOS
                subprocess.run(["open", folder_path])
            else:  # Linux
                subprocess.run(["xdg-open", folder_path])
            
            print(f"✅ Opened storage folder: {folder_path}")
            
        except Exception as e:
            print(f"❌ Failed to open storage folder: {e}")
            # Show error message
            from PyQt6.QtWidgets import QMessageBox
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Icon.Warning)
            msg_box.setWindowTitle("오류")
            msg_box.setText(f"폴더를 열 수 없습니다: {str(e)}")
            msg_box.setStyleSheet("""
                QMessageBox {
                    background-color: #1a1a1a;
                    color: white;
                }
                QMessageBox QLabel {
                    color: white;
                }
                QMessageBox QPushButton {
                    background-color: #3a3a3a;
                    color: white;
                    border: 1px solid #555;
                    padding: 5px 15px;
                    min-width: 60px;
                }
                QMessageBox QPushButton:hover {
                    background-color: #4a4a4a;
                }
            """)
            msg_box.exec()


class CharacterReferenceModule(BaseMiddleModule, ModeAwareModule):
    """Character Reference module for NAID4.5F/NAID4.5C models"""
    
    def __init__(self):
        super().__init__()
        self.character_frames = []  # List of CharacterReferenceFrame instances
        self.app_context = None
        self.storage_window = None  # Storage window instance
        
        # Compatibility flags
        self.NAI_compatibility = True
        self.WEBUI_compatibility = False
        self.COMFYUI_compatibility = False
        
    def get_title(self) -> str:
        return "📸 Character Reference"
    
    def get_order(self) -> int:
        return 115  # After vibe transfer module (110)
    
    def get_module_name(self) -> str:
        return "CharacterReferenceModule"
    
    def initialize_with_context(self, context: AppContext):
        self.app_context = context
    
    def collect_current_settings(self) -> Dict[str, Any]:
        """Collect current module settings"""
        frames_data = []
        for frame in self.character_frames:
            frames_data.append({
                "file_path": frame.file_path,
                "file_hash": frame.file_hash,
                "style_aware": frame.style_aware,
                "fidelity": frame.fidelity,
                "is_enabled": frame.is_enabled
            })

        return {
            "frames": frames_data
        }
    
    def apply_settings(self, settings: Dict[str, Any]):
        """Apply settings (currently not needed as frames save individually)"""
        pass
    
    def create_widget(self, parent: QWidget) -> QWidget:
        """Create the main widget for this module"""
        dynamic_styles = get_dynamic_styles()
        
        # Main container
        main_widget = QWidget(parent)
        main_widget.setStyleSheet(f"""
            QWidget {{
                background-color: transparent;
                color: white;
            }}
        """)
        
        layout = QVBoxLayout(main_widget)
        layout.setSpacing(get_scaled_size(8))
        layout.setContentsMargins(get_scaled_size(10), get_scaled_size(10), get_scaled_size(10), get_scaled_size(10))
        
        # Title
        title_label = QLabel("📸 Character Reference (NAID4.5F/C Only)")
        title_label.setStyleSheet(f"""
            color: #FFD700;
            font-size: {get_scaled_font_size(24)}px;
            font-weight: bold;
            margin-bottom: {get_scaled_size(10)}px;
        """)
        layout.addWidget(title_label)
        
        # Control buttons
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(get_scaled_size(8))
        
        # Upload image button
        upload_btn = QPushButton("📁 Upload Image")
        upload_btn.setFixedHeight(get_scaled_size(40))
        upload_btn.setStyleSheet(dynamic_styles['primary_button'])
        upload_btn.clicked.connect(self._on_upload_image)
        controls_layout.addWidget(upload_btn)
        
        # Clipboard image button
        clipboard_btn = QPushButton("📋 From Clipboard")
        clipboard_btn.setFixedHeight(get_scaled_size(40))
        clipboard_btn.setStyleSheet(dynamic_styles['secondary_button'])
        clipboard_btn.clicked.connect(self._on_clipboard_image)
        controls_layout.addWidget(clipboard_btn)
        
        controls_layout.addStretch()
        
        # Storage button
        self.storage_btn = QPushButton("📦 Storage")
        self.storage_btn.setFixedHeight(get_scaled_size(40))
        self.storage_btn.setStyleSheet(dynamic_styles['secondary_button'])
        self.storage_btn.clicked.connect(self._on_storage_clicked)
        controls_layout.addWidget(self.storage_btn)
        
        layout.addLayout(controls_layout)
        
        # Scroll area for character frames
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setStyleSheet(f"""
            QScrollArea {{
                border: 1px solid #444;
                border-radius: 4px;
                background-color: #1a1a1a;
            }}
            QScrollBar:vertical {{
                background-color: #2a2a2a;
                width: {get_scaled_size(12)}px;
                border-radius: {get_scaled_size(6)}px;
            }}
            QScrollBar::handle:vertical {{
                background-color: #555;
                border-radius: {get_scaled_size(6)}px;
                min-height: {get_scaled_size(20)}px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: #666;
            }}
        """)
        
        # Container for character frames
        self.frames_container = QWidget()
        self.frames_layout = QVBoxLayout(self.frames_container)
        self.frames_layout.setSpacing(get_scaled_size(8))
        self.frames_layout.setContentsMargins(get_scaled_size(8), get_scaled_size(8), get_scaled_size(8), get_scaled_size(8))
        
        # Add stretch to push frames to top
        self.frames_layout.addStretch()
        
        scroll_area.setWidget(self.frames_container)
        scroll_area.setMinimumHeight(get_scaled_size(460))  # Min height for at least 2 frames
        layout.addWidget(scroll_area)
        
        return main_widget
    
    def _on_upload_image(self):
        """Handle upload image button click"""
        file_dialog = QFileDialog()
        file_path, _ = file_dialog.getOpenFileName(
            None,
            "Select Character Reference Image",
            "",
            "Image Files (*.png *.jpg *.jpeg *.bmp *.gif *.webp)"
        )
        
        if file_path:
            self._add_character_frame(file_path)
    
    def _on_clipboard_image(self):
        """Handle clipboard image button click"""
        from PyQt6.QtGui import QClipboard
        
        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData()
        
        if mime_data.hasImage():
            image = clipboard.image()
            if not image.isNull():
                # Save clipboard image to temp file
                temp_folder = Path("save/character_reference/temp")
                temp_folder.mkdir(parents=True, exist_ok=True)
                
                import time
                temp_file = temp_folder / f"clipboard_{int(time.time())}.png"
                
                # Convert QImage to PIL Image and save
                qimage = image.convertToFormat(QImage.Format.Format_RGB888)
                width = qimage.width()
                height = qimage.height()
                
                # Convert to bytes and create PIL Image
                buffer = qimage.bits().asstring(qimage.sizeInBytes())
                pil_image = Image.frombytes("RGB", (width, height), buffer)
                pil_image.save(temp_file)
                
                self._add_character_frame(str(temp_file))
            else:
                # Warning message with dark theme
                msg_box = QMessageBox()
                msg_box.setIcon(QMessageBox.Icon.Warning)
                msg_box.setWindowTitle("Warning")
                msg_box.setText("No valid image found in clipboard.")
                msg_box.setStyleSheet("""
                    QMessageBox {
                        background-color: #1a1a1a;
                        color: white;
                    }
                    QMessageBox QLabel {
                        color: white;
                    }
                    QMessageBox QPushButton {
                        background-color: #3a3a3a;
                        color: white;
                        border: 1px solid #555;
                        padding: 5px 15px;
                        min-width: 60px;
                    }
                    QMessageBox QPushButton:hover {
                        background-color: #4a4a4a;
                    }
                """)
                msg_box.exec()
        else:
            # Warning message with dark theme
            msg_box = QMessageBox()
            msg_box.setIcon(QMessageBox.Icon.Warning)
            msg_box.setWindowTitle("Warning")
            msg_box.setText("No image found in clipboard.")
            msg_box.setStyleSheet("""
                QMessageBox {
                    background-color: #1a1a1a;
                    color: white;
                }
                QMessageBox QLabel {
                    color: white;
                }
                QMessageBox QPushButton {
                    background-color: #3a3a3a;
                    color: white;
                    border: 1px solid #555;
                    padding: 5px 15px;
                    min-width: 60px;
                }
                QMessageBox QPushButton:hover {
                    background-color: #4a4a4a;
                }
            """)
            msg_box.exec()
    
    def _add_character_frame(self, file_path: str) -> Optional[CharacterReferenceFrame]:
        """Add a new character reference frame"""
        try:
            frame = CharacterReferenceFrame(file_path, self.app_context, self.frames_container)
            frame.removed.connect(self._remove_frame)
            
            self.character_frames.append(frame)
            
            # Insert before the stretch
            self.frames_layout.insertWidget(len(self.character_frames) - 1, frame)
            
            return frame
            
        except Exception as e:
            # Error message with dark theme
            msg_box = QMessageBox()
            msg_box.setIcon(QMessageBox.Icon.Critical)
            msg_box.setWindowTitle("Error")
            msg_box.setText(f"Failed to add character reference: {str(e)}")
            msg_box.setStyleSheet("""
                QMessageBox {
                    background-color: #1a1a1a;
                    color: white;
                }
                QMessageBox QLabel {
                    color: white;
                }
                QMessageBox QPushButton {
                    background-color: #3a3a3a;
                    color: white;
                    border: 1px solid #555;
                    padding: 5px 15px;
                    min-width: 60px;
                }
                QMessageBox QPushButton:hover {
                    background-color: #4a4a4a;
                }
            """)
            msg_box.exec()
            return None
    
    def _remove_frame(self, frame: CharacterReferenceFrame):
        """Remove a character reference frame"""
        if frame in self.character_frames:
            self.character_frames.remove(frame)
            self.frames_layout.removeWidget(frame)
            frame.deleteLater()
    
    def _on_storage_clicked(self):
        """Handle storage button click"""
        if not self.storage_window:
            self.storage_window = CharacterStorageWindow(self.app_context, self.widget if hasattr(self, 'widget') else None)
            self.storage_window.apply_character.connect(self._on_apply_character_from_storage)
        
        self.storage_window.load_storage_items()  # Reload items to get latest
        self.storage_window.show()
        self.storage_window.raise_()
        self.storage_window.activateWindow()
    
    def _on_apply_character_from_storage(self, file_hash: str, file_name: str, image_path: str):
        """Apply character reference from storage"""
        try:
            # Add the character frame
            frame = self._add_character_frame(image_path)
            
            if frame:
                # Enable this frame (single selection) with default settings
                frame.enable_check.setChecked(True)
                frame.is_enabled = True
                frame._update_enabled_display()
                
                # Style Aware defaults to True (user can change if needed)
                frame.style_aware_check.setChecked(True)
                frame.style_aware = True
                    
                # Success message with dark theme
                msg_box = QMessageBox()
                msg_box.setIcon(QMessageBox.Icon.Information)
                msg_box.setWindowTitle("Applied")
                msg_box.setText(f"Character reference '{file_name}' has been applied.")
                msg_box.setStyleSheet("""
                    QMessageBox {
                        background-color: #1a1a1a;
                        color: white;
                    }
                    QMessageBox QLabel {
                        color: white;
                    }
                    QMessageBox QPushButton {
                        background-color: #3a3a3a;
                        color: white;
                        border: 1px solid #555;
                        padding: 5px 15px;
                        min-width: 60px;
                    }
                    QMessageBox QPushButton:hover {
                        background-color: #4a4a4a;
                    }
                """)
                msg_box.exec()
            
        except Exception as e:
            # Error message with dark theme
            msg_box = QMessageBox()
            msg_box.setIcon(QMessageBox.Icon.Critical)
            msg_box.setWindowTitle("Error")
            msg_box.setText(f"Failed to apply character reference: {str(e)}")
            msg_box.setStyleSheet("""
                QMessageBox {
                    background-color: #1a1a1a;
                    color: white;
                }
                QMessageBox QLabel {
                    color: white;
                }
                QMessageBox QPushButton {
                    background-color: #3a3a3a;
                    color: white;
                    border: 1px solid #555;
                    padding: 5px 15px;
                    min-width: 60px;
                }
                QMessageBox QPushButton:hover {
                    background-color: #4a4a4a;
                }
            """)
            msg_box.exec()
    
    def get_parameters(self) -> Dict[str, Any]:
        """Get Character Reference API parameters"""
        # Check if current model is supported
        if not self._is_naid45_model():
            return {}
        
        # Find the active frame (single selection)
        active_frame = None
        for frame in self.character_frames:
            if frame.is_enabled:
                active_frame = frame
                break
        
        if not active_frame:
            return {}
        
        # Get character data
        char_data = active_frame.get_character_data()
        if not char_data:
            return {}
        
        # Build API parameters based on Style Aware setting
        if char_data["style_aware"]:
            descriptions = [{
                "caption": {
                    "base_caption": "character&style",
                    "char_captions": []
                },
                "legacy_uc": False
            }]
        else:
            descriptions = [{
                "caption": {
                    "base_caption": "character",
                    "char_captions": []
                },
                "legacy_uc": False
            }]
        
        return {
            "director_reference_descriptions": descriptions,
            "director_reference_images": [char_data["image_data"]],
            "director_reference_information_extracted": [1],
            "director_reference_secondary_strength_values": [char_data["fidelity"]],
            "director_reference_strength_values": [1],
            "controlnet_strength": 1,
            "inpaintImg2ImgStrength": 1,
            "normalize_reference_strength_multiple": True
        }
    
    def _is_naid45_model(self) -> bool:
        """Check if current model is NAID4.5F or NAID4.5C"""
        try:
            if hasattr(self.app_context, 'main_window') and hasattr(self.app_context.main_window, 'model_combo'):
                current_text = self.app_context.main_window.model_combo.currentText()
                return "NAID4.5F" in current_text or "NAID4.5C" in current_text
        except Exception as e:
            print(f"Failed to get current model: {e}")
        return False

