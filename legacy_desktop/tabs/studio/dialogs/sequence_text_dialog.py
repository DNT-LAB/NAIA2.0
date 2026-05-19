"""
SequenceTextDialog - Dialog for displaying generated sequence text
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QPushButton, QApplication
)
from PyQt6.QtCore import Qt

from legacy_desktop.ui.theme import DARK_COLORS, get_dynamic_styles
from legacy_desktop.ui.scaling_manager import get_scaled_font_size, get_scaled_size


class SequenceTextDialog(QDialog):
    """Dialog for displaying generated sequence text from frame events"""

    def __init__(self, sequence_text: str, parent=None):
        super().__init__(parent)
        self.sequence_text = sequence_text

        self.setWindowTitle("Generated :Sequence Text")
        self.setMinimumSize(get_scaled_size(700), get_scaled_size(400))
        self.resize(get_scaled_size(900), get_scaled_size(500))
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
        title_label = QLabel("Generated :Sequence Text")
        title_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['accent_blue']};
                font-size: {get_scaled_font_size(20)}px;
                font-weight: bold;
            }}
        """)
        layout.addWidget(title_label)

        # Text display
        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(self.sequence_text)
        self.text_edit.setReadOnly(True)
        self.text_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 8px;
                font-size: {get_scaled_font_size(14)}px;
                font-family: Consolas, "Courier New", monospace;
            }}
        """)
        layout.addWidget(self.text_edit, 1)

        # Instruction label
        instruction_label = QLabel(
            "텍스트를 복사하여 메인/선행고정 프롬프트, 와일드카드 등에 붙여넣기 하세요."
        )
        instruction_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(14)}px;
                padding: 4px 0;
            }}
        """)
        instruction_label.setWordWrap(True)
        layout.addWidget(instruction_label)

        # Button row
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        # Copy button
        copy_btn = QPushButton("Copy to Clipboard")
        copy_btn.setStyleSheet(dynamic_styles.get('secondary_button', ''))
        copy_btn.clicked.connect(self._on_copy_clicked)
        button_layout.addWidget(copy_btn)

        # Copy without resolution button
        copy_no_res_btn = QPushButton("Copy without :resolution")
        copy_no_res_btn.setStyleSheet(dynamic_styles.get('secondary_button', ''))
        copy_no_res_btn.clicked.connect(self._on_copy_without_resolution_clicked)
        button_layout.addWidget(copy_no_res_btn)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(dynamic_styles.get('primary_button', ''))
        close_btn.clicked.connect(self.accept)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

    def _on_copy_clicked(self):
        """Copy text to clipboard and close dialog"""
        clipboard = QApplication.clipboard()
        clipboard.setText(self.sequence_text)
        self.accept()

    def _on_copy_without_resolution_clicked(self):
        """Copy text to clipboard excluding resolution tags and close dialog"""
        # Split by ', ' and filter out resolution tags
        parts = self.sequence_text.split(', ')
        filtered_parts = [p for p in parts if not p.startswith('resolution:')]
        filtered_text = ', '.join(filtered_parts)

        clipboard = QApplication.clipboard()
        clipboard.setText(filtered_text)
        self.accept()
