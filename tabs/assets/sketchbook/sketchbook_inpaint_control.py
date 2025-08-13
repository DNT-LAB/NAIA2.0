"""
Inpaint control window for Sketchbook module
"""

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, 
                            QPushButton, QLabel, QSlider, QButtonGroup, QWidget, QCheckBox,
                            QTabWidget, QStatusBar, QFrame, QTabBar, QFileDialog, QMessageBox)
from PyQt6.QtCore import Qt, pyqtSignal, QPropertyAnimation, QEasingCurve, QTimer
from PyQt6.QtGui import QIcon, QCloseEvent
from ui.theme import get_dynamic_styles, DARK_STYLES
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from typing import List, Optional
from dataclasses import dataclass
import json
import os
import random
from pathlib import Path

@dataclass
class PromptTabData:
    """Data structure for individual prompt tab"""
    main_prompt: str = ""
    negative_prompt: str = ""
    strength: float = 1.0
    update_virtual_layer: bool = False


class PromptTabWidget(QWidget):
    """Individual tab widget containing prompts and settings"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        
    def setup_ui(self):
        """Setup the tab UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # Create horizontal layout for prompts with frame
        prompts_frame = QFrame()
        prompts_frame.setFrameStyle(QFrame.Shape.Box)
        prompts_frame.setStyleSheet("""
            QFrame {
                background-color: #3a3a3a;
                border: 1px solid #505050;
                border-radius: 4px;
                padding: 5px;
            }
        """)
        
        prompts_layout = QHBoxLayout(prompts_frame)
        prompts_layout.setSpacing(10)
        
        # Main Prompt section
        main_prompt_widget = QWidget()
        main_prompt_widget.setStyleSheet("background-color: #2B2B2B;")
        main_prompt_layout = QVBoxLayout(main_prompt_widget)
        main_prompt_layout.setContentsMargins(0, 0, 0, 0)
        
        main_prompt_label = QLabel("Main Prompt:")
        main_prompt_label.setStyleSheet("color: #FFFFFF; font-weight: bold;")
        main_prompt_layout.addWidget(main_prompt_label)
        self.main_prompt_edit = QTextEdit()
        self.main_prompt_edit.setMinimumWidth(400)
        main_prompt_layout.addWidget(self.main_prompt_edit)
        
        # Negative Prompt section
        negative_prompt_widget = QWidget()
        negative_prompt_widget.setStyleSheet("background-color: #2B2B2B;")
        negative_prompt_layout = QVBoxLayout(negative_prompt_widget)
        negative_prompt_layout.setContentsMargins(0, 0, 0, 0)
        
        negative_prompt_label = QLabel("Negative Prompt:")
        negative_prompt_label.setStyleSheet("color: #FFFFFF; font-weight: bold;")
        negative_prompt_layout.addWidget(negative_prompt_label)
        self.negative_prompt_edit = QTextEdit()
        self.negative_prompt_edit.setMinimumWidth(400)
        negative_prompt_layout.addWidget(self.negative_prompt_edit)
        
        # Add prompt sections to horizontal layout
        prompts_layout.addWidget(main_prompt_widget, 1)
        prompts_layout.addWidget(negative_prompt_widget, 1)
        
        main_layout.addWidget(prompts_frame)
        
        # Bottom controls section - horizontal layout
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(15)
        
        # Strength slider - horizontal arrangement
        strength_label_text = QLabel("Strength:")
        strength_label_text.setStyleSheet(f"color: #FFFFFF; font-size: {get_scaled_font_size(16)}px;")
        controls_layout.addWidget(strength_label_text)
        
        self.strength_slider = QSlider(Qt.Orientation.Horizontal)
        self.strength_slider.setRange(0, 100)
        self.strength_slider.setValue(100)  # Default to 1.0
        self.strength_slider.setMinimumWidth(150)
        self.strength_slider.setMaximumWidth(200)
        controls_layout.addWidget(self.strength_slider)
        
        self.strength_label = QLabel("1.0")
        self.strength_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.strength_label.setMinimumWidth(35)
        self.strength_label.setStyleSheet(f"color: #FFFFFF; font-size: {get_scaled_font_size(16)}px;")
        controls_layout.addWidget(self.strength_label)
        
        self.strength_slider.valueChanged.connect(
            lambda v: self.strength_label.setText(f"{v/100:.2f}")
        )
        
        controls_layout.addStretch()
        
        # Virtual layer update checkbox
        self.update_layer_checkbox = QCheckBox("연속 생성시 이 결과를 가상 레이어에 업데이트")
        controls_layout.addWidget(self.update_layer_checkbox)
        
        main_layout.addLayout(controls_layout)
        
        # Apply styling
        ds = get_dynamic_styles()
        self.main_prompt_edit.setStyleSheet(ds.get('compact_textedit', ''))
        self.negative_prompt_edit.setStyleSheet(ds.get('compact_textedit', ''))
        self.update_layer_checkbox.setStyleSheet(f"""
            QCheckBox {{
                color: #FFFFFF;
                font-size: {get_scaled_font_size(14)}px;
            }}
            QCheckBox::indicator {{
                width: {get_scaled_size(16)}px;
                height: {get_scaled_size(16)}px;
            }}
        """)
    
    def get_data(self) -> PromptTabData:
        """Get current tab data"""
        return PromptTabData(
            main_prompt=self.main_prompt_edit.toPlainText(),
            negative_prompt=self.negative_prompt_edit.toPlainText(),
            strength=self.strength_slider.value() / 100.0,
            update_virtual_layer=self.update_layer_checkbox.isChecked()
        )
    
    def set_data(self, data: PromptTabData):
        """Set tab data"""
        self.main_prompt_edit.setPlainText(data.main_prompt)
        self.negative_prompt_edit.setPlainText(data.negative_prompt)
        self.strength_slider.setValue(int(data.strength * 100))
        self.update_layer_checkbox.setChecked(data.update_virtual_layer)
    
    def copy_from(self, other: 'PromptTabWidget'):
        """Copy data from another tab widget"""
        self.set_data(other.get_data())


