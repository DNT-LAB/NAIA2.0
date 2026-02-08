"""
Save as Variation dialog for character images in Sketchbook
"""

import os
import json
from pathlib import Path
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                            QPushButton, QMessageBox, QSplitter, QWidget)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap

from .property_widgets import PropertyWidgets
from ui.theme import get_dynamic_styles, DARK_COLORS
from ui.scaling_manager import get_scaled_font_size, get_scaled_size

# No need for StableImageWidget - using QLabel with transparency support

class SaveAsVariationDialog(QDialog):
    """Dialog for saving character variation images"""
    
    def __init__(self, layer_data, layer_pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self.layer_data = layer_data
        self.layer_pixmap = layer_pixmap
        self.character_name = self._extract_character_name()
        self.variation_folder = self._get_variation_folder_path()
        
        self.setWindowTitle("Save as Variation")
        self.setModal(True)
        self.resize(get_scaled_size(800), get_scaled_size(600))
        
        self.setup_ui()
        self.apply_styling()
        self.load_character_data()
    
    def _extract_character_name(self) -> str:
        """Extract character name from layer data"""
        if hasattr(self.layer_data, 'character_prompt') and self.layer_data.character_prompt:
            # Try to get name from character prompt data
            char_data = self.layer_data.character_prompt
            if isinstance(char_data, dict):
                # Look for character name in various possible fields
                name = char_data.get('name', '')
                if not name and 'image_path' in char_data:
                    # Extract from image path
                    path = Path(char_data['image_path'])
                    name = path.stem
                if name:
                    return name
        
        # Fallback to layer name, but remove processing prefixes
        layer_name = self.layer_data.name or "character"
        # Remove common processing prefixes
        prefixes_to_remove = ['BG_Removed_Merged_','BG_Removed_', 'Merged_']
        for prefix in prefixes_to_remove:
            if layer_name.startswith(prefix):
                layer_name = layer_name[len(prefix):]
                break
        
        return layer_name
    
    def _get_variation_folder_path(self) -> Path:
        """Get the path to the variations folder"""
        # Assume character files are in tabs/assets/characters/
        base_path = Path("tabs/assets/characters")
        variation_folder = base_path / f"{self.character_name}_variations"
        return variation_folder
    
    def setup_ui(self):
        """Setup the dialog UI similar to character_prompt_editor"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # Main content area with splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left panel: Image preview
        left_panel = self.create_image_panel()
        splitter.addWidget(left_panel)
        
        # Right panel: Property management
        right_panel = self.create_property_panel()
        splitter.addWidget(right_panel)
        
        # Set initial splitter sizes (50/50)
        splitter.setSizes([400, 400])
        
        main_layout.addWidget(splitter)
        
        # Bottom buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.save_btn = QPushButton("💾 저장")
        self.save_btn.clicked.connect(self.save_variation)
        button_layout.addWidget(self.save_btn)
        
        self.cancel_btn = QPushButton("❌ 취소")
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_btn)
        
        main_layout.addLayout(button_layout)
    
    def create_image_panel(self):
        """Create the image preview panel"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Title similar to character_prompt_editor
        title = QLabel("이미지 미리보기")
        title.setStyleSheet(f"font-size: {get_scaled_font_size(16)}px; font-weight: bold; color: {DARK_COLORS['text_primary']};")
        layout.addWidget(title)
        
        # Images container with horizontal layout
        images_layout = QHBoxLayout()
        
        # New image (current layer) preview
        new_image_container = QVBoxLayout()
        new_label = QLabel("새 이미지")
        new_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        new_label.setStyleSheet(f"font-size: {get_scaled_font_size(12)}px; color: #ccc; margin-bottom: 5px;")
        new_image_container.addWidget(new_label)
        
        self.new_image_label = QLabel()
        self.new_image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.new_image_label.setMinimumSize(get_scaled_size(150), get_scaled_size(200))
        self.new_image_label.setStyleSheet("""
            QLabel {
                border: 2px solid #555;
                background: rgba(43, 43, 43, 0.8);
                margin: 2px;
            }
        """)
        self.new_image_label.setScaledContents(False)  # Keep aspect ratio
        
        # Display the layer pixmap with transparency support
        if not self.layer_pixmap.isNull():
            # Create a checkered background for transparency visualization
            scaled_pixmap = self._create_transparency_preview(self.layer_pixmap, 
                                                           get_scaled_size(150), get_scaled_size(180))
            self.new_image_label.setPixmap(scaled_pixmap)
        
        new_image_container.addWidget(self.new_image_label)
        images_layout.addLayout(new_image_container)
        
        # Existing image preview (initially hidden)
        existing_image_container = QVBoxLayout()
        existing_label = QLabel("기존 이미지")
        existing_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        existing_label.setStyleSheet(f"font-size: {get_scaled_font_size(12)}px; color: #ccc; margin-bottom: 5px;")
        existing_image_container.addWidget(existing_label)
        
        self.existing_image_label = QLabel()
        self.existing_image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.existing_image_label.setMinimumSize(get_scaled_size(150), get_scaled_size(200))
        self.existing_image_label.setStyleSheet("""
            QLabel {
                border: 2px solid #555;
                background: rgba(43, 43, 43, 0.8);
                margin: 2px;
            }
        """)
        self.existing_image_label.setScaledContents(False)
        existing_image_container.addWidget(self.existing_image_label)
        
        # Initially hide existing image preview
        existing_label.setVisible(False)
        self.existing_image_label.setVisible(False)
        self.existing_label = existing_label  # Store for later use
        
        images_layout.addLayout(existing_image_container)
        layout.addLayout(images_layout)
        
        # Character info
        info_layout = QVBoxLayout()
        info_layout.setSpacing(5)
        
        char_label = QLabel(f"캐릭터: {self.character_name}")
        char_label.setStyleSheet(f"font-size: {get_scaled_font_size(14)}px; font-weight: bold; color: {DARK_COLORS['text_primary']};")
        info_layout.addWidget(char_label)
        
        path_label = QLabel(f"저장 위치: {self.variation_folder}")
        path_label.setWordWrap(True)
        path_label.setStyleSheet(f"font-size: {get_scaled_font_size(11)}px; color: #999;")
        info_layout.addWidget(path_label)
        
        layout.addLayout(info_layout)
        
        return panel
    
    def _create_transparency_preview(self, pixmap: QPixmap, max_width: int, max_height: int) -> QPixmap:
        """Create a pixmap with checkered background for transparency visualization"""
        from PyQt6.QtGui import QPainter, QBrush, QColor
        
        # Scale the pixmap while maintaining aspect ratio
        scaled_pixmap = pixmap.scaled(
            max_width, max_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        
        # Create a new pixmap with checkered background
        result_pixmap = QPixmap(scaled_pixmap.size())
        result_pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(result_pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Draw checkered pattern background
        checker_size = 10
        light_color = QColor(200, 200, 200)
        dark_color = QColor(150, 150, 150)
        
        for x in range(0, result_pixmap.width(), checker_size):
            for y in range(0, result_pixmap.height(), checker_size):
                color = light_color if (x // checker_size + y // checker_size) % 2 == 0 else dark_color
                painter.fillRect(x, y, checker_size, checker_size, color)
        
        # Draw the actual pixmap on top
        painter.drawPixmap(0, 0, scaled_pixmap)
        painter.end()
        
        return result_pixmap
    
    def _update_existing_image_preview(self, property_name: str):
        """Update the existing image preview when property is selected"""
        if not property_name:
            self.existing_label.setVisible(False)
            self.existing_image_label.setVisible(False)
            return
            
        existing_path = self.variation_folder / f"{property_name}.png"
        
        if existing_path.exists():
            existing_pixmap = QPixmap(str(existing_path))
            if not existing_pixmap.isNull():
                # Show existing image with transparency support
                scaled_existing = self._create_transparency_preview(existing_pixmap, 
                                                                 get_scaled_size(150), get_scaled_size(180))
                self.existing_image_label.setPixmap(scaled_existing)
                self.existing_label.setVisible(True)
                self.existing_image_label.setVisible(True)
                return
        
        # Hide if no existing image
        self.existing_label.setVisible(False)
        self.existing_image_label.setVisible(False)
    
    def create_property_panel(self):
        """Create the property management panel similar to character_prompt_editor"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Add property widgets (enable editing)
        self.property_widgets = PropertyWidgets("Properties", self)
        layout.addWidget(self.property_widgets)
        
        # Connect property change signal to update existing image preview
        self.property_widgets.property_changed.connect(self._update_existing_image_preview)
        
        # Add help text
        help_text = QLabel("선택한 Property 이름으로 variation 이미지가 저장됩니다.\n기존 파일이 있으면 우측에 미리보기가 표시됩니다.")
        help_text.setWordWrap(True)
        help_text.setStyleSheet(f"font-size: {get_scaled_font_size(11)}px; color: #999; margin: 5px;")
        layout.addWidget(help_text)
        
        return panel
    
    def load_character_data(self):
        """Load character data into property widgets"""
        if hasattr(self.layer_data, 'character_prompt') and self.layer_data.character_prompt:
            char_data = self.layer_data.character_prompt
            properties = char_data.get('properties', {})
            
            if properties:
                self.property_widgets.load_properties(properties)
                # Enable editing for variation saving (not readonly)
                self.property_widgets.set_readonly(False)
                print(f"✅ Loaded {len(properties)} properties for {self.character_name}")
                
                # Update existing image preview for first property
                if properties:
                    first_property = list(properties.keys())[0]
                    self._update_existing_image_preview(first_property)
            else:
                print(f"⚠️ No properties found for character: {self.character_name}")
                # Show message and disable save
                self.save_btn.setEnabled(False)
                QMessageBox.warning(self, "속성 없음", 
                    f"캐릭터 '{self.character_name}'에 저장할 속성이 없습니다.\n"
                    "먼저 Character Prompt Editor에서 속성을 추가해주세요.")
        else:
            print(f"⚠️ No character prompt data found")
            self.save_btn.setEnabled(False)
            QMessageBox.warning(self, "캐릭터 데이터 없음", 
                "이 레이어에는 캐릭터 프롬프트 정보가 없습니다.")
    
    def save_variation(self):
        """Save the variation image"""
        try:
            # Get selected property name
            property_name = self.property_widgets.get_current_property_name()
            
            if not property_name:
                QMessageBox.warning(self, "속성 선택", "저장할 속성을 선택해주세요.")
                return
            
            # Create variations folder if it doesn't exist
            self.variation_folder.mkdir(parents=True, exist_ok=True)
            
            # Determine save path
            save_path = self.variation_folder / f"{property_name}.png"
            
            # Check for existing file
            if save_path.exists():
                reply = QMessageBox.question(self, "파일 중복", 
                    f"'{property_name}.png' 파일이 이미 존재합니다.\n덮어쓰시겠습니까?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                
                if reply != QMessageBox.StandardButton.Yes:
                    return
            
            # Save the pixmap
            success = self.layer_pixmap.save(str(save_path), 'PNG')
            
            if success:
                # Update JSON file with new/updated property
                self._update_character_json(property_name)
                print(f"✅ Saved variation: {save_path}")
                self.accept()
            else:
                QMessageBox.critical(self, "저장 실패", 
                    f"이미지 저장에 실패했습니다:\n{save_path}")
                
        except Exception as e:
            print(f"❌ Error saving variation: {e}")
            QMessageBox.critical(self, "오류", f"저장 중 오류 발생:\n{str(e)}")
    
    def _update_character_json(self, property_name: str):
        """Update the character's JSON file with the new/updated property"""
        try:
            # Find the original character JSON file
            # First try to get from character_prompt data
            json_path = None
            
            if hasattr(self.layer_data, 'character_prompt') and self.layer_data.character_prompt:
                char_data = self.layer_data.character_prompt
                if isinstance(char_data, dict) and 'image_path' in char_data:
                    # Get JSON path from image path
                    image_path = Path(char_data['image_path'])
                    json_path = image_path.with_suffix('.json')
            
            # If no path found, try to construct from character name
            if not json_path or not json_path.exists():
                base_path = Path("tabs/assets/characters")
                json_path = base_path / f"{self.character_name}.json"
            
            if not json_path.exists():
                print(f"⚠️ Character JSON file not found: {json_path}")
                return
            
            # Load existing JSON data
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Get current property data from the dialog
            current_properties = self.property_widgets.get_all_properties()
            
            # Ensure properties key exists
            if 'properties' not in data:
                data['properties'] = {}
            
            # Update or add the property
            if property_name in current_properties:
                # Get the property value from property_widgets
                prop_data = current_properties[property_name]
                if isinstance(prop_data, dict):
                    data['properties'][property_name] = prop_data
                else:
                    # If it's just a string (legacy format), create dict format
                    data['properties'][property_name] = {
                        'prompt': prop_data if isinstance(prop_data, str) else '',
                        'uc': ''
                    }
            else:
                # New property - get from the text edits in property_widgets
                # This handles cases where user added a new property
                property_prompt = ''
                property_uc = ''
                
                # Try to get values from property widgets if they are available
                if hasattr(self.property_widgets, 'get_current_property_data'):
                    prop_data = self.property_widgets.get_current_property_data()
                    if prop_data:
                        property_prompt = prop_data.get('prompt', '')
                        property_uc = prop_data.get('uc', '')
                
                data['properties'][property_name] = {
                    'prompt': property_prompt,
                    'uc': property_uc
                }
            
            # Save updated JSON
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            print(f"✅ Updated character JSON with property '{property_name}': {json_path}")
            
        except Exception as e:
            print(f"⚠️ Failed to update character JSON: {e}")
            # Don't show error to user - JSON update is optional enhancement
    
    def apply_styling(self):
        """Apply dark theme styling similar to character_prompt_editor"""
        dynamic_styles = get_dynamic_styles()
        
        # Set dialog background similar to character_prompt_editor
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
            }}
        """)
        
        # Style buttons similar to character_prompt_editor
        button_style = dynamic_styles.get('primary_button', '')
        button_style2 = dynamic_styles.get('secondary_button', '')
        
        self.save_btn.setStyleSheet(button_style)
        self.cancel_btn.setStyleSheet(button_style2)