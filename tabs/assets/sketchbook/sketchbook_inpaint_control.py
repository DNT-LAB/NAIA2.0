"""
Inpaint control window for Sketchbook module
"""

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, 
                            QPushButton, QLabel, QSlider, QButtonGroup, QWidget)
from PyQt6.QtCore import Qt, pyqtSignal
from ui.theme import get_dynamic_styles
from ui.scaling_manager import get_scaled_font_size, get_scaled_size

class InpaintControlWindow(QDialog):
    """Window for controlling inpaint parameters"""
    
    # Signals for result handling
    result_accepted = pyqtSignal()
    result_cancelled = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_widget = parent
        self.setWindowTitle("인페인트 설정")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.setup_ui()
        self._auto_fill_prompts_if_empty()
        
    def setup_ui(self):
        """Setup the UI with 3 column layout"""
        main_layout = QHBoxLayout(self)
        
        # Column 1: Control Area
        control_widget = QWidget()
        control_layout = QVBoxLayout(control_widget)
        control_layout.setContentsMargins(5, 5, 5, 5)
        
        # Drawing mode buttons
        control_layout.addWidget(QLabel("도구:"))
        
        self.mode_group = QButtonGroup()
        
        self.square_brush_button = QPushButton("▢ 사각 브러시")
        self.square_brush_button.setCheckable(True)
        self.square_brush_button.setChecked(True)  # Default
        self.mode_group.addButton(self.square_brush_button, 0)
        control_layout.addWidget(self.square_brush_button)
        
        self.circle_brush_button = QPushButton("○ 원형 브러시")
        self.circle_brush_button.setCheckable(True)
        self.mode_group.addButton(self.circle_brush_button, 1)
        control_layout.addWidget(self.circle_brush_button)
        
        self.rect_button = QPushButton("▭ 직사각형")
        self.rect_button.setCheckable(True)
        self.mode_group.addButton(self.rect_button, 2)
        control_layout.addWidget(self.rect_button)
        
        self.move_button = QPushButton("✋ 이동")
        self.move_button.setCheckable(True)
        self.mode_group.addButton(self.move_button, 3)
        control_layout.addWidget(self.move_button)
        
        # Connect mode buttons
        self.mode_group.buttonClicked.connect(self.on_mode_changed)
        
        control_layout.addSpacing(10)
        
        # Brush size slider
        control_layout.addWidget(QLabel("브러시 크기:"))
        self.brush_slider = QSlider(Qt.Orientation.Horizontal)
        self.brush_slider.setRange(8, 160)
        self.brush_slider.setValue(48)
        self.brush_slider.setSingleStep(8)
        self.brush_slider.setPageStep(16)
        control_layout.addWidget(self.brush_slider)
        
        self.brush_label = QLabel("48 px")
        self.brush_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        control_layout.addWidget(self.brush_label)
        
        self.brush_slider.valueChanged.connect(self.on_brush_size_changed)
        
        control_layout.addSpacing(10)
        
        # Strength slider
        control_layout.addWidget(QLabel("Strength:"))
        self.strength_slider = QSlider(Qt.Orientation.Horizontal)
        self.strength_slider.setRange(0, 100)
        self.strength_slider.setValue(70)
        control_layout.addWidget(self.strength_slider)
        
        self.strength_label = QLabel("0.7")
        self.strength_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        control_layout.addWidget(self.strength_label)
        
        self.strength_slider.valueChanged.connect(
            lambda v: self.strength_label.setText(f"{v/100:.2f}")
        )
        
        control_layout.addStretch()
        
        # Action buttons
        self.clear_mask_button = QPushButton("🧹 마스크 지우기")
        self.clear_mask_button.clicked.connect(self.clear_mask)
        control_layout.addWidget(self.clear_mask_button)
        
        self.generate_button = QPushButton("🎨 생성")
        self.generate_button.clicked.connect(self.generate_inpaint)
        control_layout.addWidget(self.generate_button)
        
        # Result buttons (hidden by default)
        self.accept_button = QPushButton("✅ 승인")
        self.accept_button.clicked.connect(self._on_accept_result)
        self.accept_button.setVisible(False)
        control_layout.addWidget(self.accept_button)
        
        self.cancel_button = QPushButton("❌ 취소")
        self.cancel_button.clicked.connect(self._on_cancel_result)
        self.cancel_button.setVisible(False)
        control_layout.addWidget(self.cancel_button)
        
        # Column 2: Main Prompt
        prompt_widget = QWidget()
        prompt_layout = QVBoxLayout(prompt_widget)
        prompt_layout.setContentsMargins(5, 5, 5, 5)
        
        prompt_layout.addWidget(QLabel("Main Prompt:"))
        self.main_prompt_edit = QTextEdit()
        self.main_prompt_edit.setMinimumWidth(480)
        prompt_layout.addWidget(self.main_prompt_edit)
        
        # Column 3: Negative Prompt
        negative_widget = QWidget()
        negative_layout = QVBoxLayout(negative_widget)
        negative_layout.setContentsMargins(5, 5, 5, 5)
        
        negative_layout.addWidget(QLabel("Negative Prompt:"))
        self.negative_prompt_edit = QTextEdit()
        self.negative_prompt_edit.setMinimumWidth(480)
        negative_layout.addWidget(self.negative_prompt_edit)
        
        # Add columns to main layout
        main_layout.addWidget(control_widget)
        main_layout.addWidget(prompt_widget)
        main_layout.addWidget(negative_widget)
        
        # Set column stretch ratios (1:2:2)
        main_layout.setStretchFactor(control_widget, 1)
        main_layout.setStretchFactor(prompt_widget, 2)
        main_layout.setStretchFactor(negative_widget, 2)
        
        # Apply styling
        ds = get_dynamic_styles()
        self.main_prompt_edit.setStyleSheet(ds.get('compact_textedit', ''))
        self.negative_prompt_edit.setStyleSheet(ds.get('compact_textedit', ''))
        self.clear_mask_button.setStyleSheet(ds.get('secondary_button', ''))
        self.generate_button.setStyleSheet(ds.get('primary_button', ''))
        self.accept_button.setStyleSheet(ds.get('primary_button', ''))
        self.cancel_button.setStyleSheet(ds.get('secondary_button', ''))
        
        # Style mode buttons
        for button in [self.square_brush_button, self.circle_brush_button, 
                      self.rect_button, self.move_button]:
            button.setStyleSheet(ds.get('secondary_button', ''))
        
        self.resize(900, 400)
    
    def on_mode_changed(self, button):
        """Handle drawing mode change"""
        if self.parent_widget and self.parent_widget.canvas.inpaint_layer:
            from .sketchbook_inpaint import DrawMode
            
            mode_map = {
                0: DrawMode.SQUARE_BRUSH,
                1: DrawMode.CIRCLE_BRUSH,
                2: DrawMode.RECTANGLE,
                3: DrawMode.MOVE
            }
            
            mode_id = self.mode_group.id(button)
            if mode_id in mode_map:
                self.parent_widget.canvas.inpaint_layer.set_draw_mode(mode_map[mode_id])
    
    def on_brush_size_changed(self, value):
        """Handle brush size change"""
        # Align to 8px grid
        aligned_value = (value // 8) * 8
        if aligned_value < 8:
            aligned_value = 8
        
        self.brush_label.setText(f"{aligned_value} px")
        
        # Update inpaint layer
        if self.parent_widget and self.parent_widget.canvas.inpaint_layer:
            self.parent_widget.canvas.inpaint_layer.set_brush_size(aligned_value)
    
    def update_brush_size(self, size: int):
        """Update brush size display (called from canvas wheel event)"""
        self.brush_slider.setValue(size)
        self.brush_label.setText(f"{size} px")
    
    def set_prompts(self, main_prompt: str, negative_prompt: str):
        """Set the prompts"""
        self.main_prompt_edit.setPlainText(main_prompt)
        self.negative_prompt_edit.setPlainText(negative_prompt)
    
    def _auto_fill_prompts_if_empty(self):
        """Auto-fill prompts from main window if they are empty"""
        # Check if prompts are already set
        if self.main_prompt_edit.toPlainText().strip() or self.negative_prompt_edit.toPlainText().strip():
            return
        
        # Try to get prompts from main window via app_context
        try:
            if self.parent_widget and hasattr(self.parent_widget, 'app_context'):
                app_context = self.parent_widget.app_context
                main_window = app_context.main_window
                
                if main_window:
                    # Get main prompt from prompt_input
                    if hasattr(main_window, 'main_prompt_textedit'):
                        main_prompt = main_window.main_prompt_textedit.toPlainText()
                        if main_prompt:
                            self.main_prompt_edit.setPlainText(main_prompt)
                            print(f"✅ Auto-filled main prompt from main window")
                    
                    # Get negative prompt from negative_prompt 
                    if hasattr(main_window, 'negative_prompt_textedit'):
                        negative_prompt = main_window.negative_prompt_textedit.toPlainText()
                        if negative_prompt:
                            self.negative_prompt_edit.setPlainText(negative_prompt)
                            print(f"✅ Auto-filled negative prompt from main window")
        except Exception as e:
            print(f"⚠️ Could not auto-fill prompts: {e}")
    
    def clear_mask(self):
        """Clear the inpaint mask"""
        if self.parent_widget and self.parent_widget.canvas.inpaint_layer:
            self.parent_widget.canvas.clear_inpaint_mask()
    
    def generate_inpaint(self):
        """Start inpaint generation"""
        if self.parent_widget:
            main_prompt = self.main_prompt_edit.toPlainText()
            negative_prompt = self.negative_prompt_edit.toPlainText()
            strength = self.strength_slider.value() / 100.0
            
            # Store prompts for persistence
            self.parent_widget.stored_main_prompt = main_prompt
            self.parent_widget.stored_negative_prompt = negative_prompt
            
            # Call parent's generation method
            if hasattr(self.parent_widget, 'generate_inpaint'):
                self.parent_widget.generate_inpaint(main_prompt, negative_prompt, strength)
            else:
                print("⚠️ generate_inpaint method not found in parent widget")
    
    def show_result_buttons(self, show: bool):
        """Show or hide accept/cancel buttons"""
        self.accept_button.setVisible(show)
        self.cancel_button.setVisible(show)
        self.generate_button.setEnabled(not show)
        self.clear_mask_button.setEnabled(not show)
    
    def _on_accept_result(self):
        """Handle accept button click"""
        self.result_accepted.emit()
        self.show_result_buttons(False)
    
    def _on_cancel_result(self):
        """Handle cancel button click"""
        self.result_cancelled.emit()
        self.show_result_buttons(False)
    
    def closeEvent(self, event):
        """Handle window close"""
        # If there are visible result buttons, it means there's a pending result
        if self.accept_button.isVisible() or self.cancel_button.isVisible():
            # Emit cancel signal to restore mask and remove temp layer
            self.result_cancelled.emit()
            self.show_result_buttons(False)
        
        # Disable inpaint mode when closing the control window
        if self.parent_widget and hasattr(self.parent_widget, 'inpaint_button'):
            # Uncheck the inpaint button to disable mode
            self.parent_widget.inpaint_button.setChecked(False)
            # This will trigger _on_inpaint_mode_toggled(False)
        
        event.accept()