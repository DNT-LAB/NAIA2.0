import os
import json
import hashlib
import base64
import io
import requests
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, 
    QPushButton, QScrollArea, QCheckBox, QFileDialog, QSlider,
    QMessageBox, QApplication, QDialog, QTabWidget, QGridLayout,
    QMenu, QInputDialog, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QSize
from PyQt6.QtGui import QPixmap, QImage, QAction
from PIL import Image
from PIL.ImageQt import ImageQt
from interfaces.base_module import BaseMiddleModule
from interfaces.mode_aware_module import ModeAwareModule
from core.context import AppContext
from ui.theme import get_dynamic_styles
from ui.scaling_manager import get_scaled_font_size, get_scaled_size


def _get_current_model_from_context(app_context) -> str:
    """AppContext에서 현재 선택된 모델명을 반환하는 공용 헬퍼"""
    try:
        if hasattr(app_context, 'main_window') and hasattr(app_context.main_window, 'model_combo'):
            current_text = app_context.main_window.model_combo.currentText()
            return current_text.replace("/", "_").replace("\\", "_").replace(":", "").replace(
                "*", "").replace("?", "").replace('"', "").replace("<", "").replace(">", "").replace("|", "")
    except Exception as e:
        print(f"Failed to get current model: {e}")
    return "default"


def _is_naid3_model_from_context(app_context) -> bool:
    """현재 모델이 NAID3인지 확인하는 공용 헬퍼"""
    return "NAID3" in _get_current_model_from_context(app_context)


class VibeEncodingWorker(QThread):
    """Background worker for vibe encoding API calls"""
    encoding_finished = pyqtSignal(bool, str, dict)  # success, message, result

    # 모델명 → API 모델 ID 매핑
    MODEL_API_MAP = {
        'NAID4.5F': 'nai-diffusion-4-5-full',
        'NAID4.5C': 'nai-diffusion-4-5-curated',
        'NAID4.0F': 'nai-diffusion-4-full',
        'NAID4.0C': 'nai-diffusion-4-curated',
    }
    DEFAULT_MODEL = 'nai-diffusion-4-5-full'

    def __init__(self, image_data: str, info_extracted: float, access_token: str, model: str = None):
        super().__init__()
        self.image_data = image_data
        self.info_extracted = info_extracted
        self.access_token = access_token
        self.api_model = self.MODEL_API_MAP.get(model, self.DEFAULT_MODEL)

    def run(self):
        try:
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }

            data = {
                "image": self.image_data,
                "information_extracted": self.info_extracted,
                "model": self.api_model
            }
            
            response = requests.post(
                "https://image.novelai.net/ai/encode-vibe",
                json=data,
                headers=headers,
                timeout=180
            )
            response.raise_for_status()
            
            # Debug: Log response details
            print(f"Vibe encoding response status: {response.status_code}")
            print(f"Response content type: {response.headers.get('content-type', 'unknown')}")
            print(f"Response content length: {len(response.content)} bytes")
            
            # The response is binary data (the encoded vibe)
            # Show first 100 bytes as hex for debugging
            if response.content:
                hex_preview = response.content[:100].hex()
                print(f"Response binary preview (hex): {hex_preview[:200]}...")
                
            encoded_data = base64.b64encode(response.content).decode('utf-8')
            result = {
                str(self.info_extracted): encoded_data
            }
            
            self.encoding_finished.emit(True, "Encoding successful", result)
            
        except requests.exceptions.RequestException as e:
            self.encoding_finished.emit(False, f"API request failed: {str(e)}", {})
        except Exception as e:
            self.encoding_finished.emit(False, f"Encoding failed: {str(e)}", {})


