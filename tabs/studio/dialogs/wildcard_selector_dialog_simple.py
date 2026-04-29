"""
WildcardSelectorDialogSimple - Simplified 2D wildcard selector with tree view
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QWidget, QTreeWidget, QTreeWidgetItem, QGroupBox,
    QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from ui.theme import DARK_COLORS, get_dynamic_styles
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
import os


class WildcardSelectorDialogSimple(QDialog):
    """Simplified wildcard selector with tree view for single wildcard selection"""

    # Signal: (wildcard_name, items_list)
    wildcard_selected = pyqtSignal(str, list)

    def __init__(self, wildcard_manager, total_combinations: int, parent=None):
        """
        Args:
            wildcard_manager: WildcardManager instance to access wildcard files
            total_combinations: Total number of combinations (not used in simple version)
            parent: Parent widget
        """
        super().__init__(parent)
        self.wildcard_manager = wildcard_manager
        self.total_combinations = total_combinations

        # Selected wildcard
        self.selected_wc1 = None  # (name, items_list) - kept for compatibility

        # Current file path
        self.wc1_file_path = None

        self.setWindowTitle("Select Wildcard")
        self.setModal(True)
        self.resize(get_scaled_size(1200), get_scaled_size(650))

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

        dynamic_styles = get_dynamic_styles()

        # Title
        title_label = QLabel("🎲 Select Wildcard")
        title_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(18)}px;
                font-weight: bold;
            }}
        """)
        layout.addWidget(title_label)

        # Info text
        info_text = QLabel("Select a wildcard from the tree")
        info_text.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(13)}px;
            }}
        """)
        layout.addWidget(info_text)

        # Main content: Tree + Selected wildcard display + Apply wildcard (horizontal 3-column)
        main_content_layout = QHBoxLayout()
        main_content_layout.setSpacing(get_scaled_size(15))

        # Left: Tree view (Fixed size)
        tree_group = QGroupBox("📁 Wildcard Files")
        tree_group.setFixedWidth(get_scaled_size(250))
        tree_group.setStyleSheet(f"""
            QGroupBox {{
                font-size: {get_scaled_font_size(16)}px;
                font-weight: bold;
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(5)}px;
                padding-top: {get_scaled_size(20)}px;
                margin-top: {get_scaled_size(10)}px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: {get_scaled_size(10)}px;
                padding: 0 {get_scaled_size(5)}px;
            }}
        """)
        tree_layout = QVBoxLayout(tree_group)

        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderHidden(True)
        self.tree_widget.setStyleSheet(f"""
            QTreeWidget {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(5)}px;
                font-size: {get_scaled_font_size(14)}px;
                color: {DARK_COLORS['text_primary']};
            }}
            QTreeWidget::item {{
                padding: {get_scaled_size(4)}px;
                min-height: {get_scaled_size(22)}px;
            }}
            QTreeWidget::item:selected {{
                background-color: {DARK_COLORS['accent_blue']};
            }}
            QTreeWidget::item:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
        """)
        self.tree_widget.itemClicked.connect(self._on_tree_item_clicked)
        tree_layout.addWidget(self.tree_widget)

        # Load tree
        self._load_wildcard_tree()

        main_content_layout.addWidget(tree_group)

        # Middle: Selected wildcard display (Read-only, 3.6x size - 1.8x larger than before)
        wc1_group = self._create_wc_display_group("Selected Wildcard", is_wc1=True, editable=False)
        main_content_layout.addWidget(wc1_group, 36)

        # Right: Apply wildcard (Editable, 1.5x size)
        apply_group = self._create_wc_display_group("Apply Wildcard", is_wc1=False, editable=True)
        main_content_layout.addWidget(apply_group, 15)

        layout.addLayout(main_content_layout, 1)

        # Bottom buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        # Apply button
        apply_btn = QPushButton("Apply")
        apply_btn.setFixedWidth(get_scaled_size(120))
        apply_btn.setStyleSheet(f"""
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
        apply_btn.clicked.connect(self._on_apply_clicked)
        button_layout.addWidget(apply_btn)

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

        layout.addLayout(button_layout)

    def _create_wc_display_group(self, title: str, is_wc1: bool, editable: bool = False) -> QGroupBox:
        """Create wildcard display group

        Args:
            title: Group box title
            is_wc1: True for Selected Wildcard, False for Apply Wildcard
            editable: True for editable TextEdit, False for read-only
        """
        group = QGroupBox(title)
        group.setStyleSheet(f"""
            QGroupBox {{
                font-size: {get_scaled_font_size(16)}px;
                font-weight: bold;
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(5)}px;
                padding-top: {get_scaled_size(20)}px;
                margin-top: {get_scaled_size(10)}px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: {get_scaled_size(10)}px;
                padding: 0 {get_scaled_size(5)}px;
            }}
        """)

        layout = QVBoxLayout(group)
        layout.setSpacing(get_scaled_size(8))

        # File path label (only for Selected Wildcard)
        if is_wc1:
            path_label = QLabel("Not selected")
            path_label.setStyleSheet(f"""
                QLabel {{
                    font-size: {get_scaled_font_size(13)}px;
                    color: {DARK_COLORS['text_secondary']};
                    padding: {get_scaled_size(5)}px;
                }}
            """)
            layout.addWidget(path_label)

        # Content display
        content_edit = QTextEdit()
        content_edit.setStyleSheet(get_dynamic_styles()['compact_textedit'])
        content_edit.setReadOnly(not editable)

        if is_wc1:
            content_edit.setPlaceholderText("Select a wildcard file from the tree...")
        else:
            # Apply Wildcard - editable
            content_edit.setPlaceholderText(
                "와일드카드의 line 수가 9를 초과하는 경우, 사용하실 와일드카드를 최대 9줄 까지 "
                "직접 드래그 후 Ctrl + C 로 복사하여 이 영역에 Ctrl + V 합니다."
            )
            # Disable autocomplete for Apply Wildcard
            content_edit.setProperty("autocomplete_ignore", True)

        layout.addWidget(content_edit, 1)

        # Clear button
        clear_btn = QPushButton("Clear")
        clear_btn.setFixedHeight(get_scaled_size(28))
        clear_btn.setStyleSheet(f"""
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
        """)
        if is_wc1:
            clear_btn.clicked.connect(self._clear_wc1)
        else:
            clear_btn.clicked.connect(self._clear_apply)
        layout.addWidget(clear_btn)

        # Store references
        if is_wc1:
            self.wc1_path_label = path_label
            self.wc1_content_edit = content_edit
            self.wc1_clear_btn = clear_btn
        else:
            # Apply Wildcard
            self.apply_content_edit = content_edit
            self.apply_clear_btn = clear_btn

        return group

    def _load_wildcard_tree(self):
        """Load wildcard tree from wildcard_manager"""
        self.tree_widget.clear()

        # Root item
        root_item = QTreeWidgetItem(self.tree_widget, ["📂 wildcards"])
        root_item.setExpanded(True)

        # Get wildcards directory
        wildcards_dir = self.wildcard_manager.wildcards_dir
        if not os.path.exists(wildcards_dir):
            os.makedirs(wildcards_dir)

        # Build tree structure
        self._add_directory_to_tree(wildcards_dir, root_item)

    def _add_directory_to_tree(self, dir_path: str, parent_item: QTreeWidgetItem):
        """Add directory to tree"""
        try:
            for item_name in os.listdir(dir_path):
                item_path = os.path.join(dir_path, item_name)

                if os.path.isdir(item_path):
                    # Folder
                    folder_item = QTreeWidgetItem(parent_item, [f"📁 {item_name}"])
                    folder_item.setData(0, Qt.ItemDataRole.UserRole, item_path)
                    self._add_directory_to_tree(item_path, folder_item)

                elif item_name.endswith('.txt'):
                    # Text file
                    file_item = QTreeWidgetItem(parent_item, [f"📄 {item_name}"])
                    file_item.setData(0, Qt.ItemDataRole.UserRole, item_path)

                    # Show line count
                    try:
                        with open(item_path, 'r', encoding='utf-8', errors='ignore') as f:
                            line_count = sum(1 for line in f if line.strip())
                        file_item.setText(0, f"📄 {item_name} ({line_count})")
                    except:
                        pass

        except Exception as e:
            print(f"Error loading directory: {e}")

    def _on_tree_item_clicked(self, item: QTreeWidgetItem, column: int):
        """Handle tree item click - always load to WC1"""
        file_path = item.data(0, Qt.ItemDataRole.UserRole)

        # Only handle file clicks
        if file_path and os.path.isfile(file_path):
            self._load_file_to_wc1(file_path)

    def _load_file_to_wc1(self, file_path: str):
        """Load file to selected wildcard"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            # Get items (non-empty lines)
            items = [line.strip() for line in content.split('\n') if line.strip()]

            # Get wildcard name (relative path without .txt)
            relative_path = os.path.relpath(file_path, self.wildcard_manager.wildcards_dir)
            wildcard_name = relative_path.replace('\\', '/').replace('.txt', '')

            # Update selected wildcard
            self.selected_wc1 = (wildcard_name, items)
            self.wc1_file_path = file_path
            self.wc1_path_label.setText(f"📄 {wildcard_name} ({len(items)} items)")
            self.wc1_content_edit.setText(content)

            # Auto-fill Apply Wildcard based on item count
            if len(items) < 10:
                # Less than 10 items: auto-fill Apply Wildcard
                self.apply_content_edit.setText(content)
                print(f"Wildcard selected: {wildcard_name} ({len(items)} items) - Auto-filled to Apply Wildcard")
            else:
                # 10 or more items: clear Apply Wildcard (user must manually paste)
                self.apply_content_edit.clear()
                print(f"Wildcard selected: {wildcard_name} ({len(items)} items) - Please manually paste up to 9 lines")

        except Exception as e:
            print(f"Error loading file: {e}")

    def _clear_wc1(self):
        """Clear wildcard selection"""
        self.selected_wc1 = None
        self.wc1_file_path = None
        self.wc1_path_label.setText("Not selected")
        self.wc1_content_edit.clear()
        print("Wildcard cleared")

    def _clear_apply(self):
        """Clear Apply Wildcard content"""
        self.apply_content_edit.clear()
        print("Apply Wildcard cleared")

    def _on_apply_clicked(self):
        """Handle Apply button click"""
        # Get Apply Wildcard content (what user will actually use)
        apply_content = self.apply_content_edit.toPlainText().strip()

        if not apply_content:
            self._show_warning("Warning", "Apply Wildcard is empty.\nPlease fill in the wildcard items to use.")
            return

        # Parse Apply Wildcard items
        apply_items = [line.strip() for line in apply_content.split('\n') if line.strip()]

        # Check item count (max 9)
        if len(apply_items) > 9:
            self._show_warning(
                "Warning",
                f"Apply Wildcard has {len(apply_items)} items. Maximum is 9.\n"
                f"Please reduce to 9 lines or less."
            )
            return

        # Determine wildcard name
        if self.selected_wc1:
            # Use selected wildcard name
            wc_name, _ = self.selected_wc1
        else:
            # No wildcard selected, use default name
            wc_name = "custom"
            print("No wildcard file selected. Using custom wildcard name.")

        # Emit signal with Apply Wildcard items
        self.wildcard_selected.emit(wc_name, apply_items)
        self.accept()

    def _show_warning(self, title: str, message: str):
        """Show warning message with dark theme styling"""
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Warning)
        msg_box.setWindowTitle(title)
        msg_box.setText(message)

        # Apply dark theme styling
        msg_box.setStyleSheet(f"""
            QMessageBox {{
                background-color: {DARK_COLORS['bg_primary']};
            }}
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(14)}px;
            }}
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 6px 20px;
                font-size: {get_scaled_font_size(13)}px;
                min-width: 80px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
        """)

        # TODO(web-dialog): 원래 QMessageBox.exec() — Web Shell 토스트로 재구현 필요.
        title = msg_box.windowTitle() if hasattr(msg_box, 'windowTitle') else 'Message'
        text = msg_box.text() if hasattr(msg_box, 'text') else ''
        print(f"[Dialog] {title}: {text}")
