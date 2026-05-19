"""
ExportViewsDialog - Dialog for exporting frame images as grid with live preview
"""

import os
import io
from typing import List, Tuple, Optional
from datetime import datetime

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QRadioButton, QButtonGroup, QFrame, QFileDialog, QMessageBox,
    QComboBox, QGroupBox, QSplitter, QScrollArea, QWidget, QGridLayout,
    QApplication
)
from PyQt6.QtCore import Qt, QMimeData
from PyQt6.QtGui import QPixmap
from PIL import Image

from legacy_desktop.ui.theme import DARK_COLORS, get_dynamic_styles, show_info, show_warning, show_error
from legacy_desktop.ui.scaling_manager import get_scaled_font_size, get_scaled_size


class ExportViewsDialog(QDialog):
    """Dialog for exporting frame images as a combined grid image with live preview"""

    # Max dimension per image in the grid (for export)
    MAX_IMAGE_SIZE = 768

    # Preview sizes per column count
    PREVIEW_SIZES = {
        1: 768,  # 1 column: 768px width
        2: 512,  # 2 columns: 512px width each
        3: 368   # 3 columns: 368px width each
    }

    def __init__(self, images: List[Tuple[int, Image.Image]], parent=None):
        """
        Args:
            images: List of (frame_index, PIL.Image) tuples for frames with images
            parent: Parent widget
        """
        super().__init__(parent)
        self.images = images
        self.result_image: Optional[Image.Image] = None

        # Cache for preview thumbnails (keyed by (cols, use_crop))
        self._preview_cache = {}

        self.setWindowTitle("Export Views")
        # Increased size: height 1.5x, width adjusted for 2.25x preview area
        self.setMinimumSize(get_scaled_size(1200), get_scaled_size(900))
        self.resize(get_scaled_size(1500), get_scaled_size(1050))
        self.setModal(True)

        # Dark theme
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {DARK_COLORS['bg_primary']};
            }}
            QLabel {{
                color: {DARK_COLORS['text_primary']};
            }}
        """)

        self._create_ui()

        # Generate initial preview
        self._update_preview()

    def _create_ui(self):
        """Create dialog UI with splitter layout"""
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(
            get_scaled_size(8), get_scaled_size(8),
            get_scaled_size(8), get_scaled_size(8)
        )

        # Splitter for settings and preview
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background-color: {DARK_COLORS['border']};
                width: 2px;
            }}
        """)

        # Left side: Settings panel (fixed narrow width)
        settings_widget = self._create_settings_panel()
        settings_widget.setMinimumWidth(get_scaled_size(350))
        settings_widget.setMaximumWidth(get_scaled_size(400))
        splitter.addWidget(settings_widget)

        # Right side: Preview panel (expanded, 2.25x larger)
        preview_widget = self._create_preview_panel()
        splitter.addWidget(preview_widget)

        # Set initial splitter sizes (fixed settings, expanded preview)
        splitter.setSizes([350, 1100])

        main_layout.addWidget(splitter)

    def _create_settings_panel(self) -> QWidget:
        """Create left settings panel"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(get_scaled_size(12))
        layout.setContentsMargins(
            get_scaled_size(8), get_scaled_size(8),
            get_scaled_size(8), get_scaled_size(8)
        )

        dynamic_styles = get_dynamic_styles()

        # Title
        title_label = QLabel("Export Views as Grid Image")
        title_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['accent_blue']};
                font-size: {get_scaled_font_size(18)}px;
                font-weight: bold;
            }}
        """)
        layout.addWidget(title_label)

        # Image count info
        info_label = QLabel(f"Total images to export: {len(self.images)}")
        info_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(14)}px;
            }}
        """)
        layout.addWidget(info_label)

        # Warning label
        warning_frame = QFrame()
        warning_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border: 1px solid {DARK_COLORS['warning']};
                border-radius: 4px;
                padding: 8px;
            }}
        """)
        warning_layout = QVBoxLayout(warning_frame)
        warning_layout.setContentsMargins(
            get_scaled_size(8), get_scaled_size(8),
            get_scaled_size(8), get_scaled_size(8)
        )

        warning_label = QLabel(
            "Note: For best results, all images should have the same resolution. "
            "Mixed resolutions may result in uneven grid layout."
        )
        warning_label.setWordWrap(True)
        warning_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['warning']};
                font-size: {get_scaled_font_size(14)}px;
            }}
        """)
        warning_layout.addWidget(warning_label)
        layout.addWidget(warning_frame)

        # Layout selection group
        layout_group = QGroupBox("Grid Layout")
        layout_group.setStyleSheet(f"""
            QGroupBox {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(15)}px;
                font-weight: bold;
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                margin-top: 8px;
                padding-top: 12px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }}
        """)
        layout_group_layout = QVBoxLayout(layout_group)

        self.layout_button_group = QButtonGroup(self)

        radio_style = f"""
            QRadioButton {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(14)}px;
                spacing: 8px;
            }}
            QRadioButton::indicator {{
                width: {get_scaled_size(16)}px;
                height: {get_scaled_size(16)}px;
            }}
        """

        self.radio_3_per_row = QRadioButton("3 images per row")
        self.radio_3_per_row.setStyleSheet(radio_style)
        self.layout_button_group.addButton(self.radio_3_per_row, 3)
        self.radio_3_per_row.toggled.connect(self._on_layout_changed)
        layout_group_layout.addWidget(self.radio_3_per_row)

        self.radio_2_per_row = QRadioButton("2 images per row")
        self.radio_2_per_row.setStyleSheet(radio_style)
        self.radio_2_per_row.setChecked(True)  # Default to 2 per row
        self.layout_button_group.addButton(self.radio_2_per_row, 2)
        self.radio_2_per_row.toggled.connect(self._on_layout_changed)
        layout_group_layout.addWidget(self.radio_2_per_row)

        self.radio_1_per_row = QRadioButton("1 image per row (vertical stack)")
        self.radio_1_per_row.setStyleSheet(radio_style)
        self.layout_button_group.addButton(self.radio_1_per_row, 1)
        self.radio_1_per_row.toggled.connect(self._on_layout_changed)
        layout_group_layout.addWidget(self.radio_1_per_row)

        layout.addWidget(layout_group)

        # Asymmetric handling group
        crop_group = QGroupBox("Asymmetric Image Handling")
        crop_group.setStyleSheet(f"""
            QGroupBox {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(15)}px;
                font-weight: bold;
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                margin-top: 8px;
                padding-top: 12px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }}
        """)
        crop_layout = QHBoxLayout(crop_group)

        crop_label = QLabel("Method:")
        crop_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(14)}px;
            }}
        """)
        crop_layout.addWidget(crop_label)

        self.crop_combo = QComboBox()
        self.crop_combo.addItems(["Square Crop (Center)", "Auto (Fit with padding)"])
        self.crop_combo.setStyleSheet(dynamic_styles.get('compact_combobox', ''))
        self.crop_combo.currentIndexChanged.connect(self._on_crop_changed)
        crop_layout.addWidget(self.crop_combo, 1)

        layout.addWidget(crop_group)

        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet(f"background-color: {DARK_COLORS['border']};")
        layout.addWidget(separator)

        layout.addStretch()

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(dynamic_styles.get('secondary_button', ''))
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        copy_btn = QPushButton("Copy to Clipboard")
        copy_btn.setStyleSheet(dynamic_styles.get('secondary_button', ''))
        copy_btn.clicked.connect(self._on_copy_to_clipboard)
        copy_btn.setToolTip("Copy grid image to clipboard")
        button_layout.addWidget(copy_btn)

        export_btn = QPushButton("Export...")
        export_btn.setStyleSheet(dynamic_styles.get('primary_button', ''))
        export_btn.clicked.connect(self._on_export)
        button_layout.addWidget(export_btn)

        layout.addLayout(button_layout)

        return widget

    def _create_preview_panel(self) -> QWidget:
        """Create right preview panel with scroll area"""
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(
            get_scaled_size(8), get_scaled_size(8),
            get_scaled_size(8), get_scaled_size(8)
        )
        container_layout.setSpacing(get_scaled_size(8))

        # Preview title
        preview_title = QLabel("Preview")
        preview_title.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['accent_blue']};
                font-size: {get_scaled_font_size(16)}px;
                font-weight: bold;
            }}
        """)
        container_layout.addWidget(preview_title)

        # Scroll area for preview
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(True)
        self.preview_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.preview_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.preview_scroll.setStyleSheet(f"""
            QScrollArea {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
            }}
        """)

        # Preview container widget
        self.preview_container = QWidget()
        self.preview_container.setStyleSheet(f"""
            QWidget {{
                background-color: {DARK_COLORS['bg_secondary']};
            }}
        """)
        self.preview_layout = QVBoxLayout(self.preview_container)
        self.preview_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.preview_layout.setContentsMargins(
            get_scaled_size(8), get_scaled_size(8),
            get_scaled_size(8), get_scaled_size(8)
        )

        self.preview_scroll.setWidget(self.preview_container)
        container_layout.addWidget(self.preview_scroll)

        return container

    def _on_layout_changed(self, checked: bool):
        """Handle layout radio button change"""
        if checked:
            self._update_preview()

    def _on_crop_changed(self, index: int):
        """Handle crop method combo box change"""
        self._update_preview()

    def _update_preview(self):
        """Update preview with current settings"""
        if not self.images:
            return

        cols = self.layout_button_group.checkedId()
        use_crop = self.crop_combo.currentIndex() == 0

        # Clear current preview
        while self.preview_layout.count():
            item = self.preview_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Get preview size for current column count
        preview_cell_size = self.PREVIEW_SIZES.get(cols, 512)

        # Generate preview grid
        if cols == 1:
            # Vertical stack preview
            preview_image = self._create_preview_vertical_stack(preview_cell_size)
        else:
            preview_image = self._create_preview_grid(cols, use_crop, preview_cell_size)

        if preview_image:
            # Convert to QPixmap and display
            pixmap = self._pil_to_pixmap(preview_image)
            preview_label = QLabel()
            preview_label.setPixmap(pixmap)
            preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.preview_layout.addWidget(preview_label)

    def _create_preview_grid(self, cols: int, use_crop: bool, cell_size: int) -> Optional[Image.Image]:
        """Create preview grid image with specified cell size"""
        if not self.images:
            return None

        # Process each image for grid layout
        processed_images = []
        for _, img in self.images:
            processed = self._process_image_for_preview(img, use_crop, cell_size)
            processed_images.append(processed)

        if not processed_images:
            return None

        # Calculate grid dimensions
        num_images = len(processed_images)
        rows = (num_images + cols - 1) // cols

        grid_width = cols * cell_size
        grid_height = rows * cell_size

        # Create white background
        grid_image = Image.new('RGB', (grid_width, grid_height), (255, 255, 255))

        # Place images
        for idx, img in enumerate(processed_images):
            row = idx // cols
            col = idx % cols
            x = col * cell_size
            y = row * cell_size

            # Center image in cell if it's smaller
            if img.size[0] < cell_size or img.size[1] < cell_size:
                x_offset = (cell_size - img.size[0]) // 2
                y_offset = (cell_size - img.size[1]) // 2
                grid_image.paste(img, (x + x_offset, y + y_offset))
            else:
                grid_image.paste(img, (x, y))

        return grid_image

    def _create_preview_vertical_stack(self, width: int) -> Optional[Image.Image]:
        """Create vertical stack preview with specified width"""
        if not self.images:
            return None

        resized_images = []

        for _, img in self.images:
            # Resize to specified width maintaining aspect ratio
            orig_width, orig_height = img.size
            scale = width / orig_width
            new_height = int(orig_height * scale)

            resized = img.resize((width, new_height), Image.Resampling.LANCZOS)

            # Convert RGBA to RGB if needed
            if resized.mode == 'RGBA':
                rgb_img = Image.new('RGB', resized.size, (255, 255, 255))
                rgb_img.paste(resized, mask=resized.split()[3])
                resized = rgb_img

            resized_images.append(resized)

        if not resized_images:
            return None

        # Calculate total height
        total_height = sum(img.size[1] for img in resized_images)

        # Create result image and paste all images
        result = Image.new('RGB', (width, total_height), (255, 255, 255))
        y_offset = 0

        for img in resized_images:
            result.paste(img, (0, y_offset))
            y_offset += img.size[1]

        return result

    def _process_image_for_preview(self, img: Image.Image, use_crop: bool, target_size: int) -> Image.Image:
        """Process single image for preview grid placement"""
        if use_crop:
            return self._crop_to_square_preview(img, target_size)
        else:
            return self._fit_with_padding_preview(img, target_size)

    def _crop_to_square_preview(self, img: Image.Image, target_size: int) -> Image.Image:
        """Crop image to center square, then resize to target size"""
        width, height = img.size

        # Determine crop box for center square
        if width > height:
            left = (width - height) // 2
            top = 0
            right = left + height
            bottom = height
        elif height > width:
            left = 0
            top = (height - width) // 2
            right = width
            bottom = top + width
        else:
            left, top, right, bottom = 0, 0, width, height

        # Crop to square
        cropped = img.crop((left, top, right, bottom))

        # Resize to target size
        resized = cropped.resize((target_size, target_size), Image.Resampling.LANCZOS)

        # Convert RGBA to RGB
        if resized.mode == 'RGBA':
            rgb_img = Image.new('RGB', resized.size, (255, 255, 255))
            rgb_img.paste(resized, mask=resized.split()[3])
            resized = rgb_img

        return resized

    def _fit_with_padding_preview(self, img: Image.Image, target_size: int) -> Image.Image:
        """Fit image within target size with minimal padding"""
        width, height = img.size

        # Calculate scale to fit within target_size
        scale = min(target_size / width, target_size / height)
        new_width = int(width * scale)
        new_height = int(height * scale)

        # Resize maintaining aspect ratio
        resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

        # Calculate padding
        x_padding = (target_size - new_width) // 4
        y_padding = (target_size - new_height) // 4

        result_width = new_width + x_padding * 2
        result_height = new_height + y_padding * 2

        # Create white background
        result = Image.new('RGB', (result_width, result_height), (255, 255, 255))

        # Handle RGBA images
        if resized.mode == 'RGBA':
            result.paste(resized, (x_padding, y_padding), resized)
        else:
            result.paste(resized, (x_padding, y_padding))

        return result

    def _pil_to_pixmap(self, pil_image: Image.Image) -> QPixmap:
        """Convert PIL Image to QPixmap"""
        # Convert to RGB if necessary
        if pil_image.mode == 'RGBA':
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

    def _on_export(self):
        """Handle export button click"""
        if not self.images:
            show_warning(self, "Warning", "No images to export.")
            return

        # Get save path
        default_name = f"studio_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Save Grid Image",
            default_name,
            "PNG Files (*.png);;JPEG Files (*.jpg);;All Files (*.*)"
        )

        if not filepath:
            return

        try:
            # Generate grid image (full resolution for export)
            cols = self.layout_button_group.checkedId()
            use_crop = self.crop_combo.currentIndex() == 0

            grid_image = self._create_grid_image(cols, use_crop)

            if grid_image:
                grid_image.save(filepath)
                self.result_image = grid_image
                show_info(self, "Success", f"Grid image saved to:\n{filepath}")
                self.accept()
            else:
                show_error(self, "Error", "Failed to create grid image.")

        except Exception as e:
            show_error(self, "Error", f"Failed to export:\n{str(e)}")

    def _create_grid_image(self, cols: int, use_crop: bool) -> Optional[Image.Image]:
        """
        Create grid image from frame images (full resolution for export).

        Args:
            cols: Number of columns (images per row)
            use_crop: If True, crop to square; if False, fit with padding

        Returns:
            Combined PIL.Image or None on failure
        """
        if not self.images:
            return None

        # Special handling for vertical stack (1 column)
        if cols == 1:
            return self._create_vertical_stack()

        # Process each image for grid layout
        processed_images = []
        for _, img in self.images:
            processed = self._process_image(img, use_crop)
            processed_images.append(processed)

        if not processed_images:
            return None

        # Calculate grid dimensions
        num_images = len(processed_images)
        rows = (num_images + cols - 1) // cols  # Ceiling division

        # All processed images are now MAX_IMAGE_SIZE x MAX_IMAGE_SIZE
        cell_size = self.MAX_IMAGE_SIZE
        grid_width = cols * cell_size
        grid_height = rows * cell_size

        # Create white background
        grid_image = Image.new('RGB', (grid_width, grid_height), (255, 255, 255))

        # Place images
        for idx, img in enumerate(processed_images):
            row = idx // cols
            col = idx % cols
            x = col * cell_size
            y = row * cell_size

            # Center image in cell if it's smaller
            if img.size[0] < cell_size or img.size[1] < cell_size:
                x_offset = (cell_size - img.size[0]) // 2
                y_offset = (cell_size - img.size[1]) // 2
                grid_image.paste(img, (x + x_offset, y + y_offset))
            else:
                grid_image.paste(img, (x, y))

        return grid_image

    def _create_vertical_stack(self) -> Optional[Image.Image]:
        """
        Create vertical stack image - all images resized to 768 width and stacked vertically.
        No padding, no cropping - just resize width and concatenate.
        """
        if not self.images:
            return None

        STACK_WIDTH = 768
        resized_images = []

        for _, img in self.images:
            # Resize to 768 width maintaining aspect ratio
            width, height = img.size
            scale = STACK_WIDTH / width
            new_height = int(height * scale)

            resized = img.resize((STACK_WIDTH, new_height), Image.Resampling.LANCZOS)

            # Convert RGBA to RGB if needed
            if resized.mode == 'RGBA':
                rgb_img = Image.new('RGB', resized.size, (255, 255, 255))
                rgb_img.paste(resized, mask=resized.split()[3])
                resized = rgb_img

            resized_images.append(resized)

        if not resized_images:
            return None

        # Calculate total height
        total_height = sum(img.size[1] for img in resized_images)

        # Create result image and paste all images
        result = Image.new('RGB', (STACK_WIDTH, total_height), (255, 255, 255))
        y_offset = 0

        for img in resized_images:
            result.paste(img, (0, y_offset))
            y_offset += img.size[1]

        return result

    def _process_image(self, img: Image.Image, use_crop: bool) -> Image.Image:
        """
        Process single image for grid placement (full resolution).

        Args:
            img: Source PIL.Image
            use_crop: If True, crop to square center; if False, fit with padding

        Returns:
            Processed image (MAX_IMAGE_SIZE x MAX_IMAGE_SIZE)
        """
        if use_crop:
            return self._crop_to_square(img)
        else:
            return self._fit_with_padding(img)

    def _crop_to_square(self, img: Image.Image) -> Image.Image:
        """Crop image to center square, then resize to MAX_IMAGE_SIZE"""
        width, height = img.size

        # Determine crop box for center square
        if width > height:
            # Landscape - crop sides
            left = (width - height) // 2
            top = 0
            right = left + height
            bottom = height
        elif height > width:
            # Portrait - crop top/bottom
            left = 0
            top = (height - width) // 2
            right = width
            bottom = top + width
        else:
            # Already square
            left, top, right, bottom = 0, 0, width, height

        # Crop to square
        cropped = img.crop((left, top, right, bottom))

        # Resize to target size
        resized = cropped.resize(
            (self.MAX_IMAGE_SIZE, self.MAX_IMAGE_SIZE),
            Image.Resampling.LANCZOS
        )

        return resized

    def _fit_with_padding(self, img: Image.Image) -> Image.Image:
        """Fit image within MAX_IMAGE_SIZE while maintaining aspect ratio, add minimal white padding"""
        width, height = img.size

        # Calculate scale to fit within MAX_IMAGE_SIZE
        scale = min(self.MAX_IMAGE_SIZE / width, self.MAX_IMAGE_SIZE / height)
        new_width = int(width * scale)
        new_height = int(height * scale)

        # Resize maintaining aspect ratio
        resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

        # Calculate padding (half of the original padding for minimal padding)
        x_padding = (self.MAX_IMAGE_SIZE - new_width) // 4  # Half padding
        y_padding = (self.MAX_IMAGE_SIZE - new_height) // 4  # Half padding

        # Result size is image size plus minimal padding
        result_width = new_width + x_padding * 2
        result_height = new_height + y_padding * 2

        # Create white background with reduced padding
        result = Image.new('RGB', (result_width, result_height), (255, 255, 255))

        # Handle RGBA images
        if resized.mode == 'RGBA':
            result.paste(resized, (x_padding, y_padding), resized)
        else:
            result.paste(resized, (x_padding, y_padding))

        return result

    def _on_copy_to_clipboard(self):
        """Copy grid image to clipboard"""
        if not self.images:
            show_warning(self, "Warning", "No images to copy.")
            return

        try:
            # Generate grid image (full resolution)
            cols = self.layout_button_group.checkedId()
            use_crop = self.crop_combo.currentIndex() == 0

            grid_image = self._create_grid_image(cols, use_crop)

            if grid_image:
                # Convert PIL image to QPixmap for clipboard
                pixmap = self._pil_to_pixmap(grid_image)

                # Copy to clipboard
                clipboard = QApplication.clipboard()
                clipboard.setPixmap(pixmap)

                self.result_image = grid_image
                show_info(self, "Success", "Grid image copied to clipboard.")
            else:
                show_error(self, "Error", "Failed to create grid image.")

        except Exception as e:
            show_error(self, "Error", f"Failed to copy to clipboard:\n{str(e)}")
