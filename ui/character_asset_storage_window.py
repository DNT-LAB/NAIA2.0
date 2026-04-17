"""Dedicated storage window for saved character assets."""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

from PIL import Image
from PIL.ImageQt import ImageQt
from PyQt6.QtCore import QEvent, Qt, QSize
from PyQt6.QtGui import QAction, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from ui.theme import DARK_COLORS
from utils.character_asset_storage import (
    CHARACTER_ASSET_IMAGE_DIR,
    ensure_character_asset_storage_dirs,
    get_legacy_character_asset_metadata_path,
    load_character_asset_metadata,
)


class CharacterAssetStorageItem(QFrame):
    """Single asset tile for the dedicated asset storage."""

    def __init__(self, file_hash: str, file_name: str, image_path: Path, app_context=None, parent=None):
        super().__init__(parent)
        self.file_hash = file_hash
        self.file_name = file_name
        self.image_path = image_path
        self.app_context = app_context

        self.setFixedSize(QSize(get_scaled_size(270), get_scaled_size(380)))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(f"""
            QFrame {{
                border: 1px solid #333;
                border-radius: {get_scaled_size(6)}px;
                background-color: #1a1a1a;
                padding: {get_scaled_size(4)}px;
            }}
            QFrame:hover {{
                border-color: {DARK_COLORS['accent_blue']};
                border-width: 2px;
                background-color: #222;
            }}
        """)

        self._setup_ui()
        self.installEventFilter(self)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(get_scaled_size(6))
        layout.setContentsMargins(get_scaled_size(6), get_scaled_size(6), get_scaled_size(6), get_scaled_size(6))

        self.image_label = QLabel()
        self.image_label.setFixedSize(get_scaled_size(256), get_scaled_size(334))
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("QLabel { border: 1px solid #444; background: #101010; }")
        layout.addWidget(self.image_label, alignment=Qt.AlignmentFlag.AlignCenter)

        hint_label = QLabel("더블클릭 적용")
        hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint_label.setStyleSheet(
            f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(12)}px;"
        )
        layout.addWidget(hint_label)

        self._load_image()

    def _load_image(self):
        try:
            image = Image.open(self.image_path)
            if image.mode != "RGBA":
                image = image.convert("RGBA")

            image.thumbnail((get_scaled_size(256), get_scaled_size(334)), Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", (get_scaled_size(256), get_scaled_size(334)), (16, 16, 16, 255))
            paste_x = (canvas.width - image.width) // 2
            paste_y = (canvas.height - image.height) // 2
            canvas.paste(image, (paste_x, paste_y), image)

            self.image_label.setPixmap(QPixmap.fromImage(ImageQt(canvas)))
            self.image_label.setText("")
        except Exception as exc:
            print(f"Failed to load asset image {self.image_path}: {exc}")
            self.image_label.setText("Failed to load")
            self.image_label.setStyleSheet("QLabel { border: 1px solid #444; background: #101010; color: #ff6666; }")

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.ContextMenu:
            self._show_context_menu(event.globalPos())
            return True
        return super().eventFilter(obj, event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._apply_asset()
        super().mouseDoubleClickEvent(event)

    def _show_context_menu(self, pos):
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                color: {DARK_COLORS['text_primary']};
            }}
            QMenu::item:selected {{
                background-color: {DARK_COLORS['accent_blue']};
            }}
        """)

        apply_action = QAction("적용", self)
        apply_action.triggered.connect(self._apply_asset)
        menu.addAction(apply_action)

        delete_action = QAction("파일 삭제", self)
        delete_action.triggered.connect(self._delete_asset)
        menu.addAction(delete_action)

        menu.exec(pos)

    def _apply_asset(self):
        metadata = load_character_asset_metadata(self.file_hash, self.image_path)
        character_prompt = (metadata or {}).get("character_prompt", "").strip()
        character_uc = (metadata or {}).get("character_uc", "").strip()

        if not character_prompt:
            QMessageBox.warning(self, "적용 실패", "에셋 메타데이터에서 캐릭터 프롬프트를 찾을 수 없습니다.")
            return

        character_module = None
        try:
            if self.app_context:
                character_module = self.app_context.middle_section_controller.get_module_instance("CharacterModule")
        except Exception as exc:
            print(f"Failed to get CharacterModule for asset apply: {exc}")

        if not character_module:
            QMessageBox.warning(self, "적용 실패", "CharacterModule을 찾을 수 없습니다.")
            return

        character_module.assign_c1(character_prompt, character_uc)

        main_window = getattr(self.app_context, "main_window", None) if self.app_context else None
        if main_window and hasattr(main_window, "apply_character_asset_reference_from_image_path"):
            try:
                main_window.apply_character_asset_reference_from_image_path(str(self.image_path))
            except Exception as exc:
                print(f"Failed to apply character asset reference from storage image: {exc}")

        self._close_storage_window()

    def _delete_asset(self):
        try:
            metadata_path = get_legacy_character_asset_metadata_path(self.file_hash)
            if self.image_path.exists():
                self.image_path.unlink()
            if metadata_path.exists():
                metadata_path.unlink()
            self._refresh_parent_window()
            self.deleteLater()
        except Exception as exc:
            print(f"Failed to delete character asset {self.image_path}: {exc}")

    def _refresh_parent_window(self):
        parent = self.parent()
        while parent:
            if isinstance(parent, CharacterAssetStorageWindow):
                parent.load_storage_items()
                break
            parent = parent.parent()

    def _close_storage_window(self):
        parent = self.parent()
        while parent:
            if isinstance(parent, CharacterAssetStorageWindow):
                parent.close()
                break
            parent = parent.parent()


class CharacterAssetStorageWindow(QDialog):
    """Dedicated storage window for saved character assets."""

    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app_context = app_context

        self.setWindowTitle("캐릭터 에셋 스토리지")
        self.setModal(False)
        self.setFixedSize(get_scaled_size(1420), get_scaled_size(720))
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {DARK_COLORS['bg_primary']};
            }}
            QScrollArea {{
                background-color: {DARK_COLORS['bg_primary']};
                border: none;
            }}
        """)

        self._setup_ui()
        self.load_storage_items()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(get_scaled_size(10))
        layout.setContentsMargins(get_scaled_size(12), get_scaled_size(12), get_scaled_size(12), get_scaled_size(12))

        title_layout = QHBoxLayout()
        title_layout.setSpacing(get_scaled_size(10))

        title_block = QVBoxLayout()
        title_block.setContentsMargins(0, 0, 0, 0)
        title_block.setSpacing(get_scaled_size(2))

        title_label = QLabel("캐릭터 에셋 스토리지")
        title_label.setStyleSheet(
            f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(24)}px; font-weight: bold;"
        )
        helper_label = QLabel("저장된 에셋을 더블클릭하면 C1 업데이트와 Comic Panel 적용을 함께 수행합니다.")
        helper_label.setStyleSheet(
            f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(12)}px;"
        )

        title_block.addWidget(title_label)
        title_block.addWidget(helper_label)
        title_layout.addLayout(title_block)
        title_layout.addStretch()

        folder_btn = QPushButton("폴더 열기")
        folder_btn.setFixedHeight(get_scaled_size(40))
        folder_btn.clicked.connect(self._open_storage_folder)
        title_layout.addWidget(folder_btn)

        layout.addLayout(title_layout)

        self.empty_label = QLabel("저장된 에셋이 없습니다.")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet(
            f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(14)}px;"
        )
        layout.addWidget(self.empty_label)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.viewport().setStyleSheet(f"background-color: {DARK_COLORS['bg_primary']};")

        self.container_widget = QWidget()
        self.container_widget.setStyleSheet(f"background-color: {DARK_COLORS['bg_primary']};")
        self.grid_layout = QGridLayout(self.container_widget)
        self.grid_layout.setSpacing(get_scaled_size(10))
        self.grid_layout.setContentsMargins(get_scaled_size(10), get_scaled_size(10), get_scaled_size(10), get_scaled_size(10))
        self.grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        scroll_area.setWidget(self.container_widget)
        layout.addWidget(scroll_area)

    def load_storage_items(self):
        ensure_character_asset_storage_dirs()

        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        image_files = []
        for ext in ("*.png", "*.jpg", "*.jpeg", "*.bmp", "*.gif", "*.webp"):
            image_files.extend(CHARACTER_ASSET_IMAGE_DIR.glob(ext))

        image_files = sorted(image_files, key=lambda file: file.stat().st_mtime, reverse=True)
        self.empty_label.setVisible(not image_files)

        max_cols = 5
        row = 0
        col = 0
        for image_file in image_files:
            try:
                item = CharacterAssetStorageItem(image_file.stem, image_file.name, image_file, self.app_context, self.container_widget)
                self.grid_layout.addWidget(item, row, col)
                col += 1
                if col >= max_cols:
                    col = 0
                    row += 1
            except Exception as exc:
                print(f"Failed to load character asset {image_file}: {exc}")

    def _open_storage_folder(self):
        ensure_character_asset_storage_dirs()
        folder_path = CHARACTER_ASSET_IMAGE_DIR.resolve()

        try:
            system = platform.system()
            if system == "Windows":
                os.startfile(folder_path)
            elif system == "Darwin":
                subprocess.run(["open", str(folder_path)])
            else:
                subprocess.run(["xdg-open", str(folder_path)])
        except Exception as exc:
            print(f"Failed to open character asset storage folder: {exc}")
