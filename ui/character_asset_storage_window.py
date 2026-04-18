"""Dedicated storage window for saved character assets.

MVP structure:
    QMainWindow
      └─ QTabWidget
          ├─ Characters tab   [grid | (zoomed preview + variation strip)]
          └─ Variations tab   [header + actions + generated results stack]

Selection is a single click. C1 prompt apply / reference-inset apply is
explicit — either via right-click context menu or via action buttons next to
the zoomed preview. Variations tab drives the main img2img panel (reference
inset + forced "mask-only save") and subscribes to
`generation_completed_for_variations` to collect results for saving under the
selected character.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
from pathlib import Path
from typing import Optional

from PIL import Image
from PIL.ImageQt import ImageQt
import io

from PyQt6.QtCore import QEvent, QObject, Qt, QSize, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from ui.theme import DARK_COLORS, DARK_STYLES
from utils.character_asset_storage import (
    CHARACTER_ASSET_CHARACTERS_DIR,
    CharacterRecord,
    delete_character,
    delete_variation,
    ensure_character_asset_storage_dirs,
    list_character_variations,
    list_characters,
    load_character_asset_metadata,
    migrate_legacy_flat_layout,
    promote_variation_to_primary,
    save_character_variation,
)
from utils.reference_inpaint_preprocess import prepare_variation_inpaint_canvas


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _load_pixmap_for_label(image_path: Path, target_w: int, target_h: int) -> Optional[QPixmap]:
    """Open an image and return a centered pixmap padded to exact size."""
    try:
        image = Image.open(image_path)
        if image.mode != "RGBA":
            image = image.convert("RGBA")
        image.thumbnail((target_w, target_h), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (target_w, target_h), (16, 16, 16, 255))
        canvas.paste(image, ((target_w - image.width) // 2, (target_h - image.height) // 2), image)
        return QPixmap.fromImage(ImageQt(canvas))
    except Exception as exc:
        print(f"Failed to load pixmap for {image_path}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Character card (grid tile on Characters tab)
# ---------------------------------------------------------------------------


class CharacterCard(QFrame):
    """Single character tile showing its primary image."""

    clicked = pyqtSignal(str)
    context_requested = pyqtSignal(str, object)  # character_id, globalPos

    def __init__(self, record: CharacterRecord, parent=None):
        super().__init__(parent)
        self.record = record
        self._selected = False

        self.setFixedSize(QSize(get_scaled_size(280), get_scaled_size(400)))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_style(False)
        self._setup_ui()
        self.installEventFilter(self)

    def _apply_style(self, selected: bool):
        border = DARK_COLORS['accent_blue'] if selected else "#333"
        bg = "#1f2a36" if selected else "#1a1a1a"
        self.setStyleSheet(f"""
            QFrame {{
                border: 2px solid {border};
                border-radius: {get_scaled_size(6)}px;
                background-color: {bg};
                padding: {get_scaled_size(4)}px;
            }}
            QFrame:hover {{
                border-color: {DARK_COLORS['accent_blue']};
                background-color: #222;
            }}
        """)

    def set_selected(self, selected: bool):
        self._selected = selected
        self._apply_style(selected)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(get_scaled_size(6), get_scaled_size(6), get_scaled_size(6), get_scaled_size(6))
        layout.setSpacing(get_scaled_size(4))

        image_label = QLabel()
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_w = get_scaled_size(264)
        image_h = get_scaled_size(340)
        image_label.setFixedSize(image_w, image_h)
        image_label.setStyleSheet("QLabel { border: 1px solid #444; background: #101010; }")
        pixmap = _load_pixmap_for_label(self.record.primary_path, image_w, image_h)
        if pixmap is not None:
            image_label.setPixmap(pixmap)
        else:
            image_label.setText("Failed to load")
            image_label.setStyleSheet("QLabel { border: 1px solid #444; background: #101010; color: #ff6666; }")
        layout.addWidget(image_label)

        info_label = QLabel(f"variations: {self.record.variation_count}")
        info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_label.setStyleSheet(
            f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(11)}px; border: none;"
        )
        layout.addWidget(info_label)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.record.character_id)
        super().mousePressEvent(event)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.ContextMenu:
            self.context_requested.emit(self.record.character_id, event.globalPos())
            return True
        return super().eventFilter(obj, event)


# ---------------------------------------------------------------------------
# Variation thumbnail (right strip on Characters tab + generated result cards)
# ---------------------------------------------------------------------------


class VariationTile(QFrame):
    """Small thumbnail for a stored variation under a character."""

    clicked = pyqtSignal(object)  # Path
    context_requested = pyqtSignal(object, object)  # Path, globalPos

    def __init__(self, image_path: Path, parent=None):
        super().__init__(parent)
        self.image_path = image_path
        self._selected = False
        self.setFixedSize(get_scaled_size(100), get_scaled_size(138))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_style(False)
        self._setup_ui()
        self.installEventFilter(self)

    def _apply_style(self, selected: bool):
        border = DARK_COLORS['accent_blue'] if selected else "#333"
        bg = "#1f2a36" if selected else "#1a1a1a"
        self.setStyleSheet(f"""
            QFrame {{
                border: 2px solid {border};
                border-radius: {get_scaled_size(5)}px;
                background-color: {bg};
            }}
            QFrame:hover {{
                border-color: {DARK_COLORS['accent_blue']};
            }}
        """)

    def set_selected(self, selected: bool):
        self._selected = selected
        self._apply_style(selected)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(get_scaled_size(4), get_scaled_size(4), get_scaled_size(4), get_scaled_size(4))
        layout.setSpacing(0)

        image_label = QLabel()
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_w = get_scaled_size(88)
        image_h = get_scaled_size(124)
        image_label.setFixedSize(image_w, image_h)
        image_label.setStyleSheet("QLabel { border: none; background: #101010; }")
        pixmap = _load_pixmap_for_label(self.image_path, image_w, image_h)
        if pixmap is not None:
            image_label.setPixmap(pixmap)
        layout.addWidget(image_label)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.image_path)
        super().mousePressEvent(event)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.ContextMenu:
            self.context_requested.emit(self.image_path, event.globalPos())
            return True
        return super().eventFilter(obj, event)


class VariationResultCard(QFrame):
    """Selectable small thumbnail for a generated variation.

    The actual Save/Discard actions live in the central preview pane so a
    single click here only switches which result is expanded.
    """

    clicked = pyqtSignal(object)  # VariationResultCard

    CARD_WIDTH = 110
    CARD_HEIGHT = 154
    IMAGE_WIDTH = 100
    IMAGE_HEIGHT = 140

    def __init__(self, result: dict, parent=None):
        super().__init__(parent)
        self.result = result
        self._selected = False
        self.setFixedSize(get_scaled_size(self.CARD_WIDTH), get_scaled_size(self.CARD_HEIGHT))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_style(False)
        self._setup_ui()

    def _apply_style(self, selected: bool):
        border = DARK_COLORS['accent_blue'] if selected else "#333"
        bg = "#1f2a36" if selected else "#1a1a1a"
        self.setStyleSheet(f"""
            QFrame {{
                border: 2px solid {border};
                border-radius: {get_scaled_size(6)}px;
                background-color: {bg};
            }}
            QFrame:hover {{
                border-color: {DARK_COLORS['accent_blue']};
            }}
        """)

    def set_selected(self, selected: bool):
        self._selected = selected
        self._apply_style(selected)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(get_scaled_size(4), get_scaled_size(4), get_scaled_size(4), get_scaled_size(4))
        layout.setSpacing(0)

        image_label = QLabel()
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_w = get_scaled_size(self.IMAGE_WIDTH)
        image_h = get_scaled_size(self.IMAGE_HEIGHT)
        image_label.setFixedSize(image_w, image_h)
        image_label.setStyleSheet("QLabel { border: none; background: #101010; }")

        image = self.result.get("image")
        if image is not None:
            try:
                preview = image.copy()
                if preview.mode != "RGBA":
                    preview = preview.convert("RGBA")
                preview.thumbnail((image_w, image_h), Image.Resampling.LANCZOS)
                image_label.setPixmap(QPixmap.fromImage(ImageQt(preview)))
            except Exception as exc:
                print(f"Failed to render variation thumbnail: {exc}")
        layout.addWidget(image_label, alignment=Qt.AlignmentFlag.AlignCenter)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self)
        super().mousePressEvent(event)


# ---------------------------------------------------------------------------
# Characters tab
# ---------------------------------------------------------------------------


class CharactersTab(QWidget):
    """Tab 1: character grid on the left, zoomed preview + variation strip on the right."""

    variations_requested = pyqtSignal(str)  # character_id → request to switch to Variations tab

    def __init__(self, window: "CharacterAssetStorageWindow", parent=None):
        super().__init__(parent)
        self.window_ref = window
        self.app_context = window.app_context

        self._selected_character_id: Optional[str] = None
        self._selected_variation_path: Optional[Path] = None
        self._character_cards: list[CharacterCard] = []
        self._variation_tiles: list[VariationTile] = []

        self._setup_ui()

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(get_scaled_size(12), get_scaled_size(12), get_scaled_size(12), get_scaled_size(12))
        outer.setSpacing(get_scaled_size(10))

        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(get_scaled_size(12))

        # --- Column 1: character grid (2 cols fixed) --------------------
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(get_scaled_size(6))

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title = QLabel("캐릭터")
        title.setStyleSheet(
            f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(18)}px; font-weight: 700;"
        )
        title_row.addWidget(title)
        title_row.addStretch()
        folder_btn = QPushButton("폴더 열기")
        folder_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        folder_btn.setFixedHeight(get_scaled_size(32))
        folder_btn.clicked.connect(self._open_storage_folder)
        title_row.addWidget(folder_btn)
        left_layout.addLayout(title_row)

        self.empty_label = QLabel("저장된 에셋이 없습니다.")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet(
            f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(13)}px;"
        )
        left_layout.addWidget(self.empty_label)

        self.grid_scroll = QScrollArea()
        self.grid_scroll.setWidgetResizable(True)
        self.grid_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.grid_scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background-color: {DARK_COLORS['bg_primary']}; }}"
        )
        self.grid_scroll.viewport().setStyleSheet(f"background-color: {DARK_COLORS['bg_primary']};")
        self.grid_host = QWidget()
        self.grid_host.setStyleSheet(f"background-color: {DARK_COLORS['bg_primary']};")
        self.grid_layout = QGridLayout(self.grid_host)
        self.grid_layout.setSpacing(get_scaled_size(10))
        self.grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.grid_scroll.setWidget(self.grid_host)
        left_layout.addWidget(self.grid_scroll, stretch=1)

        # 2열 카드가 스크롤바를 포함해 딱 들어가도록 고정폭 — 빈 공간 제거.
        card_w = get_scaled_size(280)
        spacing = get_scaled_size(10)
        scrollbar_pad = get_scaled_size(18)
        grid_panel_width = card_w * 2 + spacing + scrollbar_pad + get_scaled_size(8)
        left_panel.setFixedWidth(grid_panel_width)
        content_row.addWidget(left_panel)

        # --- Column 2: zoom preview -----------------------------------
        preview_panel = QWidget()
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(get_scaled_size(6))

        preview_title = QLabel("미리보기")
        preview_title.setStyleSheet(
            f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(14)}px; font-weight: 700;"
        )
        preview_layout.addWidget(preview_title)

        self.zoom_label = QLabel("캐릭터를 선택하세요.")
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.zoom_label.setMinimumSize(get_scaled_size(420), get_scaled_size(560))
        self.zoom_label.setStyleSheet(
            f"QLabel {{ border: 1px solid #333; background: #101010; color: {DARK_COLORS['text_secondary']}; }}"
        )
        self.zoom_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        preview_layout.addWidget(self.zoom_label, stretch=1)

        content_row.addWidget(preview_panel, stretch=1)

        # --- Column 3: variation strip (2 cols wrap) ------------------
        variation_panel = QWidget()
        variation_layout = QVBoxLayout(variation_panel)
        variation_layout.setContentsMargins(0, 0, 0, 0)
        variation_layout.setSpacing(get_scaled_size(6))

        strip_title = QLabel("바리에이션")
        strip_title.setStyleSheet(
            f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(14)}px; font-weight: 700;"
        )
        variation_layout.addWidget(strip_title)

        self.strip_scroll = QScrollArea()
        self.strip_scroll.setWidgetResizable(True)
        self.strip_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.strip_scroll.setStyleSheet(
            f"QScrollArea {{ border: 1px solid #333; background-color: #0e1218; }}"
        )
        self.strip_scroll.viewport().setStyleSheet("background-color: #0e1218;")

        self.strip_host = QWidget()
        self.strip_host.setStyleSheet("background-color: #0e1218;")
        self.strip_layout = QGridLayout(self.strip_host)
        self.strip_layout.setContentsMargins(
            get_scaled_size(6), get_scaled_size(6), get_scaled_size(6), get_scaled_size(6)
        )
        self.strip_layout.setSpacing(get_scaled_size(6))
        self.strip_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.strip_scroll.setWidget(self.strip_host)
        variation_layout.addWidget(self.strip_scroll, stretch=1)

        # 2열 바리에이션이 딱 맞도록 고정폭.
        tile_w = get_scaled_size(100)
        tile_spacing = get_scaled_size(6)
        variation_panel_width = tile_w * 2 + tile_spacing + scrollbar_pad + get_scaled_size(20)
        variation_panel.setFixedWidth(variation_panel_width)
        content_row.addWidget(variation_panel)

        outer.addLayout(content_row, stretch=1)

        # --- Bottom row: action buttons ---------------------------------
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(get_scaled_size(6))

        self.c1_only_btn = QPushButton("C1 프롬프트 적용")
        self.c1_only_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.c1_only_btn.setFixedHeight(get_scaled_size(40))
        self.c1_only_btn.clicked.connect(self._apply_c1_only)
        action_row.addWidget(self.c1_only_btn, stretch=1)

        self.c1_inset_btn = QPushButton("C1 + 레퍼런스 인셋")
        self.c1_inset_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.c1_inset_btn.setFixedHeight(get_scaled_size(40))
        self.c1_inset_btn.clicked.connect(self._apply_c1_with_reference)
        action_row.addWidget(self.c1_inset_btn, stretch=1)

        self.open_variations_btn = QPushButton("Variations 편집")
        self.open_variations_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.open_variations_btn.setFixedHeight(get_scaled_size(40))
        self.open_variations_btn.clicked.connect(self._open_variations)
        action_row.addWidget(self.open_variations_btn, stretch=1)

        outer.addLayout(action_row)

        self._update_action_button_state()

    # -- loading ----------------------------------------------------------

    def load_characters(self):
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._character_cards.clear()

        records = list_characters()
        self.empty_label.setVisible(not records)

        for record in records:
            card = CharacterCard(record, self.grid_host)
            card.clicked.connect(self._on_character_clicked)
            card.context_requested.connect(self._on_character_context)
            self._character_cards.append(card)

        self._relayout_grid()
        # viewport width is 0 until the tab has been shown at least once,
        # so schedule a second pass for the initial flash.
        QTimer.singleShot(0, self._relayout_grid)

        # Keep prior selection if it still exists; otherwise clear.
        if self._selected_character_id and not any(
            c.record.character_id == self._selected_character_id for c in self._character_cards
        ):
            self._selected_character_id = None
            self._selected_variation_path = None
            self._reset_preview()
        else:
            self._refresh_variation_strip()
            if self._selected_character_id:
                for card in self._character_cards:
                    card.set_selected(card.record.character_id == self._selected_character_id)

        self._update_action_button_state()

    def _relayout_grid(self):
        """Place character cards in a fixed 2-column grid."""
        if not self._character_cards:
            return
        cols = 2
        for index, card in enumerate(self._character_cards):
            self.grid_layout.addWidget(card, index // cols, index % cols)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._relayout_grid)

    def _refresh_variation_strip(self):
        while self.strip_layout.count():
            item = self.strip_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._variation_tiles.clear()

        if not self._selected_character_id:
            return

        variations = list_character_variations(self._selected_character_id)
        cols = 2
        for index, path in enumerate(variations):
            tile = VariationTile(path, self.strip_host)
            tile.clicked.connect(self._on_variation_clicked)
            tile.context_requested.connect(self._on_variation_context)
            self.strip_layout.addWidget(tile, index // cols, index % cols)
            self._variation_tiles.append(tile)

    # -- selection --------------------------------------------------------

    def _on_character_clicked(self, character_id: str):
        self._selected_character_id = character_id
        self._selected_variation_path = None
        for card in self._character_cards:
            card.set_selected(card.record.character_id == character_id)
        self._update_preview_to_primary()
        self._refresh_variation_strip()
        self._update_action_button_state()

    def _on_variation_clicked(self, path: Path):
        self._selected_variation_path = path
        for tile in self._variation_tiles:
            tile.set_selected(tile.image_path == path)
        self._update_preview(path)

    def _update_preview_to_primary(self):
        if not self._selected_character_id:
            self._reset_preview()
            return
        record = next(
            (c.record for c in self._character_cards if c.record.character_id == self._selected_character_id),
            None,
        )
        if record:
            self._update_preview(record.primary_path)

    def _update_preview(self, image_path: Path):
        w = max(self.zoom_label.width(), get_scaled_size(400))
        h = max(self.zoom_label.height(), get_scaled_size(520))
        pixmap = _load_pixmap_for_label(image_path, w, h)
        if pixmap is not None:
            self.zoom_label.setPixmap(pixmap)
            self.zoom_label.setText("")
        else:
            self.zoom_label.setPixmap(QPixmap())
            self.zoom_label.setText("미리보기 로드 실패")

    def _reset_preview(self):
        self.zoom_label.setPixmap(QPixmap())
        self.zoom_label.setText("캐릭터를 선택하세요.")

    def _update_action_button_state(self):
        enabled = self._selected_character_id is not None
        self.c1_only_btn.setEnabled(enabled)
        self.c1_inset_btn.setEnabled(enabled)
        self.open_variations_btn.setEnabled(enabled)

    # -- actions ----------------------------------------------------------

    def _current_image_path_for_action(self) -> Optional[Path]:
        """Prefer the selected variation, otherwise fall back to the primary."""
        if self._selected_variation_path is not None:
            return self._selected_variation_path
        if not self._selected_character_id:
            return None
        record = next(
            (c.record for c in self._character_cards if c.record.character_id == self._selected_character_id),
            None,
        )
        return record.primary_path if record else None

    def _apply_c1_only(self):
        path = self._current_image_path_for_action()
        if path is None:
            return
        self.window_ref.apply_c1_only(path)

    def _apply_c1_with_reference(self):
        path = self._current_image_path_for_action()
        if path is None:
            return
        self.window_ref.apply_c1_with_reference(path)

    def _open_variations(self):
        if not self._selected_character_id:
            return
        self.variations_requested.emit(self._selected_character_id)

    # -- context menus ----------------------------------------------------

    def _on_character_context(self, character_id: str, global_pos):
        # Make sure the character clicked is the selected one before showing actions.
        if self._selected_character_id != character_id:
            self._on_character_clicked(character_id)

        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background-color: {DARK_COLORS['bg_secondary']}; color: {DARK_COLORS['text_primary']}; "
            f"border: 1px solid {DARK_COLORS['border']}; }} "
            f"QMenu::item:selected {{ background-color: {DARK_COLORS['accent_blue']}; }}"
        )

        act_c1 = QAction("C1 프롬프트 적용", self)
        act_c1.triggered.connect(self._apply_c1_only)
        menu.addAction(act_c1)

        act_ref = QAction("C1 + 레퍼런스 인셋 적용", self)
        act_ref.triggered.connect(self._apply_c1_with_reference)
        menu.addAction(act_ref)

        act_var = QAction("Variations 편집", self)
        act_var.triggered.connect(self._open_variations)
        menu.addAction(act_var)

        menu.addSeparator()

        act_delete = QAction("캐릭터 삭제", self)
        act_delete.triggered.connect(lambda: self._delete_character(character_id))
        menu.addAction(act_delete)

        menu.exec(global_pos)

    def _on_variation_context(self, variation_path: Path, global_pos):
        self._on_variation_clicked(variation_path)

        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background-color: {DARK_COLORS['bg_secondary']}; color: {DARK_COLORS['text_primary']}; "
            f"border: 1px solid {DARK_COLORS['border']}; }} "
            f"QMenu::item:selected {{ background-color: {DARK_COLORS['accent_blue']}; }}"
        )

        act_c1 = QAction("C1 프롬프트 적용 (이 이미지 기준)", self)
        act_c1.triggered.connect(self._apply_c1_only)
        menu.addAction(act_c1)

        act_ref = QAction("레퍼런스 인셋 적용 (이 이미지)", self)
        act_ref.triggered.connect(self._apply_c1_with_reference)
        menu.addAction(act_ref)

        menu.addSeparator()

        act_promote = QAction("primary로 승격", self)
        act_promote.triggered.connect(lambda: self._promote_variation(variation_path))
        menu.addAction(act_promote)

        act_delete = QAction("이 바리에이션 삭제", self)
        act_delete.triggered.connect(lambda: self._delete_variation(variation_path))
        menu.addAction(act_delete)

        menu.exec(global_pos)

    def _delete_character(self, character_id: str):
        confirm = QMessageBox.question(
            self,
            "캐릭터 삭제",
            "선택한 캐릭터와 모든 바리에이션을 삭제할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        if delete_character(character_id):
            if self._selected_character_id == character_id:
                self._selected_character_id = None
                self._selected_variation_path = None
            self.load_characters()

    def _delete_variation(self, variation_path: Path):
        if not self._selected_character_id:
            return
        if delete_variation(self._selected_character_id, variation_path):
            if self._selected_variation_path == variation_path:
                self._selected_variation_path = None
            self.load_characters()

    def _promote_variation(self, variation_path: Path):
        if not self._selected_character_id:
            return
        if promote_variation_to_primary(self._selected_character_id, variation_path):
            self._selected_variation_path = None
            self.load_characters()

    def _open_storage_folder(self):
        ensure_character_asset_storage_dirs()
        folder = CHARACTER_ASSET_CHARACTERS_DIR.resolve()
        try:
            system = platform.system()
            if system == "Windows":
                os.startfile(folder)
            elif system == "Darwin":
                subprocess.run(["open", str(folder)])
            else:
                subprocess.run(["xdg-open", str(folder)])
        except Exception as exc:
            print(f"Failed to open character asset folder: {exc}")


# ---------------------------------------------------------------------------
# NAI metadata re-encoder (shared between worker + Save paths)
# ---------------------------------------------------------------------------


def _reencode_with_nai_meta(
    edited_image: Image.Image,
    source_image: Image.Image,
    parameters: dict,
) -> bytes:
    """Re-save ``edited_image`` as PNG while carrying over NAI tEXt chunks
    from ``source_image.info``. Falls back to synthesising a minimal Comment
    JSON from ``parameters`` when the original lacks the core NAI fields.
    Mirrors ``APIService._build_nai_pnginfo_for_cropped_image``.

    Shared by the inpaint worker's ``_finalize_variation_result`` and by the
    plain Save button's LANCZOS upscale path — both need the same NAI tEXt
    carry-over so PNG Info / Enhance downstream keep working.
    """
    import json as _json
    from PIL.PngImagePlugin import PngInfo

    pnginfo = PngInfo()
    source_info = getattr(source_image, "info", {}) or {}
    preserved_keys = (
        "Title",
        "Description",
        "Software",
        "Source",
        "Comment",
        "Generation time",
        "Author",
    )
    added_any = False
    for key in preserved_keys:
        value = source_info.get(key)
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="ignore")
        if isinstance(value, str) and value:
            pnginfo.add_text(key, value)
            added_any = True

    has_core_nai = bool(source_info.get("Software")) and bool(source_info.get("Comment"))
    if not has_core_nai:
        comment_payload: dict = {
            "prompt": parameters.get("input", "") or "",
            "uc": parameters.get("negative_prompt", "") or "",
        }
        for key in (
            "steps",
            "scale",
            "seed",
            "sampler",
            "noise_schedule",
            "cfg_rescale",
            "sm",
            "sm_dyn",
        ):
            if parameters.get(key) is not None:
                comment_payload[key] = parameters[key]
        try:
            comment_json = _json.dumps(comment_payload, ensure_ascii=False)
        except Exception:
            comment_json = None
        if not source_info.get("Software"):
            pnginfo.add_text("Software", "NovelAI")
            added_any = True
        if not source_info.get("Description"):
            description_text = parameters.get("input", "") or ""
            if description_text:
                pnginfo.add_text("Description", description_text)
                added_any = True
        if not source_info.get("Comment") and comment_json:
            pnginfo.add_text("Comment", comment_json)
            added_any = True

    buffer = io.BytesIO()
    edited_image.save(buffer, format="PNG", pnginfo=pnginfo if added_any else None)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Variations worker — dedicated inpaint pipeline (sketchbook pattern)
# ---------------------------------------------------------------------------


class VariationGenerationWorker(QThread):
    """QThread worker that runs a reference-inset inpaint through the API
    service directly, bypassing the main prompt pipeline so character, main and
    inpaint prompts can be edited in isolation."""

    generation_finished = pyqtSignal(dict)  # full result dict from api_service
    generation_error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(
        self,
        app_context,
        canvas_image: Image.Image,
        full_mask: Image.Image,
        small_mask: Image.Image,
        main_prompt: str,
        negative_prompt: str,
        character_prompt: str,
        character_uc: str,
        strength: float = 1.0,
        noise: float = 0.0,
    ):
        super().__init__()
        self.app_context = app_context
        self.canvas_image = canvas_image
        self.full_mask = full_mask
        self.small_mask = small_mask
        self.main_prompt = main_prompt
        self.negative_prompt = negative_prompt
        self.character_prompt = character_prompt
        self.character_uc = character_uc
        self.strength = strength
        self.noise = noise

    def run(self):
        try:
            main_window = getattr(self.app_context, "main_window", None)
            api_service = getattr(self.app_context, "api_service", None)
            if main_window is None or api_service is None:
                self.generation_error.emit("앱 컨텍스트가 완전히 초기화되지 않았습니다.")
                return

            api_mode = main_window.get_current_api_mode() if hasattr(main_window, "get_current_api_mode") else "NAI"

            self.progress.emit("파라미터 수집 중...")
            params = self._collect_parameters(api_mode, main_window)

            # Inpaint + reference inset overrides — these win against whatever
            # was in the main UI so the main generation panel state doesn't
            # leak into the variation.
            canvas_bytes = io.BytesIO()
            self.canvas_image.save(canvas_bytes, format="PNG")
            mask_bytes = io.BytesIO()
            if api_mode == "NAI":
                self.small_mask.save(mask_bytes, format="PNG", compress_level=0, optimize=False)
            else:
                self.full_mask.save(mask_bytes, format="PNG", compress_level=1, optimize=False)

            params["type"] = "inpaint"
            params["strength"] = self.strength
            params["noise"] = self.noise
            params["image_bytes"] = canvas_bytes.getvalue()
            params["mask_bytes"] = mask_bytes.getvalue()
            params["width"] = self.canvas_image.width
            params["height"] = self.canvas_image.height

            # NOTE: cropped_image_request는 의도적으로 끈다. 크롭 파이프라인은
            # 마스크 bbox를 Enhance-ready(≈1MP, x1.5 선반영) 박스로 축소하는데,
            # Variations의 좁은 480x1280 마스크에 적용하면 결과가 ~280x794까지
            # 줄어 다음 768x1344 i2i에서 재사용이 불가능해진다. 전체 768x1344
            # 캔버스를 그대로 저장해 바리에이션으로 보존한다 — 마스크 바깥은
            # 원본 primary가 유지되고 NAI Comment는 raw_bytes에 그대로 담긴다.

            # Prompt overrides — user's direct edits, no prompt-engineering hook
            # pass. sketchbook pattern: params['input'] drives the final string.
            params["input"] = self.main_prompt
            params["prompt"] = self.main_prompt
            params["negative_prompt"] = self.negative_prompt

            # Character prompt override via sketchbook contract — api_service
            # already normalizes this into the NAI character block.
            if self.character_prompt.strip():
                params["sketchbook_character_prompts"] = [
                    (self.character_prompt, self.character_uc or "")
                ]
            else:
                # Nothing to override — make sure any residual main-UI character
                # state does not slip through.
                params["sketchbook_character_prompts"] = []

            self.progress.emit("API 호출 중...")
            result = api_service.call_generation_api(params)

            if not isinstance(result, dict):
                self.generation_error.emit("API 응답이 비어있습니다.")
                return
            if result.get("status") != "success":
                self.generation_error.emit(str(result.get("message") or "알 수 없는 오류"))
                return

            # Crop the edit rect (480x840 on a 1152x896 canvas) and scale up
            # to 768x1344 so the saved variation is a standalone portrait
            # usable as the primary for the next i2i round. NAI metadata is
            # copied from the original full-canvas response.
            try:
                self._finalize_variation_result(result, params)
            except Exception as exc:
                self.generation_error.emit(f"결과 후처리 실패: {exc}")
                return

            # Echo the effective params so downstream UI can inspect what ran.
            result["generation_params"] = params
            self.generation_finished.emit(result)
        except Exception as exc:
            self.generation_error.emit(f"오류: {exc}")

    def _finalize_variation_result(self, result: dict, params: dict) -> None:
        """In-place rewrite of ``result`` so ``image``/``raw_bytes`` hold the
        cropped editable rectangle (512×896) at native resolution. The
        original full-canvas image is used as the source for NAI tEXt chunks
        — we don't want to re-encode them away.

        No upscale is performed here. NAI's inpaint output loses effective
        resolution inside the mask, so forcing a LANCZOS 1.5× resize here
        would just bake in soft detail. Instead we keep the native crop and
        let the user hit "Save with Enhance" in the main UI to reach
        768×1344 properly — that path runs a real Enhance pass rather than a
        blind resampler.

        The edit rect is exactly 4:7 (512×896), so a later Enhance 1.5×
        lands on 768×1344 with zero aspect correction.
        """
        source_image = result.get("image")
        if source_image is None:
            return

        from utils.reference_inpaint_preprocess import VariationInpaintSpec

        spec = VariationInpaintSpec()
        final_image = source_image.crop(
            (spec.edit_left, spec.edit_top, spec.edit_right, spec.edit_bottom)
        )

        raw_bytes = _reencode_with_nai_meta(final_image, source_image, params)

        # Reload through a BytesIO so the returned PIL image carries the NAI
        # tEXt chunks in ``.info`` — mirrors the 170 cropped-image pattern so
        # downstream tooling (Enhance, PNG Info tab) recognises the metadata.
        reloaded = Image.open(io.BytesIO(raw_bytes))
        reloaded.load()

        result["image"] = reloaded
        result["raw_bytes"] = raw_bytes

    def _collect_parameters(self, api_mode: str, main_window) -> dict:
        """Mirror sketchbook worker's collection: main-window parameters +
        optional middle-section module parameters. We deliberately skip any
        automation/prompt-engineering side effects."""
        params: dict = {}
        if hasattr(main_window, "get_main_parameters"):
            try:
                params = main_window.get_main_parameters() or {}
            except Exception as exc:
                print(f"get_main_parameters failed in variations worker: {exc}")
                params = {}

        params["api_mode"] = api_mode

        # Credential wiring (same ordering as sketchbook worker).
        secure_tokens = getattr(self.app_context, "secure_token_manager", None)
        if secure_tokens is not None:
            try:
                if api_mode == "NAI":
                    params["credential"] = secure_tokens.get_token("nai_token")
                elif api_mode == "COMFYUI":
                    params["credential"] = secure_tokens.get_token("comfyui_url")
                else:
                    params["credential"] = secure_tokens.get_token("webui_url")
            except Exception as exc:
                print(f"Credential lookup failed: {exc}")

        # Middle-section module parameter merge (e.g. Danbooru weight, e621
        # boost are turned off for variations — we only want things that don't
        # rewrite prompts, such as LoRA selectors, but the sketchbook pattern
        # just merges everything. Keep it simple for MVP.).
        middle_controller = getattr(self.app_context, "middle_section_controller", None)
        if middle_controller is not None and hasattr(middle_controller, "module_instances"):
            for module in middle_controller.module_instances:
                if hasattr(module, "get_parameters"):
                    try:
                        module_params = module.get_parameters()
                    except Exception:
                        module_params = None
                    if module_params:
                        params.update(module_params)

        return params


class _VariationEnhanceWorker(QObject):
    """Lightweight QObject worker for a single NAI img2img Enhance pass.

    Matches the pattern used by ``tabs/image_window._execute_enhance``: the
    worker is moved onto a QThread, started from ``thread.started``, and
    emits ``finished`` with the api_service result dict when done. We keep
    the shape identical so anyone who already knows the main-UI Enhance flow
    can read this without surprises.
    """

    finished = pyqtSignal(dict)

    def __init__(self, api_service, params: dict):
        super().__init__()
        self.api_service = api_service
        self.params = params

    def run(self):
        try:
            result = self.api_service.call_generation_api(self.params)
        except Exception as exc:
            result = {"status": "error", "message": str(exc)}
        if not isinstance(result, dict):
            result = {"status": "error", "message": "API 응답이 비어있습니다."}
        self.finished.emit(result)


# ---------------------------------------------------------------------------
# Variations tab
# ---------------------------------------------------------------------------


class VariationsTab(QWidget):
    """Tab 2: dedicated variation pipeline. Loads the character's primary as a
    reference inset canvas, exposes character/main/negative prompt editors, and
    runs generations through a private QThread worker — the main img2img panel
    is not touched."""

    def __init__(self, window: "CharacterAssetStorageWindow", parent=None):
        super().__init__(parent)
        self.window_ref = window
        self.app_context = window.app_context

        self._character_id: Optional[str] = None
        self._primary_path: Optional[Path] = None
        self._result_cards: list[VariationResultCard] = []
        self._selected_card: Optional[VariationResultCard] = None
        self._preview_source_image: Optional[Image.Image] = None
        self._active_worker: Optional[VariationGenerationWorker] = None

        # Continuous generation session state (character_asset_generation_window 패턴)
        self._pending_count: int = 0
        self._stop_requested: bool = False
        self._continuous_mode: bool = False
        # Hard re-entrancy guard: flips True at the start of _dispatch_next_generation
        # and resets in cleanup. Catches any pathway (queued click event, timer race,
        # duplicate signal connection) that would otherwise start a second worker
        # while one is still in flight.
        self._is_dispatching: bool = False
        # Suppress textChanged auto-save while programmatically populating editors
        # from the last-used defaults on disk.
        self._suppress_defaults_save: bool = False
        # Enhance save flow — one worker at a time. Buttons disable while a
        # save-with-enhance is running so the user can't double-trigger or
        # discard the card mid-flight.
        self._enhance_thread: Optional[QThread] = None
        self._enhance_worker: Optional[QObject] = None

        self._setup_ui()

    def _setup_ui(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(get_scaled_size(12), get_scaled_size(12), get_scaled_size(12), get_scaled_size(12))
        outer.setSpacing(get_scaled_size(12))

        # -------------------------------------------------------------
        # Left column — controls
        # -------------------------------------------------------------
        left_column = QVBoxLayout()
        left_column.setContentsMargins(0, 0, 0, 0)
        left_column.setSpacing(get_scaled_size(10))

        # Header (character thumb + status)
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(get_scaled_size(10))

        self.character_preview = QLabel()
        self.character_preview.setFixedSize(get_scaled_size(120), get_scaled_size(168))
        self.character_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.character_preview.setStyleSheet("QLabel { border: 1px solid #333; background: #101010; }")
        header_row.addWidget(self.character_preview)

        header_text = QVBoxLayout()
        header_text.setContentsMargins(0, 0, 0, 0)
        header_text.setSpacing(get_scaled_size(4))
        self.character_name_label = QLabel("선택된 캐릭터 없음")
        self.character_name_label.setStyleSheet(
            f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(16)}px; font-weight: 700;"
        )
        self.hint_label = QLabel(
            "Characters 탭에서 'Variations 편집'을 누르면 primary 프롬프트가 채워집니다. "
            "의상·자세 태그를 추가하고 '바리에이션 생성'을 누르세요."
        )
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet(
            f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(11)}px;"
        )
        self.status_label = QLabel("대기 중")
        self.status_label.setStyleSheet(
            f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(11)}px;"
        )
        header_text.addWidget(self.character_name_label)
        header_text.addWidget(self.hint_label)
        header_text.addWidget(self.status_label)
        header_text.addStretch()
        header_row.addLayout(header_text, stretch=1)
        left_column.addLayout(header_row)

        # Prompt editors stacked vertically (column is narrow)
        left_column.addWidget(self._prompt_title("Character Prompt (의상 / 악세서리 / 디테일 작성)"))
        self.character_prompt_edit = self._make_text_edit(
            placeholder="primary 이미지에서 자동 복구. 의상·악세서리·디테일을 여기에 추가하세요.",
            height=get_scaled_size(100),
        )
        left_column.addWidget(self.character_prompt_edit)

        left_column.addWidget(self._prompt_title("Character UC"))
        self.character_uc_edit = self._make_text_edit(
            placeholder="캐릭터 전용 네거티브",
            height=get_scaled_size(64),
        )
        left_column.addWidget(self.character_uc_edit)

        left_column.addWidget(self._prompt_title("Main Prompt (자세 / 배경만)"))
        self.main_prompt_edit = self._make_text_edit(
            placeholder="예) sitting, cafe — 자세와 배경만 작성하세요 (의상은 Character Prompt)",
            height=get_scaled_size(100),
        )
        left_column.addWidget(self.main_prompt_edit)

        left_column.addWidget(self._prompt_title("추가 Negative (메인 UI 네거티브에 이어붙임)"))
        self.negative_prompt_edit = self._make_text_edit(
            placeholder="예) blurry, low quality — 메인 네거티브는 자동 포함",
            height=get_scaled_size(64),
        )
        left_column.addWidget(self.negative_prompt_edit)

        # Last-used values persistence: load immediately so defaults show at
        # first open, and rebind to text changes so each edit is saved. The
        # two base defaults come from the NAI 2-panel reference-inset trick:
        # "2koma, borderless panel" on the main prompt + "border" on the
        # negative makes the second panel blend cleanly with the reference.
        self._load_variation_defaults()
        self.main_prompt_edit.textChanged.connect(self._save_variation_defaults)
        self.negative_prompt_edit.textChanged.connect(self._save_variation_defaults)

        # Count + continuous + buttons
        count_row = QHBoxLayout()
        count_row.setContentsMargins(0, 0, 0, 0)
        count_row.setSpacing(get_scaled_size(8))

        count_label = QLabel("생성 횟수")
        count_label.setStyleSheet(
            f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(12)}px;"
        )
        self.count_spinbox = QSpinBox()
        self.count_spinbox.setRange(1, 999)
        self.count_spinbox.setValue(1)
        self.count_spinbox.setFixedWidth(get_scaled_size(100))
        self.count_spinbox.setStyleSheet(DARK_STYLES['compact_spinbox'])

        self.continue_checkbox = QCheckBox("계속 생성")
        self.continue_checkbox.setToolTip(
            "체크 시 생성 횟수와 무관하게 Stop을 누를 때까지 계속 생성합니다."
        )
        self.continue_checkbox.setStyleSheet(DARK_STYLES['dark_checkbox'])

        count_row.addWidget(count_label)
        count_row.addWidget(self.count_spinbox)
        count_row.addWidget(self.continue_checkbox)
        count_row.addStretch()
        left_column.addLayout(count_row)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(get_scaled_size(6))

        self.generate_btn = QPushButton("바리에이션 생성")
        self.generate_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.generate_btn.setFixedHeight(get_scaled_size(40))
        self.generate_btn.clicked.connect(self._on_generate_clicked)
        button_row.addWidget(self.generate_btn, stretch=1)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.stop_btn.setFixedHeight(get_scaled_size(40))
        self.stop_btn.clicked.connect(self._on_stop_clicked)
        button_row.addWidget(self.stop_btn)

        left_column.addLayout(button_row)
        left_column.addStretch()

        # Pin the control column width so the result area dominates.
        left_host = QWidget()
        left_host.setLayout(left_column)
        left_host.setFixedWidth(get_scaled_size(540))
        outer.addWidget(left_host)

        # -------------------------------------------------------------
        # Center column — expanded preview for the selected result
        # -------------------------------------------------------------
        center_column = QVBoxLayout()
        center_column.setContentsMargins(0, 0, 0, 0)
        center_column.setSpacing(get_scaled_size(6))

        center_title = QLabel("생성 결과")
        center_title.setStyleSheet(
            f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(14)}px; font-weight: 700;"
        )
        center_column.addWidget(center_title)

        self.preview_label = QLabel("생성된 결과가 여기 크게 표시됩니다.")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(get_scaled_size(420), get_scaled_size(560))
        self.preview_label.setStyleSheet(
            f"QLabel {{ border: 1px solid #333; background: #0e1218; color: {DARK_COLORS['text_secondary']}; }}"
        )
        self.preview_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        center_column.addWidget(self.preview_label, stretch=1)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(get_scaled_size(8))

        self.save_btn = QPushButton("Save")
        self.save_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.save_btn.setFixedHeight(get_scaled_size(40))
        self.save_btn.clicked.connect(self._on_save_clicked)
        action_row.addWidget(self.save_btn, stretch=1)

        # Primary-styled — Enhance is the recommended save path because NAI
        # inpaint output loses effective resolution inside the mask. A 1.5×
        # img2img Enhance pass at strength 0.2 / noise 0.0 lifts the 512×896
        # crop to 768×1344 with proper detail instead of a blind LANCZOS
        # upsample. NAI-only; button disables in other modes.
        self.save_enhance_btn = QPushButton("✨ Save with Enhance")
        self.save_enhance_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.save_enhance_btn.setFixedHeight(get_scaled_size(40))
        self.save_enhance_btn.clicked.connect(self._on_save_with_enhance_clicked)
        action_row.addWidget(self.save_enhance_btn, stretch=1)

        self.discard_btn = QPushButton("Discard")
        self.discard_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.discard_btn.setFixedHeight(get_scaled_size(40))
        self.discard_btn.clicked.connect(self._on_discard_clicked)
        action_row.addWidget(self.discard_btn, stretch=1)

        center_column.addLayout(action_row)

        center_host = QWidget()
        center_host.setLayout(center_column)
        outer.addWidget(center_host, stretch=1)

        # -------------------------------------------------------------
        # Right column — thumbnail strip (2 columns)
        # -------------------------------------------------------------
        right_column = QVBoxLayout()
        right_column.setContentsMargins(0, 0, 0, 0)
        right_column.setSpacing(get_scaled_size(6))

        thumbs_title = QLabel("썸네일")
        thumbs_title.setStyleSheet(
            f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(14)}px; font-weight: 700;"
        )
        right_column.addWidget(thumbs_title)

        self.result_scroll = QScrollArea()
        self.result_scroll.setWidgetResizable(True)
        self.result_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.result_scroll.setStyleSheet(
            f"QScrollArea {{ border: 1px solid #333; background-color: #0e1218; }}"
        )
        self.result_scroll.viewport().setStyleSheet("background-color: #0e1218;")

        self.result_host = QWidget()
        self.result_host.setStyleSheet("background-color: #0e1218;")
        self.result_layout = QGridLayout(self.result_host)
        self.result_layout.setContentsMargins(
            get_scaled_size(8), get_scaled_size(8), get_scaled_size(8), get_scaled_size(8)
        )
        self.result_layout.setSpacing(get_scaled_size(6))
        self.result_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.result_scroll.setWidget(self.result_host)
        right_column.addWidget(self.result_scroll, stretch=1)

        right_host = QWidget()
        right_host.setLayout(right_column)
        # 2 columns of CARD_WIDTH + spacing + scrollbar padding.
        thumb_w = get_scaled_size(VariationResultCard.CARD_WIDTH)
        thumb_spacing = get_scaled_size(6)
        scrollbar_pad = get_scaled_size(18)
        right_host.setFixedWidth(thumb_w * 2 + thumb_spacing + scrollbar_pad + get_scaled_size(24))
        outer.addWidget(right_host)

        self._update_controls()
        self._update_preview()

    # -- small factories -------------------------------------------------

    def _prompt_title(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(
            f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(12)}px; font-weight: 700;"
        )
        return label

    def _make_text_edit(self, placeholder: str, height: int) -> QTextEdit:
        editor = QTextEdit()
        editor.setAcceptRichText(False)
        editor.setPlaceholderText(placeholder)
        editor.setFixedHeight(height)
        editor.setStyleSheet(DARK_STYLES['compact_textedit'])
        return editor

    # -- character binding ----------------------------------------------

    def bind_character(self, character_id: str, primary_path: Path):
        # 캐릭터를 갈아끼울 때 이전 결과를 비워 잘못된 캐릭터 폴더에 저장되는 것을 방지.
        self._clear_all_results()

        self._character_id = character_id
        self._primary_path = primary_path
        self.character_name_label.setText(f"캐릭터: {character_id}")
        preview = _load_pixmap_for_label(
            primary_path, self.character_preview.width(), self.character_preview.height()
        )
        if preview is not None:
            self.character_preview.setPixmap(preview)

        # Prefill character prompt/UC from the primary image's NAI metadata so
        # the user only has to add a main prompt for the variation.
        metadata = load_character_asset_metadata(character_id, primary_path)
        self.character_prompt_edit.setPlainText((metadata or {}).get("character_prompt", ""))
        self.character_uc_edit.setPlainText((metadata or {}).get("character_uc", ""))
        self.status_label.setText("준비 완료 — 메인 프롬프트를 입력하고 생성하세요.")
        self._update_controls()

    def _clear_all_results(self):
        """Drop every pending thumbnail and reset the central preview."""
        for card in list(self._result_cards):
            card.setParent(None)
            card.deleteLater()
        self._result_cards.clear()
        self._selected_card = None
        self._relayout_results()
        self._update_preview()

    # -- generate --------------------------------------------------------

    def _update_controls(self):
        character_bound = self._character_id is not None and self._primary_path is not None
        busy = self._is_session_active()
        self.generate_btn.setEnabled(character_bound and not busy)
        self.stop_btn.setEnabled(busy)
        self.count_spinbox.setEnabled(not busy)
        self.continue_checkbox.setEnabled(not busy)
        for editor in (
            self.character_prompt_edit,
            self.character_uc_edit,
            self.main_prompt_edit,
            self.negative_prompt_edit,
        ):
            editor.setReadOnly(busy)

    def _is_session_active(self) -> bool:
        """Session = either a worker is running or the continuous loop is armed."""
        if self._active_worker is not None and self._active_worker.isRunning():
            return True
        if self._continuous_mode and not self._stop_requested:
            return True
        if self._pending_count > 0 and not self._stop_requested:
            return True
        return False

    def _on_generate_clicked(self):
        # Immediately disable the button so any duplicate click events
        # queued by Qt (focus-in-then-click, key-activated, accessibility…)
        # can't re-enter this slot before _update_controls has a chance to
        # reflect the session state.
        self.generate_btn.setEnabled(False)

        # Any in-flight session — either a worker is running or the dispatch
        # guard is still held — short-circuits here. This is the outer guard
        # against a duplicate click event being processed after we disabled
        # the button; the inner guard lives in _dispatch_next_generation.
        if self._is_dispatching or self._is_session_active():
            return

        if not self._primary_path or not self._primary_path.exists():
            QMessageBox.warning(self, "생성 실패", "선택된 캐릭터의 primary 이미지가 없습니다.")
            self._update_controls()
            return

        self._pending_count = int(self.count_spinbox.value())
        self._continuous_mode = self.continue_checkbox.isChecked()
        self._stop_requested = False
        self._update_controls()
        self._dispatch_next_generation()

    def _on_stop_clicked(self):
        """Request the continuous loop to finish after the current call returns."""
        if not self._is_session_active():
            return
        self._stop_requested = True
        self._pending_count = 0
        self._continuous_mode = False
        self.status_label.setText("중지 요청됨 — 현재 생성 완료 후 정지")
        self._update_controls()

    def _dispatch_next_generation(self):
        # Hard re-entrancy guard. Any second caller (QTimer race, duplicate
        # click event queued before the button disabled, stray signal) returns
        # early so only one worker can ever be in flight. The flag resets in
        # _on_worker_cleanup after the worker is torn down.
        if self._is_dispatching or self._active_worker is not None:
            return

        if self._stop_requested:
            self._finalize_session("중지됨")
            return
        if not self._continuous_mode and self._pending_count <= 0:
            self._finalize_session("생성 완료")
            return

        if not self._primary_path or not self._primary_path.exists():
            self._finalize_session("primary 이미지가 사라졌습니다.")
            return

        # Claim the dispatch slot BEFORE any further work so a parallel caller
        # entering between here and worker.start() cannot double-dispatch.
        self._is_dispatching = True
        # Decrement up-front (non-continuous only). This represents "this
        # dispatch consumes one scheduled generation". Doing it here — rather
        # than in _on_worker_finished — means the counter is always consistent
        # even if the finished callback throws before its own decrement runs.
        if not self._continuous_mode and self._pending_count > 0:
            self._pending_count -= 1

        try:
            pil_image = Image.open(self._primary_path)
            pil_image.load()
        except Exception as exc:
            self._finalize_session(f"이미지 오픈 실패: {exc}")
            return

        try:
            # Variations 탭은 "같은 캐릭터의 의상/자세 변화"가 목적이므로
            # 768x1344 캔버스 + 중앙 480x1280 좁은 마스크를 사용한다. 기본
            # reference-inset preprocessor는 편집 영역이 커서 NAI가 빈
            # 공간을 또 다른 캐릭터로 채우려는 부작용이 있었다.
            preprocess = prepare_variation_inpaint_canvas(pil_image)
        except Exception as exc:
            self._finalize_session(f"레퍼런스 인셋 생성 실패: {exc}")
            return

        # 메인 파이프라인을 wildcard_standalone=True 로 1회 돌려 pre/post 고정
        # 프롬프트, Auto Hide, Danbooru Auto-Weight 등 훅이 적용된 최종 프롬프트를
        # 얻는다. 매 dispatch마다 다시 호출하여 와일드카드 랜덤성이 매 회 갱신되도록.
        user_main = self.main_prompt_edit.toPlainText().strip()
        final_main_prompt = self._compose_main_prompt(user_main)

        final_negative = self._compose_negative_prompt(
            self.negative_prompt_edit.toPlainText().strip()
        )

        worker = VariationGenerationWorker(
            app_context=self.app_context,
            canvas_image=preprocess.canvas_image,
            full_mask=preprocess.full_mask_image,
            small_mask=preprocess.small_mask_image,
            main_prompt=final_main_prompt,
            negative_prompt=final_negative,
            character_prompt=self.character_prompt_edit.toPlainText().strip(),
            character_uc=self.character_uc_edit.toPlainText().strip(),
            # Variations 탭은 레퍼런스 인셋 고정 → strength/noise 1.0/0.0 고정
            strength=1.0,
            noise=0.0,
        )
        worker.generation_finished.connect(self._on_worker_finished)
        worker.generation_error.connect(self._on_worker_error)
        worker.progress.connect(lambda msg: self.status_label.setText(msg))
        worker.finished.connect(lambda: self._on_worker_cleanup(worker))
        self._active_worker = worker

        remaining_hint = "무제한" if self._continuous_mode else str(self._pending_count)
        self.status_label.setText(f"생성 중... (남은 예약: {remaining_hint})")
        self._update_controls()
        worker.start()

    def _finalize_session(self, status_message: str):
        self._pending_count = 0
        self._continuous_mode = False
        self._stop_requested = False
        # Always release the dispatch guard on finalize — covers the
        # "early-failure after the flag was claimed" branches inside
        # _dispatch_next_generation (image open / preprocess exceptions).
        self._is_dispatching = False
        self.status_label.setText(status_message)
        self._update_controls()

    def _compose_main_prompt(self, user_main_prompt: str) -> str:
        """메인 UI의 pre/post 고정 프롬프트 + 훅 파이프라인을 적용한 최종 프롬프트.

        PromptGenerationController.generate_instant_source_silent 가
        AppContext 상태(current_source_row/context)를 save/restore 하므로
        메인 생성 플로우와 충돌 없이 호출 가능하다. wildcard_standalone=True
        로 DB 태그 없이 유저 입력 + 훅만으로 조립한다.

        NOTE: ``prompt_gen_controller``는 ``MainWindow``의 속성이지
        ``AppContext``의 속성이 아니다 (NAIA_cold_v4.py:939). 이전에
        ``app_context.prompt_gen_controller``를 잘못 참조해 항상 None이
        되면서 훅 파이프라인이 돌지 않고 유저 입력만 그대로 통과됐고,
        그 결과 선행/후행 고정 프롬프트 없이 NAI에 짧은 프롬프트가
        전달되어 "빈 프롬프트" 증상이 나왔다.
        """
        main_window = getattr(self.app_context, "main_window", None)
        prompt_gen = getattr(main_window, "prompt_gen_controller", None) if main_window else None
        if prompt_gen is None:
            return user_main_prompt

        api_mode = main_window.get_current_api_mode() if hasattr(main_window, "get_current_api_mode") else "NAI"

        tags_dict = {
            "general": user_main_prompt,
            "character": "",
            "copyright": "",
            "artist": "",
            "meta": "",
        }
        settings = {
            "prompt_fixed": False,
            "auto_generate": False,
            "turbo_mode": False,
            "wildcard_standalone": True,
            "api_mode": api_mode,
            "comfyui_sampling_mode": "eps",
        }

        try:
            composed = prompt_gen.generate_instant_source_silent(tags_dict, settings)
        except Exception as exc:
            print(f"Variations prompt compose failed, using raw main prompt: {exc}")
            composed = None
        return composed or user_main_prompt

    def _compose_negative_prompt(self, user_extra_negative: str) -> str:
        """메인 UI 네거티브 + 유저 추가분을 결합한다.

        get_main_parameters 는 seed_input 을 랜덤 변이시키는 side-effect 가 있어
        여기서는 호출하지 않고, negative_prompt_textedit 위젯을 직접 읽는다.
        """
        main_window = getattr(self.app_context, "main_window", None)
        base_negative = ""
        widget = getattr(main_window, "negative_prompt_textedit", None) if main_window else None
        if widget is not None:
            try:
                base_negative = widget.toPlainText().strip()
            except Exception as exc:
                print(f"Reading main UI negative failed: {exc}")

        parts = [segment for segment in (base_negative, user_extra_negative.strip()) if segment]
        return ", ".join(parts)

    def _on_worker_finished(self, result: dict):
        card = VariationResultCard(result, self.result_host)
        card.clicked.connect(self._on_thumbnail_clicked)
        self._result_cards.append(card)
        self._relayout_results()
        # Auto-select the newest result so continuous generation keeps
        # bringing the latest image into the central preview.
        self._select_card(card)

        # Mirror the freshly generated variation into the main UI — same
        # contract the Comic Panel / Inpaint path uses. We bypass
        # ``update_ui_with_result`` (which would also retrigger automation
        # scheduling and Remote relay events) and instead call the three
        # image-window methods directly: ``update_image`` for the viewer,
        # ``update_info`` for the side panel, ``add_to_history`` for the
        # scrollable history list + optional auto-save.
        #
        # ``add_to_history`` respects the main UI's auto-save checkbox, so
        # whether a duplicate PNG is written to ``save/`` is the user's own
        # preference. The dedicated ``variations/{hash}.png`` copy is still
        # only written on the explicit Save button inside this tab.
        main_window = getattr(self.app_context, "main_window", None)
        image_window = getattr(main_window, "image_window", None) if main_window else None
        if image_window is not None:
            image_obj = result.get("image")
            raw_bytes = result.get("raw_bytes")
            info_text = result.get("info", "")
            source_row = result.get("source_row")
            try:
                image_window.update_image(image_obj)
            except Exception as exc:
                print(f"Failed to mirror variation to main image window: {exc}")
            try:
                image_window.update_info(info_text)
            except Exception as exc:
                print(f"Failed to update main info panel: {exc}")
            try:
                image_window.add_to_history(
                    image_obj,
                    raw_bytes,
                    info_text,
                    source_row,
                    generation_result=result,
                )
            except Exception as exc:
                print(f"Failed to add variation to main history: {exc}")

        # Note: _pending_count was already decremented up-front in
        # _dispatch_next_generation. Do not decrement here or continuous
        # mode would run out of budget one cycle early.

    def _on_worker_error(self, message: str):
        self.status_label.setText(f"실패: {message}")
        # On error, abort the continuous loop so we don't spin on a broken request.
        self._stop_requested = True
        self._pending_count = 0
        self._continuous_mode = False

    def _on_worker_cleanup(self, worker: VariationGenerationWorker):
        if self._active_worker is worker:
            self._active_worker = None
        worker.deleteLater()
        # Release the re-entrancy guard. The next dispatch (if any) claims it
        # again synchronously when it starts.
        self._is_dispatching = False

        if self._stop_requested:
            self._finalize_session("중지됨")
            return

        if self._continuous_mode or self._pending_count > 0:
            # Defer the next dispatch to the event loop so the finished signal
            # has a chance to fully unwind before we start another worker.
            QTimer.singleShot(0, self._dispatch_next_generation)
        else:
            self._finalize_session("생성 완료")

    # -- thumbnail selection + central preview --------------------------

    def _on_thumbnail_clicked(self, card: VariationResultCard):
        self._select_card(card)

    def _select_card(self, card: Optional[VariationResultCard]):
        if self._selected_card is card:
            self._update_preview()
            return
        if self._selected_card is not None:
            self._selected_card.set_selected(False)
        self._selected_card = card
        if card is not None:
            card.set_selected(True)
            # Keep the newly selected thumbnail in view.
            self.result_scroll.ensureWidgetVisible(card)
        self._update_preview()

    def _update_preview(self):
        enhance_busy = self._enhance_worker is not None
        if self._selected_card is None:
            self._preview_source_image = None
            self.preview_label.setPixmap(QPixmap())
            self.preview_label.setText("생성된 결과가 여기 크게 표시됩니다.")
            self.save_btn.setEnabled(False)
            self.save_enhance_btn.setEnabled(False)
            self.discard_btn.setEnabled(False)
            return
        image = self._selected_card.result.get("image")
        if image is None:
            self._preview_source_image = None
            self.preview_label.setPixmap(QPixmap())
            self.preview_label.setText("결과 이미지가 비어있습니다.")
            self.save_btn.setEnabled(False)
            self.save_enhance_btn.setEnabled(False)
            self.discard_btn.setEnabled(not enhance_busy)
            return
        try:
            self._preview_source_image = image.copy()
        except Exception as exc:
            print(f"Failed to clone preview image: {exc}")
            self._preview_source_image = image
        self._render_preview()
        self.save_btn.setEnabled(not enhance_busy)
        # Enhance is NAI-only (img2img pass). Grey the button out in other
        # modes or while another Enhance is already running.
        api_mode = getattr(self.app_context, "current_api_mode", "NAI")
        self.save_enhance_btn.setEnabled(api_mode == "NAI" and not enhance_busy)
        self.discard_btn.setEnabled(not enhance_busy)

    def _render_preview(self):
        if self._preview_source_image is None:
            return
        try:
            preview = self._preview_source_image.copy()
            if preview.mode != "RGBA":
                preview = preview.convert("RGBA")
            target_w = max(self.preview_label.width(), get_scaled_size(420))
            target_h = max(self.preview_label.height(), get_scaled_size(560))
            preview.thumbnail((target_w, target_h), Image.Resampling.LANCZOS)
            self.preview_label.setText("")
            self.preview_label.setPixmap(QPixmap.fromImage(ImageQt(preview)))
        except Exception as exc:
            print(f"Failed to render central preview: {exc}")

    # -- save / discard drive the currently selected card ----------------

    # Save without Enhance: LANCZOS 1.5× upscale to 768×1344 then save.
    # The edit-rect crop is exactly 4:7 so the upscale preserves aspect
    # without letterboxing. This is the fast path — no extra API round trip,
    # but resolution fidelity is capped at what LANCZOS can recover from
    # NAI's post-inpaint 512×896. Users who want a real detail lift should
    # take the "✨ Save with Enhance" path instead.
    _SAVE_UPSCALE_WIDTH: int = 768
    _SAVE_UPSCALE_HEIGHT: int = 1344

    def _on_save_clicked(self):
        card = self._selected_card
        if card is None:
            return
        if not self._character_id:
            QMessageBox.warning(self, "저장 실패", "캐릭터가 선택되어 있지 않습니다.")
            return
        if self._enhance_worker is not None:
            return

        result = card.result
        source_image = result.get("image")
        if source_image is None:
            QMessageBox.warning(self, "저장 실패", "원본 이미지가 없습니다.")
            return

        # Already the target resolution? Skip the resize/re-encode entirely
        # so downstream tooling sees the exact bytes NAI produced.
        if source_image.size == (self._SAVE_UPSCALE_WIDTH, self._SAVE_UPSCALE_HEIGHT):
            raw_bytes = result.get("raw_bytes") or result.get("image_bytes")
            image_to_save = source_image
        else:
            try:
                upscaled = source_image.resize(
                    (self._SAVE_UPSCALE_WIDTH, self._SAVE_UPSCALE_HEIGHT),
                    Image.Resampling.LANCZOS,
                )
            except Exception as exc:
                QMessageBox.critical(self, "저장 실패", f"업스케일 실패: {exc}")
                return
            gen_params = result.get("generation_params") or {}
            raw_bytes = _reencode_with_nai_meta(upscaled, source_image, gen_params)
            image_to_save = upscaled

        try:
            variation_path = save_character_variation(
                self._character_id,
                raw_bytes=raw_bytes,
                image=image_to_save,
            )
        except Exception as exc:
            QMessageBox.critical(self, "저장 실패", str(exc))
            return

        self._drop_card(card)
        self.status_label.setText(
            f"LANCZOS 저장 완료: {variation_path.name} "
            f"({self._SAVE_UPSCALE_WIDTH}×{self._SAVE_UPSCALE_HEIGHT})"
        )
        self.window_ref.refresh_characters_view()

    # -- save with enhance ----------------------------------------------

    # Fixed Enhance settings for variations. The user can still run a custom
    # Enhance from the main UI on the mirrored history copy, but the
    # "Save with Enhance" button always uses the 1.5× / strength 0.2 /
    # noise 0.0 profile because that is the canonical "crisp the inpaint
    # output without changing content" preset for NAI.
    _VARIATION_ENHANCE_UPSCALE: float = 1.5
    # Strength 0.3 (was 0.2): inpaint output is already soft inside the mask,
    # and 0.2 left a noticeable haze on variations. 0.3 gives the Enhance
    # pass enough denoise headroom to crisp up without drifting the content.
    _VARIATION_ENHANCE_STRENGTH: float = 0.3
    _VARIATION_ENHANCE_NOISE: float = 0.0

    def _on_save_with_enhance_clicked(self):
        card = self._selected_card
        if card is None:
            return
        if not self._character_id:
            QMessageBox.warning(self, "저장 실패", "캐릭터가 선택되어 있지 않습니다.")
            return
        if self._enhance_worker is not None:
            return

        api_mode = getattr(self.app_context, "current_api_mode", "NAI")
        if api_mode != "NAI":
            QMessageBox.warning(
                self,
                "Enhance 불가",
                "Enhance는 NAI 모드에서만 사용할 수 있습니다. 일반 Save를 이용하세요.",
            )
            return

        result = card.result
        source_image = result.get("image")
        gen_params = result.get("generation_params") or {}
        if source_image is None:
            QMessageBox.warning(self, "Enhance 실패", "원본 이미지가 없습니다.")
            return
        if not gen_params:
            QMessageBox.warning(
                self,
                "Enhance 실패",
                "생성 파라미터가 없어 Enhance를 수행할 수 없습니다. 일반 Save를 이용하세요.",
            )
            return

        api_service = getattr(self.app_context, "api_service", None)
        if api_service is None:
            QMessageBox.critical(self, "Enhance 실패", "API 서비스가 초기화되지 않았습니다.")
            return

        # Build img2img params off the original generation parameters —
        # mirrors image_window._execute_enhance so the backend sees exactly
        # the same profile a main-UI Enhance would produce.
        import copy as _copy
        import io as _io

        buf = _io.BytesIO()
        source_image.save(buf, format="PNG")
        image_bytes = buf.getvalue()

        orig_w, orig_h = source_image.size
        new_w = self._round_to_64(orig_w * self._VARIATION_ENHANCE_UPSCALE)
        new_h = self._round_to_64(orig_h * self._VARIATION_ENHANCE_UPSCALE)

        params = _copy.deepcopy(gen_params)
        params["image_bytes"] = image_bytes
        params["strength"] = self._VARIATION_ENHANCE_STRENGTH
        params["noise"] = self._VARIATION_ENHANCE_NOISE
        params["width"] = new_w
        params["height"] = new_h
        params["api_mode"] = "NAI"
        # Strip inpaint-specific fields so the API call is a plain img2img.
        # Intentionally keeping ``sketchbook_character_prompts`` so the NAI
        # character block (identity + UC) is still active during the Enhance
        # pass — mirrors image_window._execute_enhance which also preserves
        # the character prompt across Enhance.
        params.pop("type", None)
        params.pop("mask_bytes", None)
        params.pop("cropped_image_request", None)
        params.pop("full_mask_pil", None)

        progress = QProgressDialog("Enhance 처리 중...", None, 0, 0, self)
        progress.setWindowTitle("Save with Enhance")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setCancelButton(None)
        progress.show()

        thread = QThread(self)
        worker = _VariationEnhanceWorker(api_service, params)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.finished.connect(
            lambda r, c=card, p=progress, nw=new_w, nh=new_h: self._handle_enhance_result(r, c, p, nw, nh)
        )
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._enhance_thread = thread
        self._enhance_worker = worker
        self.status_label.setText(f"Save with Enhance 실행 중... → {new_w}×{new_h}")
        self._update_preview()
        thread.start()

    @staticmethod
    def _round_to_64(value: float) -> int:
        return int(round(value / 64)) * 64

    def _handle_enhance_result(
        self,
        result: dict,
        card: VariationResultCard,
        progress: QProgressDialog,
        new_w: int,
        new_h: int,
    ) -> None:
        try:
            progress.close()
        except Exception:
            pass

        self._enhance_thread = None
        self._enhance_worker = None

        if not isinstance(result, dict) or result.get("status") != "success":
            message = "알 수 없는 오류"
            if isinstance(result, dict):
                message = str(result.get("message") or message)
            self.status_label.setText(f"Enhance 실패: {message}")
            self._update_preview()
            QMessageBox.critical(self, "Enhance 실패", message)
            return

        enhanced_bytes = result.get("raw_bytes")
        enhanced_image = result.get("image")
        if enhanced_bytes is None and enhanced_image is None:
            self.status_label.setText("Enhance 실패: 빈 응답")
            self._update_preview()
            return

        try:
            variation_path = save_character_variation(
                self._character_id,
                raw_bytes=enhanced_bytes,
                image=enhanced_image,
            )
        except Exception as exc:
            self.status_label.setText(f"저장 실패: {exc}")
            self._update_preview()
            QMessageBox.critical(self, "저장 실패", str(exc))
            return

        self._drop_card(card)
        self.status_label.setText(
            f"Enhance 저장 완료: {variation_path.name} ({new_w}×{new_h})"
        )
        self.window_ref.refresh_characters_view()
        self._update_preview()

    def _on_discard_clicked(self):
        card = self._selected_card
        if card is None:
            return
        # Guard: don't let a discard run while an Enhance is uploading the
        # same card's image — the worker still references card.result.
        if self._enhance_worker is not None:
            return
        self._drop_card(card)

    def _drop_card(self, card: VariationResultCard):
        """Remove a card from the strip and pick the next newest for preview."""
        if card not in self._result_cards:
            return
        index = self._result_cards.index(card)
        self._result_cards.remove(card)
        if self._selected_card is card:
            self._selected_card = None
        card.setParent(None)
        card.deleteLater()
        self._relayout_results()

        # Newest-first thumbnail order → the replacement is the card at the
        # same index after removal (or one step back if we removed the last).
        if self._result_cards:
            next_index = min(index, len(self._result_cards) - 1)
            self._select_card(self._result_cards[next_index])
        else:
            self._select_card(None)

    def _relayout_results(self):
        """Arrange thumbnails in a 2-column strip, newest-first."""
        while self.result_layout.count():
            item = self.result_layout.takeAt(0)
            if item is not None and item.widget() is not None:
                item.widget().setParent(self.result_host)

        if not self._result_cards:
            return

        cols = 2
        # Newest-first visual order — most recently appended should appear at top.
        ordered = list(reversed(self._result_cards))
        for index, card in enumerate(ordered):
            self.result_layout.addWidget(card, index // cols, index % cols)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._render_preview)

    # -- persistent defaults (Main Prompt / 추가 Negative) --------------

    # NAI 2-panel reference-inset trick defaults: the left half of the
    # 1152×896 canvas holds the primary, the right half is the editable
    # rectangle. Framing the generation as a 2koma panel (with "border" in
    # the negative) keeps the trace clean — these are the first-open
    # defaults only; the user can override and the override persists.
    _DEFAULT_MAIN_PROMPT: str = "2koma, borderless panel"
    _DEFAULT_NEGATIVE_PROMPT: str = "border"

    def _variation_defaults_path(self) -> Path:
        """Return path under save/character_asset/ so the file sits alongside
        the asset store and travels with backups of that directory."""
        return CHARACTER_ASSET_CHARACTERS_DIR.parent / "variations_defaults.json"

    def _load_variation_defaults(self) -> None:
        """Populate Main Prompt / 추가 Negative from the last-used values on
        disk, falling back to the hard-coded 2koma defaults on first open."""
        main_text = self._DEFAULT_MAIN_PROMPT
        negative_text = self._DEFAULT_NEGATIVE_PROMPT
        path = self._variation_defaults_path()
        try:
            if path.exists():
                with path.open("r", encoding="utf-8") as fh:
                    data = json.load(fh) or {}
                stored_main = data.get("main_prompt")
                stored_negative = data.get("negative_prompt")
                if isinstance(stored_main, str):
                    main_text = stored_main
                if isinstance(stored_negative, str):
                    negative_text = stored_negative
        except Exception as exc:
            print(f"Failed to load variation defaults: {exc}")

        # Block the textChanged→save round-trip while we programmatically set
        # the initial text. Otherwise the load itself would overwrite the
        # file with whatever intermediate state the editors pass through.
        self._suppress_defaults_save = True
        try:
            self.main_prompt_edit.setPlainText(main_text)
            self.negative_prompt_edit.setPlainText(negative_text)
        finally:
            self._suppress_defaults_save = False

    def _save_variation_defaults(self) -> None:
        """Write the current Main Prompt and 추가 Negative to disk so the next
        open restores them. Skipped while _load_variation_defaults is running
        to avoid a self-overwrite loop."""
        if self._suppress_defaults_save:
            return
        path = self._variation_defaults_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "main_prompt": self.main_prompt_edit.toPlainText(),
                "negative_prompt": self.negative_prompt_edit.toPlainText(),
            }
            with path.open("w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
        except Exception as exc:
            print(f"Failed to save variation defaults: {exc}")

    def shutdown(self):
        """Stop the continuous loop and any in-flight worker so the window can
        close cleanly."""
        self._stop_requested = True
        self._pending_count = 0
        self._continuous_mode = False

        # Shut down the Enhance worker first — it holds a QProgressDialog
        # reference that should disappear before we start tearing down the
        # generation worker.
        enhance_thread = self._enhance_thread
        if enhance_thread is not None:
            try:
                enhance_thread.quit()
                enhance_thread.wait(3000)
            except Exception:
                pass
        self._enhance_thread = None
        self._enhance_worker = None

        worker = self._active_worker
        if worker is None:
            return
        try:
            if worker.isRunning():
                worker.quit()
                worker.wait(3000)
        except Exception:
            pass
        self._active_worker = None


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------


class CharacterAssetStorageWindow(QMainWindow):
    """Independent window hosting Characters / Variations tabs."""

    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app_context = app_context

        self.setWindowTitle("캐릭터 에셋")

        # 화면 가용 영역의 90%를 넘지 않도록 클램프 — DPI 스케일링이 큰 환경에서
        # 초기 크기가 화면 밖으로 벗어나는 것을 막는다.
        screen = QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            default_w = min(get_scaled_size(1480), int(geo.width() * 0.9))
            default_h = min(get_scaled_size(940), int(geo.height() * 0.9))
            min_w = min(get_scaled_size(1080), int(geo.width() * 0.8))
            min_h = min(get_scaled_size(680), int(geo.height() * 0.8))
        else:
            default_w, default_h = get_scaled_size(1480), get_scaled_size(940)
            min_w, min_h = get_scaled_size(1080), get_scaled_size(680)
        self.resize(default_w, default_h)
        self.setMinimumSize(min_w, min_h)
        self.setStyleSheet(f"""
            QMainWindow {{ background-color: {DARK_COLORS['bg_primary']}; }}
            QTabWidget::pane {{ border: 1px solid {DARK_COLORS['border']}; background-color: {DARK_COLORS['bg_primary']}; }}
            QTabBar::tab {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                padding: {get_scaled_size(8)}px {get_scaled_size(16)}px;
                border: 1px solid {DARK_COLORS['border']};
                border-bottom: none;
            }}
            QTabBar::tab:selected {{
                background-color: {DARK_COLORS['accent_blue']};
                color: white;
            }}
        """)

        # Ensure data layout is ready (run migration idempotently).
        try:
            migrate_legacy_flat_layout()
        except Exception as exc:
            print(f"Legacy asset migration skipped: {exc}")

        self.tabs = QTabWidget(self)
        self.characters_tab = CharactersTab(self, self.tabs)
        self.variations_tab = VariationsTab(self, self.tabs)
        self.tabs.addTab(self.characters_tab, "Characters")
        self.tabs.addTab(self.variations_tab, "Variations")
        self.setCentralWidget(self.tabs)

        self.characters_tab.variations_requested.connect(self._switch_to_variations_for)

        self.load_storage_items()

    # -- public API kept compatible with prior versions -----------------

    def load_storage_items(self):
        self.characters_tab.load_characters()

    def refresh_characters_view(self):
        self.characters_tab.load_characters()

    # -- action routing --------------------------------------------------

    def apply_c1_only(self, image_path: Path):
        metadata = load_character_asset_metadata(image_path.stem, image_path)
        prompt = (metadata or {}).get("character_prompt", "").strip()
        uc = (metadata or {}).get("character_uc", "").strip()
        if not prompt:
            QMessageBox.warning(self, "적용 실패", "이미지에서 캐릭터 프롬프트를 복구할 수 없습니다.")
            return

        character_module = self._get_character_module()
        if character_module is None:
            QMessageBox.warning(self, "적용 실패", "CharacterModule을 찾을 수 없습니다.")
            return
        character_module.assign_c1(prompt, uc)

    def apply_c1_with_reference(self, image_path: Path):
        self.apply_c1_only(image_path)
        main_window = getattr(self.app_context, "main_window", None)
        if main_window and hasattr(main_window, "apply_character_asset_reference_from_image_path"):
            try:
                main_window.apply_character_asset_reference_from_image_path(str(image_path))
            except Exception as exc:
                print(f"Failed to apply character asset reference: {exc}")

    def _get_character_module(self):
        try:
            return self.app_context.middle_section_controller.get_module_instance("CharacterModule")
        except Exception as exc:
            print(f"Failed to resolve CharacterModule: {exc}")
            return None

    # -- tab switching --------------------------------------------------

    def _switch_to_variations_for(self, character_id: str):
        record = next((r for r in list_characters() if r.character_id == character_id), None)
        if record is None:
            return
        self.variations_tab.bind_character(character_id, record.primary_path)
        self.tabs.setCurrentWidget(self.variations_tab)

    # -- lifecycle ------------------------------------------------------

    def closeEvent(self, event):
        # Stop any in-flight variation worker so the window can close cleanly.
        try:
            self.variations_tab.shutdown()
        except Exception:
            pass
        super().closeEvent(event)