class VibeTransferFrame(QFrame):
    """Individual vibe transfer frame widget"""
    
    removed = pyqtSignal(object)  # Signal when frame is removed
    encoding_requested = pyqtSignal(object, float)  # Signal when encoding is requested
    
    def __init__(self, file_path: str, app_context: AppContext, parent=None, is_no_image: bool = False, target_model: str = None):
        super().__init__(parent)
        self.app_context = app_context
        self.file_path = file_path
        self.file_name = os.path.basename(file_path)
        self.is_no_image = is_no_image  # Mark if this is a no_image type frame
        self.target_model = target_model  # For no_image frames, which model they're for
        
        # Only calculate hash and load image if not no_image
        if not self.is_no_image:
            self.file_hash = self._calculate_file_hash(file_path)
            # Load image
            self.image = Image.open(file_path)
            self.image_data = self._image_to_base64(self.image)
        else:
            # For no_image frames, use the path as hash
            self.file_hash = file_path.replace("no_image_", "")[:16]
            # Create a placeholder black image
            self.image = Image.new('RGB', (512, 512), color='black')
            self.image_data = ""
        
        # Vibe data
        self.vibe_encodings = {}  # {info_extracted_value: encoded_data}
        self.reference_strength = 0.6
        self.information_extracted = 1.0
        self.is_enabled = True
        
        # Check if NAID3 mode
        self.is_naid3 = self._is_naid3_model()
        
        # Load existing encodings if available (skip for no_image)
        if not self.is_no_image:
            self._load_existing_encodings()
        
        # For NAID3, automatically save with image data as encoding
        if self.is_naid3 and not self.vibe_encodings and not self.is_no_image:
            self._save_naid3_encoding()
        
        # Setup UI
        self._setup_ui()
        
    def _calculate_file_hash(self, file_path: str) -> str:
        """Calculate SHA-256 hash of file"""
        hash_sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_sha256.update(chunk)
        return hash_sha256.hexdigest()[:16]  # Use first 16 characters
        
    def _image_to_base64(self, image: Image.Image) -> str:
        """Convert PIL image to base64 string"""
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode('utf-8')
        
    def _get_current_model(self) -> str:
        return _get_current_model_from_context(self.app_context)

    def _is_naid3_model(self) -> bool:
        return _is_naid3_model_from_context(self.app_context)

    def _save_naid3_encoding(self):
        """Save NAID3 encoding with image data as the encoding value"""
        # For NAID3, use image data itself as encoding
        self.vibe_encodings[1.0] = self.image_data
        self._save_encodings()
    
    def _load_existing_encodings(self):
        """Load existing vibe encodings from JSON file if available"""
        current_model = self._get_current_model()
        vibe_folder = Path("save/vibe_transfer") / current_model
        if not vibe_folder.exists():
            return
            
        json_file = vibe_folder / f"{self.file_hash}.json"
        if json_file.exists():
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.vibe_encodings = {
                        float(k): v for k, v in data.get("encodings", {}).items()
                    }
            except Exception as e:
                print(f"Failed to load vibe encodings: {e}")
                
    def _save_encodings(self):
        """Save vibe encodings to JSON file and save resized image"""
        current_model = self._get_current_model()
        vibe_folder = Path("save/vibe_transfer") / current_model
        vibe_folder.mkdir(parents=True, exist_ok=True)
        
        # Create images subdirectory within model folder
        images_folder = vibe_folder / "images"
        images_folder.mkdir(parents=True, exist_ok=True)
        
        # Save resized image if it doesn't exist
        image_file = images_folder / f"{self.file_hash}.png"
        if not image_file.exists():
            try:
                # Resize image with longer side to 386px
                img_copy = self.image.copy()
                
                # Calculate new size maintaining aspect ratio
                width, height = img_copy.size
                if width > height:
                    new_width = 386
                    new_height = int(height * (386 / width))
                else:
                    new_height = 386
                    new_width = int(width * (386 / height))
                
                # Resize and save
                img_resized = img_copy.resize((new_width, new_height), Image.Resampling.LANCZOS)
                img_resized.save(image_file, "PNG")
                print(f"Saved resized image to: {image_file}")
            except Exception as e:
                print(f"Failed to save resized image: {e}")
        
        # Check if this is a volatile file (no_image_)
        is_volatile = self.file_name.startswith("no_image_")
        
        # Save JSON file
        json_file = vibe_folder / f"{self.file_hash}.json"
        data = {
            "file_path": self.file_path,
            "file_name": self.file_name,
            "file_hash": self.file_hash,
            "encodings": {str(k): v for k, v in self.vibe_encodings.items()},
            "volatile": is_volatile  # Mark as volatile if no_image_
        }
        
        try:
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Failed to save vibe encodings: {e}")
            
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
        
        # Fixed size for the frame to prevent resizing
        self.setFixedHeight(get_scaled_size(280))
        
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(get_scaled_size(4))  # Reduced spacing
        main_layout.setContentsMargins(get_scaled_size(6), get_scaled_size(6), get_scaled_size(6), get_scaled_size(6))  # Reduced margins
        
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
        
        # Encode button (hide for no_image frames)
        if not self.is_no_image:
            self.encode_btn = QPushButton("Encode:2")
            self.encode_btn.setFixedSize(get_scaled_size(130), get_scaled_size(40))
            self.encode_btn.setStyleSheet(dynamic_styles['primary_button'])
            self.encode_btn.setToolTip("Encode vibe")
            self.encode_btn.clicked.connect(self._on_encode_clicked)
            
            # Current vibe label (shows encoding value when already encoded)
            self.current_vibe_label = QLabel()
            self.current_vibe_label.setFixedSize(get_scaled_size(130), get_scaled_size(40))
            self.current_vibe_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.current_vibe_label.setStyleSheet(f"color: #4a9eff; font-size: {get_scaled_font_size(18)}px; font-weight: bold;")
            self.current_vibe_label.setVisible(False)  # Initially hidden
            
            top_row.addStretch()
            top_row.addWidget(self.encode_btn)
            top_row.addWidget(self.current_vibe_label)
        else:
            # For no_image frames, show a label indicating the source
            # Check if this is from metadata or from import
            if hasattr(self, 'file_path') and 'metadata' not in self.file_path.lower():
                # This is from .naiv4vibe import
                no_image_label = QLabel("📦 Noimage Vibe")
            else:
                # This is from metadata
                no_image_label = QLabel("📦 Metadata Vibe")
            no_image_label.setStyleSheet(f"color: #C8B8FF; font-size: {get_scaled_font_size(16)}px; font-weight: bold;")
            top_row.addStretch()
            top_row.addWidget(no_image_label)
        
        # Enable checkbox
        self.enable_check = QCheckBox("Enable")
        self.enable_check.setChecked(True)
        self.enable_check.setStyleSheet(dynamic_styles['dark_checkbox'])
        self.enable_check.toggled.connect(self._on_enabled_changed)
        top_row.addWidget(self.enable_check)
        
        # Store image label reference for enabling/disabling
        self.image_label = None
        
        main_layout.addLayout(top_row)
        
        # Content frame - boundary-less container for image and controls
        content_frame = QFrame()
        content_frame.setStyleSheet("QFrame { border: none; background: transparent; }")
        # Remove fixed height to allow content to fit naturally
        
        content_row = QHBoxLayout(content_frame)
        content_row.setSpacing(get_scaled_size(8))  # Horizontal spacing between image and controls
        content_row.setContentsMargins(0, 0, 0, 0)
        
        # Image preview - direct label without container
        self.image_label = QLabel()
        self.image_label.setFixedSize(164, 198)  # 112x154 aspect ratio
        self.image_label.setStyleSheet("QLabel { border: 1px solid #666; background: #1a1a1a; }")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Resize image to fit 112x154 while maintaining aspect ratio
        thumbnail = self.image.copy()
        thumbnail.thumbnail((164, 198), Image.Resampling.LANCZOS)
        
        # Convert to QPixmap
        qimage = self._pil_to_qimage(thumbnail)
        self.original_pixmap = QPixmap.fromImage(qimage)
        
        # Scale pixmap to fit label
        scaled_pixmap = self.original_pixmap.scaled(164, 198, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.image_label.setPixmap(scaled_pixmap)
        
        content_row.addWidget(self.image_label)
        
        # Controls column with fixed width
        controls_container = QFrame()
        controls_container.setStyleSheet("QFrame { border: none; background: transparent; }")
        controls_container.setMinimumWidth(get_scaled_size(300))
        controls_container.setMaximumWidth(get_scaled_size(400))
        
        controls_layout = QVBoxLayout(controls_container)
        controls_layout.setSpacing(get_scaled_size(2))  # Reduced spacing between controls
        controls_layout.setContentsMargins(0, 0, 0, 0)
        
        # Model compatibility label for no_image frames
        if self.is_no_image:
            # Determine which model this vibe is for
            model_name = self.target_model if self.target_model else self._get_current_model()
            model_display = model_name
            
            # Simplify model display name
            if "NAID4.5F" in model_name:
                model_display = "NAID4.5F"
            elif "NAID4.5C" in model_name:
                model_display = "NAID4.5C"
            elif "NAID4.0F" in model_name:
                model_display = "NAID4.0F"
            elif "NAID4.0C" in model_name:
                model_display = "NAID4.0C"
            elif "NAID3" in model_name:
                model_display = "NAID3"
            
            self.model_label = QLabel(f"✨ Model: {model_display}")
            self.model_label.setStyleSheet(f"""
                color: #FFD700;
                font-size: {get_scaled_font_size(16)}px;
                font-weight: bold;
                padding: {get_scaled_size(4)}px;
                background-color: rgba(255, 215, 0, 0.1);
                border: 1px solid #FFD700;
                border-radius: 4px;
            """)
            self.model_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            controls_layout.addWidget(self.model_label)
            controls_layout.addSpacing(get_scaled_size(4))
            
            # Check initial compatibility
            self._update_model_compatibility_display(self._get_current_model())
        else:
            self.model_label = None
        
        # Reference Strength
        self.ref_strength_label = QLabel(f"Reference Strength {self.reference_strength:.2f}")
        self.ref_strength_label.setStyleSheet(f"color: white; font-size: {get_scaled_font_size(16)}px;")
        self.ref_strength_label.setWordWrap(False)
        controls_layout.addWidget(self.ref_strength_label)
        
        self.ref_strength_slider = QSlider(Qt.Orientation.Horizontal)
        self.ref_strength_slider.setRange(-100, 100)
        self.ref_strength_slider.setValue(int(self.reference_strength * 100))
        self.ref_strength_slider.setFixedHeight(get_scaled_size(20))  # Fixed height to save space
        self.ref_strength_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 6px;
                background: #444;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #888;
                width: 12px;
                margin: -3px 0;
                border-radius: 6px;
            }
            QSlider::handle:horizontal:hover {
                background: #aaa;
            }
        """)
        self.ref_strength_slider.valueChanged.connect(
            lambda v: self._update_ref_strength(v / 100.0)
        )
        self.ref_strength_slider.wheelEvent = lambda e: e.ignore()
        controls_layout.addWidget(self.ref_strength_slider)
        
        # Information Extracted (hide for no_image frames)
        if not self.is_no_image:
            self.info_extracted_label = QLabel(f"Information Extracted {self.information_extracted:.2f}")
            self.info_extracted_label.setStyleSheet(f"color: white; font-size: {get_scaled_font_size(16)}px;")
            self.info_extracted_label.setWordWrap(False)
            controls_layout.addWidget(self.info_extracted_label)
            
            self.info_extracted_slider = QSlider(Qt.Orientation.Horizontal)
            self.info_extracted_slider.setRange(1, 100)
            self.info_extracted_slider.setValue(int(self.information_extracted * 100))
            self.info_extracted_slider.setFixedHeight(get_scaled_size(20))  # Fixed height to save space
            self.info_extracted_slider.setStyleSheet(self.ref_strength_slider.styleSheet())
            self.info_extracted_slider.valueChanged.connect(
                lambda v: self._update_info_extracted(v / 100.0)
            )
            self.info_extracted_slider.wheelEvent = lambda e: e.ignore()
            controls_layout.addWidget(self.info_extracted_slider)
        
        # Encoding status (hide for NAID3 and no_image)
        if not self.is_naid3 and not self.is_no_image:
            self.encoding_status_label = QLabel()
            self.encoding_status_label.setWordWrap(True)
            self.encoding_status_label.setStyleSheet(f"color: #888; font-size: {get_scaled_font_size(14)}px;")
            self._update_encoding_status()
            self._update_encode_button_visibility()  # Update button visibility on init
            controls_layout.addWidget(self.encoding_status_label)
        else:
            self.encoding_status_label = None
            if not self.is_no_image:
                self._update_encode_button_visibility()  # Still need to update button visibility for NAID3
        
        # Add small stretch to push content to top but not waste space
        controls_layout.addSpacing(get_scaled_size(4))
        content_row.addWidget(controls_container, 1)
        
        main_layout.addWidget(content_frame)
        
    def _pil_to_qimage(self, pil_image: Image.Image) -> QImage:
        """Convert PIL Image to QImage using PIL.ImageQt for proper color handling"""
        # Convert to RGBA for consistent handling
        if pil_image.mode != "RGBA":
            pil_image = pil_image.convert("RGBA")
        
        # Use PIL.ImageQt for proper conversion without color inversion
        return ImageQt(pil_image)
        
    def _update_ref_strength(self, value: float):
        """Update reference strength value"""
        self.reference_strength = value
        self.ref_strength_label.setText(f"Reference Strength {value:.2f}")
    
    def _update_model_compatibility_display(self, current_model: str):
        """Update model label color based on compatibility"""
        if not self.is_no_image or not self.model_label:
            return
        
        # Get the target model for this frame
        model_name = self.target_model if self.target_model else current_model
        
        # Simplify both model names for comparison
        def simplify_model_name(name):
            if "NAID4.5F" in name:
                return "NAID4.5F"
            elif "NAID4.5C" in name:
                return "NAID4.5C"
            elif "NAID4.0F" in name:
                return "NAID4.0F"
            elif "NAID4.0C" in name:
                return "NAID4.0C"
            elif "NAID3" in name:
                return "NAID3"
            return name
        
        simplified_target = simplify_model_name(model_name)
        simplified_current = simplify_model_name(current_model)
        
        # Check if models match
        if simplified_target == simplified_current:
            # Compatible - show in gold
            self.model_label.setStyleSheet(f"""
                color: #FFD700;
                font-size: {get_scaled_font_size(16)}px;
                font-weight: bold;
                padding: {get_scaled_size(4)}px;
                background-color: rgba(255, 215, 0, 0.1);
                border: 1px solid #FFD700;
                border-radius: 4px;
            """)
            self.model_label.setText(f"✨ Model: {simplified_target}")
        else:
            # Incompatible - show in red
            self.model_label.setStyleSheet(f"""
                color: #FF4444;
                font-size: {get_scaled_font_size(16)}px;
                font-weight: bold;
                padding: {get_scaled_size(4)}px;
                background-color: rgba(255, 0, 0, 0.1);
                border: 1px solid #FF4444;
                border-radius: 4px;
            """)
            self.model_label.setText(f"⚠️ Model: {simplified_target} (Incompatible)")
        
    def _update_info_extracted(self, value: float):
        """Update information extracted value"""
        self.information_extracted = value
        if not self.is_no_image:
            self.info_extracted_label.setText(f"Information Extracted {value:.2f}")
            self._update_encoding_status()
            self._update_encode_button_visibility()
        
    def _update_encoding_status(self):
        """Update encoding status label based on available encodings"""
        if self.is_naid3 or not self.encoding_status_label:
            return  # Skip for NAID3
            
        if self.vibe_encodings:
            available = [f"{v:.2f}" for v in sorted(self.vibe_encodings.keys())]
            self.encoding_status_label.setText(f"Available encodings: {', '.join(available)}")
            self.encoding_status_label.setStyleSheet(f"color: #4a9eff; font-size: {get_scaled_font_size(14)}px;")
        else:
            self.encoding_status_label.setText("Encoding required. This will cost 2 Anlas.")
            self.encoding_status_label.setStyleSheet(f"color: #ff9944; font-size: {get_scaled_font_size(14)}px;")
            
    def _update_encode_button_visibility(self):
        """Update encode button visibility and current vibe label based on whether current value is already encoded"""
        # Skip for no_image frames as they don't have encode buttons
        if self.is_no_image:
            return
            
        # For NAID3, always hide encode button and show vibe label
        if self.is_naid3:
            self.encode_btn.setVisible(False)
            # Always show current vibe label for NAID3
            if self.vibe_encodings:
                display_text = "NAID3"
                self.current_vibe_label.setText(display_text)
                self.current_vibe_label.setVisible(True)
            return
            
        # 부동소수점 직접 비교 대신 가장 가까운 키와의 거리로 판단
        if self.vibe_encodings:
            closest_key = min(self.vibe_encodings.keys(),
                              key=lambda k: abs(k - self.information_extracted))
            current_value_exists = abs(closest_key - self.information_extracted) < 1e-9
        else:
            closest_key = None
            current_value_exists = False

        # Update encode button visibility
        self.encode_btn.setVisible(not current_value_exists)

        # Update current vibe encoding label
        if current_value_exists and closest_key is not None:
            encoding_string = self.vibe_encodings[closest_key]
            if encoding_string:
                display_text = encoding_string[:8] if len(encoding_string) >= 8 else encoding_string
                self.current_vibe_label.setText(display_text)
                self.current_vibe_label.setVisible(True)
        else:
            # Hide the label when no matching encoding
            self.current_vibe_label.setVisible(False)
            
    def _on_encode_clicked(self):
        """Handle encode button click"""
        self.encoding_requested.emit(self, self.information_extracted)
        
    def _on_enabled_changed(self, checked: bool):
        """Handle enable checkbox change"""
        self.is_enabled = checked
        
        # Apply visual effect to image instead of disabling controls
        if self.image_label and self.original_pixmap:
            if checked:
                # Restore original image
                scaled_pixmap = self.original_pixmap.scaled(164, 198, 
                    Qt.AspectRatioMode.KeepAspectRatio, 
                    Qt.TransformationMode.SmoothTransformation)
                self.image_label.setPixmap(scaled_pixmap)
            else:
                # Darken the image by applying an overlay
                darkened_pixmap = self._create_darkened_pixmap(self.original_pixmap)
                scaled_pixmap = darkened_pixmap.scaled(164, 198,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
                self.image_label.setPixmap(scaled_pixmap)
                
    def _create_darkened_pixmap(self, pixmap: QPixmap) -> QPixmap:
        """Create a darkened version of the pixmap"""
        from PyQt6.QtGui import QPainter, QBrush, QColor
        
        # Create a copy of the pixmap
        darkened = QPixmap(pixmap)
        
        # Paint a semi-transparent black overlay
        painter = QPainter(darkened)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
        painter.fillRect(darkened.rect(), QBrush(QColor(0, 0, 0, 150)))  # 150/255 opacity black
        painter.end()
        
        return darkened
        
    def add_encoding(self, info_extracted: float, encoded_data: str):
        """Add a new encoding"""
        self.vibe_encodings[info_extracted] = encoded_data
        
        # Debug: Show what's being stored
        try:
            # Decode base64 to see raw bytes
            raw_bytes = base64.b64decode(encoded_data)
            print(f"Storing vibe encoding for {info_extracted:.2f}:")
            print(f"  - Base64 length: {len(encoded_data)} chars")
            print(f"  - Raw binary size: {len(raw_bytes)} bytes")
            print(f"  - First 8 chars (shown in label): {encoded_data[:8]}")
            # Show as hex for better visibility of binary data
            print(f"  - Binary preview (hex): {raw_bytes[:50].hex()}")
        except Exception as e:
            print(f"Debug decode error: {e}")
            
        self._save_encodings()
        self._update_encoding_status()
        self._update_encode_button_visibility()
        
    def get_vibe_data(self) -> Optional[Dict[str, Any]]:
        """Get vibe data for generation"""
        if not self.is_enabled or not self.vibe_encodings:
            return None
            
        # Find closest encoding to current info_extracted value
        closest_key = min(self.vibe_encodings.keys(), 
                         key=lambda x: abs(x - self.information_extracted))
        
        return {
            "image": self.image_data,
            "encoding": self.vibe_encodings[closest_key],
            "reference_strength": self.reference_strength,
            "information_extracted": closest_key
        }


class VibeStorageItem(QFrame):
    """Storage item widget for vibe display"""
    apply_requested = pyqtSignal(str, str, str, float)  # model, file_hash, file_name, selected_encoding
    
    def __init__(self, model: str, file_hash: str, file_name: str, image_path: Path, encodings: dict = None, parent=None):
        super().__init__(parent)
        self.model = model
        self.file_hash = file_hash
        self.file_name = file_name
        self.image_path = image_path
        self.encodings = encodings or {}  # Store available encodings
        
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
        
        self.setFixedSize(QSize(270, 380))  # Adjusted for 256x334 image + padding
        
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(4, 4, 4, 4)
        
        # File name label at top
        self.name_label = QLabel(file_name[:30] + "..." if len(file_name) > 30 else file_name)
        self.name_label.setStyleSheet(f"color: white; font-size: {get_scaled_font_size(14)}px;")
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setWordWrap(True)
        self.name_label.setMaximumHeight(get_scaled_size(40))
        layout.addWidget(self.name_label)
        
        # Image display
        self.image_label = QLabel()
        self.image_label.setFixedSize(256, 334)  # Adjusted size
        self.image_label.setStyleSheet("QLabel { border: 1px solid #444; background: #1a1a1a; }")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setScaledContents(False)
        
        # Load and display image
        self._load_image()
        layout.addWidget(self.image_label)
        
        # Install event filter for context menu
        self.installEventFilter(self)
        
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
        """Handle double-click to apply vibe with first available encoding"""
        if event.button() == Qt.MouseButton.LeftButton and self.encodings:
            # Apply with first available encoding value
            sorted_encodings = sorted(self.encodings.keys())
            if sorted_encodings:
                first_encoding = float(sorted_encodings[0])
                self._on_apply_with_value(first_encoding)
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
        
        # Create submenu for apply action with encoded values
        if self.encodings:
            apply_menu = QMenu("✨ Vibe 적용", self)
            apply_menu.setStyleSheet(menu.styleSheet())
            
            # Add encoded values sorted - no default option needed
            sorted_encodings = sorted(self.encodings.keys())
            for encoding_value in sorted_encodings:
                value_action = QAction(f"IE: {float(encoding_value):.2f}", self)
                value_action.triggered.connect(lambda checked, val=float(encoding_value): self._on_apply_with_value(val))
                apply_menu.addAction(value_action)
            
            menu.addMenu(apply_menu)
        else:
            # No encodings available - just add simple action
            apply_action = QAction("✨ Vibe 적용 (인코딩 필요)", self)
            apply_action.setEnabled(False)
            menu.addAction(apply_action)
        
        menu.addSeparator()
        
        rename_action = QAction("✏️ 파일명 변경", self)
        rename_action.triggered.connect(self._on_rename)
        menu.addAction(rename_action)
        
        delete_action = QAction("🗑️ 파일 삭제", self)
        delete_action.triggered.connect(self._on_delete)
        menu.addAction(delete_action)
        
        menu.exec(pos)
        
    def _on_apply_with_value(self, encoding_value: float):
        """Handle apply vibe action with specific encoding value"""
        self.apply_requested.emit(self.model, self.file_hash, self.file_name, encoding_value)
        
    def _on_rename(self):
        """Handle rename action.
        TODO(web-dialog): 원래 QInputDialog "파일명 변경" — Web Shell 입력 모달로 재구현 필요.
        현재는 차단 — 이름 변경은 Web Shell Vibe Transfer 패널에서 처리."""
        print(f"[Dialog/SKIPPED] Vibe 파일명 변경 dialog 차단 (file={self.file_name}) — Web Shell 재구현 예정")
        return
        # 아래 원본 흐름:
        dialog = QInputDialog(self)
        dialog.setWindowTitle("파일명 변경")
        dialog.setLabelText("새 파일명을 입력하세요:")
        dialog.setTextValue(self.file_name)
        ok = dialog.exec()
        new_name = dialog.textValue()

        if ok and new_name and new_name != self.file_name:
            # Update JSON file with new name
            json_path = Path("save/vibe_transfer") / self.model / f"{self.file_hash}.json"
            if json_path.exists():
                try:
                    with open(json_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    data['file_name'] = new_name
                    
                    with open(json_path, 'w', encoding='utf-8') as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                    
                    self.file_name = new_name
                    self.name_label.setText(new_name[:30] + "..." if len(new_name) > 30 else new_name)
                    QMessageBox.information(self, "성공", "파일명이 변경되었습니다.")
                except Exception as e:
                    QMessageBox.critical(self, "오류", f"파일명 변경 실패: {e}")
                    
    def _on_delete(self):
        """Handle delete action"""
        # Delete without confirmation
        try:
            # Delete JSON file
            json_path = Path("save/vibe_transfer") / self.model / f"{self.file_hash}.json"
            if json_path.exists():
                json_path.unlink()
            
            # Delete image file
            if self.image_path.exists():
                self.image_path.unlink()
            
            # Remove widget
            self.deleteLater()
            # Don't show success message
        except Exception as e:
            print(f"Failed to delete file: {e}")


class VibeStorageWindow(QDialog):
    """Storage window for managing saved vibes"""
    
    apply_vibe = pyqtSignal(str, str, str, float)  # model, file_hash, file_name, selected_encoding
    
    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.setWindowTitle("📦 Vibe Storage")
        self.setModal(False)
        
        # Fixed window size for 5 columns (270px * 5 + spacing + margins)
        window_width = 1420  # 270*5 + some padding for scrollbar and margins
        window_height = 700
        self.setFixedSize(window_width, window_height)
        
        # Store current model info
        self.current_model = self._get_current_model()
        self.is_naid3 = "NAID3" in self.current_model
        
        # Apply dark theme with black background
        self.setStyleSheet("""
            QDialog {
                background-color: #0a0a0a;
            }
            QTabWidget::pane {
                border: 1px solid #333;
                background-color: #0a0a0a;
            }
            QTabBar::tab {
                background-color: #1a1a1a;
                color: #cccccc;
                padding: 8px 16px;
                margin-right: 2px;
                border: 1px solid #333;
            }
            QTabBar::tab:selected {
                background-color: #2a5a8a;
                color: white;
            }
            QTabBar::tab:hover {
                background-color: #2a2a2a;
            }
            QScrollArea {
                background-color: #0a0a0a;
            }
            QWidget {
                background-color: #0a0a0a;
            }
        """)
        
        self.setup_ui()
        self.load_tabs()
        
    def setup_ui(self):
        """Setup the UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Tab widget
        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)
        
    def load_tabs(self):
        """Load tabs from vibe_transfer folder"""
        # Clear existing tabs first to avoid duplicates
        self.tab_widget.clear()
        
        vibe_folder = Path("save/vibe_transfer")
        if not vibe_folder.exists():
            vibe_folder.mkdir(parents=True, exist_ok=True)
            
        # Get all model folders
        model_folders = [f for f in vibe_folder.iterdir() if f.is_dir()]
        
        # Current model from main window
        current_model = self._get_current_model()
        current_index = 0
        
        for i, folder in enumerate(sorted(model_folders)):
            model_name = folder.name
            
            # Create scroll area for tab content
            scroll_area = QScrollArea()
            scroll_area.setWidgetResizable(True)
            scroll_area.setStyleSheet("""
                QScrollArea {
                    border: none;
                    background-color: #0a0a0a;
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
            
            # Create grid widget for items
            grid_widget = QWidget()
            grid_widget.setStyleSheet("QWidget { background-color: #0a0a0a; }")
            grid_layout = QGridLayout(grid_widget)
            grid_layout.setSpacing(10)
            grid_layout.setContentsMargins(10, 10, 10, 10)
            
            # Load items for this model
            self.load_model_items(model_name, grid_layout)
            
            scroll_area.setWidget(grid_widget)
            self.tab_widget.addTab(scroll_area, model_name)
            
            # Track current model tab index
            if model_name == current_model:
                current_index = i
                
        # Select current model tab
        if self.tab_widget.count() > 0:
            self.tab_widget.setCurrentIndex(current_index)
            
    def load_model_items(self, model: str, grid_layout: QGridLayout):
        """Load vibe items for a specific model"""
        model_folder = Path("save/vibe_transfer") / model
        images_folder = model_folder / "images"
        
        if not model_folder.exists():
            return
            
        # Get all JSON files
        json_files = list(model_folder.glob("*.json"))
        
        col = 0
        row = 0
        max_cols = 5  # 5 items per row
        
        for json_file in sorted(json_files):
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                # Skip volatile files in storage view
                if data.get("volatile", False):
                    continue
                    
                file_hash = data.get("file_hash", json_file.stem)
                file_name = data.get("file_name", "Unknown")
                encodings = data.get("encodings", {})
                
                # Image path
                image_path = images_folder / f"{file_hash}.png"
                
                # Create item widget with encodings
                item = VibeStorageItem(model, file_hash, file_name, image_path, encodings)
                item.apply_requested.connect(self.apply_vibe.emit)
                
                grid_layout.addWidget(item, row, col)
                
                col += 1
                if col >= max_cols:
                    col = 0
                    row += 1
                    
            except Exception as e:
                print(f"Failed to load {json_file}: {e}")
                
        # Add stretch to push items to top-left
        grid_layout.setRowStretch(row + 1, 1)
        grid_layout.setColumnStretch(max_cols, 1)
    
    def _get_current_model(self) -> str:
        return _get_current_model_from_context(self.app_context)


class VibeTransferModule(BaseMiddleModule, ModeAwareModule):
    """Vibe Transfer module for NAI image generation"""
    
    def __init__(self):
        BaseMiddleModule.__init__(self)
        ModeAwareModule.__init__(self)
        
        # ModeAwareModule required attributes
        self.settings_base_filename = "VibeTransferModule"
        self.current_mode = "NAI"
        
        # Compatibility settings (NAI only)
        self.NAI_compatibility = True
        self.WEBUI_compatibility = False
        self.COMFYUI_compatibility = False
        
        # Module attributes
        self.vibe_frames: List[VibeTransferFrame] = []
        self.normalize_strength = False
        self.encoding_worker = None
        self._encoding_target_frame: Optional[VibeTransferFrame] = None
        
        # UI references
        self.scroll_layout: QVBoxLayout = None
        self.normalize_checkbox: QCheckBox = None
        self.upload_btn: QPushButton = None
        self.clipboard_btn: QPushButton = None
        self.storage_btn: QPushButton = None
        self.storage_window: Optional[VibeStorageWindow] = None
        
        # Model tracking for NAID3 switching
        self._previous_model = None
        self._model_combo_connected = False  # Track connection state

        # Volatile file tracking
        self.volatile_files = {}  # {model: [file_hashes]}
        self._load_volatile_tracking()

        # Clean up volatile files on initialization
        self._cleanup_volatile_files()
        
    def get_title(self) -> str:
        return "✨ Vibe Transfer"
        
    def get_order(self) -> int:
        return 50
        
    def get_module_name(self) -> str:
        return self.get_title()
        
    def initialize_with_context(self, context: AppContext):
        """Initialize with app context"""
        self.app_context = context
    
    def on_initialize(self):
        """Called after widget creation - connect to model combo here"""
        if hasattr(self, 'app_context') and self.app_context:
            # Initialize previous model
            self._previous_model = self._get_current_model()

            # Connect to model combo changes if available (only if not already connected)
            if hasattr(self.app_context, 'main_window') and hasattr(self.app_context.main_window, 'model_combo'):
                if not self._model_combo_connected:
                    # Connect to model combo changes
                    self.app_context.main_window.model_combo.currentIndexChanged.connect(self._on_model_changed)
                    self._model_combo_connected = True
                    print(f"✅ VibeTransferModule: Connected to model_combo changes")
                else:
                    print(f"ℹ️ VibeTransferModule: Already connected to model_combo changes")

            # Refresh encoding states on initialization (for mode changes)
            if self.vibe_frames:
                print(f"🔄 VibeTransferModule: Refreshing encoding states on initialization")
                self._refresh_all_encoding_states()
        
    def collect_current_settings(self) -> Dict[str, Any]:
        """Collect current UI settings"""
        settings = {
            "normalize_strength": self.normalize_checkbox.isChecked() if self.normalize_checkbox else False,
            "vibe_frames": []
        }

        for frame in self.vibe_frames:
            entry = {
                "file_path": frame.file_path,
                "reference_strength": frame.reference_strength,
                "information_extracted": frame.information_extracted,
                "is_enabled": frame.is_enabled,
                "is_no_image": frame.is_no_image,
            }
            if frame.is_no_image:
                # 가상 경로는 파일이 없으므로 인코딩 데이터를 직접 저장
                entry["vibe_encodings"] = {str(k): v for k, v in frame.vibe_encodings.items()}
                entry["target_model"] = frame.target_model
            settings["vibe_frames"].append(entry)

        return settings
        
    def apply_settings(self, settings: Dict[str, Any]):
        """Apply settings to UI"""
        if self.normalize_checkbox:
            self.normalize_checkbox.setChecked(settings.get("normalize_strength", False))
            
        # Clear existing frames
        for frame in self.vibe_frames[:]:
            self._remove_frame(frame)

        # Restore frames
        for frame_data in settings.get("vibe_frames", []):
            is_no_image = frame_data.get("is_no_image", False)

            if is_no_image:
                # no_image 프레임: 저장된 인코딩 데이터로 직접 복원
                saved_encodings = frame_data.get("vibe_encodings", {})
                if not saved_encodings:
                    continue
                file_path = frame_data.get("file_path", "")
                per_hash = hashlib.sha256(file_path.encode()).hexdigest()[:16]
                no_image_path = f"no_image_restored_{per_hash}"
                per_vibe_data = {
                    'reference_image_multiple': list(saved_encodings.values()),
                    'reference_strength_multiple': [frame_data.get("reference_strength", 0.6)],
                    'reference_information_extracted_multiple': [float(k) for k in saved_encodings.keys()],
                    'source_model': frame_data.get("target_model", self._get_current_model()),
                }
                frame = self._add_vibe_frame_from_metadata(no_image_path, per_vibe_data)
                if frame:
                    frame.is_enabled = frame_data.get("is_enabled", True)
                    frame.enable_check.setChecked(frame.is_enabled)
            else:
                if not os.path.exists(frame_data["file_path"]):
                    continue
                frame = self._add_vibe_frame(frame_data["file_path"])
                if frame:
                    frame.reference_strength = frame_data.get("reference_strength", 0.6)
                    frame.information_extracted = frame_data.get("information_extracted", 1.0)
                    frame.is_enabled = frame_data.get("is_enabled", True)

                    # Update UI
                    frame.ref_strength_slider.setValue(int(frame.reference_strength * 100))
                    frame.info_extracted_slider.setValue(int(frame.information_extracted * 100))
                    frame.enable_check.setChecked(frame.is_enabled)

                    # Update labels
                    frame.ref_strength_label.setText(f"Reference Strength {frame.reference_strength:.2f}")
                    frame.info_extracted_label.setText(f"Information Extracted {frame.information_extracted:.2f}")
        
        # After applying settings (mode change), refresh encoding states
        self._refresh_all_encoding_states()
                    
    def create_widget(self, parent: QWidget) -> QWidget:
        """Create the module widget"""
        widget = QWidget(parent)
        main_layout = QVBoxLayout(widget)
        main_layout.setSpacing(get_scaled_size(10))
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        dynamic_styles = get_dynamic_styles()
        
        # Top controls
        top_controls = QFrame()
        top_controls.setStyleSheet("QFrame { border: none; background: transparent; }")
        top_layout = QVBoxLayout(top_controls)
        top_layout.setSpacing(get_scaled_size(8))
        top_layout.setContentsMargins(0, 0, 0, 0)
        
        # Buttons row
        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(get_scaled_size(8))
        
        self.upload_btn = QPushButton("📁 Upload Image")
        self.upload_btn.setStyleSheet(dynamic_styles['primary_button'])
        self.upload_btn.clicked.connect(self._on_upload_image)
        buttons_row.addWidget(self.upload_btn)
        
        self.clipboard_btn = QPushButton("📋 Copy Clipboard")
        self.clipboard_btn.setStyleSheet(dynamic_styles['secondary_button'])
        self.clipboard_btn.clicked.connect(self._on_clipboard_image)
        buttons_row.addWidget(self.clipboard_btn)
        
        self.import_vibe_btn = QPushButton("📥 .naiv4vibe")
        self.import_vibe_btn.setStyleSheet(dynamic_styles['secondary_button'])
        self.import_vibe_btn.clicked.connect(self._on_import_vibe)
        buttons_row.addWidget(self.import_vibe_btn)
        
        top_layout.addLayout(buttons_row)
        
        # Normalize checkbox and Storage button row
        checkbox_row = QHBoxLayout()
        checkbox_row.setSpacing(get_scaled_size(8))
        
        self.normalize_checkbox = QCheckBox("Normalize Reference Strength Values")
        self.normalize_checkbox.setStyleSheet(dynamic_styles['dark_checkbox'])
        # Don't set fixed height - let it use natural height
        checkbox_row.addWidget(self.normalize_checkbox)
        checkbox_row.addStretch()
        
        self.storage_btn = QPushButton("📦 Storage")
        self.storage_btn.setStyleSheet(dynamic_styles['secondary_button'])
        self.storage_btn.clicked.connect(self._on_storage_clicked)
        checkbox_row.addWidget(self.storage_btn)
        
        top_layout.addLayout(checkbox_row)
        
        main_layout.addWidget(top_controls)
        
        # Container frame for scroll area with minimum height
        scroll_container = QFrame()
        scroll_container.setStyleSheet("QFrame { border: none; background: transparent; }")
        scroll_container.setMinimumHeight(get_scaled_size(460))  # Min height for at least 2 frames
        
        scroll_container_layout = QVBoxLayout(scroll_container)
        scroll_container_layout.setContentsMargins(0, 0, 0, 0)
        
        # Scroll area for vibe frames
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollBar:vertical {
                width: 12px;
                background: #2a2a2a;
            }
            QScrollBar::handle:vertical {
                background: #555;
                border-radius: 6px;
            }
        """)
        
        # Inner scroll widget with proper frame container
        scroll_widget = QWidget()
        self.scroll_layout = QVBoxLayout(scroll_widget)
        self.scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_layout.setSpacing(get_scaled_size(8))
        self.scroll_layout.setContentsMargins(0, 0, get_scaled_size(4), 0)  # Right margin for scrollbar
        
        scroll_area.setWidget(scroll_widget)
        scroll_container_layout.addWidget(scroll_area)
        
        main_layout.addWidget(scroll_container)
        
        self.widget = widget
        return widget
        
    def _on_upload_image(self):
        """Handle upload image button"""
        file_path, _ = QFileDialog.getOpenFileName(
            self.widget,
            "Select Image",
            "",
            "Image Files (*.png *.jpg *.jpeg *.webp);;All Files (*.*)"
        )
        
        if file_path:
            self._add_vibe_frame(file_path)
            
    def _on_clipboard_image(self):
        """Handle clipboard image button"""
        clipboard = QApplication.clipboard()
        mimedata = clipboard.mimeData()
        
        if mimedata.hasImage():
            image = mimedata.imageData()
            if image:
                # 픽셀 데이터 기반으로 안정적인 해시 계산
                from PyQt6.QtCore import QBuffer, QIODevice
                buf = QBuffer()
                buf.open(QIODevice.OpenModeFlag.WriteOnly)
                QPixmap(image).save(buf, "PNG")
                img_bytes = buf.data().data()
                img_hash = hashlib.sha256(img_bytes).hexdigest()[:8]

                temp_path = Path("temp") / f"clipboard_vibe_{img_hash}.png"
                temp_path.parent.mkdir(exist_ok=True)

                if not temp_path.exists():
                    with open(str(temp_path), 'wb') as f:
                        f.write(img_bytes)

                self._add_vibe_frame(str(temp_path))
        else:
            QMessageBox.warning(self.widget, "Warning", "No image found in clipboard")
    
    def _on_import_vibe(self):
        """Handle .naiv4vibe import button"""
        file_path, _ = QFileDialog.getOpenFileName(
            self.widget,
            "Import .naiv4vibe or .naiv4vibebundle",
            "",
            "NAI Vibe Files (*.naiv4vibe *.naiv4vibebundle);;All Files (*.*)"
        )
        
        if file_path:
            self._import_vibe_file(file_path)
    
    def _import_vibe_file(self, filepath: str):
        """Import .naiv4vibe or .naiv4vibebundle file"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if filepath.endswith('.naiv4vibebundle'):
                # Handle bundle file
                if data.get('identifier') == 'novelai-vibe-transfer-bundle':
                    vibes = data.get('vibes', [])
                    processed_count = 0
                    
                    for vibe_data in vibes:
                        if vibe_data.get('identifier') == 'novelai-vibe-transfer':
                            if self._process_single_vibe(vibe_data):
                                processed_count += 1
                    
                    if processed_count == 0:
                        QMessageBox.warning(self.widget, "Warning", "No processable vibes found in bundle")
                    else:
                        print(f"Successfully imported {processed_count} vibes from bundle")
                else:
                    QMessageBox.warning(self.widget, "Warning", "Invalid bundle file format")
            else:
                # Handle single vibe file
                if data.get('identifier') == 'novelai-vibe-transfer':
                    if not self._process_single_vibe(data):
                        QMessageBox.warning(self.widget, "Warning", "Could not extract vibe data from file")
                else:
                    QMessageBox.warning(self.widget, "Warning", "Invalid vibe file format")
                    
        except Exception as e:
            QMessageBox.critical(self.widget, "Error", f"Failed to import file: {e}")
    
    def _process_single_vibe(self, vibe_data: dict) -> bool:
        """Process a single vibe data dictionary"""
        try:
            # Model mapping
            model_map = {
                'v4-5curated': 'NAID4.5C',
                'v4-5full': 'NAID4.5F',
                'v4curated': 'NAID4.0C',
                'v4full': 'NAID4.0F'
            }
            
            # Extract image if available
            image_data = vibe_data.get('image')
            image_path = None
            file_hash = None
            
            if image_data:
                # Decode base64 image
                image_bytes = base64.b64decode(image_data)
                file_hash = hashlib.sha256(image_bytes).hexdigest()[:16]  # Use first 16 characters
                
                # Save image temporarily
                temp_path = Path("temp") / f"imported_vibe_{file_hash[:8]}.png"
                temp_path.parent.mkdir(exist_ok=True)
                
                # Convert bytes to image and save
                from PIL import Image
                import io
                image = Image.open(io.BytesIO(image_bytes))
                image.save(str(temp_path))
                image_path = str(temp_path)
            else:
                # Create placeholder image
                temp_path = Path("temp") / f"no_image_{hashlib.sha256(str(vibe_data).encode()).hexdigest()[:8]}.png"
                temp_path.parent.mkdir(exist_ok=True)
                
                # Create black placeholder image
                from PIL import Image
                image = Image.new('RGB', (112, 112), 'black')
                image.save(str(temp_path))
                image_path = str(temp_path)
                file_hash = hashlib.sha256(open(temp_path, 'rb').read()).hexdigest()[:16]  # Use first 16 characters
            
            # Process encodings for each model
            encodings_data = vibe_data.get('encodings', {})
            imported_any = False
            
            for model_key, model_name in model_map.items():
                if model_key in encodings_data:
                    model_encodings = encodings_data[model_key]
                    
                    # Process each encoding entry
                    vibe_encodings = {}
                    for encoding_id, encoding_info in model_encodings.items():
                        if isinstance(encoding_info, dict):
                            encoding_value = encoding_info.get('encoding')
                            params = encoding_info.get('params', {})
                            info_extracted = params.get('information_extracted', 1.0)
                            
                            if encoding_value:
                                vibe_encodings[float(info_extracted)] = encoding_value
                    
                    if vibe_encodings:
                        # Save to storage for this model
                        self._save_imported_vibe(model_name, file_hash, image_path, vibe_encodings)
                        imported_any = True
            
            # Add frame if any encodings were imported
            # Extract importInfo.strength if present
            import_strength = None
            import_info = vibe_data.get('importInfo')
            if isinstance(import_info, dict):
                s = import_info.get('strength')
                if s is not None:
                    import_strength = float(s)

            if imported_any and image_path:
                # Check if this is a no_image case
                is_no_image = "no_image_" in image_path
                
                if is_no_image:
                    # Use the no_image frame creation method
                    # Prepare vibe data from imported encodings
                    current_model = self._get_current_model()
                    model_key = None
                    for key, name in model_map.items():
                        if name == current_model:
                            model_key = key
                            break
                    
                    if model_key and model_key in encodings_data:
                        # Extract vibe data for current model
                        model_encodings = encodings_data[model_key]
                        reference_image_multiple = []
                        reference_strength_multiple = []
                        
                        for encoding_id, encoding_info in model_encodings.items():
                            if isinstance(encoding_info, dict):
                                encoding_value = encoding_info.get('encoding')
                                params = encoding_info.get('params', {})
                                info_extracted = params.get('information_extracted', 1.0)
                                
                                if encoding_value:
                                    reference_image_multiple.append(encoding_value)
                                    reference_strength_multiple.append(float(info_extracted))
                        
                        if reference_image_multiple:
                            # Create no_image vibe data
                            vibe_data = {
                                'reference_image_multiple': reference_image_multiple,
                                'reference_strength_multiple': reference_strength_multiple
                            }
                            
                            # Use special no_image frame creation
                            no_image_path = f"no_image_{file_hash}"
                            frame = self._add_vibe_frame_from_noimage_import(no_image_path, vibe_data)
                            return frame is not None
                    
                    # Fallback to regular frame if can't extract current model data
                    frame = self._add_vibe_frame(image_path)
                else:
                    # Regular image frame
                    frame = self._add_vibe_frame(image_path)
                
                if frame:
                    # Load encodings for current model
                    current_model = self._get_current_model()
                    vibe_folder = Path("save/vibe_transfer") / current_model
                    json_file = vibe_folder / f"{file_hash}.json"

                    if json_file.exists():
                        with open(json_file, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        frame.vibe_encodings = {
                            float(k): v for k, v in data.get("encodings", {}).items()
                        }
                        if not is_no_image:
                            frame._update_encoding_status()
                            frame._update_encode_button_visibility()

                    # Apply importInfo.strength if available
                    if import_strength is not None:
                        frame.reference_strength = import_strength
                        frame.ref_strength_slider.setValue(int(import_strength * 100))
                        frame.ref_strength_label.setText(f"Reference Strength {import_strength:.2f}")

                return True
                
            return False
            
        except Exception as e:
            print(f"Error processing vibe: {e}")
            return False
    
    def _save_imported_vibe(self, model: str, file_hash: str, image_path: str, encodings: dict):
        """Save imported vibe to storage"""
        try:
            # Create directories
            vibe_folder = Path("save/vibe_transfer") / model
            vibe_folder.mkdir(parents=True, exist_ok=True)
            
            images_folder = vibe_folder / "images"
            images_folder.mkdir(exist_ok=True)
            
            # Copy image to storage
            image_storage_path = images_folder / f"{file_hash}.png"
            if not image_storage_path.exists():
                import shutil
                shutil.copy2(image_path, image_storage_path)
            
            # Check if this is a no_image_ file
            is_volatile = "no_image_" in str(image_path)
            
            # Save JSON data
            json_path = vibe_folder / f"{file_hash}.json"
            json_data = {
                "file_hash": file_hash,
                "file_path": image_path,
                "file_name": f"imported_{file_hash[:8]}",
                "encodings": {str(k): v for k, v in encodings.items()},
                "volatile": is_volatile
            }
            
            # Track volatile files
            if is_volatile:
                self._add_to_volatile_list(model, file_hash)
            
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(json_data, f, indent=2, ensure_ascii=False)
                
            print(f"Saved imported vibe to {model}/{file_hash} (volatile: {is_volatile})")
            
        except Exception as e:
            print(f"Error saving imported vibe: {e}")
            
    def _is_naid3_model(self) -> bool:
        return _is_naid3_model_from_context(self.app_context)
    
    def _add_vibe_frame(self, file_path: str) -> Optional[VibeTransferFrame]:
        """Add a new vibe transfer frame"""
        if len(self.vibe_frames) >= 8:
            QMessageBox.warning(self.widget, "Limit Reached", "Maximum 8 vibe frames allowed")
            return None
            
        try:
            # Calculate hash of the new image to check for duplicates
            new_hash = self._calculate_file_hash_static(file_path)
            
            # Check if this image already exists in current frames
            for existing_frame in self.vibe_frames:
                if existing_frame.file_hash == new_hash:
                    # Silently return existing frame without showing message
                    print(f"Image already loaded with encodings: {', '.join([f'{k:.2f}' for k in existing_frame.vibe_encodings.keys()]) if existing_frame.vibe_encodings else 'None'}")
                    return existing_frame
            
            # Check if this image exists in storage for current model
            current_model = self._get_current_model()
            vibe_folder = Path("save/vibe_transfer") / current_model
            json_file = vibe_folder / f"{new_hash}.json"
            
            if json_file.exists():
                # Load the existing data and inform user
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        encodings = data.get("encodings", {})
                        
                    if encodings:
                        # Automatically load with existing encodings without asking
                        print(f"Loading image with existing encodings: {', '.join([f'{k}' for k in encodings.keys()])}")
                except Exception as e:
                    print(f"Error reading existing vibe data: {e}")
            
            # Create new frame (will auto-load existing encodings if available)
            frame = VibeTransferFrame(file_path, self.app_context)
            frame.removed.connect(self._remove_frame)
            frame.encoding_requested.connect(self._on_encoding_requested)
            
            self.scroll_layout.addWidget(frame)
            self.vibe_frames.append(frame)
            
            return frame
            
        except Exception as e:
            QMessageBox.critical(self.widget, "Error", f"Failed to add image: {str(e)}")
            return None
    
    def _add_vibe_frame_from_noimage_import(self, no_image_path: str, vibe_data: dict) -> Optional[VibeTransferFrame]:
        """Add a vibe frame from imported .naiv4vibe file without image"""
        if len(self.vibe_frames) >= 8:
            QMessageBox.warning(self.widget, "Limit Reached", "Maximum 8 vibe frames allowed")
            return None

        try:
            # Handle None values
            ref_img_multiple = vibe_data.get('reference_image_multiple') or []
            ref_ie_multiple = vibe_data.get('reference_information_extracted_multiple') or []

            # Early return if no valid vibe data
            if not ref_img_multiple:
                print(f"⚠️ No reference_image_multiple data in import - aborting")
                return None

            # Create a special frame for no_image mode
            # Since we don't have an actual file, we'll create a minimal VibeTransferFrame
            # that only holds the vibe data

            # Create a temporary black image for display purposes
            from PIL import Image
            import io
            import base64

            temp_image = Image.new('RGB', (512, 512), color='black')

            # Save to temp path
            temp_path = Path("temp") / f"{no_image_path}.png"
            temp_path.parent.mkdir(exist_ok=True)
            temp_image.save(str(temp_path))

            # Create frame using the temp path with is_no_image flag
            # Get current model to set as target model
            current_model = self._get_current_model()
            frame = VibeTransferFrame(str(temp_path), self.app_context, is_no_image=True, target_model=current_model)

            # Override the frame's data with imported vibe data
            # Store the vibe data directly in the frame's encodings
            # ✅ Use information_extracted as the key (not reference_strength)
            # For non-NAID3 models, this key doesn't matter (default 1.0)
            # For NAID3 models, this would be provided in reference_information_extracted_multiple
            if ref_ie_multiple and len(ref_ie_multiple) > 0:
                # Use provided IE values as keys
                for i, ie_value in enumerate(ref_ie_multiple):
                    if i < len(ref_img_multiple):
                        frame.vibe_encodings[float(ie_value)] = ref_img_multiple[i]
            else:
                # Default: use 1.0 as key (non-NAID3 models)
                for encoding in ref_img_multiple:
                    frame.vibe_encodings[1.0] = encoding

            # Mark this as a no_image frame by setting special properties
            frame.file_name = no_image_path
            frame.file_path = no_image_path

            # Save the vibe data to storage
            frame._save_encodings()

            # Connect signals
            frame.removed.connect(self._remove_frame)
            frame.encoding_requested.connect(self._on_encoding_requested)

            # Add to UI
            self.scroll_layout.addWidget(frame)
            self.vibe_frames.append(frame)

            return frame

        except Exception as e:
            QMessageBox.critical(self.widget, "Error", f"Failed to add vibe from import: {str(e)}")
            return None
    
    def _add_vibe_frame_from_metadata(self, no_image_path: str, vibe_data: dict) -> Optional[VibeTransferFrame]:
        """Add a vibe frame from metadata (no actual image file)"""
        if len(self.vibe_frames) >= 8:
            QMessageBox.warning(self.widget, "Limit Reached", "Maximum 8 vibe frames allowed")
            return None

        try:
            # Handle None values - convert to empty list for safety
            ref_img_multiple = vibe_data.get('reference_image_multiple') or []
            ref_str_multiple = vibe_data.get('reference_strength_multiple') or []
            ref_ie_multiple = vibe_data.get('reference_information_extracted_multiple') or []

            # Early return if no valid vibe data
            if not ref_img_multiple:
                QMessageBox.warning(self.widget, "경고", "Metadata에 유효한 Vibe Transfer 데이터가 없습니다.")
                return None

            # Create a special frame for no_image mode
            # Since we don't have an actual file, we'll create a minimal VibeTransferFrame
            # that only holds the vibe data

            # Create a temporary black image for display purposes
            from PIL import Image
            import io
            import base64

            temp_image = Image.new('RGB', (512, 512), color='black')

            # Save to temp path - ensure metadata is in the path for proper identification
            temp_path = Path("temp") / f"{no_image_path}.png"
            temp_path.parent.mkdir(exist_ok=True)
            temp_image.save(str(temp_path))

            # Create frame using the temp path with is_no_image flag
            # Use source model from metadata if available, otherwise current model
            target_model = vibe_data.get('source_model', self._get_current_model())
            frame = VibeTransferFrame(str(temp_path), self.app_context, is_no_image=True, target_model=target_model)

            # Override the frame's data with metadata vibe data
            # Store the vibe data directly in the frame's encodings
            # Use information_extracted as the key (not reference_strength)
            # Metadata may contain reference_information_extracted_multiple for NAID3
            if ref_ie_multiple and len(ref_ie_multiple) > 0:
                # Use provided IE values as keys (NAID3 compatibility)
                for i, ie_value in enumerate(ref_ie_multiple):
                    if i < len(ref_img_multiple):
                        encoding = ref_img_multiple[i]
                        frame.vibe_encodings[float(ie_value)] = encoding
            else:
                # Default: use 1.0 as key for all encodings (non-NAID3 models)
                for encoding in ref_img_multiple:
                    frame.vibe_encodings[1.0] = encoding

            # Apply reference_strength if provided
            if ref_str_multiple:
                strength = float(ref_str_multiple[0])
                frame.reference_strength = strength
                frame.ref_strength_slider.setValue(int(strength * 100))
                frame.ref_strength_label.setText(f"Reference Strength {strength:.2f}")

            # Mark this as a no_image frame by setting special properties
            frame.file_name = no_image_path
            frame.file_path = no_image_path

            # Update UI to show it's from metadata - the label is already set in _setup_ui

            # Save the vibe data to storage
            frame._save_encodings()

            # Connect signals
            frame.removed.connect(self._remove_frame)
            frame.encoding_requested.connect(self._on_encoding_requested)

            # Add to UI
            self.scroll_layout.addWidget(frame)
            self.vibe_frames.append(frame)

            return frame

        except Exception as e:
            QMessageBox.critical(self.widget, "Error", f"Failed to add vibe from metadata: {str(e)}")
            return None
    
    def _calculate_file_hash_static(self, file_path: str) -> str:
        """Static method to calculate SHA-256 hash of file"""
        hash_sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_sha256.update(chunk)
        return hash_sha256.hexdigest()[:16]
    
    def _get_current_model(self) -> str:
        return _get_current_model_from_context(self.app_context)

    def _remove_frame(self, frame: VibeTransferFrame):
        """Remove a vibe frame and clean up volatile files if needed"""
        if frame in self.vibe_frames:
            # Check if this is a volatile file - check both file_name and file_path
            is_volatile = False
            if hasattr(frame, 'file_name') and "no_image_" in frame.file_name:
                is_volatile = True
            elif hasattr(frame, 'file_path') and "no_image_" in frame.file_path:
                is_volatile = True
            
            if is_volatile:
                # Clean up volatile file immediately
                print(f"Cleaning up volatile file: {frame.file_hash}")
                self._cleanup_single_volatile_file(frame.file_hash)
            
            self.vibe_frames.remove(frame)
            self.scroll_layout.removeWidget(frame)
            frame.deleteLater()
            
    def _on_encoding_requested(self, frame: VibeTransferFrame, info_extracted: float):
        """Handle encoding request from frame"""
        if not self.app_context.secure_token_manager.get_token('nai_token'):
            QMessageBox.warning(self.widget, "Error", "Access token not available")
            return
            
        if self.encoding_worker and self.encoding_worker.isRunning():
            QMessageBox.warning(self.widget, "Busy", "Another encoding is in progress")
            return
            
        # This shouldn't happen since button is hidden when encoding exists
        # But check just in case and silently proceed
        if info_extracted in frame.vibe_encodings:
            print(f"Warning: Re-encoding {info_extracted:.2f} (button should have been hidden)")
                
        # Start encoding
        self.encoding_worker = VibeEncodingWorker(
            frame.image_data,
            info_extracted,
            self.app_context.secure_token_manager.get_token('nai_token'),
            self._get_current_model()
        )
        
        self._encoding_target_frame = frame
        self.encoding_worker.encoding_finished.connect(self._on_encoding_finished)

        frame.encode_btn.setEnabled(False)
        frame.encode_btn.setText("⏳...")
        self.encoding_worker.start()

    def _on_encoding_finished(self, success: bool, message: str, result: dict):
        """Handle encoding completion"""
        # Clean up worker first
        if self.encoding_worker:
            self.encoding_worker.deleteLater()
            self.encoding_worker = None

        frame = self._encoding_target_frame
        self._encoding_target_frame = None

        # 프레임이 이미 삭제된 경우 무시
        if frame not in self.vibe_frames:
            return

        frame.encode_btn.setEnabled(True)
        frame.encode_btn.setText("Encode:2")

        if success and result:
            for info_str, encoded_data in result.items():
                frame.add_encoding(float(info_str), encoded_data)
            QMessageBox.information(self.widget, "Success", "Vibe encoding completed successfully")
        else:
            QMessageBox.critical(self.widget, "Error", message)

        # 원격 웹 세션에 인코딩 결과 브로드캐스트
        try:
            bridge = getattr(self.app_context, 'remote_bridge', None)
            if bridge and hasattr(bridge, '_read_vibe_transfer'):
                state = bridge._read_vibe_transfer()
                if state:
                    bridge._broadcast_json(state)
        except Exception:
            pass

    def _on_model_changed(self):
        """Handle model combo changes"""
        current_model = self._get_current_model()
        is_naid3 = "NAID3" in current_model
        
        # Check if switching TO NAID3 (not FROM NAID3)
        if is_naid3:
            # Store previous model to detect if we're switching TO NAID3
            if hasattr(self, '_previous_model'):
                was_naid3 = "NAID3" in self._previous_model
                if not was_naid3:
                    # Switching from non-NAID3 to NAID3 - clear all frames
                    print(f"Switching to NAID3 - clearing all frames due to compatibility")
                    for frame in self.vibe_frames[:]:  # Use slice to avoid modification during iteration
                        self._remove_frame(frame)
            
        # Store current model for next comparison
        self._previous_model = current_model
        
        print(f"Model changed to {current_model}, refreshing encoding states...")
        self._refresh_all_encoding_states()
    
    def _refresh_all_encoding_states(self):
        """Refresh encoding states for all frames based on current model"""
        if not self.vibe_frames:
            return
            
        current_model = self._get_current_model()
        print(f"Refreshing encoding states for model: {current_model}")
        
        for frame in self.vibe_frames:
            # Update model compatibility display for no_image frames
            if frame.is_no_image:
                frame._update_model_compatibility_display(current_model)
            # Re-check existing encodings for this image and model
            if hasattr(frame, 'file_hash'):
                vibe_folder = Path("save/vibe_transfer") / current_model
                json_file = vibe_folder / f"{frame.file_hash}.json"
                
                if json_file.exists():
                    try:
                        with open(json_file, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        
                        # Update encodings from storage
                        frame.vibe_encodings = {
                            float(k): v for k, v in data.get("encodings", {}).items()
                        }
                        
                        print(f"Loaded encodings for {frame.file_name}: {list(frame.vibe_encodings.keys())}")
                    except Exception as e:
                        print(f"Failed to reload encodings: {e}")
                        frame.vibe_encodings = {}
                else:
                    # No encodings for this model
                    frame.vibe_encodings = {}
                    print(f"No encodings found for {frame.file_name} in model {current_model}")
                
                # Update the encoding display
                frame._update_encoding_status()
                frame._update_encode_button_visibility()
    
    def _on_storage_clicked(self):
        """Handle storage button click"""
        if not self.storage_window:
            self.storage_window = VibeStorageWindow(self.app_context, self.widget)
            self.storage_window.apply_vibe.connect(self._on_apply_vibe_from_storage)
        else:
            # Update current model info when reopening
            self.storage_window.current_model = self._get_current_model()
            self.storage_window.is_naid3 = "NAID3" in self.storage_window.current_model
        
        self.storage_window.load_tabs()  # Reload tabs to get latest files
        self.storage_window.show()
        self.storage_window.raise_()
        self.storage_window.activateWindow()
        
    def _on_apply_vibe_from_storage(self, model: str, file_hash: str, file_name: str, selected_encoding: float):
        """Handle vibe application from storage with selected encoding value"""
        # Check if model differs from current model
        current_model = self._get_current_model()
        model_changed = (model != current_model)
        
        # Check NAID3 compatibility
        current_is_naid3 = "NAID3" in current_model
        storage_is_naid3 = "NAID3" in model
        
        # Block loading non-NAID3 vibes in NAID3 mode
        if current_is_naid3 and not storage_is_naid3:
            QMessageBox.warning(
                self.widget, 
                "Compatibility Error", 
                f"Cannot load vibe from '{model}' in NAID3 mode.\n"
                f"NAID3 can only use vibes created in NAID3 mode."
            )
            return
        
        if model_changed:
            print(f"Model mismatch detected: Storage model={model}, Current model={current_model}")
        
        # Load the vibe data from JSON
        json_path = Path("save/vibe_transfer") / model / f"{file_hash}.json"
        if not json_path.exists():
            QMessageBox.warning(self.widget, "Error", "Vibe file not found")
            return
            
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            # Get original file path or use saved image
            file_path = data.get("file_path")
            if not file_path or not os.path.exists(file_path):
                # Use saved image as fallback
                image_path = Path("save/vibe_transfer") / model / "images" / f"{file_hash}.png"
                if image_path.exists():
                    file_path = str(image_path)
                else:
                    QMessageBox.warning(self.widget, "Error", "Original image not found")
                    return
                    
            # Check if this vibe is already loaded
            for frame in self.vibe_frames:
                if frame.file_hash == file_hash:
                    # no_image 프레임은 슬라이더가 없으므로 스킵
                    if frame.is_no_image:
                        return
                    # If already loaded, just update the slider value
                    frame.info_extracted_slider.setValue(int(selected_encoding * 100))
                    frame.information_extracted = selected_encoding
                    frame._update_encoding_status()
                    frame._update_encode_button_visibility()
                    print(f"Vibe already loaded. Slider set to {selected_encoding:.2f}")
                    
                    # If model changed, refresh encoding states
                    if model_changed:
                        self._refresh_all_encoding_states()
                    
                    # Don't close the storage window
                    return
                    
            # Add the vibe frame
            frame = self._add_vibe_frame(file_path)
            if frame:
                # Load encodings
                encodings = data.get("encodings", {})
                for info_str, encoded_data in encodings.items():
                    frame.vibe_encodings[float(info_str)] = encoded_data
                
                # Set the selected encoding value
                frame.information_extracted = selected_encoding
                frame.info_extracted_slider.setValue(int(selected_encoding * 100))
                frame.info_extracted_label.setText(f"Information Extracted {selected_encoding:.2f}")
                    
                # Update UI
                frame._update_encoding_status()
                frame._update_encode_button_visibility()
                
                print(f"Vibe '{file_name}' loaded with Information Extracted: {selected_encoding:.2f}")
                
                # If model changed, refresh all encoding states after adding
                if model_changed:
                    print(f"Refreshing encoding states due to model mismatch")
                    self._refresh_all_encoding_states()
                
                # Don't close storage window - user can continue selecting
                    
        except Exception as e:
            QMessageBox.critical(self.widget, "Error", f"Failed to load vibe: {e}")
            
    def get_vibe_transfer_multiple_data(self) -> dict:
        """
        Get vibe transfer data for multiple reference images.
        Returns:
            dict with keys:
                - normalize_reference_strength_multiple: bool
                - reference_image_multiple: List of encoded values
                - reference_strength_multiple: List of reference strength values
                - reference_information_extracted_multiple: List of IE values (NAID3 only)
        """
        reference_image_multiple = []
        reference_strength_multiple = []
        reference_information_extracted_multiple = []

        # Check if current model is NAID3
        current_model = self._get_current_model()
        is_naid3 = "NAID3" in current_model

        # Collect data from enabled frames only
        for frame in self.vibe_frames:
            if not frame.is_enabled or not frame.vibe_encodings:
                continue

            # Get the encoding for the current information_extracted value
            # Find closest encoding to current info_extracted value
            closest_key = min(frame.vibe_encodings.keys(),
                            key=lambda x: abs(x - frame.information_extracted))

            encoded_value = frame.vibe_encodings[closest_key]
            reference_image_multiple.append(encoded_value)
            reference_strength_multiple.append(frame.reference_strength)

            # For NAID3, also collect information_extracted values
            # Use the actual encoding key (closest_key) instead of frame.information_extracted
            # This ensures no_image frames use the correct IE value from vibe_encodings
            if is_naid3:
                reference_information_extracted_multiple.append(closest_key)
        
        # Get normalization setting
        normalize = self.normalize_checkbox and self.normalize_checkbox.isChecked()

        # Apply normalization if enabled and sum > 1
        if normalize and reference_strength_multiple:
            total_strength = sum(reference_strength_multiple)
            if total_strength > 1.0:
                # Normalize to sum to 1.0 with 15 decimal places max
                reference_strength_multiple = [
                    round(strength / total_strength, 15)
                    for strength in reference_strength_multiple
                ]

        result = {
            "normalize_reference_strength_multiple": normalize,
            "reference_image_multiple": reference_image_multiple,
            "reference_strength_multiple": reference_strength_multiple
        }

        # Add NAID3-specific field if applicable
        if is_naid3 and reference_information_extracted_multiple:
            result["reference_information_extracted_multiple"] = reference_information_extracted_multiple

        return result
    
    def get_parameters(self) -> dict:
        # Vibe Transfer 데이터는 api_service.py의 LateBinding에서
        # get_vibe_transfer_multiple_data()로 직접 수집됨.
        # generation_controller.py의 EarlyBinding은 top-level 'reference_image_multiple' 키를
        # 기대하므로 이 포맷("vibe_transfer" 래핑)과 호환되지 않아 항상 miss.
        # 정규화는 get_vibe_transfer_multiple_data() 내부에서만 수행.
        return {}
    
    def _load_volatile_tracking(self):
        """Load volatile file tracking from disk"""
        volatile_file = Path("save/vibe_transfer/volatile.json")
        if volatile_file.exists():
            try:
                with open(volatile_file, 'r', encoding='utf-8') as f:
                    self.volatile_files = json.load(f)
            except Exception as e:
                print(f"Failed to load volatile tracking: {e}")
                self.volatile_files = {}
        else:
            self.volatile_files = {}
    
    def _save_volatile_tracking(self):
        """Save volatile file tracking to disk"""
        volatile_file = Path("save/vibe_transfer/volatile.json")
        volatile_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(volatile_file, 'w', encoding='utf-8') as f:
                json.dump(self.volatile_files, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Failed to save volatile tracking: {e}")
    
    def _add_to_volatile_list(self, model: str, file_hash: str):
        """Add file to volatile tracking list"""
        if model not in self.volatile_files:
            self.volatile_files[model] = []
        if file_hash not in self.volatile_files[model]:
            self.volatile_files[model].append(file_hash)
            self._save_volatile_tracking()
    
    def _remove_from_volatile_list(self, model: str, file_hash: str):
        """Remove file from volatile tracking list"""
        if model in self.volatile_files and file_hash in self.volatile_files[model]:
            self.volatile_files[model].remove(file_hash)
            if not self.volatile_files[model]:
                del self.volatile_files[model]
            self._save_volatile_tracking()
    
    def _cleanup_volatile_files(self):
        """Clean up all volatile files on startup"""
        vibe_folder = Path("save/vibe_transfer")
        if not vibe_folder.exists():
            return
        
        cleanup_count = 0
        
        # Iterate through all model folders
        for model_folder in vibe_folder.iterdir():
            if not model_folder.is_dir():
                continue
                
            # Get all JSON files in this model folder
            for json_file in model_folder.glob("*.json"):
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    # Check if this is a volatile file
                    if data.get("volatile", False):
                        file_hash = data.get("file_hash", json_file.stem)
                        
                        # Delete the JSON file
                        json_file.unlink()
                        cleanup_count += 1
                        
                        # Delete the associated image file
                        image_file = model_folder / "images" / f"{file_hash}.png"
                        if image_file.exists():
                            try:
                                image_file.unlink()
                            except:
                                pass
                        
                        print(f"Cleaned up volatile file: {json_file.name}")
                        
                except Exception as e:
                    print(f"Error processing {json_file}: {e}")
        
        # Clear volatile tracking
        self.volatile_files = {}
        self._save_volatile_tracking()
        
        if cleanup_count > 0:
            print(f"Cleaned up {cleanup_count} volatile files on startup")
    
    def _cleanup_single_volatile_file(self, file_hash: str):
        """Clean up a single volatile file across all models"""
        vibe_folder = Path("save/vibe_transfer")
        if not vibe_folder.exists():
            return
            
        # Clean up in all model folders
        for model_folder in vibe_folder.iterdir():
            if model_folder.is_dir():
                # Delete JSON file
                json_file = model_folder / f"{file_hash}.json"
                if json_file.exists():
                    try:
                        with open(json_file, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        if data.get("volatile", False):
                            json_file.unlink()
                            print(f"Deleted volatile file: {json_file}")
                            
                            # Remove from tracking
                            self._remove_from_volatile_list(model_folder.name, file_hash)
                    except Exception as e:
                        print(f"Error checking volatile status: {e}")
                
                # Delete image file
                image_file = model_folder / "images" / f"{file_hash}.png"
                if image_file.exists():
                    try:
                        image_file.unlink()
                        print(f"Deleted volatile image: {image_file}")
                    except:
                        pass