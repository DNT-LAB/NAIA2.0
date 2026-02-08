"""
ArtistThumbnailFrame - Individual artist thumbnail frame for Gallery Window
"""

from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy, QPushButton, QApplication
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QPixmap, QCursor
from ui.theme import DARK_COLORS
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
import base64


class ArtistThumbnailFrame(QFrame):
    """Individual artist thumbnail frame with favorite toggle"""

    # Signals
    favorite_toggled = pyqtSignal(str, bool)  # (artist_name, is_favorite)
    artist_clicked = pyqtSignal(str)          # artist_name
    generate_requested = pyqtSignal(str)      # artist_name - request generation
    add_to_combo_requested = pyqtSignal(str)  # artist_name - 우클릭 시 태그 조합에 추가

    def __init__(self, artist_name: str, thumbnail_data: str = None,
                 is_favorite: bool = False, parent=None):
        super().__init__(parent)
        self.artist_name = artist_name
        self.thumbnail_data = thumbnail_data  # base64 encoded
        self.is_favorite = is_favorite
        self._pixmap_original = None  # Store original pixmap for resizing

        self.setFrameStyle(QFrame.Shape.Box)
        self.setLineWidth(1)

        # Frame sizing
        self.setMinimumSize(get_scaled_size(180), get_scaled_size(220))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Base frame style
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 5px;
            }}
        """)

        self._create_ui()
        self._load_thumbnail()
        self._update_favorite_style()

    def _create_ui(self):
        """Create the frame UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        # 1. Header - Artist tag + favorite star
        header = self._create_header()
        layout.addWidget(header)

        # 2. Thumbnail image area (expanding)
        self.image_label = self._create_image_display()
        layout.addWidget(self.image_label, 1)

    def _create_header(self) -> QFrame:
        """Create header with artist tag (5), copy button (1), generate button (1)"""
        self.header_frame = QFrame()
        self.header_frame.setFixedHeight(get_scaled_size(32))
        self.header_frame.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        layout = QHBoxLayout(self.header_frame)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(3)

        # Artist name button (5 parts) - clickable for favorite toggle
        self.artist_btn = QPushButton(self.artist_name)
        self.artist_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.artist_btn.setToolTip(f"{self.artist_name}\n좌클릭: 관심 작가 토글\n우클릭: 태그 조합에 추가")
        self.artist_btn.clicked.connect(self._on_header_clicked)
        self.artist_btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.artist_btn.customContextMenuRequested.connect(self._on_right_click)
        layout.addWidget(self.artist_btn, 5)

        # Favorite star label (inside artist button area)
        self.star_label = QLabel("★")
        self.star_label.setFixedWidth(get_scaled_size(18))
        self.star_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.star_label)

        # Copy button (1 part)
        self.copy_btn = QPushButton("📋")
        self.copy_btn.setFixedWidth(get_scaled_size(32))
        self.copy_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.copy_btn.setToolTip("작가명 복사")
        self.copy_btn.clicked.connect(self._on_copy_clicked)
        self.copy_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 3px;
                font-size: {get_scaled_font_size(12)}px;
                padding: 2px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
        """)
        layout.addWidget(self.copy_btn, 1)

        # Generate button (1 part)
        self.gen_btn = QPushButton("🎨")
        self.gen_btn.setFixedWidth(get_scaled_size(32))
        self.gen_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.gen_btn.setToolTip("이 작가로 생성")
        self.gen_btn.clicked.connect(self._on_generate_clicked)
        self.gen_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['accent_blue']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['accent_blue']};
                border-radius: 3px;
                font-size: {get_scaled_font_size(12)}px;
                padding: 2px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['accent_blue_hover']};
            }}
        """)
        layout.addWidget(self.gen_btn, 1)

        return self.header_frame

    def _create_image_display(self) -> QLabel:
        """Create expanding image display area"""
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setMinimumSize(get_scaled_size(150), get_scaled_size(150))
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        label.setScaledContents(False)
        label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        label.setStyleSheet(f"""
            QLabel {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 3px;
            }}
        """)

        # Make image clickable to select artist
        label.mousePressEvent = self._on_image_clicked

        return label

    def _load_thumbnail(self):
        """Load and display thumbnail from base64 data"""
        if not self.thumbnail_data:
            self._set_placeholder()
            return

        try:
            img_bytes = base64.b64decode(self.thumbnail_data)
            pixmap = QPixmap()
            pixmap.loadFromData(img_bytes)

            if pixmap.isNull():
                self._set_placeholder()
                return

            # Crop black borders (85px from each side)
            if pixmap.width() > 170:
                self._pixmap_original = pixmap.copy(
                    85, 0,
                    pixmap.width() - 170,
                    pixmap.height()
                )
            else:
                self._pixmap_original = pixmap

            self._update_image_display()

        except Exception as e:
            print(f"Thumbnail load error for {self.artist_name}: {e}")
            self._set_placeholder()

    def _update_image_display(self):
        """Update image display to fit current label size"""
        if self._pixmap_original and not self._pixmap_original.isNull():
            scaled = self._pixmap_original.scaled(
                self.image_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.image_label.setPixmap(scaled)

    def _set_placeholder(self):
        """Set placeholder when no image available"""
        self.image_label.setText("No Image")
        self.image_label.setStyleSheet(f"""
            QLabel {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 3px;
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(12)}px;
            }}
        """)

    def _update_favorite_style(self):
        """Update header and star style based on favorite status"""
        if self.is_favorite:
            # Favorite artist - green background, gold star
            self.artist_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: #2d5a2d;
                    color: {DARK_COLORS['text_primary']};
                    border: none;
                    border-radius: 3px;
                    font-size: {get_scaled_font_size(13)}px;
                    padding: 2px 6px;
                    text-align: left;
                }}
                QPushButton:hover {{
                    background-color: #3d6a3d;
                }}
            """)
            self.star_label.setStyleSheet(f"""
                QLabel {{
                    color: #ffd700;
                    font-size: {get_scaled_font_size(14)}px;
                    font-weight: bold;
                    background: transparent;
                    border: none;
                }}
            """)
            self.star_label.setText("★")
        else:
            # Non-favorite - dark background, dim star
            self.artist_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {DARK_COLORS['bg_primary']};
                    color: {DARK_COLORS['text_primary']};
                    border: none;
                    border-radius: 3px;
                    font-size: {get_scaled_font_size(13)}px;
                    padding: 2px 6px;
                    text-align: left;
                }}
                QPushButton:hover {{
                    background-color: {DARK_COLORS['bg_hover']};
                }}
            """)
            self.star_label.setStyleSheet(f"""
                QLabel {{
                    color: {DARK_COLORS['text_secondary']};
                    font-size: {get_scaled_font_size(14)}px;
                    background: transparent;
                    border: none;
                }}
            """)
            self.star_label.setText("☆")

    def _on_header_clicked(self):
        """Handle header click - toggle favorite"""
        self.is_favorite = not self.is_favorite
        self._update_favorite_style()
        self.favorite_toggled.emit(self.artist_name, self.is_favorite)

    def _on_copy_clicked(self):
        """Handle copy button click - copy artist name to clipboard"""
        clipboard = QApplication.clipboard()
        clipboard.setText(self.artist_name)

    def _on_generate_clicked(self):
        """Handle generate button click - request generation with this artist"""
        self.generate_requested.emit(self.artist_name)

    def _on_right_click(self, pos):
        """Handle right click on artist button - add to tag combo"""
        self.add_to_combo_requested.emit(self.artist_name)

    def _on_image_clicked(self, event):
        """Handle image click - select artist"""
        self.artist_clicked.emit(self.artist_name)

    def set_favorite(self, is_favorite: bool):
        """Set favorite status externally"""
        self.is_favorite = is_favorite
        self._update_favorite_style()

    def resizeEvent(self, event):
        """Handle resize - update image display"""
        super().resizeEvent(event)
        if self._pixmap_original:
            self._update_image_display()

    def set_uniform_size(self, width: int, height: int):
        """Set uniform fixed size for this frame"""
        self.setFixedSize(width, height)
        if self._pixmap_original:
            self._update_image_display()
