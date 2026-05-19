"""
SavePresetDialog - Dialog for saving Studio presets
"""

import os
import io
import json
import base64
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Optional, Dict

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QFrame, QScrollArea, QWidget,
    QInputDialog, QGridLayout
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PIL import Image

from legacy_desktop.ui.theme import DARK_COLORS, get_dynamic_styles, show_info, show_warning, show_error, show_question
from legacy_desktop.ui.scaling_manager import get_scaled_font_size, get_scaled_size


class SavePresetDialog(QDialog):
    """Dialog for saving Studio presets with thumbnails"""

    THUMB_SIZE = 386
    PREVIEW_THUMB_SIZE = 96  # Smaller for preview display
    PRESETS_BASE_DIR = Path("save/studio_presets")

    def __init__(
        self,
        frames_data: List[Dict],
        images: List[Tuple[int, Optional[Image.Image]]],
        global_prompts: Dict[str, str],
        parent=None
    ):
        """
        Args:
            frames_data: List of frame prompt_data dicts
            images: List of (frame_index, PIL.Image or None) tuples
            global_prompts: Dict with prefix_prompt, postfix_prompt, negative_prompt
            parent: Parent widget
        """
        super().__init__(parent)
        self.frames_data = frames_data
        self.images = images
        self.global_prompts = global_prompts
        self.thumbnails: Dict[int, str] = {}  # frame_index -> base64

        self.setWindowTitle("Save Studio Preset")
        self.setMinimumSize(get_scaled_size(500), get_scaled_size(400))
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

        # Ensure base directory exists
        self.PRESETS_BASE_DIR.mkdir(parents=True, exist_ok=True)

        self._generate_thumbnails()
        self._create_ui()

    def _generate_thumbnails(self):
        """Generate base64 thumbnails for all images"""
        for frame_index, pil_image in self.images:
            if pil_image:
                self.thumbnails[frame_index] = self._create_thumbnail(pil_image)

    def _create_thumbnail(self, pil_image: Image.Image) -> str:
        """Create base64 encoded thumbnail with black background"""
        # Create black background
        thumb = Image.new('RGB', (self.THUMB_SIZE, self.THUMB_SIZE), (0, 0, 0))

        # Resize original maintaining aspect ratio
        width, height = pil_image.size
        scale = min(self.THUMB_SIZE / width, self.THUMB_SIZE / height)
        new_width = int(width * scale)
        new_height = int(height * scale)

        # Ensure RGB mode
        if pil_image.mode == 'RGBA':
            resized = pil_image.convert('RGB').resize(
                (new_width, new_height), Image.Resampling.LANCZOS
            )
        else:
            resized = pil_image.resize(
                (new_width, new_height), Image.Resampling.LANCZOS
            )

        # Center on black background
        x_offset = (self.THUMB_SIZE - new_width) // 2
        y_offset = (self.THUMB_SIZE - new_height) // 2
        thumb.paste(resized, (x_offset, y_offset))

        # Encode to base64
        buffer = io.BytesIO()
        thumb.save(buffer, format='PNG')
        return base64.b64encode(buffer.getvalue()).decode('utf-8')

    def _create_ui(self):
        """Create dialog UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(get_scaled_size(12))
        layout.setContentsMargins(
            get_scaled_size(16), get_scaled_size(16),
            get_scaled_size(16), get_scaled_size(16)
        )

        dynamic_styles = get_dynamic_styles()

        # Title
        title_label = QLabel("Save Studio Preset")
        title_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['accent_blue']};
                font-size: {get_scaled_font_size(18)}px;
                font-weight: bold;
            }}
        """)
        layout.addWidget(title_label)

        # Preset name
        name_layout = QHBoxLayout()
        name_label = QLabel("Preset Name:")
        name_label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(14)}px;
            }}
        """)
        name_label.setFixedWidth(get_scaled_size(100))
        name_layout.addWidget(name_label)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Enter preset name...")
        self.name_input.setText(f"preset_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        self.name_input.setProperty("autocomplete_ignore", True)  # Disable autocomplete
        self.name_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 6px 10px;
                font-size: {get_scaled_font_size(14)}px;
            }}
        """)
        name_layout.addWidget(self.name_input)
        layout.addLayout(name_layout)

        # Folder selection
        folder_layout = QHBoxLayout()
        folder_label = QLabel("Folder:")
        folder_label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(14)}px;
            }}
        """)
        folder_label.setFixedWidth(get_scaled_size(100))
        folder_layout.addWidget(folder_label)

        self.folder_combo = QComboBox()
        self.folder_combo.setStyleSheet(dynamic_styles.get('compact_combobox', ''))
        self._populate_folder_combo()
        folder_layout.addWidget(self.folder_combo, 1)

        new_folder_btn = QPushButton("+ New Folder")
        new_folder_btn.setStyleSheet(dynamic_styles.get('secondary_button', ''))
        new_folder_btn.clicked.connect(self._on_new_folder)
        folder_layout.addWidget(new_folder_btn)
        layout.addLayout(folder_layout)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background-color: {DARK_COLORS['border']};")
        layout.addWidget(sep)

        # Preview section
        preview_label = QLabel(f"Preview ({len(self.thumbnails)} images):")
        preview_label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(14)}px;
                color: {DARK_COLORS['text_secondary']};
            }}
        """)
        layout.addWidget(preview_label)

        # Thumbnail preview scroll area
        preview_scroll = QScrollArea()
        preview_scroll.setWidgetResizable(True)
        preview_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        preview_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        preview_scroll.setFixedHeight(get_scaled_size(130))
        preview_scroll.setStyleSheet(f"""
            QScrollArea {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
            }}
        """)

        preview_widget = QWidget()
        preview_layout = QHBoxLayout(preview_widget)
        preview_layout.setContentsMargins(
            get_scaled_size(8), get_scaled_size(8),
            get_scaled_size(8), get_scaled_size(8)
        )
        preview_layout.setSpacing(get_scaled_size(8))

        # Add thumbnail previews
        for frame_index, base64_data in sorted(self.thumbnails.items()):
            thumb_frame = self._create_preview_thumbnail(frame_index, base64_data)
            preview_layout.addWidget(thumb_frame)

        if not self.thumbnails:
            no_image_label = QLabel("No images to preview")
            no_image_label.setStyleSheet(f"""
                QLabel {{
                    color: {DARK_COLORS['text_disabled']};
                    font-size: {get_scaled_font_size(14)}px;
                }}
            """)
            preview_layout.addWidget(no_image_label)

        preview_layout.addStretch()
        preview_scroll.setWidget(preview_widget)
        layout.addWidget(preview_scroll)

        # Info label
        info_label = QLabel(
            f"This will save: {len(self.frames_data)} frames, "
            f"{len(self.thumbnails)} thumbnails, global prompts"
        )
        info_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(13)}px;
            }}
        """)
        layout.addWidget(info_label)

        layout.addStretch()

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(dynamic_styles.get('secondary_button', ''))
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        save_btn = QPushButton("Save")
        save_btn.setStyleSheet(dynamic_styles.get('primary_button', ''))
        save_btn.clicked.connect(self._on_save)
        button_layout.addWidget(save_btn)

        layout.addLayout(button_layout)

    def _create_preview_thumbnail(self, frame_index: int, base64_data: str) -> QFrame:
        """Create a preview thumbnail widget"""
        frame = QFrame()
        frame.setFixedSize(
            get_scaled_size(self.PREVIEW_THUMB_SIZE + 10),
            get_scaled_size(self.PREVIEW_THUMB_SIZE + 25)
        )
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
            }}
        """)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        # Frame number label
        num_label = QLabel(f"[{frame_index + 1}]")
        num_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        num_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(12)}px;
            }}
        """)
        layout.addWidget(num_label)

        # Thumbnail image
        img_label = QLabel()
        img_label.setFixedSize(
            get_scaled_size(self.PREVIEW_THUMB_SIZE),
            get_scaled_size(self.PREVIEW_THUMB_SIZE)
        )
        img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Decode and display
        try:
            img_data = base64.b64decode(base64_data)
            pixmap = QPixmap()
            pixmap.loadFromData(img_data)
            scaled = pixmap.scaled(
                get_scaled_size(self.PREVIEW_THUMB_SIZE),
                get_scaled_size(self.PREVIEW_THUMB_SIZE),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            img_label.setPixmap(scaled)
        except Exception as e:
            img_label.setText("Error")
            print(f"Thumbnail decode error: {e}")

        layout.addWidget(img_label)
        return frame

    def _populate_folder_combo(self):
        """Populate folder combo with existing subfolders"""
        self.folder_combo.clear()
        self.folder_combo.addItem("(Root)")  # Root folder option

        if self.PRESETS_BASE_DIR.exists():
            for folder in sorted(self.PRESETS_BASE_DIR.iterdir()):
                if folder.is_dir() and not folder.name.startswith('.'):
                    self.folder_combo.addItem(folder.name)

    def _on_new_folder(self):
        """Create new subfolder"""
        name, ok = QInputDialog.getText(
            self, "New Folder",
            "Enter folder name:",
            QLineEdit.EchoMode.Normal
        )

        if ok and name:
            # Sanitize folder name
            name = "".join(c for c in name if c.isalnum() or c in ('_', '-', ' '))
            name = name.strip()

            if not name:
                show_warning(self, "Error", "Invalid folder name.")
                return

            new_folder = self.PRESETS_BASE_DIR / name
            try:
                new_folder.mkdir(parents=True, exist_ok=True)
                self._populate_folder_combo()
                # Select the new folder
                index = self.folder_combo.findText(name)
                if index >= 0:
                    self.folder_combo.setCurrentIndex(index)
                print(f"Created folder: {new_folder}")
            except Exception as e:
                show_error(self, "Error", f"Failed to create folder:\n{str(e)}")

    def _on_save(self):
        """Save preset to file"""
        name = self.name_input.text().strip()
        if not name:
            show_warning(self, "Warning", "Please enter a preset name.")
            return

        # Sanitize filename
        name = "".join(c for c in name if c.isalnum() or c in ('_', '-', ' '))
        name = name.strip()

        if not name:
            show_warning(self, "Warning", "Invalid preset name.")
            return

        # Determine save path
        folder_name = self.folder_combo.currentText()
        if folder_name == "(Root)":
            save_dir = self.PRESETS_BASE_DIR
        else:
            save_dir = self.PRESETS_BASE_DIR / folder_name

        save_dir.mkdir(parents=True, exist_ok=True)
        filepath = save_dir / f"{name}.json"

        # Check for existing file
        if filepath.exists():
            if not show_question(self, "Overwrite?", f"'{name}.json' already exists. Overwrite?"):
                return

        # Build preset data
        preset_data = {
            "version": "2.0",
            "created_at": datetime.now().isoformat(),
            "name": name,
            "global_prompts": self.global_prompts,
            "frames": []
        }

        for i, frame_data in enumerate(self.frames_data):
            frame_entry = {
                "index": i,
                "prompt_data": frame_data,
                "thumbnail": self.thumbnails.get(i, "")
            }
            preset_data["frames"].append(frame_entry)

        # Save to file
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(preset_data, f, indent=2, ensure_ascii=False)

            show_info(self, "Success", f"Preset saved to:\n{filepath}")
            self.accept()

        except Exception as e:
            show_error(self, "Error", f"Failed to save preset:\n{str(e)}")

    def get_save_path(self) -> Optional[Path]:
        """Get the path where preset was saved (after dialog accepted)"""
        name = self.name_input.text().strip()
        folder_name = self.folder_combo.currentText()

        if folder_name == "(Root)":
            return self.PRESETS_BASE_DIR / f"{name}.json"
        else:
            return self.PRESETS_BASE_DIR / folder_name / f"{name}.json"
