import os
import hashlib
import base64
import io
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, 
    QPushButton, QScrollArea, QCheckBox, QFileDialog,
    QMessageBox, QApplication, QDialog, QTabWidget, QGridLayout,
    QMenu, QInputDialog, QSizePolicy
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
        
        # Style Aware checkbox (replaces IE/IRS sliders)
        style_aware_label = QLabel("Style Aware")
        style_aware_label.setStyleSheet(f"color: white; font-size: {get_scaled_font_size(16)}px; font-weight: bold;")
        controls_layout.addWidget(style_aware_label)
        
        self.style_aware_check = QCheckBox("Include style information")
        self.style_aware_check.setChecked(self.style_aware)
        self.style_aware_check.setStyleSheet(dynamic_styles['dark_checkbox'])
        self.style_aware_check.toggled.connect(self._on_style_aware_changed)
        controls_layout.addWidget(self.style_aware_check)
        
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
        
        return {
            "image_data": self.image_data,
            "style_aware": self.style_aware,
            "file_path": self.file_path,
            "file_hash": self.file_hash
        }


class CharacterStorageItem(QFrame):
    """Storage item widget for character reference display"""
    apply_requested = pyqtSignal(str, str, str)  # file_hash, file_name, image_path
    
    def __init__(self, file_hash: str, file_name: str, image_path: Path, parent=None):
        super().__init__(parent)
        self.file_hash = file_hash
        self.file_name = file_name
        self.image_path = image_path
        
        # Fixed size for grid layout (same as vibe transfer)
        self.setFixedSize(get_scaled_size(270), get_scaled_size(320))
        self.setStyleSheet("""
            QFrame {
                border: 1px solid #444;
                border-radius: 4px;
                background-color: #1a1a1a;
                padding: 8px;
            }
            QFrame:hover {
                border-color: #666;
                background-color: #2a2a2a;
            }
        """)
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup the UI for this storage item"""
        layout = QVBoxLayout(self)
        layout.setSpacing(get_scaled_size(8))
        layout.setContentsMargins(get_scaled_size(8), get_scaled_size(8), get_scaled_size(8), get_scaled_size(8))
        
        # Image preview
        self.image_label = QLabel()
        self.image_label.setFixedSize(get_scaled_size(240), get_scaled_size(200))
        self.image_label.setStyleSheet("QLabel { border: 1px solid #666; background: #0a0a0a; }")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Load and display image
        if self.image_path.exists():
            try:
                pil_image = Image.open(self.image_path)
                pil_image.thumbnail((240, 200), Image.Resampling.LANCZOS)
                
                # Convert to RGBA for consistent color handling (like vibe_transfer)
                if pil_image.mode != "RGBA":
                    pil_image = pil_image.convert("RGBA")
                qimage = ImageQt(pil_image)
                pixmap = QPixmap.fromImage(qimage)
                
                self.image_label.setPixmap(pixmap)
            except Exception as e:
                print(f"Failed to load image {self.image_path}: {e}")
                self.image_label.setText("Image Load Failed")
        else:
            self.image_label.setText("Image Not Found")
        
        layout.addWidget(self.image_label)
        
        # File name label
        name_label = QLabel(self.file_name[:30] + "..." if len(self.file_name) > 30 else self.file_name)
        name_label.setStyleSheet(f"color: white; font-size: {get_scaled_font_size(14)}px;")
        name_label.setWordWrap(True)
        layout.addWidget(name_label)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(get_scaled_size(4))
        
        apply_btn = QPushButton("Apply")
        apply_btn.setStyleSheet(get_dynamic_styles()['compact_button'])
        apply_btn.clicked.connect(self._on_apply_clicked)
        button_layout.addWidget(apply_btn)
        
        delete_btn = QPushButton("Delete")
        delete_btn.setStyleSheet(get_dynamic_styles()['compact_button'])
        delete_btn.clicked.connect(self._on_delete_clicked)
        button_layout.addWidget(delete_btn)
        
        layout.addLayout(button_layout)
    
    def _on_apply_clicked(self):
        """Handle apply button click"""
        self.apply_requested.emit(self.file_hash, self.file_name, str(self.image_path))
    
    def _on_delete_clicked(self):
        """Handle delete button click"""
        reply = QMessageBox.question(
            self, "Confirm Delete",
            f"Delete character reference '{self.file_name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # Delete image file
            try:
                if self.image_path.exists():
                    self.image_path.unlink()
                    print(f"✅ Deleted character reference image: {self.image_path}")
                
                # Remove from parent layout
                if self.parent() and self.parent().layout():
                    self.parent().layout().removeWidget(self)
                    self.deleteLater()
                    
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete image: {e}")


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
        
        # Title
        title_label = QLabel("📦 Character Reference Storage")
        title_label.setStyleSheet(f"color: #FFD700; font-size: {get_scaled_font_size(24)}px; font-weight: bold;")
        layout.addWidget(title_label)
        
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
                item = CharacterStorageItem(file_hash, file_name, image_file)
                item.apply_requested.connect(self.apply_character.emit)
                
                self.grid_layout.addWidget(item, row, col)
                
                col += 1
                if col >= max_cols:
                    col = 0
                    row += 1
                    
            except Exception as e:
                print(f"Failed to load character reference {image_file}: {e}")


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
                QMessageBox.warning(None, "Warning", "No valid image found in clipboard.")
        else:
            QMessageBox.warning(None, "Warning", "No image found in clipboard.")
    
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
            QMessageBox.critical(None, "Error", f"Failed to add character reference: {str(e)}")
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
                    
                QMessageBox.information(None, "Applied", f"Character reference '{file_name}' has been applied.")
            
        except Exception as e:
            QMessageBox.critical(None, "Error", f"Failed to apply character reference: {str(e)}")
    
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

