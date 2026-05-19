"""
DetachedTextEditDialog - Detachable TextEdit window for Studio Tab
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QLabel
)
from PyQt6.QtCore import Qt, pyqtSignal
from ui.theme import DARK_COLORS, get_dynamic_styles
from ui.scaling_manager import get_scaled_font_size, get_scaled_size


class DetachedTextEditDialog(QDialog):
    """Detached window for editing text in a larger view"""

    # Signals
    text_updated = pyqtSignal(str)  # Emitted when text changes
    dialog_closed = pyqtSignal()     # Emitted when dialog closes
    apply_and_close = pyqtSignal(str)  # Emitted when Apply is clicked (text, then close)

    def __init__(self, initial_text: str, title: str, section_type: str, parent=None):
        super().__init__(parent)
        self.section_type = section_type
        self.initial_text = initial_text

        self.setWindowTitle(f"Studio - {title}")
        self.setMinimumSize(get_scaled_size(500), get_scaled_size(300))
        self.resize(get_scaled_size(600), get_scaled_size(400))

        # Window flags for independent window
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowMinimizeButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowTitleHint
        )

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
        layout.setSpacing(get_scaled_size(8))
        layout.setContentsMargins(
            get_scaled_size(12), get_scaled_size(12),
            get_scaled_size(12), get_scaled_size(12)
        )

        dynamic_styles = get_dynamic_styles()

        # Header with info
        header_label = QLabel(f"Edit in larger window. Changes sync on close.")
        header_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(15)}px;
            }}
        """)
        layout.addWidget(header_label)

        # TextEdit
        self.text_edit = QTextEdit()
        self.text_edit.setText(self.initial_text)
        self.text_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 8px;
                font-size: {get_scaled_font_size(15)}px;
            }}
        """)
        layout.addWidget(self.text_edit, 1)

        # Button row
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        # Apply button
        apply_btn = QPushButton("Apply")
        apply_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['accent_blue']};
                color: {DARK_COLORS['text_primary']};
                border: none;
                border-radius: 4px;
                padding: 6px 16px;
                font-size: {get_scaled_font_size(14)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['accent_blue_hover']};
            }}
        """)
        apply_btn.clicked.connect(self._on_apply)
        button_layout.addWidget(apply_btn)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(dynamic_styles.get('secondary_button', ''))
        close_btn.clicked.connect(self.close)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

    def _on_apply(self):
        """Apply changes and close"""
        self.apply_and_close.emit(self.text_edit.toPlainText())
        self.close()

    def closeEvent(self, event):
        """Handle close - emit close signal only (no auto-sync on X button)"""
        self.dialog_closed.emit()
        event.accept()

    def get_text(self) -> str:
        """Get current text"""
        return self.text_edit.toPlainText()
