"""
OpenPresetDialog - Dialog for opening Studio presets with preview
"""

import os
import io
import json
import base64
from pathlib import Path
from typing import Optional, Dict, List

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QWidget, QTreeWidget,
    QTreeWidgetItem, QSplitter, QTextEdit, QGridLayout, QMenu, QSizePolicy
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap, QAction

from ui.theme import DARK_COLORS, get_dynamic_styles, show_warning, show_error, show_question
from ui.scaling_manager import get_scaled_font_size, get_scaled_size


class OpenPresetDialog(QDialog):
    """Dialog for opening Studio presets with TreeView and preview"""

    PRESETS_BASE_DIR = Path("save/studio_presets")
    THUMBNAIL_DISPLAY_SIZE = 180  # Display size for thumbnails in grid

    # Load mode constants
    LOAD_ALL = "all"
    LOAD_EVENTS_ONLY = "events_only"
    LOAD_GLOBAL_ONLY = "global_only"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_preset_path: Optional[Path] = None
        self.preset_data: Optional[Dict] = None
        self.load_mode: str = self.LOAD_ALL  # Default to load all

        self.setWindowTitle("Open Studio Preset")
        self.setMinimumSize(get_scaled_size(1350), get_scaled_size(900))
        self.resize(get_scaled_size(1500), get_scaled_size(975))
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

        self._create_ui()
        self._load_tree()

    def _create_ui(self):
        """Create dialog UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(get_scaled_size(8))
        layout.setContentsMargins(
            get_scaled_size(12), get_scaled_size(12),
            get_scaled_size(12), get_scaled_size(12)
        )

        dynamic_styles = get_dynamic_styles()

        # Title
        title_label = QLabel("Open Studio Preset")
        title_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['accent_blue']};
                font-size: {get_scaled_font_size(21)}px;
                font-weight: bold;
            }}
        """)
        layout.addWidget(title_label)

        # Main splitter (3 panels)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background-color: {DARK_COLORS['border']};
                width: 2px;
            }}
        """)

        # Left panel - TreeView
        left_panel = self._create_tree_panel()
        left_panel.setMinimumWidth(get_scaled_size(300))  # Fixed minimum width for TreeView (1.5x)
        splitter.addWidget(left_panel)

        # Center panel - Details
        center_panel = self._create_details_panel()
        splitter.addWidget(center_panel)

        # Right panel - Thumbnails
        right_panel = self._create_thumbnails_panel()
        right_panel.setMinimumWidth(get_scaled_size(400))  # Fixed minimum width for Thumbnails (1.6x)
        splitter.addWidget(right_panel)

        # Set stretch factors (20%, 45%, 35%)
        splitter.setStretchFactor(0, 20)
        splitter.setStretchFactor(1, 45)
        splitter.setStretchFactor(2, 35)

        layout.addWidget(splitter, 1)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(dynamic_styles.get('secondary_button', ''))
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        # Get :Sequence button
        self.get_sequence_btn = QPushButton("Get :Sequence")
        self.get_sequence_btn.setStyleSheet(dynamic_styles.get('secondary_button', ''))
        self.get_sequence_btn.clicked.connect(self._on_get_sequence)
        self.get_sequence_btn.setEnabled(False)
        self.get_sequence_btn.setToolTip("Generate :sequence text from frame events")
        button_layout.addWidget(self.get_sequence_btn)

        # Load Events Only button
        self.load_events_btn = QPushButton("Load Events Only")
        self.load_events_btn.setStyleSheet(dynamic_styles.get('secondary_button', ''))
        self.load_events_btn.clicked.connect(self._on_load_events_only)
        self.load_events_btn.setEnabled(False)
        self.load_events_btn.setToolTip("Load only frame prompts (without global prefix/postfix/negative)")
        button_layout.addWidget(self.load_events_btn)

        # Load Pre/Postfix/Negative button
        self.load_global_btn = QPushButton("Load Pre/Postfix/Negative")
        self.load_global_btn.setStyleSheet(dynamic_styles.get('secondary_button', ''))
        self.load_global_btn.clicked.connect(self._on_load_global_only)
        self.load_global_btn.setEnabled(False)
        self.load_global_btn.setToolTip("Load only global prefix, postfix, and negative prompts")
        button_layout.addWidget(self.load_global_btn)

        # Load All button (renamed from Load)
        self.load_btn = QPushButton("Load All")
        self.load_btn.setStyleSheet(dynamic_styles.get('primary_button', ''))
        self.load_btn.clicked.connect(self._on_load)
        self.load_btn.setEnabled(False)
        self.load_btn.setToolTip("Load all data (frames + global prompts)")
        button_layout.addWidget(self.load_btn)

        layout.addLayout(button_layout)

    def _create_tree_panel(self) -> QWidget:
        """Create left panel with TreeWidget"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(get_scaled_size(4))

        # Header
        header_layout = QHBoxLayout()
        header_label = QLabel("Presets")
        header_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(17)}px;
                font-weight: bold;
            }}
        """)
        header_layout.addWidget(header_label)
        header_layout.addStretch()

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setFixedHeight(get_scaled_size(24))
        refresh_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 3px;
                padding: 2px 8px;
                font-size: {get_scaled_font_size(15)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
        """)
        refresh_btn.clicked.connect(self._load_tree)
        header_layout.addWidget(refresh_btn)
        layout.addLayout(header_layout)

        # TreeWidget
        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderLabel("Studio Presets")
        self.tree_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_widget.customContextMenuRequested.connect(self._show_tree_context_menu)
        self.tree_widget.itemClicked.connect(self._on_tree_item_clicked)
        self.tree_widget.setStyleSheet(f"""
            QTreeWidget {{
                background-color: #FFFFFF;
                color: #000000;
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                font-size: {get_scaled_font_size(17)}px;
            }}
            QTreeWidget::item:selected {{
                background-color: #0078D4;
                color: #FFFFFF;
            }}
            QTreeWidget::item:hover {{
                background-color: #E5E5E5;
                color: #000000;
            }}
            QHeaderView::section {{
                background-color: #F0F0F0;
                color: #000000;
                padding: 5px;
                border: none;
                font-weight: bold;
            }}
        """)
        layout.addWidget(self.tree_widget)

        return panel

    def _create_details_panel(self) -> QWidget:
        """Create center panel with preset details"""
        panel = QWidget()
        panel.setStyleSheet(f"""
            QWidget {{
                background-color: {DARK_COLORS['bg_secondary']};
                border-radius: 4px;
            }}
        """)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(
            get_scaled_size(8), get_scaled_size(8),
            get_scaled_size(8), get_scaled_size(8)
        )
        layout.setSpacing(get_scaled_size(8))

        # Global prompts section (top)
        global_frame = QFrame()
        global_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
            }}
        """)
        global_layout = QVBoxLayout(global_frame)
        global_layout.setContentsMargins(8, 8, 8, 8)
        global_layout.setSpacing(4)

        global_title = QLabel("Global Prompts")
        global_title.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(16)}px;
                font-weight: bold;
                color: {DARK_COLORS['accent_blue']};
            }}
        """)
        global_layout.addWidget(global_title)

        # 3x2 grid for global prompts
        prompts_grid = QGridLayout()
        prompts_grid.setSpacing(get_scaled_size(6))

        # Labels
        for i, label_text in enumerate(["Prefix:", "Postfix:", "Negative:"]):
            label = QLabel(label_text)
            label.setStyleSheet(f"""
                QLabel {{
                    font-size: {get_scaled_font_size(15)}px;
                    font-weight: bold;
                    color: {DARK_COLORS['text_secondary']};
                }}
            """)
            prompts_grid.addWidget(label, 0, i)

        # Text edits (read-only)
        text_style = f"""
            QTextEdit {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 3px;
                font-size: {get_scaled_font_size(15)}px;
            }}
        """

        self.prefix_preview = QTextEdit()
        self.prefix_preview.setReadOnly(True)
        self.prefix_preview.setMaximumHeight(get_scaled_size(60))
        self.prefix_preview.setStyleSheet(text_style)
        prompts_grid.addWidget(self.prefix_preview, 1, 0)

        self.postfix_preview = QTextEdit()
        self.postfix_preview.setReadOnly(True)
        self.postfix_preview.setMaximumHeight(get_scaled_size(60))
        self.postfix_preview.setStyleSheet(text_style)
        prompts_grid.addWidget(self.postfix_preview, 1, 1)

        self.negative_preview = QTextEdit()
        self.negative_preview.setReadOnly(True)
        self.negative_preview.setMaximumHeight(get_scaled_size(60))
        self.negative_preview.setStyleSheet(text_style)
        prompts_grid.addWidget(self.negative_preview, 1, 2)

        global_layout.addLayout(prompts_grid)
        layout.addWidget(global_frame)

        # Frame details section (bottom, scrollable)
        details_label = QLabel("Frame Details")
        details_label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(16)}px;
                font-weight: bold;
                color: {DARK_COLORS['accent_blue']};
            }}
        """)
        layout.addWidget(details_label)

        details_scroll = QScrollArea()
        details_scroll.setWidgetResizable(True)
        details_scroll.setStyleSheet(f"""
            QScrollArea {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
            }}
        """)

        self.details_container = QWidget()
        self.details_layout = QVBoxLayout(self.details_container)
        self.details_layout.setContentsMargins(8, 8, 8, 8)
        self.details_layout.setSpacing(8)
        self.details_layout.addStretch()

        details_scroll.setWidget(self.details_container)
        layout.addWidget(details_scroll, 1)

        return panel

    def _create_thumbnails_panel(self) -> QWidget:
        """Create right panel with thumbnail grid"""
        panel = QWidget()
        panel.setStyleSheet(f"""
            QWidget {{
                background-color: {DARK_COLORS['bg_secondary']};
                border-radius: 4px;
            }}
        """)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(
            get_scaled_size(8), get_scaled_size(8),
            get_scaled_size(8), get_scaled_size(8)
        )
        layout.setSpacing(get_scaled_size(4))

        # Header
        thumb_label = QLabel("Thumbnails")
        thumb_label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(16)}px;
                font-weight: bold;
                color: {DARK_COLORS['accent_blue']};
            }}
        """)
        layout.addWidget(thumb_label)

        # Scrollable thumbnail grid
        thumb_scroll = QScrollArea()
        thumb_scroll.setWidgetResizable(True)
        thumb_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        thumb_scroll.setStyleSheet(f"""
            QScrollArea {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
            }}
        """)

        self.thumbnails_container = QWidget()
        self.thumbnails_grid = QGridLayout(self.thumbnails_container)
        self.thumbnails_grid.setContentsMargins(8, 8, 8, 8)
        self.thumbnails_grid.setSpacing(get_scaled_size(8))

        thumb_scroll.setWidget(self.thumbnails_container)
        layout.addWidget(thumb_scroll, 1)

        return panel

    def _load_tree(self):
        """Load TreeWidget with folder/file structure"""
        self.tree_widget.clear()

        # Root item
        root_item = QTreeWidgetItem(self.tree_widget)
        root_item.setText(0, "📦 Studio Presets")
        root_item.setExpanded(True)
        root_item.setData(0, Qt.ItemDataRole.UserRole, str(self.PRESETS_BASE_DIR))

        # Populate tree
        self._populate_tree_item(root_item, self.PRESETS_BASE_DIR)

    def _populate_tree_item(self, parent_item: QTreeWidgetItem, path: Path):
        """Recursively populate tree items"""
        try:
            for item_path in sorted(path.iterdir()):
                if item_path.name.startswith('.'):
                    continue

                tree_item = QTreeWidgetItem(parent_item)
                tree_item.setData(0, Qt.ItemDataRole.UserRole, str(item_path))

                if item_path.is_dir():
                    tree_item.setText(0, f"📁 {item_path.name}")
                    self._populate_tree_item(tree_item, item_path)
                elif item_path.suffix.lower() == '.json':
                    # Show without .json extension
                    tree_item.setText(0, f"📄 {item_path.stem}")

        except Exception as e:
            print(f"Tree load error: {e}")

    def _on_tree_item_clicked(self, item: QTreeWidgetItem, column: int):
        """Handle tree item click"""
        path_str = item.data(0, Qt.ItemDataRole.UserRole)
        if not path_str:
            return

        path = Path(path_str)

        # Only load JSON files
        if path.is_file() and path.suffix.lower() == '.json':
            self._load_preset_preview(path)
            self.selected_preset_path = path
            self._set_load_buttons_enabled(True)
        else:
            self.selected_preset_path = None
            self._set_load_buttons_enabled(False)
            self._clear_preview()

    def _load_preset_preview(self, path: Path):
        """Load preset and show preview"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                self.preset_data = json.load(f)

            self._update_global_prompts_preview()
            self._update_frame_details_preview()
            self._update_thumbnails_preview()

        except Exception as e:
            show_warning(self, "Error", f"Failed to load preset:\n{str(e)}")
            self._clear_preview()

    def _update_global_prompts_preview(self):
        """Update global prompts preview"""
        global_prompts = self.preset_data.get('global_prompts', {})

        self.prefix_preview.setText(global_prompts.get('prefix_prompt', ''))
        self.postfix_preview.setText(global_prompts.get('postfix_prompt', ''))
        self.negative_preview.setText(global_prompts.get('negative_prompt', ''))

    def _update_frame_details_preview(self):
        """Update frame details preview"""
        # Clear existing
        while self.details_layout.count() > 1:
            item = self.details_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        frames = self.preset_data.get('frames', [])

        for frame in frames:
            index = frame.get('index', 0)
            prompt_data = frame.get('prompt_data', {})

            frame_widget = self._create_frame_detail_widget(index, prompt_data)
            self.details_layout.insertWidget(self.details_layout.count() - 1, frame_widget)

    def _create_frame_detail_widget(self, index: int, prompt_data: Dict) -> QFrame:
        """Create a frame detail widget"""
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
            }}
        """)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)

        # Frame header
        header = QLabel(f"[{index + 1}]")
        header.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(16)}px;
                font-weight: bold;
                color: {DARK_COLORS['accent_blue']};
            }}
        """)
        layout.addWidget(header)

        detail_style = f"""
            QLabel {{
                font-size: {get_scaled_font_size(15)}px;
                color: {DARK_COLORS['text_primary']};
            }}
        """

        # Main prompt
        prompt = prompt_data.get('prompt', '')
        if prompt:
            prompt_display = prompt[:80] + "..." if len(prompt) > 80 else prompt
            prompt_label = QLabel(f"Prompt: {prompt_display}")
            prompt_label.setStyleSheet(detail_style)
            prompt_label.setWordWrap(True)
            layout.addWidget(prompt_label)

        # Additional negative
        neg = prompt_data.get('negative_prompt', '')
        if neg:
            neg_display = neg[:50] + "..." if len(neg) > 50 else neg
            neg_label = QLabel(f"Neg: {neg_display}")
            neg_label.setStyleSheet(f"""
                QLabel {{
                    font-size: {get_scaled_font_size(15)}px;
                    color: {DARK_COLORS['text_secondary']};
                }}
            """)
            layout.addWidget(neg_label)

        # Resolution
        resolution = prompt_data.get('resolution', '1024 x 1024')
        res_label = QLabel(f"Resolution: {resolution}")
        res_label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(15)}px;
                color: {DARK_COLORS['text_secondary']};
            }}
        """)
        layout.addWidget(res_label)

        return frame

    def _update_thumbnails_preview(self):
        """Update thumbnails grid"""
        # Clear existing
        while self.thumbnails_grid.count():
            item = self.thumbnails_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        frames = self.preset_data.get('frames', [])

        row, col = 0, 0
        for frame in frames:
            index = frame.get('index', 0)
            thumbnail_b64 = frame.get('thumbnail', '')

            thumb_widget = self._create_thumbnail_widget(index, thumbnail_b64)
            self.thumbnails_grid.addWidget(thumb_widget, row, col)

            col += 1
            if col >= 2:  # 2 columns
                col = 0
                row += 1

    def _create_thumbnail_widget(self, index: int, thumbnail_b64: str) -> QFrame:
        """Create a thumbnail widget with label"""
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
            }}
        """)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        # Index label
        index_label = QLabel(f"[{index + 1}]")
        index_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        index_label.setStyleSheet(f"""
            QLabel {{
                font-size: {get_scaled_font_size(16)}px;
                font-weight: bold;
                color: {DARK_COLORS['accent_blue']};
            }}
        """)
        layout.addWidget(index_label)

        # Thumbnail image
        img_label = QLabel()
        img_label.setFixedSize(
            get_scaled_size(self.THUMBNAIL_DISPLAY_SIZE),
            get_scaled_size(self.THUMBNAIL_DISPLAY_SIZE)
        )
        img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img_label.setStyleSheet(f"""
            QLabel {{
                background-color: #000000;
                border: 1px solid {DARK_COLORS['border']};
            }}
        """)

        if thumbnail_b64:
            try:
                img_data = base64.b64decode(thumbnail_b64)
                pixmap = QPixmap()
                pixmap.loadFromData(img_data)
                scaled = pixmap.scaled(
                    get_scaled_size(self.THUMBNAIL_DISPLAY_SIZE),
                    get_scaled_size(self.THUMBNAIL_DISPLAY_SIZE),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                img_label.setPixmap(scaled)
            except Exception as e:
                img_label.setText("Error")
                print(f"Thumbnail decode error: {e}")
        else:
            img_label.setText("No Image")
            img_label.setStyleSheet(f"""
                QLabel {{
                    background-color: #000000;
                    color: {DARK_COLORS['text_disabled']};
                    font-size: {get_scaled_font_size(15)}px;
                }}
            """)

        layout.addWidget(img_label)
        return frame

    def _clear_preview(self):
        """Clear all preview panels"""
        self.preset_data = None

        self.prefix_preview.clear()
        self.postfix_preview.clear()
        self.negative_preview.clear()

        # Clear frame details
        while self.details_layout.count() > 1:
            item = self.details_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Clear thumbnails
        while self.thumbnails_grid.count():
            item = self.thumbnails_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _show_tree_context_menu(self, position):
        """Show context menu for tree items"""
        item = self.tree_widget.itemAt(position)
        if not item:
            return

        path_str = item.data(0, Qt.ItemDataRole.UserRole)
        if not path_str:
            return

        path = Path(path_str)
        menu = QMenu(self.tree_widget)

        # Delete action
        if path.is_file():
            delete_action = QAction("🗑️ Delete", self.tree_widget)
            delete_action.triggered.connect(lambda: self._delete_preset(path, item))
            menu.addAction(delete_action)

        # Open folder action
        if path.is_dir() or path.is_file():
            open_folder_action = QAction("📂 Open Folder", self.tree_widget)
            folder_path = path.parent if path.is_file() else path
            open_folder_action.triggered.connect(
                lambda: os.startfile(str(folder_path)) if os.name == 'nt' else None
            )
            menu.addAction(open_folder_action)

        if menu.actions():
            global_pos = self.tree_widget.mapToGlobal(position)
            menu.exec(global_pos)

    def _delete_preset(self, path: Path, tree_item: QTreeWidgetItem):
        """Delete a preset file"""
        if not show_question(self, "Delete Preset", f"Delete '{path.stem}'?"):
            return

        try:
            path.unlink()
            parent = tree_item.parent()
            if parent:
                parent.removeChild(tree_item)
            else:
                index = self.tree_widget.indexOfTopLevelItem(tree_item)
                if index >= 0:
                    self.tree_widget.takeTopLevelItem(index)

            self._clear_preview()
            self.selected_preset_path = None
            self._set_load_buttons_enabled(False)

        except Exception as e:
            show_error(self, "Error", f"Failed to delete:\n{str(e)}")

    def _set_load_buttons_enabled(self, enabled: bool):
        """Enable or disable all load buttons"""
        self.load_btn.setEnabled(enabled)
        self.load_events_btn.setEnabled(enabled)
        self.load_global_btn.setEnabled(enabled)
        self.get_sequence_btn.setEnabled(enabled)

    def _on_get_sequence(self):
        """Generate and display :sequence text from preset"""
        if not self.preset_data:
            return

        from tabs.studio.sequence_generator import generate_sequence_text_from_preset
        from tabs.studio.dialogs.sequence_text_dialog import SequenceTextDialog

        # Generate sequence text
        sequence_text = generate_sequence_text_from_preset(self.preset_data)

        # Show dialog
        dialog = SequenceTextDialog(sequence_text, self)
        dialog.exec()

    def _on_load_events_only(self):
        """Load only frame events (without global prompts)"""
        if not self.preset_data:
            return
        self.load_mode = self.LOAD_EVENTS_ONLY
        self.accept()

    def _on_load_global_only(self):
        """Load only global prompts (prefix/postfix/negative)"""
        if not self.preset_data:
            return
        self.load_mode = self.LOAD_GLOBAL_ONLY
        self.accept()

    def _on_load(self):
        """Load all preset data"""
        if not self.preset_data:
            return
        self.load_mode = self.LOAD_ALL
        self.accept()

    def get_preset_data(self) -> Optional[Dict]:
        """Get loaded preset data after dialog accepted"""
        return self.preset_data

    def get_load_mode(self) -> str:
        """Get the load mode selected by user"""
        return self.load_mode
