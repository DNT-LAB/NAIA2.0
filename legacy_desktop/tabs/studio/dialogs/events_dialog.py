"""
EventsDialog - Batch prompt editing dialog for Studio Tab frames
"""

from typing import List, Dict, Optional, TYPE_CHECKING

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QWidget, QTextEdit, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal

from legacy_desktop.ui.theme import DARK_COLORS, get_dynamic_styles
from legacy_desktop.ui.scaling_manager import get_scaled_font_size, get_scaled_size

if TYPE_CHECKING:
    from legacy_desktop.tabs.studio.manager import ResultImageFrameManager


class EventRowWidget(QFrame):
    """Single event row widget with prompt and negative prompt inputs"""

    def __init__(self, index: int, prompt: str = "", negative: str = "", parent=None):
        super().__init__(parent)
        self.index = index

        self.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
            }}
        """)

        self._create_ui(prompt, negative)

    def _create_ui(self, prompt: str, negative: str):
        """Create the row UI"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            get_scaled_size(8), get_scaled_size(6),
            get_scaled_size(8), get_scaled_size(6)
        )
        layout.setSpacing(get_scaled_size(8))

        # Index label
        index_label = QLabel(f"[{self.index + 1}]")
        index_label.setFixedWidth(get_scaled_size(35))
        index_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        index_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['accent_blue']};
                font-size: {get_scaled_font_size(20)}px;
                font-weight: bold;
            }}
        """)
        layout.addWidget(index_label)

        # Prompt input
        self.prompt_edit = QTextEdit()
        self.prompt_edit.setPlaceholderText("Main prompt...")
        self.prompt_edit.setText(prompt)
        self.prompt_edit.setMinimumHeight(get_scaled_size(60))
        self.prompt_edit.setMaximumHeight(get_scaled_size(100))
        self.prompt_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 4px;
                font-size: {get_scaled_font_size(18)}px;
            }}
        """)
        layout.addWidget(self.prompt_edit, 3)  # Stretch factor 3

        # Negative prompt input
        self.negative_edit = QTextEdit()
        self.negative_edit.setPlaceholderText("Additional negative...")
        self.negative_edit.setText(negative)
        self.negative_edit.setMinimumHeight(get_scaled_size(60))
        self.negative_edit.setMaximumHeight(get_scaled_size(100))
        self.negative_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 4px;
                font-size: {get_scaled_font_size(18)}px;
            }}
        """)
        layout.addWidget(self.negative_edit, 2)  # Stretch factor 2

    def get_data(self) -> Dict:
        """Get prompt data from this row"""
        return {
            'index': self.index,
            'prompt': self.prompt_edit.toPlainText(),
            'negative_prompt': self.negative_edit.toPlainText()
        }


class EventsDialog(QDialog):
    """Dialog for batch editing frame prompts"""

    # Signal emitted when dialog is opened/closed
    dialog_opened = pyqtSignal()
    dialog_closed = pyqtSignal()

    def __init__(self, frame_manager: 'ResultImageFrameManager', parent=None):
        super().__init__(parent)
        self.frame_manager = frame_manager
        self.event_rows: List[EventRowWidget] = []

        self.setWindowTitle("Batch Event Editor")
        self.setMinimumSize(get_scaled_size(1200), get_scaled_size(750))
        self.resize(get_scaled_size(1350), get_scaled_size(900))
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
        self._load_frame_data()

        # Emit signal when dialog opens
        self.dialog_opened.emit()

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
        title_label = QLabel("Batch Event Editor")
        title_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['accent_blue']};
                font-size: {get_scaled_font_size(25)}px;
                font-weight: bold;
            }}
        """)
        layout.addWidget(title_label)

        # Description
        desc_label = QLabel(
            "Edit prompts for all frames at once. Changes will be applied when you click 'Apply'."
        )
        desc_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(18)}px;
            }}
        """)
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        # Header row
        header_frame = QFrame()
        header_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
            }}
        """)
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(
            get_scaled_size(8), get_scaled_size(6),
            get_scaled_size(8), get_scaled_size(6)
        )
        header_layout.setSpacing(get_scaled_size(8))

        header_style = f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(19)}px;
                font-weight: bold;
            }}
        """

        index_header = QLabel("#")
        index_header.setFixedWidth(get_scaled_size(35))
        index_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        index_header.setStyleSheet(header_style)
        header_layout.addWidget(index_header)

        prompt_header = QLabel("Main Prompt")
        prompt_header.setStyleSheet(header_style)
        header_layout.addWidget(prompt_header, 3)

        negative_header = QLabel("Additional Negative")
        negative_header.setStyleSheet(header_style)
        header_layout.addWidget(negative_header, 2)

        layout.addWidget(header_frame)

        # Scrollable content area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet(f"""
            QScrollArea {{
                background-color: {DARK_COLORS['bg_primary']};
                border: none;
            }}
        """)

        self.content_widget = QWidget()
        self.content_widget.setStyleSheet(f"""
            QWidget {{
                background-color: {DARK_COLORS['bg_primary']};
            }}
        """)
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setSpacing(get_scaled_size(6))
        self.content_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area.setWidget(self.content_widget)
        layout.addWidget(scroll_area, 1)

        # Button row
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(dynamic_styles.get('secondary_button', ''))
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        # Get :Sequence button
        get_sequence_btn = QPushButton("Get :Sequence")
        get_sequence_btn.setStyleSheet(dynamic_styles.get('secondary_button', ''))
        get_sequence_btn.clicked.connect(self._on_get_sequence)
        get_sequence_btn.setToolTip("Generate :sequence text from current events")
        button_layout.addWidget(get_sequence_btn)

        apply_btn = QPushButton("Apply")
        apply_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #2d7d46;
                color: {DARK_COLORS['text_primary']};
                border: none;
                border-radius: 4px;
                padding: 8px 20px;
                font-size: {get_scaled_font_size(19)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #3d9d56;
            }}
            QPushButton:pressed {{
                background-color: #1d6d36;
            }}
        """)
        apply_btn.clicked.connect(self._on_apply)
        button_layout.addWidget(apply_btn)

        layout.addLayout(button_layout)

    def _load_frame_data(self):
        """Load current frame data into the dialog"""
        if not self.frame_manager:
            return

        # Clear existing rows
        self.event_rows.clear()
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Create rows for each frame
        for frame in self.frame_manager.frames:
            prompt_data = frame.get_prompt_data()
            row = EventRowWidget(
                index=frame.index,
                prompt=prompt_data.get('prompt', ''),
                negative=prompt_data.get('negative_prompt', ''),
                parent=self.content_widget
            )
            self.event_rows.append(row)
            self.content_layout.addWidget(row)

        # Add stretch at the end
        self.content_layout.addStretch()

    def _on_get_sequence(self):
        """Generate and display :sequence text from current events"""
        from legacy_desktop.tabs.studio.sequence_generator import generate_sequence_text
        from legacy_desktop.tabs.studio.dialogs.sequence_text_dialog import SequenceTextDialog

        # Collect current data from event rows (including any edits made)
        frames_data = []
        for row in self.event_rows:
            data = row.get_data()
            # Get resolution from frame if available
            resolution = ""
            if self.frame_manager:
                frame = self.frame_manager.get_frame(data['index'])
                if frame:
                    resolution = frame.get_resolution()

            frames_data.append({
                'prompt': data['prompt'],
                'negative_prompt': data['negative_prompt'],
                'resolution': resolution
            })

        # Generate sequence text
        sequence_text = generate_sequence_text(frames_data)

        # TODO(web-dialog): 원래 SequenceTextDialog.exec() — Web Shell 패널로 재구현 필요.
        print(f"[Dialog/SKIPPED] SequenceTextDialog 차단 — Web Shell 재구현 예정\n[sequence] {sequence_text}")

    def _on_apply(self):
        """Apply changes to frames"""
        if not self.frame_manager:
            self.accept()
            return

        # Apply data to each frame
        for row in self.event_rows:
            data = row.get_data()
            frame = self.frame_manager.get_frame(data['index'])
            if frame:
                # Get existing prompt data and update only prompt fields
                existing_data = frame.get_prompt_data()
                existing_data['prompt'] = data['prompt']
                existing_data['negative_prompt'] = data['negative_prompt']
                frame.set_prompt_data(existing_data)

        self.accept()

    def reject(self):
        """Override reject to emit signal"""
        self.dialog_closed.emit()
        super().reject()

    def accept(self):
        """Override accept to emit signal"""
        self.dialog_closed.emit()
        super().accept()

    def closeEvent(self, event):
        """Override close event to emit signal"""
        self.dialog_closed.emit()
        super().closeEvent(event)
