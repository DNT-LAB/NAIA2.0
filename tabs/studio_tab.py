"""
StudioTab - Multi-image generation and management tab
"""

import random

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QPushButton, QSpinBox, QFrame, QSplitter, QMessageBox, QLineEdit,
    QComboBox, QFileDialog, QCheckBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap

from interfaces.base_tab_module import BaseTabModule
from tabs.studio.manager import ResultImageFrameManager
from tabs.studio.dialogs.prompt_dialog import PromptSettingDialog
from tabs.studio.dialogs.detached_textedit_dialog import DetachedTextEditDialog
from tabs.studio.dialogs.export_dialog import ExportViewsDialog
from tabs.studio.dialogs.save_preset_dialog import SavePresetDialog
from tabs.studio.dialogs.open_preset_dialog import OpenPresetDialog
from tabs.studio.dialogs.events_dialog import EventsDialog
from tabs.studio.dialogs.wildcard_selector_dialog import WildcardSelectorDialog
from tabs.studio.widgets.wildcard_nav_panel import WildcardNavPanel
from ui.theme import DARK_COLORS, DARK_STYLES, get_dynamic_styles
from ui.scaling_manager import get_scaled_font_size, get_scaled_size


class StudioTab(BaseTabModule):
    """Studio Tab - Multi-image generation management interface"""

    def __init__(self):
        super().__init__()
        self.frame_manager: ResultImageFrameManager = None

        # UI references
        self.prefix_prompt_edit: QTextEdit = None
        self.postfix_prompt_edit: QTextEdit = None
        self.negative_prompt_edit: QTextEdit = None
        self.repeat_spin: QSpinBox = None
        self.progress_label: QLabel = None
        self.start_btn: QPushButton = None
        self.stop_btn: QPushButton = None
        self.save_view_btn: QPushButton = None
        self.fix_seed_checkbox: QCheckBox = None

        # Lock buttons for detached windows
        self.prefix_lock_btn: QPushButton = None
        self.postfix_lock_btn: QPushButton = None
        self.negative_lock_btn: QPushButton = None

        # Wildcard analyzer section
        self.wildcard_input: QLineEdit = None
        self.analyze_btn: QPushButton = None
        self.wildcard_analyzer_frame: QFrame = None  # Reference for border styling

        # Wildcard navigation panel
        self.wildcard_nav_panel: WildcardNavPanel = None

        # Bottom panel controls
        self.add_frame_btn: QPushButton = None
        self.position_input: QLineEdit = None
        self.global_resolution_combo: QComboBox = None
        self.reset_frames_btn: QPushButton = None

        # Detached dialogs
        self.detached_dialogs = {}

    def get_tab_title(self) -> str:
        return "Studio"

    def get_tab_order(self) -> int:
        return 50

    def get_tab_type(self) -> str:
        return 'core'

    def create_widget(self, parent: QWidget) -> QWidget:
        """Create main Studio tab UI"""
        main_widget = QWidget(parent)
        main_widget.setStyleSheet(f"background-color: {DARK_COLORS['bg_primary']};")

        layout = QVBoxLayout(main_widget)
        layout.setContentsMargins(
            get_scaled_size(8), get_scaled_size(8),
            get_scaled_size(8), get_scaled_size(8)
        )
        layout.setSpacing(get_scaled_size(8))

        # 1. Top control area
        top_control = self._create_top_control_area()
        layout.addWidget(top_control)

        # 2. Wildcard analyzer section (NEW!)
        wildcard_analyzer = self._create_wildcard_analyzer_section()
        layout.addWidget(wildcard_analyzer)

        # 2.5. Wildcard navigation panel (hidden by default)
        self.wildcard_nav_panel = WildcardNavPanel()
        self.wildcard_nav_panel.hide()  # Hidden until wildcard mode activated
        self.wildcard_nav_panel.page_changed.connect(self._on_wildcard_page_changed)
        self.wildcard_nav_panel.axis_swapped.connect(self._on_wildcard_axis_swapped)
        self.wildcard_nav_panel.exit_mode_requested.connect(self._on_exit_wildcard_mode)
        layout.addWidget(self.wildcard_nav_panel)

        # 3. ResultImageFrame grid area (3x3 for wildcard mode)
        self.frame_manager = ResultImageFrameManager(self)
        grid_widget = self.frame_manager.create_grid(rows=3, cols=3)
        layout.addWidget(grid_widget, 1)  # Stretch factor 1

        # 4. Bottom control panel
        bottom_panel = self._create_bottom_panel()
        layout.addWidget(bottom_panel)

        # Connect manager signals
        self._connect_manager_signals()

        self.widget = main_widget
        return main_widget

    def _create_top_control_area(self) -> QFrame:
        """Create top control area with prompts and generation controls"""
        control_frame = QFrame()
        control_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 5px;
            }}
        """)

        layout = QHBoxLayout(control_frame)
        layout.setContentsMargins(
            get_scaled_size(10), get_scaled_size(10),
            get_scaled_size(10), get_scaled_size(10)
        )
        layout.setSpacing(get_scaled_size(10))

        dynamic_styles = get_dynamic_styles()

        # 1-1. Prefix prompt area (left)
        prefix_frame = self._create_prompt_section(
            "Prefix Prompt",
            "All images will start with this prompt...",
            "prefix"
        )
        layout.addWidget(prefix_frame, 1)

        # 1-2. Postfix prompt area (middle-left)
        postfix_frame = self._create_prompt_section(
            "Postfix Prompt",
            "All images will end with this prompt...",
            "postfix"
        )
        layout.addWidget(postfix_frame, 1)

        # 1-3. Negative prompt area (middle-right)
        negative_frame = self._create_prompt_section(
            "Negative Prompt",
            "Negative prompt applied to all images...",
            "negative"
        )
        layout.addWidget(negative_frame, 1)

        # 1-4. Generation control area (right)
        control_panel = self._create_generation_control()
        layout.addWidget(control_panel)

        return control_frame

    def _create_prompt_section(self, title: str, placeholder: str, section_type: str) -> QFrame:
        """Create a prompt input section

        Args:
            title: Section title
            placeholder: Placeholder text for TextEdit
            section_type: "prefix", "postfix", or "negative"
        """
        frame = QFrame()
        frame.setStyleSheet("border: none; background: transparent;")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(get_scaled_size(2))

        dynamic_styles = get_dynamic_styles()

        # Header row with label and buttons
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(get_scaled_size(4))

        # Label
        label = QLabel(title)
        label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(14)}px;
                font-weight: bold;
            }}
        """)
        header_layout.addWidget(label)
        header_layout.addStretch()

        # Small button style
        small_btn_style = f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 3px;
                padding: 2px 6px;
                font-size: {get_scaled_font_size(12)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
            QPushButton:pressed {{
                background-color: {DARK_COLORS['bg_pressed']};
            }}
        """

        # Copy from Main button (only for negative prompt)
        if section_type == "negative":
            copy_btn = QPushButton("Copy from Main")
            copy_btn.setStyleSheet(small_btn_style)
            copy_btn.setToolTip("Copy negative prompt from Main Window")
            copy_btn.clicked.connect(self._on_copy_from_main_clicked)
            header_layout.addWidget(copy_btn)

        # Lock button (detach to window)
        lock_btn = QPushButton("🔓")
        lock_btn.setFixedSize(get_scaled_size(24), get_scaled_size(20))
        lock_btn.setStyleSheet(small_btn_style)
        lock_btn.setToolTip("Detach to separate window")
        lock_btn.clicked.connect(lambda: self._on_lock_clicked(section_type))
        header_layout.addWidget(lock_btn)

        # Store lock button reference
        if section_type == "prefix":
            self.prefix_lock_btn = lock_btn
        elif section_type == "postfix":
            self.postfix_lock_btn = lock_btn
        elif section_type == "negative":
            self.negative_lock_btn = lock_btn

        layout.addLayout(header_layout)

        # TextEdit (stretch factor 3)
        text_edit = QTextEdit()
        text_edit.setPlaceholderText(placeholder)
        text_edit.setStyleSheet(dynamic_styles.get('compact_textedit', ''))
        layout.addWidget(text_edit, 3)  # stretch factor 3 for 1:3 ratio

        if section_type == "prefix":
            self.prefix_prompt_edit = text_edit
        elif section_type == "postfix":
            self.postfix_prompt_edit = text_edit
        elif section_type == "negative":
            self.negative_prompt_edit = text_edit

        return frame

    def _create_generation_control(self) -> QFrame:
        """Create generation control panel"""
        frame = QFrame()
        frame.setFixedWidth(get_scaled_size(220))
        frame.setStyleSheet("border: none; background: transparent;")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(get_scaled_size(6))

        dynamic_styles = get_dynamic_styles()

        # Repeat count row
        repeat_layout = QHBoxLayout()
        repeat_label = QLabel("Repeat per event:")
        repeat_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(13)}px;
            }}
        """)
        repeat_layout.addWidget(repeat_label)

        self.repeat_spin = QSpinBox()
        self.repeat_spin.setRange(1, 10)
        self.repeat_spin.setValue(1)
        self.repeat_spin.setFixedWidth(get_scaled_size(80))
        self.repeat_spin.setStyleSheet(f"""
            QSpinBox {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 3px;
                padding: 2px 4px;
                font-size: {get_scaled_font_size(14)}px;
            }}
            QSpinBox::up-button, QSpinBox::down-button {{
                width: {get_scaled_size(24)}px;
            }}
        """)
        self.repeat_spin.valueChanged.connect(self._update_start_button)
        repeat_layout.addWidget(self.repeat_spin)
        repeat_layout.addStretch()
        layout.addLayout(repeat_layout)

        # Progress label
        self.progress_label = QLabel("Ready")
        self.progress_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(13)}px;
            }}
        """)
        layout.addWidget(self.progress_label)

        # Start button
        self.start_btn = QPushButton("Start Generation")
        self.start_btn.setStyleSheet(f"""
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
        self.start_btn.clicked.connect(self._on_start_clicked)
        layout.addWidget(self.start_btn)

        # Stop button
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #703030;
                color: {DARK_COLORS['text_primary']};
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-size: {get_scaled_font_size(14)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #904040;
            }}
            QPushButton:disabled {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_disabled']};
            }}
        """)
        self.stop_btn.clicked.connect(self._on_stop_clicked)
        self.stop_btn.setEnabled(False)
        layout.addWidget(self.stop_btn)

        # Save view button
        self.save_view_btn = QPushButton("Save View")
        self.save_view_btn.setStyleSheet(dynamic_styles.get('secondary_button', ''))
        self.save_view_btn.clicked.connect(self._on_save_view_clicked)
        layout.addWidget(self.save_view_btn)

        # Fix seed checkbox (with value display)
        self.fix_seed_checkbox = QCheckBox("Fix Seed (-1)")
        self.fix_seed_checkbox.setStyleSheet(f"""
            QCheckBox {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(13)}px;
            }}
            QCheckBox::indicator {{
                width: {get_scaled_size(16)}px;
                height: {get_scaled_size(16)}px;
            }}
        """)
        self.fix_seed_checkbox.setToolTip("Use last generated seed for all frames (Repeat forced to 1)")
        self.fix_seed_checkbox.stateChanged.connect(self._on_fix_seed_changed)
        layout.addWidget(self.fix_seed_checkbox)

        layout.addStretch()

        return frame

    def _create_wildcard_analyzer_section(self) -> QFrame:
        """Create wildcard analyzer section - Single row"""
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 5px;
            }}
        """)

        # Store reference for dynamic styling
        self.wildcard_analyzer_frame = frame

        layout = QHBoxLayout(frame)
        layout.setContentsMargins(
            get_scaled_size(8), get_scaled_size(4),
            get_scaled_size(8), get_scaled_size(4)
        )
        layout.setSpacing(get_scaled_size(6))

        # WC1 Button
        self.wc1_btn = QPushButton("WC1")
        self.wc1_btn.setFixedSize(get_scaled_size(50), get_scaled_size(28))
        self.wc1_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['accent_blue']};
                color: {DARK_COLORS['text_primary']};
                border: none;
                border-radius: 3px;
                padding: 4px 8px;
                font-size: {get_scaled_font_size(12)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['accent_blue_hover']};
            }}
        """)
        self.wc1_btn.setToolTip("Select WC1 wildcard")
        self.wc1_btn.clicked.connect(self._on_wc1_clicked)
        layout.addWidget(self.wc1_btn)

        # WC1 LineEdit
        self.wc1_input = QLineEdit()
        self.wc1_input.setPlaceholderText("Not selected")
        self.wc1_input.setReadOnly(True)
        self.wc1_input.setFixedHeight(get_scaled_size(28))
        self.wc1_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 3px;
                padding: 4px 8px;
                font-size: {get_scaled_font_size(12)}px;
            }}
        """)
        layout.addWidget(self.wc1_input, 1)

        # WC2 Button
        self.wc2_btn = QPushButton("WC2")
        self.wc2_btn.setFixedSize(get_scaled_size(50), get_scaled_size(28))
        self.wc2_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['accent_blue']};
                color: {DARK_COLORS['text_primary']};
                border: none;
                border-radius: 3px;
                padding: 4px 8px;
                font-size: {get_scaled_font_size(12)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['accent_blue_hover']};
            }}
        """)
        self.wc2_btn.setToolTip("Select WC2 wildcard")
        self.wc2_btn.clicked.connect(self._on_wc2_clicked)
        layout.addWidget(self.wc2_btn)

        # WC2 LineEdit
        self.wc2_input = QLineEdit()
        self.wc2_input.setPlaceholderText("Not selected")
        self.wc2_input.setReadOnly(True)
        self.wc2_input.setFixedHeight(get_scaled_size(28))
        self.wc2_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 3px;
                padding: 4px 8px;
                font-size: {get_scaled_font_size(12)}px;
            }}
        """)
        layout.addWidget(self.wc2_input, 1)

        # Spacer
        layout.addSpacing(get_scaled_size(10))

        # ASSIGN Button
        self.assign_btn = QPushButton("ASSIGN")
        self.assign_btn.setFixedSize(get_scaled_size(80), get_scaled_size(28))
        self.assign_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #44AA44;
                color: {DARK_COLORS['text_primary']};
                border: none;
                border-radius: 3px;
                padding: 4px 8px;
                font-size: {get_scaled_font_size(12)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #55BB55;
            }}
            QPushButton:disabled {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_secondary']};
            }}
        """)
        self.assign_btn.setToolTip("Assign wildcards to frames")
        self.assign_btn.clicked.connect(self._on_assign_clicked)
        self.assign_btn.setEnabled(False)
        layout.addWidget(self.assign_btn)

        # CLEAR Button
        self.clear_btn = QPushButton("CLEAR")
        self.clear_btn.setFixedSize(get_scaled_size(70), get_scaled_size(28))
        self.clear_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 3px;
                padding: 4px 8px;
                font-size: {get_scaled_font_size(12)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
        """)
        self.clear_btn.setToolTip("Clear wildcards and frames")
        self.clear_btn.clicked.connect(self._on_clear_clicked)
        layout.addWidget(self.clear_btn)

        # Store selected wildcards
        self.selected_wc1 = None  # (name, items_list)
        self.selected_wc2 = None  # (name, items_list)

        return frame

    def _create_bottom_panel(self) -> QFrame:
        """Create bottom control panel for frame management"""
        panel = QFrame()
        panel.setFixedHeight(get_scaled_size(36))
        panel.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
            }}
        """)

        layout = QHBoxLayout(panel)
        layout.setContentsMargins(
            get_scaled_size(10), get_scaled_size(4),
            get_scaled_size(10), get_scaled_size(4)
        )
        layout.setSpacing(get_scaled_size(10))

        dynamic_styles = get_dynamic_styles()

        # Small button style for bottom panel
        small_btn_style = f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 3px;
                padding: 4px 8px;
                font-size: {get_scaled_font_size(12)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
            QPushButton:pressed {{
                background-color: {DARK_COLORS['bg_pressed']};
            }}
        """

        # Add Frame button
        self.add_frame_btn = QPushButton("Add Event Frame")
        self.add_frame_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 3px;
                padding: 4px 12px;
                font-size: {get_scaled_font_size(13)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
            QPushButton:pressed {{
                background-color: {DARK_COLORS['bg_pressed']};
            }}
        """)
        self.add_frame_btn.clicked.connect(self._on_add_frame_clicked)
        layout.addWidget(self.add_frame_btn)

        # Position label
        pos_label = QLabel("Position:")
        pos_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(13)}px;
                border: none;
            }}
        """)
        layout.addWidget(pos_label)

        # Position input
        self.position_input = QLineEdit()
        self.position_input.setPlaceholderText("last")
        self.position_input.setFixedWidth(get_scaled_size(50))
        self.position_input.setProperty("autocomplete_ignore", True)  # Disable autocomplete
        self.position_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 3px;
                padding: 2px 6px;
                font-size: {get_scaled_font_size(13)}px;
            }}
        """)
        self.position_input.editingFinished.connect(self._on_position_editing_finished)
        layout.addWidget(self.position_input)

        # Frame count label
        self.frame_count_label = QLabel("(Frames: 6)")
        self.frame_count_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(12)}px;
                border: none;
            }}
        """)
        layout.addWidget(self.frame_count_label)

        # Reset frames button
        self.reset_frames_btn = QPushButton("Reset")
        self.reset_frames_btn.setStyleSheet(small_btn_style)
        self.reset_frames_btn.setToolTip("Reset all frames (keeps prompts)")
        self.reset_frames_btn.clicked.connect(self._on_reset_frames_clicked)
        layout.addWidget(self.reset_frames_btn)

        # Separator
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.VLine)
        sep1.setStyleSheet(f"background-color: {DARK_COLORS['border']};")
        layout.addWidget(sep1)

        # Global resolution label
        global_res_label = QLabel("Global Res:")
        global_res_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(13)}px;
                border: none;
            }}
        """)
        layout.addWidget(global_res_label)

        # Global resolution combo
        from tabs.studio.frame import ResultImageFrame
        self.global_resolution_combo = QComboBox()
        self.global_resolution_combo.setFixedWidth(get_scaled_size(100))
        self.global_resolution_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 3px;
                padding: 2px 4px;
                font-size: {get_scaled_font_size(12)}px;
            }}
            QComboBox::drop-down {{
                width: {get_scaled_size(16)}px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                selection-background-color: {DARK_COLORS['accent_blue']};
            }}
        """)
        for res in ResultImageFrame.STANDARD_RESOLUTIONS:
            self.global_resolution_combo.addItem(res)
        self.global_resolution_combo.setCurrentText("1024 x 1024")
        self.global_resolution_combo.currentTextChanged.connect(self._on_global_resolution_changed)
        layout.addWidget(self.global_resolution_combo)

        # Separator
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.VLine)
        sep2.setStyleSheet(f"background-color: {DARK_COLORS['border']};")
        layout.addWidget(sep2)

        # Event Preset buttons
        open_preset_btn = QPushButton("Open Presets")
        open_preset_btn.setStyleSheet(small_btn_style)
        open_preset_btn.setToolTip("Load event presets from file")
        open_preset_btn.clicked.connect(self._on_open_presets_clicked)
        layout.addWidget(open_preset_btn)

        save_preset_btn = QPushButton("Save Presets")
        save_preset_btn.setStyleSheet(small_btn_style)
        save_preset_btn.setToolTip("Save current event presets to file")
        save_preset_btn.clicked.connect(self._on_save_presets_clicked)
        layout.addWidget(save_preset_btn)

        export_views_btn = QPushButton("Export Views")
        export_views_btn.setStyleSheet(small_btn_style)
        export_views_btn.setToolTip("Export all generated images")
        export_views_btn.clicked.connect(self._on_export_views_clicked)
        layout.addWidget(export_views_btn)

        # Events button (batch prompt editor) - green background for visibility
        self.events_btn = QPushButton("Events")
        self.events_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #2d7d46;
                color: {DARK_COLORS['text_primary']};
                border: 1px solid #3d8d56;
                border-radius: 3px;
                padding: 4px 12px;
                font-size: {get_scaled_font_size(13)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #3d9d56;
            }}
            QPushButton:pressed {{
                background-color: #1d6d36;
            }}
        """)
        self.events_btn.setToolTip("Batch edit prompts for all frames")
        self.events_btn.clicked.connect(self._on_events_clicked)
        layout.addWidget(self.events_btn)

        layout.addStretch()

        return panel

    def _connect_manager_signals(self):
        """Connect frame manager signals"""
        self.frame_manager.generation_started.connect(self._on_generation_started)
        self.frame_manager.generation_stopped.connect(self._on_generation_stopped)
        self.frame_manager.generation_progress.connect(self._on_generation_progress)
        self.frame_manager.prompt_edit_requested.connect(self._on_prompt_edit_requested)
        self.frame_manager.frame_updated.connect(self._on_frame_updated)

    def initialize_with_context(self, app_context):
        """Initialize with AppContext"""
        super().initialize_with_context(app_context)

        if self.frame_manager:
            self.frame_manager.set_app_context(app_context)

        # Subscribe to events
        if app_context:
            app_context.subscribe("generation_completed_for_studio", self._on_image_generated)
            app_context.subscribe("generation_error_for_studio", self._on_generation_error)

        self._update_start_button()

    # === Event Handlers ===
    def _on_start_clicked(self):
        """Handle start generation button click"""
        if not self.frame_manager:
            return

        active_count = self.frame_manager.get_total_event_count()
        if active_count == 0:
            QMessageBox.warning(
                self.widget, "Warning",
                "No frames with prompts configured.\n"
                "Click the 'Prompt' button on a frame to set its prompt."
            )
            return

        repeat_count = self.repeat_spin.value()
        self.frame_manager.start_generation(repeat_count)

    def _on_stop_clicked(self):
        """Handle stop button click"""
        if self.frame_manager:
            self.frame_manager.stop_generation()

    def _on_save_view_clicked(self):
        """Handle save view button click"""
        if self.frame_manager:
            self.frame_manager.save_current_view()

    def _on_fix_seed_changed(self, state: int):
        """Handle fix seed checkbox state change"""
        is_checked = state == 2  # Qt.CheckState.Checked

        if is_checked:
            # Force repeat to 1 and disable
            self.repeat_spin.setValue(1)
            self.repeat_spin.setEnabled(False)
            # Display current seed value (or -1 if not yet generated)
            if self.frame_manager:
                current_seed = self.frame_manager.get_last_seed()
                if current_seed is not None and current_seed != -1:
                    self._update_fix_seed_label(current_seed)
        else:
            # Re-enable repeat spin
            self.repeat_spin.setEnabled(True)
            # Reset label to show -1 and clear last seed
            self.fix_seed_checkbox.setText("Fix Seed (-1)")
            if self.frame_manager:
                self.frame_manager.set_last_seed(-1)

        # Update manager's fix seed state
        if self.frame_manager:
            self.frame_manager.set_fix_seed_mode(is_checked)

        self._update_start_button()

    def _on_generation_started(self):
        """Handle generation started"""
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_label.setText("Generating...")

    def _on_generation_stopped(self):
        """Handle generation stopped"""
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_label.setText("Ready")
        self._update_start_button()

    def _on_generation_progress(self, current: int, total: int):
        """Handle generation progress update"""
        self.progress_label.setText(f"Progress: {current} / {total}")

    def _on_prompt_edit_requested(self, frame_index: int):
        """Handle prompt edit request for a frame"""
        frame = self.frame_manager.get_frame(frame_index)
        if not frame:
            return

        # TODO(web-dialog): 원래 PromptSettingDialog.exec() — Web Shell 패널/모달로 재구현 필요.
        print(f"[Dialog/SKIPPED] PromptSettingDialog 차단 (frame={frame_index}) — Web Shell 재구현 예정")
        return

    def _on_frame_updated(self, frame_index: int):
        """Handle frame update (for single frame generation)"""
        if not self.app_context or not self.frame_manager:
            return

        frame = self.frame_manager.get_frame(frame_index)
        if not frame or not frame.has_prompt():
            return

        # Build full prompt: Prefix + Main Prompt + Postfix
        prompt_data = frame.get_prompt_data()
        prefix = self.prefix_prompt_edit.toPlainText().strip() if self.prefix_prompt_edit else ""
        main_prompt = prompt_data.get('prompt', '').strip()
        postfix = self.postfix_prompt_edit.toPlainText().strip() if self.postfix_prompt_edit else ""

        full_prompt_parts = []
        if prefix:
            full_prompt_parts.append(prefix)
        if main_prompt:
            full_prompt_parts.append(main_prompt)
        if postfix:
            full_prompt_parts.append(postfix)

        full_prompt = ", ".join(full_prompt_parts)

        # Build negative prompt: Negative Prompt + Additional Negative Prompt
        global_negative = self.negative_prompt_edit.toPlainText().strip() if self.negative_prompt_edit else ""
        additional_negative = prompt_data.get('negative_prompt', '').strip()

        negative_parts = []
        if global_negative:
            negative_parts.append(global_negative)
        if additional_negative:
            negative_parts.append(additional_negative)

        full_negative = ", ".join(negative_parts)

        # Parse resolution from frame
        resolution_text = frame.get_resolution()
        if " x " in resolution_text:
            res_parts = resolution_text.split(" x ")
            width = int(res_parts[0].strip())
            height = int(res_parts[1].strip())
        else:
            width, height = 1024, 1024

        # Prepare override parameters for direct generation.
        override_params = {
            'input': full_prompt,
            'negative_prompt': full_negative,
            'width': width,
            'height': height,
            'random_resolution': False,
            'studio_request': True,  # Studio request identifier
            'studio_frame_index': frame_index
        }

        # Apply seed based on fix seed mode
        if self.frame_manager and self.frame_manager.fix_seed_mode:
            # Use last generated seed if available, otherwise generate random
            last_seed = self.frame_manager.get_last_seed()
            if last_seed is None or last_seed == -1:
                # Generate random seed and store it
                last_seed = random.randint(0, 9999999999)
                self.frame_manager.set_last_seed(last_seed)
                self._update_fix_seed_label(last_seed)
                print(f"  Generated new fixed seed: {last_seed}")
            override_params['seed'] = last_seed
            print(f"  Using fixed seed: {last_seed}")
        else:
            # Always generate independent random seed for Studio
            # (overrides main window's seed_fix_checkbox state)
            seed = prompt_data.get('seed', -1)
            if seed != -1:
                override_params['seed'] = seed
            else:
                override_params['seed'] = random.randint(0, 9999999999)
            print(f"  Using random seed: {override_params['seed']}")

        print(f"Studio: Requesting generation for frame #{frame_index + 1}")
        print(f"  Resolution: {width}x{height}")
        print(f"  Prompt: {full_prompt[:100]}...")
        print(f"  Negative: {full_negative[:50]}..." if full_negative else "  Negative: (none)")

        # Call generation controller directly.
        try:
            if hasattr(self.app_context, 'main_window'):
                gen_controller = self.app_context.main_window.generation_controller
                gen_controller.execute_generation_pipeline(overrides=override_params)
                print(f"Studio: Generation pipeline started for frame #{frame_index + 1}")
            else:
                print("Studio: generation_controller not found")
                self.frame_manager.on_generation_failed(frame_index, "Generation controller not available")
        except Exception as e:
            print(f"Studio: Generation error: {e}")
            self.frame_manager.on_generation_failed(frame_index, str(e))

    def _on_image_generated(self, result):
        """Handle image generation completion"""
        if not self.frame_manager:
            return

        try:
            # Extract frame index from result
            frame_index = result.get('frame_index', 0) if isinstance(result, dict) else 0

            # Get image from result
            if isinstance(result, dict):
                image = result.get('image')
                # Store the seed used for this generation
                seed = result.get('seed')
                if seed is not None and seed != -1:
                    self.frame_manager.set_last_seed(seed)
                    self._update_fix_seed_label(seed)
            else:
                image = result  # Direct PIL image

            if image and hasattr(image, 'mode'):
                # Convert PIL image to QPixmap (safe byte-based conversion)
                # NOTE: PIL.ImageQt causes crashes on repeated generation because
                # the underlying buffer goes out of scope while QPixmap still references it.
                from io import BytesIO
                buffer = BytesIO()
                image.save(buffer, format='PNG')
                buffer.seek(0)
                pixmap = QPixmap()
                pixmap.loadFromData(buffer.getvalue())

                self.frame_manager.on_generation_completed(frame_index, pixmap, image)
                print(f"Studio: Image added to frame #{frame_index + 1}")

        except Exception as e:
            print(f"Studio: Error processing generated image: {e}")
            if isinstance(result, dict):
                frame_index = result.get('frame_index', 0)
                self.frame_manager.on_generation_failed(frame_index, str(e))

    def _on_generation_error(self, error_data):
        """Handle generation error for Studio requests"""
        if not self.frame_manager:
            return

        try:
            frame_index = error_data.get('studio_frame_index', 0) if isinstance(error_data, dict) else 0
            message = error_data.get('message', 'Unknown error') if isinstance(error_data, dict) else str(error_data)
            print(f"Studio: Generation failed for frame #{frame_index + 1}: {message}")
            self.frame_manager.on_generation_failed(frame_index, message)
        except Exception as e:
            print(f"Studio: Error handling generation error: {e}")
            # Unlock all frames as a safety fallback
            if self.frame_manager:
                self.frame_manager._unlock_all_frames()

    def _update_start_button(self):
        """Update start button with total generation count (active frames × repeat)"""
        if not self.frame_manager:
            return

        active_count = self.frame_manager.get_total_event_count()
        repeat_count = self.repeat_spin.value() if hasattr(self, 'repeat_spin') else 1
        total_count = active_count * repeat_count
        self.start_btn.setText(f"Start Generation ({total_count})")

    def _update_fix_seed_label(self, seed: int):
        """Update fix seed checkbox label with current seed value"""
        if self.fix_seed_checkbox:
            self.fix_seed_checkbox.setText(f"Fix Seed ({seed})")

    def _update_frame_count_label(self):
        """Update frame count label and position input"""
        if self.frame_manager and hasattr(self, 'frame_count_label'):
            count = len(self.frame_manager.frames)
            self.frame_count_label.setText(f"(Frames: {count})")

            # Update position input to last frame (for appending at end)
            if hasattr(self, 'position_input') and self.position_input:
                self.position_input.setText(str(count))

    # === New Event Handlers ===
    def _on_position_editing_finished(self):
        """Auto-correct position input to valid range"""
        if not self.frame_manager:
            return

        pos_text = self.position_input.text().strip()
        max_pos = len(self.frame_manager.frames)

        if not pos_text:
            # Empty input - set to last position
            self.position_input.setText(str(max_pos))
            return

        try:
            position = int(pos_text)
            # Clamp to valid range [0, max_pos]
            corrected = max(0, min(position, max_pos))
            if corrected != position:
                self.position_input.setText(str(corrected))
        except ValueError:
            # Invalid input, reset to last position
            self.position_input.setText(str(max_pos))

    def _on_add_frame_clicked(self):
        """Handle add frame button click"""
        if not self.frame_manager:
            return

        # Get position from input
        pos_text = self.position_input.text().strip()
        try:
            position = int(pos_text) if pos_text else len(self.frame_manager.frames)
        except ValueError:
            position = len(self.frame_manager.frames)

        # Clamp position to valid range
        max_pos = len(self.frame_manager.frames)
        position = max(0, min(position, max_pos))

        # Add frame at position
        self.frame_manager.insert_frame_at(position)
        self._update_frame_count_label()
        self._update_start_button()
        print(f"Studio: Added frame at position {position}")

    def _on_copy_from_main_clicked(self):
        """Copy negative prompt from main window"""
        if not self.app_context:
            return

        try:
            # Get main window's negative prompt
            main_window = self.app_context.main_window
            if hasattr(main_window, 'negative_prompt_textedit'):
                negative_text = main_window.negative_prompt_textedit.toPlainText()
                if self.negative_prompt_edit:
                    self.negative_prompt_edit.setText(negative_text)
                    print(f"Studio: Copied negative prompt from main window")
        except Exception as e:
            print(f"Studio: Failed to copy from main - {e}")

    def _on_lock_clicked(self, section_type: str):
        """Handle lock button click - detach TextEdit to separate window"""
        text_edit = None
        title = ""

        if section_type == "prefix":
            text_edit = self.prefix_prompt_edit
            title = "Prefix Prompt"
        elif section_type == "postfix":
            text_edit = self.postfix_prompt_edit
            title = "Postfix Prompt"
        elif section_type == "negative":
            text_edit = self.negative_prompt_edit
            title = "Negative Prompt"

        if not text_edit:
            return

        # Check if already detached
        if section_type in self.detached_dialogs:
            dialog = self.detached_dialogs[section_type]
            if dialog.isVisible():
                dialog.raise_()
                dialog.activateWindow()
                return

        # Freeze the TextEdit while detached
        text_edit.setReadOnly(True)
        text_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_disabled']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
            }}
        """)

        # Create detached dialog
        dialog = DetachedTextEditDialog(
            text_edit.toPlainText(),
            title,
            section_type,
            self.widget
        )
        dialog.apply_and_close.connect(lambda text, st=section_type: self._on_apply_and_close(st, text))
        dialog.dialog_closed.connect(lambda st=section_type: self._on_detached_dialog_closed(st))

        self.detached_dialogs[section_type] = dialog
        dialog.show()

        print(f"Studio: Detached {title} to separate window (TextEdit frozen)")

    def _on_apply_and_close(self, section_type: str, text: str):
        """Handle Apply button - update text, unfreeze, and close"""
        dynamic_styles = get_dynamic_styles()

        if section_type == "prefix" and self.prefix_prompt_edit:
            self.prefix_prompt_edit.setText(text)
            self.prefix_prompt_edit.setReadOnly(False)
            self.prefix_prompt_edit.setStyleSheet(dynamic_styles.get('compact_textedit', ''))
        elif section_type == "postfix" and self.postfix_prompt_edit:
            self.postfix_prompt_edit.setText(text)
            self.postfix_prompt_edit.setReadOnly(False)
            self.postfix_prompt_edit.setStyleSheet(dynamic_styles.get('compact_textedit', ''))
        elif section_type == "negative" and self.negative_prompt_edit:
            self.negative_prompt_edit.setText(text)
            self.negative_prompt_edit.setReadOnly(False)
            self.negative_prompt_edit.setStyleSheet(dynamic_styles.get('compact_textedit', ''))

        print(f"Studio: Applied and unfroze {section_type}")

    def _on_detached_dialog_closed(self, section_type: str):
        """Handle detached dialog closed - unfreeze TextEdit"""
        dynamic_styles = get_dynamic_styles()

        # Unfreeze the TextEdit
        if section_type == "prefix" and self.prefix_prompt_edit:
            self.prefix_prompt_edit.setReadOnly(False)
            self.prefix_prompt_edit.setStyleSheet(dynamic_styles.get('compact_textedit', ''))
        elif section_type == "postfix" and self.postfix_prompt_edit:
            self.postfix_prompt_edit.setReadOnly(False)
            self.postfix_prompt_edit.setStyleSheet(dynamic_styles.get('compact_textedit', ''))
        elif section_type == "negative" and self.negative_prompt_edit:
            self.negative_prompt_edit.setReadOnly(False)
            self.negative_prompt_edit.setStyleSheet(dynamic_styles.get('compact_textedit', ''))

        if section_type in self.detached_dialogs:
            del self.detached_dialogs[section_type]
        print(f"Studio: {section_type} window closed, TextEdit unfrozen")

    # === Bottom panel handlers ===
    def _on_reset_frames_clicked(self):
        """Reset all frames but keep prompt settings"""
        if not self.frame_manager:
            return

        from ui.theme import show_question
        if show_question(
            self.widget, "Reset Frames",
            "Reset all frames? (Prefix, Postfix, Negative Prompt will be kept)"
        ):
            self.frame_manager.reset_all_frames()
            self._update_frame_count_label()
            self._update_start_button()
            print("Studio: All frames reset")

    def _on_global_resolution_changed(self, resolution: str):
        """Apply resolution to all frames"""
        if not self.frame_manager:
            return

        for frame in self.frame_manager.frames:
            frame.set_resolution(resolution)

        print(f"Studio: Global resolution set to {resolution}")

    def _on_open_presets_clicked(self):
        """Open event presets using OpenPresetDialog.
        TODO(web-dialog): 원래 OpenPresetDialog.exec() — Web Shell 패널로 재구현 필요."""
        print("[Dialog/SKIPPED] OpenPresetDialog 차단 — Web Shell 재구현 예정")

    def _apply_preset_data(self, preset_data: dict, load_mode: str = OpenPresetDialog.LOAD_ALL):
        """Apply loaded preset data to Studio Tab based on load mode"""
        if not self.frame_manager:
            return

        # Apply global prompts (only if load_mode is ALL or GLOBAL_ONLY)
        if load_mode in (OpenPresetDialog.LOAD_ALL, OpenPresetDialog.LOAD_GLOBAL_ONLY):
            global_prompts = preset_data.get('global_prompts', {})
            if self.prefix_prompt_edit:
                self.prefix_prompt_edit.setText(global_prompts.get('prefix_prompt', ''))
            if self.postfix_prompt_edit:
                self.postfix_prompt_edit.setText(global_prompts.get('postfix_prompt', ''))
            if self.negative_prompt_edit:
                self.negative_prompt_edit.setText(global_prompts.get('negative_prompt', ''))

        # Apply frame data (only if load_mode is ALL or EVENTS_ONLY)
        if load_mode in (OpenPresetDialog.LOAD_ALL, OpenPresetDialog.LOAD_EVENTS_ONLY):
            frames_data = preset_data.get('frames', [])
            for frame_entry in frames_data:
                index = frame_entry.get('index', 0)
                prompt_data = frame_entry.get('prompt_data', {})

                if 0 <= index < len(self.frame_manager.frames):
                    self.frame_manager.frames[index].set_prompt_data(prompt_data)
                    if 'resolution' in prompt_data:
                        self.frame_manager.frames[index].set_resolution(prompt_data['resolution'])

        self._update_frame_count_label()
        self._update_start_button()

        # Log what was loaded
        mode_names = {
            OpenPresetDialog.LOAD_ALL: "all data",
            OpenPresetDialog.LOAD_EVENTS_ONLY: "events only",
            OpenPresetDialog.LOAD_GLOBAL_ONLY: "global prompts only"
        }
        print(f"Studio: Preset loaded ({mode_names.get(load_mode, 'unknown')})")

    def _on_save_presets_clicked(self):
        """Save current event presets using SavePresetDialog"""
        if not self.frame_manager:
            return

        # Collect frame data and images
        frames_data = []
        images = []

        for frame in self.frame_manager.frames:
            frames_data.append(frame.get_prompt_data())

            # Get current PIL image if available
            pil_image = frame.get_current_pil_image() if frame.get_stack_count() > 0 else None
            images.append((frame.index, pil_image))

        # Collect global prompts
        global_prompts = {
            'prefix_prompt': self.prefix_prompt_edit.toPlainText() if self.prefix_prompt_edit else '',
            'postfix_prompt': self.postfix_prompt_edit.toPlainText() if self.postfix_prompt_edit else '',
            'negative_prompt': self.negative_prompt_edit.toPlainText() if self.negative_prompt_edit else ''
        }

        # Show save dialog
        # TODO(web-dialog): 원래 SavePresetDialog.exec() — Web Shell 패널로 재구현 필요.
        print("[Dialog/SKIPPED] SavePresetDialog 차단 — Web Shell 재구현 예정")
        return

    def _on_export_views_clicked(self):
        """Export generated images as a grid image

        In wildcard mode, only exports images from currently visible frames.
        """
        if not self.frame_manager:
            return

        # Collect images from visible frames only
        images = []
        for frame in self.frame_manager.frames:
            # Skip hidden frames (in wildcard mode, only visible frames are exported)
            if frame.isHidden():
                continue

            if frame.get_stack_count() > 0:
                pil_image = frame.get_current_pil_image()
                if pil_image:
                    images.append((frame.index, pil_image))

        if not images:
            # TODO(web-dialog): 원래 QMessageBox.warning — Web Shell 토스트.
            print("[Dialog/WARN] Warning: No images to export.")
            return

        # TODO(web-dialog): 원래 ExportViewsDialog.exec() — Web Shell 패널로 재구현 필요.
        print("[Dialog/SKIPPED] ExportViewsDialog 차단 — Web Shell 재구현 예정")

    def _on_events_clicked(self):
        """Open batch event editor dialog.
        TODO(web-dialog): 원래 EventsDialog.exec() — Web Shell 패널로 재구현 필요."""
        print("[Dialog/SKIPPED] EventsDialog 차단 — Web Shell 재구현 예정")
        self._update_start_button()

    def _lock_frame_buttons(self):
        """Lock all frame buttons while EventsDialog is open"""
        if not self.frame_manager:
            return

        for frame in self.frame_manager.frames:
            # Disable buttons that could cause sync issues
            if hasattr(frame, 'prompt_btn'):
                frame.prompt_btn.setEnabled(False)
            if hasattr(frame, 'delete_btn'):
                frame.delete_btn.setEnabled(False)
            if hasattr(frame, 'order_btn'):
                frame.order_btn.setEnabled(False)
            if hasattr(frame, 'resolution_combo'):
                frame.resolution_combo.setEnabled(False)

        # Also disable bottom panel buttons that modify frames
        if hasattr(self, 'add_frame_btn') and self.add_frame_btn:
            self.add_frame_btn.setEnabled(False)
        if hasattr(self, 'reset_frames_btn') and self.reset_frames_btn:
            self.reset_frames_btn.setEnabled(False)

        print("Studio: Frame buttons locked for batch editing")

    def _unlock_frame_buttons(self):
        """Unlock all frame buttons after EventsDialog closes"""
        if not self.frame_manager:
            return

        for frame in self.frame_manager.frames:
            # Re-enable buttons
            if hasattr(frame, 'prompt_btn'):
                frame.prompt_btn.setEnabled(True)
            if hasattr(frame, 'delete_btn'):
                frame.delete_btn.setEnabled(True)
            # Note: order_btn and expand_btn remain disabled as they are TODO
            if hasattr(frame, 'resolution_combo'):
                frame.resolution_combo.setEnabled(True)

        # Re-enable bottom panel buttons
        if hasattr(self, 'add_frame_btn') and self.add_frame_btn:
            self.add_frame_btn.setEnabled(True)
        if hasattr(self, 'reset_frames_btn') and self.reset_frames_btn:
            self.reset_frames_btn.setEnabled(True)

        print("Studio: Frame buttons unlocked")

    # === Helper methods ===
    def _show_styled_message(self, title: str, text: str, icon=QMessageBox.Icon.Information):
        """TODO(web-dialog): 원래 dark-themed QMessageBox.exec() — Web Shell 토스트로 재구현 필요."""
        print(f"[Dialog] {title}: {text}")

    def _show_styled_question(self, title: str, text: str) -> bool:
        """TODO(web-dialog): 원래 dark-themed QMessageBox(Yes/No).exec() — Web Shell confirm 모달로 재구현 필요.
        안전 기본값으로 항상 False 반환 (destructive 동작 차단)."""
        print(f"[Dialog/CONFIRM(skipped→No)] {title}: {text}")
        return False

    # === Wildcard analyzer methods ===
    # === New Wildcard Selector Methods ===
    def _on_wc1_clicked(self):
        """Open wildcard selector for WC1"""
        try:
            from tabs.studio.dialogs.wildcard_selector_dialog_simple import WildcardSelectorDialogSimple
            from core.wildcard_manager import WildcardManager
        except ImportError as e:
            self._show_styled_message("Error", f"Import error: {e}", QMessageBox.Icon.Critical)
            return

        # Get wildcard manager
        wildcard_manager = None
        if self.app_context and hasattr(self.app_context, 'wildcard_manager'):
            wildcard_manager = self.app_context.wildcard_manager
        if not wildcard_manager:
            wildcard_manager = WildcardManager()

        # Create selector dialog
        dialog = WildcardSelectorDialogSimple(wildcard_manager, 0, self.widget)

        # Connect signal
        def on_selected(wc_name, wc_items):
            self.selected_wc1 = (wc_name, wc_items)
            self.wc1_input.setText(f"{wc_name} ({len(wc_items)} items)")
            print(f"WC1 selected: {wc_name} ({len(wc_items)} items)")
            self._update_assign_button()

        dialog.wildcard_selected.connect(on_selected)
        # TODO(web-dialog): 원래 WildcardSelectorDialogSimple.exec() — Web Shell 패널로 재구현 필요.
        print("[Dialog/SKIPPED] WildcardSelectorDialogSimple (WC1) 차단 — Web Shell 재구현 예정")

    def _on_wc2_clicked(self):
        """Open wildcard selector for WC2"""
        try:
            from tabs.studio.dialogs.wildcard_selector_dialog_simple import WildcardSelectorDialogSimple
            from core.wildcard_manager import WildcardManager
        except ImportError as e:
            self._show_styled_message("Error", f"Import error: {e}", QMessageBox.Icon.Critical)
            return

        # Get wildcard manager
        wildcard_manager = None
        if self.app_context and hasattr(self.app_context, 'wildcard_manager'):
            wildcard_manager = self.app_context.wildcard_manager
        if not wildcard_manager:
            wildcard_manager = WildcardManager()

        # Create selector dialog
        dialog = WildcardSelectorDialogSimple(wildcard_manager, 0, self.widget)

        # Connect signal
        def on_selected(wc_name, wc_items):
            self.selected_wc2 = (wc_name, wc_items)
            self.wc2_input.setText(f"{wc_name} ({len(wc_items)} items)")
            print(f"WC2 selected: {wc_name} ({len(wc_items)} items)")
            self._update_assign_button()

        dialog.wildcard_selected.connect(on_selected)
        # TODO(web-dialog): 원래 WildcardSelectorDialogSimple.exec() — Web Shell 패널로 재구현 필요.
        print("[Dialog/SKIPPED] WildcardSelectorDialogSimple (WC2) 차단 — Web Shell 재구현 예정")

    def _update_assign_button(self):
        """Enable ASSIGN button if at least one wildcard is selected"""
        if self.selected_wc1 or self.selected_wc2:
            self.assign_btn.setEnabled(True)
        else:
            self.assign_btn.setEnabled(False)

    def _on_assign_clicked(self):
        """Assign wildcards to frames"""
        if not self.selected_wc1 and not self.selected_wc2:
            self._show_styled_message("Warning", "Please select at least one wildcard first!", QMessageBox.Icon.Warning)
            return

        if not self.frame_manager:
            self._show_styled_message("Warning", "Frame manager not available!", QMessageBox.Icon.Warning)
            return

        # Single wildcard: use simple mode (no wildcard navigation)
        if (self.selected_wc1 and not self.selected_wc2) or (self.selected_wc2 and not self.selected_wc1):
            self._assign_single_wildcard()
        # Both wildcards selected: use 2D wildcard mode
        else:
            self._assign_dual_wildcards()

    def _assign_single_wildcard(self):
        """Assign single wildcard to frames (simple mode, no navigation)"""
        # Determine which wildcard is selected
        if self.selected_wc1:
            wc_name, wc_items = self.selected_wc1
        else:
            wc_name, wc_items = self.selected_wc2

        # Validate item count (max 9)
        if len(wc_items) > 9:
            self._show_styled_message(
                "Warning",
                f"Wildcard has {len(wc_items)} items. Maximum is 9.\nPlease select a smaller wildcard or manually reduce items.",
                QMessageBox.Icon.Warning
            )
            return

        # Assign each item to a frame
        for i, item in enumerate(wc_items):
            if i >= len(self.frame_manager.frames):
                break

            frame = self.frame_manager.frames[i]
            current_data = frame.get_prompt_data()
            current_data['prompt'] = item
            frame.set_prompt_data(current_data)

        self._show_styled_message(
            "Wildcard Assigned",
            f"Assigned {len(wc_items)} items from '{wc_name}' to frames.\n\n"
            f"Ready for generation!",
            QMessageBox.Icon.Information
        )

        self._update_start_button()
        print(f"Studio: Assigned single wildcard '{wc_name}' ({len(wc_items)} items) to frames")

    def _assign_dual_wildcards(self):
        """Assign dual wildcards to frames (2D wildcard mode with navigation)"""
        wc1_name, wc1_items = self.selected_wc1
        wc2_name, wc2_items = self.selected_wc2

        # Validate item counts (max 9 each)
        if len(wc1_items) > 9:
            self._show_styled_message(
                "Warning",
                f"WC1 has {len(wc1_items)} items. Maximum is 9.\nPlease select a smaller wildcard.",
                QMessageBox.Icon.Warning
            )
            return

        if len(wc2_items) > 9:
            self._show_styled_message(
                "Warning",
                f"WC2 has {len(wc2_items)} items. Maximum is 9.\nPlease select a smaller wildcard.",
                QMessageBox.Icon.Warning
            )
            return

        # Build prompt pattern
        prompt_pattern = f"__{wc1_name}__, __{wc2_name}__"

        # Enter wildcard mode
        success = self.frame_manager.enter_wildcard_mode(
            prompt_pattern,
            wc1_name,
            wc2_name,
            wc1_items,
            wc2_items
        )

        if success:
            # Show navigation panel
            if self.wildcard_nav_panel:
                self.wildcard_nav_panel.show()
                self._update_wildcard_nav_panel()

            # Apply red border to wildcard analyzer section
            if self.wildcard_analyzer_frame:
                self.wildcard_analyzer_frame.setStyleSheet(f"""
                    QFrame {{
                        background-color: {DARK_COLORS['bg_secondary']};
                        border: 2px solid #CC4444;
                        border-radius: 5px;
                    }}
                """)

            self._show_styled_message(
                "2D Wildcard Mode",
                f"Entered 2D wildcard mode:\n"
                f"WC1: {wc1_name} ({len(wc1_items)} items)\n"
                f"WC2: {wc2_name} ({len(wc2_items)} items)\n\n"
                f"Use navigation controls to browse pages.",
                QMessageBox.Icon.Information
            )
        else:
            self._show_styled_message(
                "Error",
                "Failed to enter wildcard mode.",
                QMessageBox.Icon.Critical
            )

    def _on_clear_clicked(self):
        """Clear wildcards and reset frames"""
        # Clear selections
        self.selected_wc1 = None
        self.selected_wc2 = None
        self.wc1_input.clear()
        self.wc2_input.clear()
        self.wc1_input.setPlaceholderText("Not selected")
        self.wc2_input.setPlaceholderText("Not selected")

        # Disable ASSIGN button
        self.assign_btn.setEnabled(False)

        # Exit wildcard mode if active
        if self.frame_manager and self.frame_manager.is_in_wildcard_mode():
            self.frame_manager.exit_wildcard_mode()

            # Hide navigation panel
            if self.wildcard_nav_panel:
                self.wildcard_nav_panel.hide()

        # Restore normal border to wildcard analyzer section
        if self.wildcard_analyzer_frame:
            self.wildcard_analyzer_frame.setStyleSheet(f"""
                QFrame {{
                    background-color: {DARK_COLORS['bg_secondary']};
                    border: 1px solid {DARK_COLORS['border']};
                    border-radius: 5px;
                }}
            """)

        # Clear all frames
        if self.frame_manager:
            for frame in self.frame_manager.frames:
                frame.reset()

        print("Wildcards and frames cleared")
        self._show_styled_message(
            "Cleared",
            "Wildcards and frames have been cleared.",
            QMessageBox.Icon.Information
        )

    def _on_auto_assign_clicked(self):
        """Auto-assign wildcard combinations to frames"""
        if not hasattr(self, '_last_analysis') or not self._last_analysis:
            self._show_styled_message("Warning", "Please analyze wildcards first!", QMessageBox.Icon.Warning)
            return

        if not self.frame_manager or not self.frame_manager.frames:
            self._show_styled_message("Warning", "No frames available!", QMessageBox.Icon.Warning)
            return

        # Get analysis data
        prompt_pattern = self._last_analysis['prompt']
        total_combinations = self._last_analysis['total_combinations']

        frame_count = len(self.frame_manager.frames)

        # Confirm with user
        confirm_text = (
            f"This will assign wildcard combinations to {frame_count} frame(s).\n\n"
            f"Total combinations available: {total_combinations:,}\n"
            f"Frames: {frame_count}\n\n"
            f"Each frame will get a sequential wildcard combination.\n"
            f"Continue?"
        )
        if not self._show_styled_question("Auto-Assign Wildcards", confirm_text):
            return

        # Import necessary modules
        try:
            from core.wildcard_processor import WildcardProcessor
            from core.wildcard_manager import WildcardManager
            from core.prompt_context import PromptContext
            import pandas as pd
        except ImportError as e:
            self._show_styled_message("Error", f"Import error: {e}", QMessageBox.Icon.Critical)
            return

        # Get wildcard manager
        wildcard_manager = None
        if self.app_context and hasattr(self.app_context, 'wildcard_manager'):
            wildcard_manager = self.app_context.wildcard_manager

        if not wildcard_manager:
            wildcard_manager = WildcardManager()

        processor = WildcardProcessor(wildcard_manager)

        # Prepare tags for expansion
        # Split by comma and strip whitespace
        tags = [tag.strip() for tag in prompt_pattern.split(',') if tag.strip()]

        if not tags:
            self._show_styled_message("Warning", "No wildcard tags found in pattern!", QMessageBox.Icon.Warning)
            return

        # Assign to each frame
        assigned_count = 0
        for i, frame in enumerate(self.frame_manager.frames):
            if i >= total_combinations:
                # No more combinations available
                break

            # Create a fresh context for this iteration
            context = PromptContext(
                source_row=pd.Series(),
                settings={}
            )

            # Expand tags
            expanded_tags = processor.expand_tags(tags.copy(), context)

            # Join into prompt
            frame_prompt = ', '.join(expanded_tags)

            # Get current prompt data
            current_data = frame.get_prompt_data()

            # Update prompt field
            current_data['prompt'] = frame_prompt

            # Set back to frame
            frame.set_prompt_data(current_data)

            assigned_count += 1

        # Show success message
        self._show_styled_message(
            "Success",
            f"Successfully assigned {assigned_count} wildcard combinations to frames!",
            QMessageBox.Icon.Information
        )

        # Update UI
        self._update_start_button()

        print(f"Studio: Auto-assigned {assigned_count} wildcard combinations to frames")

    def _show_wildcard_selector_dialog(self, wildcards: list, prompt_pattern: str):
        """Show wildcard selector dialog for 2D mode

        Args:
            wildcards: List of WildcardInfo objects
            prompt_pattern: Original prompt pattern
        """
        # Convert wildcards to dict format for dialog
        wildcard_info_list = []
        for wc in wildcards:
            wildcard_info_list.append({
                'name': wc.name,
                'item_count': wc.item_count
            })

        total_combinations = self._last_analysis.get('total_combinations', 0)

        # Create and show dialog
        dialog = WildcardSelectorDialog(wildcard_info_list, total_combinations, self.widget)

        # Connect signals
        dialog.mode_1d_requested.connect(lambda: self._on_1d_mode_selected(dialog))
        dialog.mode_2d_requested.connect(lambda x, y, x_items, y_items: self._on_2d_mode_selected(x, y, x_items, y_items, prompt_pattern, dialog))

        # TODO(web-dialog): 원래 WildcardSelectorDialog.exec() — Web Shell 패널로 재구현 필요.
        print("[Dialog/SKIPPED] WildcardSelectorDialog (1D/2D 모드 선택) 차단 — Web Shell 재구현 예정")

    def _on_1d_mode_selected(self, dialog):
        """Handle 1D mode selection - use existing auto-assign logic"""
        dialog.accept()
        # Use existing 1D auto-assign
        self._on_auto_assign_clicked()

    def _on_2d_mode_selected(self, x_wildcard: str, y_wildcard: str, x_items: list, y_items: list, prompt_pattern: str, dialog):
        """Handle 2D mode selection - enter wildcard mode

        Args:
            x_wildcard: X-axis wildcard name
            y_wildcard: Y-axis wildcard name
            x_items: X-axis items list (up to 9 items)
            y_items: Y-axis items list (up to 9 items)
            prompt_pattern: Original prompt pattern
            dialog: Dialog to close
        """
        dialog.accept()

        if not self.frame_manager:
            return

        # Enter wildcard mode
        success = self.frame_manager.enter_wildcard_mode(
            prompt_pattern,
            x_wildcard,
            y_wildcard,
            x_items,
            y_items
        )

        if success:
            # Show navigation panel
            if self.wildcard_nav_panel:
                self.wildcard_nav_panel.show()
                self._update_wildcard_nav_panel()

            self._show_styled_message(
                "2D Mode Enabled",
                f"Entered 2D wildcard mode with:\n"
                f"X-Axis: {x_wildcard}\n"
                f"Y-Axis: {y_wildcard}\n\n"
                f"Use navigation controls to browse pages.",
                QMessageBox.Icon.Information
            )

            # Update UI
            self._update_start_button()
        else:
            self._show_styled_message(
                "Error",
                "Failed to enter 2D wildcard mode. Check console for details.",
                QMessageBox.Icon.Critical
            )

    def _on_wildcard_page_changed(self, delta: int):
        """Handle wildcard page navigation

        Args:
            delta: Page offset (-1=previous, +1=next)
        """
        if not self.frame_manager:
            return

        self.frame_manager.navigate_wildcard_page(delta)
        self._update_wildcard_nav_panel()

    def _on_wildcard_axis_swapped(self):
        """Handle wildcard axis swap request"""
        if not self.frame_manager:
            return

        self.frame_manager.swap_wildcard_axes()
        self._update_wildcard_nav_panel()

    def _on_exit_wildcard_mode(self):
        """Handle exit from wildcard mode"""
        if not self.frame_manager:
            return

        self.frame_manager.exit_wildcard_mode()

        # Hide navigation panel
        if self.wildcard_nav_panel:
            self.wildcard_nav_panel.hide()

        # Restore normal border to wildcard analyzer section
        if self.wildcard_analyzer_frame:
            self.wildcard_analyzer_frame.setStyleSheet(f"""
                QFrame {{
                    background-color: {DARK_COLORS['bg_secondary']};
                    border: 1px solid {DARK_COLORS['border']};
                    border-radius: 5px;
                }}
            """)

        self._show_styled_message(
            "Exited 2D Mode",
            "Returned to normal mode.",
            QMessageBox.Icon.Information
        )

    def _update_wildcard_nav_panel(self):
        """Update wildcard navigation panel with current state"""
        if not self.wildcard_nav_panel or not self.frame_manager:
            return

        state = self.frame_manager.wildcard_mode_state

        if not state.is_wildcard_mode:
            return

        # Get page and frame axis info
        page_axis_name = state.get_page_axis_name()
        frame_axis_name = state.get_frame_axis_name()
        current_page = state.current_page + 1  # Convert to 1-indexed
        total_pages = state.get_total_pages()
        current_item = state.get_current_page_item()
        frame_items = state.get_frame_items()

        # Update panel info
        self.wildcard_nav_panel.update_info(
            page_axis_name,
            frame_axis_name,
            current_page,
            total_pages,
            current_item,
            frame_items
        )

    # === Tab lifecycle ===
    def on_tab_activated(self):
        """Called when tab is activated"""
        self._update_start_button()
        self._update_frame_count_label()

    def cleanup(self):
        """Cleanup resources"""
        # Close any detached dialogs
        for dialog in self.detached_dialogs.values():
            try:
                dialog.close()
            except:
                pass
        self.detached_dialogs.clear()

        if self.app_context:
            try:
                self.app_context.unsubscribe("generation_completed_for_studio", self._on_image_generated)
            except:
                pass
            try:
                self.app_context.unsubscribe("generation_error_for_studio", self._on_generation_error)
            except:
                pass
