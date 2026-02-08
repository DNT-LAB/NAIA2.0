"""
WildcardNavPanel - Navigation panel for wildcard mode with dynamic axis swapping
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
)
from PyQt6.QtCore import Qt, pyqtSignal
from ui.theme import DARK_COLORS
from ui.scaling_manager import get_scaled_font_size, get_scaled_size


class WildcardNavPanel(QWidget):
    """Navigation panel for wildcard mode with swappable axes"""

    # Signals
    page_changed = pyqtSignal(int)  # delta (relative page movement)
    axis_swapped = pyqtSignal()  # User wants to swap page/frame axes
    exit_mode_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._create_ui()

    def _create_ui(self):
        """Create navigation panel UI"""
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: none;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            get_scaled_size(12), get_scaled_size(8),
            get_scaled_size(12), get_scaled_size(8)
        )
        layout.setSpacing(get_scaled_size(10))

        # Top row: Title and Exit button
        top_row = QHBoxLayout()
        top_row.setSpacing(get_scaled_size(10))

        # Title
        title_label = QLabel("🌐 Wildcard Mode")
        title_label.setStyleSheet(f"""
            QLabel {{
                color: #FFE066;
                font-size: {get_scaled_font_size(16)}px;
                font-weight: bold;
                border: none;
            }}
        """)
        top_row.addWidget(title_label)

        top_row.addStretch()

        # Exit button
        exit_btn = QPushButton("Exit Mode")
        exit_btn.setFixedHeight(get_scaled_size(28))
        exit_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #703030;
                color: #FFFFFF;
                border: none;
                border-radius: 3px;
                padding: 4px 12px;
                font-size: {get_scaled_font_size(13)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #904040;
            }}
        """)
        exit_btn.clicked.connect(self.exit_mode_requested.emit)
        top_row.addWidget(exit_btn)

        layout.addLayout(top_row)

        # Row 1: Page Axis control
        page_row = QHBoxLayout()
        page_row.setSpacing(get_scaled_size(10))

        # "Page Axis:" label
        page_label = QLabel("Page Axis:")
        page_label.setStyleSheet(f"""
            QLabel {{
                color: #FFFFFF;
                font-size: {get_scaled_font_size(13)}px;
                font-weight: bold;
                border: none;
            }}
        """)
        page_row.addWidget(page_label)

        # Swap button: [WC1 ↔ WC2]
        self.swap_btn = QPushButton("[WC1 ↔ WC2]")
        self.swap_btn.setFixedHeight(get_scaled_size(28))
        self.swap_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: #FFE066;
                border: none;
                border-radius: 3px;
                padding: 4px 12px;
                font-size: {get_scaled_font_size(13)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
        """)
        self.swap_btn.setToolTip("Click to swap Page and Frame axes")
        self.swap_btn.clicked.connect(self.axis_swapped.emit)
        page_row.addWidget(self.swap_btn)

        # Previous button
        self.prev_btn = QPushButton("<")
        self.prev_btn.setFixedSize(get_scaled_size(28), get_scaled_size(28))
        self.prev_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: #FFFFFF;
                border: none;
                border-radius: 3px;
                font-size: {get_scaled_font_size(14)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
            QPushButton:disabled {{
                color: {DARK_COLORS['text_disabled']};
            }}
        """)
        self.prev_btn.clicked.connect(lambda: self.page_changed.emit(-1))
        page_row.addWidget(self.prev_btn)

        # Page range label
        self.page_range_label = QLabel("[1 of 9]")
        self.page_range_label.setStyleSheet(f"""
            QLabel {{
                color: #FFFFFF;
                font-size: {get_scaled_font_size(13)}px;
                min-width: {get_scaled_size(80)}px;
                border: none;
            }}
        """)
        self.page_range_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        page_row.addWidget(self.page_range_label)

        # Next button
        self.next_btn = QPushButton(">")
        self.next_btn.setFixedSize(get_scaled_size(28), get_scaled_size(28))
        self.next_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: #FFFFFF;
                border: none;
                border-radius: 3px;
                font-size: {get_scaled_font_size(14)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
            QPushButton:disabled {{
                color: {DARK_COLORS['text_disabled']};
            }}
        """)
        self.next_btn.clicked.connect(lambda: self.page_changed.emit(1))
        page_row.addWidget(self.next_btn)

        # Current item display
        current_label = QLabel("Current:")
        current_label.setStyleSheet(f"""
            QLabel {{
                color: #FFFFFF;
                font-size: {get_scaled_font_size(13)}px;
                border: none;
            }}
        """)
        page_row.addWidget(current_label)

        self.current_item_label = QLabel('"1"')
        self.current_item_label.setStyleSheet(f"""
            QLabel {{
                color: #FFE066;
                font-size: {get_scaled_font_size(14)}px;
                font-weight: bold;
                border: none;
            }}
        """)
        page_row.addWidget(self.current_item_label)

        page_row.addStretch()
        layout.addLayout(page_row)

        # Row 2: Frame Axis info
        frame_row = QHBoxLayout()
        frame_row.setSpacing(get_scaled_size(10))

        # "Frame Axis:" label
        frame_label = QLabel("Frame Axis:")
        frame_label.setStyleSheet(f"""
            QLabel {{
                color: #FFFFFF;
                font-size: {get_scaled_font_size(13)}px;
                font-weight: bold;
                border: none;
            }}
        """)
        frame_row.addWidget(frame_label)

        # Frame axis info
        self.frame_info_label = QLabel("WC2 (9 items: A, B, C, D, E, F, G, H, I)")
        self.frame_info_label.setStyleSheet(f"""
            QLabel {{
                color: #CCCCCC;
                font-size: {get_scaled_font_size(13)}px;
                border: none;
            }}
        """)
        frame_row.addWidget(self.frame_info_label)

        frame_row.addStretch()
        layout.addLayout(frame_row)

    def update_info(
        self,
        page_axis_name: str,
        frame_axis_name: str,
        current_page: int,
        total_pages: int,
        current_item: str,
        frame_items: list
    ):
        """Update navigation panel information

        Args:
            page_axis_name: Name of page axis wildcard (e.g., "WC1")
            frame_axis_name: Name of frame axis wildcard (e.g., "WC2")
            current_page: Current page index (1-indexed)
            total_pages: Total number of pages
            current_item: Current page's item value (e.g., "1" or "A")
            frame_items: List of frame axis items
        """
        # Update swap button text
        self.swap_btn.setText(f"[{page_axis_name} ↔ {frame_axis_name}]")

        # Update page range
        self.page_range_label.setText(f"[{current_page} of {total_pages}]")

        # Update current item
        self.current_item_label.setText(f'"{current_item}"')

        # Update frame info
        frame_items_str = ", ".join(str(item) for item in frame_items[:10])
        if len(frame_items) > 10:
            frame_items_str += "..."
        self.frame_info_label.setText(
            f"{frame_axis_name} ({len(frame_items)} items: {frame_items_str})"
        )

        # Update navigation buttons
        self.prev_btn.setEnabled(current_page > 1)
        self.next_btn.setEnabled(current_page < total_pages)
