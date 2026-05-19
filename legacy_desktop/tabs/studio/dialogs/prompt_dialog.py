"""
PromptSettingDialog - Dialog for editing frame prompt settings
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QLineEdit, QPushButton, QCheckBox, QFrame, QSpinBox
)
from PyQt6.QtCore import Qt
from legacy_desktop.ui.theme import DARK_COLORS, DARK_STYLES, get_dynamic_styles
from legacy_desktop.ui.scaling_manager import get_scaled_font_size, get_scaled_size


class PromptSettingDialog(QDialog):
    """Dialog for editing individual frame prompt settings"""

    def __init__(self, frame_index: int, prompt_data: dict = None, parent=None):
        super().__init__(parent)
        self.frame_index = frame_index
        self.prompt_data = prompt_data or {
            "prompt": "",
            "negative_prompt": "",
            "seed": -1,
            "enabled": True
        }
        self.result_data = None

        self.setWindowTitle(f"Prompt Settings - Frame #{frame_index + 1}")
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

        self._create_ui()
        self._load_data()

    def _create_ui(self):
        """Create dialog UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(get_scaled_size(12))
        layout.setContentsMargins(
            get_scaled_size(16), get_scaled_size(16),
            get_scaled_size(16), get_scaled_size(16)
        )

        dynamic_styles = get_dynamic_styles()

        # Frame indicator
        frame_label = QLabel(f"Frame #{self.frame_index + 1}")
        frame_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['accent_blue']};
                font-size: {get_scaled_font_size(18)}px;
                font-weight: bold;
            }}
        """)
        layout.addWidget(frame_label)

        # Enable checkbox
        self.enabled_checkbox = QCheckBox("Enable generation for this frame")
        self.enabled_checkbox.setStyleSheet(f"""
            QCheckBox {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(15)}px;
            }}
            QCheckBox::indicator {{
                width: {get_scaled_size(18)}px;
                height: {get_scaled_size(18)}px;
            }}
        """)
        layout.addWidget(self.enabled_checkbox)

        # Separator
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setStyleSheet(f"background-color: {DARK_COLORS['border']};")
        layout.addWidget(sep1)

        # Main Prompt section
        prompt_label = QLabel("Main Prompt:")
        prompt_label.setStyleSheet(dynamic_styles.get('label_style', ''))
        layout.addWidget(prompt_label)

        self.prompt_edit = QTextEdit()
        self.prompt_edit.setPlaceholderText("Main prompt for this frame (combined with Prefix + Postfix)...")
        self.prompt_edit.setMinimumHeight(get_scaled_size(100))
        self.prompt_edit.setStyleSheet(dynamic_styles.get('compact_textedit', ''))
        layout.addWidget(self.prompt_edit)

        # Additional Negative Prompt section
        neg_label = QLabel("Additional Negative Prompt:")
        neg_label.setStyleSheet(dynamic_styles.get('label_style', ''))
        layout.addWidget(neg_label)

        self.negative_edit = QTextEdit()
        self.negative_edit.setPlaceholderText("Additional negative prompt (combined with global Negative Prompt)...")
        self.negative_edit.setMinimumHeight(get_scaled_size(60))
        self.negative_edit.setStyleSheet(dynamic_styles.get('compact_textedit', ''))
        layout.addWidget(self.negative_edit)

        # Seed section (hidden - always use random seed)
        # Keep the widget for data compatibility but don't show it
        self.seed_spin = QSpinBox()
        self.seed_spin.setRange(-1, 2147483647)
        self.seed_spin.setValue(-1)
        self.seed_spin.setVisible(False)  # Hidden from UI

        # Separator
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"background-color: {DARK_COLORS['border']};")
        layout.addWidget(sep2)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        # Clear button
        clear_btn = QPushButton("Clear")
        clear_btn.setStyleSheet(dynamic_styles.get('secondary_button', ''))
        clear_btn.clicked.connect(self._on_clear)
        button_layout.addWidget(clear_btn)

        # Cancel button
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(dynamic_styles.get('secondary_button', ''))
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        # OK button
        ok_btn = QPushButton("OK")
        ok_btn.setStyleSheet(dynamic_styles.get('primary_button', ''))
        ok_btn.clicked.connect(self._on_ok)
        button_layout.addWidget(ok_btn)

        layout.addLayout(button_layout)

    def _load_data(self):
        """Load existing prompt data into UI"""
        self.prompt_edit.setText(self.prompt_data.get('prompt', ''))
        self.negative_edit.setText(self.prompt_data.get('negative_prompt', ''))
        self.seed_spin.setValue(self.prompt_data.get('seed', -1))
        self.enabled_checkbox.setChecked(self.prompt_data.get('enabled', True))

    def _on_clear(self):
        """Clear all fields"""
        self.prompt_edit.clear()
        self.negative_edit.clear()
        self.seed_spin.setValue(-1)
        self.enabled_checkbox.setChecked(True)

    def _on_ok(self):
        """Save and close dialog"""
        self.result_data = {
            "prompt": self.prompt_edit.toPlainText().strip(),
            "negative_prompt": self.negative_edit.toPlainText().strip(),
            "seed": self.seed_spin.value(),
            "enabled": self.enabled_checkbox.isChecked()
        }
        self.accept()

    def get_result(self) -> dict:
        """Get the result data after dialog is accepted"""
        return self.result_data
