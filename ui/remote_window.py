# ui/remote_window.py
"""
리모트 컨트롤 창 - 모듈 통합 제어 UI
"""

import json
from pathlib import Path
from PIL import Image
from io import BytesIO

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QTabWidget, QLabel, QComboBox, QTextEdit, QPushButton,
    QScrollArea, QFrame, QMessageBox, QApplication, QSizePolicy,
    QCheckBox, QSlider, QFileDialog, QInputDialog, QLineEdit, QDialog,
    QRadioButton, QButtonGroup
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QSize
from PyQt6.QtGui import QAction, QPixmap, QImage

from ui.theme import DARK_COLORS, DARK_STYLES
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from modules.character_module import CharacterSearchDialog


# 즐겨찾기 썸네일 기본 크기 상수
FAVORITE_THUMB_WIDTH = 120
FAVORITE_THUMB_HEIGHT = 167  # 368:512 비율 유지
PREVIEW_THUMB_WIDTH = 140
PREVIEW_THUMB_HEIGHT = 195
THUMB_ASPECT_RATIO = 368 / 512  # 가로/세로 비율

# 캐릭터 레퍼런스 즐겨찾기 상수
CHAR_REF_FAVORITES_DIR = Path("save/character_reference/favorites")
CHAR_REF_FAVORITES_JSON = Path("save/character_reference/favorites.json")
CHAR_REF_FOLDERS_JSON = Path("save/character_reference/favorite_folders.json")

# 캐릭터 프롬프트 즐겨찾기 상수
CHAR_PROMPT_FAVORITES_DIR = Path("save/character_prompt_favorites")
CHAR_PROMPT_FAVORITES_JSON = Path("save/character_prompt_favorites/favorites.json")
CHAR_PROMPT_FOLDERS_JSON = Path("save/character_prompt_favorites/folders.json")
# 즐겨찾기 그리드 썸네일 - 한 줄에 4개 배치
CHAR_PROMPT_THUMB_WIDTH = 144
CHAR_PROMPT_THUMB_HEIGHT = 200  # 368:512 비율 유지
# 즐겨찾기 관리 탭용 더 큰 썸네일
CHAR_PROMPT_MANAGE_THUMB_WIDTH = 150
CHAR_PROMPT_MANAGE_THUMB_HEIGHT = 208

# 🆕 이벤트 저장 상수
REMOTE_EVENTS_DIR = Path("save/remote_events")
REMOTE_EVENTS_JSON = Path("save/remote_events/events.json")
REMOTE_EVENTS_THUMBS_DIR = Path("save/remote_events/thumbnails")
# 이벤트 썸네일 크기 = 프리셋-프리셋 썸네일과 동일 (120x167)
EVENT_THUMB_WIDTH = FAVORITE_THUMB_WIDTH  # 120
EVENT_THUMB_HEIGHT = FAVORITE_THUMB_HEIGHT  # 167


class PresetFavoriteItemWidget(QFrame):
    """즐겨찾기 프리셋 아이템 위젯 (동적 크기 지원)"""

    clicked = pyqtSignal(str)  # preset_name

    def __init__(self, preset_name: str, thumbnail_path: Path = None,
                 thumb_width: int = None, thumb_height: int = None, parent=None):
        super().__init__(parent)
        self.preset_name = preset_name
        self.thumbnail_path = thumbnail_path

        # 동적 크기 설정 (기본값 사용 가능)
        self.thumb_width = thumb_width or FAVORITE_THUMB_WIDTH
        self.thumb_height = thumb_height or FAVORITE_THUMB_HEIGHT

        self.setFixedSize(self.thumb_width + 10, self.thumb_height + 35)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 6px;
            }}
            QFrame:hover {{
                border: 2px solid {DARK_COLORS['accent_blue']};
                background-color: {DARK_COLORS['bg_secondary']};
            }}
        """)

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(4)

        # 썸네일 이미지
        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(self.thumb_width, self.thumb_height)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setStyleSheet(f"""
            QLabel {{
                background-color: {DARK_COLORS['bg_primary']};
                border-radius: 4px;
            }}
        """)

        if self.thumbnail_path and self.thumbnail_path.exists():
            pixmap = QPixmap(str(self.thumbnail_path))
            scaled = pixmap.scaled(
                self.thumb_width, self.thumb_height,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.thumb_label.setPixmap(scaled)
        else:
            self.thumb_label.setText("📷")
            self.thumb_label.setStyleSheet(f"""
                QLabel {{
                    background-color: {DARK_COLORS['bg_primary']};
                    border-radius: 4px;
                    color: {DARK_COLORS['text_disabled']};
                    font-size: {get_scaled_font_size(24)}px;
                }}
            """)

        layout.addWidget(self.thumb_label)

        # 프리셋 이름 (폰트 크기 +3px)
        name_label = QLabel(self.preset_name)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setWordWrap(True)
        name_label.setMaximumHeight(28)
        name_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(14)}px;
                background-color: transparent;
                border: none;
            }}
        """)
        layout.addWidget(name_label)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.preset_name)
        super().mousePressEvent(event)


class CharRefFavoriteItemWidget(QFrame):
    """캐릭터 레퍼런스 즐겨찾기 아이템 위젯 (2줄 라벨: 이름 + Style/Fidelity)"""

    clicked = pyqtSignal(dict)  # favorite_data

    def __init__(self, favorite_data: dict, thumbnail_path: Path = None,
                 thumb_width: int = None, thumb_height: int = None,
                 is_selected: bool = False, parent=None):
        super().__init__(parent)
        self.favorite_data = favorite_data
        self.thumbnail_path = thumbnail_path
        self._is_selected = is_selected

        # 동적 크기 설정 (기본값 사용 가능)
        self.thumb_width = thumb_width or FAVORITE_THUMB_WIDTH
        self.thumb_height = thumb_height or FAVORITE_THUMB_HEIGHT

        # 2줄 라벨을 위해 높이 추가
        self.setFixedSize(self.thumb_width + 10, self.thumb_height + 50)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_style()
        self._init_ui()

    def _update_style(self):
        """선택 상태에 따른 스타일 업데이트"""
        if self._is_selected:
            self.setStyleSheet(f"""
                QFrame {{
                    background-color: {DARK_COLORS['bg_secondary']};
                    border: 2px solid {DARK_COLORS['success']};
                    border-radius: 6px;
                }}
                QFrame:hover {{
                    border-color: {DARK_COLORS['success']};
                    background-color: {DARK_COLORS['bg_hover']};
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QFrame {{
                    background-color: {DARK_COLORS['bg_tertiary']};
                    border: 1px solid {DARK_COLORS['border']};
                    border-radius: 6px;
                }}
                QFrame:hover {{
                    border-color: {DARK_COLORS['accent_blue']};
                    background-color: {DARK_COLORS['bg_secondary']};
                }}
            """)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(2)

        # 썸네일 이미지
        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(self.thumb_width, self.thumb_height)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setStyleSheet(f"""
            QLabel {{
                background-color: {DARK_COLORS['bg_primary']};
                border-radius: 4px;
            }}
        """)

        if self.thumbnail_path and self.thumbnail_path.exists():
            pixmap = QPixmap(str(self.thumbnail_path))
            scaled = pixmap.scaled(
                self.thumb_width, self.thumb_height,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.thumb_label.setPixmap(scaled)
        else:
            self.thumb_label.setText("📷")
            self.thumb_label.setStyleSheet(f"""
                QLabel {{
                    background-color: {DARK_COLORS['bg_primary']};
                    border-radius: 4px;
                    color: {DARK_COLORS['text_disabled']};
                    font-size: {get_scaled_font_size(24)}px;
                }}
            """)

        layout.addWidget(self.thumb_label)

        # 1줄: 이름 라벨
        name = self.favorite_data.get("name", "Unknown")
        if len(name) > 12:
            name = name[:10] + "..."
        name_label = QLabel(name)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setMaximumHeight(18)
        name_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(12)}px;
                background-color: transparent;
                border: none;
            }}
        """)
        layout.addWidget(name_label)

        # 2줄: Style Aware + Fidelity 정보
        style_aware = self.favorite_data.get("style_aware", False)
        fidelity = self.favorite_data.get("fidelity", 1.0)

        info_layout = QHBoxLayout()
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(4)

        if style_aware:
            style_label = QLabel("Style")
            style_label.setStyleSheet(f"""
                QLabel {{
                    color: {DARK_COLORS['warning']};
                    font-size: {get_scaled_font_size(10)}px;
                    font-weight: bold;
                    background-color: transparent;
                    border: none;
                }}
            """)
            info_layout.addWidget(style_label)

        fidelity_label = QLabel(f"F:{fidelity:.2f}")
        fidelity_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(10)}px;
                background-color: transparent;
                border: none;
            }}
        """)
        info_layout.addWidget(fidelity_label)

        # 메타데이터 없음 표시
        has_metadata = self.favorite_data.get("has_metadata", False)
        if not has_metadata:
            no_meta_label = QLabel("No metadata")
            no_meta_label.setStyleSheet(f"""
                QLabel {{
                    color: {DARK_COLORS['text_secondary']};
                    font-size: {get_scaled_font_size(10)}px;
                    background-color: transparent;
                    border: none;
                }}
            """)
            info_layout.addWidget(no_meta_label)

        info_layout.addStretch()

        info_widget = QWidget()
        info_widget.setLayout(info_layout)
        info_widget.setMaximumHeight(16)
        layout.addWidget(info_widget)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.favorite_data)
        super().mousePressEvent(event)


