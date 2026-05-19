"""
PreviewDialog - Image preview window with stack navigation for Studio Tab
"""

from typing import List, Callable, Optional
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PIL import Image

from ui.theme import DARK_COLORS
from ui.scaling_manager import get_scaled_size, get_scaled_font_size


class PreviewDialog(QDialog):
    """Image preview dialog with stack navigation support"""

    PREVIEW_SIZE = 1024  # Max dimension for preview

    # Signal emitted when user selects an image from stack
    image_selected = pyqtSignal(int)  # stack index

    def __init__(
        self,
        frame_index: int,
        pil_image: Image.Image = None,
        pixmap: QPixmap = None,
        parent=None,
        # Stack navigation parameters
        pil_image_stack: List[Image.Image] = None,
        pixmap_stack: List[QPixmap] = None,
        current_stack_index: int = 0,
        on_select_callback: Callable[[int], None] = None
    ):
        """
        Args:
            frame_index: Frame index for title
            pil_image: Single PIL Image to display (legacy, used if stacks not provided)
            pixmap: Single QPixmap to display (legacy fallback)
            parent: Parent widget
            pil_image_stack: List of PIL Images for stack navigation
            pixmap_stack: List of QPixmaps for stack navigation
            current_stack_index: Initial index to display
            on_select_callback: Callback when SELECT button is clicked, receives stack index
        """
        super().__init__(parent)
        self.frame_index = frame_index
        self.on_select_callback = on_select_callback

        # Stack data
        if pil_image_stack:
            self.pil_image_stack = pil_image_stack
        elif pil_image:
            self.pil_image_stack = [pil_image]
        else:
            self.pil_image_stack = []

        if pixmap_stack:
            self.pixmap_stack = pixmap_stack
        elif pixmap:
            self.pixmap_stack = [pixmap]
        else:
            self.pixmap_stack = []

        self.current_index = current_stack_index
        self.stack_size = max(len(self.pil_image_stack), len(self.pixmap_stack))

        # Legacy compatibility
        self.pil_image = pil_image
        self.source_pixmap = pixmap

        self.setWindowTitle(f"Frame #{frame_index + 1} Preview")
        self.setModal(False)  # Non-blocking

        # Dark theme
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {DARK_COLORS['bg_primary']};
            }}
        """)

        self._create_ui()

    def _create_ui(self):
        """Create dialog UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            get_scaled_size(8), get_scaled_size(8),
            get_scaled_size(8), get_scaled_size(8)
        )
        layout.setSpacing(get_scaled_size(8))

        # Image label
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet(f"""
            QLabel {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
            }}
        """)
        layout.addWidget(self.image_label)

        # Stack navigation (only show if stack has multiple images)
        if self.stack_size > 1:
            nav_frame = self._create_stack_navigation()
            layout.addWidget(nav_frame)

        # Display the image
        self._display_image()

    def _display_image(self):
        """Display the current image resized to preview size"""
        display_pixmap = None

        # Get current image from stack
        pil_image = None
        pixmap = None

        if self.pil_image_stack and self.current_index < len(self.pil_image_stack):
            pil_image = self.pil_image_stack[self.current_index]
        if self.pixmap_stack and self.current_index < len(self.pixmap_stack):
            pixmap = self.pixmap_stack[self.current_index]

        if pil_image:
            # Resize PIL image
            resized = self._resize_image(pil_image)
            display_pixmap = self._pil_to_pixmap(resized)
        elif pixmap:
            # Resize QPixmap
            display_pixmap = self._resize_pixmap(pixmap)

        if display_pixmap:
            self.image_label.setPixmap(display_pixmap)
            # Set dialog size based on image (add extra height for nav bar if present)
            nav_height = get_scaled_size(50) if self.stack_size > 1 else 0
            self.setFixedSize(
                display_pixmap.width() + get_scaled_size(16),
                display_pixmap.height() + get_scaled_size(16) + nav_height
            )
        else:
            self.image_label.setText("No image available")
            self.setFixedSize(get_scaled_size(300), get_scaled_size(200))

        # Update navigation button states
        if self.stack_size > 1:
            self._update_navigation_state()

    def _create_stack_navigation(self) -> QFrame:
        """Create stack navigation controls"""
        nav_frame = QFrame()
        nav_frame.setFixedHeight(get_scaled_size(40))
        nav_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
            }}
        """)

        layout = QHBoxLayout(nav_frame)
        layout.setContentsMargins(
            get_scaled_size(8), get_scaled_size(4),
            get_scaled_size(8), get_scaled_size(4)
        )
        layout.setSpacing(get_scaled_size(8))

        nav_btn_style = f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 4px 16px;
                font-size: {get_scaled_font_size(16)}px;
                font-weight: bold;
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

        select_btn_style = f"""
            QPushButton {{
                background-color: {DARK_COLORS['accent_blue']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['accent_blue']};
                border-radius: 4px;
                padding: 4px 20px;
                font-size: {get_scaled_font_size(16)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['accent_blue_hover']};
            }}
            QPushButton:pressed {{
                background-color: {DARK_COLORS['accent_blue']};
            }}
        """

        # Previous button
        self.prev_btn = QPushButton("<")
        self.prev_btn.setFixedWidth(get_scaled_size(60))
        self.prev_btn.setStyleSheet(nav_btn_style)
        self.prev_btn.clicked.connect(self._on_prev_clicked)
        layout.addWidget(self.prev_btn)

        layout.addStretch()

        # Select button with current position
        self.select_btn = QPushButton(f"SELECT ({self.current_index + 1}/{self.stack_size})")
        self.select_btn.setStyleSheet(select_btn_style)
        self.select_btn.clicked.connect(self._on_select_clicked)
        layout.addWidget(self.select_btn)

        layout.addStretch()

        # Next button
        self.next_btn = QPushButton(">")
        self.next_btn.setFixedWidth(get_scaled_size(60))
        self.next_btn.setStyleSheet(nav_btn_style)
        self.next_btn.clicked.connect(self._on_next_clicked)
        layout.addWidget(self.next_btn)

        return nav_frame

    def _update_navigation_state(self):
        """Update navigation button states"""
        if not hasattr(self, 'prev_btn'):
            return

        self.prev_btn.setEnabled(self.current_index > 0)
        self.next_btn.setEnabled(self.current_index < self.stack_size - 1)
        self.select_btn.setText(f"SELECT ({self.current_index + 1}/{self.stack_size})")

    def _on_prev_clicked(self):
        """Navigate to previous image"""
        if self.current_index > 0:
            self.current_index -= 1
            self._display_image()

    def _on_next_clicked(self):
        """Navigate to next image"""
        if self.current_index < self.stack_size - 1:
            self.current_index += 1
            self._display_image()

    def _on_select_clicked(self):
        """Select current image and close dialog"""
        # Emit signal
        self.image_selected.emit(self.current_index)

        # Call callback if provided
        if self.on_select_callback:
            self.on_select_callback(self.current_index)

        # Close dialog
        self.accept()

    def _resize_image(self, pil_image: Image.Image) -> Image.Image:
        """Resize PIL image so longer side is PREVIEW_SIZE"""
        width, height = pil_image.size

        # Determine scale based on longer side
        if width >= height:
            # Landscape or square
            scale = self.PREVIEW_SIZE / width
        else:
            # Portrait
            scale = self.PREVIEW_SIZE / height

        new_width = int(width * scale)
        new_height = int(height * scale)

        return pil_image.resize((new_width, new_height), Image.Resampling.LANCZOS)

    def _resize_pixmap(self, pixmap: QPixmap) -> QPixmap:
        """Resize QPixmap so longer side is PREVIEW_SIZE"""
        width = pixmap.width()
        height = pixmap.height()

        # Determine scale based on longer side
        if width >= height:
            # Landscape or square
            new_width = self.PREVIEW_SIZE
            new_height = int(height * (self.PREVIEW_SIZE / width))
        else:
            # Portrait
            new_height = self.PREVIEW_SIZE
            new_width = int(width * (self.PREVIEW_SIZE / height))

        return pixmap.scaled(
            new_width, new_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )

    def _pil_to_pixmap(self, pil_image: Image.Image) -> QPixmap:
        """Convert PIL Image to QPixmap"""
        import io
        from PyQt6.QtGui import QImage

        # Convert to RGB if necessary
        if pil_image.mode == 'RGBA':
            # Keep alpha
            buffer = io.BytesIO()
            pil_image.save(buffer, format='PNG')
            buffer.seek(0)
            pixmap = QPixmap()
            pixmap.loadFromData(buffer.getvalue())
            return pixmap
        else:
            if pil_image.mode != 'RGB':
                pil_image = pil_image.convert('RGB')

            buffer = io.BytesIO()
            pil_image.save(buffer, format='PNG')
            buffer.seek(0)
            pixmap = QPixmap()
            pixmap.loadFromData(buffer.getvalue())
            return pixmap
