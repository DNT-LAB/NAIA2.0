"""
Character Prompt Editor Window for managing character prompts with JSON storage
"""

import json
import os
from typing import Dict, Optional, List
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, 
    QLabel, QComboBox, QWidget, QSplitter, QFrame, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from legacy_desktop.ui.theme import get_dynamic_styles, DARK_COLORS
from legacy_desktop.ui.scaling_manager import get_scaled_font_size, get_scaled_size

class CharacterPromptEditor(QDialog):
    """Editor window for character prompts with properties"""
    
    saved = pyqtSignal(str)  # Emits the saved JSON path
    
    def __init__(self, image_path: str, parent=None):
        super().__init__(parent)
        self.image_path = image_path
        self.json_path = self._get_json_path(image_path)
        self.properties_data = {}
        self.current_property = None
        
        self.setWindowTitle("Character Prompt Editor")
        self.setMinimumSize(get_scaled_size(800), get_scaled_size(600))
        self.setup_ui()
        self.load_data()
        
    def _get_json_path(self, image_path: str) -> str:
        """Get the JSON file path for the given image"""
        base_path = os.path.splitext(image_path)[0]
        return f"{base_path}.json"
    
    def setup_ui(self):
        """Setup the UI layout"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # Main content area with splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left panel - Character prompts
        left_panel = self.create_left_panel()
        splitter.addWidget(left_panel)
        
        # Right panel - Properties
        right_panel = self.create_right_panel()
        splitter.addWidget(right_panel)
        
        # Set initial splitter sizes (50/50)
        splitter.setSizes([400, 400])
        
        main_layout.addWidget(splitter)
        
        # Bottom buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.save_btn = QPushButton("💾 저장")
        self.save_btn.clicked.connect(self.save_data)
        button_layout.addWidget(self.save_btn)
        
        self.close_btn = QPushButton("❌ 닫기")
        self.close_btn.clicked.connect(self.close)
        button_layout.addWidget(self.close_btn)
        
        main_layout.addLayout(button_layout)
        
        # Apply styling
        self.apply_styling()
    
    def create_left_panel(self) -> QWidget:
        """Create the left panel with character prompts"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Title
        title = QLabel("캐릭터 프롬프트")
        title.setStyleSheet(f"font-size: {get_scaled_font_size(16)}px; font-weight: bold; color: {DARK_COLORS['text_primary']};")
        layout.addWidget(title)
        
        # Character prompt text edit (larger)
        self.character_prompt = QTextEdit()
        self.character_prompt.setPlaceholderText(
            "girl 또는 boy로 시작하고, 의상 정보는 기입하지 마세요"
        )
        layout.addWidget(self.character_prompt, 3)  # Give more weight
        
        # Undesired content label
        uc_label = QLabel("Undesired Content")
        uc_label.setStyleSheet(f"font-size: {get_scaled_font_size(14)}px; color: {DARK_COLORS['text_primary']};")
        layout.addWidget(uc_label)
        
        # Undesired content text edit (smaller)
        self.character_uc = QTextEdit()
        self.character_uc.setMaximumHeight(get_scaled_size(100))
        layout.addWidget(self.character_uc, 1)  # Less weight
        
        return panel
    
    def create_right_panel(self) -> QWidget:
        """Create the right panel with properties"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Title
        title = QLabel("Properties")
        title.setStyleSheet(f"font-size: {get_scaled_font_size(16)}px; font-weight: bold; color: {DARK_COLORS['text_primary']};")
        layout.addWidget(title)
        
        # Property selector and buttons
        selector_layout = QHBoxLayout()
        
        self.property_combo = QComboBox()
        self.property_combo.setEditable(True)
        self.property_combo.setPlaceholderText("Property 이름 입력...")
        self.property_combo.currentTextChanged.connect(self.on_property_changed)
        selector_layout.addWidget(self.property_combo)
        
        self.add_property_btn = QPushButton("추가")
        self.add_property_btn.setMaximumWidth(get_scaled_size(70))
        self.add_property_btn.clicked.connect(self.add_property)
        selector_layout.addWidget(self.add_property_btn)
        
        self.delete_property_btn = QPushButton("삭제")
        self.delete_property_btn.setMaximumWidth(get_scaled_size(70))
        self.delete_property_btn.clicked.connect(self.delete_property)
        self.delete_property_btn.setEnabled(False)
        selector_layout.addWidget(self.delete_property_btn)
        
        layout.addLayout(selector_layout)
        
        # Property prompt text edit
        prop_prompt_label = QLabel("Property 프롬프트")
        prop_prompt_label.setStyleSheet(f"font-size: {get_scaled_font_size(14)}px; color: {DARK_COLORS['text_primary']};")
        layout.addWidget(prop_prompt_label)
        
        self.property_prompt = QTextEdit()
        self.property_prompt.setPlaceholderText(
            "의상 또는 추가 프롬프트 정보를 기입합니다."
        )
        self.property_prompt.setEnabled(False)
        layout.addWidget(self.property_prompt, 3)
        
        # Property undesired content
        prop_uc_label = QLabel("Property Undesired Content")
        prop_uc_label.setStyleSheet(f"font-size: {get_scaled_font_size(14)}px; color: {DARK_COLORS['text_primary']};")
        layout.addWidget(prop_uc_label)
        
        self.property_uc = QTextEdit()
        self.property_uc.setMaximumHeight(get_scaled_size(100))
        self.property_uc.setEnabled(False)
        layout.addWidget(self.property_uc, 1)
        
        return panel
    
    def apply_styling(self):
        """Apply dark theme styling"""
        dynamic_styles = get_dynamic_styles()
        
        # Set dialog background
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
            }}
        """)
        
        # Style text edits
        text_edit_style = f"""
            QTextEdit {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: {get_scaled_size(5)}px;
                font-size: {get_scaled_font_size(14)}px;
            }}
        """
        
        self.character_prompt.setStyleSheet(text_edit_style)
        self.character_uc.setStyleSheet(text_edit_style)
        self.property_prompt.setStyleSheet(text_edit_style)
        self.property_uc.setStyleSheet(text_edit_style)
        
        # Style combo box
        self.property_combo.setStyleSheet(dynamic_styles.get('compact_combobox', ''))
        
        # Style buttons
        button_style = dynamic_styles.get('primary_button', '')
        button_style2 = dynamic_styles.get('secondary_button', '')
        self.save_btn.setStyleSheet(button_style)
        self.close_btn.setStyleSheet(dynamic_styles.get('secondary_button', ''))
        self.add_property_btn.setStyleSheet(button_style)
        self.delete_property_btn.setStyleSheet(button_style2)
    
    def load_data(self):
        """Load existing JSON data if available"""
        if os.path.exists(self.json_path):
            try:
                with open(self.json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Load main prompts
                self.character_prompt.setPlainText(data.get('prompt', ''))
                self.character_uc.setPlainText(data.get('uc', ''))
                
                # Load properties
                properties = data.get('properties', {})
                if properties:
                    self.properties_data = {}
                    for prop_name, prop_value in properties.items():
                        if isinstance(prop_value, dict):
                            # New format with prompt and uc
                            self.properties_data[prop_name] = prop_value
                        else:
                            # Legacy format - just prompt string
                            self.properties_data[prop_name] = {
                                'prompt': prop_value,
                                'uc': ''
                            }
                    
                    # Update combo box
                    self.property_combo.addItems(list(self.properties_data.keys()))
                    if self.properties_data:
                        self.property_combo.setCurrentIndex(0)
                
                print(f"✅ Loaded character data from: {self.json_path}")
                
            except Exception as e:
                print(f"⚠️ Error loading JSON: {e}")
    
    def save_data(self):
        """Save data to JSON file"""
        try:
            # Don't auto-save incomplete properties being typed
            # Only save if it's an actual property (exists in properties_data)
            current_text = self.property_combo.currentText().strip()
            if current_text and current_text in self.properties_data and self.property_prompt.isEnabled():
                # Update the existing property with current values
                self.properties_data[current_text] = {
                    'prompt': self.property_prompt.toPlainText(),
                    'uc': self.property_uc.toPlainText()
                }
            
            # Prepare data structure
            data = {
                'prompt': self.character_prompt.toPlainText(),
                'uc': self.character_uc.toPlainText(),
                'properties': self.properties_data
            }
            
            # Save to file
            with open(self.json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            print(f"✅ Saved character data to: {self.json_path}")
            
            # Emit saved signal
            self.saved.emit(self.json_path)
            
            # Show success feedback (brief)
            self.save_btn.setText("✅ 저장됨")
            # Reset button text after 1 second
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(1000, lambda: self.save_btn.setText("💾 저장"))
            
        except Exception as e:
            print(f"❌ Error saving JSON: {e}")
            QMessageBox.critical(self, "오류", f"저장 실패:\n{str(e)}")
    
    def on_property_changed(self, text: str):
        """Handle property selection change"""
        # Don't auto-save on every keystroke - only save when user explicitly saves or switches
        # Check if this is an existing property
        if text and text in self.properties_data:
            # Load existing property data
            prop_data = self.properties_data[text]
            self.property_prompt.setPlainText(prop_data.get('prompt', ''))
            self.property_uc.setPlainText(prop_data.get('uc', ''))
            self.property_prompt.setEnabled(True)
            self.property_uc.setEnabled(True)
            self.delete_property_btn.setEnabled(True)
            self.current_property = text
        else:
            # New property or empty
            if text:  # New property name being typed
                # Only clear fields if switching from an existing property
                if self.current_property != text:
                    self.property_prompt.clear()
                    self.property_uc.clear()
                self.property_prompt.setEnabled(True)
                self.property_uc.setEnabled(True)
                self.delete_property_btn.setEnabled(False)
                # Don't set current_property yet - wait for add button
            else:
                self.property_prompt.clear()
                self.property_uc.clear()
                self.property_prompt.setEnabled(False)
                self.property_uc.setEnabled(False)
                self.delete_property_btn.setEnabled(False)
                self.current_property = None
    
    def add_property(self):
        """Add or update a property"""
        prop_name = self.property_combo.currentText().strip()
        
        if not prop_name:
            return
        
        # Save the property data
        self.properties_data[prop_name] = {
            'prompt': self.property_prompt.toPlainText(),
            'uc': self.property_uc.toPlainText()
        }
        
        # Update combo box if it's a new item
        if self.property_combo.findText(prop_name) == -1:
            self.property_combo.addItem(prop_name)
        
        # Set as current property
        self.current_property = prop_name
        self.delete_property_btn.setEnabled(True)
        
        if prop_name in self.properties_data:
            print(f"✅ Updated property: {prop_name}")
        else:
            print(f"✅ Added property: {prop_name}")
    
    def delete_property(self):
        """Delete current property"""
        if self.current_property and self.current_property in self.properties_data:
            # Confirm deletion
            reply = QMessageBox.question(
                self, "확인", 
                f"'{self.current_property}' 속성을 삭제하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                # Remove from data
                del self.properties_data[self.current_property]
                
                # Remove from combo box
                index = self.property_combo.findText(self.current_property)
                if index >= 0:
                    self.property_combo.removeItem(index)
                
                # Clear fields
                self.property_prompt.clear()
                self.property_uc.clear()
                self.property_prompt.setEnabled(False)
                self.property_uc.setEnabled(False)
                self.delete_property_btn.setEnabled(False)
                
                print(f"✅ Deleted property: {self.current_property}")
                self.current_property = None
    
    def closeEvent(self, event):
        """Handle window close - auto-save"""
        # Auto-save on close
        self.save_data()
        event.accept()