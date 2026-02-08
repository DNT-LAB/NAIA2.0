"""
Property management widgets for character prompt editor and variation dialogs
"""

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                            QComboBox, QPushButton, QTextEdit)
from PyQt6.QtCore import pyqtSignal
from ui.theme import DARK_COLORS, get_dynamic_styles
from ui.scaling_manager import get_scaled_font_size, get_scaled_size

class PropertyWidgets(QWidget):
    """Reusable property management widget components"""
    
    # Signals for property management
    property_changed = pyqtSignal(str)  # property_name
    property_added = pyqtSignal(str)    # property_name
    property_deleted = pyqtSignal(str)  # property_name
    
    def __init__(self, title="Properties", parent=None):
        super().__init__(parent)
        self.title = title
        self.properties_data = {}
        self.current_property = None
        self.setup_ui()
        self.apply_styling()
    
    def setup_ui(self):
        """Create the property management UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Title
        title_label = QLabel(self.title)
        title_label.setStyleSheet(f"font-size: {get_scaled_font_size(16)}px; font-weight: bold; color: {DARK_COLORS['text_primary']};")
        layout.addWidget(title_label)
        
        # Property selector and buttons
        selector_layout = QHBoxLayout()
        
        self.property_combo = QComboBox()
        self.property_combo.setEditable(True)
        self.property_combo.setPlaceholderText("Property 이름 입력...")
        self.property_combo.currentTextChanged.connect(self._on_property_changed)
        selector_layout.addWidget(self.property_combo)
        
        self.add_property_btn = QPushButton("추가")
        self.add_property_btn.setMaximumWidth(get_scaled_size(70))
        self.add_property_btn.clicked.connect(self._add_property)
        selector_layout.addWidget(self.add_property_btn)
        
        self.delete_property_btn = QPushButton("삭제")
        self.delete_property_btn.setMaximumWidth(get_scaled_size(70))
        self.delete_property_btn.clicked.connect(self._delete_property)
        self.delete_property_btn.setEnabled(False)
        selector_layout.addWidget(self.delete_property_btn)
        
        layout.addLayout(selector_layout)
        
        # Property prompt text edit
        prop_prompt_label = QLabel("Property 프롬프트")
        prop_prompt_label.setStyleSheet(f"font-size: {get_scaled_font_size(14)}px; color: {DARK_COLORS['text_primary']};")
        layout.addWidget(prop_prompt_label)
        
        self.property_prompt = QTextEdit()
        self.property_prompt.setPlaceholderText("의상 또는 추가 프롬프트 정보를 기입합니다.")
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
    
    def apply_styling(self):
        """Apply dark theme styling"""
        dynamic_styles = get_dynamic_styles()
        
        # Style combo and text edits
        self.property_combo.setStyleSheet(dynamic_styles.get('compact_combobox', ''))
        self.property_prompt.setStyleSheet(dynamic_styles.get('compact_textedit', ''))
        self.property_uc.setStyleSheet(dynamic_styles.get('compact_textedit', ''))
        
        # Style buttons
        button_style = dynamic_styles.get('primary_button', '')
        button_style2 = dynamic_styles.get('secondary_button', '')
        
        self.add_property_btn.setStyleSheet(button_style)
        self.delete_property_btn.setStyleSheet(button_style2)
    
    def load_properties(self, properties_data: dict):
        """Load properties data into the widgets"""
        self.properties_data = properties_data.copy() if properties_data else {}
        
        # Clear and populate combo
        self.property_combo.clear()
        if self.properties_data:
            self.property_combo.addItems(list(self.properties_data.keys()))
            self.property_combo.setCurrentIndex(0)
    
    def get_properties_data(self) -> dict:
        """Get the current properties data"""
        # Save current property before returning
        self._save_current_property()
        return self.properties_data.copy()
    
    def _save_current_property(self):
        """Save current property data"""
        current_text = self.property_combo.currentText().strip()
        if current_text and current_text in self.properties_data and self.property_prompt.isEnabled():
            self.properties_data[current_text] = {
                'prompt': self.property_prompt.toPlainText().strip(),
                'uc': self.property_uc.toPlainText().strip()
            }
    
    def _on_property_changed(self, property_name: str):
        """Handle property selection change"""
        property_name = property_name.strip()
        
        if not property_name:
            self.property_prompt.clear()
            self.property_uc.clear()
            self.property_prompt.setEnabled(False)
            self.property_uc.setEnabled(False)
            self.delete_property_btn.setEnabled(False)
            return
        
        # Enable controls if property exists
        if property_name in self.properties_data:
            prop_data = self.properties_data[property_name]
            self.property_prompt.setPlainText(prop_data.get('prompt', ''))
            self.property_uc.setPlainText(prop_data.get('uc', ''))
            self.property_prompt.setEnabled(True)
            self.property_uc.setEnabled(True)
            self.delete_property_btn.setEnabled(True)
            self.current_property = property_name
        else:
            # New property name typed
            self.property_prompt.clear()
            self.property_uc.clear()
            self.property_prompt.setEnabled(False)
            self.property_uc.setEnabled(False)
            self.delete_property_btn.setEnabled(False)
        
        # Emit signal
        self.property_changed.emit(property_name)
    
    def _add_property(self):
        """Add a new property"""
        prop_name = self.property_combo.currentText().strip()
        
        if not prop_name:
            return
        
        # Add to data
        self.properties_data[prop_name] = {
            'prompt': '',
            'uc': ''
        }
        
        # Add to combo if not exists
        if self.property_combo.findText(prop_name) == -1:
            self.property_combo.addItem(prop_name)
        
        # Set as current property
        self.current_property = prop_name
        self.property_combo.setCurrentText(prop_name)
        
        # Enable controls
        self.property_prompt.setEnabled(True)
        self.property_uc.setEnabled(True)
        self.delete_property_btn.setEnabled(True)
        
        print(f"✅ Added property: {prop_name}")
        self.property_added.emit(prop_name)
    
    def _delete_property(self):
        """Delete the current property"""
        if not self.current_property or self.current_property not in self.properties_data:
            return
        
        prop_name = self.current_property
        
        # Remove from data
        del self.properties_data[prop_name]
        
        # Remove from combo
        index = self.property_combo.findText(prop_name)
        if index >= 0:
            self.property_combo.removeItem(index)
        
        # Clear fields and disable
        self.property_prompt.clear()
        self.property_uc.clear()
        self.property_prompt.setEnabled(False)
        self.property_uc.setEnabled(False)
        self.delete_property_btn.setEnabled(False)
        
        # Select next property if available
        if self.properties_data:
            next_prop = list(self.properties_data.keys())[0]
            self.property_combo.setCurrentText(next_prop)
        
        self.current_property = None
        
        print(f"✅ Deleted property: {prop_name}")
        self.property_deleted.emit(prop_name)
    
    def get_current_property_name(self) -> str:
        """Get the currently selected property name"""
        return self.property_combo.currentText().strip()
    
    def set_readonly(self, readonly: bool = True):
        """Set widgets to readonly mode"""
        self.property_combo.setEnabled(not readonly)
        self.add_property_btn.setEnabled(not readonly)
        self.delete_property_btn.setEnabled(not readonly)
        self.property_prompt.setReadOnly(readonly)
        self.property_uc.setReadOnly(readonly)