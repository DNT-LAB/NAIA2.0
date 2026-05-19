"""
WildcardAnalyzerDialog - Wildcard pattern analysis result window
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QWidget
)
from PyQt6.QtCore import Qt, pyqtSignal
from ui.theme import DARK_COLORS, get_dynamic_styles
from ui.scaling_manager import get_scaled_font_size, get_scaled_size


class WildcardAnalyzerDialog(QDialog):
    """Dialog to display wildcard analysis results"""

    # Signal emitted when user clicks Auto-Assign button
    auto_assign_requested = pyqtSignal()

    def __init__(self, analysis_result: dict, parent=None):
        """
        Args:
            analysis_result: {
                'wildcards': List[WildcardInfo],
                'total_combinations': int,
                'warning_msg': str
            }
        """
        super().__init__(parent)
        self.analysis_result = analysis_result
        self.setWindowTitle("Wildcard Analysis Result")
        self.setModal(True)
        self.resize(get_scaled_size(600), get_scaled_size(500))

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
        title_label = QLabel("🎲 Wildcard Pattern Analysis")
        title_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(18)}px;
                font-weight: bold;
            }}
        """)
        layout.addWidget(title_label)

        # Summary section
        summary_frame = QWidget()
        summary_frame.setStyleSheet(f"""
            QWidget {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 5px;
            }}
        """)
        summary_layout = QVBoxLayout(summary_frame)
        summary_layout.setContentsMargins(
            get_scaled_size(15), get_scaled_size(15),
            get_scaled_size(15), get_scaled_size(15)
        )
        summary_layout.setSpacing(get_scaled_size(8))

        # Wildcard count
        wildcards = self.analysis_result.get('wildcards', [])
        count_label = QLabel(f"✅ Found {len(wildcards)} wildcard(s)")
        count_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(14)}px;
            }}
        """)
        summary_layout.addWidget(count_label)

        # Total combinations
        total = self.analysis_result.get('total_combinations', 0)
        combo_label = QLabel(f"📊 Total combinations: {total:,}")
        combo_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(14)}px;
            }}
        """)
        summary_layout.addWidget(combo_label)

        # Warning message
        warning_msg = self.analysis_result.get('warning_msg', '')
        warning_label = QLabel(warning_msg)
        warning_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(13)}px;
            }}
        """)
        warning_label.setWordWrap(True)
        summary_layout.addWidget(warning_label)

        layout.addWidget(summary_frame)

        # Details section
        details_label = QLabel("Wildcard Details:")
        details_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(14)}px;
                font-weight: bold;
            }}
        """)
        layout.addWidget(details_label)

        # Details text (scrollable)
        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 8px;
                font-size: {get_scaled_font_size(13)}px;
                font-family: 'Consolas', 'Courier New', monospace;
            }}
        """)

        # Format details
        details_lines = []
        for i, wc in enumerate(wildcards, 1):
            if wc.master_name:
                details_lines.append(
                    f"{i}. {wc.name}\n"
                    f"   Items: {wc.item_count}\n"
                    f"   Master: {wc.master_name}\n"
                    f"   Advances every: {wc.advance_rate} iteration(s)\n"
                )
            else:
                details_lines.append(
                    f"{i}. {wc.name}\n"
                    f"   Items: {wc.item_count}\n"
                    f"   Type: Sequential (independent)\n"
                    f"   Advances every: 1 iteration\n"
                )

        self.details_text.setPlainText("\n".join(details_lines))
        layout.addWidget(self.details_text, 1)  # Stretch

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        # Auto-Assign button
        auto_assign_btn = QPushButton("Auto-Assign to Frames")
        auto_assign_btn.setFixedWidth(get_scaled_size(180))
        auto_assign_btn.setStyleSheet(f"""
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
        """)
        auto_assign_btn.setToolTip("Automatically assign wildcard combinations to all frames")
        auto_assign_btn.clicked.connect(self._on_auto_assign_clicked)
        button_layout.addWidget(auto_assign_btn)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(get_scaled_size(100))
        close_btn.setStyleSheet(f"""
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
        close_btn.clicked.connect(self.accept)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

    def _on_auto_assign_clicked(self):
        """Emit signal and close dialog"""
        self.auto_assign_requested.emit()
        self.accept()