class InpaintControlWindow(QDialog):
    """Window for controlling inpaint parameters"""
    
    # Signal for seed fix checkbox changes
    seed_fix_changed = pyqtSignal(bool)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_widget = parent
        self.setWindowTitle("인페인트 설정")
        
        # Get main window as parent for proper window hierarchy
        main_window = None
        if parent and hasattr(parent, 'app_context'):
            main_window = parent.app_context.main_window
        
        # Set parent to main window if available, remove topmost flag
        if main_window:
            self.setParent(main_window)
            self.setWindowFlags(Qt.WindowType.Window)
        else:
            self.setWindowFlags(Qt.WindowType.Window)
        
        self.is_generating = False  # Track generation state
        self.is_sequential_generating = False  # Track sequential generation
        self.sequential_queue = []  # Queue for sequential generation
        self.current_sequential_index = 0
        self.prompt_tabs: List[PromptTabWidget] = []  # List of tab widgets
        self.plus_tab_index = 0  # Index of the '+' tab
        self.setup_ui()
        self._auto_fill_prompts_if_empty()
        
    def setup_ui(self):
        """Setup the UI with tab-based prompt system"""
        # Main vertical layout
        main_vbox = QVBoxLayout(self)
        main_vbox.setContentsMargins(5, 5, 5, 5)
        
        # Content area (horizontal layout)
        content_layout = QHBoxLayout()
        
        # Column 1: Control Area
        control_widget = QWidget()
        control_widget.setMaximumWidth(250)
        control_layout = QVBoxLayout(control_widget)
        control_layout.setContentsMargins(5, 5, 5, 5)
        
        # Drawing mode buttons
        control_layout.addWidget(QLabel("도구:"))
        
        self.mode_group = QButtonGroup()
        
        self.square_brush_button = QPushButton("▢ 사각 브러시")
        self.square_brush_button.setCheckable(True)
        self.square_brush_button.setChecked(True)
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
        
        # Brush size slider with integrated label
        self.brush_label = QLabel("브러시 크기: 48px")
        self.brush_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.brush_label.setStyleSheet(f"""
            QLabel {{
                color: #000000;
                font-size: {get_scaled_font_size(16)}px;
                font-weight: bold;
            }}
        """)
        control_layout.addWidget(self.brush_label)
        
        self.brush_slider = QSlider(Qt.Orientation.Horizontal)
        self.brush_slider.setRange(8, 160)
        self.brush_slider.setValue(48)
        self.brush_slider.setSingleStep(8)
        self.brush_slider.setPageStep(16)
        control_layout.addWidget(self.brush_slider)
        
        self.brush_slider.valueChanged.connect(self.on_brush_size_changed)
        
        control_layout.addSpacing(10)
        
        # Export/Import buttons below brush slider
        import_export_layout = QHBoxLayout()
        import_export_layout.setSpacing(5)
        
        self.import_button = QPushButton("📂")
        self.import_button.setToolTip("설정 불러오기")
        self.import_button.clicked.connect(self.import_settings)
        self.import_button.setFixedWidth(80)
        import_export_layout.addWidget(self.import_button)
        
        self.export_button = QPushButton("💾")
        self.export_button.setToolTip("설정 저장하기")
        self.export_button.clicked.connect(self.export_settings)
        self.export_button.setFixedWidth(80)
        import_export_layout.addWidget(self.export_button)
        
        control_layout.addLayout(import_export_layout)
        
        control_layout.addStretch()
        
        # Action buttons
        self.clear_mask_button = QPushButton("🧹 마스크 지우기")
        self.clear_mask_button.clicked.connect(self.clear_mask)
        control_layout.addWidget(self.clear_mask_button)
        
        self.generate_button = QPushButton("🎨 생성")
        self.generate_button.clicked.connect(self.generate_inpaint)
        control_layout.addWidget(self.generate_button)
        
        # Sequential generate button (initially hidden)
        self.sequential_button = QPushButton("🔄 연속 생성")
        self.sequential_button.clicked.connect(self.generate_sequential)
        self.sequential_button.setVisible(False)  # Hidden by default
        control_layout.addWidget(self.sequential_button)
        
        control_layout.addSpacing(10)
        
        # Seed controls layout
        seed_controls_layout = QHBoxLayout()
        seed_controls_layout.setSpacing(5)
        
        # Seed fix checkbox
        self.seed_fix_checkbox = QCheckBox("시드 고정")
        self.seed_fix_checkbox.clicked.connect(self._on_seed_fix_toggled)
        self.seed_fix_checkbox.setStyleSheet(f"""
            QCheckBox {{
                color: #000000;
                font-size: {get_scaled_font_size(14)}px;
            }}
            QCheckBox::indicator {{
                width: {get_scaled_size(16)}px;
                height: {get_scaled_size(16)}px;
            }}
        """)
        seed_controls_layout.addWidget(self.seed_fix_checkbox)
        
        # Seed refresh button
        self.seed_refresh_button = QPushButton("갱신")
        self.seed_refresh_button.clicked.connect(self._on_seed_refresh)
        self.seed_refresh_button.setStyleSheet(f"""
            QPushButton {{
                background-color: #404040;
                color: #e0e0e0;
                border: 1px solid #505050;
                padding: {get_scaled_size(4)}px {get_scaled_size(8)}px;
                border-radius: 3px;
                font-size: {get_scaled_font_size(14)}px;
            }}
            QPushButton:hover {{
                background-color: #505050;
            }}
            QPushButton:pressed {{
                background-color: #353535;
            }}
        """)
        seed_controls_layout.addWidget(self.seed_refresh_button)
        seed_controls_layout.addStretch()
        
        control_layout.addLayout(seed_controls_layout)
        
        # Seed preview label
        self.seed_preview_label = QLabel("시드: 0")
        self.seed_preview_label.setStyleSheet(f"""
            QLabel {{
                color: #000000;
                font-size: {get_scaled_font_size(14)}px;
            }}
        """)
        control_layout.addWidget(self.seed_preview_label)
        
        # Column 2: Tab Widget for Prompts
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self.remove_tab)
        
        # Create and add "+" tab first
        self._add_plus_tab()
        
        # Add initial tab (will be inserted before plus tab)
        self.add_new_tab()
        
        # Connect tab change signal after initial setup
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        
        # Add widgets to content layout
        content_layout.addWidget(control_widget)
        content_layout.addWidget(self.tab_widget, 1)  # Tab widget takes remaining space
        
        main_vbox.addLayout(content_layout)
        
        # Status bar
        self.status_bar = QStatusBar()
        self.status_bar.showMessage("준비")
        main_vbox.addWidget(self.status_bar)
        
        # Apply styling
        self._apply_styles()
        
        # Sync initial seed value
        QTimer.singleShot(100, self.sync_seed_from_main)
        
        self.resize(1200, 700)  # Slightly taller for status bar
    
    def _apply_styles(self):
        """Apply dark theme styles to UI elements"""
        ds = get_dynamic_styles()
        
        # Style control buttons
        for button in [self.square_brush_button, self.circle_brush_button,
                      self.rect_button, self.move_button]:
            button.setStyleSheet(ds.get('secondary_button', ''))
        
        self.clear_mask_button.setStyleSheet(ds.get('secondary_button', ''))
        self.generate_button.setStyleSheet(ds.get('primary_button', ''))
        self.sequential_button.setStyleSheet(ds.get('primary_button', ''))
        
        # Style import/export buttons
        compact_button_style = f"""
            QPushButton {{
                background-color: #404040;
                color: #e0e0e0;
                border: 1px solid #505050;
                padding: {get_scaled_size(4)}px;
                border-radius: 3px;
                font-size: {get_scaled_font_size(16)}px;
            }}
            QPushButton:hover {{
                background-color: #505050;
                border-color: #606060;
            }}
            QPushButton:pressed {{
                background-color: #353535;
            }}
        """
        self.import_button.setStyleSheet(compact_button_style)
        self.export_button.setStyleSheet(compact_button_style)
        
        # Style tab widget - bright gray background with black text
        self.tab_widget.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid #c0c0c0;
                background-color: #3a3a3a;
            }}
            QTabBar::tab {{
                background-color: #d0d0d0;
                color: #000000;
                padding: 8px 16px;
                margin-right: 2px;
                font-size: {get_scaled_font_size(14)}px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }}
            QTabBar::tab:selected {{
                background-color: #e8e8e8;
                color: #000000;
                border-bottom: 2px solid #ffffff;
            }}
            QTabBar::tab:hover {{
                background-color: #e0e0e0;
            }}
            QTabBar::tab:!selected {{
                margin-top: 2px;
            }}
            QTabBar::tab:last {{
                font-weight: bold;
                background-color: #a8d8a8;
                color: #004400;
            }}
            QTabBar::tab:last:hover {{
                background-color: #90e090;
            }}
        """)
        
        # Style status bar - bright background with black text
        self.status_bar.setStyleSheet(f"""
            QStatusBar {{
                background-color: #e0e0e0;
                color: #000000;
                border-top: 1px solid #c0c0c0;
                font-size: {get_scaled_font_size(13)}px;
                padding: 2px;
            }}
        """)
    
    def _add_plus_tab(self):
        """Add a '+' tab at the end for adding new tabs"""
        plus_widget = QWidget()
        self.plus_tab_index = self.tab_widget.addTab(plus_widget, "  ➕  ")
        # Disable close button for plus tab
        close_button = self.tab_widget.tabBar().tabButton(self.plus_tab_index, QTabBar.ButtonPosition.RightSide)
        if close_button:
            close_button.hide()
        
    def _on_tab_changed(self, index):
        """Handle tab selection - create new tab if '+' is clicked"""
        if index == self.plus_tab_index:
            # Add new tab before the plus tab
            self.add_new_tab()
        elif index == -1 and len(self.prompt_tabs) > 0:
            # If no valid tab selected, select the last actual tab
            self.tab_widget.setCurrentIndex(len(self.prompt_tabs) - 1)
    
    def add_new_tab(self, copy_from_index: int = -1):
        """Add a new tab, optionally copying from another tab"""
        # Create new tab widget
        new_tab = PromptTabWidget(self)
        
        # If copying from another tab
        if copy_from_index >= 0 and copy_from_index < len(self.prompt_tabs):
            new_tab.copy_from(self.prompt_tabs[copy_from_index])
        elif len(self.prompt_tabs) > 0:
            # Copy from last tab by default
            new_tab.copy_from(self.prompt_tabs[-1])
        
        # Insert before the plus tab
        tab_index = self.tab_widget.insertTab(
            self.plus_tab_index, 
            new_tab, 
            f"탭 {len(self.prompt_tabs) + 1}"
        )
        self.prompt_tabs.append(new_tab)
        
        # Update plus tab index
        self.plus_tab_index = self.tab_widget.count() - 1
        
        # Hide close button for plus tab (re-apply after tab changes)
        close_button = self.tab_widget.tabBar().tabButton(self.plus_tab_index, QTabBar.ButtonPosition.RightSide)
        if close_button:
            close_button.hide()
        
        # Switch to new tab
        self.tab_widget.setCurrentIndex(tab_index)
        
        # Update sequential button visibility
        self._update_sequential_button()
        
        # Auto-fill if first tab and empty
        if len(self.prompt_tabs) == 1:
            self._auto_fill_prompts_if_empty()
        
        return new_tab
    
    def remove_tab(self, index: int):
        """Remove a tab at given index"""
        # Don't remove the plus tab
        if index == self.plus_tab_index:
            return
            
        # Don't remove if only one tab
        if len(self.prompt_tabs) <= 1:
            self.status_bar.showMessage("마지막 탭은 삭제할 수 없습니다", 2000)
            return
        
        # Remove from lists and widget
        if 0 <= index < len(self.prompt_tabs):
            # Determine which tab to select after removal
            new_index = index - 1 if index > 0 else 0
            
            self.prompt_tabs.pop(index)
            self.tab_widget.removeTab(index)
            
            # Update plus tab index
            self.plus_tab_index = self.tab_widget.count() - 1
            
            # Rename remaining tabs (excluding plus tab)
            for i in range(self.tab_widget.count() - 1):
                self.tab_widget.setTabText(i, f"탭 {i + 1}")
            
            # Select appropriate tab after removal
            if new_index < len(self.prompt_tabs):
                self.tab_widget.setCurrentIndex(new_index)
            
            # Update sequential button visibility
            self._update_sequential_button()
    
    def _update_sequential_button(self):
        """Update visibility of sequential generation button"""
        self.sequential_button.setVisible(len(self.prompt_tabs) >= 2)
    
    def get_current_tab(self) -> Optional[PromptTabWidget]:
        """Get currently active tab widget"""
        index = self.tab_widget.currentIndex()
        # Skip the plus tab
        if index == self.plus_tab_index:
            return None
        if 0 <= index < len(self.prompt_tabs):
            return self.prompt_tabs[index]
        return None
    
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
        
        self.brush_label.setText(f"브러시 크기: {aligned_value}px")
        
        # Update inpaint layer
        if self.parent_widget and self.parent_widget.canvas.inpaint_layer:
            self.parent_widget.canvas.inpaint_layer.set_brush_size(aligned_value)
    
    def update_brush_size(self, size: int):
        """Update brush size display (called from canvas wheel event)"""
        self.brush_slider.setValue(size)
        self.brush_label.setText(f"브러시 크기: {size}px")
    
    def set_prompts(self, main_prompt: str, negative_prompt: str):
        """Set the prompts for current tab"""
        current_tab = self.get_current_tab()
        if current_tab:
            current_tab.main_prompt_edit.setPlainText(main_prompt)
            current_tab.negative_prompt_edit.setPlainText(negative_prompt)
    
    def _auto_fill_prompts_if_empty(self):
        """Auto-fill prompts from main window if they are empty"""
        current_tab = self.get_current_tab()
        if not current_tab:
            return
            
        # Check if prompts are already set
        if current_tab.main_prompt_edit.toPlainText().strip() or current_tab.negative_prompt_edit.toPlainText().strip():
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
                            current_tab.main_prompt_edit.setPlainText(main_prompt)
                            print(f"✅ Auto-filled main prompt from main window")
                    
                    # Get negative prompt from negative_prompt 
                    if hasattr(main_window, 'negative_prompt_textedit'):
                        negative_prompt = main_window.negative_prompt_textedit.toPlainText()
                        if negative_prompt:
                            current_tab.negative_prompt_edit.setPlainText(negative_prompt)
                            print(f"✅ Auto-filled negative prompt from main window")
        except Exception as e:
            print(f"⚠️ Could not auto-fill prompts: {e}")
    
    def clear_mask(self):
        """Clear the inpaint mask"""
        if self.parent_widget and self.parent_widget.canvas.inpaint_layer:
            self.parent_widget.canvas.clear_inpaint_mask()
    
    def generate_inpaint(self):
        """Start single inpaint generation from current tab"""
        # Prevent multiple simultaneous generations
        if self.is_generating or self.is_sequential_generating:
            print("⚠️ Already generating, please wait...")
            return
        
        # Early mask check
        if self.parent_widget and self.parent_widget.canvas:
            mask = self.parent_widget.canvas.get_inpaint_mask()
            if not mask:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "오류", "마스크가 비어있습니다. 인페인트 영역을 그려주세요.")
                print("⚠️ Mask is empty - please draw inpaint area")
                return
        
        current_tab = self.get_current_tab()
        if not current_tab:
            return
            
        if self.parent_widget:
            tab_data = current_tab.get_data()
            
            # Store prompts for persistence
            self.parent_widget.stored_main_prompt = tab_data.main_prompt
            self.parent_widget.stored_negative_prompt = tab_data.negative_prompt
            
            # Set generation state
            self.set_generating(True)
            self.status_bar.showMessage("생성 중...")
            
            # Store current tab data for virtual layer update check
            self.current_generation_data = tab_data
            
            # Call parent's generation method
            if hasattr(self.parent_widget, 'generate_inpaint'):
                self.parent_widget.generate_inpaint(
                    tab_data.main_prompt,
                    tab_data.negative_prompt,
                    tab_data.strength
                )
            else:
                print("⚠️ generate_inpaint method not found in parent widget")
                self.set_generating(False)
                self.status_bar.showMessage("오류: 생성 메서드를 찾을 수 없습니다", 3000)
    
    def generate_sequential(self):
        """Start sequential generation for all tabs"""
        # Prevent multiple simultaneous generations
        if self.is_generating or self.is_sequential_generating:
            print("⚠️ Already generating, please wait...")
            return
        
        # Early mask check
        if self.parent_widget and self.parent_widget.canvas:
            mask = self.parent_widget.canvas.get_inpaint_mask()
            if not mask:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "오류", "마스크가 비어있습니다. 인페인트 영역을 그려주세요.")
                print("⚠️ Mask is empty - please draw inpaint area")
                return
        
        if len(self.prompt_tabs) < 2:
            return
        
        # Build generation queue starting from current tab to the end only
        current_index = self.tab_widget.currentIndex()
        self.sequential_queue = []
        
        # Add tabs from current to end (excluding plus tab)
        # Only process from current tab to the last tab, no wrapping
        for i in range(current_index, min(len(self.prompt_tabs), self.plus_tab_index)):
            self.sequential_queue.append(i)
        
        # Start sequential generation
        self.is_sequential_generating = True
        self.current_sequential_index = 0
        self.status_bar.showMessage(f"연속 생성 시작: {len(self.sequential_queue)}개 탭")
        
        # Process first item in queue
        self._process_next_in_queue()
    
    def _process_next_in_queue(self):
        """Process next tab in sequential generation queue"""
        if not self.is_sequential_generating or not self.sequential_queue:
            return
        
        if self.current_sequential_index >= len(self.sequential_queue):
            # All done - delete virtual layers
            if self.parent_widget and hasattr(self.parent_widget, '_delete_virtual_layers'):
                self.parent_widget._delete_virtual_layers()
                print("🧹 Deleted virtual layers after sequential generation")
            
            self.is_sequential_generating = False
            self.sequential_queue = []
            self.current_sequential_index = 0
            self.status_bar.showMessage("연속 생성 완료", 3000)
            self.set_generating(False)
            return
        
        # Get next tab index
        tab_index = self.sequential_queue[self.current_sequential_index]
        
        # Switch to tab
        self.tab_widget.setCurrentIndex(tab_index)
        
        # Get tab data
        if 0 <= tab_index < len(self.prompt_tabs):
            tab_widget = self.prompt_tabs[tab_index]
            tab_data = tab_widget.get_data()
            
            # Update status
            self.status_bar.showMessage(
                f"연속 생성 중: 탭 {tab_index + 1}/{len(self.prompt_tabs)}"
            )
            
            # Store current tab data for virtual layer update check
            self.current_generation_data = tab_data
            self.current_generation_tab_index = tab_index
            
            # Set generation state
            self.set_generating(True)
            
            # Call parent's generation method
            if self.parent_widget and hasattr(self.parent_widget, 'generate_inpaint'):
                self.parent_widget.generate_inpaint(
                    tab_data.main_prompt,
                    tab_data.negative_prompt,
                    tab_data.strength
                )
            else:
                print("⚠️ generate_inpaint method not found")
                self.is_sequential_generating = False
                self.set_generating(False)
    
    def on_generation_complete(self, success: bool = True):
        """Called when a generation completes"""
        # Update seed preview after generation
        self.sync_seed_from_main()
        
        if self.is_sequential_generating:
            if success:
                # Move to next in queue
                self.current_sequential_index += 1
                # Small delay before next generation
                QTimer.singleShot(500, self._process_next_in_queue)
            else:
                # Stop on error - delete virtual layers
                if self.parent_widget and hasattr(self.parent_widget, '_delete_virtual_layers'):
                    self.parent_widget._delete_virtual_layers()
                    print("🧹 Deleted virtual layers after error")
                
                self.is_sequential_generating = False
                self.sequential_queue = []
                self.status_bar.showMessage("연속 생성 중단됨 (오류)", 3000)
                self.set_generating(False)
        else:
            # Single generation complete
            self.set_generating(False)
            self.status_bar.showMessage("생성 완료", 2000)
    
    def _on_seed_fix_toggled(self, checked: bool):
        """Handle seed fix checkbox toggle"""
        # Update main window's seed fix checkbox
        try:
            if self.parent_widget and hasattr(self.parent_widget, 'app_context'):
                app_context = self.parent_widget.app_context
                main_window = app_context.main_window
                
                if main_window and hasattr(main_window, 'seed_fix_checkbox'):
                    # Block signals to prevent recursion
                    main_window.seed_fix_checkbox.blockSignals(True)
                    main_window.seed_fix_checkbox.setChecked(checked)
                    main_window.seed_fix_checkbox.blockSignals(False)
                    print(f"✅ Synced seed fix to main window: {checked}")
        except Exception as e:
            print(f"⚠️ Could not sync seed fix: {e}")
        
        # Emit signal for other listeners
        self.seed_fix_changed.emit(checked)
    
    def sync_seed_fix_from_main(self, checked: bool):
        """Sync seed fix checkbox from main window"""
        self.seed_fix_checkbox.blockSignals(True)
        self.seed_fix_checkbox.setChecked(checked)
        self.seed_fix_checkbox.blockSignals(False)
    
    def _on_seed_refresh(self):
        """Generate new random seed and sync with main window"""
        # Generate random seed
        new_seed = random.randint(0, 9999999999)
        
        # Update main window's seed input
        try:
            if self.parent_widget and hasattr(self.parent_widget, 'app_context'):
                app_context = self.parent_widget.app_context
                main_window = app_context.main_window
                
                if main_window and hasattr(main_window, 'seed_input'):
                    main_window.seed_input.setText(str(new_seed))
                    print(f"✅ Generated new seed: {new_seed}")
                    
                    # Update our preview label
                    self.update_seed_preview(new_seed)
        except Exception as e:
            print(f"⚠️ Could not refresh seed: {e}")
    
    def update_seed_preview(self, seed_value: int):
        """Update the seed preview label"""
        self.seed_preview_label.setText(f"시드: {seed_value}")
    
    def sync_seed_from_main(self):
        """Sync seed value from main window"""
        try:
            if self.parent_widget and hasattr(self.parent_widget, 'app_context'):
                app_context = self.parent_widget.app_context
                main_window = app_context.main_window
                
                if main_window and hasattr(main_window, 'seed_input'):
                    seed_text = main_window.seed_input.text()
                    try:
                        seed_value = int(seed_text) if seed_text else 0
                    except ValueError:
                        seed_value = 0
                    
                    self.update_seed_preview(seed_value)
        except Exception as e:
            print(f"⚠️ Could not sync seed: {e}")
    
    def set_generating(self, is_generating: bool):
        """Set generation state and update UI"""
        self.is_generating = is_generating
        
        if is_generating or self.is_sequential_generating:
            # Change button text and disable
            if self.is_sequential_generating:
                self.sequential_button.setText("🔄 연속 생성중...")
                self.sequential_button.setEnabled(False)
            self.generate_button.setText("🔄 생성중...")
            self.generate_button.setEnabled(False)
            
            # Disable other controls during generation
            self.clear_mask_button.setEnabled(False)
            self.square_brush_button.setEnabled(False)
            self.circle_brush_button.setEnabled(False)
            self.rect_button.setEnabled(False)
            self.move_button.setEnabled(False)
            self.brush_slider.setEnabled(False)
            # Tab switching disabled during generation
            self.tab_widget.setEnabled(False)
        else:
            # Restore button text and enable
            self.generate_button.setText("🎨 생성")
            self.generate_button.setEnabled(True)
            self.sequential_button.setText("🔄 연속 생성")
            self.sequential_button.setEnabled(True)
            
            # Re-enable other controls
            self.clear_mask_button.setEnabled(True)
            self.square_brush_button.setEnabled(True)
            self.circle_brush_button.setEnabled(True)
            self.rect_button.setEnabled(True)
            self.move_button.setEnabled(True)
            self.brush_slider.setEnabled(True)
            self.tab_widget.setEnabled(True)
    
    def show_window(self):
        """Show the window if it was hidden"""
        self.show()
        self.raise_()
        self.activateWindow()
        
        # Sync seed value when showing
        self.sync_seed_from_main()
    
    def export_settings(self):
        """Export all tab settings to a JSON file"""
        # Ensure save directory exists
        save_dir = Path("sketchbook/save")
        save_dir.mkdir(parents=True, exist_ok=True)
        
        # Get file path from user
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "인페인트 설정 내보내기",
            str(save_dir / "inpaint_settings.json"),
            "JSON Files (*.json);;All Files (*)"
        )
        
        if not file_path:
            return
        
        try:
            # Collect all tab data
            settings = {
                "version": "1.0",
                "tabs": [],
                "brush_size": self.brush_slider.value(),
                "seed_fixed": self.seed_fix_checkbox.isChecked(),
                "draw_mode": self.mode_group.checkedId()
            }
            
            for tab in self.prompt_tabs:
                tab_data = tab.get_data()
                settings["tabs"].append({
                    "main_prompt": tab_data.main_prompt,
                    "negative_prompt": tab_data.negative_prompt,
                    "strength": tab_data.strength,
                    "update_virtual_layer": tab_data.update_virtual_layer
                })
            
            # Save to file
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
            
            self.status_bar.showMessage(f"설정이 저장되었습니다: {Path(file_path).name}", 3000)
            print(f"✅ Exported settings to: {file_path}")
            
        except Exception as e:
            QMessageBox.critical(self, "오류", f"설정 내보내기 실패:\n{str(e)}")
            print(f"❌ Failed to export settings: {e}")
    
    def import_settings(self):
        """Import tab settings from a JSON file"""
        # Ensure save directory exists
        save_dir = Path("sketchbook/save")
        save_dir.mkdir(parents=True, exist_ok=True)
        
        # Get file path from user
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "인페인트 설정 불러오기",
            str(save_dir),
            "JSON Files (*.json);;All Files (*)"
        )
        
        if not file_path or not os.path.exists(file_path):
            return
        
        try:
            # Load settings from file
            with open(file_path, 'r', encoding='utf-8') as f:
                settings = json.load(f)
            
            # Validate version
            if settings.get("version") != "1.0":
                QMessageBox.warning(self, "경고", "호환되지 않는 설정 파일 버전입니다.")
                return
            
            # Clear existing tabs (except plus tab)
            # Remove all tabs except the plus tab
            while len(self.prompt_tabs) > 0:
                # Always remove the first tab (non-plus tabs are before plus tab)
                self.tab_widget.removeTab(0)
                self.prompt_tabs.pop(0)
            
            # At this point, only plus tab remains at index 0
            self.plus_tab_index = 0
            
            # Load tabs
            tabs_data = settings.get("tabs", [])
            if not tabs_data:
                # If no tabs in file, create at least one
                self.add_new_tab()
            else:
                # Insert tabs in reverse order at index 0
                # This ensures tab 1 ends up at index 0
                for i in range(len(tabs_data) - 1, -1, -1):
                    tab_settings = tabs_data[i]
                    
                    # Create new tab
                    new_tab = PromptTabWidget(self)
                    
                    # Set tab data
                    tab_data = PromptTabData(
                        main_prompt=tab_settings.get("main_prompt", ""),
                        negative_prompt=tab_settings.get("negative_prompt", ""),
                        strength=tab_settings.get("strength", 1.0),
                        update_virtual_layer=tab_settings.get("update_virtual_layer", False)
                    )
                    new_tab.set_data(tab_data)
                    
                    # Insert at index 0 (before all other tabs including plus tab)
                    self.tab_widget.insertTab(
                        0,
                        new_tab,
                        f"탭 {i + 1}"
                    )
                    # Add to beginning of list since we're inserting in reverse
                    self.prompt_tabs.insert(0, new_tab)
                    
                    # Update plus tab index (it moves right with each insertion)
                    self.plus_tab_index = self.tab_widget.count() - 1
                
                # Hide close button for plus tab at its final position
                close_button = self.tab_widget.tabBar().tabButton(self.plus_tab_index, QTabBar.ButtonPosition.RightSide)
                if close_button:
                    close_button.hide()
            
            # Load other settings
            if "brush_size" in settings:
                self.brush_slider.setValue(settings["brush_size"])
            
            if "seed_fixed" in settings:
                self.seed_fix_checkbox.setChecked(settings["seed_fixed"])
            
            if "draw_mode" in settings:
                mode_id = settings["draw_mode"]
                button = self.mode_group.button(mode_id)
                if button:
                    button.setChecked(True)
                    self.on_mode_changed(button)
            
            # Select first tab
            if len(self.prompt_tabs) > 0:
                self.tab_widget.setCurrentIndex(0)
            
            # Update UI
            self._update_sequential_button()
            
            self.status_bar.showMessage(f"설정을 불러왔습니다: {Path(file_path).name}", 3000)
            print(f"✅ Imported settings from: {file_path}")
            
        except Exception as e:
            QMessageBox.critical(self, "오류", f"설정 불러오기 실패:\n{str(e)}")
            print(f"❌ Failed to import settings: {e}")
    
    def closeEvent(self, event):
        """Handle window close"""
        # Disable inpaint mode when closing the control window
        if self.parent_widget and hasattr(self.parent_widget, 'inpaint_button'):
            # Uncheck the inpaint button to disable mode
            self.parent_widget.inpaint_button.setChecked(False)
            # This will trigger _on_inpaint_mode_toggled(False)
        
        event.accept()