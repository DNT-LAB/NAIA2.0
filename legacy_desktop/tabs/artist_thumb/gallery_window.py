"""
ArtistGalleryWindow - 4x3 grid gallery window for browsing artist thumbnails
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QSpinBox, QFrame, QWidget, QSizePolicy, QTextEdit
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QKeyEvent, QShortcut, QKeySequence
from ui.theme import DARK_COLORS
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from legacy_desktop.tabs.artist_thumb.artist_frame import ArtistThumbnailFrame
import math


class ArtistGalleryWindow(QDialog):
    """4x2 grid gallery window for browsing artist thumbnails"""

    # Signals
    favorite_toggled = pyqtSignal(str, bool)  # (artist_name, is_favorite)
    artist_clicked = pyqtSignal(str)          # artist_name
    generate_requested = pyqtSignal(str)      # artist_name - request generation
    custom_generate_requested = pyqtSignal(str)  # custom artist tags - request generation

    COLUMNS = 4
    ROWS = 2
    ITEMS_PER_PAGE = COLUMNS * ROWS  # 8

    def __init__(self, artist_data: dict, artist_list: list,
                 favorite_artists: list, current_mode: str, parent=None,
                 title_suffix: str = "", app_context=None):
        super().__init__(parent)
        self.artist_data = artist_data
        self.artist_list = artist_list  # Sorted list of artist names
        self.favorite_artists = set(favorite_artists)  # Use set for O(1) lookup
        self.current_mode = current_mode
        self.title_suffix = title_suffix  # 필터 옵션에 따른 타이틀 접미사
        self.app_context = app_context  # AppContext for API mode detection

        self.current_page = 0
        self.total_pages = max(1, math.ceil(len(self.artist_list) / self.ITEMS_PER_PAGE))
        self.frames: list[ArtistThumbnailFrame] = []

        # Resize debounce timer
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._update_frame_sizes)

        self._setup_window()
        self._create_ui()
        self._load_page(0)

    def _setup_window(self):
        """Setup window properties"""
        self.setWindowTitle(f"Artist Gallery - {self.current_mode}{self.title_suffix}")
        self.setMinimumSize(get_scaled_size(900), get_scaled_size(550))
        self.resize(get_scaled_size(1400), get_scaled_size(750))

        # 최소화/최대화 버튼 추가 (일반 윈도우처럼 동작)
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowMinimizeButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint |
            Qt.WindowType.WindowCloseButtonHint
        )

        # Dark theme
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {DARK_COLORS['bg_primary']};
            }}
        """)

        # Keyboard shortcuts (using QShortcut for focus-independent handling)
        self._setup_shortcuts()

    def _setup_shortcuts(self):
        """Setup keyboard shortcuts"""
        # Left arrow / A - previous page
        QShortcut(QKeySequence(Qt.Key.Key_Left), self, self._prev_page)
        QShortcut(QKeySequence(Qt.Key.Key_A), self, self._prev_page)

        # Right arrow / D - next page
        QShortcut(QKeySequence(Qt.Key.Key_Right), self, self._next_page)
        QShortcut(QKeySequence(Qt.Key.Key_D), self, self._next_page)

        # Home - first page
        QShortcut(QKeySequence(Qt.Key.Key_Home), self, lambda: self._load_page(0))

        # End - last page
        QShortcut(QKeySequence(Qt.Key.Key_End), self, lambda: self._load_page(self.total_pages - 1))

        # Escape - blocked (do nothing)

    def _create_ui(self):
        """Create the gallery UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # 1. Grid container
        self.grid_container = self._create_grid_container()
        layout.addWidget(self.grid_container, 1)

        # 2. Pagination bar
        pagination = self._create_pagination_bar()
        layout.addWidget(pagination)

    def _create_grid_container(self) -> QWidget:
        """Create the 4x3 grid container"""
        container = QWidget()
        container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.grid_layout = QGridLayout(container)
        self.grid_layout.setContentsMargins(5, 5, 5, 5)
        self.grid_layout.setSpacing(8)

        # Set equal stretch for all columns and rows
        for col in range(self.COLUMNS):
            self.grid_layout.setColumnStretch(col, 1)
        for row in range(self.ROWS):
            self.grid_layout.setRowStretch(row, 1)

        # Create placeholder frames
        for row in range(self.ROWS):
            for col in range(self.COLUMNS):
                frame = ArtistThumbnailFrame("", None, False, container)
                frame.favorite_toggled.connect(self._on_frame_favorite_toggled)
                frame.artist_clicked.connect(self._on_frame_artist_clicked)
                frame.generate_requested.connect(self._on_frame_generate_requested)
                frame.add_to_combo_requested.connect(self._on_frame_add_to_combo)
                frame.hide()  # Hide initially
                self.grid_layout.addWidget(frame, row, col)
                self.frames.append(frame)

        return container

    def _create_pagination_bar(self) -> QFrame:
        """Create pagination navigation bar with artist tag combination input"""
        bar = QFrame()
        bar.setFixedHeight(get_scaled_size(66))  # Tight fit around TextEdit
        bar.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 5px;
            }}
        """)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(15, 8, 15, 8)
        layout.setSpacing(10)

        # Common height for buttons and labels
        btn_height = get_scaled_size(36)

        # Button style
        nav_btn_style = f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 8px 16px;
                font-size: {get_scaled_font_size(14)}px;
                min-width: {get_scaled_size(50)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
            QPushButton:pressed {{
                background-color: {DARK_COLORS['bg_pressed']};
            }}
            QPushButton:disabled {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_disabled']};
            }}
        """

        # Label style with fixed height matching buttons
        label_style = f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(13)}px;
            }}
        """

        # Previous button
        self.prev_btn = QPushButton("<")
        self.prev_btn.setStyleSheet(nav_btn_style)
        self.prev_btn.setFixedHeight(btn_height)
        self.prev_btn.setToolTip("Previous page (←)")
        self.prev_btn.clicked.connect(self._prev_page)
        layout.addWidget(self.prev_btn)

        # Page indicator
        self.page_label = QLabel()
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_label.setFixedHeight(btn_height)
        self.page_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(14)}px;
                min-width: {get_scaled_size(100)}px;
            }}
        """)
        layout.addWidget(self.page_label)

        # Next button
        self.next_btn = QPushButton(">")
        self.next_btn.setStyleSheet(nav_btn_style)
        self.next_btn.setFixedHeight(btn_height)
        self.next_btn.setToolTip("Next page (→)")
        self.next_btn.clicked.connect(self._next_page)
        layout.addWidget(self.next_btn)

        # Separator 1
        separator1 = QFrame()
        separator1.setFrameShape(QFrame.Shape.VLine)
        separator1.setStyleSheet(f"background-color: {DARK_COLORS['border']};")
        layout.addWidget(separator1)

        # Artist tag combination section
        tag_combo_label = QLabel("작가 태그 조합:")
        tag_combo_label.setFixedHeight(btn_height)
        tag_combo_label.setStyleSheet(label_style)
        layout.addWidget(tag_combo_label)

        self.tag_combo_edit = QTextEdit()
        self.tag_combo_edit.setFixedHeight(get_scaled_size(50))  # 2 lines height
        self.tag_combo_edit.setMinimumWidth(get_scaled_size(250))
        self.tag_combo_edit.setPlaceholderText("artist:name1, artist:name2, ...")
        self.tag_combo_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 4px 8px;
                font-size: {get_scaled_font_size(16)}px;
            }}
        """)
        layout.addWidget(self.tag_combo_edit, 1)  # Stretch factor 1

        # Generate button (for custom artist tags)
        generate_btn_style = f"""
            QPushButton {{
                background-color: {DARK_COLORS['accent_blue']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['accent_blue']};
                border-radius: 4px;
                padding: 8px 16px;
                font-size: {get_scaled_font_size(14)}px;
                font-weight: bold;
                min-width: {get_scaled_size(60)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['accent_blue_hover']};
            }}
            QPushButton:pressed {{
                background-color: {DARK_COLORS['accent_blue']};
            }}
        """
        self.custom_gen_btn = QPushButton("생성")
        self.custom_gen_btn.setStyleSheet(generate_btn_style)
        self.custom_gen_btn.setFixedHeight(btn_height)
        self.custom_gen_btn.setToolTip("입력한 작가 태그로 생성")
        self.custom_gen_btn.clicked.connect(self._on_custom_generate)
        layout.addWidget(self.custom_gen_btn)

        # Separator 2
        separator2 = QFrame()
        separator2.setFrameShape(QFrame.Shape.VLine)
        separator2.setStyleSheet(f"background-color: {DARK_COLORS['border']};")
        layout.addWidget(separator2)

        # Page jump section
        jump_label = QLabel("페이지 이동:")
        jump_label.setFixedHeight(btn_height)
        jump_label.setStyleSheet(label_style)
        layout.addWidget(jump_label)

        self.page_spinbox = QSpinBox()
        self.page_spinbox.setMinimum(1)
        self.page_spinbox.setMaximum(self.total_pages)
        self.page_spinbox.setValue(1)
        self.page_spinbox.setFixedWidth(get_scaled_size(70))
        self.page_spinbox.setFixedHeight(btn_height)
        self.page_spinbox.setStyleSheet(f"""
            QSpinBox {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 4px 8px;
                font-size: {get_scaled_font_size(13)}px;
            }}
            QSpinBox::up-button, QSpinBox::down-button {{
                background-color: {DARK_COLORS['bg_hover']};
                border: none;
                width: {get_scaled_size(16)}px;
            }}
        """)
        layout.addWidget(self.page_spinbox)

        # Jump button
        jump_btn = QPushButton("이동")
        jump_btn.setStyleSheet(nav_btn_style)
        jump_btn.setFixedHeight(btn_height)
        jump_btn.clicked.connect(self._jump_to_page)
        layout.addWidget(jump_btn)

        return bar

    def _on_custom_generate(self):
        """Handle custom generate button click - generate with custom artist tags"""
        custom_tags = self.tag_combo_edit.toPlainText().strip()
        if custom_tags:
            self.custom_generate_requested.emit(custom_tags)

    def _load_page(self, page: int):
        """Load artists for the specified page"""
        if page < 0 or page >= self.total_pages:
            return

        self.current_page = page
        start_idx = page * self.ITEMS_PER_PAGE
        end_idx = min(start_idx + self.ITEMS_PER_PAGE, len(self.artist_list))

        # Update frames
        for i, frame in enumerate(self.frames):
            artist_idx = start_idx + i

            if artist_idx < end_idx:
                artist_name = self.artist_list[artist_idx]
                thumbnail_data = None

                # Get thumbnail data
                img_data_list = self.artist_data.get(artist_name, [])
                if img_data_list and img_data_list[0]:
                    thumbnail_data = img_data_list[0]

                is_favorite = artist_name in self.favorite_artists

                # Update frame
                frame.artist_name = artist_name
                frame.thumbnail_data = thumbnail_data
                frame.is_favorite = is_favorite
                frame.artist_btn.setText(artist_name)
                frame.artist_btn.setToolTip(f"{artist_name}\n좌클릭: 관심 작가 토글\n우클릭: 태그 조합에 추가")
                frame._load_thumbnail()
                frame._update_favorite_style()
                frame.show()
            else:
                frame.hide()

        # Update pagination controls
        self._update_pagination_ui()

        # Update frame sizes after loading
        QTimer.singleShot(10, self._update_frame_sizes)

    def _update_pagination_ui(self):
        """Update pagination UI elements"""
        self.page_label.setText(f"페이지 {self.current_page + 1} / {self.total_pages}")
        self.prev_btn.setEnabled(self.current_page > 0)
        self.next_btn.setEnabled(self.current_page < self.total_pages - 1)
        self.page_spinbox.setValue(self.current_page + 1)
        self.page_spinbox.setMaximum(self.total_pages)

    def _prev_page(self):
        """Go to previous page"""
        if self.current_page > 0:
            self._load_page(self.current_page - 1)

    def _next_page(self):
        """Go to next page"""
        if self.current_page < self.total_pages - 1:
            self._load_page(self.current_page + 1)

    def _jump_to_page(self):
        """Jump to page specified in spinbox"""
        target_page = self.page_spinbox.value() - 1  # Convert to 0-indexed
        if 0 <= target_page < self.total_pages:
            self._load_page(target_page)

    def _on_frame_favorite_toggled(self, artist_name: str, is_favorite: bool):
        """Handle favorite toggle from frame"""
        if is_favorite:
            self.favorite_artists.add(artist_name)
        else:
            self.favorite_artists.discard(artist_name)

        self.favorite_toggled.emit(artist_name, is_favorite)

    def _on_frame_artist_clicked(self, artist_name: str):
        """Handle artist click from frame"""
        self.artist_clicked.emit(artist_name)

    def _on_frame_generate_requested(self, artist_name: str):
        """Handle generate request from frame"""
        self.generate_requested.emit(artist_name)

    def _on_frame_add_to_combo(self, artist_name: str):
        """Handle add to combo request from frame - 우클릭 시 태그 조합에 추가"""
        # AppContext에서 현재 API 모드 확인
        is_nai_mode = (
            self.app_context and
            hasattr(self.app_context, 'current_api_mode') and
            self.app_context.current_api_mode == "NAI"
        )

        # 현재 모드에 따라 태그 형식 결정
        if is_nai_mode:
            # NAI 모드: "1.0::artist:작가명 ::, " 형식
            formatted_tag = f"1.0::artist:{artist_name} ::, "
        else:
            # 기타 모드: 괄호 이스케이프만 수행 (artist: 접두사 없음)
            escaped_name = artist_name.replace("(", "\\(").replace(")", "\\)")
            formatted_tag = f"{escaped_name}, "

        # 현재 텍스트에 추가
        current_text = self.tag_combo_edit.toPlainText()
        self.tag_combo_edit.setPlainText(current_text + formatted_tag)

        # 커서를 끝으로 이동
        cursor = self.tag_combo_edit.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.tag_combo_edit.setTextCursor(cursor)

    def _update_frame_sizes(self):
        """Update all frame sizes to fit grid uniformly"""
        if not self.frames:
            return

        # Calculate available size
        container_size = self.grid_container.size()
        margins = self.grid_layout.contentsMargins()
        spacing = self.grid_layout.spacing()

        available_width = container_size.width() - margins.left() - margins.right()
        available_height = container_size.height() - margins.top() - margins.bottom()

        # Calculate frame size
        frame_width = (available_width - (self.COLUMNS - 1) * spacing) // self.COLUMNS
        frame_height = (available_height - (self.ROWS - 1) * spacing) // self.ROWS

        # Apply uniform size to all visible frames
        for frame in self.frames:
            if frame.isVisible():
                frame.set_uniform_size(frame_width, frame_height)

    def resizeEvent(self, event):
        """Handle window resize with debouncing"""
        super().resizeEvent(event)
        # Debounce resize updates
        self._resize_timer.start(50)

    def wheelEvent(self, event):
        """Handle mouse wheel for page navigation"""
        delta = event.angleDelta().y()
        if delta > 0:
            # Scroll up - previous page
            self._prev_page()
        elif delta < 0:
            # Scroll down - next page
            self._next_page()
        event.accept()

    def keyPressEvent(self, event):
        """Block Escape key from closing the dialog"""
        if event.key() == Qt.Key.Key_Escape:
            event.ignore()  # Block ESC
            return
        super().keyPressEvent(event)

    def update_favorite_status(self, artist_name: str, is_favorite: bool):
        """Update favorite status from external source (sync with main tab)"""
        if is_favorite:
            self.favorite_artists.add(artist_name)
        else:
            self.favorite_artists.discard(artist_name)

        # Update visible frame if it shows this artist
        for frame in self.frames:
            if frame.isVisible() and frame.artist_name == artist_name:
                frame.set_favorite(is_favorite)
                break