class CharacterPromptFavoriteItemWidget(QFrame):
    """캐릭터 프롬프트 즐겨찾기 아이템 위젯 (상단 썸네일 + 하단 텍스트)"""

    clicked = pyqtSignal(dict)  # favorite_data

    def __init__(self, favorite_data: dict, thumbnail_path: Path = None,
                 thumb_width: int = None, thumb_height: int = None,
                 is_selected: bool = False, parent=None):
        super().__init__(parent)
        self.favorite_data = favorite_data
        self.thumbnail_path = thumbnail_path
        self._is_selected = is_selected

        # 동적 크기 설정 (기본값 사용 가능)
        self.thumb_width = thumb_width or CHAR_PROMPT_THUMB_WIDTH
        self.thumb_height = thumb_height or CHAR_PROMPT_THUMB_HEIGHT

        self.setFixedSize(self.thumb_width + 10, self.thumb_height + 35)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_style()

        self._init_ui()

    def _update_style(self):
        """선택 상태에 따른 스타일 업데이트"""
        if self._is_selected:
            self.setStyleSheet(f"""
                QFrame {{
                    background-color: {DARK_COLORS['bg_tertiary']};
                    border: 2px solid {DARK_COLORS['success']};
                    border-radius: 6px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QFrame {{
                    background-color: {DARK_COLORS['bg_tertiary']};
                    border: 1px solid {DARK_COLORS['border']};
                    border-radius: 6px;
                }}
                QFrame:hover {{
                    border: 2px solid {DARK_COLORS['accent_blue']};
                    background-color: {DARK_COLORS['bg_secondary']};
                }}
            """)

    def set_selected(self, selected: bool):
        """선택 상태 변경"""
        self._is_selected = selected
        self._update_style()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(4)

        # 썸네일 이미지
        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(self.thumb_width, self.thumb_height)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setStyleSheet(f"""
            QLabel {{
                background-color: {DARK_COLORS['bg_primary']};
                border-radius: 4px;
            }}
        """)

        if self.thumbnail_path and self.thumbnail_path.exists():
            pixmap = QPixmap(str(self.thumbnail_path))
            scaled = pixmap.scaled(
                self.thumb_width, self.thumb_height,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.thumb_label.setPixmap(scaled)
        else:
            self.thumb_label.setText("👤")
            self.thumb_label.setStyleSheet(f"""
                QLabel {{
                    background-color: {DARK_COLORS['bg_primary']};
                    border-radius: 4px;
                    color: {DARK_COLORS['text_disabled']};
                    font-size: {get_scaled_font_size(24)}px;
                }}
            """)

        layout.addWidget(self.thumb_label)

        # 캐릭터 이름 (하단 텍스트)
        char_name = self.favorite_data.get("name", "이름 없음")
        name_label = QLabel(char_name)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setWordWrap(True)
        name_label.setMaximumHeight(28)
        name_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(12)}px;
                background-color: transparent;
                border: none;
            }}
        """)
        layout.addWidget(name_label)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.favorite_data)
        super().mousePressEvent(event)


# 와일드카드 썸네일 크기 (이벤트와 동일)
WC_THUMB_WIDTH = FAVORITE_THUMB_WIDTH  # 120
WC_THUMB_HEIGHT = FAVORITE_THUMB_HEIGHT  # 167


class WildcardItemWidget(QFrame):
    """인스턴트 와일드카드 아이템 위젯 - 1줄 전체 레이아웃"""

    # 시그널 정의
    instant_generate_requested = pyqtSignal(str, str)  # file_key, item_key
    add_to_queue_requested = pyqtSignal(str, str)  # file_key, item_key
    delete_requested = pyqtSignal(str, str)  # file_key, item_key
    edit_requested = pyqtSignal(str, str, str)  # file_key, item_key, new_value
    heart_changed = pyqtSignal(str, str, int)  # file_key, item_key, new_value
    clip_requested = pyqtSignal(str, str)  # file_key, item_key (클립보드 이미지 할당)

    def __init__(self, file_key: str, item_key: str, item_data: dict, parent=None):
        super().__init__(parent)
        self.file_key = file_key  # JSON 파일명 (확장자 제외)
        self.item_key = item_key  # 와일드카드 키
        self.item_data = item_data  # {"value": "...", "heart": 0}
        self._setup_ui()

    def _setup_ui(self):
        self.setFrameStyle(QFrame.Shape.StyledPanel)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 6px;
            }}
        """)
        # 위젯 최소 높이 설정 (이벤트보다 조금 더 높게)
        self.setMinimumHeight(200)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(12)

        # 썸네일 (120x167, 중앙 크롭)
        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(WC_THUMB_WIDTH, WC_THUMB_HEIGHT)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setStyleSheet(f"""
            QLabel {{
                background-color: {DARK_COLORS['bg_primary']};
                border-radius: 4px;
            }}
        """)
        self._load_thumbnail()
        main_layout.addWidget(self.thumb_label)

        # 오른쪽 영역 (항목명 + 태그 + 버튼)
        right_layout = QVBoxLayout()
        right_layout.setSpacing(6)

        # 상단: 항목명 라벨 (file_key::item_key 형식)
        name_label = QLabel(f"📌 {self.file_key}::{self.item_key}")
        name_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['accent_blue']};
                font-size: {get_scaled_font_size(13)}px;
                font-weight: bold;
                background-color: transparent;
            }}
        """)
        right_layout.addWidget(name_label)

        # 중단: 와일드카드 값 (TextEdit) - 4:1 비율 중 상단
        self.value_edit = QTextEdit()
        self.value_edit.setAcceptRichText(False)
        self.value_edit.setPlainText(self.item_data.get("value", ""))
        self.value_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 4px;
                font-size: {get_scaled_font_size(12)}px;
            }}
        """)
        right_layout.addWidget(self.value_edit, 4)  # 4 비율

        # 하단: 버튼 행 - 1 비율
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(4)

        small_btn_style = f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 3px;
                padding: 3px 8px;
                font-size: {get_scaled_font_size(13)}px;
                min-width: 35px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
                border-color: {DARK_COLORS['accent_blue']};
            }}
        """

        # Clip 버튼 (클립보드 이미지 할당)
        self.clip_btn = QPushButton("📋Clip")
        self.clip_btn.setStyleSheet(small_btn_style)
        self.clip_btn.setToolTip("클립보드 이미지를 썸네일로 할당")
        self.clip_btn.clicked.connect(self._on_clip_clicked)
        btn_layout.addWidget(self.clip_btn)

        # 수정 버튼
        edit_btn = QPushButton("✏️수정")
        edit_btn.setStyleSheet(small_btn_style)
        edit_btn.setToolTip("와일드카드 값 수정")
        edit_btn.clicked.connect(self._on_edit_clicked)
        btn_layout.addWidget(edit_btn)

        # 삭제 버튼
        delete_btn = QPushButton("🗑️삭제")
        delete_btn.setStyleSheet(small_btn_style)
        delete_btn.setToolTip("와일드카드 삭제")
        delete_btn.clicked.connect(lambda: self.delete_requested.emit(self.file_key, self.item_key))
        btn_layout.addWidget(delete_btn)

        # 즉시 생성 버튼
        instant_btn = QPushButton("⚡즉시")
        instant_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['success']};
                color: white;
                border: none;
                border-radius: 3px;
                padding: 3px 8px;
                font-size: {get_scaled_font_size(13)}px;
                min-width: 35px;
            }}
            QPushButton:hover {{
                background-color: #5CBF60;
            }}
        """)
        instant_btn.setToolTip("즉시 생성")
        instant_btn.clicked.connect(lambda: self.instant_generate_requested.emit(self.file_key, self.item_key))
        btn_layout.addWidget(instant_btn)

        # 대기열 추가 버튼
        queue_btn = QPushButton("📋대기열")
        queue_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['accent_blue']};
                color: white;
                border: none;
                border-radius: 3px;
                padding: 3px 8px;
                font-size: {get_scaled_font_size(13)}px;
                min-width: 35px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['accent_blue_hover']};
            }}
        """)
        queue_btn.setToolTip("대기열에 추가")
        queue_btn.clicked.connect(lambda: self.add_to_queue_requested.emit(self.file_key, self.item_key))
        btn_layout.addWidget(queue_btn)

        btn_layout.addStretch()

        # 하트 버튼들
        heart_minus_btn = QPushButton("♥-")
        heart_minus_btn.setStyleSheet(small_btn_style)
        heart_minus_btn.setToolTip("우선순위 감소")
        heart_minus_btn.clicked.connect(lambda: self._change_heart(-1))
        btn_layout.addWidget(heart_minus_btn)

        self.heart_label = QLabel(str(self.item_data.get("heart", 0)))
        self.heart_label.setFixedWidth(30)
        self.heart_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.heart_label.setStyleSheet(f"""
            QLabel {{
                color: #FF6B9D;
                font-size: {get_scaled_font_size(15)}px;
                font-weight: bold;
            }}
        """)
        btn_layout.addWidget(self.heart_label)

        heart_plus_btn = QPushButton("♥+")
        heart_plus_btn.setStyleSheet(small_btn_style)
        heart_plus_btn.setToolTip("우선순위 증가")
        heart_plus_btn.clicked.connect(lambda: self._change_heart(1))
        btn_layout.addWidget(heart_plus_btn)

        right_layout.addLayout(btn_layout, 1)  # 1 비율

        main_layout.addLayout(right_layout, 1)

    def _load_thumbnail(self):
        """썸네일 로드 - 중앙 크롭하여 영역을 꽉 채움"""
        image_path = Path("save") / "instant_wildcard" / "images" / self.file_key / f"{self.item_key}.png"

        if image_path.exists():
            pixmap = QPixmap(str(image_path))
            # KeepAspectRatioByExpanding으로 확대하여 빈 공간 없이 채움
            scaled = pixmap.scaled(
                WC_THUMB_WIDTH, WC_THUMB_HEIGHT,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation
            )
            # 중앙 크롭
            if scaled.width() > WC_THUMB_WIDTH or scaled.height() > WC_THUMB_HEIGHT:
                x = (scaled.width() - WC_THUMB_WIDTH) // 2
                y = (scaled.height() - WC_THUMB_HEIGHT) // 2
                cropped = scaled.copy(x, y, WC_THUMB_WIDTH, WC_THUMB_HEIGHT)
                self.thumb_label.setPixmap(cropped)
            else:
                self.thumb_label.setPixmap(scaled)
        else:
            self.thumb_label.setText("📷")
            self.thumb_label.setStyleSheet(f"""
                QLabel {{
                    background-color: {DARK_COLORS['bg_primary']};
                    border-radius: 4px;
                    color: {DARK_COLORS['text_disabled']};
                    font-size: {get_scaled_font_size(24)}px;
                }}
            """)

    def _on_clip_clicked(self):
        """Clip 버튼 클릭 - 클립보드 이미지 할당"""
        self.clip_requested.emit(self.file_key, self.item_key)

    def _on_edit_clicked(self):
        """수정 버튼 클릭"""
        new_value = self.value_edit.toPlainText()
        self.edit_requested.emit(self.file_key, self.item_key, new_value)

    def _change_heart(self, delta: int):
        """하트 값 변경"""
        current = self.item_data.get("heart", 0)
        new_value = max(0, current + delta)
        self.item_data["heart"] = new_value
        self.heart_label.setText(str(new_value))
        self.heart_changed.emit(self.file_key, self.item_key, new_value)

    def has_thumbnail(self) -> bool:
        """썸네일 존재 여부"""
        image_path = Path("save") / "instant_wildcard" / "images" / self.file_key / f"{self.item_key}.png"
        return image_path.exists()

    def refresh_thumbnail(self):
        """썸네일 새로고침"""
        self._load_thumbnail()


class EventItemWidget(QFrame):
    """🆕 이벤트 아이템 위젯 - 1줄 전체 레이아웃"""

    # 시그널 정의
    instant_generate_requested = pyqtSignal(str)  # event_id
    add_to_queue_requested = pyqtSignal(str)  # event_id
    delete_requested = pyqtSignal(str)  # event_id
    edit_requested = pyqtSignal(str)  # event_id
    heart_changed = pyqtSignal(str, int)  # event_id, new_value
    rating_changed = pyqtSignal(str, str)  # event_id, new_rating

    def __init__(self, event_data: dict, parent=None):
        super().__init__(parent)
        self.event_data = event_data
        self.event_id = event_data.get("id", "")
        self.is_editing = False

        self._init_ui()

    def _init_ui(self):
        # 전체 프레임 스타일
        self.setStyleSheet(f"""
            EventItemWidget {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 6px;
            }}
            EventItemWidget:hover {{
                border: 1px solid {DARK_COLORS['accent_blue']};
            }}
        """)
        self.setMinimumHeight(EVENT_THUMB_HEIGHT + 20)
        self.setMaximumHeight(EVENT_THUMB_HEIGHT + 20)

        # 메인 레이아웃 (수평)
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(10)

        # === 좌측: 썸네일 ===
        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(EVENT_THUMB_WIDTH, EVENT_THUMB_HEIGHT)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setStyleSheet(f"""
            QLabel {{
                background-color: {DARK_COLORS['bg_primary']};
                border-radius: 4px;
            }}
        """)
        self._load_thumbnail()
        main_layout.addWidget(self.thumb_label)

        # === 우측: 정보 영역 (4:1 비율) ===
        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)

        # --- 상단 4: General 태그 표시/편집 ---
        self.general_edit = QTextEdit()
        general_text = self.event_data.get("source_row", {}).get("general", "")
        self.general_edit.setPlainText(general_text)
        self.general_edit.setReadOnly(True)
        self.general_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                font-size: {get_scaled_font_size(16)}px;
                padding: 4px;
            }}
            QTextEdit:focus {{
                border: 1px solid {DARK_COLORS['accent_blue']};
            }}
        """)
        right_layout.addWidget(self.general_edit, 4)  # 4 비율

        # --- 하단 1: 버튼 행 ---
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(4)

        # 버튼 스타일
        small_btn_style = f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 3px;
                padding: 3px 8px;
                font-size: {get_scaled_font_size(13)}px;
                min-width: 35px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['accent_blue']};
            }}
            QPushButton:pressed {{
                background-color: {DARK_COLORS['accent_blue_hover']};
            }}
        """

        # Rating 버튼
        current_rating = self.event_data.get("source_row", {}).get("rating", "g")
        self.rating_btn = QPushButton(f"R:{current_rating.upper()}")
        self.rating_btn.setStyleSheet(small_btn_style)
        self.rating_btn.setToolTip("등급 변경")
        self.rating_btn.clicked.connect(self._on_rating_clicked)
        btn_layout.addWidget(self.rating_btn)

        # 수정 버튼
        self.edit_btn = QPushButton("✏️")
        self.edit_btn.setStyleSheet(small_btn_style)
        self.edit_btn.setToolTip("General 태그 수정")
        self.edit_btn.clicked.connect(self._on_edit_clicked)
        btn_layout.addWidget(self.edit_btn)

        # 삭제 버튼
        delete_btn = QPushButton("🗑️")
        delete_btn.setStyleSheet(small_btn_style)
        delete_btn.setToolTip("삭제")
        delete_btn.clicked.connect(lambda: self.delete_requested.emit(self.event_id))
        btn_layout.addWidget(delete_btn)

        btn_layout.addStretch()

        # 즉시 생성 버튼
        instant_btn = QPushButton("⚡ 즉시")
        instant_btn.setStyleSheet(small_btn_style)
        instant_btn.setToolTip("즉시 생성")
        instant_btn.clicked.connect(lambda: self.instant_generate_requested.emit(self.event_id))
        btn_layout.addWidget(instant_btn)

        # 대기열 추가 버튼
        queue_btn = QPushButton("📋 대기열")
        queue_btn.setStyleSheet(small_btn_style)
        queue_btn.setToolTip("대기열에 추가")
        queue_btn.clicked.connect(lambda: self.add_to_queue_requested.emit(self.event_id))
        btn_layout.addWidget(queue_btn)

        btn_layout.addStretch()

        # 하트 버튼들
        heart_minus_btn = QPushButton("♥-")
        heart_minus_btn.setStyleSheet(small_btn_style)
        heart_minus_btn.setToolTip("우선순위 감소")
        heart_minus_btn.clicked.connect(lambda: self._change_heart(-1))
        btn_layout.addWidget(heart_minus_btn)

        # 하트 값 표시
        current_heart = self.event_data.get("heart", 0)
        self.heart_label = QLabel(f"♥{current_heart}")
        self.heart_label.setStyleSheet(f"""
            QLabel {{
                color: {'#FF6B9D' if current_heart > 0 else DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(14)}px;
                font-weight: bold;
                min-width: 30px;
            }}
        """)
        self.heart_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn_layout.addWidget(self.heart_label)

        heart_plus_btn = QPushButton("♥+")
        heart_plus_btn.setStyleSheet(small_btn_style)
        heart_plus_btn.setToolTip("우선순위 증가")
        heart_plus_btn.clicked.connect(lambda: self._change_heart(1))
        btn_layout.addWidget(heart_plus_btn)

        right_layout.addLayout(btn_layout, 1)  # 1 비율

        main_layout.addLayout(right_layout, 1)

    def _load_thumbnail(self):
        """썸네일 로드 - 중앙 크롭하여 영역을 꽉 채움"""
        thumb_filename = self.event_data.get("thumbnail", "")
        thumb_path = REMOTE_EVENTS_THUMBS_DIR / thumb_filename

        if thumb_path.exists():
            pixmap = QPixmap(str(thumb_path))
            # KeepAspectRatioByExpanding으로 확대하여 빈 공간 없이 채움
            scaled = pixmap.scaled(
                EVENT_THUMB_WIDTH, EVENT_THUMB_HEIGHT,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation
            )
            # 중앙 크롭: 확대된 이미지에서 중앙 부분만 추출
            if scaled.width() > EVENT_THUMB_WIDTH or scaled.height() > EVENT_THUMB_HEIGHT:
                x = (scaled.width() - EVENT_THUMB_WIDTH) // 2
                y = (scaled.height() - EVENT_THUMB_HEIGHT) // 2
                cropped = scaled.copy(x, y, EVENT_THUMB_WIDTH, EVENT_THUMB_HEIGHT)
                self.thumb_label.setPixmap(cropped)
            else:
                self.thumb_label.setPixmap(scaled)
        else:
            self.thumb_label.setText("📷")
            self.thumb_label.setStyleSheet(f"""
                QLabel {{
                    background-color: {DARK_COLORS['bg_primary']};
                    border-radius: 4px;
                    color: {DARK_COLORS['text_disabled']};
                    font-size: {get_scaled_font_size(24)}px;
                }}
            """)

    def _on_rating_clicked(self):
        """Rating 변경 클릭"""
        ratings = ["g", "s", "q", "e"]
        current = self.event_data.get("source_row", {}).get("rating", "g")
        try:
            next_idx = (ratings.index(current) + 1) % len(ratings)
        except ValueError:
            next_idx = 0
        new_rating = ratings[next_idx]

        self.rating_btn.setText(f"R:{new_rating.upper()}")
        self.rating_changed.emit(self.event_id, new_rating)

    def _on_edit_clicked(self):
        """수정 버튼 클릭"""
        if self.is_editing:
            # 수정 완료 - 저장
            self.general_edit.setReadOnly(True)
            self.edit_btn.setText("✏️")
            self.is_editing = False
            self.edit_requested.emit(self.event_id)
        else:
            # 수정 시작
            self.general_edit.setReadOnly(False)
            self.general_edit.setFocus()
            self.edit_btn.setText("💾")
            self.is_editing = True

    def get_general_text(self) -> str:
        """현재 General 텍스트 반환"""
        return self.general_edit.toPlainText()

    def _change_heart(self, delta: int):
        """하트 값 변경"""
        current = self.event_data.get("heart", 0)
        new_value = max(0, current + delta)  # 최소 0
        self.event_data["heart"] = new_value

        self.heart_label.setText(f"♥{new_value}")
        self.heart_label.setStyleSheet(f"""
            QLabel {{
                color: {'#FF6B9D' if new_value > 0 else DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(14)}px;
                font-weight: bold;
                min-width: 30px;
            }}
        """)
        self.heart_changed.emit(self.event_id, new_value)


class RemoteWindow(QMainWindow):
    """리모트 탭에서 열리는 독립 창 - 모듈 통합 제어"""

    window_closed = pyqtSignal()

    # 즐겨찾기 관련 경로
    FAVORITES_DIR = Path("save/presets/favorites")
    FAVORITES_JSON = Path("save/presets/favorites.json")

    def __init__(self, parent_app=None):
        super().__init__(parent=None)  # 완전 독립 창
        self.parent_app = parent_app

        # 모듈 참조 저장
        self.preset_module = None
        self.character_module = None
        self.character_ref_module = None
        self.instant_wc_module = None

        # 프리셋 즐겨찾기 데이터
        self.favorites = []  # [{"name": "preset_name", "mode": "NAI"}, ...]

        # 캐릭터 레퍼런스 즐겨찾기 데이터
        self.char_ref_favorites = []  # [{"file_hash": "...", "name": "...", "style_aware": bool, "fidelity": float, "folder": "기본"}, ...]
        self.char_ref_folders = ["기본"]  # 즐겨찾기 폴더 목록
        self.char_ref_current_folder = "기본"  # 현재 선택된 폴더
        self.char_ref_auto_assign_c1 = False  # C1 자동 할당 체크박스 상태

        # 캐릭터 프롬프트 탭 데이터
        self.char_prompt_favorites = []  # [{"name": "...", "prompt": "...", "uc": "...", "folder": "기본"}, ...]
        self.char_prompt_folders = ["기본"]  # 즐겨찾기 폴더 목록
        self.char_prompt_current_folder = "기본"  # 현재 선택된 폴더
        self.char_prompt_selected_slot = 0  # 현재 선택된 C슬롯 인덱스 (0=C1, 1=C2, ...)
        self.char_prompt_person_count = 1  # 인원 수 설정 (1-6)
        self._pending_thumb_image = None  # 썸네일 등록 대기 이미지

        # 🆕 이벤트 탭 데이터
        self.remote_events = []  # [{"id": "...", "name": "...", "source_row": {...}, "thumbnail": "...", "created_at": "..."}, ...]

        # 🆕 자동 생성 관련 플래그
        self._event_auto_generate_pending = False  # 이벤트 탭 자동 생성 대기 중
        self._wc_auto_generate_pending = False  # INST.WC 탭 자동 생성 대기 중

        # 윈도우 플래그 설정 (항상 위에 기본 활성화)
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowMinimizeButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.WindowStaysOnTopHint
        )

        self.setWindowTitle("NAIA - 리모트 컨트롤")
        self.setMinimumSize(550, 500)
        self.resize(700, 980)  # 높이 1.8배 (600 * 1.8)

        # 다크 테마 적용
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
            }}
        """)

        self._ensure_directories()
        self._get_module_references()
        self._load_favorites()
        self._load_char_ref_favorites()
        self._load_remote_events()  # 🆕
        self._setup_menubar()
        self._init_ui()

        # 🆕 생성 완료 이벤트 구독 (자동 생성용)
        self._subscribe_generation_completed()

    def _subscribe_generation_completed(self):
        """생성 완료 이벤트 구독 (자동 생성용)"""
        if self.parent_app and hasattr(self.parent_app, 'app_context'):
            app_context = self.parent_app.app_context
            app_context.subscribe("generation_completed_for_redirect", self._on_generation_completed_for_auto)

    def _on_generation_completed_for_auto(self, data):
        """생성 완료 시 자동 생성 처리"""
        # 이벤트 탭 자동 생성 처리
        if self._event_auto_generate_pending:
            self._event_auto_generate_pending = False
            # 대기열에 남은 항목이 있고, 자동 생성이 활성화되어 있으면 다음 실행
            if (hasattr(self, 'event_queue') and self.event_queue and
                hasattr(self, 'event_auto_generate_check') and
                self.event_auto_generate_check.isChecked()):
                # 약간의 딜레이 후 다음 생성 시작 (UI 업데이트 시간 확보)
                QTimer.singleShot(500, self._on_event_generate_start)

        # INST.WC 탭 자동 생성 처리
        if self._wc_auto_generate_pending:
            self._wc_auto_generate_pending = False
            # 대기열에 남은 항목이 있고, 자동 생성이 활성화되어 있으면 다음 실행
            if (hasattr(self, 'wc_queue') and self.wc_queue and
                hasattr(self, 'wc_auto_generate_check') and
                self.wc_auto_generate_check.isChecked()):
                # 약간의 딜레이 후 다음 생성 시작 (UI 업데이트 시간 확보)
                QTimer.singleShot(500, self._on_wc_generate_start)

    def _style_dialog(self, dialog):
        """다이얼로그에 다크 테마 스타일 적용 (흰색 텍스트)"""
        dialog.setStyleSheet(f"""
            QMessageBox, QInputDialog {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
            }}
            QMessageBox QLabel, QInputDialog QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(15)}px;
            }}
            QMessageBox QPushButton, QInputDialog QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 6px 16px;
                min-width: 60px;
            }}
            QMessageBox QPushButton:hover, QInputDialog QPushButton:hover {{
                background-color: {DARK_COLORS['bg_secondary']};
                border-color: {DARK_COLORS['accent_blue']};
            }}
            QInputDialog QLineEdit, QInputDialog QComboBox {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 4px 8px;
            }}
            QInputDialog QComboBox QAbstractItemView {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                selection-background-color: {DARK_COLORS['accent_blue']};
            }}
        """)

    def _show_warning(self, title: str, message: str):
        """다크 테마가 적용된 경고 다이얼로그"""
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle(title)
        msg.setText(message)
        self._style_dialog(msg)
        msg.exec()

    def _show_info(self, title: str, message: str):
        """다크 테마가 적용된 정보 다이얼로그"""
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setWindowTitle(title)
        msg.setText(message)
        self._style_dialog(msg)
        msg.exec()

    def _show_question(self, title: str, message: str) -> bool:
        """다크 테마가 적용된 확인 다이얼로그 (Yes/No)"""
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setWindowTitle(title)
        msg.setText(message)
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        self._style_dialog(msg)
        return msg.exec() == QMessageBox.StandardButton.Yes

    def _get_text_input(self, title: str, label: str) -> tuple:
        """다크 테마가 적용된 텍스트 입력 다이얼로그"""
        from PyQt6.QtWidgets import QInputDialog, QLineEdit
        dialog = QInputDialog(self)
        dialog.setWindowTitle(title)
        dialog.setLabelText(label)
        dialog.setInputMode(QInputDialog.InputMode.TextInput)

        self._style_dialog(dialog)

        # ✅ 스타일 적용 후에 line edit를 "다시" 잡기
        line_edit = None
        if hasattr(dialog, "lineEdit"):
            line_edit = dialog.lineEdit()
        if line_edit is None:
            line_edit = dialog.findChild(QLineEdit)

        if line_edit:
            line_edit.setProperty("autocomplete_ignore", True)

        ok = dialog.exec()
        return dialog.textValue(), ok == QInputDialog.DialogCode.Accepted

    def _get_item_input(self, title: str, label: str, items: list) -> tuple:
        """다크 테마가 적용된 항목 선택 다이얼로그"""
        dialog = QInputDialog(self)
        dialog.setWindowTitle(title)
        dialog.setLabelText(label)
        dialog.setComboBoxItems(items)
        dialog.setComboBoxEditable(False)
        self._style_dialog(dialog)
        ok = dialog.exec()
        return dialog.textValue(), ok == QInputDialog.DialogCode.Accepted

    def _ensure_directories(self):
        """필요한 디렉토리 생성"""
        self.FAVORITES_DIR.mkdir(parents=True, exist_ok=True)
        CHAR_REF_FAVORITES_DIR.mkdir(parents=True, exist_ok=True)
        CHAR_PROMPT_FAVORITES_DIR.mkdir(parents=True, exist_ok=True)
        (CHAR_PROMPT_FAVORITES_DIR / "thumbnails").mkdir(parents=True, exist_ok=True)
        REMOTE_EVENTS_DIR.mkdir(parents=True, exist_ok=True)  # 🆕
        REMOTE_EVENTS_THUMBS_DIR.mkdir(parents=True, exist_ok=True)  # 🆕

    def _get_module_references(self):
        """모듈 인스턴스 참조 획득"""
        if not self.parent_app or not hasattr(self.parent_app, 'middle_section_controller'):
            return

        controller = self.parent_app.middle_section_controller

        # 모듈 참조 획득
        self.preset_module = controller.get_module_instance("PromptEngineeringModule")
        self.character_module = controller.get_module_instance("CharacterModule")
        self.character_ref_module = controller.get_module_instance("CharacterReferenceModule")
        self.instant_wc_module = controller.get_module_instance("InstantWildcardModule")

    def _load_favorites(self):
        """프리셋 즐겨찾기 데이터 로드"""
        if self.FAVORITES_JSON.exists():
            try:
                with open(self.FAVORITES_JSON, 'r', encoding='utf-8') as f:
                    self.favorites = json.load(f)
            except Exception as e:
                print(f"⚠️ 즐겨찾기 로드 실패: {e}")
                self.favorites = []
        else:
            self.favorites = []

    def _load_char_ref_favorites(self):
        """캐릭터 레퍼런스 즐겨찾기 데이터 로드"""
        # 폴더 목록 로드
        if CHAR_REF_FOLDERS_JSON.exists():
            try:
                with open(CHAR_REF_FOLDERS_JSON, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.char_ref_folders = data.get("folders", ["기본"])
                    self.char_ref_current_folder = data.get("current_folder", "기본")
                    self.char_ref_auto_assign_c1 = data.get("auto_assign_c1", False)
                    if "기본" not in self.char_ref_folders:
                        self.char_ref_folders.insert(0, "기본")
            except Exception as e:
                print(f"⚠️ 캐릭터 레퍼런스 폴더 로드 실패: {e}")
                self.char_ref_folders = ["기본"]
        else:
            self.char_ref_folders = ["기본"]

        # 즐겨찾기 데이터 로드
        if CHAR_REF_FAVORITES_JSON.exists():
            try:
                with open(CHAR_REF_FAVORITES_JSON, 'r', encoding='utf-8') as f:
                    self.char_ref_favorites = json.load(f)
            except Exception as e:
                print(f"⚠️ 캐릭터 레퍼런스 즐겨찾기 로드 실패: {e}")
                self.char_ref_favorites = []
        else:
            self.char_ref_favorites = []

    def _save_char_ref_favorites(self):
        """캐릭터 레퍼런스 즐겨찾기 데이터 저장"""
        try:
            with open(CHAR_REF_FAVORITES_JSON, 'w', encoding='utf-8') as f:
                json.dump(self.char_ref_favorites, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ 캐릭터 레퍼런스 즐겨찾기 저장 실패: {e}")

    def _save_char_ref_folders(self):
        """캐릭터 레퍼런스 폴더 설정 저장"""
        try:
            data = {
                "folders": self.char_ref_folders,
                "current_folder": self.char_ref_current_folder,
                "auto_assign_c1": self.char_ref_auto_assign_c1
            }
            with open(CHAR_REF_FOLDERS_JSON, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ 캐릭터 레퍼런스 폴더 저장 실패: {e}")

    def _save_favorites(self):
        """즐겨찾기 데이터 저장"""
        try:
            with open(self.FAVORITES_JSON, 'w', encoding='utf-8') as f:
                json.dump(self.favorites, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ 즐겨찾기 저장 실패: {e}")

    def _validate_favorites(self):
        """즐겨찾기 유효성 검사 - 실제 프리셋에 존재하는지 확인"""
        if not self.preset_module:
            return

        valid_favorites = []
        current_mode = self.preset_module.app_context.get_api_mode() if self.preset_module.app_context else "NAI"
        preset_dir = Path("save/presets") / current_mode

        for fav in self.favorites:
            preset_name = fav.get("name", "")
            fav_mode = fav.get("mode", "NAI")

            # 현재 모드의 프리셋만 검사
            if fav_mode == current_mode:
                preset_file = preset_dir / f"{preset_name}.json"
                thumb_file = self.FAVORITES_DIR / f"{preset_name}.png"

                if preset_file.exists():
                    valid_favorites.append(fav)
                else:
                    # 프리셋이 없으면 썸네일도 삭제
                    if thumb_file.exists():
                        thumb_file.unlink()
                    print(f"🗑️ 삭제된 프리셋 즐겨찾기 제거: {preset_name}")
            else:
                # 다른 모드의 즐겨찾기는 유지
                valid_favorites.append(fav)

        if len(valid_favorites) != len(self.favorites):
            self.favorites = valid_favorites
            self._save_favorites()

    def _setup_menubar(self):
        """메뉴바 설정"""
        menubar = self.menuBar()
        menubar.setStyleSheet(f"""
            QMenuBar {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border-bottom: 1px solid {DARK_COLORS['border']};
                padding: 2px;
            }}
            QMenuBar::item {{
                background-color: transparent;
                padding: 4px 8px;
                border-radius: 4px;
            }}
            QMenuBar::item:selected {{
                background-color: {DARK_COLORS['accent_blue']};
            }}
        """)

        # 옵션 메뉴
        option_menu = menubar.addMenu("옵션 (&O)")
        option_menu.setStyleSheet(f"""
            QMenu {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 4px;
            }}
            QMenu::item {{
                padding: 6px 20px;
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background-color: {DARK_COLORS['accent_blue']};
            }}
            QMenu::indicator {{
                width: 16px;
                height: 16px;
                margin-left: 4px;
            }}
        """)

        # 항상 위에 옵션 (기본 체크됨)
        self.always_on_top_action = QAction("📌 항상 위에 표시", self)
        self.always_on_top_action.setCheckable(True)
        self.always_on_top_action.setChecked(True)
        self.always_on_top_action.triggered.connect(self._toggle_always_on_top)
        option_menu.addAction(self.always_on_top_action)

    def _toggle_always_on_top(self, checked: bool):
        """항상 위에 표시 토글"""
        current_flags = self.windowFlags()

        if checked:
            new_flags = current_flags | Qt.WindowType.WindowStaysOnTopHint
        else:
            new_flags = current_flags & ~Qt.WindowType.WindowStaysOnTopHint

        self.setWindowFlags(new_flags)
        self.show()

    def _init_ui(self):
        """UI 초기화 - 탭 뷰 구조"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # 메인 탭 위젯
        self.main_tabs = QTabWidget()
        self.main_tabs.setStyleSheet(DARK_STYLES['dark_tabs'])
        layout.addWidget(self.main_tabs)

        # 탭1: 프리셋 (이중 탭)
        self._create_preset_tab()

        # 탭2: 캐릭터 (이중 탭)
        self._create_character_tab()

        # 탭3: 이벤트 (이중 탭)
        self._create_event_tab()

    def _create_preset_tab(self):
        """탭1: 프리셋 (이중 탭 - 프리셋, P.엔지니어링)"""
        preset_container = QWidget()
        preset_container_layout = QVBoxLayout(preset_container)
        preset_container_layout.setContentsMargins(4, 4, 4, 4)

        # 이중 탭
        preset_sub_tabs = QTabWidget()
        preset_sub_tabs.setStyleSheet(DARK_STYLES['dark_tabs'])
        preset_container_layout.addWidget(preset_sub_tabs)

        # 서브탭1: 프리셋 (즐겨찾기)
        self._create_preset_favorites_subtab(preset_sub_tabs)

        # 서브탭2: P.엔지니어링
        self._create_preset_engineering_subtab(preset_sub_tabs)

        self.main_tabs.addTab(preset_container, "🔧 프리셋")

    def _create_preset_favorites_subtab(self, parent_tabs: QTabWidget):
        """프리셋 즐겨찾기 서브탭"""
        favorites_widget = QWidget()
        favorites_layout = QVBoxLayout(favorites_widget)
        favorites_layout.setContentsMargins(8, 8, 8, 8)
        favorites_layout.setSpacing(8)

        # === 상단 섹션 ===
        top_section = QFrame()
        top_section.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 8px;
            }}
        """)
        top_layout = QHBoxLayout(top_section)
        top_layout.setContentsMargins(10, 10, 10, 10)
        top_layout.setSpacing(12)

        # 왼쪽: 썸네일 영역
        self.current_preset_thumb = QLabel()
        self.current_preset_thumb.setFixedSize(PREVIEW_THUMB_WIDTH, PREVIEW_THUMB_HEIGHT)
        self.current_preset_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.current_preset_thumb.setStyleSheet(f"""
            QLabel {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 2px dashed {DARK_COLORS['border']};
                border-radius: 6px;
                color: {DARK_COLORS['text_disabled']};
                font-size: {get_scaled_font_size(14)}px;
            }}
        """)
        self.current_preset_thumb.setText("썸네일\n없음")
        top_layout.addWidget(self.current_preset_thumb)

        # 오른쪽: 컨트롤 영역 (세로 배치)
        right_section = QVBoxLayout()
        right_section.setSpacing(6)

        # 1) "현재 프리셋" 라벨
        preset_label = QLabel("현재 프리셋")
        preset_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-weight: bold;
                font-size: {get_scaled_font_size(15)}px;
            }}
        """)
        right_section.addWidget(preset_label)

        # 2) [콤보박스][관리] 가로 배치
        combo_row = QHBoxLayout()
        combo_row.setSpacing(6)

        self.remote_preset_combo = QComboBox()
        self.remote_preset_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
        self.remote_preset_combo.setMinimumWidth(150)
        self._sync_preset_combo()
        self.remote_preset_combo.currentTextChanged.connect(self._on_remote_preset_changed)
        combo_row.addWidget(self.remote_preset_combo, 1)

        self.manage_preset_btn = QPushButton("📂 관리")
        self.manage_preset_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.manage_preset_btn.setFixedWidth(100)
        self.manage_preset_btn.clicked.connect(self._open_preset_folder)
        combo_row.addWidget(self.manage_preset_btn)

        right_section.addLayout(combo_row)

        # 3) 클립보드에서 썸네일 생성 버튼 (진한 회색 배경, primary_button과 동일한 크기)
        self.paste_thumb_btn = QPushButton("📋 클립보드에서 썸네일 생성")
        self.paste_thumb_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(8)}px {get_scaled_size(24)}px;
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-weight: 500;
                font-size: {get_scaled_font_size(15)}px;
                min-height: {get_scaled_size(16)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_secondary']};
                border-color: {DARK_COLORS['accent_blue']};
            }}
            QPushButton:pressed {{
                background-color: {DARK_COLORS['bg_primary']};
            }}
            QPushButton:disabled {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_disabled']};
                border-color: {DARK_COLORS['bg_tertiary']};
            }}
        """)
        self.paste_thumb_btn.clicked.connect(self._paste_thumbnail_from_clipboard)
        right_section.addWidget(self.paste_thumb_btn)

        # 4) 즐겨찾기에 등록 버튼
        self.favorite_btn = QPushButton("⭐ 즐겨찾기에 등록")
        self.favorite_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.favorite_btn.clicked.connect(self._toggle_favorite)
        right_section.addWidget(self.favorite_btn)

        right_section.addStretch()

        top_layout.addLayout(right_section, 1)
        favorites_layout.addWidget(top_section)

        # === 하단 섹션: 즐겨찾기 목록 ===
        bottom_section = QFrame()
        bottom_section.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 8px;
            }}
        """)
        bottom_layout = QVBoxLayout(bottom_section)
        bottom_layout.setContentsMargins(10, 10, 10, 10)
        bottom_layout.setSpacing(8)

        # 헤더
        header_label = QLabel("⭐ 즐겨찾기")
        header_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['accent_blue']};
                font-size: {get_scaled_font_size(14)}px;
                font-weight: bold;
            }}
        """)
        bottom_layout.addWidget(header_label)

        # 스크롤 영역
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet(f"""
            QScrollArea {{
                background-color: transparent;
                border: none;
            }}
            QScrollArea > QWidget > QWidget {{
                background-color: transparent;
            }}
        """)

        # 그리드 컨테이너
        self.favorites_grid_widget = QWidget()
        self.favorites_grid_layout = QGridLayout(self.favorites_grid_widget)
        self.favorites_grid_layout.setSpacing(10)
        self.favorites_grid_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area.setWidget(self.favorites_grid_widget)
        bottom_layout.addWidget(scroll_area, 1)

        favorites_layout.addWidget(bottom_section, 1)

        parent_tabs.addTab(favorites_widget, "⭐ 프리셋")

        # 즐겨찾기 유효성 검사 및 UI 업데이트
        self._validate_favorites()
        self._update_favorites_grid()
        self._update_current_preset_ui()

    def _create_preset_engineering_subtab(self, parent_tabs: QTabWidget):
        """P.엔지니어링 서브탭 - 원본 모듈과 양방향 동기화"""
        eng_widget = QWidget()
        eng_layout = QVBoxLayout(eng_widget)
        eng_layout.setContentsMargins(8, 8, 8, 8)
        eng_layout.setSpacing(8)

        # 동기화 플래그 (무한 루프 방지)
        self._sync_in_progress = False

        # 리모트 체크박스 저장
        self.remote_preprocessing_checkboxes = {}

        if self.preset_module:
            # === 선행 프롬프트 ===
            if hasattr(self.preset_module, 'pre_textedit') and self.preset_module.pre_textedit:
                pre_label = QLabel("선행 프롬프트:")
                pre_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-weight: bold;")
                eng_layout.addWidget(pre_label)

                self.remote_pre_edit = QTextEdit()
                self.remote_pre_edit.setStyleSheet(DARK_STYLES['compact_textedit'])
                self.remote_pre_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                self.remote_pre_edit.setPlainText(self.preset_module.pre_textedit.toPlainText())
                self.remote_pre_edit.textChanged.connect(self._on_remote_pre_changed)
                eng_layout.addWidget(self.remote_pre_edit, 1)  # stretch factor 1

                # 원본 -> 리모트 동기화 연결
                self.preset_module.pre_textedit.textChanged.connect(self._sync_pre_from_original)

            # === 후행 프롬프트 ===
            if hasattr(self.preset_module, 'post_textedit') and self.preset_module.post_textedit:
                post_label = QLabel("후행 프롬프트:")
                post_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-weight: bold;")
                eng_layout.addWidget(post_label)

                self.remote_post_edit = QTextEdit()
                self.remote_post_edit.setStyleSheet(DARK_STYLES['compact_textedit'])
                self.remote_post_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                self.remote_post_edit.setPlainText(self.preset_module.post_textedit.toPlainText())
                self.remote_post_edit.textChanged.connect(self._on_remote_post_changed)
                eng_layout.addWidget(self.remote_post_edit, 1)  # stretch factor 1

                # 원본 -> 리모트 동기화 연결
                self.preset_module.post_textedit.textChanged.connect(self._sync_post_from_original)

            # === 자동 숨김 프롬프트 ===
            if hasattr(self.preset_module, 'auto_hide_textedit') and self.preset_module.auto_hide_textedit:
                auto_hide_label = QLabel("자동 숨김 프롬프트:")
                auto_hide_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-weight: bold;")
                eng_layout.addWidget(auto_hide_label)

                self.remote_auto_hide_edit = QTextEdit()
                self.remote_auto_hide_edit.setStyleSheet(DARK_STYLES['compact_textedit'])
                self.remote_auto_hide_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                self.remote_auto_hide_edit.setPlainText(self.preset_module.auto_hide_textedit.toPlainText())
                self.remote_auto_hide_edit.textChanged.connect(self._on_remote_auto_hide_changed)
                eng_layout.addWidget(self.remote_auto_hide_edit, 1)  # stretch factor 1

                # 원본 -> 리모트 동기화 연결
                self.preset_module.auto_hide_textedit.textChanged.connect(self._sync_auto_hide_from_original)

            # === 전처리 옵션 체크박스 ===
            if hasattr(self.preset_module, 'option_key_map') and hasattr(self.preset_module, 'preprocessing_checkboxes'):
                options_label = QLabel("전처리 옵션:")
                options_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-weight: bold;")
                eng_layout.addWidget(options_label)

                options_frame = QFrame()
                options_frame.setStyleSheet(f"""
                    QFrame {{
                        background-color: {DARK_COLORS['bg_secondary']};
                        border: 1px solid {DARK_COLORS['border']};
                        border-radius: 6px;
                        padding: 4px;
                    }}
                """)
                options_layout = QVBoxLayout(options_frame)
                options_layout.setContentsMargins(8, 8, 8, 8)
                options_layout.setSpacing(4)

                for text in self.preset_module.option_key_map.keys():
                    cb = QCheckBox(text)
                    cb.setStyleSheet(DARK_STYLES['dark_checkbox'])

                    # 원본 체크박스 상태 복사
                    if text in self.preset_module.preprocessing_checkboxes:
                        cb.setChecked(self.preset_module.preprocessing_checkboxes[text].isChecked())

                    # 양방향 동기화 연결
                    cb.stateChanged.connect(lambda state, t=text: self._on_remote_checkbox_changed(t, state))
                    options_layout.addWidget(cb)
                    self.remote_preprocessing_checkboxes[text] = cb

                    # 원본 -> 리모트 동기화 연결
                    if text in self.preset_module.preprocessing_checkboxes:
                        self.preset_module.preprocessing_checkboxes[text].stateChanged.connect(
                            lambda state, t=text: self._sync_checkbox_from_original(t, state)
                        )

                eng_layout.addWidget(options_frame)

            eng_layout.addStretch()
        else:
            placeholder = QLabel("프리셋 모듈을 찾을 수 없습니다.")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet(f"color: {DARK_COLORS['text_disabled']};")
            eng_layout.addWidget(placeholder)

        parent_tabs.addTab(eng_widget, "🔧 P.엔지니어링")

    # === 양방향 동기화 메서드들 ===

    def _on_remote_pre_changed(self):
        """리모트 선행 프롬프트 변경 -> 원본 반영"""
        if self._sync_in_progress:
            return
        if self.preset_module and hasattr(self.preset_module, 'pre_textedit'):
            self._sync_in_progress = True
            self.preset_module.pre_textedit.setPlainText(self.remote_pre_edit.toPlainText())
            self._sync_in_progress = False

    def _on_remote_post_changed(self):
        """리모트 후행 프롬프트 변경 -> 원본 반영"""
        if self._sync_in_progress:
            return
        if self.preset_module and hasattr(self.preset_module, 'post_textedit'):
            self._sync_in_progress = True
            self.preset_module.post_textedit.setPlainText(self.remote_post_edit.toPlainText())
            self._sync_in_progress = False

    def _on_remote_auto_hide_changed(self):
        """리모트 자동 숨김 프롬프트 변경 -> 원본 반영"""
        if self._sync_in_progress:
            return
        if self.preset_module and hasattr(self.preset_module, 'auto_hide_textedit'):
            self._sync_in_progress = True
            self.preset_module.auto_hide_textedit.setPlainText(self.remote_auto_hide_edit.toPlainText())
            self._sync_in_progress = False

    def _on_remote_checkbox_changed(self, text: str, state: int):
        """리모트 체크박스 변경 -> 원본 반영"""
        if self._sync_in_progress:
            return
        if self.preset_module and hasattr(self.preset_module, 'preprocessing_checkboxes'):
            if text in self.preset_module.preprocessing_checkboxes:
                self._sync_in_progress = True
                self.preset_module.preprocessing_checkboxes[text].setChecked(state == 2)
                self._sync_in_progress = False

    def _sync_pre_from_original(self):
        """원본 선행 프롬프트 변경 -> 리모트 반영"""
        if self._sync_in_progress:
            return
        if hasattr(self, 'remote_pre_edit') and self.preset_module:
            self._sync_in_progress = True
            self.remote_pre_edit.setPlainText(self.preset_module.pre_textedit.toPlainText())
            self._sync_in_progress = False

    def _sync_post_from_original(self):
        """원본 후행 프롬프트 변경 -> 리모트 반영"""
        if self._sync_in_progress:
            return
        if hasattr(self, 'remote_post_edit') and self.preset_module:
            self._sync_in_progress = True
            self.remote_post_edit.setPlainText(self.preset_module.post_textedit.toPlainText())
            self._sync_in_progress = False

    def _sync_auto_hide_from_original(self):
        """원본 자동 숨김 프롬프트 변경 -> 리모트 반영"""
        if self._sync_in_progress:
            return
        if hasattr(self, 'remote_auto_hide_edit') and self.preset_module:
            self._sync_in_progress = True
            self.remote_auto_hide_edit.setPlainText(self.preset_module.auto_hide_textedit.toPlainText())
            self._sync_in_progress = False

    def _sync_checkbox_from_original(self, text: str, state: int):
        """원본 체크박스 변경 -> 리모트 반영"""
        if self._sync_in_progress:
            return
        if text in self.remote_preprocessing_checkboxes:
            self._sync_in_progress = True
            self.remote_preprocessing_checkboxes[text].setChecked(state == 2)
            self._sync_in_progress = False

    def _calculate_thumbnail_size(self) -> tuple:
        """현재 UI 크기를 기반으로 썸네일 크기 계산 (3열 기준)"""
        # 그리드 영역의 가용 너비 계산
        available_width = self.favorites_grid_widget.width()

        # 최소 너비 보장
        if available_width < 100:
            available_width = 450  # 기본값

        # 3열 기준으로 각 아이템 너비 계산 (여백 고려)
        cols = 3
        spacing = 10  # 그리드 간격
        item_padding = 10  # 아이템 내부 패딩

        # 아이템 하나의 너비 = (전체 너비 - 간격) / 열 수 - 내부 패딩
        item_width = (available_width - (cols - 1) * spacing) // cols - item_padding

        # 최소/최대 크기 제한
        item_width = max(80, min(180, item_width))

        # 비율에 맞는 높이 계산 (368:512 비율)
        item_height = int(item_width / THUMB_ASPECT_RATIO)

        return item_width, item_height

    def _update_favorites_grid(self):
        """즐겨찾기 그리드 업데이트 (UI 크기에 맞게 동적 조절, 좌측 정렬)"""
        # 기존 위젯 제거
        while self.favorites_grid_layout.count():
            item = self.favorites_grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        current_mode = "NAI"
        if self.preset_module and self.preset_module.app_context:
            current_mode = self.preset_module.app_context.get_api_mode() or "NAI"

        # 현재 모드의 즐겨찾기만 필터링
        mode_favorites = [f for f in self.favorites if f.get("mode", "NAI") == current_mode]

        if not mode_favorites:
            empty_label = QLabel("즐겨찾기가 없습니다.\n프리셋을 선택하고 ⭐ 버튼을 눌러 추가하세요.")
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_label.setStyleSheet(f"""
                QLabel {{
                    color: {DARK_COLORS['text_disabled']};
                    font-size: {get_scaled_font_size(12)}px;
                    padding: 40px;
                }}
            """)
            self.favorites_grid_layout.addWidget(empty_label, 0, 0, 1, 3)
            return

        # 동적 썸네일 크기 계산
        thumb_width, thumb_height = self._calculate_thumbnail_size()

        # 그리드에 아이템 추가 (3열, 좌측 정렬)
        cols = 3
        for idx, fav in enumerate(mode_favorites):
            preset_name = fav.get("name", "")
            thumb_path = self.FAVORITES_DIR / f"{preset_name}.png"

            item_widget = PresetFavoriteItemWidget(
                preset_name, thumb_path,
                thumb_width=thumb_width,
                thumb_height=thumb_height
            )
            item_widget.clicked.connect(self._on_favorite_clicked)

            row = idx // cols
            col = idx % cols
            self.favorites_grid_layout.addWidget(
                item_widget, row, col,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
            )

    def _update_current_preset_ui(self):
        """현재 선택된 프리셋 UI 업데이트"""
        if not self.preset_module:
            return

        current_preset = self.preset_module.current_preset
        current_mode = "NAI"
        if self.preset_module.app_context:
            current_mode = self.preset_module.app_context.get_api_mode() or "NAI"

        # default 프리셋 여부 확인
        is_default = (current_preset == "default")

        # 썸네일 업데이트
        thumb_path = self.FAVORITES_DIR / f"{current_preset}.png"
        if thumb_path.exists():
            pixmap = QPixmap(str(thumb_path))
            scaled = pixmap.scaled(
                PREVIEW_THUMB_WIDTH, PREVIEW_THUMB_HEIGHT,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.current_preset_thumb.setPixmap(scaled)
            self.current_preset_thumb.setStyleSheet(f"""
                QLabel {{
                    background-color: {DARK_COLORS['bg_primary']};
                    border: 2px solid {DARK_COLORS['border']};
                    border-radius: 6px;
                }}
            """)
        else:
            self.current_preset_thumb.clear()
            self.current_preset_thumb.setText("썸네일\n없음")
            self.current_preset_thumb.setStyleSheet(f"""
                QLabel {{
                    background-color: {DARK_COLORS['bg_primary']};
                    border: 2px dashed {DARK_COLORS['border']};
                    border-radius: 6px;
                    color: {DARK_COLORS['text_disabled']};
                    font-size: {get_scaled_font_size(14)}px;
                }}
            """)

        # default 프리셋일 경우 버튼 비활성화
        self.paste_thumb_btn.setEnabled(not is_default)
        self.favorite_btn.setEnabled(not is_default)

        # 즐겨찾기 버튼 상태 업데이트
        is_favorite = any(
            f.get("name") == current_preset and f.get("mode") == current_mode
            for f in self.favorites
        )

        if is_favorite:
            self.favorite_btn.setText("💔 즐겨찾기에서 제거")
            self.favorite_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        else:
            self.favorite_btn.setText("⭐ 즐겨찾기에 등록")
            self.favorite_btn.setStyleSheet(DARK_STYLES['primary_button'])

    def _open_preset_folder(self):
        """프리셋 폴더 열기"""
        import subprocess
        import os

        current_mode = "NAI"
        if self.preset_module and self.preset_module.app_context:
            current_mode = self.preset_module.app_context.get_api_mode() or "NAI"

        preset_dir = Path("save/presets") / current_mode

        if not preset_dir.exists():
            preset_dir.mkdir(parents=True, exist_ok=True)

        # Windows 탐색기로 폴더 열기
        if os.name == 'nt':
            subprocess.Popen(['explorer', str(preset_dir.resolve())])
        else:
            # macOS / Linux
            subprocess.Popen(['open' if os.uname().sysname == 'Darwin' else 'xdg-open', str(preset_dir.resolve())])

    def _paste_thumbnail_from_clipboard(self):
        """클립보드에서 썸네일 이미지 붙여넣기"""
        if not self.preset_module:
            return

        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData()

        if mime_data.hasImage():
            qimage = clipboard.image()
            if qimage.isNull():
                self._show_warning("오류", "클립보드에 유효한 이미지가 없습니다.")
                return

            # QImage -> PIL Image 변환
            buffer = qimage.bits().asstring(qimage.sizeInBytes())
            pil_image = Image.frombytes(
                "RGBA" if qimage.hasAlphaChannel() else "RGB",
                (qimage.width(), qimage.height()),
                buffer,
                "raw",
                "BGRA" if qimage.hasAlphaChannel() else "BGR"
            )

            # 스마트 크롭 및 리사이즈
            cropped = self._smart_crop_image(pil_image, 368, 512)

            # 저장
            current_preset = self.preset_module.current_preset
            thumb_path = self.FAVORITES_DIR / f"{current_preset}.png"
            cropped.save(str(thumb_path), "PNG")

            print(f"✅ 썸네일 저장: {thumb_path}")

            # UI 업데이트
            self._update_current_preset_ui()
            self._update_favorites_grid()

            self._show_info("완료", f"'{current_preset}' 프리셋의 썸네일이 저장되었습니다.")
        else:
            self._show_warning("오류", "클립보드에 이미지가 없습니다.\n이미지를 복사한 후 다시 시도하세요.")

    def _smart_crop_image(self, image: Image.Image, target_width: int, target_height: int) -> Image.Image:
        """이미지를 스마트 크롭하여 목표 비율에 맞춤 (상단 중앙 포커싱)"""
        img_width, img_height = image.size
        target_ratio = target_width / target_height
        img_ratio = img_width / img_height

        # 1단계: 비율 맞춤 크롭
        if img_ratio > target_ratio:
            # 가로로 긴 이미지 -> 중앙 크롭
            new_width = int(img_height * target_ratio)
            left = (img_width - new_width) // 2
            crop_box = (left, 0, left + new_width, img_height)
        else:
            # 세로로 긴 이미지 -> 상단 크롭
            new_height = int(img_width / target_ratio)
            crop_box = (0, 0, img_width, new_height)

        cropped = image.crop(crop_box)

        # 2단계: 상단 중앙 포커싱 크롭 (얼굴 영역)
        # 368:512 비율 유지하면서 상단 중앙 영역 추출
        crop_w, crop_h = cropped.size

        # 포커싱 영역 크기 계산 (원본의 약 50% 크기, 368:512 비율 유지)
        focus_ratio = THUMB_ASPECT_RATIO  # 368/512 = 0.71875

        # 세로 기준으로 60% 영역 사용 (상단 포커싱)
        focus_h = int(crop_h * 0.6)
        focus_w = int(focus_h * focus_ratio)

        # 가로가 원본보다 크면 가로 기준으로 재계산
        if focus_w > crop_w * 0.8:
            focus_w = int(crop_w * 0.8)
            focus_h = int(focus_w / focus_ratio)

        # 중앙 정렬 (가로), 상단 정렬 (세로)
        focus_left = (crop_w - focus_w) // 2
        focus_top = 0

        focused = cropped.crop((focus_left, focus_top, focus_left + focus_w, focus_top + focus_h))

        # 최종 리사이즈
        return focused.resize((target_width, target_height), Image.Resampling.LANCZOS)

    def _toggle_favorite(self):
        """즐겨찾기 등록/제거 토글"""
        if not self.preset_module:
            return

        current_preset = self.preset_module.current_preset
        current_mode = "NAI"
        if self.preset_module.app_context:
            current_mode = self.preset_module.app_context.get_api_mode() or "NAI"

        # default는 즐겨찾기 불가
        if current_preset == "default":
            self._show_warning("알림", "default 프리셋은 즐겨찾기에 등록할 수 없습니다.")
            return

        # 현재 즐겨찾기 상태 확인
        is_favorite = any(
            f.get("name") == current_preset and f.get("mode") == current_mode
            for f in self.favorites
        )

        if is_favorite:
            # 즐겨찾기 제거
            self.favorites = [
                f for f in self.favorites
                if not (f.get("name") == current_preset and f.get("mode") == current_mode)
            ]
            self._save_favorites()
            self._update_favorites_grid()
            self._update_current_preset_ui()
            print(f"💔 즐겨찾기 제거: {current_preset}")
        else:
            # 즐겨찾기 등록 전 썸네일 확인
            thumb_path = self.FAVORITES_DIR / f"{current_preset}.png"
            if not thumb_path.exists():
                if self._show_question(
                    "썸네일 필요",
                    f"'{current_preset}' 프리셋의 썸네일이 없습니다.\n"
                    "클립보드에서 이미지를 붙여넣으시겠습니까?"
                ):
                    self._paste_thumbnail_from_clipboard()
                    # 썸네일 저장 후 다시 확인
                    if not thumb_path.exists():
                        return
                else:
                    return

            # 즐겨찾기 등록
            self.favorites.append({
                "name": current_preset,
                "mode": current_mode
            })
            self._save_favorites()
            self._update_favorites_grid()
            self._update_current_preset_ui()
            print(f"⭐ 즐겨찾기 등록: {current_preset}")

    def _on_favorite_clicked(self, preset_name: str):
        """즐겨찾기 아이템 클릭 시 해당 프리셋 선택"""
        if not self.preset_module:
            return

        # 콤보박스에서 해당 프리셋 선택
        self.remote_preset_combo.setCurrentText(preset_name)

    def _create_character_tab(self):
        """탭2: 캐릭터 (이중 탭 - 레퍼런스, 프롬프트)"""
        char_widget = QWidget()
        char_layout = QVBoxLayout(char_widget)
        char_layout.setContentsMargins(4, 4, 4, 4)

        # 이중 탭
        char_sub_tabs = QTabWidget()
        char_sub_tabs.setStyleSheet(DARK_STYLES['dark_tabs'])
        char_layout.addWidget(char_sub_tabs)

        # 서브탭1: 레퍼런스 (새로운 즐겨찾기 시스템)
        self._create_char_ref_subtab(char_sub_tabs)

        # 서브탭2: 프롬프트 (CharacterModule) - 새로운 UI
        self._create_char_prompt_subtab(char_sub_tabs)

        self.main_tabs.addTab(char_widget, "👤 캐릭터")

    def _create_char_prompt_subtab(self, parent_tabs: QTabWidget):
        """캐릭터 프롬프트 서브탭 - 인원 수 설정 + 캐릭터 슬롯 + 즐겨찾기"""
        prompt_widget = QWidget()
        prompt_layout = QVBoxLayout(prompt_widget)
        prompt_layout.setContentsMargins(8, 8, 8, 8)
        prompt_layout.setSpacing(8)

        if not self.character_module:
            placeholder = QLabel("캐릭터 모듈을 찾을 수 없습니다.")
            placeholder.setStyleSheet(f"color: {DARK_COLORS['text_disabled']};")
            prompt_layout.addWidget(placeholder)
            parent_tabs.addTab(prompt_widget, "👤 프롬프트")
            return

        # === 상단: activate/reroll 체크박스 미러 버튼 ===
        options_frame = QFrame()
        options_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 6px;
            }}
        """)
        options_layout = QHBoxLayout(options_frame)
        options_layout.setContentsMargins(8, 6, 8, 6)
        options_layout.setSpacing(12)

        # 활성화 체크박스
        self.char_prompt_activate_check = QCheckBox("캐릭터 프롬프트 활성화")
        self.char_prompt_activate_check.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.char_prompt_activate_check.stateChanged.connect(self._on_char_prompt_activate_changed)
        options_layout.addWidget(self.char_prompt_activate_check)

        # 생성 시 리롤 체크박스
        self.char_prompt_reroll_check = QCheckBox("생성 시 와일드카드 개봉")
        self.char_prompt_reroll_check.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.char_prompt_reroll_check.stateChanged.connect(self._on_char_prompt_reroll_changed)
        options_layout.addWidget(self.char_prompt_reroll_check)

        options_layout.addStretch()
        prompt_layout.addWidget(options_frame)

        # === 인원 수 설정 섹션 ===
        person_frame = QFrame()
        person_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 6px;
            }}
        """)
        person_layout = QHBoxLayout(person_frame)
        person_layout.setContentsMargins(8, 6, 8, 6)
        person_layout.setSpacing(8)

        person_label = QLabel("인원 수 설정:")
        person_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(15)}px;
            }}
        """)
        person_layout.addWidget(person_label)

        # 라디오 버튼 그룹 (1-6)
        self.char_prompt_person_group = QButtonGroup(self)
        self.char_prompt_person_radios = []

        for i in range(1, 7):
            radio = QRadioButton(str(i))
            radio.setStyleSheet(f"""
                QRadioButton {{
                    color: {DARK_COLORS['text_primary']};
                    font-size: {get_scaled_font_size(15)}px;
                    spacing: 4px;
                }}
                QRadioButton::indicator {{
                    width: 16px;
                    height: 16px;
                }}
            """)
            if i == 1:
                radio.setChecked(True)
            self.char_prompt_person_group.addButton(radio, i)
            self.char_prompt_person_radios.append(radio)
            person_layout.addWidget(radio)

        self.char_prompt_person_group.idClicked.connect(self._on_char_prompt_person_changed)
        person_layout.addStretch()
        prompt_layout.addWidget(person_frame)

        # === 구분선 ===
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet(f"background-color: {DARK_COLORS['border']};")
        separator.setFixedHeight(1)
        prompt_layout.addWidget(separator)

        # === 활성 캐릭터 프롬프트 섹션 ===
        slots_label = QLabel("활성 캐릭터 프롬프트 (선택 후 즐겨찾기 클릭)")
        slots_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(12)}px;
            }}
        """)
        prompt_layout.addWidget(slots_label)

        # 캐릭터 슬롯 프레임들 (C1-C6)
        self.char_prompt_slot_frames = []
        self.char_prompt_slot_edits = []

        for i in range(6):
            slot_frame = QFrame()
            slot_frame.setProperty("slot_index", i)
            slot_frame.setCursor(Qt.CursorShape.PointingHandCursor)
            slot_frame.mousePressEvent = lambda event, idx=i: self._on_char_prompt_slot_clicked(idx)
            self._update_slot_frame_style(slot_frame, i == 0)  # 첫 번째 선택

            slot_layout = QHBoxLayout(slot_frame)
            slot_layout.setContentsMargins(8, 4, 8, 4)
            slot_layout.setSpacing(8)

            # C 라벨
            c_label = QLabel(f"C{i+1}")
            c_label.setFixedWidth(30)
            c_label.setStyleSheet(f"""
                QLabel {{
                    color: {DARK_COLORS['text_primary']};
                    font-size: {get_scaled_font_size(16)}px;
                    font-weight: bold;
                    background: transparent;
                    border: none;
                }}
            """)
            slot_layout.addWidget(c_label)

            # 프롬프트 표시 (읽기 전용)
            slot_edit = QLineEdit()
            slot_edit.setReadOnly(True)
            slot_edit.setPlaceholderText("(비어 있음)")
            slot_edit.setCursor(Qt.CursorShape.PointingHandCursor)
            slot_edit.setStyleSheet(f"""
                QLineEdit {{
                    background-color: {DARK_COLORS['bg_primary']};
                    color: {DARK_COLORS['text_primary']};
                    border: 1px solid {DARK_COLORS['border']};
                    border-radius: 4px;
                    padding: 4px 8px;
                    font-size: {get_scaled_font_size(16)}px;
                }}
            """)
            # QLineEdit 클릭 시 슬롯 선택
            slot_edit.mousePressEvent = lambda event, idx=i: self._on_char_prompt_slot_clicked(idx)
            slot_layout.addWidget(slot_edit, 1)

            # 수정 버튼
            edit_btn = QPushButton("수정")
            edit_btn.setFixedWidth(80)
            edit_btn.setStyleSheet(DARK_STYLES['secondary_button'])
            edit_btn.clicked.connect(lambda checked, idx=i: self._on_char_prompt_slot_edit(idx))
            slot_layout.addWidget(edit_btn)

            self.char_prompt_slot_frames.append(slot_frame)
            self.char_prompt_slot_edits.append(slot_edit)
            prompt_layout.addWidget(slot_frame)

            # 초기에는 첫 번째만 표시
            if i > 0:
                slot_frame.setVisible(False)

        # === 하단: 즐겨찾기 탭뷰 ===
        favorites_tabs = QTabWidget()
        favorites_tabs.setStyleSheet(DARK_STYLES['dark_tabs'])

        # 즐겨찾기 탭
        fav_widget = self._create_char_prompt_favorites_tab()
        favorites_tabs.addTab(fav_widget, "⭐ 즐겨찾기")

        # 즐겨찾기 관리 탭
        manage_widget = self._create_char_prompt_manage_tab()
        favorites_tabs.addTab(manage_widget, "⚙️ 즐겨찾기 관리")

        prompt_layout.addWidget(favorites_tabs, 1)

        parent_tabs.addTab(prompt_widget, "👤 프롬프트")

        # 초기 동기화
        QTimer.singleShot(100, self._sync_char_prompt_from_module)

    def _update_slot_frame_style(self, frame: QFrame, is_selected: bool):
        """슬롯 프레임 스타일 업데이트"""
        if is_selected:
            frame.setStyleSheet(f"""
                QFrame {{
                    background-color: {DARK_COLORS['bg_secondary']};
                    border: 2px solid {DARK_COLORS['accent_blue']};
                    border-radius: 6px;
                }}
            """)
        else:
            frame.setStyleSheet(f"""
                QFrame {{
                    background-color: {DARK_COLORS['bg_tertiary']};
                    border: 1px solid {DARK_COLORS['border']};
                    border-radius: 6px;
                }}
                QFrame:hover {{
                    border-color: {DARK_COLORS['border_light']};
                }}
            """)

    def _create_char_prompt_favorites_tab(self) -> QWidget:
        """캐릭터 프롬프트 즐겨찾기 탭"""
        fav_widget = QWidget()
        fav_layout = QVBoxLayout(fav_widget)
        fav_layout.setContentsMargins(4, 4, 4, 4)
        fav_layout.setSpacing(4)

        # 폴더 선택 + 추가/관리 버튼
        folder_row = QHBoxLayout()
        folder_row.setSpacing(6)

        folder_label = QLabel("폴더:")
        folder_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']};")
        folder_row.addWidget(folder_label)

        self.char_prompt_folder_combo = QComboBox()
        self.char_prompt_folder_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
        self.char_prompt_folder_combo.addItems(self.char_prompt_folders)
        self.char_prompt_folder_combo.currentTextChanged.connect(self._on_char_prompt_folder_changed)
        folder_row.addWidget(self.char_prompt_folder_combo, 1)

        add_folder_btn = QPushButton("폴더 추가")
        add_folder_btn.setFixedWidth(100)
        add_folder_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        add_folder_btn.setToolTip("새 폴더 추가")
        add_folder_btn.clicked.connect(self._on_char_prompt_add_folder)
        folder_row.addWidget(add_folder_btn)

        delete_char_btn = QPushButton("캐릭터 삭제")
        delete_char_btn.setFixedWidth(100)
        delete_char_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        delete_char_btn.setToolTip("선택된 캐릭터 삭제")
        delete_char_btn.clicked.connect(self._on_char_prompt_delete_character)
        folder_row.addWidget(delete_char_btn)

        fav_layout.addLayout(folder_row)

        # 즐겨찾기 그리드 (스크롤 영역)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"""
            QScrollArea {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
            }}
            QScrollArea > QWidget > QWidget {{
                background-color: {DARK_COLORS['bg_primary']};
            }}
        """)

        self.char_prompt_favorites_container = QWidget()
        self.char_prompt_favorites_container.setStyleSheet(f"background-color: {DARK_COLORS['bg_primary']};")
        self.char_prompt_favorites_grid = QGridLayout(self.char_prompt_favorites_container)
        self.char_prompt_favorites_grid.setContentsMargins(4, 4, 4, 4)
        self.char_prompt_favorites_grid.setSpacing(6)
        scroll.setWidget(self.char_prompt_favorites_container)

        fav_layout.addWidget(scroll, 1)

        return fav_widget

    def _create_char_prompt_manage_tab(self) -> QWidget:
        """캐릭터 프롬프트 즐겨찾기 관리 탭"""
        manage_widget = QWidget()
        manage_layout = QVBoxLayout(manage_widget)
        manage_layout.setContentsMargins(8, 8, 8, 8)
        manage_layout.setSpacing(8)

        # === 상단 섹션: 썸네일 + 폴더/아이템 선택 ===
        top_section = QHBoxLayout()
        top_section.setSpacing(12)

        # 좌측: 큰 썸네일 영역
        self.char_prompt_manage_thumb = QLabel()
        self.char_prompt_manage_thumb.setFixedSize(
            CHAR_PROMPT_MANAGE_THUMB_WIDTH, CHAR_PROMPT_MANAGE_THUMB_HEIGHT
        )
        self.char_prompt_manage_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.char_prompt_manage_thumb.setStyleSheet(f"""
            QLabel {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 6px;
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(12)}px;
            }}
        """)
        self.char_prompt_manage_thumb.setText("썸네일 없음")
        top_section.addWidget(self.char_prompt_manage_thumb)

        # 우측: 폴더/아이템 선택 영역
        right_top = QVBoxLayout()
        right_top.setSpacing(4)

        # 라벨 스타일 (폰트 15px)
        label_style = f"""
            color: {DARK_COLORS['text_primary']};
            font-size: {get_scaled_font_size(15)}px;
        """

        # 캐릭터 폴더 그룹 라벨
        folder_label = QLabel("캐릭터 폴더 그룹")
        folder_label.setStyleSheet(label_style)
        right_top.addWidget(folder_label)

        # 폴더 콤보박스 + 추가 버튼 행
        folder_row = QHBoxLayout()
        folder_row.setSpacing(6)
        self.char_prompt_manage_folder_combo = QComboBox()
        self.char_prompt_manage_folder_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
        self.char_prompt_manage_folder_combo.currentTextChanged.connect(
            self._on_manage_folder_changed
        )
        folder_row.addWidget(self.char_prompt_manage_folder_combo, 1)

        # 폴더 추가 버튼
        add_folder_btn = QPushButton("추가")
        add_folder_btn.setFixedWidth(50)
        add_folder_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        add_folder_btn.clicked.connect(self._on_manage_add_folder)
        folder_row.addWidget(add_folder_btn)
        right_top.addLayout(folder_row)

        # 캐릭터 선택 라벨
        item_label = QLabel("캐릭터 선택 (신규 등록시 무시)")
        item_label.setStyleSheet(label_style)
        right_top.addWidget(item_label)

        # 아이템 콤보박스
        self.char_prompt_manage_item_combo = QComboBox()
        self.char_prompt_manage_item_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
        self.char_prompt_manage_item_combo.currentIndexChanged.connect(
            self._on_manage_item_changed
        )
        right_top.addWidget(self.char_prompt_manage_item_combo)

        # 수정/삭제 버튼 행
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self.char_prompt_manage_edit_btn = QPushButton("수정")
        self.char_prompt_manage_edit_btn.setFixedWidth(80)
        self.char_prompt_manage_edit_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.char_prompt_manage_edit_btn.clicked.connect(self._on_manage_edit_clicked)

        self.char_prompt_manage_delete_btn = QPushButton("삭제")
        self.char_prompt_manage_delete_btn.setFixedWidth(80)
        self.char_prompt_manage_delete_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.char_prompt_manage_delete_btn.clicked.connect(self._on_manage_delete_clicked)

        btn_row.addWidget(self.char_prompt_manage_edit_btn)
        btn_row.addWidget(self.char_prompt_manage_delete_btn)
        btn_row.addStretch()
        right_top.addLayout(btn_row)

        # 신규 등록 버튼 (별도 행)
        register_btn = QPushButton("신규 등록")
        register_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['accent_blue']};
                color: white;
                border: none;
                padding: 6px 12px;
                border-radius: 4px;
                font-size: {get_scaled_font_size(15)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['accent_blue_hover']};
            }}
        """)
        register_btn.clicked.connect(self._on_manage_register_clicked)
        right_top.addWidget(register_btn)

        right_top.addStretch()
        top_section.addLayout(right_top, 1)
        manage_layout.addLayout(top_section)

        # === 중간 섹션: 프롬프트 편집 ===
        prompt_section = QVBoxLayout()
        prompt_section.setSpacing(2)
        prompt_section.setContentsMargins(0, 4, 0, 0)

        # 캐릭터 프롬프트
        prompt_label = QLabel("캐릭터 프롬프트")
        prompt_label.setStyleSheet(f"""
            color: {DARK_COLORS['text_primary']};
            font-size: {get_scaled_font_size(15)}px;
            margin-bottom: 2px;
        """)
        prompt_section.addWidget(prompt_label)

        self.char_prompt_manage_prompt_edit = QTextEdit()
        self.char_prompt_manage_prompt_edit.setPlaceholderText("캐릭터 프롬프트를 입력하세요...")
        self.char_prompt_manage_prompt_edit.setMinimumHeight(120)
        self.char_prompt_manage_prompt_edit.setStyleSheet(DARK_STYLES['compact_textedit'])
        prompt_section.addWidget(self.char_prompt_manage_prompt_edit)

        # 네거티브 프롬프트
        uc_label = QLabel("네거티브 프롬프트")
        uc_label.setStyleSheet(f"""
            color: {DARK_COLORS['text_primary']};
            font-size: {get_scaled_font_size(15)}px;
            margin-bottom: 2px;
        """)
        prompt_section.addWidget(uc_label)

        self.char_prompt_manage_uc_edit = QTextEdit()
        self.char_prompt_manage_uc_edit.setPlaceholderText("네거티브 프롬프트를 입력하세요...")
        self.char_prompt_manage_uc_edit.setMaximumHeight(80)
        self.char_prompt_manage_uc_edit.setStyleSheet(DARK_STYLES['compact_textedit'])
        prompt_section.addWidget(self.char_prompt_manage_uc_edit)

        manage_layout.addLayout(prompt_section)

        # === 하단 섹션: 액션 버튼들 ===
        bottom_section = QHBoxLayout()
        bottom_section.setSpacing(6)

        # 캐릭터 검색 버튼 (보라색 배경)
        search_btn = QPushButton("캐릭터 검색")
        search_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #7C4DFF;
                color: white;
                border: none;
                padding: 6px 12px;
                border-radius: 4px;
                font-size: {get_scaled_font_size(15)}px;
            }}
            QPushButton:hover {{
                background-color: #651FFF;
            }}
        """)
        search_btn.clicked.connect(self._on_manage_search_clicked)
        bottom_section.addWidget(search_btn)

        # 썸네일 이미지 생성 버튼
        gen_thumb_btn = QPushButton("썸네일 생성")
        gen_thumb_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        gen_thumb_btn.clicked.connect(self._on_manage_gen_thumb_clicked)
        bottom_section.addWidget(gen_thumb_btn)

        # 썸네일 붙여넣기 버튼
        paste_thumb_btn = QPushButton("썸네일 붙여넣기")
        paste_thumb_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        paste_thumb_btn.clicked.connect(self._on_manage_paste_thumb_clicked)
        bottom_section.addWidget(paste_thumb_btn)

        manage_layout.addLayout(bottom_section)

        # 콤보박스 데이터 초기화
        self._refresh_manage_folder_combo()

        return manage_widget

    # === 캐릭터 프롬프트 탭 이벤트 핸들러 ===

    def _on_char_prompt_activate_changed(self, state: int):
        """활성화 체크박스 변경 → 모듈에 반영"""
        if not self.character_module or not hasattr(self.character_module, 'activate_checkbox'):
            return
        is_checked = state == Qt.CheckState.Checked.value
        self.character_module.activate_checkbox.setChecked(is_checked)

    def _on_char_prompt_reroll_changed(self, state: int):
        """생성 시 리롤 체크박스 변경 → 모듈에 반영"""
        if not self.character_module or not hasattr(self.character_module, 'reroll_on_generate_checkbox'):
            return
        is_checked = state == Qt.CheckState.Checked.value
        self.character_module.reroll_on_generate_checkbox.setChecked(is_checked)

    def _on_char_prompt_person_changed(self, person_id: int):
        """인원 수 라디오 버튼 변경"""
        self.char_prompt_person_count = person_id

        # 슬롯 프레임 표시/숨김
        for i, frame in enumerate(self.char_prompt_slot_frames):
            frame.setVisible(i < person_id)

        # character_module의 캐릭터 위젯 관리
        self._adjust_character_widgets(person_id)

        # 슬롯 내용 업데이트
        self._update_char_prompt_slots()

    def _adjust_character_widgets(self, target_count: int):
        """character_module의 캐릭터 위젯 수 조정"""
        if not self.character_module or not hasattr(self.character_module, 'character_widgets'):
            return

        current_count = len(self.character_module.character_widgets)

        # 위젯 수가 부족하면 추가
        while current_count < target_count:
            if hasattr(self.character_module, 'add_character_widget'):
                self.character_module.add_character_widget()
            current_count = len(self.character_module.character_widgets)

        # 위젯 수가 초과하면: 빈 프레임 삭제 또는 비활성화
        for i, widget in enumerate(self.character_module.character_widgets):
            if i < target_count:
                # 필요한 범위: 활성화
                if hasattr(widget, 'active_checkbox'):
                    widget.active_checkbox.setChecked(True)
                widget.setEnabled(True)
            else:
                # 초과 범위
                is_empty = self._is_character_widget_empty(widget)
                if is_empty:
                    # 빈 프레임은 비활성화 (삭제는 안전하지 않을 수 있음)
                    if hasattr(widget, 'active_checkbox'):
                        widget.active_checkbox.setChecked(False)
                    widget.setEnabled(False)
                else:
                    # 비어있지 않은 프레임은 비활성화만
                    if hasattr(widget, 'active_checkbox'):
                        widget.active_checkbox.setChecked(False)
                    widget.setEnabled(False)

    def _is_character_widget_empty(self, widget) -> bool:
        """캐릭터 위젯이 비어있는지 확인"""
        prompt_text = ""
        uc_text = ""

        if hasattr(widget, 'prompt_textbox'):
            prompt_text = widget.prompt_textbox.toPlainText().strip()
        if hasattr(widget, 'uc_textbox'):
            uc_text = widget.uc_textbox.toPlainText().strip()

        return not prompt_text and not uc_text

    def _on_char_prompt_slot_clicked(self, slot_index: int):
        """캐릭터 슬롯 클릭 → 선택"""
        old_index = self.char_prompt_selected_slot
        self.char_prompt_selected_slot = slot_index

        # 스타일 업데이트
        if old_index < len(self.char_prompt_slot_frames):
            self._update_slot_frame_style(self.char_prompt_slot_frames[old_index], False)
        if slot_index < len(self.char_prompt_slot_frames):
            self._update_slot_frame_style(self.char_prompt_slot_frames[slot_index], True)

    def _on_char_prompt_slot_edit(self, slot_index: int):
        """캐릭터 슬롯 수정 버튼 클릭"""
        if not self.character_module or not hasattr(self.character_module, 'character_widgets'):
            return

        widgets = self.character_module.character_widgets
        if slot_index >= len(widgets):
            self._show_warning("경고", f"C{slot_index+1} 캐릭터가 존재하지 않습니다.")
            return

        widget = widgets[slot_index]

        # 현재 값 가져오기
        current_prompt = ""
        current_uc = ""
        if hasattr(widget, 'prompt_textbox'):
            current_prompt = widget.prompt_textbox.toPlainText()
        if hasattr(widget, 'uc_textbox'):
            current_uc = widget.uc_textbox.toPlainText()

        # 편집 다이얼로그 열기
        self._open_char_prompt_edit_dialog(slot_index, current_prompt, current_uc)

    def _open_char_prompt_edit_dialog(self, slot_index: int, current_prompt: str, current_uc: str):
        """캐릭터 프롬프트 편집 다이얼로그"""
        dialog = QDialog(self)
        dialog.setWindowTitle(f"C{slot_index+1} 캐릭터 프롬프트 편집")
        dialog.setMinimumSize(500, 400)
        self._style_dialog(dialog)

        layout = QVBoxLayout(dialog)
        layout.setSpacing(12)

        # 프롬프트
        prompt_label = QLabel("캐릭터 프롬프트:")
        prompt_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-weight: bold;")
        layout.addWidget(prompt_label)

        prompt_edit = QTextEdit()
        prompt_edit.setAcceptRichText(False)
        prompt_edit.setPlainText(current_prompt)
        prompt_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                font-size: {get_scaled_font_size(16)}px;
            }}
        """)
        layout.addWidget(prompt_edit, 1)

        # UC
        uc_label = QLabel("부정 프롬프트 (UC):")
        uc_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-weight: bold;")
        layout.addWidget(uc_label)

        uc_edit = QTextEdit()
        uc_edit.setAcceptRichText(False)
        uc_edit.setPlainText(current_uc)
        uc_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                font-size: {get_scaled_font_size(16)}px;
            }}
        """)
        layout.addWidget(uc_edit, 1)

        # 버튼
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        save_btn = QPushButton("저장")
        save_btn.setStyleSheet(DARK_STYLES['primary_button'])
        save_btn.clicked.connect(dialog.accept)
        btn_layout.addWidget(save_btn)

        cancel_btn = QPushButton("취소")
        cancel_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        cancel_btn.clicked.connect(dialog.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_prompt = prompt_edit.toPlainText()
            new_uc = uc_edit.toPlainText()
            self._apply_char_prompt_to_module(slot_index, new_prompt, new_uc)

    def _apply_char_prompt_to_module(self, slot_index: int, prompt: str, uc: str):
        """캐릭터 프롬프트를 모듈에 적용"""
        if not self.character_module or not hasattr(self.character_module, 'character_widgets'):
            return

        widgets = self.character_module.character_widgets
        if slot_index >= len(widgets):
            return

        widget = widgets[slot_index]
        if hasattr(widget, 'prompt_textbox'):
            widget.prompt_textbox.setPlainText(prompt)
        if hasattr(widget, 'uc_textbox'):
            widget.uc_textbox.setPlainText(uc)

        # 슬롯 표시 업데이트
        self._update_char_prompt_slots()

    def _on_char_prompt_folder_changed(self, folder_name: str):
        """즐겨찾기 폴더 변경"""
        self.char_prompt_current_folder = folder_name
        self._update_char_prompt_favorites_grid()

    def _on_char_prompt_add_folder(self):
        """새 즐겨찾기 폴더 추가"""
        name, ok = self._get_text_input("새 폴더", "폴더 이름을 입력하세요:")
        if ok and name:
            if name not in self.char_prompt_folders:
                self.char_prompt_folders.append(name)
                self.char_prompt_folder_combo.addItem(name)
                self._save_char_prompt_folders()
            else:
                self._show_warning("경고", "이미 존재하는 폴더 이름입니다.")

    def _on_char_prompt_delete_folder(self):
        """선택된 즐겨찾기 폴더 삭제"""
        current_folder = self.char_prompt_folder_combo.currentText()

        if current_folder == "기본":
            self._show_warning("경고", "기본 폴더는 삭제할 수 없습니다.")
            return

        # 해당 폴더의 즐겨찾기 개수 확인
        folder_favorites = [f for f in self.char_prompt_favorites
                           if f.get("folder", "기본") == current_folder]

        confirm_msg = f"'{current_folder}' 폴더를 삭제하시겠습니까?"
        if folder_favorites:
            confirm_msg += f"\n\n이 폴더에 {len(folder_favorites)}개의 즐겨찾기가 있습니다.\n즐겨찾기도 함께 삭제됩니다."

        if not self._show_question("폴더 삭제", confirm_msg):
            return

        # 폴더 내 즐겨찾기 삭제
        self.char_prompt_favorites = [f for f in self.char_prompt_favorites
                                      if f.get("folder", "기본") != current_folder]
        self._save_char_prompt_favorites()

        # 폴더 목록에서 제거
        self.char_prompt_folders.remove(current_folder)
        self._save_char_prompt_folders()

        # 콤보박스 업데이트
        idx = self.char_prompt_folder_combo.findText(current_folder)
        if idx >= 0:
            self.char_prompt_folder_combo.removeItem(idx)

        # 기본 폴더로 이동
        self.char_prompt_folder_combo.setCurrentText("기본")

    def _sync_char_prompt_from_module(self):
        """character_module에서 현재 상태 동기화"""
        if not self.character_module:
            return

        # 체크박스 동기화
        if hasattr(self.character_module, 'activate_checkbox') and self.character_module.activate_checkbox:
            self.char_prompt_activate_check.blockSignals(True)
            self.char_prompt_activate_check.setChecked(self.character_module.activate_checkbox.isChecked())
            self.char_prompt_activate_check.blockSignals(False)

        if hasattr(self.character_module, 'reroll_on_generate_checkbox') and self.character_module.reroll_on_generate_checkbox:
            self.char_prompt_reroll_check.blockSignals(True)
            self.char_prompt_reroll_check.setChecked(self.character_module.reroll_on_generate_checkbox.isChecked())
            self.char_prompt_reroll_check.blockSignals(False)

        # 슬롯 내용 업데이트
        self._update_char_prompt_slots()

        # 즐겨찾기 그리드 업데이트
        self._load_char_prompt_favorites()
        self._update_char_prompt_favorites_grid()

    def _update_char_prompt_slots(self):
        """캐릭터 슬롯 표시 업데이트 (모듈에서 데이터 읽기)"""
        if not self.character_module or not hasattr(self.character_module, 'character_widgets'):
            return

        widgets = self.character_module.character_widgets

        for i, slot_edit in enumerate(self.char_prompt_slot_edits):
            if i < len(widgets):
                widget = widgets[i]
                prompt_text = ""
                if hasattr(widget, 'prompt_textbox'):
                    prompt_text = widget.prompt_textbox.toPlainText().strip()

                # 첫 줄만 표시 (너무 길면 생략)
                if prompt_text:
                    first_line = prompt_text.split('\n')[0]
                    if len(first_line) > 50:
                        first_line = first_line[:47] + "..."
                    slot_edit.setText(first_line)
                else:
                    slot_edit.setText("")
            else:
                slot_edit.setText("")

    def _update_char_prompt_favorites_grid(self):
        """캐릭터 프롬프트 즐겨찾기 그리드 업데이트"""
        # 기존 위젯 제거
        while self.char_prompt_favorites_grid.count():
            item = self.char_prompt_favorites_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 현재 폴더의 즐겨찾기 필터링
        folder_favorites = [f for f in self.char_prompt_favorites
                           if f.get("folder", "기본") == self.char_prompt_current_folder]

        if not folder_favorites:
            empty_label = QLabel("즐겨찾기가 없습니다.")
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_label.setStyleSheet(f"color: {DARK_COLORS['text_disabled']}; background-color: transparent;")
            self.char_prompt_favorites_grid.addWidget(empty_label, 0, 0)
            return

        # 4열 그리드로 배치
        cols = 4
        for idx, fav_data in enumerate(folder_favorites):
            row = idx // cols
            col = idx % cols

            # 썸네일 경로: thumbnail 필드에서 파일명 가져오기
            thumb_filename = fav_data.get("thumbnail", "")
            if thumb_filename:
                thumb_path = CHAR_PROMPT_FAVORITES_DIR / thumb_filename
            else:
                thumb_path = None

            # 선택 상태 확인
            is_selected = (hasattr(self, '_char_prompt_selected_fav') and
                          self._char_prompt_selected_fav and
                          self._char_prompt_selected_fav.get("name") == fav_data.get("name") and
                          self._char_prompt_selected_fav.get("folder") == fav_data.get("folder"))

            item_widget = CharacterPromptFavoriteItemWidget(
                fav_data, thumb_path,
                CHAR_PROMPT_THUMB_WIDTH, CHAR_PROMPT_THUMB_HEIGHT,
                is_selected=is_selected
            )
            item_widget.clicked.connect(self._on_char_prompt_favorite_clicked)
            self.char_prompt_favorites_grid.addWidget(item_widget, row, col)

        # 좌측 상단 정렬을 위한 스페이서 추가
        last_row = (len(folder_favorites) - 1) // cols + 1
        # 우측 스페이서
        self.char_prompt_favorites_grid.setColumnStretch(cols, 1)
        # 하단 스페이서
        self.char_prompt_favorites_grid.setRowStretch(last_row, 1)

    def _on_char_prompt_favorite_clicked(self, fav_data: dict):
        """즐겨찾기 아이템 클릭 → 선택된 슬롯에 적용"""
        prompt = fav_data.get("prompt", "")
        uc = fav_data.get("uc", "")

        # 선택 상태 저장
        self._char_prompt_selected_fav = fav_data

        # 모듈에 적용
        self._apply_char_prompt_to_module(self.char_prompt_selected_slot, prompt, uc)

        # 슬롯 프레임의 프롬프트 표시 업데이트
        slot_idx = self.char_prompt_selected_slot - 1  # 0-based index
        if hasattr(self, 'char_prompt_slot_edits') and 0 <= slot_idx < len(self.char_prompt_slot_edits):
            self.char_prompt_slot_edits[slot_idx].setText(prompt)

        # 그리드 업데이트하여 선택 표시
        self._update_char_prompt_favorites_grid()

    def _on_char_prompt_delete_character(self):
        """선택된 캐릭터 삭제"""
        if not hasattr(self, '_char_prompt_selected_fav') or not self._char_prompt_selected_fav:
            QMessageBox.warning(self, "알림", "삭제할 캐릭터를 먼저 선택해주세요.")
            return

        fav_data = self._char_prompt_selected_fav
        name = fav_data.get("name", "")
        folder = fav_data.get("folder", "기본")

        # 삭제 확인
        reply = QMessageBox.question(
            self, "캐릭터 삭제",
            f"'{name}' 캐릭터를 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # 썸네일 파일 삭제
        thumb_filename = fav_data.get("thumbnail", "")
        if thumb_filename:
            thumb_path = CHAR_PROMPT_FAVORITES_DIR / thumb_filename
            if thumb_path.exists():
                try:
                    thumb_path.unlink()
                except Exception as e:
                    print(f"썸네일 삭제 실패: {e}")

        # 즐겨찾기 목록에서 제거
        self.char_prompt_favorites = [
            f for f in self.char_prompt_favorites
            if not (f.get("name") == name and f.get("folder") == folder)
        ]

        # 선택 상태 초기화
        self._char_prompt_selected_fav = None

        # 저장 및 UI 업데이트
        self._save_char_prompt_favorites()
        self._update_char_prompt_favorites_grid()
        self._refresh_manage_folder_combo()

        QMessageBox.information(self, "완료", f"'{name}' 캐릭터가 삭제되었습니다.")

    def _load_char_prompt_favorites(self):
        """캐릭터 프롬프트 즐겨찾기 로드"""
        if CHAR_PROMPT_FAVORITES_JSON.exists():
            try:
                with open(CHAR_PROMPT_FAVORITES_JSON, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.char_prompt_favorites = data.get("favorites", [])
            except Exception as e:
                print(f"캐릭터 프롬프트 즐겨찾기 로드 실패: {e}")
                self.char_prompt_favorites = []

        if CHAR_PROMPT_FOLDERS_JSON.exists():
            try:
                with open(CHAR_PROMPT_FOLDERS_JSON, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.char_prompt_folders = data.get("folders", ["기본"])
            except Exception as e:
                print(f"캐릭터 프롬프트 폴더 로드 실패: {e}")
                self.char_prompt_folders = ["기본"]

    def _save_char_prompt_favorites(self):
        """캐릭터 프롬프트 즐겨찾기 저장"""
        try:
            CHAR_PROMPT_FAVORITES_DIR.mkdir(parents=True, exist_ok=True)
            with open(CHAR_PROMPT_FAVORITES_JSON, 'w', encoding='utf-8') as f:
                json.dump({"favorites": self.char_prompt_favorites}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"캐릭터 프롬프트 즐겨찾기 저장 실패: {e}")

    def _save_char_prompt_folders(self):
        """캐릭터 프롬프트 폴더 저장"""
        try:
            CHAR_PROMPT_FAVORITES_DIR.mkdir(parents=True, exist_ok=True)
            with open(CHAR_PROMPT_FOLDERS_JSON, 'w', encoding='utf-8') as f:
                json.dump({"folders": self.char_prompt_folders}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"캐릭터 프롬프트 폴더 저장 실패: {e}")

    # === 캐릭터 프롬프트 즐겨찾기 관리 탭 핸들러 ===

    def _refresh_manage_folder_combo(self):
        """관리 탭 폴더 콤보박스 새로고침"""
        if not hasattr(self, 'char_prompt_manage_folder_combo'):
            return

        self.char_prompt_manage_folder_combo.blockSignals(True)
        self.char_prompt_manage_folder_combo.clear()
        self.char_prompt_manage_folder_combo.addItems(self.char_prompt_folders)
        self.char_prompt_manage_folder_combo.blockSignals(False)

        # 첫 폴더 선택
        if self.char_prompt_folders:
            self._on_manage_folder_changed(self.char_prompt_folders[0])

    def _refresh_char_prompt_folder_combo(self):
        """즐겨찾기 탭 폴더 콤보박스 새로고침"""
        if not hasattr(self, 'char_prompt_folder_combo'):
            return

        current_folder = self.char_prompt_folder_combo.currentText()

        self.char_prompt_folder_combo.blockSignals(True)
        self.char_prompt_folder_combo.clear()
        self.char_prompt_folder_combo.addItems(self.char_prompt_folders)

        # 기존 선택 복원
        idx = self.char_prompt_folder_combo.findText(current_folder)
        if idx >= 0:
            self.char_prompt_folder_combo.setCurrentIndex(idx)

        self.char_prompt_folder_combo.blockSignals(False)

    def _on_manage_folder_changed(self, folder_name: str):
        """관리 탭 폴더 변경 → 아이템 콤보 업데이트"""
        if not folder_name or not hasattr(self, 'char_prompt_manage_item_combo'):
            return

        self.char_prompt_manage_item_combo.blockSignals(True)
        self.char_prompt_manage_item_combo.clear()

        # 해당 폴더의 즐겨찾기 필터링
        folder_items = [
            fav for fav in self.char_prompt_favorites
            if fav.get("folder", "기본") == folder_name
        ]

        for fav in folder_items:
            name = fav.get("name", "이름없음")
            self.char_prompt_manage_item_combo.addItem(name, fav)

        self.char_prompt_manage_item_combo.blockSignals(False)

        # 첫 아이템 선택
        if folder_items:
            self._on_manage_item_changed(0)
        else:
            self._clear_manage_display()

    def _on_manage_item_changed(self, index: int):
        """관리 탭 아이템 변경 → 상세 정보 표시"""
        if index < 0:
            self._clear_manage_display()
            return

        fav_data = self.char_prompt_manage_item_combo.itemData(index)
        if not fav_data:
            self._clear_manage_display()
            return

        # 썸네일 표시
        thumb_filename = fav_data.get("thumbnail", "")
        if thumb_filename:
            thumb_path = CHAR_PROMPT_FAVORITES_DIR / thumb_filename
            if thumb_path.exists():
                pixmap = QPixmap(str(thumb_path))
                scaled = pixmap.scaled(
                    CHAR_PROMPT_MANAGE_THUMB_WIDTH, CHAR_PROMPT_MANAGE_THUMB_HEIGHT,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.char_prompt_manage_thumb.setPixmap(scaled)
            else:
                self.char_prompt_manage_thumb.setText("썸네일 없음")
        else:
            self.char_prompt_manage_thumb.setText("썸네일 없음")

        # 프롬프트 표시
        self.char_prompt_manage_prompt_edit.setPlainText(fav_data.get("prompt", ""))
        self.char_prompt_manage_uc_edit.setPlainText(fav_data.get("uc", ""))

    def _clear_manage_display(self):
        """관리 탭 표시 초기화"""
        if hasattr(self, 'char_prompt_manage_thumb'):
            self.char_prompt_manage_thumb.setText("썸네일 없음")
            self.char_prompt_manage_thumb.setPixmap(QPixmap())
        if hasattr(self, 'char_prompt_manage_prompt_edit'):
            self.char_prompt_manage_prompt_edit.clear()
        if hasattr(self, 'char_prompt_manage_uc_edit'):
            self.char_prompt_manage_uc_edit.clear()

    def _on_manage_edit_clicked(self):
        """수정 버튼 클릭 → 현재 선택된 아이템 수정"""
        index = self.char_prompt_manage_item_combo.currentIndex()
        if index < 0:
            QMessageBox.warning(self, "알림", "수정할 아이템을 선택하세요.")
            return

        fav_data = self.char_prompt_manage_item_combo.itemData(index)
        if not fav_data:
            return

        # 현재 편집된 값으로 업데이트
        new_prompt = self.char_prompt_manage_prompt_edit.toPlainText().strip()
        new_uc = self.char_prompt_manage_uc_edit.toPlainText().strip()

        # 이름 수정 대화상자
        old_name = fav_data.get("name", "")
        new_name, ok = QInputDialog.getText(
            self, "이름 수정", "아이템 이름:", text=old_name
        )
        if not ok:
            return

        if not new_name.strip():
            new_name = old_name

        # 원본 데이터 찾아서 수정
        for fav in self.char_prompt_favorites:
            if fav.get("name") == old_name and fav.get("folder") == fav_data.get("folder"):
                fav["name"] = new_name.strip()
                fav["prompt"] = new_prompt
                fav["uc"] = new_uc
                break

        self._save_char_prompt_favorites()
        self._update_char_prompt_favorites_grid()
        self._refresh_manage_folder_combo()

        QMessageBox.information(self, "완료", "아이템이 수정되었습니다.")

    def _on_manage_delete_clicked(self):
        """삭제 버튼 클릭 → 현재 선택된 아이템 삭제"""
        index = self.char_prompt_manage_item_combo.currentIndex()
        if index < 0:
            QMessageBox.warning(self, "알림", "삭제할 아이템을 선택하세요.")
            return

        fav_data = self.char_prompt_manage_item_combo.itemData(index)
        if not fav_data:
            return

        name = fav_data.get("name", "")
        reply = QMessageBox.question(
            self, "삭제 확인",
            f"'{name}' 아이템을 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # 썸네일 파일 삭제
        thumb_filename = fav_data.get("thumbnail", "")
        if thumb_filename:
            thumb_path = CHAR_PROMPT_FAVORITES_DIR / thumb_filename
            if thumb_path.exists():
                try:
                    thumb_path.unlink()
                except Exception as e:
                    print(f"썸네일 삭제 실패: {e}")

        # 리스트에서 제거
        self.char_prompt_favorites = [
            fav for fav in self.char_prompt_favorites
            if not (fav.get("name") == name and fav.get("folder") == fav_data.get("folder"))
        ]

        self._save_char_prompt_favorites()
        self._update_char_prompt_favorites_grid()
        self._refresh_manage_folder_combo()

        QMessageBox.information(self, "완료", "아이템이 삭제되었습니다.")

    def _on_manage_search_clicked(self):
        """캐릭터 검색 버튼 클릭 → CharacterSearchDialog 사용"""
        # CharacterSearchDialog에 프롬프트/UC TextEdit 전달
        dialog = CharacterSearchDialog(
            parent_prompt_textbox=self.char_prompt_manage_prompt_edit,
            parent_uc_textbox=self.char_prompt_manage_uc_edit,
            parent=self
        )
        dialog.exec()

    def _on_manage_add_folder(self):
        """관리 탭에서 폴더 추가"""
        folder_name, ok = QInputDialog.getText(
            self, "폴더 추가", "새 폴더 이름을 입력하세요:"
        )
        if not ok or not folder_name.strip():
            return

        folder_name = folder_name.strip()
        if folder_name in self.char_prompt_folders:
            QMessageBox.warning(self, "오류", "이미 존재하는 폴더 이름입니다.")
            return

        self.char_prompt_folders.append(folder_name)
        self._save_char_prompt_folders()
        self._refresh_manage_folder_combo()
        self._refresh_char_prompt_folder_combo()

        # 새로 추가된 폴더 선택
        idx = self.char_prompt_manage_folder_combo.findText(folder_name)
        if idx >= 0:
            self.char_prompt_manage_folder_combo.setCurrentIndex(idx)

    def _on_manage_gen_thumb_clicked(self):
        """썸네일 생성 버튼 클릭 → 이미지 생성하여 썸네일 생성"""
        import pandas as pd
        from PIL import Image
        from PIL.ImageQt import ImageQt

        if not self.character_module or not self.parent_app:
            QMessageBox.warning(self, "오류", "캐릭터 모듈 또는 메인 앱을 찾을 수 없습니다.")
            return

        # app_context 확인
        if not hasattr(self.parent_app, 'app_context') or not self.parent_app.app_context:
            QMessageBox.warning(self, "오류", "앱 컨텍스트를 찾을 수 없습니다.")
            return

        app_context = self.parent_app.app_context

        # 현재 입력된 프롬프트 확인
        new_prompt = self.char_prompt_manage_prompt_edit.toPlainText().strip()
        new_uc = self.char_prompt_manage_uc_edit.toPlainText().strip()

        if not new_prompt:
            QMessageBox.warning(self, "알림", "캐릭터 프롬프트를 입력해주세요.")
            return

        # === 1. 현재 상태 백업 ===
        # 인원 수 백업
        original_person_count = self.char_prompt_person_count

        # C1 프롬프트/UC 백업 (prompt_textbox, uc_textbox 사용)
        original_c1_prompt = ""
        original_c1_uc = ""
        if self.character_module and hasattr(self.character_module, 'character_widgets'):
            widgets = self.character_module.character_widgets
            if widgets and len(widgets) > 0:
                c1_widget = widgets[0]
                if hasattr(c1_widget, 'prompt_textbox'):
                    original_c1_prompt = c1_widget.prompt_textbox.toPlainText()
                if hasattr(c1_widget, 'uc_textbox'):
                    original_c1_uc = c1_widget.uc_textbox.toPlainText()

        # === 2. 임시 설정 적용 ===
        # 인원 수를 1로 설정
        if hasattr(self, 'char_prompt_person_radios') and self.char_prompt_person_radios:
            self.char_prompt_person_radios[0].setChecked(True)
            self._on_char_prompt_person_changed(1)

        # C1에 새 프롬프트/UC 적용 (prompt_textbox, uc_textbox 사용)
        if self.character_module and hasattr(self.character_module, 'character_widgets'):
            widgets = self.character_module.character_widgets
            if widgets and len(widgets) > 0:
                c1_widget = widgets[0]
                if hasattr(c1_widget, 'prompt_textbox'):
                    c1_widget.prompt_textbox.setPlainText(new_prompt)
                if hasattr(c1_widget, 'uc_textbox'):
                    c1_widget.uc_textbox.setPlainText(new_uc)

        # === 3. 생성 완료 콜백 정의 ===
        def on_thumb_generation_finished(result):
            """생성 완료 시 썸네일 표시 및 원래 상태 복원"""
            # 구독 즉시 해제 (일회성)
            try:
                if "generation_completed_for_redirect" in app_context.subscribers:
                    app_context.subscribers["generation_completed_for_redirect"].remove(on_thumb_generation_finished)
            except ValueError:
                pass

            # 생성된 이미지를 썸네일로 표시
            if isinstance(result, Image.Image):
                # PIL Image → QImage → QPixmap
                q_image = ImageQt(result)
                pixmap = QPixmap.fromImage(q_image)
                scaled = pixmap.scaled(
                    CHAR_PROMPT_MANAGE_THUMB_WIDTH, CHAR_PROMPT_MANAGE_THUMB_HEIGHT,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.char_prompt_manage_thumb.setPixmap(scaled)

                # 원본 이미지 저장 (등록 시 사용)
                self._pending_thumb_image = q_image

            # === 4. 원래 상태 복원 ===
            # C1 프롬프트/UC 복원
            if self.character_module and hasattr(self.character_module, 'character_widgets'):
                widgets = self.character_module.character_widgets
                if widgets and len(widgets) > 0:
                    c1_widget = widgets[0]
                    if hasattr(c1_widget, 'prompt_textbox'):
                        c1_widget.prompt_textbox.setPlainText(original_c1_prompt)
                    if hasattr(c1_widget, 'uc_textbox'):
                        c1_widget.uc_textbox.setPlainText(original_c1_uc)

            # 인원 수 복원
            if original_person_count != 1:
                if hasattr(self, 'char_prompt_person_radios') and len(self.char_prompt_person_radios) >= original_person_count:
                    self.char_prompt_person_radios[original_person_count - 1].setChecked(True)
                    self._on_char_prompt_person_changed(original_person_count)

        # 생성 완료 이벤트 구독
        app_context.subscribe("generation_completed_for_redirect", on_thumb_generation_finished)

        # === 가상 row 생성 및 생성 요청 ===
        virtual_row = pd.Series({
            'general': 'upper body',
            'character': '',
            'meta': '',
            'copyright': '',
            'artist': '',
            'rating': 'g',
            'id': 0,
            'created_at': '',
            'uploader_id': 0,
            'score': 0,
            'source': 'CharPrompt Thumbnail',
            'md5': '',
            'file_ext': '',
            'file_size': 0,
            'image_width': 0,
            'image_height': 0,
            'parent_id': None,
            'has_children': False,
            'is_deleted': False,
            'is_banned': False,
            'pixiv_id': None,
            'has_active_children': False,
            'bit_flags': 0,
            'has_large': False,
            'has_visible_children': False,
            'is_favorited': False,
            'tag_string': 'upper body',
            'pool_string': '',
            'up_score': 0,
            'down_score': 0,
            'is_pending': False,
            'is_flagged': False,
            'is_note_locked': False,
            'is_rating_locked': False,
            'is_status_locked': False,
        })

        # 생성 요청
        if hasattr(self.parent_app, 'on_generate_with_image_requested'):
            self.parent_app.on_generate_with_image_requested(virtual_row)

    def _on_manage_paste_thumb_clicked(self):
        """썸네일 붙여넣기 → 클립보드에서 이미지 가져오기"""
        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData()

        if mime_data.hasImage():
            image = clipboard.image()
            if not image.isNull():
                # QImage를 썸네일로 표시
                scaled = image.scaled(
                    CHAR_PROMPT_MANAGE_THUMB_WIDTH, CHAR_PROMPT_MANAGE_THUMB_HEIGHT,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                pixmap = QPixmap.fromImage(scaled)
                self.char_prompt_manage_thumb.setPixmap(pixmap)

                # 임시 썸네일 경로 저장 (등록 시 사용)
                self._pending_thumb_image = image
                return

        QMessageBox.warning(self, "알림", "클립보드에 이미지가 없습니다.")

    def _set_manage_thumbnail_from_path(self, file_path: str):
        """파일 경로에서 썸네일 설정"""
        try:
            pixmap = QPixmap(file_path)
            if pixmap.isNull():
                QMessageBox.warning(self, "오류", "이미지를 로드할 수 없습니다.")
                return

            scaled = pixmap.scaled(
                CHAR_PROMPT_MANAGE_THUMB_WIDTH, CHAR_PROMPT_MANAGE_THUMB_HEIGHT,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.char_prompt_manage_thumb.setPixmap(scaled)

            # 원본 이미지 저장 (등록 시 사용)
            image = QImage(file_path)
            self._pending_thumb_image = image

        except Exception as e:
            QMessageBox.warning(self, "오류", f"이미지 로드 실패: {e}")

    def _on_manage_register_clicked(self):
        """신규 즐겨찾기 등록"""
        # 이름 입력
        name, ok = QInputDialog.getText(
            self, "신규 등록", "아이템 이름을 입력하세요:"
        )
        if not ok or not name.strip():
            return

        name = name.strip()

        # 현재 폴더
        folder = self.char_prompt_manage_folder_combo.currentText()
        if not folder:
            folder = "기본"

        # 중복 확인
        for fav in self.char_prompt_favorites:
            if fav.get("name") == name and fav.get("folder") == folder:
                QMessageBox.warning(self, "오류", "같은 이름의 아이템이 이미 있습니다.")
                return

        # 프롬프트 데이터
        prompt = self.char_prompt_manage_prompt_edit.toPlainText().strip()
        uc = self.char_prompt_manage_uc_edit.toPlainText().strip()

        # 썸네일 저장
        thumb_filename = ""
        if hasattr(self, '_pending_thumb_image') and self._pending_thumb_image:
            CHAR_PROMPT_FAVORITES_DIR.mkdir(parents=True, exist_ok=True)
            thumb_filename = f"thumb_{name.replace(' ', '_')}_{len(self.char_prompt_favorites)}.png"
            thumb_path = CHAR_PROMPT_FAVORITES_DIR / thumb_filename

            # QImage를 파일로 저장
            self._pending_thumb_image.save(str(thumb_path), "PNG")
            self._pending_thumb_image = None

        # 즐겨찾기 추가
        new_fav = {
            "name": name,
            "folder": folder,
            "prompt": prompt,
            "uc": uc,
            "thumbnail": thumb_filename
        }
        self.char_prompt_favorites.append(new_fav)

        self._save_char_prompt_favorites()
        self._update_char_prompt_favorites_grid()
        self._refresh_manage_folder_combo()

        QMessageBox.information(self, "완료", f"'{name}' 아이템이 등록되었습니다.")

    def _create_char_ref_subtab(self, parent_tabs: QTabWidget):
        """캐릭터 레퍼런스 서브탭 - Storage 즐겨찾기 시스템"""
        ref_widget = QWidget()
        ref_layout = QVBoxLayout(ref_widget)
        ref_layout.setContentsMargins(8, 8, 8, 8)
        ref_layout.setSpacing(8)

        if not self.character_ref_module:
            placeholder = QLabel("레퍼런스 모듈을 찾을 수 없습니다.")
            placeholder.setStyleSheet(f"color: {DARK_COLORS['text_disabled']};")
            ref_layout.addWidget(placeholder)
            parent_tabs.addTab(ref_widget, "📸 레퍼런스")
            return

        # === 상단 섹션: 현재 레퍼런스 제어 ===
        top_section = QFrame()
        top_section.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 8px;
            }}
        """)
        top_layout = QHBoxLayout(top_section)
        top_layout.setContentsMargins(10, 10, 10, 10)
        top_layout.setSpacing(12)

        # 왼쪽: 썸네일 영역
        self.char_ref_current_thumb = QLabel()
        self.char_ref_current_thumb.setFixedSize(PREVIEW_THUMB_WIDTH, PREVIEW_THUMB_HEIGHT)
        self.char_ref_current_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.char_ref_current_thumb.setStyleSheet(f"""
            QLabel {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 2px dashed {DARK_COLORS['border']};
                border-radius: 6px;
                color: {DARK_COLORS['text_disabled']};
                font-size: {get_scaled_font_size(14)}px;
            }}
        """)
        self.char_ref_current_thumb.setText("썸네일\n없음")
        top_layout.addWidget(self.char_ref_current_thumb)

        # 오른쪽: 컨트롤 영역 (세로 배치)
        right_section = QVBoxLayout()
        right_section.setSpacing(6)

        # 1) "캐릭터 레퍼런스" 라벨
        ref_label = QLabel("캐릭터 레퍼런스")
        ref_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-weight: bold;
                font-size: {get_scaled_font_size(15)}px;
            }}
        """)
        right_section.addWidget(ref_label)

        # 2) [Storage 아이템 콤보박스][관리] 가로 배치
        combo_row = QHBoxLayout()
        combo_row.setSpacing(6)

        self.char_ref_storage_combo = QComboBox()
        self.char_ref_storage_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
        self.char_ref_storage_combo.setMinimumWidth(150)
        self._sync_char_ref_storage_combo()
        self.char_ref_storage_combo.currentTextChanged.connect(self._on_char_ref_storage_changed)
        combo_row.addWidget(self.char_ref_storage_combo, 1)

        self.char_ref_manage_btn = QPushButton("📂 관리")
        self.char_ref_manage_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.char_ref_manage_btn.setFixedWidth(100)
        self.char_ref_manage_btn.clicked.connect(self._open_char_ref_storage_folder)
        combo_row.addWidget(self.char_ref_manage_btn)

        right_section.addLayout(combo_row)

        # 3) Upload Image / From Clipboard 버튼 (가로 배치)
        upload_row = QHBoxLayout()
        upload_row.setSpacing(6)

        self.char_ref_upload_btn = QPushButton("📁 직접 업로드")
        self.char_ref_upload_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.char_ref_upload_btn.clicked.connect(self._on_char_ref_upload_image)
        upload_row.addWidget(self.char_ref_upload_btn)

        self.char_ref_clipboard_btn = QPushButton("📋클립보드 붙이기")
        self.char_ref_clipboard_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(6)}px {get_scaled_size(12)}px;
                font-size: {get_scaled_font_size(16)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_secondary']};
                border-color: {DARK_COLORS['accent_blue']};
            }}
        """)
        self.char_ref_clipboard_btn.clicked.connect(self._on_char_ref_clipboard_image)
        upload_row.addWidget(self.char_ref_clipboard_btn)

        self.char_ref_edit_meta_btn = QPushButton("📝메타데이터")
        self.char_ref_edit_meta_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.char_ref_edit_meta_btn.clicked.connect(self._on_char_ref_edit_metadata)
        upload_row.addWidget(self.char_ref_edit_meta_btn)

        right_section.addLayout(upload_row)

        # 4) Style Aware 체크박스 + Fidelity 슬라이더 (한 줄, 상하 마진 추가)
        style_fidelity_container = QWidget()
        style_fidelity_container.setContentsMargins(0, 6, 0, 6)
        style_fidelity_row = QHBoxLayout(style_fidelity_container)
        style_fidelity_row.setContentsMargins(0, 0, 0, 0)
        style_fidelity_row.setSpacing(8)

        self.char_ref_style_aware_check = QCheckBox("Style Aware")
        self.char_ref_style_aware_check.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.char_ref_style_aware_check.setChecked(True)
        self.char_ref_style_aware_check.toggled.connect(self._on_char_ref_style_aware_changed)
        style_fidelity_row.addWidget(self.char_ref_style_aware_check)

        fidelity_label = QLabel("Fidelity:")
        fidelity_label.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(15)}px;")
        style_fidelity_row.addWidget(fidelity_label)

        self.char_ref_fidelity_slider = QSlider(Qt.Orientation.Horizontal)
        self.char_ref_fidelity_slider.setMinimum(0)
        self.char_ref_fidelity_slider.setMaximum(20)
        self.char_ref_fidelity_slider.setValue(20)  # 1.0
        self.char_ref_fidelity_slider.setFixedWidth(160)
        self.char_ref_fidelity_slider.setFixedHeight(20)
        self.char_ref_fidelity_slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                border: 1px solid {DARK_COLORS['border']};
                height: 8px;
                background: {DARK_COLORS['bg_primary']};
                border-radius: 4px;
            }}
            QSlider::handle:horizontal {{
                background: {DARK_COLORS['accent_blue']};
                border: 1px solid {DARK_COLORS['accent_blue']};
                width: 16px;
                height: 16px;
                margin: -5px 0;
                border-radius: 8px;
            }}
            QSlider::handle:horizontal:hover {{
                background: {DARK_COLORS['accent_blue_hover']};
            }}
            QSlider::sub-page:horizontal {{
                background: {DARK_COLORS['accent_blue']};
                border-radius: 4px;
            }}
        """)
        self.char_ref_fidelity_slider.valueChanged.connect(self._on_char_ref_fidelity_changed)
        style_fidelity_row.addWidget(self.char_ref_fidelity_slider)

        self.char_ref_fidelity_value = QLabel("1.00")
        self.char_ref_fidelity_value.setStyleSheet(f"""
            color: {DARK_COLORS['text_primary']};
            font-size: {get_scaled_font_size(15)}px;
            font-weight: bold;
            min-width: 40px;
        """)
        style_fidelity_row.addWidget(self.char_ref_fidelity_value)

        style_fidelity_row.addStretch()
        right_section.addWidget(style_fidelity_container)

        # 5) 즐겨찾기에 등록 버튼
        self.char_ref_favorite_btn = QPushButton("⭐ 즐겨찾기에 등록")
        self.char_ref_favorite_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.char_ref_favorite_btn.clicked.connect(self._on_char_ref_toggle_favorite)
        right_section.addWidget(self.char_ref_favorite_btn)

        right_section.addStretch()
        top_layout.addLayout(right_section, 1)
        ref_layout.addWidget(top_section)

        # === 중간 섹션: C1 자동 할당 체크박스 + 폴더 선택 ===
        middle_section = QFrame()
        middle_section.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 6px;
            }}
        """)
        middle_layout = QVBoxLayout(middle_section)
        middle_layout.setContentsMargins(10, 8, 10, 8)
        middle_layout.setSpacing(6)

        # C1 자동 할당 체크박스
        self.char_ref_auto_c1_check = QCheckBox("C1 캐릭터 프롬프트에 메타데이터 자동 할당")
        self.char_ref_auto_c1_check.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.char_ref_auto_c1_check.setChecked(self.char_ref_auto_assign_c1)
        self.char_ref_auto_c1_check.toggled.connect(self._on_char_ref_auto_c1_changed)
        middle_layout.addWidget(self.char_ref_auto_c1_check)

        # 폴더 선택 행
        folder_row = QHBoxLayout()
        folder_row.setSpacing(6)

        folder_label = QLabel("즐겨찾기 폴더:")
        folder_label.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(12)}px;")
        folder_row.addWidget(folder_label)

        self.char_ref_folder_combo = QComboBox()
        self.char_ref_folder_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
        self.char_ref_folder_combo.setMinimumWidth(100)
        for folder in self.char_ref_folders:
            self.char_ref_folder_combo.addItem(folder)
        self.char_ref_folder_combo.setCurrentText(self.char_ref_current_folder)
        self.char_ref_folder_combo.currentTextChanged.connect(self._on_char_ref_folder_changed)
        folder_row.addWidget(self.char_ref_folder_combo, 1)

        self.char_ref_add_folder_btn = QPushButton("➕ 추가")
        self.char_ref_add_folder_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.char_ref_add_folder_btn.setFixedWidth(100)
        self.char_ref_add_folder_btn.clicked.connect(self._on_char_ref_add_folder)
        folder_row.addWidget(self.char_ref_add_folder_btn)

        self.char_ref_manage_folder_btn = QPushButton("📂 관리")
        self.char_ref_manage_folder_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        self.char_ref_manage_folder_btn.setFixedWidth(100)
        self.char_ref_manage_folder_btn.clicked.connect(self._on_char_ref_manage_folders)
        folder_row.addWidget(self.char_ref_manage_folder_btn)

        middle_layout.addLayout(folder_row)
        ref_layout.addWidget(middle_section)

        # === 하단 섹션: 즐겨찾기 그리드 ===
        bottom_section = QFrame()
        bottom_section.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 8px;
            }}
        """)
        bottom_layout = QVBoxLayout(bottom_section)
        bottom_layout.setContentsMargins(8, 8, 8, 8)

        # 스크롤 영역
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet(f"""
            QScrollArea {{
                background-color: transparent;
                border: none;
            }}
            QScrollArea > QWidget > QWidget {{
                background-color: transparent;
            }}
        """)

        # 그리드 컨테이너
        self.char_ref_favorites_grid_widget = QWidget()
        self.char_ref_favorites_grid_layout = QGridLayout(self.char_ref_favorites_grid_widget)
        self.char_ref_favorites_grid_layout.setSpacing(10)
        self.char_ref_favorites_grid_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area.setWidget(self.char_ref_favorites_grid_widget)
        bottom_layout.addWidget(scroll_area, 1)

        ref_layout.addWidget(bottom_section, 1)

        parent_tabs.addTab(ref_widget, "📸 레퍼런스")

        # 초기 UI 업데이트
        self._update_char_ref_current_ui()
        self._update_char_ref_favorites_grid()

    # === 캐릭터 레퍼런스 헬퍼 메서드들 ===

    def _sync_char_ref_storage_combo(self):
        """Storage 아이템 콤보박스 동기화"""
        self.char_ref_storage_combo.blockSignals(True)
        self.char_ref_storage_combo.clear()

        # Storage 이미지 목록 가져오기
        images_folder = Path("save/character_reference/images")
        if images_folder.exists():
            image_files = []
            for ext in ['*.png', '*.jpg', '*.jpeg', '*.webp']:
                image_files.extend(images_folder.glob(ext))

            # 수정 시간 기준 내림차순 정렬
            for img_file in sorted(image_files, key=lambda x: x.stat().st_mtime, reverse=True):
                file_hash = img_file.stem
                # 메타데이터에서 이름 가져오기
                name = self._get_char_ref_name_from_metadata(file_hash)
                display_name = name if name else file_hash[:12]
                self.char_ref_storage_combo.addItem(display_name, file_hash)

        # 현재 활성화된 레퍼런스 선택
        if self.character_ref_module and hasattr(self.character_ref_module, 'character_frames'):
            for frame in self.character_ref_module.character_frames:
                if hasattr(frame, 'is_enabled') and frame.is_enabled:
                    file_hash = getattr(frame, 'file_hash', '')
                    for i in range(self.char_ref_storage_combo.count()):
                        if self.char_ref_storage_combo.itemData(i) == file_hash:
                            self.char_ref_storage_combo.setCurrentIndex(i)
                            break
                    break

        self.char_ref_storage_combo.blockSignals(False)

    def _get_char_ref_name_from_metadata(self, file_hash: str) -> str:
        """메타데이터에서 캐릭터 이름 가져오기"""
        metadata_path = Path(f"save/character_reference/metadata/{file_hash}.json")
        if metadata_path.exists():
            try:
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get("character_name", "")
            except:
                pass
        return ""

    def _get_char_ref_metadata(self, file_hash: str) -> dict:
        """메타데이터 전체 가져오기"""
        metadata_path = Path(f"save/character_reference/metadata/{file_hash}.json")
        if metadata_path.exists():
            try:
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {}

    def _update_char_ref_current_ui(self):
        """현재 선택된 레퍼런스 UI 업데이트 - 콤보박스 선택 기준"""
        # 콤보박스에서 현재 선택된 아이템의 file_hash 가져오기
        idx = self.char_ref_storage_combo.currentIndex()
        if idx >= 0:
            file_hash = self.char_ref_storage_combo.itemData(idx)
        else:
            file_hash = None

        # 모듈에 활성 프레임이 있고 해시가 콤보박스와 일치하는지 확인
        active_frame = None
        style_aware = self.char_ref_style_aware_check.isChecked()  # 현재 UI 값 유지
        fidelity = self.char_ref_fidelity_slider.value() / 20.0

        if self.character_ref_module and hasattr(self.character_ref_module, 'character_frames'):
            for frame in self.character_ref_module.character_frames:
                if hasattr(frame, 'is_enabled') and frame.is_enabled:
                    frame_hash = getattr(frame, 'file_hash', '')
                    if frame_hash == file_hash:
                        active_frame = frame
                        # 활성 프레임의 값으로 동기화
                        style_aware = getattr(frame, 'style_aware', True)
                        fidelity = getattr(frame, 'fidelity', 1.0)
                    break

        if file_hash:
            # 썸네일 업데이트
            image_path = Path(f"save/character_reference/images/{file_hash}.png")
            if not image_path.exists():
                # 다른 확장자 시도
                for ext in ['.jpg', '.jpeg', '.webp']:
                    alt_path = image_path.with_suffix(ext)
                    if alt_path.exists():
                        image_path = alt_path
                        break

            if image_path.exists():
                pixmap = QPixmap(str(image_path))
                scaled = pixmap.scaled(
                    PREVIEW_THUMB_WIDTH, PREVIEW_THUMB_HEIGHT,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.char_ref_current_thumb.setPixmap(scaled)
                border_color = DARK_COLORS['accent_blue'] if active_frame else DARK_COLORS['border']
                self.char_ref_current_thumb.setStyleSheet(f"""
                    QLabel {{
                        background-color: {DARK_COLORS['bg_primary']};
                        border: 2px solid {border_color};
                        border-radius: 6px;
                    }}
                """)
            else:
                self.char_ref_current_thumb.setText("썸네일\n없음")
                self.char_ref_current_thumb.setStyleSheet(f"""
                    QLabel {{
                        background-color: {DARK_COLORS['bg_primary']};
                        border: 2px dashed {DARK_COLORS['border']};
                        border-radius: 6px;
                        color: {DARK_COLORS['text_disabled']};
                        font-size: {get_scaled_font_size(12)}px;
                    }}
                """)

            # Style Aware, Fidelity 동기화
            self.char_ref_style_aware_check.blockSignals(True)
            self.char_ref_style_aware_check.setChecked(style_aware)
            self.char_ref_style_aware_check.blockSignals(False)

            self.char_ref_fidelity_slider.blockSignals(True)
            self.char_ref_fidelity_slider.setValue(int(fidelity * 20))
            self.char_ref_fidelity_value.setText(f"{fidelity:.2f}")
            self.char_ref_fidelity_slider.blockSignals(False)

            # 즐겨찾기 버튼 상태 업데이트
            is_favorite = any(
                f.get("file_hash") == file_hash and f.get("folder") == self.char_ref_current_folder
                for f in self.char_ref_favorites
            )
            if is_favorite:
                self.char_ref_favorite_btn.setText("💔 즐겨찾기에서 제거")
                self.char_ref_favorite_btn.setStyleSheet(DARK_STYLES['secondary_button'])
            else:
                self.char_ref_favorite_btn.setText("⭐ 즐겨찾기에 등록")
                self.char_ref_favorite_btn.setStyleSheet(DARK_STYLES['primary_button'])
        else:
            self.char_ref_current_thumb.setText("선택된\n레퍼런스\n없음")
            self.char_ref_current_thumb.setStyleSheet(f"""
                QLabel {{
                    background-color: {DARK_COLORS['bg_primary']};
                    border: 2px dashed {DARK_COLORS['border']};
                    border-radius: 6px;
                    color: {DARK_COLORS['text_disabled']};
                    font-size: {get_scaled_font_size(12)}px;
                }}
            """)

    def _calculate_char_ref_thumbnail_size(self) -> tuple:
        """현재 UI 크기를 기반으로 썸네일 크기 계산 (3열 기준)"""
        available_width = self.char_ref_favorites_grid_widget.width()
        if available_width < 100:
            available_width = 450

        cols = 3
        spacing = 10
        item_padding = 10
        item_width = (available_width - (cols - 1) * spacing) // cols - item_padding
        item_width = max(80, min(180, item_width))
        item_height = int(item_width / THUMB_ASPECT_RATIO)

        return item_width, item_height

    def _update_char_ref_favorites_grid(self):
        """캐릭터 레퍼런스 즐겨찾기 그리드 업데이트"""
        # 기존 위젯 제거
        while self.char_ref_favorites_grid_layout.count():
            item = self.char_ref_favorites_grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 현재 폴더의 즐겨찾기만 필터링
        folder_favorites = [
            f for f in self.char_ref_favorites
            if f.get("folder", "기본") == self.char_ref_current_folder
        ]

        if not folder_favorites:
            empty_label = QLabel("즐겨찾기가 없습니다.\n캐릭터 레퍼런스를 추가하고\n⭐ 버튼을 눌러 등록하세요.")
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_label.setStyleSheet(f"""
                QLabel {{
                    color: {DARK_COLORS['text_disabled']};
                    font-size: {get_scaled_font_size(12)}px;
                    padding: 40px;
                }}
            """)
            self.char_ref_favorites_grid_layout.addWidget(empty_label, 0, 0, 1, 3)
            return

        # 동적 썸네일 크기 계산
        thumb_width, thumb_height = self._calculate_char_ref_thumbnail_size()

        # 현재 선택된 file_hash 가져오기 (콤보박스 기준)
        current_idx = self.char_ref_storage_combo.currentIndex()
        current_file_hash = self.char_ref_storage_combo.itemData(current_idx) if current_idx >= 0 else None

        # 그리드에 아이템 추가 (3열, 좌측 정렬)
        cols = 3
        for idx, fav in enumerate(folder_favorites):
            file_hash = fav.get("file_hash", "")
            thumb_path = Path(f"save/character_reference/images/{file_hash}.png")
            if not thumb_path.exists():
                for ext in ['.jpg', '.jpeg', '.webp']:
                    alt_path = thumb_path.with_suffix(ext)
                    if alt_path.exists():
                        thumb_path = alt_path
                        break

            # 현재 선택된 아이템인지 확인
            is_selected = (file_hash == current_file_hash)

            item_widget = CharRefFavoriteItemWidget(
                fav, thumb_path,
                thumb_width=thumb_width,
                thumb_height=thumb_height,
                is_selected=is_selected
            )
            item_widget.clicked.connect(self._on_char_ref_favorite_clicked)

            row = idx // cols
            col = idx % cols
            self.char_ref_favorites_grid_layout.addWidget(
                item_widget, row, col,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
            )

    def _on_char_ref_storage_changed(self, text: str):
        """Storage 콤보박스 변경 시 - UI 업데이트만 수행 (모듈에 프레임 추가하지 않음)"""
        # 썸네일 및 UI 업데이트만 수행
        self._update_char_ref_current_ui()

    def _clear_char_ref_frames(self):
        """캐릭터 레퍼런스 모듈의 모든 프레임 제거"""
        if not self.character_ref_module:
            return

        if hasattr(self.character_ref_module, 'character_frames'):
            # 프레임 리스트 복사 후 순회 (순회 중 삭제 방지)
            frames_to_remove = list(self.character_ref_module.character_frames)
            for frame in frames_to_remove:
                if hasattr(self.character_ref_module, '_remove_frame'):
                    self.character_ref_module._remove_frame(frame)

    def _apply_char_ref_from_storage(self, file_hash: str, style_aware: bool = None, fidelity: float = None,
                                      clear_existing: bool = True, auto_assign_c1: bool = False):
        """Storage에서 캐릭터 레퍼런스 적용

        Args:
            file_hash: 이미지 해시
            style_aware: Style Aware 설정 (None이면 기본값 True)
            fidelity: Fidelity 값 (None이면 기본값 1.0)
            clear_existing: 기존 프레임들 삭제 여부
            auto_assign_c1: C1 캐릭터 프롬프트에 메타데이터 자동 할당 여부
        """
        if not self.character_ref_module:
            return

        # 이미지 경로 찾기
        image_path = None
        for ext in ['.png', '.jpg', '.jpeg', '.webp']:
            path = Path(f"save/character_reference/images/{file_hash}{ext}")
            if path.exists():
                image_path = path
                break

        if not image_path:
            self._show_warning("오류", f"이미지를 찾을 수 없습니다: {file_hash}")
            return

        # 기존 프레임들 제거
        if clear_existing:
            self._clear_char_ref_frames()

        # 새 프레임 추가 및 활성화
        if hasattr(self.character_ref_module, '_add_character_frame'):
            frame = self.character_ref_module._add_character_frame(str(image_path))
            if frame:
                frame.enable_check.setChecked(True)

                # Style Aware 설정 (기본값 True)
                if hasattr(frame, 'style_aware_check'):
                    frame.style_aware_check.setChecked(style_aware if style_aware is not None else True)

                # Fidelity 설정 (기본값 1.0)
                if hasattr(frame, 'fidelity_slider'):
                    fidelity_value = fidelity if fidelity is not None else 1.0
                    frame.fidelity_slider.setValue(int(fidelity_value * 20))

        # C1 자동 할당
        if auto_assign_c1:
            self._assign_c1_from_metadata(file_hash)

        # UI 업데이트
        QTimer.singleShot(100, self._update_char_ref_current_ui)

    def _assign_c1_from_metadata(self, file_hash: str):
        """메타데이터에서 C1 캐릭터 프롬프트 할당"""
        metadata_path = Path(f"save/character_reference/metadata/{file_hash}.json")
        if not metadata_path.exists():
            return

        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)

            character_prompt = metadata.get("character_prompt", "").strip()
            character_uc = metadata.get("character_uc", "").strip()

            if not character_prompt:
                return

            # CharacterModule에서 C1 할당
            if self.character_module and hasattr(self.character_module, 'assign_c1'):
                self.character_module.assign_c1(character_prompt, character_uc)
                print(f"✅ C1 자동 할당 완료: {metadata.get('character_name', file_hash[:8])}")

            # RemoteWindow의 인원 수를 1명으로 설정
            if hasattr(self, 'char_prompt_person_radios') and self.char_prompt_person_radios:
                self.char_prompt_person_radios[0].setChecked(True)  # 1명 라디오 선택
                self.char_prompt_person_count = 1
                self._on_char_prompt_person_changed(1)  # UI 업데이트

            # RemoteWindow의 슬롯 프레임 UI도 업데이트 (C1 = index 0)
            if hasattr(self, 'char_prompt_slot_edits') and len(self.char_prompt_slot_edits) > 0:
                self.char_prompt_slot_edits[0].setText(character_prompt)

        except Exception as e:
            print(f"⚠️ C1 자동 할당 실패: {e}")

    def _on_char_ref_upload_image(self):
        """이미지 업로드 및 임시 프리셋 생성"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "이미지 선택",
            "",
            "Image Files (*.png *.jpg *.jpeg *.webp *.bmp *.gif)"
        )

        if file_path and self.character_ref_module:
            # 기존 프레임 모두 제거
            self._clear_char_ref_frames()

            if hasattr(self.character_ref_module, '_add_character_frame'):
                frame = self.character_ref_module._add_character_frame(file_path)
                if frame:
                    frame.enable_check.setChecked(True)

                    # Style Aware, Fidelity 설정 (UI 값 적용)
                    if hasattr(frame, 'style_aware_check'):
                        frame.style_aware_check.setChecked(self.char_ref_style_aware_check.isChecked())
                    if hasattr(frame, 'fidelity_slider'):
                        frame.fidelity_slider.setValue(self.char_ref_fidelity_slider.value())

                    # 새 file_hash 가져오기
                    new_file_hash = getattr(frame, 'file_hash', None)

                    # Storage 콤보박스 동기화 후 해당 아이템 선택
                    self._sync_char_ref_storage_combo()

                    if new_file_hash:
                        self._select_char_ref_in_combo_by_hash(new_file_hash)

                    QTimer.singleShot(100, self._update_char_ref_current_ui)
                    print(f"✅ 이미지 업로드: {new_file_hash[:8] if new_file_hash else 'unknown'}")

    def _on_char_ref_clipboard_image(self):
        """클립보드에서 이미지 가져오기 및 임시 프리셋 생성"""
        if not self.character_ref_module:
            return

        # 클립보드 확인
        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData()

        if not mime_data.hasImage():
            self._show_warning("오류", "클립보드에 이미지가 없습니다.\n이미지를 복사한 후 다시 시도하세요.")
            return

        qimage = clipboard.image()
        if qimage.isNull():
            self._show_warning("오류", "클립보드에 유효한 이미지가 없습니다.")
            return

        # 기존 프레임 모두 제거
        self._clear_char_ref_frames()

        # 클립보드 이미지를 임시 파일로 저장
        import time
        temp_folder = Path("save/character_reference/temp")
        temp_folder.mkdir(parents=True, exist_ok=True)
        temp_file = temp_folder / f"clipboard_{int(time.time())}.png"

        # QImage -> PIL Image 변환 및 저장
        qimage = qimage.convertToFormat(QImage.Format.Format_RGB888)
        width = qimage.width()
        height = qimage.height()
        buffer = qimage.bits().asstring(qimage.sizeInBytes())
        pil_image = Image.frombytes("RGB", (width, height), buffer)
        pil_image.save(str(temp_file))

        # 프레임 추가
        if hasattr(self.character_ref_module, '_add_character_frame'):
            frame = self.character_ref_module._add_character_frame(str(temp_file))
            if frame:
                frame.enable_check.setChecked(True)

                # Style Aware, Fidelity 설정 (UI 값 적용)
                if hasattr(frame, 'style_aware_check'):
                    frame.style_aware_check.setChecked(self.char_ref_style_aware_check.isChecked())
                if hasattr(frame, 'fidelity_slider'):
                    frame.fidelity_slider.setValue(self.char_ref_fidelity_slider.value())

                # 새 file_hash 가져오기
                new_file_hash = getattr(frame, 'file_hash', None)

                # Storage 콤보박스 동기화 후 해당 아이템 선택
                self._sync_char_ref_storage_combo()

                if new_file_hash:
                    self._select_char_ref_in_combo_by_hash(new_file_hash)

                QTimer.singleShot(100, self._update_char_ref_current_ui)
                print(f"✅ 클립보드 이미지 추가: {new_file_hash[:8] if new_file_hash else 'unknown'}")

    def _select_latest_char_ref_in_combo(self):
        """가장 최근 추가된 캐릭터 레퍼런스를 콤보박스에서 선택"""
        if self.char_ref_storage_combo.count() > 0:
            # Storage는 최신순 정렬이므로 첫 번째 아이템 선택
            self.char_ref_storage_combo.setCurrentIndex(0)

    def _select_char_ref_in_combo_by_hash(self, file_hash: str):
        """해시값으로 콤보박스에서 해당 아이템 선택"""
        if not file_hash:
            return False

        for i in range(self.char_ref_storage_combo.count()):
            if self.char_ref_storage_combo.itemData(i) == file_hash:
                self.char_ref_storage_combo.blockSignals(True)
                self.char_ref_storage_combo.setCurrentIndex(i)
                self.char_ref_storage_combo.blockSignals(False)
                return True

        return False

    def _on_char_ref_edit_metadata(self):
        """메타데이터 편집 - Storage 콤보박스에서 선택한 아이템 기준"""
        # 콤보박스에서 선택한 아이템의 file_hash 가져오기
        idx = self.char_ref_storage_combo.currentIndex()
        if idx < 0:
            self._show_info("알림", "먼저 캐릭터 레퍼런스를 선택하세요.")
            return

        file_hash = self.char_ref_storage_combo.itemData(idx)
        file_name = self.char_ref_storage_combo.currentText()

        if not file_hash:
            self._show_info("알림", "먼저 캐릭터 레퍼런스를 선택하세요.")
            return

        # 메타데이터 편집 다이얼로그 열기
        self._open_metadata_edit_dialog(file_hash, file_name)

    def _open_metadata_edit_dialog(self, file_hash: str, file_name: str):
        """메타데이터 편집 다이얼로그 열기 (Storage와 동일한 UI)"""
        # 기존 메타데이터 로드
        metadata = self._get_char_ref_metadata(file_hash) or {}

        # 다이얼로그 생성
        dialog = QDialog(self)
        dialog.setWindowTitle(f"📝 메타데이터 편집 - {file_name}")
        dialog.setMinimumSize(500, 400)
        dialog.setStyleSheet(f"""
            QDialog {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
            }}
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(15)}px;
            }}
            QLineEdit {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 6px;
                font-size: {get_scaled_font_size(15)}px;
            }}
            QTextEdit {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 6px;
                font-size: {get_scaled_font_size(16)}px;
            }}
            QLineEdit:focus, QTextEdit:focus {{
                border-color: {DARK_COLORS['accent_blue']};
            }}
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 8px 16px;
                font-size: {get_scaled_font_size(15)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_secondary']};
                border-color: {DARK_COLORS['accent_blue']};
            }}
        """)

        layout = QVBoxLayout(dialog)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # Character Name
        name_label = QLabel("Character Name:")
        layout.addWidget(name_label)

        name_edit = QLineEdit()
        name_edit.setText(metadata.get("character_name", ""))
        name_edit.setPlaceholderText("캐릭터 이름을 입력하세요")
        layout.addWidget(name_edit)

        # Character Prompt
        prompt_label = QLabel("Character Prompt:")
        layout.addWidget(prompt_label)

        prompt_edit = QTextEdit()
        prompt_edit.setPlainText(metadata.get("character_prompt", ""))
        prompt_edit.setPlaceholderText("캐릭터 프롬프트를 입력하세요")
        prompt_edit.setAcceptRichText(False)
        prompt_edit.setMinimumHeight(100)
        layout.addWidget(prompt_edit)

        # Undesired Content (Negative)
        uc_label = QLabel("Undesired Content (Negative):")
        layout.addWidget(uc_label)

        uc_edit = QTextEdit()
        uc_edit.setPlainText(metadata.get("character_uc", ""))
        uc_edit.setPlaceholderText("네거티브 프롬프트를 입력하세요")
        uc_edit.setAcceptRichText(False)
        uc_edit.setMinimumHeight(80)
        layout.addWidget(uc_edit)

        # 버튼 영역
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        save_btn = QPushButton("💾 저장")
        cancel_btn = QPushButton("취소")

        def on_save():
            updated_metadata = {
                "character_name": name_edit.text().strip(),
                "character_prompt": prompt_edit.toPlainText().strip(),
                "character_uc": uc_edit.toPlainText().strip(),
                "file_name": file_name,
                "file_hash": file_hash
            }
            self._save_char_ref_metadata(file_hash, updated_metadata)

            # 콤보박스 텍스트 업데이트 (현재 선택 해시 유지)
            self._sync_char_ref_storage_combo()
            self._select_char_ref_in_combo_by_hash(file_hash)

            # 즐겨찾기 그리드 업데이트
            self._update_char_ref_favorites_grid()

            # 썸네일 영역 UI 업데이트
            self._update_char_ref_current_ui()

            dialog.accept()
            print(f"✅ 메타데이터 저장: {updated_metadata.get('character_name', file_hash[:8])}")

        save_btn.clicked.connect(on_save)
        cancel_btn.clicked.connect(dialog.reject)

        button_layout.addWidget(save_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)

        dialog.exec()

    def _save_char_ref_metadata(self, file_hash: str, metadata: dict):
        """캐릭터 레퍼런스 메타데이터 저장"""
        metadata_dir = Path("save/character_reference/metadata")
        metadata_dir.mkdir(parents=True, exist_ok=True)

        metadata_path = metadata_dir / f"{file_hash}.json"
        try:
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ 메타데이터 저장 실패: {e}")

    def _on_char_ref_style_aware_changed(self, checked: bool):
        """Style Aware 체크박스 변경"""
        if not self.character_ref_module:
            return

        if hasattr(self.character_ref_module, 'character_frames'):
            for frame in self.character_ref_module.character_frames:
                if hasattr(frame, 'is_enabled') and frame.is_enabled:
                    if hasattr(frame, 'style_aware_check'):
                        frame.style_aware_check.setChecked(checked)
                    break

    def _on_char_ref_fidelity_changed(self, value: int):
        """Fidelity 슬라이더 변경"""
        fidelity = value / 20.0
        self.char_ref_fidelity_value.setText(f"{fidelity:.2f}")

        if not self.character_ref_module:
            return

        if hasattr(self.character_ref_module, 'character_frames'):
            for frame in self.character_ref_module.character_frames:
                if hasattr(frame, 'is_enabled') and frame.is_enabled:
                    if hasattr(frame, 'fidelity_slider'):
                        frame.fidelity_slider.setValue(value)
                    break

    def _on_char_ref_toggle_favorite(self):
        """즐겨찾기 등록/제거 토글 - Storage 콤보박스 기준"""
        # Storage 콤보박스에서 선택된 아이템 확인
        idx = self.char_ref_storage_combo.currentIndex()
        if idx < 0:
            self._show_info("알림", "먼저 캐릭터 레퍼런스를 선택하세요.")
            return

        file_hash = self.char_ref_storage_combo.itemData(idx)
        if not file_hash:
            self._show_info("알림", "먼저 캐릭터 레퍼런스를 선택하세요.")
            return

        # UI에서 Style Aware, Fidelity 값 가져오기
        style_aware = self.char_ref_style_aware_check.isChecked()
        fidelity = self.char_ref_fidelity_slider.value() / 20.0

        # 이름 가져오기
        name = self._get_char_ref_name_from_metadata(file_hash)
        if not name:
            name = file_hash[:12]

        # 현재 즐겨찾기 상태 확인
        is_favorite = any(
            f.get("file_hash") == file_hash and f.get("folder") == self.char_ref_current_folder
            for f in self.char_ref_favorites
        )

        if is_favorite:
            # 즐겨찾기 제거
            self.char_ref_favorites = [
                f for f in self.char_ref_favorites
                if not (f.get("file_hash") == file_hash and f.get("folder") == self.char_ref_current_folder)
            ]
            self._save_char_ref_favorites()
            print(f"💔 캐릭터 레퍼런스 즐겨찾기 제거: {name}")
        else:
            # 메타데이터 유무 확인
            metadata = self._get_char_ref_metadata(file_hash)
            has_metadata = bool(metadata and metadata.get("character_prompt", "").strip())

            # 즐겨찾기 등록
            self.char_ref_favorites.append({
                "file_hash": file_hash,
                "name": name,
                "style_aware": style_aware,
                "fidelity": fidelity,
                "folder": self.char_ref_current_folder,
                "has_metadata": has_metadata
            })
            self._save_char_ref_favorites()
            print(f"⭐ 캐릭터 레퍼런스 즐겨찾기 등록: {name}")

        self._update_char_ref_current_ui()
        self._update_char_ref_favorites_grid()

    def _on_char_ref_auto_c1_changed(self, checked: bool):
        """C1 자동 할당 체크박스 변경"""
        self.char_ref_auto_assign_c1 = checked
        self._save_char_ref_folders()

    def _on_char_ref_folder_changed(self, folder: str):
        """즐겨찾기 폴더 변경"""
        self.char_ref_current_folder = folder
        self._save_char_ref_folders()
        self._update_char_ref_favorites_grid()
        self._update_char_ref_current_ui()

    def _on_char_ref_add_folder(self):
        """새 즐겨찾기 폴더 추가"""
        name, ok = self._get_text_input("폴더 추가", "새 폴더 이름:")
        if ok and name:
            name = name.strip()
            if name and name not in self.char_ref_folders:
                self.char_ref_folders.append(name)
                self.char_ref_folder_combo.addItem(name)
                self.char_ref_folder_combo.setCurrentText(name)
                self._save_char_ref_folders()
                print(f"📁 새 폴더 추가: {name}")
            elif name in self.char_ref_folders:
                self._show_warning("알림", f"'{name}' 폴더가 이미 존재합니다.")

    def _on_char_ref_manage_folders(self):
        """즐겨찾기 폴더 관리"""
        # 폴더 목록 표시 및 삭제 기능
        if len(self.char_ref_folders) <= 1:
            self._show_info("알림", "삭제할 수 있는 폴더가 없습니다.\n'기본' 폴더는 삭제할 수 없습니다.")
            return

        folders_to_delete = [f for f in self.char_ref_folders if f != "기본"]
        folder, ok = self._get_item_input("폴더 삭제", "삭제할 폴더 선택:", folders_to_delete)

        if ok and folder:
            if self._show_question(
                "폴더 삭제 확인",
                f"'{folder}' 폴더와 해당 폴더의 즐겨찾기를 삭제하시겠습니까?"
            ):
                # 폴더와 해당 즐겨찾기 삭제
                self.char_ref_folders.remove(folder)
                self.char_ref_favorites = [
                    f for f in self.char_ref_favorites
                    if f.get("folder") != folder
                ]

                # 콤보박스 업데이트
                idx = self.char_ref_folder_combo.findText(folder)
                if idx >= 0:
                    self.char_ref_folder_combo.removeItem(idx)

                # 현재 폴더가 삭제된 폴더면 기본으로 변경
                if self.char_ref_current_folder == folder:
                    self.char_ref_current_folder = "기본"
                    self.char_ref_folder_combo.setCurrentText("기본")

                self._save_char_ref_folders()
                self._save_char_ref_favorites()
                self._update_char_ref_favorites_grid()
                print(f"🗑️ 폴더 삭제: {folder}")

    def _on_char_ref_favorite_clicked(self, favorite_data: dict):
        """즐겨찾기 아이템 클릭 시 캐릭터 레퍼런스 적용 (기존 프레임 clear 후 새로 할당)"""
        file_hash = favorite_data.get("file_hash", "")
        style_aware = favorite_data.get("style_aware", True)
        fidelity = favorite_data.get("fidelity", 1.0)

        if not file_hash:
            return

        # Storage 콤보박스에서 해당 해시 찾아서 선택
        combo_idx = -1
        for i in range(self.char_ref_storage_combo.count()):
            if self.char_ref_storage_combo.itemData(i) == file_hash:
                combo_idx = i
                break

        if combo_idx < 0:
            # Storage에 없는 이미지 (삭제됨)
            self._show_warning("오류", f"원본 이미지를 찾을 수 없습니다.\nStorage에서 삭제되었을 수 있습니다.")
            return

        # 콤보박스 선택 변경 (시그널 일시 차단)
        self.char_ref_storage_combo.blockSignals(True)
        self.char_ref_storage_combo.setCurrentIndex(combo_idx)
        self.char_ref_storage_combo.blockSignals(False)

        # 캐릭터 레퍼런스 적용 (기존 프레임 clear, C1 자동 할당 옵션 적용)
        self._apply_char_ref_from_storage(
            file_hash,
            style_aware=style_aware,
            fidelity=fidelity,
            clear_existing=True,
            auto_assign_c1=self.char_ref_auto_assign_c1
        )

        # Style Aware, Fidelity UI 업데이트
        self.char_ref_style_aware_check.setChecked(style_aware)
        self.char_ref_fidelity_slider.setValue(int(fidelity * 20))

        # 즐겨찾기 그리드 업데이트 (선택 상태 표시)
        self._update_char_ref_favorites_grid()

        print(f"✅ 즐겨찾기 적용: {favorite_data.get('name', file_hash[:8])}")

    def _open_char_ref_storage_folder(self):
        """캐릭터 레퍼런스 Storage 폴더 열기"""
        import subprocess
        import os

        storage_dir = Path("save/character_reference/images")
        if not storage_dir.exists():
            storage_dir.mkdir(parents=True, exist_ok=True)

        if os.name == 'nt':
            subprocess.Popen(['explorer', str(storage_dir.resolve())])
        else:
            subprocess.Popen(['open' if os.uname().sysname == 'Darwin' else 'xdg-open', str(storage_dir.resolve())])

    def _create_event_tab(self):
        """탭3: 이벤트 (이중 탭 - 이벤트, INST.WC)"""
        event_widget = QWidget()
        event_layout = QVBoxLayout(event_widget)
        event_layout.setContentsMargins(4, 4, 4, 4)

        # 이중 탭
        event_sub_tabs = QTabWidget()
        event_sub_tabs.setStyleSheet(DARK_STYLES['dark_tabs'])
        event_layout.addWidget(event_sub_tabs)

        # 서브탭1: 이벤트 저장 목록
        self._create_event_list_subtab(event_sub_tabs)

        # 서브탭2: INST.WC (InstantWildcardModule)
        self._create_instant_wc_subtab(event_sub_tabs)

        self.main_tabs.addTab(event_widget, "🎉 이벤트")

    def _create_event_list_subtab(self, parent_tabs: QTabWidget):
        """이벤트 저장 목록 서브탭 - 개선된 UI"""
        evt_widget = QWidget()
        evt_layout = QVBoxLayout(evt_widget)
        evt_layout.setContentsMargins(8, 8, 8, 8)
        evt_layout.setSpacing(6)

        # === 상단 Row 1: 제목 및 개수 ===
        title_row = QHBoxLayout()
        title_row.setSpacing(8)

        evt_info = QLabel("📌 저장된 이벤트")
        evt_info.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['accent_blue']};
                font-size: {get_scaled_font_size(14)}px;
                font-weight: bold;
            }}
        """)
        title_row.addWidget(evt_info)
        title_row.addStretch()

        evt_layout.addLayout(title_row)

        # === 상단 Row 2: Rating 필터 버튼 ===
        rating_row = QHBoxLayout()
        rating_row.setSpacing(6)

        rating_label = QLabel("등급:")
        rating_label.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(12)}px;")
        rating_row.addWidget(rating_label)

        # Rating 체크박스 버튼들
        self.event_rating_checks = {}
        rating_btn_style = f"""
            QCheckBox {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(14)}px;
                spacing: 4px;
            }}
            QCheckBox::indicator {{
                width: 14px;
                height: 14px;
            }}
        """
        for rating in ["g", "s", "q", "e"]:
            cb = QCheckBox(f"rating:{rating}")
            cb.setChecked(True)
            cb.setStyleSheet(rating_btn_style)
            cb.stateChanged.connect(self._on_event_filter_changed)
            self.event_rating_checks[rating] = cb
            rating_row.addWidget(cb)

        rating_row.addStretch()
        evt_layout.addLayout(rating_row)

        # === 상단 Row 3: 태그 검색 ===
        search_row = QHBoxLayout()
        search_row.setSpacing(6)

        search_label = QLabel("🔍")
        search_label.setStyleSheet(f"font-size: {get_scaled_font_size(14)}px;")
        search_row.addWidget(search_label)

        self.event_search_edit = QLineEdit()
        self.event_search_edit.setPlaceholderText("General 태그 검색 (쉼표로 구분, ~제외)")
        self.event_search_edit.setStyleSheet(f"""
            QLineEdit {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 4px 8px;
                font-size: {get_scaled_font_size(14)}px;
            }}
            QLineEdit:focus {{
                border: 1px solid {DARK_COLORS['accent_blue']};
            }}
        """)
        self.event_search_edit.returnPressed.connect(self._on_event_filter_changed)
        search_row.addWidget(self.event_search_edit, 1)

        search_btn = QPushButton("🔍 검색")
        search_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        search_btn.setFixedWidth(130)
        search_btn.clicked.connect(self._on_event_filter_changed)
        search_row.addWidget(search_btn)

        evt_layout.addLayout(search_row)

        # === 상단 Row 4: 심층 검색 ===
        depth_row = QHBoxLayout()
        depth_row.setSpacing(6)

        self.event_depth_search_edit = QLineEdit()
        self.event_depth_search_edit.setPlaceholderText("심층 검색 (현재 필터 결과에서 추가 검색)")
        self.event_depth_search_edit.setStyleSheet(f"""
            QLineEdit {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                padding: 4px 8px;
                font-size: {get_scaled_font_size(14)}px;
            }}
            QLineEdit:focus {{
                border: 1px solid {DARK_COLORS['warning']};
            }}
        """)
        self.event_depth_search_edit.returnPressed.connect(self._on_event_depth_search)
        depth_row.addWidget(self.event_depth_search_edit, 1)

        depth_search_btn = QPushButton("🔎 심층 검색")
        depth_search_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        depth_search_btn.setFixedWidth(130)
        depth_search_btn.clicked.connect(self._on_event_depth_search)
        depth_row.addWidget(depth_search_btn)

        evt_layout.addLayout(depth_row)

        # === 상단 Row 5: 전체/현재 개수 라벨 + 초기화 버튼들 ===
        info_row = QHBoxLayout()
        info_row.setSpacing(8)

        # 전체 row 라벨
        self.event_total_label = QLabel(f"[전체: {len(self.remote_events)}]")
        self.event_total_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(12)}px;
            }}
        """)
        info_row.addWidget(self.event_total_label)

        # 현재 row 라벨
        self.event_current_label = QLabel("[현재: 0]")
        self.event_current_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['success']};
                font-size: {get_scaled_font_size(12)}px;
            }}
        """)
        info_row.addWidget(self.event_current_label)

        info_row.addStretch()

        depth_reset_btn = QPushButton("↩️ 심층검색 초기화")
        depth_reset_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        depth_reset_btn.clicked.connect(self._on_event_depth_reset)
        info_row.addWidget(depth_reset_btn)

        search_reset_btn = QPushButton("🔄 전체검색 초기화")
        search_reset_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        search_reset_btn.clicked.connect(self._on_event_search_reset)
        info_row.addWidget(search_reset_btn)

        evt_layout.addLayout(info_row)

        # === 중간: 이벤트 리스트 (스크롤 영역) ===
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet(f"""
            QScrollArea {{
                background-color: transparent;
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 6px;
            }}
            QScrollArea > QWidget > QWidget {{
                background-color: transparent;
            }}
        """)

        self.events_list_widget = QWidget()
        self.events_list_layout = QVBoxLayout(self.events_list_widget)
        self.events_list_layout.setSpacing(6)
        self.events_list_layout.setContentsMargins(8, 8, 8, 8)
        self.events_list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        scroll_area.setWidget(self.events_list_widget)
        evt_layout.addWidget(scroll_area, 1)

        # === 하단: 대기열 관리 ===
        # 구분선
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet(f"background-color: {DARK_COLORS['border']};")
        separator.setFixedHeight(1)
        evt_layout.addWidget(separator)

        # 대기열 전체 추가 버튼
        queue_all_btn = QPushButton("📋 현재 검색 결과 모두 대기열로 보내기")
        queue_all_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        queue_all_btn.clicked.connect(self._on_event_queue_all)
        evt_layout.addWidget(queue_all_btn)

        # 또 다른 구분선
        separator2 = QFrame()
        separator2.setFrameShape(QFrame.Shape.HLine)
        separator2.setStyleSheet(f"background-color: {DARK_COLORS['border']};")
        separator2.setFixedHeight(1)
        evt_layout.addWidget(separator2)

        # 대기열 상태 및 자동 생성
        queue_row = QHBoxLayout()
        queue_row.setSpacing(8)

        self.event_queue_count_label = QLabel("남은 대기열: 0")
        self.event_queue_count_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(12)}px;
            }}
        """)
        queue_row.addWidget(self.event_queue_count_label)

        # 대기열 비우기 버튼
        queue_clear_btn = QPushButton("🗑️ 비우기")
        queue_clear_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['warning']};
                border: 1px solid {DARK_COLORS['warning']};
                border-radius: 4px;
                padding: 4px 12px;
                font-size: {get_scaled_font_size(12)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['warning']};
                color: {DARK_COLORS['bg_primary']};
            }}
        """)
        queue_clear_btn.setToolTip("대기열 모두 비우기")
        queue_clear_btn.clicked.connect(self._on_event_queue_clear)
        queue_row.addWidget(queue_clear_btn)

        queue_row.addStretch()

        self.event_auto_generate_check = QCheckBox("자동 생성")
        self.event_auto_generate_check.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.event_auto_generate_check.stateChanged.connect(self._on_event_auto_generate_changed)
        queue_row.addWidget(self.event_auto_generate_check)

        self.event_generate_btn = QPushButton("▶️ 생성 시작")
        self.event_generate_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.event_generate_btn.setFixedWidth(150)
        self.event_generate_btn.clicked.connect(self._on_event_generate_start)
        queue_row.addWidget(self.event_generate_btn)

        evt_layout.addLayout(queue_row)

        parent_tabs.addTab(evt_widget, "📌 이벤트")

        # 이벤트 대기열 초기화
        self.event_queue = []
        self.event_filtered_ids = set()  # 현재 필터된 이벤트 ID들
        self.event_depth_filters = []  # 심층 검색 필터 스택

        # 초기 리스트 업데이트
        self._update_events_list()

    def _create_instant_wc_subtab(self, parent_tabs: QTabWidget):
        """인스턴트 와일드카드 서브탭 - 이벤트 탭과 유사한 구조"""
        wc_widget = QWidget()
        wc_layout = QVBoxLayout(wc_widget)
        wc_layout.setContentsMargins(8, 8, 8, 8)
        wc_layout.setSpacing(8)

        if not self.instant_wc_module:
            placeholder = QLabel("인스턴트 와일드카드 모듈을 찾을 수 없습니다.")
            placeholder.setStyleSheet(f"color: {DARK_COLORS['text_disabled']};")
            wc_layout.addWidget(placeholder)
            parent_tabs.addTab(wc_widget, "☑️ INST.WC")
            return

        # 와일드카드 메타데이터 (하트 값) 로드
        self._load_wc_metadata()

        # === 상단 Row 1: 타이틀 ===
        title_row = QHBoxLayout()
        wc_info = QLabel("☑️ 인스턴트 와일드카드")
        wc_info.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['accent_blue']};
                font-size: {get_scaled_font_size(14)}px;
                font-weight: bold;
            }}
        """)
        title_row.addWidget(wc_info)
        title_row.addStretch()
        wc_layout.addLayout(title_row)

        # === 상단 Row 2: 파일 선택 콤보박스 ===
        file_row = QHBoxLayout()
        file_row.setSpacing(8)

        file_label = QLabel("파일:")
        file_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(15)}px;")
        file_row.addWidget(file_label)

        self.wc_file_combo = QComboBox()
        self.wc_file_combo.setStyleSheet(DARK_STYLES['compact_combobox'])
        self.wc_file_combo.setMinimumWidth(200)
        self.wc_file_combo.addItem("(전체)")  # 전체 옵션
        # 파일 목록 추가
        if hasattr(self.instant_wc_module, 'instant_wildcard_tree'):
            for file_key in sorted(self.instant_wc_module.instant_wildcard_tree.keys()):
                self.wc_file_combo.addItem(file_key)
        self.wc_file_combo.currentTextChanged.connect(self._on_wc_file_changed)
        file_row.addWidget(self.wc_file_combo)

        file_row.addStretch()
        wc_layout.addLayout(file_row)

        # === 상단 Row 3: 제목 검색 (General 태그 검색) ===
        search_row = QHBoxLayout()
        search_row.setSpacing(8)

        search_label = QLabel("제목 검색:")
        search_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(15)}px;")
        search_row.addWidget(search_label)

        self.wc_search_input = QLineEdit()
        self.wc_search_input.setStyleSheet(DARK_STYLES['compact_lineedit'])
        self.wc_search_input.setPlaceholderText("와일드카드 키 이름으로 검색...")
        self.wc_search_input.returnPressed.connect(self._on_wc_search)
        self.wc_search_input.setProperty("autocomplete_ignore", True)
        search_row.addWidget(self.wc_search_input)

        wc_search_btn = QPushButton("🔍 검색")
        wc_search_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        wc_search_btn.setFixedWidth(130)
        wc_search_btn.clicked.connect(self._on_wc_search)
        search_row.addWidget(wc_search_btn)

        wc_layout.addLayout(search_row)

        # === 상단 Row 4: 심층 검색 (태그에서 검색) ===
        depth_row = QHBoxLayout()
        depth_row.setSpacing(8)

        depth_label = QLabel("태그 검색:")
        depth_label.setStyleSheet(f"color: {DARK_COLORS['text_primary']}; font-size: {get_scaled_font_size(15)}px;")
        depth_row.addWidget(depth_label)

        self.wc_depth_input = QLineEdit()
        self.wc_depth_input.setStyleSheet(DARK_STYLES['compact_lineedit'])
        self.wc_depth_input.setPlaceholderText("와일드카드 값에서 태그 검색...")
        self.wc_depth_input.setProperty("autocomplete_ignore", True)
        self.wc_depth_input.returnPressed.connect(self._on_wc_depth_search)
        depth_row.addWidget(self.wc_depth_input)

        wc_depth_btn = QPushButton("🔎 태그검색")
        wc_depth_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        wc_depth_btn.setFixedWidth(130)
        wc_depth_btn.clicked.connect(self._on_wc_depth_search)
        depth_row.addWidget(wc_depth_btn)

        wc_layout.addLayout(depth_row)

        # === 상단 Row 5: 정보 표시 및 초기화 버튼 ===
        info_row = QHBoxLayout()
        info_row.setSpacing(8)

        self.wc_total_label = QLabel("전체: 0")
        self.wc_total_label.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(12)}px;")
        info_row.addWidget(self.wc_total_label)

        self.wc_current_label = QLabel("현재: 0")
        self.wc_current_label.setStyleSheet(f"color: {DARK_COLORS['text_secondary']}; font-size: {get_scaled_font_size(12)}px;")
        info_row.addWidget(self.wc_current_label)

        info_row.addStretch()

        depth_reset_btn = QPushButton("↩️ 태그검색 초기화")
        depth_reset_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        depth_reset_btn.clicked.connect(self._on_wc_depth_reset)
        info_row.addWidget(depth_reset_btn)

        search_reset_btn = QPushButton("🔄 전체검색 초기화")
        search_reset_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        search_reset_btn.clicked.connect(self._on_wc_search_reset)
        info_row.addWidget(search_reset_btn)

        wc_layout.addLayout(info_row)

        # === 중간: 와일드카드 리스트 (스크롤 영역) ===
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet(f"""
            QScrollArea {{
                background-color: transparent;
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 6px;
            }}
            QScrollArea > QWidget > QWidget {{
                background-color: transparent;
            }}
        """)

        self.wc_list_widget = QWidget()
        self.wc_list_widget.setStyleSheet("background-color: transparent;")
        self.wc_list_layout = QVBoxLayout(self.wc_list_widget)
        self.wc_list_layout.setContentsMargins(4, 4, 4, 4)
        self.wc_list_layout.setSpacing(6)
        self.wc_list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        scroll_area.setWidget(self.wc_list_widget)
        wc_layout.addWidget(scroll_area, 1)

        # === 하단: 대기열 관리 ===
        # 구분선
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet(f"background-color: {DARK_COLORS['border']};")
        separator.setFixedHeight(1)
        wc_layout.addWidget(separator)

        # 대기열 전체 추가 버튼
        queue_all_btn = QPushButton("📋 현재 검색 결과 모두 대기열로 보내기")
        queue_all_btn.setStyleSheet(DARK_STYLES['secondary_button'])
        queue_all_btn.clicked.connect(self._on_wc_queue_all)
        wc_layout.addWidget(queue_all_btn)

        # 또 다른 구분선
        separator2 = QFrame()
        separator2.setFrameShape(QFrame.Shape.HLine)
        separator2.setStyleSheet(f"background-color: {DARK_COLORS['border']};")
        separator2.setFixedHeight(1)
        wc_layout.addWidget(separator2)

        # 대기열 상태 및 자동 생성
        queue_row = QHBoxLayout()
        queue_row.setSpacing(8)

        self.wc_queue_count_label = QLabel("남은 대기열: 0")
        self.wc_queue_count_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(12)}px;
            }}
        """)
        queue_row.addWidget(self.wc_queue_count_label)

        # 대기열 비우기 버튼
        queue_clear_btn = QPushButton("🗑️ 비우기")
        queue_clear_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['warning']};
                border: 1px solid {DARK_COLORS['warning']};
                border-radius: 4px;
                padding: 4px 12px;
                font-size: {get_scaled_font_size(12)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['warning']};
                color: {DARK_COLORS['bg_primary']};
            }}
        """)
        queue_clear_btn.setToolTip("대기열 모두 비우기")
        queue_clear_btn.clicked.connect(self._on_wc_queue_clear)
        queue_row.addWidget(queue_clear_btn)

        queue_row.addStretch()

        self.wc_auto_generate_check = QCheckBox("자동 생성")
        self.wc_auto_generate_check.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.wc_auto_generate_check.stateChanged.connect(self._on_wc_auto_generate_changed)
        queue_row.addWidget(self.wc_auto_generate_check)

        self.wc_generate_btn = QPushButton("▶️ 생성 시작")
        self.wc_generate_btn.setStyleSheet(DARK_STYLES['primary_button'])
        self.wc_generate_btn.setFixedWidth(150)
        self.wc_generate_btn.clicked.connect(self._on_wc_generate_start)
        queue_row.addWidget(self.wc_generate_btn)

        wc_layout.addLayout(queue_row)

        parent_tabs.addTab(wc_widget, "☑️ INST.WC")

        # 와일드카드 대기열 초기화
        self.wc_queue = []  # [(file_key, item_key), ...]
        self.wc_depth_filters = []  # 심층 검색 필터 스택

        # 초기 리스트 업데이트
        self._update_wc_list()

    def _sync_preset_combo(self):
        """프리셋 콤보박스 동기화 (*randomized 제외)"""
        if not self.preset_module or not hasattr(self.preset_module, 'preset_combo'):
            return

        src_combo = self.preset_module.preset_combo
        self.remote_preset_combo.blockSignals(True)
        self.remote_preset_combo.clear()

        for i in range(src_combo.count()):
            item_text = src_combo.itemText(i)
            # *randomized는 즐겨찾기 시스템에서 제외
            if item_text == "*randomized":
                continue
            self.remote_preset_combo.addItem(item_text)

        self.remote_preset_combo.setCurrentText(src_combo.currentText())
        self.remote_preset_combo.blockSignals(False)

    def _on_remote_preset_changed(self, text: str):
        """리모트에서 프리셋 변경 시 원본 모듈에 반영"""
        if not self.preset_module or not hasattr(self.preset_module, 'preset_combo'):
            return

        self.preset_module.preset_combo.setCurrentText(text)

        # 표시 업데이트
        QTimer.singleShot(100, self._update_preset_display)
        QTimer.singleShot(150, self._update_current_preset_ui)

    def _update_preset_display(self):
        """프리셋 내용 표시 업데이트 (프리셋 변경 시 호출)"""
        if not self.preset_module:
            return

        self._sync_in_progress = True

        # 선행 프롬프트 동기화
        if hasattr(self, 'remote_pre_edit') and hasattr(self.preset_module, 'pre_textedit') and self.preset_module.pre_textedit:
            self.remote_pre_edit.setPlainText(self.preset_module.pre_textedit.toPlainText())

        # 후행 프롬프트 동기화
        if hasattr(self, 'remote_post_edit') and hasattr(self.preset_module, 'post_textedit') and self.preset_module.post_textedit:
            self.remote_post_edit.setPlainText(self.preset_module.post_textedit.toPlainText())

        # 자동 숨김 프롬프트 동기화
        if hasattr(self, 'remote_auto_hide_edit') and hasattr(self.preset_module, 'auto_hide_textedit') and self.preset_module.auto_hide_textedit:
            self.remote_auto_hide_edit.setPlainText(self.preset_module.auto_hide_textedit.toPlainText())

        # 체크박스 동기화
        if hasattr(self, 'remote_preprocessing_checkboxes') and hasattr(self.preset_module, 'preprocessing_checkboxes'):
            for text, remote_cb in self.remote_preprocessing_checkboxes.items():
                if text in self.preset_module.preprocessing_checkboxes:
                    remote_cb.setChecked(self.preset_module.preprocessing_checkboxes[text].isChecked())

        self._sync_in_progress = False

    def resizeEvent(self, event):
        """창 크기 변경 시 그리드 업데이트"""
        super().resizeEvent(event)
        # 창 크기 변경 시 프리셋 즐겨찾기 그리드 다시 계산
        if hasattr(self, 'favorites_grid_layout'):
            QTimer.singleShot(100, self._update_favorites_grid)
        # 창 크기 변경 시 캐릭터 레퍼런스 즐겨찾기 그리드 다시 계산
        if hasattr(self, 'char_ref_favorites_grid_layout'):
            QTimer.singleShot(150, self._update_char_ref_favorites_grid)

    def closeEvent(self, event):
        """창 닫힘 이벤트"""
        self.window_closed.emit()
        event.accept()

    # ==================== 🆕 이벤트 관련 메서드들 ====================

    def _load_remote_events(self):
        """저장된 이벤트 목록 로드"""
        if REMOTE_EVENTS_JSON.exists():
            try:
                with open(REMOTE_EVENTS_JSON, 'r', encoding='utf-8') as f:
                    self.remote_events = json.load(f)
                print(f"✅ 리모트 이벤트 {len(self.remote_events)}개 로드")
            except Exception as e:
                print(f"⚠️ 리모트 이벤트 로드 실패: {e}")
                self.remote_events = []
        else:
            self.remote_events = []

    def _save_remote_events(self):
        """이벤트 목록 저장"""
        try:
            with open(REMOTE_EVENTS_JSON, 'w', encoding='utf-8') as f:
                json.dump(self.remote_events, f, ensure_ascii=False, indent=2)
            print(f"✅ 리모트 이벤트 {len(self.remote_events)}개 저장")
        except Exception as e:
            print(f"⚠️ 리모트 이벤트 저장 실패: {e}")

    def add_remote_event(self, history_item):
        """HistoryItem을 이벤트로 추가

        Args:
            history_item: HistoryItem 객체 (source_row, thumbnail 등 포함)
        """
        import time
        import uuid

        # source_row가 없으면 무시
        if history_item.source_row is None or history_item.source_row.empty:
            self._show_warning("알림", "source_row가 없는 이미지는 이벤트로 저장할 수 없습니다.")
            return

        # 고유 ID 생성
        event_id = str(uuid.uuid4())[:8]
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

        # source_row를 딕셔너리로 변환 (JSON 저장 가능하도록)
        source_row_dict = history_item.source_row.to_dict()

        # 썸네일 저장
        thumb_filename = f"{event_id}.png"
        thumb_path = REMOTE_EVENTS_THUMBS_DIR / thumb_filename

        try:
            # QPixmap을 PIL Image로 변환하여 저장
            if history_item.thumbnail and not history_item.thumbnail.isNull():
                qimage = history_item.thumbnail.toImage()
                buffer = qimage.bits().asstring(qimage.sizeInBytes())

                # QImage 포맷에 따라 PIL 모드 결정
                if qimage.format() == QImage.Format.Format_RGBA8888:
                    pil_mode = "RGBA"
                    raw_mode = "RGBA"
                elif qimage.format() == QImage.Format.Format_RGB32:
                    pil_mode = "RGBA"
                    raw_mode = "BGRA"
                else:
                    # 안전하게 RGB32로 변환
                    qimage = qimage.convertToFormat(QImage.Format.Format_RGB32)
                    buffer = qimage.bits().asstring(qimage.sizeInBytes())
                    pil_mode = "RGBA"
                    raw_mode = "BGRA"

                pil_image = Image.frombytes(
                    pil_mode,
                    (qimage.width(), qimage.height()),
                    buffer,
                    "raw",
                    raw_mode
                )
                # 썸네일 크기로 리사이즈
                pil_image.thumbnail((EVENT_THUMB_WIDTH, EVENT_THUMB_HEIGHT), Image.Resampling.LANCZOS)
                pil_image.save(str(thumb_path), "PNG")
        except Exception as e:
            print(f"⚠️ 썸네일 저장 실패: {e}")
            thumb_filename = ""

        # 이벤트 이름 생성 (general 태그의 앞부분 사용)
        general_tags = source_row_dict.get('general', '')
        if isinstance(general_tags, str) and general_tags:
            # 첫 3개 태그만 사용
            tags_list = [t.strip() for t in general_tags.split(',')[:3]]
            event_name = ', '.join(tags_list)
            if len(event_name) > 30:
                event_name = event_name[:27] + "..."
        else:
            event_name = f"이벤트 {event_id}"

        # 🆕 중복 체크: 동일한 general 값을 가진 이벤트가 있는지 확인
        new_general = source_row_dict.get('general', '')
        for existing_evt in self.remote_events:
            existing_general = existing_evt.get("source_row", {}).get("general", "")
            if existing_general == new_general and new_general:
                self._show_warning("알림", "동일한 General 태그를 가진 이벤트가 이미 존재합니다.")
                return

        # 이벤트 데이터 생성
        event_data = {
            "id": event_id,
            "name": event_name,
            "source_row": source_row_dict,
            "thumbnail": thumb_filename,
            "created_at": timestamp,
            "heart": 0  # 🆕 하트(우선순위) 초기값
        }

        # 목록에 추가 (최신이 위로)
        self.remote_events.insert(0, event_data)

        # 저장
        self._save_remote_events()

        # UI 업데이트
        self._update_events_list()

        print(f"✅ 리모트 이벤트 추가: {event_name}")

    def _update_events_list(self):
        """🆕 이벤트 리스트 업데이트 (필터링 및 정렬 적용)"""
        import re

        # 기존 위젯 제거
        while self.events_list_layout.count():
            item = self.events_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 개수 라벨 업데이트
        if hasattr(self, 'event_total_label'):
            self.event_total_label.setText(f"[전체: {len(self.remote_events)}]")

        if not self.remote_events:
            empty_label = QLabel("저장된 이벤트가 없습니다.\n이미지 우클릭 → '리모트에 이벤트 저장'으로 추가하세요.")
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_label.setStyleSheet(f"""
                QLabel {{
                    color: {DARK_COLORS['text_disabled']};
                    font-size: {get_scaled_font_size(12)}px;
                    padding: 40px;
                }}
            """)
            self.events_list_layout.addWidget(empty_label)
            if hasattr(self, 'event_current_label'):
                self.event_current_label.setText("[현재: 0]")
            self.event_filtered_ids = set()
            return

        # 필터링: rating
        enabled_ratings = set()
        if hasattr(self, 'event_rating_checks'):
            for rating, cb in self.event_rating_checks.items():
                if cb.isChecked():
                    enabled_ratings.add(rating)
        else:
            enabled_ratings = {"g", "s", "q", "e"}

        # 필터링: 태그 검색
        search_query = ""
        if hasattr(self, 'event_search_edit'):
            search_query = self.event_search_edit.text().strip()

        # 필터 적용
        filtered_events = []
        for evt in self.remote_events:
            # Rating 필터
            evt_rating = evt.get("source_row", {}).get("rating", "g")
            if evt_rating not in enabled_ratings:
                continue

            # 태그 검색 필터
            if search_query:
                general_text = evt.get("source_row", {}).get("general", "").lower()
                keywords = [k.strip().lower() for k in search_query.split(',') if k.strip()]

                match = True
                for kw in keywords:
                    if kw.startswith('~'):
                        # 제외 키워드
                        exclude_kw = kw[1:]
                        if exclude_kw and exclude_kw in general_text:
                            match = False
                            break
                    else:
                        # 포함 키워드
                        if kw not in general_text:
                            match = False
                            break

                if not match:
                    continue

            # 심층 검색 필터 적용
            if hasattr(self, 'event_depth_filters') and self.event_depth_filters:
                general_text = evt.get("source_row", {}).get("general", "").lower()
                depth_match = True
                for depth_query in self.event_depth_filters:
                    depth_keywords = [k.strip().lower() for k in depth_query.split(',') if k.strip()]
                    for kw in depth_keywords:
                        if kw.startswith('~'):
                            exclude_kw = kw[1:]
                            if exclude_kw and exclude_kw in general_text:
                                depth_match = False
                                break
                        else:
                            if kw not in general_text:
                                depth_match = False
                                break
                    if not depth_match:
                        break
                if not depth_match:
                    continue

            filtered_events.append(evt)

        # 정렬: heart(우선순위) 기준 내림차순
        filtered_events.sort(key=lambda x: x.get("heart", 0), reverse=True)

        # 필터된 ID 저장
        self.event_filtered_ids = {evt.get("id") for evt in filtered_events}

        # 필터 결과 표시
        if hasattr(self, 'event_current_label'):
            self.event_current_label.setText(f"[현재: {len(filtered_events)}]")

        if not filtered_events:
            empty_label = QLabel("필터 조건에 맞는 이벤트가 없습니다.")
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_label.setStyleSheet(f"""
                QLabel {{
                    color: {DARK_COLORS['text_disabled']};
                    font-size: {get_scaled_font_size(12)}px;
                    padding: 20px;
                }}
            """)
            self.events_list_layout.addWidget(empty_label)
            return

        # 리스트에 아이템 추가
        for evt in filtered_events:
            item_widget = EventItemWidget(evt, parent=self.events_list_widget)

            # 시그널 연결
            item_widget.instant_generate_requested.connect(self._on_event_instant_generate)
            item_widget.add_to_queue_requested.connect(self._on_event_add_to_queue)
            item_widget.delete_requested.connect(self._delete_event)
            item_widget.edit_requested.connect(self._on_event_edit_save)
            item_widget.heart_changed.connect(self._on_event_heart_changed)
            item_widget.rating_changed.connect(self._on_event_rating_changed)

            self.events_list_layout.addWidget(item_widget)

        # 하단에 spacer 추가
        self.events_list_layout.addStretch()

    def _on_event_filter_changed(self):
        """필터 변경 시 리스트 업데이트"""
        self._update_events_list()

    def _on_event_depth_search(self):
        """심층 검색 실행"""
        if not hasattr(self, 'event_depth_search_edit'):
            return

        depth_query = self.event_depth_search_edit.text().strip()
        if not depth_query:
            return

        if not hasattr(self, 'event_depth_filters'):
            self.event_depth_filters = []

        self.event_depth_filters.append(depth_query)
        self.event_depth_search_edit.clear()
        self._update_events_list()
        print(f"✅ 심층 검색 추가: {depth_query}")

    def _on_event_depth_reset(self):
        """심층 검색 초기화"""
        if hasattr(self, 'event_depth_filters'):
            self.event_depth_filters = []
        self._update_events_list()
        print("✅ 심층 검색 초기화")

    def _on_event_search_reset(self):
        """전체 검색 초기화"""
        if hasattr(self, 'event_search_edit'):
            self.event_search_edit.clear()
        if hasattr(self, 'event_depth_search_edit'):
            self.event_depth_search_edit.clear()
        if hasattr(self, 'event_depth_filters'):
            self.event_depth_filters = []
        if hasattr(self, 'event_rating_checks'):
            for cb in self.event_rating_checks.values():
                cb.setChecked(True)
        self._update_events_list()
        print("✅ 전체 검색 초기화")

    def _on_event_instant_generate(self, event_id: str):
        """이벤트 즉시 생성"""
        import pandas as pd

        target_event = None
        for evt in self.remote_events:
            if evt.get("id") == event_id:
                target_event = evt
                break

        if not target_event:
            return

        source_row_dict = target_event.get("source_row", {})
        source_row = pd.Series(source_row_dict)

        if self.parent_app and hasattr(self.parent_app, 'on_generate_with_image_requested'):
            # on_generate_with_image_requested 사용
            self.parent_app.on_generate_with_image_requested(source_row_dict)
            print(f"✅ 이벤트 즉시 생성: {target_event.get('name', event_id)}")
        elif self.parent_app and hasattr(self.parent_app, 'on_instant_generation_requested'):
            self.parent_app.on_instant_generation_requested(source_row)
            print(f"✅ 이벤트 즉시 생성: {target_event.get('name', event_id)}")

    def _on_event_add_to_queue(self, event_id: str):
        """이벤트를 대기열에 추가"""
        if not hasattr(self, 'event_queue'):
            self.event_queue = []

        # 중복 방지
        if event_id not in self.event_queue:
            self.event_queue.append(event_id)
            self._update_event_queue_label()
            print(f"✅ 대기열에 추가: {event_id}")

    def _on_event_edit_save(self, event_id: str):
        """이벤트 수정 저장"""
        # EventItemWidget에서 수정된 general 텍스트 가져오기
        for i in range(self.events_list_layout.count()):
            item = self.events_list_layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                if isinstance(widget, EventItemWidget) and widget.event_id == event_id:
                    new_general = widget.get_general_text()

                    # 이벤트 데이터 업데이트
                    for evt in self.remote_events:
                        if evt.get("id") == event_id:
                            evt["source_row"]["general"] = new_general
                            break

                    self._save_remote_events()
                    print(f"✅ 이벤트 수정 저장: {event_id}")
                    break

    def _on_event_heart_changed(self, event_id: str, new_value: int):
        """하트(우선순위) 변경"""
        for evt in self.remote_events:
            if evt.get("id") == event_id:
                evt["heart"] = new_value
                break

        self._save_remote_events()
        # 정렬이 바뀔 수 있으므로 리스트 업데이트
        QTimer.singleShot(100, self._update_events_list)

    def _on_event_rating_changed(self, event_id: str, new_rating: str):
        """Rating 변경"""
        for evt in self.remote_events:
            if evt.get("id") == event_id:
                evt["source_row"]["rating"] = new_rating
                break

        self._save_remote_events()

    def _on_event_queue_all(self):
        """현재 필터된 모든 이벤트를 대기열에 추가"""
        if not hasattr(self, 'event_filtered_ids') or not self.event_filtered_ids:
            self._show_warning("알림", "추가할 이벤트가 없습니다.")
            return

        if not hasattr(self, 'event_queue'):
            self.event_queue = []

        added_count = 0
        for event_id in self.event_filtered_ids:
            if event_id not in self.event_queue:
                self.event_queue.append(event_id)
                added_count += 1

        self._update_event_queue_label()
        print(f"✅ {added_count}개 이벤트를 대기열에 추가")

    def _update_event_queue_label(self):
        """대기열 개수 라벨 업데이트"""
        if hasattr(self, 'event_queue_count_label') and hasattr(self, 'event_queue'):
            self.event_queue_count_label.setText(f"남은 대기열: {len(self.event_queue)}")

    def _on_event_auto_generate_changed(self, state):
        """자동 생성 체크박스 변경"""
        if state == Qt.CheckState.Checked.value:
            print("✅ 자동 생성 활성화")
        else:
            print("✅ 자동 생성 비활성화")

    def _on_event_queue_clear(self):
        """대기열 비우기"""
        if not hasattr(self, 'event_queue') or not self.event_queue:
            return

        self.event_queue.clear()
        self._update_event_queue_label()

    def _on_event_generate_start(self):
        """생성 시작 버튼 클릭"""
        if not hasattr(self, 'event_queue') or not self.event_queue:
            self._show_warning("알림", "대기열이 비어 있습니다.")
            return

        # 자동 생성이 활성화되어 있으면 플래그 설정
        if (hasattr(self, 'event_auto_generate_check') and
            self.event_auto_generate_check.isChecked()):
            self._event_auto_generate_pending = True

        # 첫 번째 이벤트 실행
        event_id = self.event_queue.pop(0)
        self._update_event_queue_label()
        self._on_event_instant_generate(event_id)

    def _delete_event(self, event_id: str):
        """이벤트 삭제"""
        # 이벤트 찾기 및 삭제
        for i, evt in enumerate(self.remote_events):
            if evt.get("id") == event_id:
                # 썸네일 파일 삭제
                thumb_path = REMOTE_EVENTS_THUMBS_DIR / evt.get("thumbnail", "")
                if thumb_path.exists():
                    try:
                        thumb_path.unlink()
                    except:
                        pass

                # 목록에서 제거
                del self.remote_events[i]
                break

        # 대기열에서도 제거
        if hasattr(self, 'event_queue') and event_id in self.event_queue:
            self.event_queue.remove(event_id)
            self._update_event_queue_label()

        # 저장 및 UI 업데이트
        self._save_remote_events()
        self._update_events_list()
        print(f"✅ 이벤트 삭제: {event_id}")

    # ==================== 🆕 인스턴트 와일드카드 관련 메서드들 ====================

    def _get_wc_module(self):
        """instant_wildcard_module 가져오기"""
        return self.instant_wc_module

    def _update_wc_list(self):
        """와일드카드 리스트 업데이트"""
        # 기존 위젯 제거
        while self.wc_list_layout.count():
            item = self.wc_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 와일드카드 모듈에서 데이터 가져오기
        wc_module = self._get_wc_module()
        if not wc_module:
            empty_label = QLabel("와일드카드 모듈을 찾을 수 없습니다.")
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_label.setStyleSheet(f"""
                QLabel {{
                    color: {DARK_COLORS['text_disabled']};
                    font-size: {get_scaled_font_size(12)}px;
                    padding: 40px;
                }}
            """)
            self.wc_list_layout.addWidget(empty_label)
            return

        wc_tree = wc_module.instant_wildcard_tree

        # 전체 개수 라벨 업데이트
        total_items = sum(len(items) for items in wc_tree.values())
        if hasattr(self, 'wc_total_label'):
            self.wc_total_label.setText(f"[전체: {total_items}]")

        if not wc_tree:
            empty_label = QLabel("저장된 와일드카드가 없습니다.\n텍스트 선택 후 우클릭 → '와일드카드 추가'로 추가하세요.")
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_label.setStyleSheet(f"""
                QLabel {{
                    color: {DARK_COLORS['text_disabled']};
                    font-size: {get_scaled_font_size(12)}px;
                    padding: 40px;
                }}
            """)
            self.wc_list_layout.addWidget(empty_label)
            if hasattr(self, 'wc_current_label'):
                self.wc_current_label.setText("[현재: 0]")
            return

        # 파일 콤보 선택 확인
        selected_file = None
        if hasattr(self, 'wc_file_combo'):
            selected_text = self.wc_file_combo.currentText()
            if selected_text and selected_text != "(전체)":
                selected_file = selected_text

        # 제목 검색 쿼리
        title_query = ""
        if hasattr(self, 'wc_search_input'):
            title_query = self.wc_search_input.text().strip().lower()

        # 필터링된 아이템 수집
        filtered_items = []  # [(file_key, item_key, value, heart), ...]

        for file_key, items in wc_tree.items():
            # 파일 필터
            if selected_file and file_key != selected_file:
                continue

            for item_key, value in items.items():
                # 제목(키) 검색 필터
                if title_query:
                    keywords = [k.strip() for k in title_query.split(',') if k.strip()]
                    match = True
                    for kw in keywords:
                        if kw.startswith('~'):
                            exclude_kw = kw[1:].lower()
                            if exclude_kw and exclude_kw in item_key.lower():
                                match = False
                                break
                        else:
                            if kw.lower() not in item_key.lower():
                                match = False
                                break
                    if not match:
                        continue

                # 심층 검색(태그) 필터 적용
                if hasattr(self, 'wc_depth_filters') and self.wc_depth_filters:
                    depth_match = True
                    for depth_query in self.wc_depth_filters:
                        depth_keywords = [k.strip() for k in depth_query.split(',') if k.strip()]
                        for kw in depth_keywords:
                            if kw.startswith('~'):
                                exclude_kw = kw[1:].lower()
                                if exclude_kw and exclude_kw in value.lower():
                                    depth_match = False
                                    break
                            else:
                                if kw.lower() not in value.lower():
                                    depth_match = False
                                    break
                        if not depth_match:
                            break
                    if not depth_match:
                        continue

                # 하트 값 가져오기
                heart = self._get_wc_heart(file_key, item_key)
                filtered_items.append((file_key, item_key, value, heart))

        # 정렬: heart 기준 내림차순
        filtered_items.sort(key=lambda x: x[3], reverse=True)

        # 현재 개수 라벨 업데이트
        if hasattr(self, 'wc_current_label'):
            self.wc_current_label.setText(f"[현재: {len(filtered_items)}]")

        if not filtered_items:
            empty_label = QLabel("필터 조건에 맞는 와일드카드가 없습니다.")
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_label.setStyleSheet(f"""
                QLabel {{
                    color: {DARK_COLORS['text_disabled']};
                    font-size: {get_scaled_font_size(12)}px;
                    padding: 20px;
                }}
            """)
            self.wc_list_layout.addWidget(empty_label)
            return

        # 리스트에 아이템 추가
        for file_key, item_key, value, heart in filtered_items:
            item_data = {"value": value, "heart": heart}
            item_widget = WildcardItemWidget(file_key, item_key, item_data, parent=self.wc_list_widget)

            # 시그널 연결
            item_widget.instant_generate_requested.connect(self._on_wc_instant_generate)
            item_widget.add_to_queue_requested.connect(self._on_wc_add_to_queue)
            item_widget.delete_requested.connect(self._on_wc_delete)
            item_widget.edit_requested.connect(self._on_wc_edit_save)
            item_widget.heart_changed.connect(self._on_wc_heart_changed)
            item_widget.clip_requested.connect(self._on_wc_clip_image)

            self.wc_list_layout.addWidget(item_widget)

        # 하단에 spacer 추가
        self.wc_list_layout.addStretch()

    def _load_wc_metadata(self):
        """와일드카드 메타데이터 로드 (하트 등)"""
        metadata_path = Path("save") / "instant_wildcard" / "wc_metadata.json"
        if metadata_path.exists():
            try:
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    self.wc_metadata = json.load(f)
            except Exception as e:
                print(f"⚠️ WC 메타데이터 로드 실패: {e}")
                self.wc_metadata = {}
        else:
            self.wc_metadata = {}

    def _save_wc_metadata(self):
        """와일드카드 메타데이터 저장"""
        metadata_path = Path("save") / "instant_wildcard" / "wc_metadata.json"
        try:
            metadata_path.parent.mkdir(parents=True, exist_ok=True)
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(self.wc_metadata, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ WC 메타데이터 저장 실패: {e}")

    def _get_wc_heart(self, file_key: str, item_key: str) -> int:
        """와일드카드 아이템의 하트 값 가져오기"""
        if not hasattr(self, 'wc_metadata'):
            self._load_wc_metadata()
        key = f"{file_key}::{item_key}"
        return self.wc_metadata.get(key, {}).get("heart", 0)

    def _set_wc_heart(self, file_key: str, item_key: str, value: int):
        """와일드카드 아이템의 하트 값 설정"""
        if not hasattr(self, 'wc_metadata'):
            self._load_wc_metadata()
        key = f"{file_key}::{item_key}"
        if key not in self.wc_metadata:
            self.wc_metadata[key] = {}
        self.wc_metadata[key]["heart"] = value
        self._save_wc_metadata()

    def _update_wc_file_combo(self):
        """파일 콤보박스 업데이트"""
        if not hasattr(self, 'wc_file_combo'):
            return

        wc_module = self._get_wc_module()
        if not wc_module:
            return

        current_text = self.wc_file_combo.currentText()

        self.wc_file_combo.blockSignals(True)
        self.wc_file_combo.clear()
        self.wc_file_combo.addItem("(전체)")

        for file_key in sorted(wc_module.instant_wildcard_tree.keys()):
            self.wc_file_combo.addItem(file_key)

        # 이전 선택 복원
        idx = self.wc_file_combo.findText(current_text)
        if idx >= 0:
            self.wc_file_combo.setCurrentIndex(idx)

        self.wc_file_combo.blockSignals(False)

    def _on_wc_file_changed(self, text: str):
        """파일 선택 변경 시"""
        self._update_wc_list()

    def _on_wc_search(self):
        """제목 검색 실행"""
        self._update_wc_list()

    def _on_wc_depth_search(self):
        """심층 검색(태그 검색) 실행"""
        if not hasattr(self, 'wc_depth_input'):
            return

        depth_query = self.wc_depth_input.text().strip()
        if not depth_query:
            return

        if not hasattr(self, 'wc_depth_filters'):
            self.wc_depth_filters = []

        self.wc_depth_filters.append(depth_query)
        self.wc_depth_input.clear()
        self._update_wc_list()
        print(f"✅ WC 심층 검색 추가: {depth_query}")

    def _on_wc_depth_reset(self):
        """심층 검색 한단계 되돌리기"""
        if hasattr(self, 'wc_depth_filters') and self.wc_depth_filters:
            removed = self.wc_depth_filters.pop()
            self._update_wc_list()
            print(f"✅ WC 심층 검색 제거: {removed}")

    def _on_wc_search_reset(self):
        """전체검색 초기화"""
        if hasattr(self, 'wc_search_input'):
            self.wc_search_input.clear()
        if hasattr(self, 'wc_depth_input'):
            self.wc_depth_input.clear()
        if hasattr(self, 'wc_depth_filters'):
            self.wc_depth_filters.clear()
        if hasattr(self, 'wc_file_combo'):
            self.wc_file_combo.setCurrentIndex(0)  # (전체)
        self._update_wc_list()
        print("✅ WC 전체 검색 초기화")

    def _on_wc_queue_all(self):
        """현재 필터된 모든 와일드카드를 대기열에 추가"""
        # 현재 표시된 아이템들 수집
        wc_module = self._get_wc_module()
        if not wc_module:
            return

        wc_tree = wc_module.instant_wildcard_tree

        # 파일 필터
        selected_file = None
        if hasattr(self, 'wc_file_combo'):
            selected_text = self.wc_file_combo.currentText()
            if selected_text and selected_text != "(전체)":
                selected_file = selected_text

        # 제목 검색 쿼리
        title_query = ""
        if hasattr(self, 'wc_search_input'):
            title_query = self.wc_search_input.text().strip().lower()

        added_count = 0
        for file_key, items in wc_tree.items():
            if selected_file and file_key != selected_file:
                continue

            for item_key, value in items.items():
                # 제목 검색 필터
                if title_query:
                    keywords = [k.strip() for k in title_query.split(',') if k.strip()]
                    match = True
                    for kw in keywords:
                        if kw.startswith('~'):
                            exclude_kw = kw[1:].lower()
                            if exclude_kw and exclude_kw in item_key.lower():
                                match = False
                                break
                        else:
                            if kw.lower() not in item_key.lower():
                                match = False
                                break
                    if not match:
                        continue

                # 심층 검색 필터
                if hasattr(self, 'wc_depth_filters') and self.wc_depth_filters:
                    depth_match = True
                    for depth_query in self.wc_depth_filters:
                        depth_keywords = [k.strip() for k in depth_query.split(',') if k.strip()]
                        for kw in depth_keywords:
                            if kw.startswith('~'):
                                exclude_kw = kw[1:].lower()
                                if exclude_kw and exclude_kw in value.lower():
                                    depth_match = False
                                    break
                            else:
                                if kw.lower() not in value.lower():
                                    depth_match = False
                                    break
                        if not depth_match:
                            break
                    if not depth_match:
                        continue

                # 대기열에 추가
                queue_item = (file_key, item_key)
                if queue_item not in self.wc_queue:
                    self.wc_queue.append(queue_item)
                    added_count += 1

        self._update_wc_queue_label()
        print(f"✅ {added_count}개 와일드카드를 대기열에 추가")

    def _update_wc_queue_label(self):
        """대기열 개수 라벨 업데이트"""
        if hasattr(self, 'wc_queue_count_label') and hasattr(self, 'wc_queue'):
            self.wc_queue_count_label.setText(f"남은 대기열: {len(self.wc_queue)}")

    def _on_wc_queue_clear(self):
        """대기열 비우기"""
        if hasattr(self, 'wc_queue'):
            self.wc_queue.clear()
            self._update_wc_queue_label()
            print("✅ WC 대기열 비움")

    def _on_wc_auto_generate_changed(self, state):
        """자동 생성 체크박스 변경"""
        if state == Qt.CheckState.Checked.value:
            print("✅ WC 자동 생성 활성화")
        else:
            print("✅ WC 자동 생성 비활성화")

    def _on_wc_generate_start(self):
        """생성 시작 버튼 클릭"""
        if not hasattr(self, 'wc_queue') or not self.wc_queue:
            self._show_warning("알림", "대기열이 비어 있습니다.")
            return

        # 자동 생성이 활성화되어 있으면 플래그 설정
        if (hasattr(self, 'wc_auto_generate_check') and
            self.wc_auto_generate_check.isChecked()):
            self._wc_auto_generate_pending = True

        # 첫 번째 아이템 실행
        file_key, item_key = self.wc_queue.pop(0)
        self._update_wc_queue_label()
        self._on_wc_instant_generate(file_key, item_key)

    def _on_wc_instant_generate(self, file_key: str, item_key: str):
        """와일드카드 즉시 생성"""
        wc_module = self._get_wc_module()
        if not wc_module:
            self._show_warning("오류", "와일드카드 모듈을 찾을 수 없습니다.")
            return

        # 와일드카드 값 가져오기
        wc_tree = wc_module.instant_wildcard_tree
        if file_key not in wc_tree or item_key not in wc_tree[file_key]:
            self._show_warning("오류", f"와일드카드를 찾을 수 없습니다: {file_key}::{item_key}")
            return

        value = wc_tree[file_key][item_key]

        # 가상 row 생성 (이벤트 탭과 동일한 방식)
        source_row_dict = {
            'general': value,
            'character': '',
            'copyright': '',
            'artist': '',
            'meta': '',
            'rating': 'g',
            'score': 0,
            'id': f"wc_{file_key}_{item_key}"
        }

        # parent_app을 통해 생성 요청 (이벤트 탭과 동일한 방식)
        if self.parent_app and hasattr(self.parent_app, 'on_generate_with_image_requested'):
            self.parent_app.on_generate_with_image_requested(source_row_dict)
            print(f"✅ WC 즉시 생성: {file_key}::{item_key}")

            # 썸네일이 없으면 생성 완료 후 저장하도록 플래그 설정
            thumb_path = Path("save") / "instant_wildcard" / "images" / file_key / f"{item_key}.png"
            if not thumb_path.exists():
                self._pending_wc_thumbnail = {
                    'file_key': file_key,
                    'item_key': item_key
                }
        elif self.parent_app and hasattr(self.parent_app, 'on_instant_generation_requested'):
            import pandas as pd
            source_row = pd.Series(source_row_dict)
            self.parent_app.on_instant_generation_requested(source_row)
            print(f"✅ WC 즉시 생성: {file_key}::{item_key}")

    def _on_wc_add_to_queue(self, file_key: str, item_key: str):
        """대기열에 추가"""
        if not hasattr(self, 'wc_queue'):
            self.wc_queue = []

        queue_item = (file_key, item_key)
        if queue_item not in self.wc_queue:
            self.wc_queue.append(queue_item)
            self._update_wc_queue_label()
            print(f"✅ WC 대기열 추가: {file_key}::{item_key}")
        else:
            print(f"⚠️ 이미 대기열에 있음: {file_key}::{item_key}")

    def _on_wc_delete(self, file_key: str, item_key: str):
        """와일드카드 삭제"""
        wc_module = self._get_wc_module()
        if not wc_module:
            return

        # 와일드카드 모듈에서 삭제
        if hasattr(wc_module, 'delete_wildcard'):
            wc_module.delete_wildcard(file_key, item_key)

        # 썸네일 삭제
        thumb_path = Path("save") / "instant_wildcard" / "images" / file_key / f"{item_key}.png"
        if thumb_path.exists():
            try:
                thumb_path.unlink()
            except:
                pass

        # 메타데이터에서 삭제
        if hasattr(self, 'wc_metadata'):
            key = f"{file_key}::{item_key}"
            if key in self.wc_metadata:
                del self.wc_metadata[key]
                self._save_wc_metadata()

        # 대기열에서도 제거
        if hasattr(self, 'wc_queue'):
            queue_item = (file_key, item_key)
            if queue_item in self.wc_queue:
                self.wc_queue.remove(queue_item)
                self._update_wc_queue_label()

        # UI 업데이트
        self._update_wc_file_combo()
        self._update_wc_list()
        print(f"✅ 와일드카드 삭제: {file_key}::{item_key}")

    def _on_wc_edit_save(self, file_key: str, item_key: str, new_value: str):
        """와일드카드 값 수정"""
        wc_module = self._get_wc_module()
        if not wc_module:
            return

        # 와일드카드 모듈에서 업데이트
        if hasattr(wc_module, 'update_wildcard_value'):
            wc_module.update_wildcard_value(file_key, item_key, new_value)
            print(f"✅ 와일드카드 수정: {file_key}::{item_key}")

    def _on_wc_heart_changed(self, file_key: str, item_key: str, new_value: int):
        """하트 값 변경"""
        self._set_wc_heart(file_key, item_key, new_value)
        print(f"✅ WC 하트 변경: {file_key}::{item_key} = {new_value}")

    def _on_wc_clip_image(self, file_key: str, item_key: str):
        """클립보드 이미지를 썸네일로 할당"""
        from PyQt6.QtWidgets import QApplication, QMessageBox

        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData()

        if not mime_data.hasImage():
            self._show_warning("알림", "클립보드에 이미지가 없습니다.")
            return

        # 이미지 가져오기
        image = clipboard.image()
        if image.isNull():
            self._show_warning("알림", "클립보드 이미지를 읽을 수 없습니다.")
            return

        # 저장 경로
        thumb_dir = Path("save") / "instant_wildcard" / "images" / file_key
        thumb_path = thumb_dir / f"{item_key}.png"

        # 기존 파일이 있으면 덮어쓰기 확인
        if thumb_path.exists():
            reply = QMessageBox.question(
                self,
                "확인",
                f"'{item_key}'의 썸네일이 이미 존재합니다.\n덮어쓰시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        # 디렉토리 생성
        thumb_dir.mkdir(parents=True, exist_ok=True)

        # QImage를 QPixmap으로 변환 후 크기 조정
        pixmap = QPixmap.fromImage(image)

        # 512px로 리사이즈 (가로/세로 중 큰 쪽 기준)
        max_size = 512
        if pixmap.width() > max_size or pixmap.height() > max_size:
            pixmap = pixmap.scaled(
                max_size, max_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )

        # 저장
        if pixmap.save(str(thumb_path), "PNG"):
            print(f"✅ WC 썸네일 저장: {thumb_path}")
            # 리스트 업데이트
            self._update_wc_list()
        else:
            self._show_warning("오류", "썸네일 저장에 실패했습니다.")
