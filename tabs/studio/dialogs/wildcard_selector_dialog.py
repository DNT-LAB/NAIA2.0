"""
WildcardSelectorDialog - Dialog for selecting wildcards as 2D navigation axes
Supports block selection for 10+ items and instant wildcard input
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QWidget, QFrame, QRadioButton, QScrollArea, QComboBox,
    QTextEdit, QCheckBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from ui.theme import DARK_COLORS
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from typing import List, Optional, Tuple


class WildcardSelectorDialog(QDialog):
    """Dialog to select 2 wildcards as X/Y axes for 2D navigation

    Features:
    - Maximum 9 items per wildcard
    - Block selection for 10+ item wildcards
    - Instant wildcard input (max 9 lines, not saved)
    - X-axis fixed, Y-axis up to 9 pages (max 81 images)
    """

    # Signals
    mode_1d_requested = pyqtSignal()  # User wants 1D sequential mode
    mode_2d_requested = pyqtSignal(str, str, list, list)  # (x_name, y_name, x_items, y_items)

    def __init__(self, wildcards: List[dict], total_combinations: int, parent=None):
        """
        Args:
            wildcards: List of WildcardInfo-like dicts: [{'name': str, 'item_count': int}, ...]
            total_combinations: Total number of combinations
            parent: Parent widget
        """
        super().__init__(parent)
        self.wildcards = wildcards
        self.total_combinations = total_combinations
        self.selected_x = None  # (name, items_list)
        self.selected_y = None  # (name, items_list)

        self.setWindowTitle("Select Wildcards for 2D Navigation")
        self.setModal(True)
        self.resize(get_scaled_size(700), get_scaled_size(600))

        # Dark background
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
            get_scaled_size(20), get_scaled_size(20),
            get_scaled_size(20), get_scaled_size(20)
        )
        layout.setSpacing(get_scaled_size(15))

        # Title
        title_label = QLabel("🎲 Select Wildcards (Max 9 items each)")
        title_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(18)}px;
                font-weight: bold;
            }}
        """)
        layout.addWidget(title_label)

        # Info text
        info_text = QLabel(
            "• Maximum 81 images (9×9)\n"
            "• X-Axis = Columns (fixed page)\n"
            "• Y-Axis = Rows (up to 9 pages)"
        )
        info_text.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(13)}px;
            }}
        """)
        layout.addWidget(info_text)

        # Add instant wildcard button
        add_instant_btn = QPushButton("+ Add Instant Wildcard (max 9 lines)")
        add_instant_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 6px 12px;
                font-size: {get_scaled_font_size(13)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
        """)
        add_instant_btn.clicked.connect(self._on_add_instant_wildcard)
        layout.addWidget(add_instant_btn)

        # Wildcard list (scrollable)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet(f"""
            QScrollArea {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 5px;
            }}
        """)

        self.list_widget = QWidget()
        self.list_layout = QVBoxLayout(self.list_widget)
        self.list_layout.setContentsMargins(
            get_scaled_size(10), get_scaled_size(10),
            get_scaled_size(10), get_scaled_size(10)
        )
        self.list_layout.setSpacing(get_scaled_size(8))

        # Create wildcard rows
        self.wildcard_rows = []
        for i, wc_info in enumerate(self.wildcards[:20]):  # Limit to 20 for safety
            row_frame = self._create_wildcard_row(i, wc_info)
            self.list_layout.addWidget(row_frame)
            self.wildcard_rows.append(row_frame)

        self.list_layout.addStretch()
        scroll_area.setWidget(self.list_widget)
        layout.addWidget(scroll_area, 1)  # Stretch

        # Preview section
        preview_frame = self._create_preview_section()
        layout.addWidget(preview_frame)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        # Cancel button
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedWidth(get_scaled_size(100))
        cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 8px 16px;
                font-size: {get_scaled_font_size(14)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
        """)
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        # 1D Mode button
        mode_1d_btn = QPushButton("Use 1D Mode")
        mode_1d_btn.setFixedWidth(get_scaled_size(120))
        mode_1d_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 8px 16px;
                font-size: {get_scaled_font_size(14)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
        """)
        mode_1d_btn.setToolTip("Use sequential 1D wildcard expansion instead")
        mode_1d_btn.clicked.connect(self._on_1d_mode_clicked)
        button_layout.addWidget(mode_1d_btn)

        # Enable 2D Mode button
        self.mode_2d_btn = QPushButton("Enable 2D Mode")
        self.mode_2d_btn.setFixedWidth(get_scaled_size(150))
        self.mode_2d_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['accent_blue']};
                color: {DARK_COLORS['text_primary']};
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-size: {get_scaled_font_size(14)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['accent_blue_hover']};
            }}
            QPushButton:disabled {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_disabled']};
            }}
        """)
        self.mode_2d_btn.setEnabled(False)  # Disabled until 2 wildcards selected
        self.mode_2d_btn.clicked.connect(self._on_2d_mode_clicked)
        button_layout.addWidget(self.mode_2d_btn)

        layout.addLayout(button_layout)

    def _create_wildcard_row(self, index: int, wc_info: dict) -> QFrame:
        """Create a single wildcard row with block selection and X/Y axis radios

        Args:
            index: Row index
            wc_info: Dict with 'name' and 'item_count'
        """
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
            }}
        """)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(
            get_scaled_size(10), get_scaled_size(8),
            get_scaled_size(10), get_scaled_size(8)
        )
        layout.setSpacing(get_scaled_size(6))

        # Top row: Name and item count
        top_layout = QHBoxLayout()
        top_layout.setSpacing(get_scaled_size(10))

        name_label = QLabel(f"{wc_info['name']} ({wc_info['item_count']} items)")
        name_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(14)}px;
                font-weight: bold;
            }}
        """)
        top_layout.addWidget(name_label, 1)

        layout.addLayout(top_layout)

        # Bottom row: Block selector (if needed) + X/Y radios
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(get_scaled_size(10))

        # Block selector if >9 items
        if wc_info['item_count'] > 9:
            block_label = QLabel("Block:")
            block_label.setStyleSheet(f"""
                QLabel {{
                    color: {DARK_COLORS['text_secondary']};
                    font-size: {get_scaled_font_size(13)}px;
                }}
            """)
            bottom_layout.addWidget(block_label)

            block_combo = QComboBox()
            block_count = (wc_info['item_count'] + 8) // 9
            for i in range(block_count):
                start = i * 9 + 1
                end = min((i + 1) * 9, wc_info['item_count'])
                block_combo.addItem(f"{start}-{end}", (start - 1, end))

            block_combo.setFixedWidth(get_scaled_size(100))
            block_combo.setStyleSheet(f"""
                QComboBox {{
                    background-color: {DARK_COLORS['bg_secondary']};
                    color: {DARK_COLORS['text_primary']};
                    border: 1px solid {DARK_COLORS['border']};
                    border-radius: 3px;
                    padding: 2px 4px;
                    font-size: {get_scaled_font_size(12)}px;
                }}
                QComboBox QAbstractItemView {{
                    background-color: {DARK_COLORS['bg_secondary']};
                    color: {DARK_COLORS['text_primary']};
                    selection-background-color: {DARK_COLORS['accent_blue']};
                }}
            """)
            bottom_layout.addWidget(block_combo)
            frame.block_combo = block_combo
        else:
            frame.block_combo = None

        bottom_layout.addStretch()

        # X-Axis radio button
        x_radio = QRadioButton("X-Axis")
        x_radio.setStyleSheet(f"""
            QRadioButton {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(13)}px;
            }}
            QRadioButton::indicator {{
                width: {get_scaled_size(16)}px;
                height: {get_scaled_size(16)}px;
            }}
        """)
        x_radio.toggled.connect(lambda checked: self._on_x_selected(frame) if checked else None)
        bottom_layout.addWidget(x_radio)

        # Y-Axis radio button
        y_radio = QRadioButton("Y-Axis")
        y_radio.setStyleSheet(f"""
            QRadioButton {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(13)}px;
            }}
            QRadioButton::indicator {{
                width: {get_scaled_size(16)}px;
                height: {get_scaled_size(16)}px;
            }}
        """)
        y_radio.toggled.connect(lambda checked: self._on_y_selected(frame) if checked else None)
        bottom_layout.addWidget(y_radio)

        layout.addLayout(bottom_layout)

        # Store references
        frame.x_radio = x_radio
        frame.y_radio = y_radio
        frame.wildcard_info = wc_info
        frame.is_instant = False

        return frame

    def _create_preview_section(self) -> QFrame:
        """Create preview section showing selected wildcards"""
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 5px;
            }}
        """)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(
            get_scaled_size(15), get_scaled_size(15),
            get_scaled_size(15), get_scaled_size(15)
        )
        layout.setSpacing(get_scaled_size(8))

        # Title
        title_label = QLabel("Preview:")
        title_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(14)}px;
                font-weight: bold;
            }}
        """)
        layout.addWidget(title_label)

        # X-Axis preview
        self.x_preview_label = QLabel("X-Axis: (none)")
        self.x_preview_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(13)}px;
            }}
        """)
        layout.addWidget(self.x_preview_label)

        # Y-Axis preview
        self.y_preview_label = QLabel("Y-Axis: (none)")
        self.y_preview_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(13)}px;
            }}
        """)
        layout.addWidget(self.y_preview_label)

        # Total combinations
        self.combinations_label = QLabel(f"Total combinations: (select 2)")
        self.combinations_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(13)}px;
            }}
        """)
        layout.addWidget(self.combinations_label)

        # Pages info
        self.pages_label = QLabel("Y-axis pages: (select 2)")
        self.pages_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(13)}px;
            }}
        """)
        layout.addWidget(self.pages_label)

        return frame

    def _on_x_selected(self, frame):
        """Handle X-axis wildcard selection"""
        # Uncheck Y radio for this wildcard
        frame.y_radio.setChecked(False)

        # Get selected items
        name, items = self._get_frame_selection(frame)
        if len(items) > 9:
            self._show_warning(f"X-Axis can have maximum 9 items. Got {len(items)}.")
            frame.x_radio.setChecked(False)
            return

        self.selected_x = (name, items)
        self._update_preview()

    def _on_y_selected(self, frame):
        """Handle Y-axis wildcard selection"""
        # Uncheck X radio for this wildcard
        frame.x_radio.setChecked(False)

        # Get selected items
        name, items = self._get_frame_selection(frame)
        if len(items) > 9:
            self._show_warning(f"Y-Axis can have maximum 9 items. Got {len(items)}.")
            frame.y_radio.setChecked(False)
            return

        self.selected_y = (name, items)
        self._update_preview()

    def _get_frame_selection(self, frame) -> Tuple[str, List[str]]:
        """Get selected wildcard name and items from frame

        Returns:
            (wildcard_name, items_list)
        """
        name = frame.wildcard_info['name']

        # If instant wildcard, items are stored directly
        if frame.is_instant:
            return (name, frame.instant_items)

        # If has block selector, get selected block
        if frame.block_combo:
            start_idx, end_idx = frame.block_combo.currentData()
            # We'll need to fetch items from wildcard file later
            # For now, return placeholder
            return (name, [f"{name}_{i}" for i in range(start_idx, end_idx)])

        # Normal wildcard (<= 9 items)
        return (name, [])  # Items will be fetched later

    def _update_preview(self):
        """Update preview labels and enable/disable 2D button"""
        # Update X preview
        if self.selected_x:
            name, items = self.selected_x
            self.x_preview_label.setText(f"X-Axis: {name} ({len(items) if items else '≤9'} items)")
            self.x_preview_label.setStyleSheet(f"""
                QLabel {{
                    color: {DARK_COLORS['text_primary']};
                    font-size: {get_scaled_font_size(13)}px;
                }}
            """)
        else:
            self.x_preview_label.setText("X-Axis: (none)")
            self.x_preview_label.setStyleSheet(f"""
                QLabel {{
                    color: {DARK_COLORS['text_secondary']};
                    font-size: {get_scaled_font_size(13)}px;
                }}
            """)

        # Update Y preview
        if self.selected_y:
            name, items = self.selected_y
            self.y_preview_label.setText(f"Y-Axis: {name} ({len(items) if items else '≤9'} items)")
            self.y_preview_label.setStyleSheet(f"""
                QLabel {{
                    color: {DARK_COLORS['text_primary']};
                    font-size: {get_scaled_font_size(13)}px;
                }}
            """)
        else:
            self.y_preview_label.setText("Y-Axis: (none)")
            self.y_preview_label.setStyleSheet(f"""
                QLabel {{
                    color: {DARK_COLORS['text_secondary']};
                    font-size: {get_scaled_font_size(13)}px;
                }}
            """)

        # Calculate totals if both selected
        if self.selected_x and self.selected_y:
            x_name, x_items = self.selected_x
            y_name, y_items = self.selected_y

            x_count = len(x_items) if x_items else 9
            y_count = len(y_items) if y_items else 9

            total = x_count * y_count
            y_pages = (y_count + 2) // 3  # Ceiling division for 3 per page

            self.combinations_label.setText(f"Total combinations: {total} (max 81)")
            self.pages_label.setText(f"Y-axis pages: {y_pages} (X-axis fixed)")
            self.mode_2d_btn.setEnabled(True)
        else:
            self.combinations_label.setText("Total combinations: (select 2)")
            self.pages_label.setText("Y-axis pages: (select 2)")
            self.mode_2d_btn.setEnabled(False)

    def _on_add_instant_wildcard(self):
        """Add instant wildcard input"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QPushButton, QLabel

        dialog = QDialog(self)
        dialog.setWindowTitle("Add Instant Wildcard")
        dialog.setModal(True)
        dialog.resize(get_scaled_size(400), get_scaled_size(300))
        dialog.setStyleSheet(f"background-color: {DARK_COLORS['bg_primary']};")

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(get_scaled_size(15), get_scaled_size(15), get_scaled_size(15), get_scaled_size(15))
        layout.setSpacing(get_scaled_size(10))

        label = QLabel("Enter up to 9 lines (one item per line):")
        label.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(13)}px;")
        layout.addWidget(label)

        text_edit = QTextEdit()
        text_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 8px;
                font-size: {get_scaled_font_size(13)}px;
            }}
        """)
        layout.addWidget(text_edit, 1)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dialog.reject)
        btn_layout.addWidget(cancel_btn)

        add_btn = QPushButton("Add")
        add_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['accent_blue']};
                color: {DARK_COLORS['text_primary']};
            }}
        """)
        add_btn.clicked.connect(dialog.accept)
        btn_layout.addWidget(add_btn)

        layout.addLayout(btn_layout)

        if dialog.exec():
            lines = [line.strip() for line in text_edit.toPlainText().split('\n') if line.strip()]
            if not lines:
                return
            if len(lines) > 9:
                self._show_warning("Maximum 9 lines allowed. Only first 9 will be used.")
                lines = lines[:9]

            # Create instant wildcard frame
            instant_name = f"Instant_{len([f for f in self.wildcard_rows if f.is_instant]) + 1}"
            instant_info = {'name': instant_name, 'item_count': len(lines)}

            frame = self._create_wildcard_row(len(self.wildcard_rows), instant_info)
            frame.is_instant = True
            frame.instant_items = lines

            # Insert before last stretch
            self.list_layout.insertWidget(len(self.wildcard_rows), frame)
            self.wildcard_rows.append(frame)

    def _show_warning(self, message: str):
        """Show warning message"""
        from PyQt6.QtWidgets import QMessageBox
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setText(message)
        msg.setWindowTitle("Warning")
        msg.setStyleSheet(f"""
            QMessageBox {{ background-color: {DARK_COLORS['bg_primary']}; }}
            QLabel {{ color: {DARK_COLORS['text_primary']}; }}
            QPushButton {{ color: {DARK_COLORS['text_primary']}; }}
        """)
        msg.exec()

    def _on_1d_mode_clicked(self):
        """Handle 1D mode button click"""
        self.mode_1d_requested.emit()
        self.accept()

    def _on_2d_mode_clicked(self):
        """Handle 2D mode button click"""
        if self.selected_x and self.selected_y:
            x_name, x_items = self.selected_x
            y_name, y_items = self.selected_y
            self.mode_2d_requested.emit(x_name, y_name, x_items, y_items)
            self.accept()

    def get_selected_wildcards(self) -> tuple:
        """Get selected wildcard data

        Returns:
            ((x_name, x_items), (y_name, y_items)) or (None, None)
        """
        return (self.selected_x, self.selected_y)
