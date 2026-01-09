"""
ResultImageFrame - Individual result image frame widget for Studio Tab
"""

from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QSizePolicy, QApplication, QMessageBox, QFileDialog, QComboBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QTimer
from PyQt6.QtGui import QPixmap, QImage, QPainter, QColor
from PIL import Image
from ui.theme import DARK_COLORS, get_dynamic_styles
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
import io
import os


class ResultImageFrame(QFrame):
    """Individual result image frame with image stack support"""

    # Signals
    generate_requested = pyqtSignal(int)       # frame index
    delete_requested = pyqtSignal(int)         # frame index
    prompt_edit_requested = pyqtSignal(int)    # frame index
    save_requested = pyqtSignal(int)           # frame index
    save_all_requested = pyqtSignal(int)       # frame index
    resolution_changed = pyqtSignal(int, str)  # frame index, resolution string

    # Standard Resolution options only
    STANDARD_RESOLUTIONS = [
        "832 x 1216",
        "896 x 1152",
        "960 x 1088",
        "1024 x 1024",
        "1088 x 960",
        "1152 x 896",
        "1216 x 832"
    ]

    def __init__(self, index: int, parent=None):
        super().__init__(parent)
        self.index = index
        self.image_stack: list = []  # List of QPixmap
        self.pil_image_stack: list = []  # List of PIL Image (for saving)
        self.current_stack_index = 0
        self.prompt_data: dict = {
            "prompt": "",
            "negative_prompt": "",
            "seed": -1,
            "enabled": True,
            "resolution": "1024 x 1024"  # Default resolution
        }

        # Resize debounce timer - prevents UI thrashing during resize
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._update_display)
        self._last_size = None

        self.setFrameStyle(QFrame.Shape.Box)
        self.setLineWidth(1)

        # Frame size - designed for 3x4 grid
        # Use Preferred policy for uniform sizing by manager
        self.setMinimumSize(get_scaled_size(180), get_scaled_size(225))
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        # Dark theme styling
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 5px;
            }}
        """)

        self._create_ui()
        self._update_stack_navigation()

    def _create_ui(self):
        """Create the frame UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(4)

        # 1. Header - Frame management area
        header = self._create_header()
        layout.addWidget(header)

        # 2. Image display area (expanding)
        image_label = self._create_image_display()
        layout.addWidget(image_label, 1)

        # 3. Stack navigation
        stack_nav = self._create_stack_navigation()
        layout.addWidget(stack_nav)

        # 4. Action buttons
        action_buttons = self._create_action_buttons()
        layout.addWidget(action_buttons)

    def _create_header(self) -> QFrame:
        """Create header with management buttons"""
        header = QFrame()
        header.setFixedHeight(get_scaled_size(28))
        header.setStyleSheet("border: none; background: transparent;")

        layout = QHBoxLayout(header)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        dynamic_styles = get_dynamic_styles()

        # Compact button style
        compact_btn_style = f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 3px;
                padding: 2px 6px;
                font-size: {get_scaled_font_size(13)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
            QPushButton:pressed {{
                background-color: {DARK_COLORS['bg_pressed']};
            }}
        """

        # Prompt setting button
        self.prompt_btn = QPushButton("Prompt")
        self.prompt_btn.setStyleSheet(compact_btn_style)
        self.prompt_btn.setToolTip("Edit prompt settings")
        self.prompt_btn.clicked.connect(self._on_prompt_clicked)
        layout.addWidget(self.prompt_btn)

        # Order button (hidden for now)
        self.order_btn = QPushButton("Order")
        self.order_btn.setStyleSheet(compact_btn_style)
        self.order_btn.setToolTip("Change frame order")
        self.order_btn.setEnabled(False)
        self.order_btn.setVisible(False)  # Hidden until implemented
        layout.addWidget(self.order_btn)

        # Expand button - opens preview window
        self.expand_btn = QPushButton("Expand")
        self.expand_btn.setStyleSheet(compact_btn_style)
        self.expand_btn.setToolTip("Open image preview window")
        self.expand_btn.clicked.connect(self._on_expand_clicked)
        layout.addWidget(self.expand_btn)

        # Resolution combo box
        self.resolution_combo = QComboBox()
        self.resolution_combo.setFixedWidth(get_scaled_size(95))
        self.resolution_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 3px;
                padding: 2px 4px;
                font-size: {get_scaled_font_size(12)}px;
            }}
            QComboBox::drop-down {{
                width: {get_scaled_size(16)}px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                selection-background-color: {DARK_COLORS['accent_blue']};
            }}
        """)
        for res in self.STANDARD_RESOLUTIONS:
            self.resolution_combo.addItem(res)
        self.resolution_combo.setCurrentText("1024 x 1024")
        self.resolution_combo.currentTextChanged.connect(self._on_resolution_changed)
        self.resolution_combo.setToolTip("Select generation resolution")
        layout.addWidget(self.resolution_combo)

        layout.addStretch()

        # Delete/Reset button
        self.delete_btn = QPushButton("X")
        self.delete_btn.setFixedSize(get_scaled_size(22), get_scaled_size(22))
        self.delete_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #703030;
                color: #ffffff;
                border: 1px solid #804040;
                border-radius: 3px;
                font-weight: bold;
                font-size: {get_scaled_font_size(14)}px;
            }}
            QPushButton:hover {{
                background-color: #904040;
            }}
            QPushButton:pressed {{
                background-color: #502020;
            }}
        """)
        self.delete_btn.setToolTip("Delete frame (reset if last)")
        self.delete_btn.clicked.connect(self._on_delete_clicked)
        layout.addWidget(self.delete_btn)

        return header

    def _create_image_display(self) -> QLabel:
        """Create expanding image display area"""
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setMinimumSize(get_scaled_size(150), get_scaled_size(150))
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        label.setScaledContents(False)
        label.setStyleSheet(f"""
            QLabel {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 3px;
            }}
        """)

        # Set placeholder
        self._set_placeholder(label)

        self.image_label = label
        return label

    def _set_placeholder(self, label: QLabel = None):
        """Set placeholder image"""
        if label is None:
            label = self.image_label

        # Create placeholder with frame index
        placeholder_text = f"#{self.index + 1}"
        label.setText(placeholder_text)
        label.setStyleSheet(f"""
            QLabel {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 3px;
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(26)}px;
            }}
        """)

    def _create_stack_navigation(self) -> QFrame:
        """Create stack navigation controls"""
        nav = QFrame()
        nav.setFixedHeight(get_scaled_size(26))
        nav.setStyleSheet("border: none; background: transparent;")

        layout = QHBoxLayout(nav)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(4)

        nav_btn_style = f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 3px;
                padding: 2px 8px;
                font-size: {get_scaled_font_size(14)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
            QPushButton:pressed {{
                background-color: {DARK_COLORS['bg_pressed']};
            }}
            QPushButton:disabled {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_disabled']};
            }}
        """

        # Previous button (2.5x wider for easier clicking)
        self.prev_btn = QPushButton("<")
        self.prev_btn.setFixedWidth(get_scaled_size(75))
        self.prev_btn.setStyleSheet(nav_btn_style)
        self.prev_btn.clicked.connect(self.show_prev_image)
        layout.addWidget(self.prev_btn)

        # Stack indicator label
        self.stack_label = QLabel("0 / 0")
        self.stack_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stack_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(13)}px;
            }}
        """)
        layout.addWidget(self.stack_label, 1)

        # Next button (2.5x wider for easier clicking)
        self.next_btn = QPushButton(">")
        self.next_btn.setFixedWidth(get_scaled_size(75))
        self.next_btn.setStyleSheet(nav_btn_style)
        self.next_btn.clicked.connect(self.show_next_image)
        layout.addWidget(self.next_btn)

        return nav

    def _create_action_buttons(self) -> QFrame:
        """Create action buttons row"""
        actions = QFrame()
        actions.setFixedHeight(get_scaled_size(32))
        actions.setStyleSheet("border: none; background: transparent;")

        layout = QHBoxLayout(actions)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(3)

        action_btn_style = f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 3px;
                padding: 4px 6px;
                font-size: {get_scaled_font_size(13)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
            QPushButton:pressed {{
                background-color: {DARK_COLORS['bg_pressed']};
            }}
            QPushButton:disabled {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_disabled']};
            }}
        """

        # Generate button
        self.generate_btn = QPushButton("Gen")
        self.generate_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['accent_blue']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['accent_blue']};
                border-radius: 3px;
                padding: 4px 6px;
                font-size: {get_scaled_font_size(13)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['accent_blue_hover']};
            }}
            QPushButton:pressed {{
                background-color: {DARK_COLORS['accent_blue']};
            }}
            QPushButton:disabled {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_disabled']};
            }}
        """)
        self.generate_btn.setToolTip("Generate image for this frame")
        self.generate_btn.clicked.connect(self._on_generate_clicked)
        layout.addWidget(self.generate_btn)

        # Save current button
        self.save_btn = QPushButton("Save")
        self.save_btn.setStyleSheet(action_btn_style)
        self.save_btn.setToolTip("Save current image")
        self.save_btn.clicked.connect(self._on_save_clicked)
        layout.addWidget(self.save_btn)

        # Save all button
        self.save_all_btn = QPushButton("All")
        self.save_all_btn.setStyleSheet(action_btn_style)
        self.save_all_btn.setToolTip("Save all stacked images")
        self.save_all_btn.clicked.connect(self._on_save_all_clicked)
        layout.addWidget(self.save_all_btn)

        return actions

    # === Signal handlers ===
    def _on_prompt_clicked(self):
        """Handle prompt button click"""
        self.prompt_edit_requested.emit(self.index)

    def _on_delete_clicked(self):
        """Handle delete button click"""
        self.delete_requested.emit(self.index)

    def _on_generate_clicked(self):
        """Handle generate button click"""
        self.generate_requested.emit(self.index)

    def _on_save_clicked(self):
        """Handle save button click"""
        self.save_requested.emit(self.index)

    def _on_save_all_clicked(self):
        """Handle save all button click"""
        self.save_all_requested.emit(self.index)

    # === Image stack management ===
    def add_image(self, pixmap: QPixmap, pil_image: Image.Image = None):
        """Add image to stack"""
        if pixmap and not pixmap.isNull():
            self.image_stack.append(pixmap)
            if pil_image:
                self.pil_image_stack.append(pil_image)
            else:
                self.pil_image_stack.append(None)

            # Show the newly added image
            self.current_stack_index = len(self.image_stack) - 1
            self._update_display()
            self._update_stack_navigation()

    def show_next_image(self):
        """Show next image in stack"""
        if self.image_stack and self.current_stack_index < len(self.image_stack) - 1:
            self.current_stack_index += 1
            self._update_display()
            self._update_stack_navigation()

    def show_prev_image(self):
        """Show previous image in stack"""
        if self.image_stack and self.current_stack_index > 0:
            self.current_stack_index -= 1
            self._update_display()
            self._update_stack_navigation()

    def clear_stack(self):
        """Clear all images from stack"""
        self.image_stack.clear()
        self.pil_image_stack.clear()
        self.current_stack_index = 0
        self._set_placeholder()
        self._update_stack_navigation()

    def _update_display(self):
        """Update image display to fit current label size"""
        if self.image_stack and 0 <= self.current_stack_index < len(self.image_stack):
            pixmap = self.image_stack[self.current_stack_index]

            # Scale to fit current label size while maintaining aspect ratio
            scaled = pixmap.scaled(
                self.image_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.image_label.setPixmap(scaled)
            self.image_label.setStyleSheet(f"""
                QLabel {{
                    background-color: {DARK_COLORS['bg_primary']};
                    border: 1px solid {DARK_COLORS['border']};
                    border-radius: 3px;
                }}
            """)
        else:
            self._set_placeholder()

    def _update_stack_navigation(self):
        """Update stack navigation controls"""
        total = len(self.image_stack)
        current = self.current_stack_index + 1 if total > 0 else 0

        self.stack_label.setText(f"{current} / {total}")
        self.prev_btn.setEnabled(self.current_stack_index > 0)
        self.next_btn.setEnabled(self.current_stack_index < total - 1)
        self.save_btn.setEnabled(total > 0)
        self.save_all_btn.setEnabled(total > 0)

    def resizeEvent(self, event):
        """Handle resize with debouncing to prevent UI thrashing"""
        super().resizeEvent(event)

        # Skip if no images to display
        if not self.image_stack:
            return

        # Only trigger update if size actually changed significantly
        new_size = self.image_label.size()
        if self._last_size is None or self._last_size != new_size:
            self._last_size = new_size
            # Restart debounce timer - only the last resize triggers update
            self._resize_timer.start()

    # === Prompt management ===
    def set_prompt_data(self, data: dict):
        """Set prompt configuration"""
        self.prompt_data.update(data)
        # Visual indicator when prompt is set
        self._update_prompt_indicator()

    def get_prompt_data(self) -> dict:
        """Get prompt configuration"""
        return self.prompt_data.copy()

    def has_prompt(self) -> bool:
        """Check if prompt is configured"""
        return bool(self.prompt_data.get('prompt', '').strip())

    def _update_prompt_indicator(self):
        """Update visual indicator for prompt status"""
        if self.has_prompt():
            self.prompt_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {DARK_COLORS['success']};
                    color: {DARK_COLORS['text_primary']};
                    border: 1px solid {DARK_COLORS['success']};
                    border-radius: 3px;
                    padding: 2px 6px;
                    font-size: {get_scaled_font_size(13)}px;
                }}
                QPushButton:hover {{
                    background-color: {DARK_COLORS['success']};
                    opacity: 0.8;
                }}
            """)
        else:
            self.prompt_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {DARK_COLORS['bg_tertiary']};
                    color: {DARK_COLORS['text_primary']};
                    border: 1px solid {DARK_COLORS['border']};
                    border-radius: 3px;
                    padding: 2px 6px;
                    font-size: {get_scaled_font_size(13)}px;
                }}
                QPushButton:hover {{
                    background-color: {DARK_COLORS['bg_hover']};
                }}
            """)

    # === Save functionality ===
    def save_current_image(self, filepath: str = None) -> bool:
        """Save current displayed image"""
        if not self.image_stack:
            return False

        try:
            # Try to use PIL image if available
            if self.pil_image_stack and self.pil_image_stack[self.current_stack_index]:
                pil_img = self.pil_image_stack[self.current_stack_index]
                if filepath:
                    pil_img.save(filepath)
                    return True

            # Fallback to QPixmap
            pixmap = self.image_stack[self.current_stack_index]
            if filepath:
                return pixmap.save(filepath)

            return False
        except Exception as e:
            print(f"Error saving image: {e}")
            return False

    def save_all_images(self, directory: str, prefix: str = "frame") -> int:
        """Save all stacked images to directory"""
        if not self.image_stack:
            return 0

        saved_count = 0
        for i, pixmap in enumerate(self.image_stack):
            try:
                filepath = os.path.join(directory, f"{prefix}_{self.index + 1}_{i + 1}.png")

                # Try PIL image first
                if self.pil_image_stack and i < len(self.pil_image_stack) and self.pil_image_stack[i]:
                    self.pil_image_stack[i].save(filepath)
                    saved_count += 1
                elif pixmap.save(filepath):
                    saved_count += 1

            except Exception as e:
                print(f"Error saving image {i}: {e}")

        return saved_count

    def get_stack_count(self) -> int:
        """Get number of images in stack"""
        return len(self.image_stack)

    def get_current_pil_image(self):
        """Get current PIL Image from stack (for export)"""
        if not self.pil_image_stack or self.current_stack_index >= len(self.pil_image_stack):
            return None
        return self.pil_image_stack[self.current_stack_index]

    def reset(self):
        """Reset frame to initial state"""
        self.clear_stack()
        self.prompt_data = {
            "prompt": "",
            "negative_prompt": "",
            "seed": -1,
            "enabled": True,
            "resolution": "1024 x 1024"
        }
        self.resolution_combo.setCurrentText("1024 x 1024")
        self._update_prompt_indicator()

    # === Resolution management ===
    def _on_resolution_changed(self, resolution: str):
        """Handle resolution combo box change"""
        self.prompt_data["resolution"] = resolution
        self.resolution_changed.emit(self.index, resolution)

    def set_resolution(self, resolution: str):
        """Set resolution from external source (e.g., global setting)"""
        if resolution in self.STANDARD_RESOLUTIONS:
            self.resolution_combo.blockSignals(True)
            self.resolution_combo.setCurrentText(resolution)
            self.prompt_data["resolution"] = resolution
            self.resolution_combo.blockSignals(False)

    def get_resolution(self) -> str:
        """Get current resolution"""
        return self.prompt_data.get("resolution", "1024 x 1024")

    def set_generating_state(self, is_generating: bool):
        """Set generating state for UI feedback"""
        if is_generating:
            self.generate_btn.setText("...")
            self.generate_btn.setEnabled(False)
        else:
            self.generate_btn.setText("Gen")
            self.generate_btn.setEnabled(True)

    def set_uniform_size(self, width: int, height: int):
        """Set uniform fixed size for this frame (called by manager for consistent grid)"""
        self.setFixedSize(width, height)
        # Trigger display update to rescale image to new size
        if self.image_stack:
            self._update_display()

    def _on_expand_clicked(self):
        """Open preview window for current image with stack navigation"""
        if not self.image_stack:
            return

        from tabs.studio.dialogs.preview_dialog import PreviewDialog

        # Callback to set selected stack index
        def on_image_selected(stack_index: int):
            self.current_stack_index = stack_index
            self._update_display()
            self._update_stack_navigation()

        # Pass full stacks for navigation
        dialog = PreviewDialog(
            frame_index=self.index,
            parent=self,
            pil_image_stack=self.pil_image_stack,
            pixmap_stack=self.image_stack,
            current_stack_index=self.current_stack_index,
            on_select_callback=on_image_selected
        )
        dialog.show()  # Non-blocking show
